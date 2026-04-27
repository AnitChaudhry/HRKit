"""Skill module — measurable per-employee skills inventory.

Owns ``skill`` (catalog) and ``employee_skill`` (employee↔skill map with level)
from migration 002. Exposes both: list of skills, plus a per-employee section.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "skill"
LABEL = "Skills"
ICON = "award"

LIST_COLUMNS = ("name", "category", "employees")
LEVELS = ("beginner", "intermediate", "advanced", "expert")


def ensure_schema(conn: sqlite3.Connection) -> None:
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("""
        SELECT s.id, s.name, s.category, s.description,
               (SELECT COUNT(*) FROM employee_skill es WHERE es.skill_id = s.id) AS employees
        FROM skill s ORDER BY s.name
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM skill WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    cols = ["name"]
    vals: list[Any] = [name]
    for key in ("category", "description"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO skill ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("name", "category", "description"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE skill SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM skill WHERE id = ?", (item_id,))
    conn.commit()


def add_employee_skill(conn: sqlite3.Connection, employee_id: int,
                       skill_id: int, level: str = "intermediate",
                       endorsed_by: int | None = None) -> int:
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    cur = conn.execute("""
        INSERT INTO employee_skill (employee_id, skill_id, level, endorsed_by, endorsed_at)
        VALUES (?, ?, ?, ?,
                CASE WHEN ? IS NULL THEN '' ELSE strftime('%Y-%m-%dT%H:%M:%S','now','+05:30') END)
        ON CONFLICT(employee_id, skill_id) DO UPDATE SET
          level = excluded.level,
          endorsed_by = excluded.endorsed_by
    """, (int(employee_id), int(skill_id), level, endorsed_by, endorsed_by))
    conn.commit()
    return int(cur.lastrowid or 0)


def remove_employee_skill(conn: sqlite3.Connection, employee_id: int, skill_id: int) -> None:
    conn.execute("DELETE FROM employee_skill WHERE employee_id = ? AND skill_id = ?",
                 (int(employee_id), int(skill_id)))
    conn.commit()


def _render_list_html(rows: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/skill/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Skill</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Name*<input name="name" required placeholder="Python / Public speaking / SQL"></label>
    <label>Category<input name="category" placeholder="technical / soft / language / tool"></label>
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
  const r = await fetch('/api/m/skill', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete skill #' + id + '?')) return;
  const r = await fetch('/api/m/skill/' + id, {{method: 'DELETE'}});
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
                      subtitle=f"No skill with id {int(item_id)}"))
        return
    holders = conn.execute("""
        SELECT e.id, e.full_name, e.employee_code, es.level, es.endorsed_at
        FROM employee_skill es
        JOIN employee e ON e.id = es.employee_id
        WHERE es.skill_id = ?
        ORDER BY CASE es.level WHEN 'expert' THEN 0 WHEN 'advanced' THEN 1
                 WHEN 'intermediate' THEN 2 WHEN 'beginner' THEN 3 END,
                 e.full_name
    """, (int(item_id),)).fetchall()
    if holders:
        rows_html = "".join(
            f"<tr><td>{_esc(h['employee_code'])}</td>"
            f"<td><a href=\"/m/employee/{int(h['id'])}\">{_esc(h['full_name'])}</a></td>"
            f"<td>{_esc(h['level'])}</td><td>{_esc(h['endorsed_at'])}</td></tr>"
            for h in holders)
        emp_body = (f"<table><thead><tr><th>Code</th><th>Employee</th><th>Level</th>"
                    f"<th>Endorsed at</th></tr></thead><tbody>{rows_html}</tbody></table>")
    else:
        emp_body = '<div class="empty">No employees have this skill yet.</div>'
    fields = [
        ("Name", row.get("name")),
        ("Category", row.get("category")),
        ("Description", row.get("description")),
    ]
    handler._html(200, render_detail_page(
        title=row.get("name") or "Skill",
        nav_active=NAME, subtitle=row.get("category") or "",
        fields=fields,
        related_html=detail_section(title="Employees with this skill", body_html=emp_body),
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


def employee_skill_api(handler, employee_id: int) -> None:
    """GET → list employee's skills; POST → add/update; DELETE-as-POST with action."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    method = (getattr(handler, "command", "") or "").upper()
    if method == "GET":
        rows = conn.execute("""
            SELECT s.id, s.name, s.category, es.level, es.endorsed_at,
                   eb.full_name AS endorsed_by_name
            FROM employee_skill es
            JOIN skill s ON s.id = es.skill_id
            LEFT JOIN employee eb ON eb.id = es.endorsed_by
            WHERE es.employee_id = ? ORDER BY s.name
        """, (int(employee_id),)).fetchall()
        handler._json({"ok": True, "skills": [_row_to_dict(r) for r in rows]})
        return
    payload = handler._read_json() or {}
    action = (payload.get("action") or "add").lower()
    skill_id = payload.get("skill_id")
    if not skill_id:
        handler._json({"error": "skill_id required"}, code=400); return
    if action == "remove":
        remove_employee_skill(conn, int(employee_id), int(skill_id))
        handler._json({"ok": True})
        return
    try:
        add_employee_skill(conn, int(employee_id), int(skill_id),
                           level=(payload.get("level") or "intermediate"),
                           endorsed_by=payload.get("endorsed_by"))
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True})


ROUTES = {
    "GET": [
        (r"^/api/m/skill/(\d+)/?$", detail_api_json),
        (r"^/api/m/employee/(\d+)/skills/?$", employee_skill_api),
        (r"^/m/skill/?$", list_view),
        (r"^/m/skill/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/employee/(\d+)/skills/?$", employee_skill_api),
        (r"^/api/m/skill/?$", create_api),
        (r"^/api/m/skill/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/skill/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--category")
    parser.add_argument("--description")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "name": args.name,
        "category": getattr(args, "category", None),
        "description": getattr(args, "description", None),
    })
    log.info("skill_added id=%s name=%s", new_id, args.name)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t(%s holders)", row["id"], row["name"], row.get("employees") or 0)
    return 0


CLI = [
    ("skill-add", _add_create_args, _handle_create),
    ("skill-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "talent",
    "requires": ["employee"],
    "description": "Skill catalog + per-employee level (beginner → expert).",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
