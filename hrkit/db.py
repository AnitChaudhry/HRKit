from __future__ import annotations
import json, sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import IST
from .models import Activity, Folder

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK(type IN ('workspace','department','position','task')),
  name TEXT NOT NULL,
  status TEXT DEFAULT '',
  priority TEXT DEFAULT '',
  tags TEXT DEFAULT '[]',
  metadata TEXT DEFAULT '{}',
  body TEXT DEFAULT '',
  created TEXT DEFAULT '',
  updated TEXT DEFAULT '',
  closed TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id);
CREATE INDEX IF NOT EXISTS idx_folders_type   ON folders(type);
CREATE INDEX IF NOT EXISTS idx_folders_status ON folders(status);

CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY,
  folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  from_value TEXT DEFAULT '',
  to_value TEXT DEFAULT '',
  actor TEXT DEFAULT 'manual',
  at TEXT NOT NULL,
  note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_activity_folder ON activity(folder_id);
CREATE INDEX IF NOT EXISTS idx_activity_at     ON activity(at DESC);

CREATE TABLE IF NOT EXISTS watches (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  label TEXT DEFAULT '',
  last_scan TEXT DEFAULT '',
  folder_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)

    # Apply HR module migrations (idempotent) and import any legacy hiring
    # folders into the new recruitment_candidate table on first run.
    try:
        from .migration_runner import apply_all
        apply_all(conn)
    except Exception:  # pragma: no cover - migrations should not break startup
        pass
    try:
        from .hiring_migrator import migrate_hiring_folders_to_db
        migrate_hiring_folders_to_db(conn)
    except Exception:  # pragma: no cover
        pass

    return conn


def now_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


# ---- folders ---------------------------------------------------------------
def upsert_folder(conn: sqlite3.Connection, f: Folder) -> int:
    row = conn.execute("SELECT id FROM folders WHERE path=?", (f.path,)).fetchone()
    tags_j = json.dumps(f.tags or [])
    meta_j = json.dumps(f.metadata or {})
    if row:
        conn.execute("""
            UPDATE folders SET parent_id=?, type=?, name=?, status=?, priority=?,
                tags=?, metadata=?, body=?, created=?, updated=?, closed=?
            WHERE id=?
        """, (f.parent_id, f.type, f.name, f.status, f.priority, tags_j, meta_j,
              f.body, f.created, f.updated, f.closed, row["id"]))
        return int(row["id"])
    cur = conn.execute("""
        INSERT INTO folders(path, parent_id, type, name, status, priority,
                            tags, metadata, body, created, updated, closed)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (f.path, f.parent_id, f.type, f.name, f.status, f.priority, tags_j, meta_j,
          f.body, f.created, f.updated, f.closed))
    return int(cur.lastrowid)


def folder_by_path(conn: sqlite3.Connection, path: str) -> Optional[Folder]:
    row = conn.execute("SELECT * FROM folders WHERE path=?", (path,)).fetchone()
    return _to_folder(row) if row else None


def folder_by_id(conn: sqlite3.Connection, fid: int) -> Optional[Folder]:
    row = conn.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone()
    return _to_folder(row) if row else None


def children(conn: sqlite3.Connection, parent_id: Optional[int]) -> list[Folder]:
    if parent_id is None:
        rows = conn.execute(
            "SELECT * FROM folders WHERE parent_id IS NULL ORDER BY name").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM folders WHERE parent_id=? ORDER BY name",
            (parent_id,)).fetchall()
    return [_to_folder(r) for r in rows]


def descendants_by_type(conn: sqlite3.Connection, parent_id: int, typ: str) -> list[Folder]:
    rows = conn.execute("""
        WITH RECURSIVE sub(id) AS (
          SELECT id FROM folders WHERE id=?
          UNION ALL
          SELECT f.id FROM folders f JOIN sub s ON f.parent_id=s.id
        )
        SELECT folders.* FROM folders
        JOIN sub ON folders.id=sub.id
        WHERE folders.type=? AND folders.id!=?
        ORDER BY folders.name
    """, (parent_id, typ, parent_id)).fetchall()
    return [_to_folder(r) for r in rows]


def all_by_type(conn: sqlite3.Connection, typ: str) -> list[Folder]:
    rows = conn.execute("SELECT * FROM folders WHERE type=? ORDER BY name", (typ,)).fetchall()
    return [_to_folder(r) for r in rows]


def delete_missing(conn: sqlite3.Connection, seen_paths: set[str]) -> int:
    existing = {r["path"]: r["id"]
                for r in conn.execute("SELECT id, path FROM folders").fetchall()}
    missing = [fid for p, fid in existing.items() if p not in seen_paths]
    if missing:
        conn.executemany("DELETE FROM folders WHERE id=?", [(m,) for m in missing])
    return len(missing)


# ---- activity --------------------------------------------------------------
def log_activity(conn: sqlite3.Connection, a: Activity) -> int:
    if not a.at:
        a.at = now_iso()
    cur = conn.execute("""
        INSERT INTO activity(folder_id, action, from_value, to_value, actor, at, note)
        VALUES (?,?,?,?,?,?,?)
    """, (a.folder_id, a.action, a.from_value, a.to_value, a.actor, a.at, a.note))
    return int(cur.lastrowid)


def recent_activity(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute("""
        SELECT a.*, f.name AS folder_name, f.type AS folder_type, f.path AS folder_path
        FROM activity a LEFT JOIN folders f ON a.folder_id=f.id
        ORDER BY a.at DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---- helpers ---------------------------------------------------------------
def _to_folder(row: sqlite3.Row) -> Folder:
    return Folder(
        id=row["id"],
        path=row["path"],
        parent_id=row["parent_id"],
        type=row["type"],
        name=row["name"],
        status=row["status"] or "",
        priority=row["priority"] or "",
        tags=json.loads(row["tags"] or "[]"),
        metadata=json.loads(row["metadata"] or "{}"),
        body=row["body"] or "",
        created=row["created"] or "",
        updated=row["updated"] or "",
        closed=row["closed"] or "",
    )


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("""
        INSERT INTO settings(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, value))


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def stats(conn: sqlite3.Connection) -> dict:
    tot = conn.execute("SELECT COUNT(*) AS c FROM folders").fetchone()["c"]
    by_type = {r["type"]: r["c"] for r in conn.execute(
        "SELECT type, COUNT(*) AS c FROM folders GROUP BY type").fetchall()}
    by_status = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) AS c FROM folders WHERE type='task' GROUP BY status").fetchall()}
    return {"total": tot, "by_type": by_type, "by_status": by_status}
