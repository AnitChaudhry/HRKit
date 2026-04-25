"""One-shot importer: legacy ``folders`` task rows -> ``recruitment_candidate``.

The original hiring kanban stored each candidate as a folder of ``type='task'``
under a position folder. The HR pivot keeps folders for attachment storage
but treats ``recruitment_candidate`` as the authoritative table. This module
copies the existing rows over without touching the source data.

Idempotent: a candidate is identified by ``(position_folder_id, name)`` (with
``name`` stored in the destination row). On a repeat run, already-imported
rows are skipped.

Stdlib only.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

_VALID_STATUSES = {
    "applied",
    "screening",
    "interview",
    "offer",
    "hired",
    "rejected",
}


def _safe_json_loads(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except (TypeError, ValueError):
        return {}


def _coerce_status(raw: str) -> str:
    if not raw:
        return "applied"
    s = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if s in _VALID_STATUSES:
        return s
    # common aliases from the legacy kanban
    aliases = {
        "new": "applied",
        "applied_": "applied",
        "screen": "screening",
        "screened": "screening",
        "shortlist": "screening",
        "shortlisted": "screening",
        "interviewing": "interview",
        "interviewed": "interview",
        "offered": "offer",
        "selected": "hired",
        "joined": "hired",
        "declined": "rejected",
        "reject": "rejected",
        "dropped": "rejected",
    }
    return aliases.get(s, "applied")


def _coerce_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def migrate_hiring_folders_to_db(conn: sqlite3.Connection) -> dict:
    """Copy legacy hiring folders into ``recruitment_candidate``.

    Returns
    -------
    dict
        ``{"imported": <int>, "skipped": <int>}`` describing the run. Counts
        are zero when there are no folders or no task-type rows.
    """
    result = {"imported": 0, "skipped": 0}

    # Either side missing -> nothing to do.
    if not _table_exists(conn, "folders"):
        log.info("hiring_migrator: 'folders' table absent; skipping")
        return result
    if not _table_exists(conn, "recruitment_candidate"):
        log.warning(
            "hiring_migrator: 'recruitment_candidate' table absent; "
            "did you run apply_all()? skipping"
        )
        return result

    rows = conn.execute(
        "SELECT id, parent_id, name, status, metadata, created, updated "
        "FROM folders WHERE type='task'"
    ).fetchall()

    for row in rows:
        folder_id = row["id"] if isinstance(row, sqlite3.Row) else row[0]
        parent_id = row["parent_id"] if isinstance(row, sqlite3.Row) else row[1]
        name = (row["name"] if isinstance(row, sqlite3.Row) else row[2]) or ""
        status_raw = (row["status"] if isinstance(row, sqlite3.Row) else row[3]) or ""
        meta_raw = row["metadata"] if isinstance(row, sqlite3.Row) else row[4]
        created = (row["created"] if isinstance(row, sqlite3.Row) else row[5]) or ""
        updated = (row["updated"] if isinstance(row, sqlite3.Row) else row[6]) or ""

        if not name:
            result["skipped"] += 1
            continue

        meta = _safe_json_loads(meta_raw)

        # Idempotency: existing rows are tagged with origin folder id in
        # metadata_json.legacy_folder_id; also fall back to (position, name).
        existing = conn.execute(
            "SELECT id, metadata_json FROM recruitment_candidate "
            "WHERE position_folder_id IS ? AND name = ?",
            (parent_id, name),
        ).fetchall()
        already_imported = False
        for ex in existing:
            ex_meta = _safe_json_loads(
                ex["metadata_json"] if isinstance(ex, sqlite3.Row) else ex[1]
            )
            if ex_meta.get("legacy_folder_id") == folder_id:
                already_imported = True
                break
        if already_imported or existing:
            result["skipped"] += 1
            continue

        candidate_meta = dict(meta)
        candidate_meta.setdefault("legacy_folder_id", folder_id)

        email = str(meta.get("email") or meta.get("contact_email") or "").strip()
        phone = str(meta.get("phone") or meta.get("contact_phone") or "").strip()
        source = str(meta.get("source") or "").strip()
        score = _coerce_int(meta.get("score"), 0)
        recommendation = str(
            meta.get("recommendation") or meta.get("verdict") or ""
        ).strip()
        resume_path = str(
            meta.get("resume_path") or meta.get("resume") or ""
        ).strip()
        applied_at = str(
            meta.get("applied_at") or meta.get("applied") or created or ""
        ).strip()
        evaluated_at = str(
            meta.get("evaluated_at") or meta.get("evaluated") or ""
        ).strip()

        params = (
            parent_id,
            name,
            email,
            phone,
            source,
            _coerce_status(status_raw or str(meta.get("status", ""))),
            score,
            recommendation,
            applied_at or None,
            evaluated_at,
            resume_path,
            json.dumps(candidate_meta),
            created or None,
            updated or None,
        )

        # Build statement so empty timestamp params fall back to defaults.
        cols = [
            "position_folder_id",
            "name",
            "email",
            "phone",
            "source",
            "status",
            "score",
            "recommendation",
            "applied_at",
            "evaluated_at",
            "resume_path",
            "metadata_json",
            "created",
            "updated",
        ]
        # Filter out the timestamp columns whose param is None so the table
        # default fires.
        kept_cols: list[str] = []
        kept_vals: list[Any] = []
        for col, val in zip(cols, params):
            if col in {"applied_at", "created", "updated"} and val is None:
                continue
            kept_cols.append(col)
            kept_vals.append(val)

        placeholders = ", ".join("?" for _ in kept_cols)
        sql = (
            f"INSERT INTO recruitment_candidate ({', '.join(kept_cols)}) "
            f"VALUES ({placeholders})"
        )
        conn.execute(sql, kept_vals)
        result["imported"] += 1

    return result


__all__ = ["migrate_hiring_folders_to_db"]
