"""Shift module — defined work shifts + employee↔shift assignments.

Owns ``shift`` and ``shift_assignment`` (migration 002). Days-of-week is
stored as a JSON list of ints 1=Mon..7=Sun.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "shift"
LABEL = "Shifts"
ICON = "clock"

LIST_COLUMNS = ("name", "start_time", "end_time", "days", "active_count")
DAY_LABELS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def ensure_schema(conn: sqlite3.Connection) -> None:
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _format_days(days_json: str) -> str:
    try:
        days = json.loads(days_json or "[]")
    except (TypeError, ValueError):
        return days_json or ""
    return ", ".join(DAY_LABELS.get(int(d), str(d)) for d in days if isinstance(d, (int, str)))


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("""
        SELECT s.id, s.name, s.start_time, s.end_time, s.break_minutes,
               s.days_of_week, s.is_active, s.notes,
               (SELECT COUNT(*) FROM shift_assignment sa
                  WHERE sa.shift_id = s.id
                    AND (sa.end_date = '' OR sa.end_date >= strftime('%Y-%m-%d','now','+05:30'))
               ) AS active_count
        FROM shift s ORDER BY s.start_time, s.name
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["days"] = _format_days(d.get("days_of_week") or "[]")
        out.append(d)
    return out


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM shift WHERE id = ?", (item_id,))
    row = cur.fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    d["days"] = _format_days(d.get("days_of_week") or "[]")
    return d


