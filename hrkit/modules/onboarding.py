"""Onboarding HR module.

Owns CRUD over the ``onboarding_task`` table created by migration
``001_full_hr_schema.sql``. Follows the registry contract from
AGENTS_SPEC.md Section 1 - a single top-level ``MODULE`` dict, no
top-level side effects, stdlib only.

The list view groups tasks by employee. Status follows the lifecycle
``pending -> in_progress -> done`` and is advanced via the lightweight
``POST /api/m/onboarding/<id>/start`` and ``/done`` transition endpoints.
``done`` stamps ``completed_at`` with the current IST timestamp.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any

from hrkit.config import IST

log = logging.getLogger(__name__)

NAME = "onboarding"
LABEL = "Onboarding"
ICON = "checklist"

LIST_COLUMNS = ("employee", "title", "owner", "due_date", "status")

ALLOWED_STATUS = ("pending", "in_progress", "done")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def ensure_schema(conn: sqlite3.Connection) -> None:
    """No-op. The ``onboarding_task`` table is created by migration 001."""
    pass


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _now_ist_iso() -> str:
    """Return the current IST timestamp as ``YYYY-MM-DDTHH:MM:SS+05:30``."""
    return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S%z")


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all onboarding tasks joined with employee + owner names.

    Ordered by employee name then due_date so the HTML view can group
    consecutive rows for each employee.
    """
    cur = conn.execute(
        """
        SELECT t.id, t.employee_id, t.title, t.owner_id, t.due_date,
               t.status, t.notes, t.completed_at, t.created, t.updated,
               e.full_name AS employee,
               o.full_name AS owner
        FROM onboarding_task t
        LEFT JOIN employee e ON e.id = t.employee_id
        LEFT JOIN employee o ON o.id = t.owner_id
        ORDER BY e.full_name, t.due_date, t.id
        """
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute(
        """
        SELECT t.*, e.full_name AS employee, o.full_name AS owner
        FROM onboarding_task t
        LEFT JOIN employee e ON e.id = t.employee_id
        LEFT JOIN employee o ON o.id = t.owner_id
        WHERE t.id = ?
        """,
        (item_id,),
    )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    """Insert an onboarding_task row. Returns the new id."""
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")

    employee_id = data.get("employee_id")
    if employee_id in (None, ""):
        raise ValueError("employee_id is required")
    employee_id = int(employee_id)

    owner_id = data.get("owner_id")
    owner_id = int(owner_id) if owner_id not in (None, "") else None

    status = (data.get("status") or "pending").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")

    cur = conn.execute(
        """
        INSERT INTO onboarding_task (
            employee_id, title, owner_id, due_date, status, notes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            employee_id,
            title,
            owner_id,
            data.get("due_date") or "",
            status,
            data.get("notes") or "",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields: list[str] = []
    values: list[Any] = []
    simple = ("title", "owner_id", "due_date", "status", "notes", "completed_at")
    for key in simple:
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if not fields:
        return
    values.append(item_id)
    conn.execute(
        f"UPDATE onboarding_task SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM onboarding_task WHERE id = ?", (item_id,))
    conn.commit()


def transition(conn: sqlite3.Connection, item_id: int, new_status: str) -> dict[str, Any]:
    """Move a task to ``in_progress`` or ``done`` and return the updated row.

    ``done`` also stamps ``completed_at`` with the current IST timestamp.
    Raises ``ValueError`` if the row does not exist or the status is invalid.
    """
    if new_status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    row = get_row(conn, item_id)
    if not row:
        raise ValueError(f"onboarding_task {item_id} not found")

    if new_status == "done":
        conn.execute(
            "UPDATE onboarding_task SET status = ?, completed_at = ? WHERE id = ?",
            (new_status, _now_ist_iso(), item_id),
        )
    else:
        conn.execute(
            "UPDATE onboarding_task SET status = ? WHERE id = ?",
            (new_status, item_id),
        )
    conn.commit()
    updated = get_row(conn, item_id)
    assert updated is not None
    return updated


def _list_employee_options(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, full_name AS label FROM employee "
        "WHERE status = 'active' ORDER BY full_name"
    )
    return [{"id": r["id"], "label": r["label"]} for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def _esc(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_list_html(rows: list[dict[str, Any]],
                      employees: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)

    # Group rows by employee for visual clarity.
    body_rows: list[str] = []
    last_employee: str | None = None
    for row in rows:
        employee = row.get("employee") or "(unassigned)"
        if employee != last_employee:
            body_rows.append(
                f'<tr class="group-row"><td colspan="{len(LIST_COLUMNS) + 1}">'
                f'<strong>{_esc(employee)}</strong></td></tr>'
            )
            last_employee = employee
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        actions: list[str] = []
        if row.get("status") == "pending":
            actions.append(
                f'<button onclick="transitionRow({row["id"]}, \'start\')">Start</button>'
            )
        if row.get("status") in ("pending", "in_progress"):
            actions.append(
                f'<button onclick="transitionRow({row["id"]}, \'done\')">Done</button>'
            )
        actions.append(
            f'<button onclick="deleteRow({row["id"]})">Delete</button>'
        )
        body_rows.append(
            f'<tr data-id="{row["id"]}">{cells}<td>{"".join(actions)}</td></tr>'
        )

    emp_opts = "".join(
        f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees
    )
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Task</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Employee*<select name="employee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Title*<input name="title" required></label>
    <label>Owner<select name="owner_id"><option value="">--</option>{emp_opts}</select></label>
    <label>Due date<input name="due_date" type="date"></label>
    <label>Notes<textarea name="notes" rows="3"></textarea></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Save</button>
    </menu>
  </form>
</dialog>
<script>
function filter(q) {{
  q = (q || '').toLowerCase();
  document.querySelectorAll('#rows tr').forEach(tr => {{
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
async function submitCreate(ev) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const payload = Object.fromEntries(fd.entries());
  for (const k of ['owner_id']) if (payload[k] === '') delete payload[k];
  const r = await fetch('/api/m/onboarding', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function transitionRow(id, action) {{
  const r = await fetch('/api/m/onboarding/' + id + '/' + action, {{method: 'POST'}});
  if (r.ok) location.reload(); else alert('Transition failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete task #' + id + '?')) return;
  const r = await fetch('/api/m/onboarding/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------
def list_view(handler) -> None:
    from hrkit.templates import render_module_page  # late import

    conn = handler.server.conn  # type: ignore[attr-defined]
    rows = list_rows(conn)
    employees = _list_employee_options(conn)
    body = _render_list_html(rows, employees)
    handler._html(200, render_module_page(title=LABEL, nav_active=NAME, body_html=body))


def _fmt_dt(value: Any) -> str:
    """Trim fractional seconds from a datetime-ish string for display."""
    if value in (None, ""):
        return ""
    text = str(value)
    if "." not in text:
        return text
    head, tail = text.split(".", 1)
    i = 0
    while i < len(tail) and tail[i].isdigit():
        i += 1
    return head + tail[i:]


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section

    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(
            title="Not found",
            nav_active=NAME,
            subtitle=f"No onboarding task with id {int(item_id)}",
        ))
        return

    fields: list[tuple[str, Any]] = [
        ("Employee", row.get("employee") or row.get("employee_id")),
        ("Title", row.get("title")),
        ("Owner", row.get("owner") or row.get("owner_id")),
        ("Due date", row.get("due_date")),
        ("Status", row.get("status")),
        ("Completed at", _fmt_dt(row.get("completed_at"))),
        ("Notes", row.get("notes")),
        ("Created", _fmt_dt(row.get("created"))),
        ("Updated", _fmt_dt(row.get("updated"))),
    ]

    rid = int(item_id)
    status = row.get("status") or ""
    btns: list[str] = []
    if status == "pending":
        btns.append(
            f"<button onclick=\"fetch('/api/m/onboarding/{rid}/start',"
            f"{{method:'POST'}}).then(r=>r.ok?location.reload():"
            f"r.text().then(t=>alert('Start failed: '+t)))\">Start</button>"
        )
    if status in ("pending", "in_progress"):
        btns.append(
            f"<button onclick=\"fetch('/api/m/onboarding/{rid}/done',"
            f"{{method:'POST'}}).then(r=>r.ok?location.reload():"
            f"r.text().then(t=>alert('Done failed: '+t)))\">Done</button>"
        )
    actions_html = "".join(btns)

    # Related: other tasks for this employee.
    related_html = ""
    emp_id = row.get("employee_id")
    if emp_id is not None:
        peers = conn.execute(
            "SELECT id, title, due_date, status FROM onboarding_task "
            "WHERE employee_id = ? AND id != ? "
            "ORDER BY due_date, id LIMIT 10",
            (int(emp_id), rid),
        ).fetchall()
        if peers:
            body = (
                "<table><thead><tr>"
                "<th>Title</th><th>Due</th><th>Status</th>"
                "</tr></thead><tbody>"
                + "".join(
                    f"<tr><td>"
                    f"<a href=\"/m/onboarding/{int(p['id'])}\">{_esc(p['title'])}</a>"
                    f"</td><td>{_esc(p['due_date'])}</td>"
                    f"<td>{_esc(p['status'])}</td></tr>"
                    for p in peers
                )
                + "</tbody></table>"
            )
        else:
            body = '<div class="empty">No other tasks for this employee.</div>'
        related_html = detail_section(
            title="Other tasks for this employee", body_html=body,
        )

    page = render_detail_page(
        title=row.get("title") or "Onboarding task",
        nav_active=NAME,
        subtitle=str(row.get("employee") or ""),
        fields=fields,
        actions_html=actions_html,
        related_html=related_html,
        item_id=rid,
        api_path="/api/m/onboarding",
        delete_redirect="/m/onboarding",
    )
    handler._html(200, page)


def detail_api_json(handler, item_id: int) -> None:
    """Return raw onboarding_task row as JSON."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._json({"error": "not_found"}, code=404)
        return
    handler._json(row)


def create_api(handler) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        new_id = create_row(conn, payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"id": new_id}, code=201)


def update_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        update_row(conn, int(item_id), payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"ok": True})


