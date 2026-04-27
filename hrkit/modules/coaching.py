"""Coaching module — 1:1 mentor / mentee sessions.

Owns ``coaching_session`` (migration 002).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "coaching"
LABEL = "Coaching"
ICON = "users-2"

LIST_COLUMNS = ("scheduled_at", "mentor", "mentee", "duration_minutes", "status")
ALLOWED_STATUS = ("scheduled", "completed", "cancelled", "no_show")


def ensure_schema(conn): return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def list_rows(conn):
    cur = conn.execute("""
        SELECT s.id, s.scheduled_at, s.duration_minutes, s.status,
               s.mentor_id, s.mentee_id, s.agenda,
               m.full_name AS mentor, n.full_name AS mentee
        FROM coaching_session s
        LEFT JOIN employee m ON m.id = s.mentor_id
        LEFT JOIN employee n ON n.id = s.mentee_id
        ORDER BY s.scheduled_at DESC
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("""
        SELECT s.*, m.full_name AS mentor, n.full_name AS mentee
        FROM coaching_session s
        LEFT JOIN employee m ON m.id = s.mentor_id
        LEFT JOIN employee n ON n.id = s.mentee_id
        WHERE s.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    mentor = data.get("mentor_id"); mentee = data.get("mentee_id")
    if not mentor or not mentee:
        raise ValueError("mentor_id and mentee_id are required")
    if int(mentor) == int(mentee):
        raise ValueError("mentor and mentee cannot be the same person")
    status = (data.get("status") or "scheduled").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["mentor_id", "mentee_id", "status"]
    vals: list[Any] = [int(mentor), int(mentee), status]
    for key in ("scheduled_at", "agenda", "notes", "action_items"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    if data.get("duration_minutes") is not None:
        cols.append("duration_minutes"); vals.append(int(data["duration_minutes"]))
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO coaching_session ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("scheduled_at", "agenda", "notes", "action_items", "status"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "duration_minutes" in data:
        fields.append("duration_minutes = ?"); values.append(int(data["duration_minutes"]))
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE coaching_session SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn, item_id):
    conn.execute("DELETE FROM coaching_session WHERE id = ?", (item_id,))
    conn.commit()


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
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/coaching/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Schedule session</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Mentor*<select name="mentor_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Mentee*<select name="mentee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Scheduled at<input name="scheduled_at" type="datetime-local"></label>
    <label>Duration (minutes)<input name="duration_minutes" type="number" min="5" max="240" value="30"></label>
    <label>Agenda<textarea name="agenda"></textarea></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Schedule</button>
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
  const r = await fetch('/api/m/coaching', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete?')) return;
  const r = await fetch('/api/m/coaching/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
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
    from hrkit.templates import render_detail_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No session with id {int(item_id)}"))
        return
    fields = [
        ("Mentor", row.get("mentor")),
        ("Mentee", row.get("mentee")),
        ("Scheduled at", row.get("scheduled_at")),
        ("Duration (min)", row.get("duration_minutes")),
        ("Status", row.get("status")),
        ("Agenda", row.get("agenda")),
        ("Notes", row.get("notes")),
        ("Action items", row.get("action_items")),
    ]
    handler._html(200, render_detail_page(
        title=f"{row.get('mentor') or '?'} → {row.get('mentee') or '?'}",
        nav_active=NAME, subtitle=row.get("scheduled_at") or "",
        fields=fields, item_id=int(item_id),
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


ROUTES = {
    "GET": [
        (r"^/api/m/coaching/(\d+)/?$", detail_api_json),
        (r"^/m/coaching/?$", list_view),
        (r"^/m/coaching/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/coaching/?$", create_api),
        (r"^/api/m/coaching/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/coaching/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--mentor-id", type=int, required=True)
    parser.add_argument("--mentee-id", type=int, required=True)
    parser.add_argument("--scheduled-at")
    parser.add_argument("--duration-minutes", type=int, default=30)


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "mentor_id": args.mentor_id,
        "mentee_id": args.mentee_id,
        "scheduled_at": getattr(args, "scheduled_at", None),
        "duration_minutes": args.duration_minutes,
    })
    log.info("coaching_session_added id=%s mentor=%s mentee=%s",
             new_id, args.mentor_id, args.mentee_id)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s -> %s\t%s",
                 row["id"], row["status"],
                 row.get("mentor") or "", row.get("mentee") or "",
                 row.get("scheduled_at") or "")
    return 0


CLI = [
    ("coaching-add", _add_create_args, _handle_create),
    ("coaching-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "talent",
    "requires": ["employee"],
    "description": "1:1 mentor/mentee coaching sessions with agenda + action items.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
