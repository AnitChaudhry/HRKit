"""Per-employee filesystem layout — the human-browsable mirror.

Every employee gets one folder under ``<workspace>/employees/<EMP-CODE>/``
that consolidates their HR artifacts in one place a person can open in
Explorer / Finder and read directly:

    <workspace>/employees/<EMP-CODE>/
        employee.md            # frontmatter mirror of the DB row
        documents/             # uploaded paperwork (PAN, contracts, ...)
        legal/                 # NDAs, employment contracts, sensitive paper
        conversations/         # AI chat transcripts (.md + .json sidecar)
        memory/                # persistent AI notes about this employee

This module owns:
* path helpers (``employee_dir``, ``documents_dir``, etc.)
* the ``employee.md`` writer — kept in sync whenever an employee is created
  or updated
* a one-shot migration that walks the existing ``document`` table and copies
  files from the legacy ``.getset/uploads/employee/<id>/`` location into the
  new ``employees/<EMP-CODE>/documents/`` layout, returning a plan dict the
  caller can dry-run before applying.

Stdlib only.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from hrkit import frontmatter as fm

log = logging.getLogger(__name__)

EMPLOYEES_DIR = "employees"
DOCUMENTS_SUBDIR = "documents"
LEGAL_SUBDIR = "legal"
CONVERSATIONS_SUBDIR = "conversations"
MEMORY_SUBDIR = "memory"

_BAD_CHARS = set('<>:"|?*\\/\x00')


def _safe_code(code: str) -> str:
    """Sanitize an employee_code so it's safe to use as a single path segment."""
    text = (code or "").strip()
    if not text or text in (".", ".."):
        raise ValueError(f"invalid employee code: {code!r}")
    cleaned = "".join("_" if c in _BAD_CHARS or ord(c) < 32 else c for c in text)
    cleaned = cleaned.strip(" .")
    if not cleaned:
        raise ValueError(f"invalid employee code after sanitization: {code!r}")
    return cleaned[:120]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def employees_root(workspace_root: str | Path) -> Path:
    """Return ``<workspace>/employees``."""
    return Path(workspace_root) / EMPLOYEES_DIR


def employee_dir(workspace_root: str | Path, employee_code: str) -> Path:
    """Return ``<workspace>/employees/<EMP-CODE>``."""
    return employees_root(workspace_root) / _safe_code(employee_code)


def documents_dir(workspace_root: str | Path, employee_code: str) -> Path:
    return employee_dir(workspace_root, employee_code) / DOCUMENTS_SUBDIR


def legal_dir(workspace_root: str | Path, employee_code: str) -> Path:
    return employee_dir(workspace_root, employee_code) / LEGAL_SUBDIR


def conversations_dir(workspace_root: str | Path, employee_code: str) -> Path:
    return employee_dir(workspace_root, employee_code) / CONVERSATIONS_SUBDIR


def memory_dir(workspace_root: str | Path, employee_code: str) -> Path:
    return employee_dir(workspace_root, employee_code) / MEMORY_SUBDIR


def ensure_employee_layout(workspace_root: str | Path, employee_code: str) -> Path:
    """Create all four standard subdirs for an employee. Idempotent."""
    base = employee_dir(workspace_root, employee_code)
    for sub in (DOCUMENTS_SUBDIR, LEGAL_SUBDIR, CONVERSATIONS_SUBDIR, MEMORY_SUBDIR):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# employee.md mirror
# ---------------------------------------------------------------------------
_EMPLOYEE_MD_FIELDS: tuple[str, ...] = (
    "employee_code", "full_name", "email", "phone",
    "status", "department_id", "role_id", "manager_id",
    "hire_date", "employment_type", "location",
)