def delete_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    delete_row(conn, int(item_id))
    handler._json({"ok": True})


def start_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        row = transition(conn, int(item_id), "in_progress")
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json(row)


def done_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        row = transition(conn, int(item_id), "done")
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json(row)


ROUTES = {
    "GET": [
        (r"^/api/m/onboarding/(\d+)/?$", detail_api_json),
        (r"^/m/onboarding/?$", list_view),
        (r"^/m/onboarding/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/onboarding/?$", create_api),
        (r"^/api/m/onboarding/(\d+)/start/?$", start_api),
        (r"^/api/m/onboarding/(\d+)/done/?$", done_api),
        (r"^/api/m/onboarding/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/onboarding/(\d+)/?$", delete_api),
    ],
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_create_args(parser) -> None:
    parser.add_argument("--employee-id", type=int, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--owner-id", type=int)
    parser.add_argument("--due-date")
    parser.add_argument("--notes", default="")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "employee_id": args.employee_id,
        "title": args.title,
        "owner_id": getattr(args, "owner_id", None),
        "due_date": getattr(args, "due_date", None),
        "notes": getattr(args, "notes", ""),
    })
    log.info("onboarding_task_added id=%s employee_id=%s", new_id, args.employee_id)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info(
            "%s\t%s\t%s\t%s\t%s",
            row["id"], row.get("employee"), row.get("title"),
            row.get("due_date"), row.get("status"),
        )
    return 0


CLI = [
    ("onboarding-add", _add_create_args, _handle_create),
    ("onboarding-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "hr",
    "requires": ["employee"],
    "description": "Joiner checklist with tasks, owners, and due dates.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
