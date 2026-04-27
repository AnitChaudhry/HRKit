"""Project module — projects + per-project timesheet entries.

Owns ``project`` and ``timesheet_entry`` (migration 002). HR-adjacent
because it lets HR back out billable vs non-billable hours per employee.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "project"
LABEL = "Projects"
ICON = "folder"

LIST_COLUMNS = ("name", "code", "client", "manager", "status", "hours_logged")
ALLOWED_STATUS = ("planning", "active", "on_hold", "completed", "cancelled")


def ensure_schema(conn): return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _format_minor(v):
    if v is None or v == "":
        return ""
    try:
        return f"₹{int(v)/100:,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _coerce_minor(payload: dict[str, Any]) -> int | None:
    if "budget_minor" in payload and payload["budget_minor"] not in (None, ""):
        return int(payload["budget_minor"])
    if "budget" in payload and payload["budget"] not in (None, ""):
        return int(round(float(payload["budget"]) * 100))
    return None


def list_rows(conn):
    cur = conn.execute("""
        SELECT p.*, m.full_name AS manager,
               (SELECT COALESCE(SUM(hours), 0) FROM timesheet_entry t
                  WHERE t.project_id = p.id) AS hours_logged
        FROM project p
        LEFT JOIN employee m ON m.id = p.manager_id
        ORDER BY p.status, p.name
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("""
        SELECT p.*, m.full_name AS manager
        FROM project p
        LEFT JOIN employee m ON m.id = p.manager_id
        WHERE p.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    status = (data.get("status") or "active").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["name", "status"]; vals: list[Any] = [name, status]
    for key in ("code", "client", "start_date", "end_date", "description"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    if data.get("manager_id") not in (None, ""):
        cols.append("manager_id"); vals.append(int(data["manager_id"]))
    budget = _coerce_minor(data)
    if budget is not None:
        cols.append("budget_minor"); vals.append(budget)
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO project ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("name", "code", "client", "status", "start_date", "end_date",
                "description", "manager_id"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "budget_minor" in data or "budget" in data:
        fields.append("budget_minor = ?"); values.append(_coerce_minor(data))
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE project SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn, item_id):
    conn.execute("DELETE FROM project WHERE id = ?", (item_id,))
    conn.commit()


def log_time(conn, employee_id: int, project_id: int, date: str,
             hours: float, billable: bool = True, description: str = "") -> int:
    if not date or hours <= 0:
        raise ValueError("date and positive hours are required")
    cur = conn.execute("""
        INSERT INTO timesheet_entry (employee_id, project_id, date, hours, billable, description)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (int(employee_id), int(project_id), date, float(hours),
          1 if billable else 0, description or ""))
    conn.commit()
    return int(cur.lastrowid)


def _emp_options(conn):
    return [{"id": r["id"], "label": r["full_name"]}
            for r in conn.execute(
                "SELECT id, full_name FROM employee ORDER BY full_name").fetchall()]


def _render_list_html(rows, employees) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/project/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    status_opts = "".join(
        f'<option value="{s}"{" selected" if s == "active" else ""}>{s}</option>'
        for s in ALLOWED_STATUS)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New project</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Name*<input name="name" required></label>
    <label>Code<input name="code" placeholder="PRJ-001"></label>
    <label>Client<input name="client"></label>
    <label>Manager<select name="manager_id"><option value="">-- (none)</option>{emp_opts}</select></label>
    <label>Status<select name="status">{status_opts}</select></label>
    <label>Start date<input name="start_date" type="date"></label>
    <label>End date<input name="end_date" type="date"></label>
    <label>Budget (₹)<input name="budget" type="number" step="0.01" min="0"></label>
    <label>Description<textarea name="description"></textarea></label>
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
  if (payload.manager_id === '') delete payload.manager_id;
  const r = await fetch('/api/m/project', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete?'))) return;
  const r = await fetch('/api/m/project/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else hrkit.toast('Delete failed', 'error');
}}
</script>
"""


def list_view(handler):
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME,
        body_html=_render_list_html(list_rows(conn), _emp_options(conn))))


def detail_api_json(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id):
    from hrkit.templates import render_detail_page, detail_section
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No project with id {int(item_id)}"))
        return
    entries = conn.execute("""
        SELECT t.*, e.full_name AS employee, e.id AS employee_id
        FROM timesheet_entry t
        JOIN employee e ON e.id = t.employee_id
        WHERE t.project_id = ? ORDER BY t.date DESC, t.id DESC LIMIT 200
    """, (int(item_id),)).fetchall()
    if entries:
        rows_html = "".join(
            f"<tr><td>{_esc(t['date'])}</td>"
            f"<td><a href=\"/m/employee/{int(t['employee_id'])}\">{_esc(t['employee'])}</a></td>"
            f"<td>{_esc(t['hours'])}</td>"
            f"<td>{'Yes' if t['billable'] else 'No'}</td>"
            f"<td>{'✓' if t['approved'] else ''}</td>"
            f"<td>{_esc(t['description'])}</td></tr>"
            for t in entries)
        ts_table = (f"<table><thead><tr><th>Date</th><th>Employee</th><th>Hours</th>"
                    f"<th>Billable</th><th>Approved</th><th>Description</th>"
                    f"</tr></thead><tbody>{rows_html}</tbody></table>")
    else:
        ts_table = '<div class="empty">No time logged yet.</div>'

    emps = _emp_options(conn)
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in emps)
    log_form = f"""