def write_employee_md(
    workspace_root: str | Path,
    employee_row: dict[str, Any],
) -> Path | None:
    """Write/refresh ``employee.md`` at the root of the employee folder.

    Preserves any user-added frontmatter keys (anything outside the canonical
    ``_EMPLOYEE_MD_FIELDS`` set) and the existing markdown body, so a person
    can hand-edit the file without their notes getting clobbered the next
    time the employee row is updated. The markdown body is only written
    when there isn't one already.

    Returns the path that was written, or ``None`` if the row didn't have a
    usable ``employee_code``.
    """
    code = (employee_row or {}).get("employee_code")
    if not code:
        return None
    base = ensure_employee_layout(workspace_root, code)
    md_path = base / "employee.md"

    existing_fm: dict[str, Any] = {}
    existing_body = ""
    if md_path.exists():
        try:
            existing_fm, existing_body = fm.parse(md_path.read_text(encoding="utf-8"))
        except OSError:
            existing_fm, existing_body = {}, ""

    # Start from existing frontmatter so user-added keys (custom fields,
    # notes_summary, anything they typed) survive.
    fm_dict: dict[str, Any] = dict(existing_fm)
    fm_dict["type"] = "employee"
    for key in _EMPLOYEE_MD_FIELDS:
        value = employee_row.get(key)
        if value is None:
            continue
        fm_dict[key] = value

    # Mirror metadata_json.custom into a `custom` frontmatter dict so
    # user-defined fields are visible in the file too.
    raw_meta = employee_row.get("metadata_json")
    if raw_meta:
        try:
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else dict(raw_meta)
        except (TypeError, ValueError):
            meta = {}
        custom = meta.get("custom") if isinstance(meta, dict) else None
        if isinstance(custom, dict):
            for k, v in custom.items():
                # Avoid colliding with canonical keys.
                if k in _EMPLOYEE_MD_FIELDS or k == "type":
                    continue
                fm_dict[f"custom_{k}"] = v

    body = existing_body
    if not body.strip():
        body_lines: list[str] = [f"# {employee_row.get('full_name') or code}", ""]
        if employee_row.get("email"):
            body_lines.append(f"Email: {employee_row['email']}")
        if employee_row.get("hire_date"):
            body_lines.append(f"Hired: {employee_row['hire_date']}")
        body = "\n".join(body_lines).strip() + "\n"

    md_path.write_text(fm.dump(fm_dict, body), encoding="utf-8")
    return md_path


def write_employee_md_for_id(
    conn: sqlite3.Connection,
    workspace_root: str | Path,
    employee_id: int,
) -> Path | None:
    """Convenience: load the row by id and call :func:`write_employee_md`."""
    row = conn.execute(
        f"SELECT id, {', '.join(_EMPLOYEE_MD_FIELDS)} "
        "FROM employee WHERE id = ?",
        (int(employee_id),),
    ).fetchone()
    if not row:
        return None
    payload = {k: row[k] for k in row.keys()}
    return write_employee_md(workspace_root, payload)


# ---------------------------------------------------------------------------
# One-shot migration of legacy uploads
# ---------------------------------------------------------------------------
def plan_migration(
    conn: sqlite3.Connection,
    workspace_root: str | Path,
) -> list[dict[str, Any]]:
    """Walk the ``document`` table and produce a list of move operations.

    Each entry is::

        {"document_id": int, "employee_code": str, "from": str, "to": str,
         "exists": bool, "reason": str | None}

    ``reason`` is set when the row will be skipped (no employee_code, source
    file missing, already at the new path, etc.). The plan is read-only —
    callers can print it for review before invoking :func:`apply_migration`.
    """
    workspace_root = Path(workspace_root)
    plan: list[dict[str, Any]] = []
    cur = conn.execute(
        "SELECT d.id AS doc_id, d.file_path, d.filename, d.employee_id,"
        " e.employee_code "
        "FROM document d "
        "LEFT JOIN employee e ON e.id = d.employee_id "
        "ORDER BY d.id"
    )
    for row in cur.fetchall():
        doc_id = int(row["doc_id"])
        file_path = (row["file_path"] or "").strip()
        filename = (row["filename"] or "").strip()
        code = (row["employee_code"] or "").strip()
        entry: dict[str, Any] = {
            "document_id": doc_id, "employee_code": code,
            "from": file_path, "to": "", "exists": False, "reason": None,
        }
        if not code:
            entry["reason"] = "employee has no employee_code"
            plan.append(entry)
            continue
        if not file_path:
            entry["reason"] = "document has no file_path"
            plan.append(entry)
            continue
        # Resolve source path relative to workspace.
        src = workspace_root / file_path
        if not src.exists():
            entry["reason"] = "source file missing on disk"
            plan.append(entry)
            continue
        # Build target path under the new layout, using the original filename.
        tgt_dir = documents_dir(workspace_root, code)
        target_name = filename or src.name
        target = tgt_dir / target_name
        rel_target = target.relative_to(workspace_root).as_posix()
        entry["to"] = rel_target
        entry["exists"] = True
        if str(src.resolve()) == str(target.resolve()):
            entry["reason"] = "already at new location"
        plan.append(entry)
    return plan


