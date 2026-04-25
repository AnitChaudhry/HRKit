"""File-based chat conversation persistence.

Each conversation is written to TWO files so a human can browse/grep the
transcript and the app can re-load it losslessly:

    <workspace>/conversations/<id>.md      # frontmatter + readable transcript
    <workspace>/conversations/<id>.json    # raw turns (role, content, attachments)

When a conversation is tied to an employee (``employee_code`` is set), the
files live under that employee's folder instead so the unified per-employee
layout (Phase 1.7) keeps everything about that person in one place:

    <workspace>/employees/<EMP-CODE>/conversations/<id>.{md,json}

Stdlib only.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from hrkit import frontmatter as fm
from hrkit.config import IST
from hrkit import employee_fs

log = logging.getLogger(__name__)

CONVERSATIONS_DIR = "conversations"

_BAD_CHARS = set('<>:"|?*\\/\x00')
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def _safe_id(text: str) -> str:
    cleaned = "".join("_" if c in _BAD_CHARS or ord(c) < 32 else c for c in (text or "").strip())
    cleaned = cleaned.strip(" .")
    if not cleaned or cleaned in (".", ".."):
        raise ValueError(f"invalid conversation id: {text!r}")
    return cleaned[:120]


def _slugify(text: str, fallback: str = "chat") -> str:
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return (s or fallback)[:48]


def _now_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _today_iso() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def conversations_dir(workspace_root: str | Path,
                      employee_code: str | None = None) -> Path:
    """Return the directory conversations are written into."""
    if employee_code:
        return employee_fs.conversations_dir(workspace_root, employee_code)
    return Path(workspace_root) / CONVERSATIONS_DIR


def _paths_for(workspace_root: str | Path, conversation_id: str,
               employee_code: str | None = None) -> tuple[Path, Path]:
    base = conversations_dir(workspace_root, employee_code) / _safe_id(conversation_id)
    return Path(str(base) + ".md"), Path(str(base) + ".json")


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------
def new_conversation_id(seed_message: str = "") -> str:
    """Return a fresh, sortable, human-readable conversation id."""
    suffix = uuid.uuid4().hex[:6]
    slug = _slugify(seed_message, fallback="chat")
    return f"{_today_iso()}-{slug}-{suffix}"


# ---------------------------------------------------------------------------
# Save / load / list
# ---------------------------------------------------------------------------
def _derive_title(messages: list[dict[str, Any]], fallback: str = "Untitled") -> str:
    for m in messages:
        if (m.get("role") or "").lower() == "user":
            content = (m.get("content") or "").strip()
            if content:
                return content[:80]
    return fallback


def _render_transcript(messages: list[dict[str, Any]]) -> str:
    """Pretty markdown transcript of the messages."""
    lines: list[str] = []
    for m in messages:
        role = (m.get("role") or "?").strip().capitalize()
        content = (m.get("content") or "").strip()
        lines.append(f"## {role}")
        if content:
            lines.append("")
            lines.append(content)
        atts = m.get("attachments") or []
        if atts:
            lines.append("")
            lines.append("**Attachments:**")
            for a in atts:
                name = a.get("filename") if isinstance(a, dict) else str(a)
                lines.append(f"- {name}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_conversation(
    *,
    workspace_root: str | Path,
    conversation_id: str,
    messages: list[dict[str, Any]],
    title: str | None = None,
    employee_code: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """Write the .md + .json pair for a conversation. Idempotent on id.

    Returns ``{"id": str, "md_path": str, "json_path": str}``.
    """
    md_path, json_path = _paths_for(workspace_root, conversation_id, employee_code)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    # Preserve the original 'created' timestamp on subsequent saves.
    created = _now_iso()
    if md_path.exists():
        try:
            existing_fm, _ = fm.parse(md_path.read_text(encoding="utf-8"))
            if existing_fm.get("created"):
                created = str(existing_fm["created"])
        except OSError:
            pass

    title = (title or _derive_title(messages)).strip() or "Untitled"
    fm_dict: dict[str, Any] = {
        "type": "conversation",
        "id": conversation_id,
        "title": title,
        "created": created,
        "updated": _now_iso(),
        "turns": len(messages or []),
    }
    if employee_code:
        fm_dict["employee_code"] = employee_code
    if model:
        fm_dict["model"] = model

    body = _render_transcript(messages or [])
    md_path.write_text(fm.dump(fm_dict, body), encoding="utf-8")
    json_path.write_text(
        json.dumps({"id": conversation_id, "messages": messages or []},
                   indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "id": conversation_id,
        "md_path": str(md_path.resolve()),
        "json_path": str(json_path.resolve()),
    }


def load_conversation(
    *,
    workspace_root: str | Path,
    conversation_id: str,
    employee_code: str | None = None,
) -> dict[str, Any] | None:
    """Read a conversation back. Returns ``None`` if not found."""
    md_path, json_path = _paths_for(workspace_root, conversation_id, employee_code)
    if not json_path.exists():
        # Fall back to looking under the global conversations/ dir if an
        # employee_code was supplied but the file isn't there.
        if employee_code:
            return load_conversation(
                workspace_root=workspace_root,
                conversation_id=conversation_id,
                employee_code=None,
            )
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fm_dict: dict[str, Any] = {}
    if md_path.exists():
        try:
            fm_dict, _ = fm.parse(md_path.read_text(encoding="utf-8"))
        except OSError:
            fm_dict = {}
    return {
        "id": conversation_id,
        "title": fm_dict.get("title", ""),
        "created": fm_dict.get("created", ""),
        "updated": fm_dict.get("updated", ""),
        "model": fm_dict.get("model", ""),
        "employee_code": fm_dict.get("employee_code", ""),
        "messages": payload.get("messages") or [],
    }


def list_conversations(
    *,
    workspace_root: str | Path,
    employee_code: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return a metadata list (newest first), capped at ``limit``."""
    folder = conversations_dir(workspace_root, employee_code)
    if not folder.exists():
        return []
    items: list[dict[str, Any]] = []
    for md_path in folder.glob("*.md"):
        try:
            text = md_path.read_text(encoding="utf-8")
            fm_dict, _ = fm.parse(text)
        except OSError:
            continue
        items.append({
            "id": fm_dict.get("id") or md_path.stem,
            "title": fm_dict.get("title", "") or md_path.stem,
            "created": fm_dict.get("created", ""),
            "updated": fm_dict.get("updated", ""),
            "turns": fm_dict.get("turns", 0),
            "model": fm_dict.get("model", ""),
            "employee_code": fm_dict.get("employee_code", "") or (employee_code or ""),
        })
    items.sort(key=lambda i: str(i.get("updated") or i.get("created") or ""), reverse=True)
    return items[:limit]


__all__ = [
    "CONVERSATIONS_DIR",
    "conversations_dir",
    "new_conversation_id",
    "save_conversation",
    "load_conversation",
    "list_conversations",
]