def _normalize_days(value: Any) -> str:
    if value is None or value == "":
        return "[1,2,3,4,5]"
    if isinstance(value, list):
        return json.dumps([int(x) for x in value if str(x).strip()])
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("["):
            try:
                return json.dumps([int(x) for x in json.loads(s)])
            except (TypeError, ValueError):
                return "[1,2,3,4,5]"
        return json.dumps([int(p) for p in s.split(",") if p.strip().isdigit()])
    return "[1,2,3,4,5]"


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    cols = ["name"]
    vals: list[Any] = [name]
    for key in ("start_time", "end_time", "notes"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    if data.get("break_minutes") is not None:
        cols.append("break_minutes"); vals.append(int(data["break_minutes"]))
    if "days_of_week" in data or "days" in data:
        cols.append("days_of_week")
        vals.append(_normalize_days(data.get("days_of_week") or data.get("days")))
    if "is_active" in data:
        cols.append("is_active"); vals.append(1 if data["is_active"] else 0)
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO shift ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("name", "start_time", "end_time", "notes"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "break_minutes" in data:
        fields.append("break_minutes = ?"); values.append(int(data["break_minutes"]))
    if "days_of_week" in data or "days" in data:
        fields.append("days_of_week = ?")
        values.append(_normalize_days(data.get("days_of_week") or data.get("days")))
    if "is_active" in data:
        fields.append("is_active = ?"); values.append(1 if data["is_active"] else 0)
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE shift SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM shift WHERE id = ?", (item_id,))
    conn.commit()


def assign_employee(conn: sqlite3.Connection, employee_id: int, shift_id: int,
                    start_date: str, end_date: str = "", notes: str = "") -> int:
    if not start_date:
        raise ValueError("start_date is required")
    cur = conn.execute("""
        INSERT INTO shift_assignment (employee_id, shift_id, start_date, end_date, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (int(employee_id), int(shift_id), start_date, end_date or "", notes or ""))
    conn.commit()
    return int(cur.lastrowid)


def _emp_options(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT id, full_name AS label FROM employee ORDER BY full_name")
    return [{"id": r["id"], "label": r["label"]} for r in cur.fetchall()]


def _render_list_html(rows: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/shift/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Shift</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Name*<input name="name" required placeholder="Morning / Night / General"></label>
    <label>Start time<input name="start_time" type="time" value="09:00"></label>
    <label>End time<input name="end_time" type="time" value="18:00"></label>
    <label>Break (minutes)<input name="break_minutes" type="number" min="0" value="60"></label>
    <label>Days (1=Mon..7=Sun, comma-sep)<input name="days" value="1,2,3,4,5"></label>
    <label>Notes<textarea name="notes"></textarea></label>
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
  const r = await fetch('/api/m/shift', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete shift #' + id + '?')) return;
  const r = await fetch('/api/m/shift/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""


def list_view(handler) -> None:
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME,
        body_html=_render_list_html(list_rows(conn))))


def detail_api_json(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No shift with id {int(item_id)}"))
        return

    assigns = conn.execute("""
        SELECT sa.id, sa.start_date, sa.end_date, sa.notes,
               e.id AS employee_id, e.full_name, e.employee_code
        FROM shift_assignment sa
        JOIN employee e ON e.id = sa.employee_id
        WHERE sa.shift_id = ? ORDER BY sa.start_date DESC
    """, (int(item_id),)).fetchall()
    if assigns:
        rows_html = "".join(
            f"<tr><td>{_esc(a['employee_code'])}</td>"
            f"<td><a href=\"/m/employee/{int(a['employee_id'])}\">{_esc(a['full_name'])}</a></td>"
            f"<td>{_esc(a['start_date'])}</td><td>{_esc(a['end_date']) or '<em>open</em>'}</td>"
            f"<td>{_esc(a['notes'])}</td></tr>"
            for a in assigns)
        assign_table = (f"<table><thead><tr><th>Code</th><th>Employee</th><th>Start</th>"
                        f"<th>End</th><th>Notes</th></tr></thead><tbody>{rows_html}</tbody></table>")
    else:
        assign_table = '<div class="empty">No assignments yet.</div>'

    emps = _emp_options(conn)
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in emps)
    assign_form = f"""
<div style="display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:8px;align-items:end;margin-bottom:14px">
  <label style="margin:0">Employee
    <select id="sa-emp" style="width:100%">{emp_opts}</select></label>
  <label style="margin:0">Start
    <input id="sa-start" type="date" value="{_esc(row.get('start_time') and '')}"></label>
  <label style="margin:0">End (optional)
    <input id="sa-end" type="date"></label>
  <button onclick="addAssign({int(item_id)})">Assign</button>
</div>
<script>
async function addAssign(shiftId) {{
  const emp = document.getElementById('sa-emp').value;
  const start = document.getElementById('sa-start').value;
  const end = document.getElementById('sa-end').value;
  if (!emp || !start) {{ alert('Pick an employee and start date'); return; }}
  const r = await fetch('/api/m/shift/' + shiftId + '/assign', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{employee_id: parseInt(emp,10), start_date: start, end_date: end || ''}})
  }});
  if (r.ok) location.reload(); else alert('Assign failed: ' + await r.text());
}}
</script>
"""

    fields = [
        ("Name", row.get("name")),
        ("Start", row.get("start_time")),
        ("End", row.get("end_time")),
        ("Break (min)", row.get("break_minutes")),
        ("Days", row.get("days")),
        ("Active", "Yes" if row.get("is_active") else "No"),
        ("Notes", row.get("notes")),
    ]
    related = (detail_section(title="Assign employee", body_html=assign_form)
               + detail_section(title="Assignments", body_html=assign_table))
    handler._html(200, render_detail_page(
        title=row.get("name") or "Shift", nav_active=NAME, subtitle="",
        fields=fields, related_html=related,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}",
        delete_redirect=f"/m/{NAME}",
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


def assign_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        new_id = assign_employee(
            conn, int(payload["employee_id"]), int(item_id),
            start_date=payload.get("start_date") or "",
            end_date=payload.get("end_date") or "",
            notes=payload.get("notes") or "")
    except (KeyError, ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True, "assignment_id": new_id})


ROUTES = {
    "GET": [
        (r"^/api/m/shift/(\d+)/?$", detail_api_json),
        (r"^/m/shift/?$", list_view),
        (r"^/m/shift/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/shift/(\d+)/assign/?$", assign_api),
        (r"^/api/m/shift/?$", create_api),
        (r"^/api/m/shift/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/shift/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--start-time", default="09:00")
    parser.add_argument("--end-time", default="18:00")
    parser.add_argument("--break-minutes", type=int, default=60)
    parser.add_argument("--days", default="1,2,3,4,5", help="Comma-sep 1=Mon..7=Sun")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "name": args.name,
        "start_time": args.start_time,
        "end_time": args.end_time,
        "break_minutes": args.break_minutes,
        "days": args.days,
    })
    log.info("shift_added id=%s name=%s", new_id, args.name)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s-%s\t%s",
                 row["id"], row["name"], row["start_time"], row["end_time"], row["days"])
    return 0


CLI = [
    ("shift-add", _add_create_args, _handle_create),
    ("shift-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "operations",
    "requires": ["employee"],
    "description": "Defined work shifts (timing + days) with employee assignments.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
