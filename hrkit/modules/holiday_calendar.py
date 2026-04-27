"""Holiday calendar module — multiple region/department-specific calendars.

Owns ``holiday_calendar``, ``holiday``, ``holiday_calendar_assignment``
(migration 002).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "holiday_calendar"
LABEL = "Holiday Calendars"
ICON = "calendar"

LIST_COLUMNS = ("name", "region", "year", "is_default", "holidays")
HOLIDAY_TYPES = ("public", "optional", "restricted", "company")


def ensure_schema(conn: sqlite3.Connection) -> None:
    return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("""
        SELECT c.id, c.name, c.region, c.year, c.is_default, c.notes,
               (SELECT COUNT(*) FROM holiday h WHERE h.calendar_id = c.id) AS holidays
        FROM holiday_calendar c
        ORDER BY c.is_default DESC, c.name
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["is_default"] = "Yes" if d.get("is_default") else "No"
        out.append(d)
    return out


def get_row(conn, item_id: int):
    cur = conn.execute("SELECT * FROM holiday_calendar WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    cols = ["name"]; vals: list[Any] = [name]
    for key in ("region", "notes"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    if data.get("year") not in (None, ""):
        cols.append("year"); vals.append(int(data["year"]))
    if data.get("is_default") is not None:
        cols.append("is_default"); vals.append(1 if data["is_default"] else 0)
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO holiday_calendar ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("name", "region", "notes"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "year" in data:
        fields.append("year = ?"); values.append(int(data["year"]) if data["year"] not in (None, "") else 0)
    if "is_default" in data:
        fields.append("is_default = ?"); values.append(1 if data["is_default"] else 0)
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE holiday_calendar SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn, item_id):
    conn.execute("DELETE FROM holiday_calendar WHERE id = ?", (item_id,))
    conn.commit()


def add_holiday(conn, calendar_id: int, name: str, date: str,
                holiday_type: str = "public", description: str = "") -> int:
    if not name or not date:
        raise ValueError("name and date required")
    if holiday_type not in HOLIDAY_TYPES:
        raise ValueError(f"type must be one of {HOLIDAY_TYPES}")
    cur = conn.execute("""
        INSERT INTO holiday (calendar_id, name, date, type, description)
        VALUES (?, ?, ?, ?, ?)
    """, (int(calendar_id), name, date, holiday_type, description))
    conn.commit()
    return int(cur.lastrowid)


def assign_calendar(conn, calendar_id: int,
                    employee_id: int | None = None,
                    department_id: int | None = None,
                    location: str = "", notes: str = "") -> int:
    cur = conn.execute("""
        INSERT INTO holiday_calendar_assignment
        (calendar_id, employee_id, department_id, location, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (int(calendar_id), employee_id, department_id, location or "", notes or ""))
    conn.commit()
    return int(cur.lastrowid)


def _render_list_html(rows) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/holiday_calendar/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New calendar</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Name*<input name="name" required placeholder="India 2026 / US 2026"></label>
    <label>Region<input name="region" placeholder="IN / US-CA / EU"></label>
    <label>Year<input name="year" type="number" min="1900" max="2100"></label>
    <label><input type="checkbox" name="is_default" value="1"> Default calendar</label>
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
  const payload = Object.fromEntries(fd.entries());
  payload.is_default = fd.has('is_default');
  const r = await fetch('/api/m/holiday_calendar', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete calendar #' + id + '?')) return;
  const r = await fetch('/api/m/holiday_calendar/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
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
                      subtitle=f"No calendar with id {int(item_id)}"))
        return
    holidays = conn.execute(
        "SELECT id, name, date, type, description FROM holiday "
        "WHERE calendar_id = ? ORDER BY date", (int(item_id),)).fetchall()
    if holidays:
        rows_html = "".join(
            f"<tr><td>{_esc(h['date'])}</td><td>{_esc(h['name'])}</td>"
            f"<td>{_esc(h['type'])}</td><td>{_esc(h['description'])}</td>"
            f"<td><button onclick=\"deleteHoliday({int(h['id'])})\">×</button></td></tr>"
            for h in holidays)
        h_table = (f"<table><thead><tr><th>Date</th><th>Name</th><th>Type</th>"
                   f"<th>Description</th><th></th></tr></thead><tbody>{rows_html}</tbody></table>")
    else:
        h_table = '<div class="empty">No holidays added yet.</div>'

    type_opts = "".join(f'<option value="{t}">{t}</option>' for t in HOLIDAY_TYPES)
    add_form = f"""
<form onsubmit="addHoliday(event,{int(item_id)})" style="display:grid;
  grid-template-columns:1fr 2fr 1fr 2fr auto;gap:8px;margin-bottom:14px">
  <input name="date" type="date" required>
  <input name="name" required placeholder="Holiday name">
  <select name="type">{type_opts}</select>
  <input name="description" placeholder="Description">
  <button>+ Add</button>
</form>
<script>
async function addHoliday(ev, calId) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const r = await fetch('/api/m/holiday_calendar/' + calId + '/holidays', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else alert('Add failed: ' + await r.text());
}}
async function deleteHoliday(hid) {{
  if (!confirm('Delete holiday?')) return;
  const r = await fetch('/api/m/holiday/' + hid, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""

    fields = [
        ("Name", row.get("name")),
        ("Region", row.get("region")),
        ("Year", row.get("year")),
        ("Default", "Yes" if row.get("is_default") else "No"),
        ("Notes", row.get("notes")),
    ]
    related = (detail_section(title="Add holiday", body_html=add_form)
               + detail_section(title="Holidays", body_html=h_table))
    handler._html(200, render_detail_page(
        title=row.get("name") or "Calendar",
        nav_active=NAME, subtitle=str(row.get("region") or row.get("year") or ""),
        fields=fields, related_html=related,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
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


def holiday_create_api(handler, calendar_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        hid = add_holiday(
            conn, int(calendar_id),
            name=payload.get("name") or "",
            date=payload.get("date") or "",
            holiday_type=payload.get("type") or "public",
            description=payload.get("description") or "")
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"id": hid}, code=201)


def holiday_delete_api(handler, holiday_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    conn.execute("DELETE FROM holiday WHERE id = ?", (int(holiday_id),))
    conn.commit()
    handler._json({"ok": True})


ROUTES = {
    "GET": [
        (r"^/api/m/holiday_calendar/(\d+)/?$", detail_api_json),
        (r"^/m/holiday_calendar/?$", list_view),
        (r"^/m/holiday_calendar/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/holiday_calendar/(\d+)/holidays/?$", holiday_create_api),
        (r"^/api/m/holiday_calendar/?$", create_api),
        (r"^/api/m/holiday_calendar/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/holiday/(\d+)/?$", holiday_delete_api),
        (r"^/api/m/holiday_calendar/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--name", required=True)
    parser.add_argument("--region")
    parser.add_argument("--year", type=int)


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "name": args.name,
        "region": getattr(args, "region", None),
        "year": getattr(args, "year", None),
    })
    log.info("calendar_added id=%s name=%s", new_id, args.name)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s holidays",
                 row["id"], row["name"], row.get("region") or "", row["holidays"])
    return 0


CLI = [
    ("calendar-add", _add_create_args, _handle_create),
    ("calendar-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "operations",
    "requires": [],
    "description": "Multiple holiday calendars per region / department / location.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
