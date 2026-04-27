"""Goal module — OKR / KRA / objective tracking per employee.

Owns ``goal`` (migration 002). Self-referential parent-goal makes it work
for cascaded OKRs (company → team → individual).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "goal"
LABEL = "Goals"
ICON = "target"

LIST_COLUMNS = ("title", "employee", "category", "progress", "target_date", "status")
ALLOWED_STATUS = ("draft", "active", "at_risk", "completed", "cancelled")
ALLOWED_CATEGORY = ("performance", "development", "business", "behavioural")


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
        SELECT g.id, g.employee_id, g.title, g.category, g.target_date, g.status,
               g.weight, g.progress_percent, g.kra, g.parent_goal_id,
               e.full_name AS employee, p.title AS parent_title
        FROM goal g
        LEFT JOIN employee e ON e.id = g.employee_id
        LEFT JOIN goal p ON p.id = g.parent_goal_id
        ORDER BY g.target_date, g.id DESC
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["progress"] = f"{d.get('progress_percent') or 0}%"
        out.append(d)
    return out


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("""
        SELECT g.*, e.full_name AS employee, p.title AS parent_title
        FROM goal g
        LEFT JOIN employee e ON e.id = g.employee_id
        LEFT JOIN goal p ON p.id = g.parent_goal_id
        WHERE g.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    title = (data.get("title") or "").strip()
    employee_id = data.get("employee_id")
    if not title:
        raise ValueError("title is required")
    if not employee_id:
        raise ValueError("employee_id is required")
    status = (data.get("status") or "active").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    category = (data.get("category") or "performance").strip()
    if category not in ALLOWED_CATEGORY:
        raise ValueError(f"category must be one of {ALLOWED_CATEGORY}")
    cols = ["title", "employee_id", "status", "category"]
    vals: list[Any] = [title, int(employee_id), status, category]
    for key in ("description", "kra", "target_date"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    if data.get("weight") is not None:
        cols.append("weight"); vals.append(float(data["weight"]))
    if data.get("progress_percent") is not None:
        cols.append("progress_percent"); vals.append(int(data["progress_percent"]))
    if data.get("parent_goal_id") not in (None, ""):
        cols.append("parent_goal_id"); vals.append(int(data["parent_goal_id"]))
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO goal ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("title", "description", "category", "kra", "target_date", "status",
                "parent_goal_id"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "weight" in data:
        fields.append("weight = ?"); values.append(float(data["weight"]))
    if "progress_percent" in data:
        v = max(0, min(100, int(data["progress_percent"])))
        fields.append("progress_percent = ?"); values.append(v)
        if v >= 100:
            fields.append("status = 'completed'")
    if not fields:
        return
    fields.append("updated = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    values.append(item_id)
    conn.execute(f"UPDATE goal SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM goal WHERE id = ?", (item_id,))
    conn.commit()


def _emp_options(conn):
    return [{"id": r["id"], "label": r["full_name"]}
            for r in conn.execute(
                "SELECT id, full_name FROM employee ORDER BY full_name").fetchall()]


def _parent_options(conn):
    return [{"id": r["id"], "label": r["title"]}
            for r in conn.execute(
                "SELECT id, title FROM goal ORDER BY title").fetchall()]


def _render_list_html(rows, employees, parents) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/goal/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    cat_opts = "".join(f'<option value="{c}"{" selected" if c == "performance" else ""}>{c}</option>'
                       for c in ALLOWED_CATEGORY)
    parent_opts = "".join(f'<option value="{p["id"]}">{_esc(p["label"])}</option>' for p in parents)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New goal</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Title*<input name="title" required placeholder="Increase NPS by 10 points"></label>
    <label>Employee*<select name="employee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Category<select name="category">{cat_opts}</select></label>
    <label>KRA / Key result<textarea name="kra" placeholder="What measurable outcome?"></textarea></label>
    <label>Description<textarea name="description"></textarea></label>
    <label>Target date<input name="target_date" type="date"></label>
    <label>Weight<input name="weight" type="number" step="0.1" min="0" max="10" value="1.0"></label>
    <label>Progress %<input name="progress_percent" type="number" min="0" max="100" value="0"></label>
    <label>Parent goal (cascade)<select name="parent_goal_id"><option value="">--</option>{parent_opts}</select></label>
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
  if (payload.parent_goal_id === '') delete payload.parent_goal_id;
  const r = await fetch('/api/m/goal', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete goal #' + id + '?')) return;
  const r = await fetch('/api/m/goal/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""


def list_view(handler) -> None:
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME,
        body_html=_render_list_html(
            list_rows(conn), _emp_options(conn), _parent_options(conn))))


def detail_api_json(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No goal with id {int(item_id)}"))
        return
    children = conn.execute(
        "SELECT id, title, employee_id, progress_percent, status FROM goal "
        "WHERE parent_goal_id = ? ORDER BY title", (int(item_id),)).fetchall()
    if children:
        ch_rows = "".join(
            f"<tr><td><a href=\"/m/goal/{int(c['id'])}\">{_esc(c['title'])}</a></td>"
            f"<td>{c['progress_percent']}%</td><td>{_esc(c['status'])}</td></tr>"
            for c in children)
        children_body = (f"<table><thead><tr><th>Sub-goal</th><th>Progress</th>"
                         f"<th>Status</th></tr></thead><tbody>{ch_rows}</tbody></table>")
    else:
        children_body = '<div class="empty">No sub-goals.</div>'

    progress_form = f"""
<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
  <input id="prog" type="number" min="0" max="100" value="{row.get('progress_percent') or 0}"
    style="width:100px;padding:7px 10px;background:var(--bg);color:var(--text);
           border:1px solid var(--border);border-radius:6px">
  <button onclick="updateProgress({int(item_id)})">Update progress</button>
</div>
<script>
async function updateProgress(goalId) {{
  const v = parseInt(document.getElementById('prog').value, 10);
  const r = await fetch('/api/m/goal/' + goalId, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{progress_percent: v}})
  }});
  if (r.ok) location.reload(); else alert('Update failed: ' + await r.text());
}}
</script>
"""

    fields = [
        ("Title", row.get("title")),
        ("Employee", row.get("employee")),
        ("Category", row.get("category")),
        ("KRA / Key result", row.get("kra")),
        ("Description", row.get("description")),
        ("Target date", row.get("target_date")),
        ("Weight", row.get("weight")),
        ("Progress", f"{row.get('progress_percent') or 0}%"),
        ("Status", row.get("status")),
        ("Parent goal", row.get("parent_title")),
    ]
    related = (detail_section(title="Update progress", body_html=progress_form)
               + detail_section(title="Sub-goals", body_html=children_body))
    handler._html(200, render_detail_page(
        title=row.get("title") or "Goal", nav_active=NAME,
        subtitle=row.get("employee") or "",
        fields=fields, related_html=related,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"status": list(ALLOWED_STATUS),
                       "category": list(ALLOWED_CATEGORY)},
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
        (r"^/api/m/goal/(\d+)/?$", detail_api_json),
        (r"^/m/goal/?$", list_view),
        (r"^/m/goal/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/goal/?$", create_api),
        (r"^/api/m/goal/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/goal/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser) -> None:
    parser.add_argument("--title", required=True)
    parser.add_argument("--employee-id", type=int, required=True)
    parser.add_argument("--category", default="performance", choices=list(ALLOWED_CATEGORY))
    parser.add_argument("--kra")
    parser.add_argument("--target-date")
    parser.add_argument("--weight", type=float, default=1.0)


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "title": args.title,
        "employee_id": args.employee_id,
        "category": args.category,
        "kra": getattr(args, "kra", None),
        "target_date": getattr(args, "target_date", None),
        "weight": args.weight,
    })
    log.info("goal_added id=%s title=%s", new_id, args.title)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s\t%s", row["id"], row["status"],
                 row["progress"], row.get("employee") or "", row["title"])
    return 0


CLI = [
    ("goal-add", _add_create_args, _handle_create),
    ("goal-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "performance",
    "requires": ["employee"],
    "description": "OKR / KRA / objective tracking with cascaded parent-goal hierarchy.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
