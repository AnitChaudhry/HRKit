"""Filesystem scanner: walks the workspace and syncs folders to the DB."""
from __future__ import annotations
import os, sqlite3
from collections import deque
from pathlib import Path
from typing import Optional

from . import db as dbmod
from .config import IGNORE_NAMES, IGNORE_PREFIXES, MARKER, TYPES
from .frontmatter import dump as fm_dump
from .frontmatter import parse as fm_parse
from .models import Activity, Folder


MAX_DEPTH = 3  # department -> position -> task


def read_marker(folder: Path) -> Optional[tuple[dict, str]]:
    m = folder / MARKER
    if not m.exists() or not m.is_file():
        return None
    try:
        text = m.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm, body = fm_parse(text)
    if not fm:
        return None
    return fm, body


def write_marker(folder: Path, fm: dict, body: str = "") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MARKER).write_text(fm_dump(fm, body), encoding="utf-8")


def _norm(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/")


def _ignored(name: str) -> bool:
    return name.startswith(IGNORE_PREFIXES) or name in IGNORE_NAMES


def _iter_subdirs(folder: Path):
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if _ignored(entry.name):
                    continue
                yield Path(entry.path)
    except OSError:
        return


def _folder_from_marker(
    path: Path, fm: dict, body: str, parent_id: Optional[int], depth: int
) -> Optional[Folder]:
    ftype = str(fm.get("type", "")).strip()
    if depth == 0:
        ftype = ftype or "workspace"
    elif depth == 1 and ftype not in TYPES:
        ftype = "department"
    elif depth == 2 and ftype not in TYPES:
        ftype = "position"
    elif depth == 3 and ftype not in TYPES:
        ftype = "task"
    if ftype not in TYPES:
        return None

    name = str(fm.get("name") or path.name).strip() or path.name
    status = str(fm.get("status") or "").strip()
    if ftype == "task" and not status:
        status = "applied"
    priority = str(fm.get("priority") or "").strip()
    tags = fm.get("tags") or []
    if isinstance(tags, str):
        tags = [tags] if tags else []

    reserved = {"type", "name", "status", "priority", "tags"}
    metadata = {k: v for k, v in fm.items() if k not in reserved}

    return Folder(
        path=_norm(path),
        parent_id=parent_id,
        type=ftype,
        name=name,
        status=status,
        priority=priority,
        tags=list(tags),
        metadata=metadata,
        body=body,
        created=str(fm.get("created") or ""),
        updated=str(fm.get("updated") or ""),
        closed=str(fm.get("closed") or ""),
    )


def scan(conn: sqlite3.Connection, root: Path, actor: str = "scanner") -> dict:
    root = Path(root).resolve()
    seen: set[str] = set()
    counts = {"added": 0, "updated": 0, "by_type": {"department": 0, "position": 0, "task": 0}}

    # BFS queue of (path, parent_id, depth) so parents exist before children.
    queue: deque[tuple[Path, Optional[int], int]] = deque()

    root_path = _norm(root)
    root_marker = read_marker(root)
    root_parent_id: Optional[int] = None
    if root_marker is not None:
        fm, body = root_marker
        f = _folder_from_marker(root, fm, body, None, depth=0)
        if f is not None:
            existed = dbmod.folder_by_path(conn, f.path) is not None
            root_parent_id = dbmod.upsert_folder(conn, f)
            seen.add(f.path)
            if existed:
                counts["updated"] += 1
            else:
                counts["added"] += 1
                dbmod.log_activity(conn, Activity(
                    folder_id=root_parent_id, action="created",
                    to_value=f.type, actor=actor, note=f.name,
                ))

    for sub in _iter_subdirs(root):
        queue.append((sub, root_parent_id, 1))

    while queue:
        path, parent_id, depth = queue.popleft()
        if depth > MAX_DEPTH:
            continue
        marker = read_marker(path)
        current_id: Optional[int] = None
        if marker is not None:
            fm, body = marker
            f = _folder_from_marker(path, fm, body, parent_id, depth)
            if f is not None:
                existed = dbmod.folder_by_path(conn, f.path) is not None
                current_id = dbmod.upsert_folder(conn, f)
                seen.add(f.path)
                if existed:
                    counts["updated"] += 1
                else:
                    counts["added"] += 1
                    if f.type in counts["by_type"]:
                        pass
                    dbmod.log_activity(conn, Activity(
                        folder_id=current_id, action="created",
                        to_value=f.type, actor=actor, note=f.name,
                    ))
                if f.type in counts["by_type"]:
                    counts["by_type"][f.type] += 1

        if depth < MAX_DEPTH:
            for sub in _iter_subdirs(path):
                queue.append((sub, current_id, depth + 1))

    removed = dbmod.delete_missing(conn, seen)

    return {
        "root": str(root),
        "scanned_at": dbmod.now_iso(),
        "seen": len(seen),
        "added": counts["added"],
        "updated": counts["updated"],
        "removed": removed,
        "by_type": counts["by_type"],
    }