def apply_migration(
    conn: sqlite3.Connection,
    workspace_root: str | Path,
    plan: list[dict[str, Any]],
) -> dict[str, Any]:
    """Execute the moves in ``plan``. Originals are kept (copy, not move).

    For each entry that has no ``reason`` set:
        * copy the source file to the new location (creating dirs as needed)
        * update ``document.file_path`` to the new workspace-relative path

    Returns ``{"copied": int, "updated_rows": int, "skipped": int, "errors": [...]}``
    """
    workspace_root = Path(workspace_root)
    copied = 0
    updated_rows = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    for entry in plan or []:
        if entry.get("reason"):
            skipped += 1
            continue
        src = workspace_root / entry["from"]
        tgt = workspace_root / entry["to"]
        try:
            tgt.parent.mkdir(parents=True, exist_ok=True)
            if not tgt.exists():
                shutil.copy2(src, tgt)
            copied += 1
            conn.execute(
                "UPDATE document SET file_path = ? WHERE id = ?",
                (entry["to"], int(entry["document_id"])),
            )
            updated_rows += 1
        except OSError as exc:
            errors.append({"document_id": str(entry["document_id"]), "error": str(exc)})
    conn.commit()
    return {
        "copied": copied, "updated_rows": updated_rows,
        "skipped": skipped, "errors": errors,
    }


# ---------------------------------------------------------------------------
# Notes (free-form markdown the user types about an employee)
# ---------------------------------------------------------------------------
def notes_path(workspace_root: str | Path, employee_code: str) -> Path:
    return memory_dir(workspace_root, employee_code) / "notes.md"


def read_notes(workspace_root: str | Path, employee_code: str) -> str:
    """Return the body of ``memory/notes.md``. '' if the file doesn't exist."""
    path = notes_path(workspace_root, employee_code)
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    _, body = fm.parse(text)
    return body


