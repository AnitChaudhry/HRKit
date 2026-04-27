"""Helpdesk module — employee support tickets.

Owns CRUD over ``helpdesk_ticket``. Schema in migration 002.
Pattern follows AGENTS_SPEC.md Section 1 (single MODULE dict, no top-level
side effects, stdlib only).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "helpdesk"
LABEL = "Helpdesk"
ICON = "lifebuoy"

LIST_COLUMNS = ("ticket_code", "subject", "requester", "assignee", "priority", "status")
ALLOWED_PRIORITY = ("low", "normal", "high", "urgent")
ALLOWED_STATUS = ("open", "in_progress", "resolved", "closed", "reopened")


def ensure_schema(conn: sqlite3.Connection) -> None:
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _next_code(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS nxt FROM helpdesk_ticket")
    return f"HD-{int(cur.fetchone()['nxt']):04d}"


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("""
        SELECT t.id, t.ticket_code, t.subject, t.priority, t.status,
               t.opened_at, t.resolved_at, t.category,
               r.full_name AS requester, a.full_name AS assignee,
               t.requester_id, t.assignee_id
        FROM helpdesk_ticket t
        LEFT JOIN employee r ON r.id = t.requester_id
        LEFT JOIN employee a ON a.id = t.assignee_id
        ORDER BY CASE t.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1
                               WHEN 'reopened' THEN 2 WHEN 'resolved' THEN 3 ELSE 4 END,
                 t.opened_at DESC
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("""
        SELECT t.*, r.full_name AS requester, a.full_name AS assignee
        FROM helpdesk_ticket t
        LEFT JOIN employee r ON r.id = t.requester_id
        LEFT JOIN employee a ON a.id = t.assignee_id
        WHERE t.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    subject = (data.get("subject") or "").strip()
    requester = data.get("requester_id")
    if not subject:
        raise ValueError("subject is required")
    if not requester:
        raise ValueError("requester_id is required")
    code = data.get("ticket_code") or _next_code(conn)
    priority = (data.get("priority") or "normal").strip()
    if priority not in ALLOWED_PRIORITY:
        raise ValueError(f"priority must be one of {ALLOWED_PRIORITY}")
    status = (data.get("status") or "open").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")

    cols = ["ticket_code", "subject", "requester_id", "priority", "status"]
    vals: list[Any] = [code, subject, int(requester), priority, status]
    for key in ("description", "category", "resolution"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    if data.get("assignee_id") not in (None, ""):
        cols.append("assignee_id"); vals.append(int(data["assignee_id"]))
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO helpdesk_ticket ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("ticket_code", "subject", "description", "category",
                "priority", "status", "resolution", "assignee_id", "resolved_at"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if not fields:
        return
    fields.append("updated = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    values.append(item_id)
    conn.execute(f"UPDATE helpdesk_ticket SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM helpdesk_ticket WHERE id = ?", (item_id,))
    conn.commit()


def _emp_options(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT id, full_name AS label FROM employee ORDER BY full_name")
    return [{"id": r["id"], "label": r["label"]} for r in cur.fetchall()]


def _render_list_html(rows: list[dict[str, Any]],
                      employees: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/helpdesk/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    pri_opts = "".join(f'<option value="{p}"{" selected" if p == "normal" else ""}>{p}</option>'
                       for p in ALLOWED_PRIORITY)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New ticket</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Subject*<input name="subject" required></label>
    <label>Requester*<select name="requester_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Assignee<select name="assignee_id"><option value="">-- (unassigned)</option>{emp_opts}</select></label>
    <label>Priority<select name="priority">{pri_opts}</select></label>
    <label>Category<input name="category" placeholder="general / it / hr / finance"></label>
    <label>Description<textarea name="description"></textarea></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Open ticket</button>
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
  if (payload.assignee_id === '') delete payload.assignee_id;
  const r = await fetch('/api/m/helpdesk', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete ticket #' + id + '?'))) return;
  const r = await fetch('/api/m/helpdesk/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else hrkit.toast('Delete failed', 'error');
}}
</script>
"""


def list_view(handler) -> None:
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    body = _render_list_html(list_rows(conn), _emp_options(conn))
    handler._html(200, render_module_page(title=LABEL, nav_active=NAME, body_html=body))


def detail_api_json(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No ticket with id {int(item_id)}"))
        return
    fields = [
        ("Ticket code", row.get("ticket_code")),
        ("Subject", row.get("subject")),
        ("Description", row.get("description")),
        ("Requester", row.get("requester")),
        ("Assignee", row.get("assignee")),
        ("Category", row.get("category")),
        ("Priority", row.get("priority")),
        ("Status", row.get("status")),
        ("Resolution", row.get("resolution")),
        ("Opened", row.get("opened_at")),
        ("Resolved", row.get("resolved_at")),
    ]
    handler._html(200, render_detail_page(
        title=row.get("subject") or "Ticket",
        nav_active=NAME,
        subtitle=row.get("ticket_code") or "",
        fields=fields,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}",
        delete_redirect=f"/m/{NAME}",
        field_options={"priority": list(ALLOWED_PRIORITY), "status": list(ALLOWED_STATUS)},
    ))


def create_api(handler) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        new_id = create_row(conn, payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"id": new_id}, code=201)


def update_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        update_row(conn, int(item_id), payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True})


def delete_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    delete_row(conn, int(item_id))
    handler._json({"ok": True})


ROUTES = {
    "GET": [
        (r"^/api/m/helpdesk/(\d+)/?$", detail_api_json),
        (r"^/m/helpdesk/?$", list_view),
        (r"^/m/helpdesk/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/helpdesk/?$", create_api),
        (r"^/api/m/helpdesk/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/helpdesk/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser) -> None:
    parser.add_argument("--subject", required=True)
    parser.add_argument("--requester-id", type=int, required=True)
    parser.add_argument("--assignee-id", type=int)
    parser.add_argument("--priority", default="normal", choices=list(ALLOWED_PRIORITY))
    parser.add_argument("--category", default="general")
    parser.add_argument("--description")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "subject": args.subject,
        "requester_id": args.requester_id,
        "assignee_id": getattr(args, "assignee_id", None),
        "priority": args.priority,
        "category": args.category,
        "description": getattr(args, "description", None),
    })
    log.info("ticket_opened id=%s subject=%s", new_id, args.subject)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s", row["ticket_code"], row["status"],
                 row["priority"], row["subject"])
    return 0


CLI = [
    ("ticket-open", _add_create_args, _handle_create),
    ("ticket-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "support",
    "requires": ["employee"],
    "description": "Employee support tickets — open, assign, resolve, track.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
