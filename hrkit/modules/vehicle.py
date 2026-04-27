"""Vehicle / fleet module — company vehicles + employee assignment.

Owns ``vehicle`` and ``vehicle_assignment`` (migration 002).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "vehicle"
LABEL = "Fleet"
ICON = "car"

LIST_COLUMNS = ("vehicle_code", "registration_number", "make", "model",
                "type", "current_holder", "status")
ALLOWED_STATUS = ("available", "assigned", "maintenance", "retired")
ALLOWED_TYPE = ("car", "bike", "van", "truck", "bus", "other")


def ensure_schema(conn): return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _next_code(conn):
    cur = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS nxt FROM vehicle")
    return f"VEH-{int(cur.fetchone()['nxt']):04d}"


def list_rows(conn):
    cur = conn.execute("""
        SELECT v.*,
               (SELECT e.full_name FROM vehicle_assignment va
                  LEFT JOIN employee e ON e.id = va.employee_id
                  WHERE va.vehicle_id = v.id AND va.returned_at = ''
                  ORDER BY va.id DESC LIMIT 1) AS current_holder
        FROM vehicle v ORDER BY v.vehicle_code
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("SELECT * FROM vehicle WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    code = data.get("vehicle_code") or _next_code(conn)
    type_ = (data.get("type") or "car").strip()
    if type_ not in ALLOWED_TYPE:
        raise ValueError(f"type must be one of {ALLOWED_TYPE}")
    status = (data.get("status") or "available").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["vehicle_code", "type", "status"]
    vals: list[Any] = [code, type_, status]
    for key in ("registration_number", "make", "model", "fuel_type",
                "purchase_date", "notes"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    for key in ("year", "seating_capacity"):
        if data.get(key) is not None:
            cols.append(key); vals.append(int(data[key]))
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO vehicle ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("vehicle_code", "registration_number", "make", "model",
                "fuel_type", "purchase_date", "type", "status", "notes"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    for key in ("year", "seating_capacity"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(int(data[key]))
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE vehicle SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn, item_id):
    conn.execute("DELETE FROM vehicle WHERE id = ?", (item_id,))
    conn.commit()


def assign_to_employee(conn, vehicle_id: int, employee_id: int,
                       mileage_start: int = 0) -> int:
    cur = conn.execute("""
        INSERT INTO vehicle_assignment (vehicle_id, employee_id, mileage_start)
        VALUES (?, ?, ?)
    """, (int(vehicle_id), int(employee_id), int(mileage_start or 0)))
    conn.execute("UPDATE vehicle SET status='assigned' WHERE id = ?", (int(vehicle_id),))
    conn.commit()
    return int(cur.lastrowid)


def return_vehicle(conn, vehicle_id: int, mileage_end: int = 0) -> None:
    conn.execute("""
        UPDATE vehicle_assignment SET
          returned_at = strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'),
          mileage_end = ?
        WHERE vehicle_id = ? AND returned_at = ''
    """, (int(mileage_end or 0), int(vehicle_id)))
    conn.execute("UPDATE vehicle SET status='available' WHERE id = ?", (int(vehicle_id),))
    conn.commit()


def _emp_options(conn):
    return [{"id": r["id"], "label": r["full_name"]}
            for r in conn.execute(
                "SELECT id, full_name FROM employee ORDER BY full_name").fetchall()]


def _render_list_html(rows) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/vehicle/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    type_opts = "".join(f'<option value="{t}"{" selected" if t == "car" else ""}>{t}</option>'
                        for t in ALLOWED_TYPE)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add vehicle</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Registration number<input name="registration_number" placeholder="MH-12-AB-1234"></label>
    <label>Make<input name="make"></label>
    <label>Model<input name="model"></label>
    <label>Year<input name="year" type="number" min="1900" max="2100"></label>
    <label>Type<select name="type">{type_opts}</select></label>
    <label>Seating capacity<input name="seating_capacity" type="number" min="1"></label>
    <label>Fuel type<input name="fuel_type" placeholder="petrol / diesel / ev"></label>
    <label>Purchase date<input name="purchase_date" type="date"></label>
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
  const r = await fetch('/api/m/vehicle', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete?'))) return;
  const r = await fetch('/api/m/vehicle/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else hrkit.toast('Delete failed', 'error');
}}
</script>
"""


def list_view(handler):
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME, body_html=_render_list_html(list_rows(conn))))


def detail_api_json(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id):
    from hrkit.templates import render_detail_page, detail_section
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No vehicle with id {int(item_id)}"))
        return
    hist = conn.execute("""
        SELECT va.*, e.full_name AS holder, e.id AS employee_id
        FROM vehicle_assignment va
        LEFT JOIN employee e ON e.id = va.employee_id
        WHERE va.vehicle_id = ? ORDER BY va.assigned_at DESC
    """, (int(item_id),)).fetchall()
    if hist:
        rows_html = "".join(
            f"<tr><td>{_esc(h['assigned_at'])}</td>"
            f"<td>{_esc(h['returned_at']) or '<em>holding</em>'}</td>"
            f"<td><a href=\"/m/employee/{int(h['employee_id'])}\">{_esc(h['holder'])}</a></td>"
            f"<td>{_esc(h['mileage_start'])} → {_esc(h['mileage_end'])}</td></tr>"
            for h in hist)
        hist_table = (f"<table><thead><tr><th>Assigned</th><th>Returned</th>"
                      f"<th>Holder</th><th>Mileage</th></tr></thead><tbody>{rows_html}</tbody></table>")
    else:
        hist_table = '<div class="empty">No assignment history.</div>'
    emps = _emp_options(conn)
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in emps)
    assign_form = f"""
<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
  <select id="va-emp" style="flex:1;padding:7px 10px;background:var(--bg);
    color:var(--text);border:1px solid var(--border);border-radius:6px">
    <option value="">-- select employee --</option>{emp_opts}
  </select>
  <input id="va-mile" type="number" min="0" placeholder="Mileage start" style="width:140px">
  <button onclick="assignTo({int(item_id)})">Assign</button>
  <button onclick="returnVeh({int(item_id)})" class="ghost">Mark returned</button>
</div>
<script>
async function assignTo(id) {{
  const emp = document.getElementById('va-emp').value;
  const mile = document.getElementById('va-mile').value || 0;
  if (!emp) {{ hrkit.toast('Pick an employee', 'info'); return; }}
  const r = await fetch('/api/m/vehicle/' + id + '/assign', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{employee_id: parseInt(emp,10), mileage_start: parseInt(mile,10)}})
  }});
  if (r.ok) location.reload(); else hrkit.toast('Assign failed', 'error');
}}
async function returnVeh(id) {{
  const mile = (await hrkit.promptDialog('Mileage at return?', '0'));
  if (mile === null) return;
  const r = await fetch('/api/m/vehicle/' + id + '/return', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{mileage_end: parseInt(mile,10) || 0}})
  }});
  if (r.ok) location.reload(); else hrkit.toast('Return failed', 'error');
}}
</script>
"""
    fields = [
        ("Vehicle code", row.get("vehicle_code")),
        ("Registration", row.get("registration_number")),
        ("Make / Model", f"{row.get('make') or ''} {row.get('model') or ''}".strip()),
        ("Year", row.get("year")),
        ("Type", row.get("type")),
        ("Seating capacity", row.get("seating_capacity")),
        ("Fuel type", row.get("fuel_type")),
        ("Purchase date", row.get("purchase_date")),
        ("Status", row.get("status")),
        ("Notes", row.get("notes")),
    ]
    related = (detail_section(title="Assign / return", body_html=assign_form)
               + detail_section(title="History", body_html=hist_table))
    handler._html(200, render_detail_page(
        title=f"{row.get('make') or ''} {row.get('model') or ''} — {row.get('vehicle_code')}".strip(),
        nav_active=NAME, subtitle=row.get("registration_number") or "",
        fields=fields, related_html=related,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"status": list(ALLOWED_STATUS), "type": list(ALLOWED_TYPE)},
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


def assign_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    emp = payload.get("employee_id")
    if not emp:
        handler._json({"error": "employee_id required"}, code=400); return
    new_id = assign_to_employee(conn, int(item_id), int(emp),
                                mileage_start=int(payload.get("mileage_start") or 0))
    handler._json({"ok": True, "assignment_id": new_id})


def return_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    return_vehicle(conn, int(item_id), int(payload.get("mileage_end") or 0))
    handler._json({"ok": True})


ROUTES = {
    "GET": [
        (r"^/api/m/vehicle/(\d+)/?$", detail_api_json),
        (r"^/m/vehicle/?$", list_view),
        (r"^/m/vehicle/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/vehicle/(\d+)/assign/?$", assign_api),
        (r"^/api/m/vehicle/(\d+)/return/?$", return_api),
        (r"^/api/m/vehicle/?$", create_api),
        (r"^/api/m/vehicle/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/vehicle/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--registration-number", required=True)
    parser.add_argument("--make")
    parser.add_argument("--model")
    parser.add_argument("--year", type=int)
    parser.add_argument("--type", default="car", choices=list(ALLOWED_TYPE))


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "registration_number": args.registration_number,
        "make": getattr(args, "make", None),
        "model": getattr(args, "model", None),
        "year": getattr(args, "year", None),
        "type": args.type,
    })
    log.info("vehicle_added id=%s reg=%s", new_id, args.registration_number)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s %s\t%s", row["vehicle_code"], row["status"],
                 row.get("registration_number") or "",
                 row.get("make") or "", row.get("model") or "",
                 row.get("current_holder") or "")
    return 0


CLI = [
    ("vehicle-add", _add_create_args, _handle_create),
    ("vehicle-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "operations",
    "requires": ["employee"],
    "description": "Company vehicle fleet with employee assignment + mileage tracking.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
