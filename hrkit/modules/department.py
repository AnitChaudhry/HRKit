"""Department HR module.

Owns CRUD over the ``department`` table. Self-referential (a department may
have a parent department) and cross-references ``employee`` via
``head_employee_id``. Schema lives in migration 001.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "department"
LABEL = "Departments"
ICON = "building"

LIST_COLUMNS = ("name", "code", "head_employee", "parent")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def ensure_schema(conn: sqlite3.Connection) -> None:
    """No-op. The ``department`` table is created by migration 001."""
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT d.id, d.name, d.code, d.head_employee_id, d.parent_department_id,
               d.notes,
               e.full_name AS head_employee,
               p.name AS parent
        FROM department d
        LEFT JOIN employee e ON e.id = d.head_employee_id
        LEFT JOIN department p ON p.id = d.parent_department_id
        ORDER BY d.name
        """
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM department WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    cols: list[str] = ["name"]
    vals: list[Any] = [name]
    for key in ("code", "notes"):
        if data.get(key) is not None:
            cols.append(key)
            vals.append(data[key])
    for key in ("head_employee_id", "parent_department_id"):
        if data.get(key) not in (None, ""):
            cols.append(key)
            vals.append(data[key])

    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO department ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields: list[str] = []
    values: list[Any] = []
    for key in ("name", "code", "head_employee_id", "parent_department_id", "notes"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE department SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM department WHERE id = ?", (item_id,))
    conn.commit()


def _list_employees(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT id, full_name AS label FROM employee ORDER BY full_name")
    return [{"id": r["id"], "label": r["label"]} for r in cur.fetchall()]


def _list_departments(conn: sqlite3.Connection,
                      exclude_id: int | None = None) -> list[dict[str, Any]]:
    if exclude_id is None:
        cur = conn.execute("SELECT id, name AS label FROM department ORDER BY name")
    else:
        cur = conn.execute(
            "SELECT id, name AS label FROM department WHERE id != ? ORDER BY name",
            (exclude_id,),
        )
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
                      employees: list[dict[str, Any]],
                      parents: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}">{cells}'
            f'<td><button onclick="deleteRow({row["id"]})">Delete</button></td></tr>'
        )
    emp_opts = "".join(
        f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees
    )
    parent_opts = "".join(
        f'<option value="{p["id"]}">{_esc(p["label"])}</option>' for p in parents
    )
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Department</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Name*<input name="name" required></label>
    <label>Code<input name="code"></label>
    <label>Head employee<select name="head_employee_id"><option value="">--</option>{emp_opts}</select></label>
    <label>Parent department<select name="parent_department_id"><option value="">--</option>{parent_opts}</select></label>
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
  for (const k of ['head_employee_id','parent_department_id']) if (payload[k] === '') delete payload[k];
  const r = await fetch('/api/m/department', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete department #' + id + '?')) return;
  const r = await fetch('/api/m/department/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
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
    body = _render_list_html(rows, _list_employees(conn), _list_departments(conn))
    handler._html(200, render_module_page(title=LABEL, nav_active=NAME, body_html=body))


def detail_api_json(handler, item_id: int) -> None:
    """Return the raw department row as JSON (back-compat for API clients)."""
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
                subtitle=f"No department with id {int(item_id)}",
            ),
        )
        return

    # Resolve FK names for the field grid.
    head_name = ""
    if row.get("head_employee_id"):
        cur = conn.execute(
            "SELECT full_name FROM employee WHERE id = ?", (row["head_employee_id"],)
        )
        r = cur.fetchone()
        if r:
            head_name = r["full_name"]
    parent_name = ""
    if row.get("parent_department_id"):
        cur = conn.execute(
            "SELECT name FROM department WHERE id = ?", (row["parent_department_id"],)
        )
        r = cur.fetchone()
        if r:
            parent_name = r["name"]

    fields: list[tuple[str, Any]] = [
        ("Name", row.get("name")),
        ("Code", row.get("code")),
        ("Head employee", head_name),
        ("Parent department", parent_name),
        ("Notes", row.get("notes")),
        ("Created", row.get("created")),
        ("Updated", row.get("updated")),
    ]

    emp_cur = conn.execute(
        "SELECT id, employee_code, full_name, email, status FROM employee "
        "WHERE department_id = ? ORDER BY full_name",
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
        emp_body = '<div class="empty">No employees in this department.</div>'

    related_html = detail_section(title="Employees", body_html=emp_body)

    html = render_detail_page(
        title=row.get("name") or "Department",
        nav_active=NAME,
        subtitle=row.get("code") or "",
        fields=fields,
        related_html=related_html,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}",
        delete_redirect=f"/m/{NAME}",
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
        (r"^/api/m/department/(\d+)/?$", detail_api_json),
        (r"^/m/department/?$", list_view),
        (r"^/m/department/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/department/?$", create_api),
        (r"^/api/m/department/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/department/(\d+)/?$", delete_api),
    ],
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_create_args(parser) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--code")
    parser.add_argument("--head-employee-id", type=int)
    parser.add_argument("--parent-department-id", type=int)
    parser.add_argument("--notes")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "name": args.name,
        "code": getattr(args, "code", None),
        "head_employee_id": getattr(args, "head_employee_id", None),
        "parent_department_id": getattr(args, "parent_department_id", None),
        "notes": getattr(args, "notes", None),
    })
    log.info("department_added id=%s name=%s", new_id, args.name)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s", row["id"], row["name"], row.get("code") or "")
    return 0


CLI = [
    ("department-add", _add_create_args, _handle_create),
    ("department-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "core",
    "requires": [],
    "description": "Org tree with departments, heads, and parent departments.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
