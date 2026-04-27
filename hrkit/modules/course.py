"""Course module — eLearning / training catalog + per-employee enrollment.

Owns ``course`` and ``course_enrollment`` (migration 002).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "course"
LABEL = "Courses"
ICON = "graduation-cap"

LIST_COLUMNS = ("title", "category", "instructor", "duration_hours", "enrolled", "status")
ALLOWED_STATUS = ("draft", "active", "archived")
ENROLL_STATUS = ("enrolled", "in_progress", "completed", "dropped")


def ensure_schema(conn): return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def list_rows(conn):
    cur = conn.execute("""
        SELECT c.*,
               (SELECT COUNT(*) FROM course_enrollment ce WHERE ce.course_id = c.id) AS enrolled
        FROM course c ORDER BY c.title
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("SELECT * FROM course WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    status = (data.get("status") or "active").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["title", "status"]; vals: list[Any] = [title, status]
    for key in ("description", "instructor", "category", "url"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    if data.get("duration_hours") is not None:
        cols.append("duration_hours"); vals.append(float(data["duration_hours"]))
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO course ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("title", "description", "instructor", "category", "url", "status"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "duration_hours" in data:
        fields.append("duration_hours = ?"); values.append(float(data["duration_hours"]))
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE course SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn, item_id):
    conn.execute("DELETE FROM course WHERE id = ?", (item_id,))
    conn.commit()


def enroll(conn, course_id: int, employee_id: int, status: str = "enrolled") -> int:
    if status not in ENROLL_STATUS:
        raise ValueError(f"status must be one of {ENROLL_STATUS}")
    try:
        cur = conn.execute("""
            INSERT INTO course_enrollment (course_id, employee_id, status)
            VALUES (?, ?, ?)
        """, (int(course_id), int(employee_id), status))
        conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        existing = conn.execute(
            "SELECT id FROM course_enrollment WHERE course_id = ? AND employee_id = ?",
            (int(course_id), int(employee_id))).fetchone()
        return int(existing["id"]) if existing else 0


def update_enrollment(conn, enrollment_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("status", "feedback"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "score" in data:
        fields.append("score = ?"); values.append(float(data["score"]))
    if data.get("status") == "completed":
        fields.append("completed_at = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    if not fields:
        return
    values.append(int(enrollment_id))
    conn.execute(f"UPDATE course_enrollment SET {', '.join(fields)} WHERE id = ?", values)
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
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/course/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New course</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Title*<input name="title" required></label>
    <label>Category<input name="category" placeholder="onboarding / compliance / technical"></label>
    <label>Instructor<input name="instructor"></label>
    <label>Duration (hours)<input name="duration_hours" type="number" step="0.5" min="0"></label>
    <label>External URL<input name="url" type="url" placeholder="https://..."></label>
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
  const r = await fetch('/api/m/course', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete?')) return;
  const r = await fetch('/api/m/course/' + id, {{method: 'DELETE'}});
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
                      subtitle=f"No course with id {int(item_id)}"))
        return
    enrolls = conn.execute("""
        SELECT ce.id, ce.status, ce.score, ce.enrolled_at, ce.completed_at,
               e.id AS employee_id, e.full_name, e.employee_code
        FROM course_enrollment ce
        JOIN employee e ON e.id = ce.employee_id
        WHERE ce.course_id = ? ORDER BY ce.enrolled_at DESC
    """, (int(item_id),)).fetchall()
    if enrolls:
        rows_html = "".join(
            f"<tr><td>{_esc(en['employee_code'])}</td>"
            f"<td><a href=\"/m/employee/{int(en['employee_id'])}\">{_esc(en['full_name'])}</a></td>"
            f"<td>{_esc(en['status'])}</td><td>{_esc(en['score'])}</td>"
            f"<td>{_esc(en['enrolled_at'])}</td><td>{_esc(en['completed_at'])}</td></tr>"
            for en in enrolls)
        en_table = (f"<table><thead><tr><th>Code</th><th>Employee</th><th>Status</th>"
                    f"<th>Score</th><th>Enrolled</th><th>Completed</th>"
                    f"</tr></thead><tbody>{rows_html}</tbody></table>")
    else:
        en_table = '<div class="empty">No enrollments yet.</div>'

    emps = _emp_options(conn)
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in emps)
    enroll_form = f"""
<form onsubmit="enrollEmp(event,{int(item_id)})" style="display:flex;gap:8px;align-items:end;margin-bottom:14px">
  <label style="flex:1">Employee
    <select name="employee_id" required style="width:100%;padding:7px 10px;
      background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px">
      <option value="">--</option>{emp_opts}
    </select>
  </label>
  <button>+ Enroll</button>
</form>
<script>
async function enrollEmp(ev, courseId) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const r = await fetch('/api/m/course/' + courseId + '/enroll', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else alert('Enroll failed: ' + await r.text());
}}
</script>
"""

    fields = [
        ("Title", row.get("title")),
        ("Category", row.get("category")),
        ("Instructor", row.get("instructor")),
        ("Duration (hours)", row.get("duration_hours")),
        ("URL", row.get("url")),
        ("Status", row.get("status")),
        ("Description", row.get("description")),
    ]
    related = (detail_section(title="Enroll employee", body_html=enroll_form)
               + detail_section(title="Enrollments", body_html=en_table))
    handler._html(200, render_detail_page(
        title=row.get("title") or "Course", nav_active=NAME,
        subtitle=row.get("category") or "",
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


def enroll_api(handler, course_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    emp = payload.get("employee_id")
    if not emp:
        handler._json({"error": "employee_id required"}, code=400); return
    try:
        eid = enroll(conn, int(course_id), int(emp))
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True, "enrollment_id": eid})


ROUTES = {
    "GET": [
        (r"^/api/m/course/(\d+)/?$", detail_api_json),
        (r"^/m/course/?$", list_view),
        (r"^/m/course/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/course/(\d+)/enroll/?$", enroll_api),
        (r"^/api/m/course/?$", create_api),
        (r"^/api/m/course/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/course/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--title", required=True)
    parser.add_argument("--category")
    parser.add_argument("--instructor")
    parser.add_argument("--duration-hours", type=float)


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "title": args.title,
        "category": getattr(args, "category", None),
        "instructor": getattr(args, "instructor", None),
        "duration_hours": getattr(args, "duration_hours", None),
    })
    log.info("course_added id=%s title=%s", new_id, args.title)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t(%s enrolled)",
                 row["id"], row["status"], row["title"], row.get("enrolled") or 0)
    return 0


CLI = [
    ("course-add", _add_create_args, _handle_create),
    ("course-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "talent",
    "requires": ["employee"],
    "description": "eLearning catalog with per-employee enrollment + completion tracking.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