<form onsubmit="logTime(event,{int(item_id)})" style="display:grid;
  grid-template-columns:1.5fr 1fr 1fr 2fr auto;gap:8px;margin-bottom:14px">
  <select name="employee_id" required><option value="">-- employee --</option>{emp_opts}</select>
  <input name="date" type="date" required>
  <input name="hours" type="number" step="0.25" min="0.25" max="24" placeholder="Hours" required>
  <input name="description" placeholder="Description">
  <button>+ Log time</button>
</form>
<script>
async function logTime(ev, projId) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const r = await fetch('/api/m/project/' + projId + '/timesheet', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Log failed: ' + await r.text(), 'error');
}}
</script>
"""

    fields = [
        ("Name", row.get("name")),
        ("Code", row.get("code")),
        ("Client", row.get("client")),
        ("Manager", row.get("manager")),
        ("Status", row.get("status")),
        ("Start date", row.get("start_date")),
        ("End date", row.get("end_date")),
        ("Budget", _format_minor(row.get("budget_minor"))),
        ("Description", row.get("description")),
    ]
    related = (detail_section(title="Log time", body_html=log_form)
               + detail_section(title="Recent entries", body_html=ts_table))
    handler._html(200, render_detail_page(
        title=row.get("name") or "Project", nav_active=NAME,
        subtitle=row.get("code") or row.get("client") or "",
        fields=fields, related_html=related,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"status": list(ALLOWED_STATUS)},
    ))


def create_api(handler):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        new_id = create_row(conn, payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"id": new_id}, code=201)


def update_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        update_row(conn, int(item_id), payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True})


def delete_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    delete_row(conn, int(item_id))
    handler._json({"ok": True})


def timesheet_create_api(handler, project_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    emp = payload.get("employee_id")
    date = payload.get("date") or ""
    hours = payload.get("hours")
    if not emp or not date or hours is None:
        handler._json({"error": "employee_id, date and hours required"}, code=400); return
    try:
        tid = log_time(conn, int(emp), int(project_id), date, float(hours),
                       billable=payload.get("billable", True) not in (False, "false", "0"),
                       description=payload.get("description") or "")
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True, "entry_id": tid})


ROUTES = {
    "GET": [
        (r"^/api/m/project/(\d+)/?$", detail_api_json),
        (r"^/m/project/?$", list_view),
        (r"^/m/project/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/project/(\d+)/timesheet/?$", timesheet_create_api),
        (r"^/api/m/project/?$", create_api),
        (r"^/api/m/project/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/project/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--name", required=True)
    parser.add_argument("--code")
    parser.add_argument("--client")
    parser.add_argument("--manager-id", type=int)


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "name": args.name,
        "code": getattr(args, "code", None),
        "client": getattr(args, "client", None),
        "manager_id": getattr(args, "manager_id", None),
    })
    log.info("project_added id=%s name=%s", new_id, args.name)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%sh", row["id"], row["status"],
                 row["name"], row.get("hours_logged") or 0)
    return 0


CLI = [
    ("project-add", _add_create_args, _handle_create),
    ("project-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "operations",
    "requires": ["employee"],
    "description": "Projects with per-employee billable / non-billable timesheet entries.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