def write_notes(workspace_root: str | Path, employee_code: str, body: str) -> Path:
    """Write the notes body to ``memory/notes.md`` (with a small frontmatter)."""
    path = notes_path(workspace_root, employee_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_dict = {
        "type": "employee-notes",
        "employee_code": employee_code,
    }
    path.write_text(fm.dump(fm_dict, (body or "").rstrip() + "\n"), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Custom fields — stored in employee.metadata_json["custom"]
# ---------------------------------------------------------------------------
def get_custom_fields(conn: sqlite3.Connection, employee_id: int) -> dict[str, Any]:
    """Return the user-defined ``metadata_json.custom`` dict for this employee."""
    row = conn.execute(
        "SELECT metadata_json FROM employee WHERE id = ?", (int(employee_id),),
    ).fetchone()
    if not row:
        return {}
    try:
        meta = json.loads(row["metadata_json"] or "{}")
    except (TypeError, ValueError):
        return {}
    custom = meta.get("custom") if isinstance(meta, dict) else None
    return custom if isinstance(custom, dict) else {}


def set_custom_fields(
    conn: sqlite3.Connection,
    employee_id: int,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Replace the ``metadata_json.custom`` dict with ``fields``. Returns the saved value."""
    row = conn.execute(
        "SELECT metadata_json FROM employee WHERE id = ?", (int(employee_id),),
    ).fetchone()
    if not row:
        raise LookupError(f"employee {employee_id} not found")
    try:
        meta = json.loads(row["metadata_json"] or "{}")
        if not isinstance(meta, dict):
            meta = {}
    except (TypeError, ValueError):
        meta = {}
    cleaned: dict[str, Any] = {}
    for k, v in (fields or {}).items():
        key = str(k or "").strip()
        if not key:
            continue
        cleaned[key] = v if v is None else str(v)
    meta["custom"] = cleaned
    conn.execute(
        "UPDATE employee SET metadata_json = ? WHERE id = ?",
        (json.dumps(meta), int(employee_id)),
    )
    conn.commit()
    return cleaned


# ---------------------------------------------------------------------------
# AI context — what the chat agent reads when "talking about" an employee
# ---------------------------------------------------------------------------
def build_ai_context(
    conn: sqlite3.Connection,
    workspace_root: str | Path,
    employee_id: int,
    *,
    max_chars: int = 6000,
) -> str:
    """Return a markdown summary of everything we know about this employee.

    Pulled live from: the ``employee`` row + linked dept/role/manager,
    ``metadata_json.custom`` fields, ``memory/notes.md``, recent leave
    requests, recent activity, and the list of documents on file. Capped
    at ``max_chars`` so a long-tenured employee's history doesn't blow up
    the prompt.
    """
    row = conn.execute(
        """
        SELECT e.id, e.employee_code, e.full_name, e.email, e.phone,
               e.status, e.hire_date, e.employment_type, e.location,
               e.metadata_json,
               d.name AS department, r.title AS role,
               m.full_name AS manager_name
        FROM employee e
        LEFT JOIN department d ON d.id = e.department_id
        LEFT JOIN role r ON r.id = e.role_id
        LEFT JOIN employee m ON m.id = e.manager_id
        WHERE e.id = ?
        """,
        (int(employee_id),),
    ).fetchone()
    if not row:
        return ""

    code = row["employee_code"] or ""
    parts: list[str] = []
    parts.append(f"# Employee context: {row['full_name']} ({code})")
    facts: list[str] = []
    for label, value in (
        ("Email", row["email"]),
        ("Phone", row["phone"]),
        ("Status", row["status"]),
        ("Department", row["department"]),
        ("Role", row["role"]),
        ("Manager", row["manager_name"]),
        ("Hire date", row["hire_date"]),
        ("Employment type", row["employment_type"]),
        ("Location", row["location"]),
    ):
        if value:
            facts.append(f"- {label}: {value}")
    if facts:
        parts.append("## Facts\n" + "\n".join(facts))

    # Custom user-defined fields.
    custom = get_custom_fields(conn, employee_id)
    if custom:
        parts.append(
            "## Custom fields (added by HR)\n"
            + "\n".join(f"- {k}: {v}" for k, v in custom.items())
        )

    # Notes (user's free-form remarks).
    if code:
        notes = read_notes(workspace_root, code).strip()
        if notes:
            parts.append("## HR notes\n" + notes)

    # Documents on file.
    doc_rows = conn.execute(
        "SELECT doc_type, filename FROM document"
        " WHERE employee_id = ? ORDER BY uploaded_at DESC LIMIT 20",
        (int(employee_id),),
    ).fetchall()
    if doc_rows:
        parts.append(
            "## Documents on file\n"
            + "\n".join(f"- {d['doc_type']}: {d['filename']}" for d in doc_rows)
        )

    # Recent leave requests.
    lr_rows = conn.execute(
        "SELECT start_date, end_date, days, status, reason FROM leave_request"
        " WHERE employee_id = ? ORDER BY applied_at DESC LIMIT 5",
        (int(employee_id),),
    ).fetchall()
    if lr_rows:
        parts.append(
            "## Recent leave requests\n"
            + "\n".join(
                f"- {r['start_date']} → {r['end_date']} ({r['days']}d, {r['status']}): {r['reason']}"
                for r in lr_rows
            )
        )

    full = "\n\n".join(parts).strip() + "\n"
    if len(full) > max_chars:
        full = full[:max_chars] + f"\n... [context truncated; {len(full) - max_chars} more chars]"
    return full


__all__ = [
    "EMPLOYEES_DIR", "DOCUMENTS_SUBDIR", "LEGAL_SUBDIR",
    "CONVERSATIONS_SUBDIR", "MEMORY_SUBDIR",
    "employees_root", "employee_dir", "documents_dir",
    "legal_dir", "conversations_dir", "memory_dir",
    "ensure_employee_layout",
    "write_employee_md", "write_employee_md_for_id",
    "plan_migration", "apply_migration",
    "notes_path", "read_notes", "write_notes",
    "get_custom_fields", "set_custom_fields",
    "build_ai_context",
]
