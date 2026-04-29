"""Role HR module.

Owns CRUD over the ``role`` table. Each role belongs to a department and
defines a job title plus a numeric level (e.g. IC1, IC2). Schema lives in
migration 001.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "role"
LABEL = "Roles"
ICON = "briefcase"

LIST_COLUMNS = ("title", "department", "level")

# Canonical HR ladder, low → high. Used as suggestions for the role.level
# field. Stored as free text in the DB so legacy values (e.g. "IC2") still
# round-trip; the UI presents this list as a datalist for new entries.
HR_LEVELS: tuple[str, ...] = (
    "Intern",
    "Junior",
    "Senior",
    "Team Lead",
    "Assistant Manager",
    "Manager",
    "Senior Manager",
    "Director",
    "VP",
)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def ensure_schema(conn: sqlite3.Connection) -> None:
    """No-op. The ``role`` table is created by migration 001."""
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT r.id, r.title, r.department_id, r.level, r.description,
               d.name AS department
        FROM role r
        LEFT JOIN department d ON d.id = r.department_id
        ORDER BY r.title
        """
    )
    return [_row_to_dict(row) for row in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM role WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")

    cols: list[str] = ["title"]
    vals: list[Any] = [title]
    for key in ("level", "description"):
        if data.get(key) is not None:
            cols.append(key)
            vals.append(data[key])
    if data.get("department_id") not in (None, ""):
        cols.append("department_id")
        vals.append(data["department_id"])

    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO role ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields: list[str] = []
    values: list[Any] = []
    for key in ("title", "department_id", "level", "description"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE role SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM role WHERE id = ?", (item_id,))
    conn.commit()


def _list_departments(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT id, name AS label FROM department ORDER BY name")
    return [{"id": r["id"], "label": r["label"]} for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_list_html(rows: list[dict[str, Any]],
                      departments: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}">{cells}'
            f'<td style="display:flex;gap:8px;align-items:center">'
            f'<a href="/m/role/{row["id"]}" '
            f'style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;'
            f'color:var(--text);text-decoration:none;font-size:12px">Open</a>'
            f'<button onclick="deleteRow({row["id"]})">Delete</button></td></tr>'
        )
    dept_opts = "".join(
        f'<option value="{d["id"]}">{_esc(d["label"])}</option>' for d in departments
    )
    level_opts = "".join(f'<option value="{_esc(l)}">' for l in HR_LEVELS)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Role</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<datalist id="hr-levels">{level_opts}</datalist>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Title*<input name="title" required placeholder="e.g. Senior Engineer"></label>
    <label>Department<select name="department_id"><option value="">--</option>{dept_opts}</select></label>
    <label>HR Level<input name="level" list="hr-levels" placeholder="Pick or type..."></label>
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
  if (payload.department_id === '') delete payload.department_id;
  const r = await fetch('/api/m/role', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete role #' + id + '?'))) return;
  const r = await fetch('/api/m/role/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else hrkit.toast('Delete failed', 'error');
}}
</script>
"""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def list_view(handler) -> None:
    from hrkit.templates import render_module_page

    conn = handler.server.conn  # type: ignore[attr-defined]
    rows = list_rows(conn)
    body = _render_list_html(rows, _list_departments(conn))
    handler._html(200, render_module_page(title=LABEL, nav_active=NAME, body_html=body))


def detail_api_json(handler, item_id: int) -> None:
    """Return the raw role row as JSON (back-compat for API clients)."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section

    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(
            404,
            render_detail_page(
                title="Not found",
                nav_active=NAME,
                subtitle=f"No role with id {int(item_id)}",
            ),
        )
        return

    dept_name = ""
    if row.get("department_id"):
        cur = conn.execute(
            "SELECT name FROM department WHERE id = ?", (row["department_id"],)
        )
        r = cur.fetchone()
        if r:
            dept_name = r["name"]

    fields: list[tuple[str, Any]] = [
        ("Title", row.get("title")),
        ("Department", dept_name),
        ("Level", row.get("level")),
        ("Description", row.get("description")),
        ("Created", row.get("created")),
        ("Updated", row.get("updated")),
    ]

    emp_cur = conn.execute(
        "SELECT id, employee_code, full_name, email, status FROM employee "
        "WHERE role_id = ? ORDER BY full_name",
        (int(item_id),),
    )
    emp_rows = emp_cur.fetchall()
    if emp_rows:
        emp_body = (
            "<table><thead><tr><th>Code</th><th>Name</th>"
            "<th>Email</th><th>Status</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{_esc(e['employee_code'])}</td>"
                f"<td><a href=\"/m/employee/{int(e['id'])}\">{_esc(e['full_name'])}</a></td>"
                f"<td>{_esc(e['email'])}</td><td>{_esc(e['status'])}</td></tr>"
                for e in emp_rows
            )
            + "</tbody></table>"
        )
    else:
        emp_body = '<div class="empty">No employees with this role.</div>'

    current_dept = row.get("department_id")
    dept_options = ['<option value="">-- no department --</option>']
    for dept in _list_departments(conn):
        sel = " selected" if current_dept and int(current_dept) == int(dept["id"]) else ""
        dept_options.append(
            f'<option value="{int(dept["id"])}"{sel}>{_esc(dept["label"])}</option>'
        )
    dept_body = f"""
<style>
  .role-dept-row{{display:flex;gap:8px;align-items:center;margin-bottom:10px}}
  .role-dept-row label{{flex:0 0 96px;color:var(--dim);font-size:12px;margin:0}}
  .role-dept-row select{{flex:1;padding:7px 10px;background:var(--bg);
    color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:13px}}
  .role-dept-row button{{padding:7px 14px;border-radius:6px;background:var(--accent);
    color:#fff;border:none;cursor:pointer;font-size:12px}}
</style>
<div class="role-dept-row">
  <label>Department</label>
  <select id="role-dept-picker">{''.join(dept_options)}</select>
  <button onclick="saveRoleDepartment({int(item_id)})">Update</button>
</div>
<script>
async function saveRoleDepartment(id) {{
  const sel = document.getElementById('role-dept-picker');
  const payload = {{department_id: sel.value === '' ? null : parseInt(sel.value, 10)}};
  const r = await fetch('/api/m/role/' + id, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload();
  else hrkit.toast('Update failed: ' + await r.text(), 'error');
}}
</script>
"""

    related_html = (
        detail_section(title="Department assignment", body_html=dept_body)
        + detail_section(title="Employees", body_html=emp_body)
    )

    subtitle_bits = [b for b in (dept_name, row.get("level")) if b]
    html = render_detail_page(
        title=row.get("title") or "Role",
        nav_active=NAME,
        subtitle=" · ".join(subtitle_bits),
        fields=fields,
        related_html=related_html,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}",
        delete_redirect=f"/m/{NAME}",
        field_options={"level": list(HR_LEVELS)},
        exclude_edit_fields={"department", "created", "updated"},
    )
    handler._html(200, html)


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


ROUTES = {
    "GET": [
        (r"^/api/m/role/(\d+)/?$", detail_api_json),
        (r"^/m/role/?$", list_view),
        (r"^/m/role/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/role/?$", create_api),
        (r"^/api/m/role/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/role/(\d+)/?$", delete_api),
    ],
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_create_args(parser) -> None:
    parser.add_argument("--title", required=True)
    parser.add_argument("--department-id", type=int)
    parser.add_argument("--level")
    parser.add_argument("--description")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "title": args.title,
        "department_id": getattr(args, "department_id", None),
        "level": getattr(args, "level", None),
        "description": getattr(args, "description", None),
    })
    log.info("role_added id=%s title=%s", new_id, args.title)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s", row["id"], row["title"], row.get("level") or "")
    return 0


CLI = [
    ("role-add", _add_create_args, _handle_create),
    ("role-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "core",
    "requires": ["department"],
    "description": "Job titles and HR levels (Team Lead, Manager, Director, ...) per department.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
