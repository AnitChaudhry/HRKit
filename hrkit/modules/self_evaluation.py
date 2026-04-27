"""Self-evaluation module — employee fills own review.

Owns ``self_evaluation`` (migration 002). Optionally linked to a
``performance_review`` row when one exists.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "self_evaluation"
LABEL = "Self Evaluation"
ICON = "edit-3"

LIST_COLUMNS = ("employee", "period", "rating_self", "submitted_at")


def ensure_schema(conn): return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def list_rows(conn):
    cur = conn.execute("""
        SELECT s.id, s.employee_id, s.period, s.rating_self, s.submitted_at, s.created,
               e.full_name AS employee
        FROM self_evaluation s
        LEFT JOIN employee e ON e.id = s.employee_id
        ORDER BY s.submitted_at DESC, s.id DESC
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("""
        SELECT s.*, e.full_name AS employee
        FROM self_evaluation s
        LEFT JOIN employee e ON e.id = s.employee_id
        WHERE s.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    employee_id = data.get("employee_id")
    if not employee_id:
        raise ValueError("employee_id is required")
    cols = ["employee_id"]
    vals: list[Any] = [int(employee_id)]
    for key in ("period", "strengths", "areas_to_improve", "achievements",
                "goals_for_next_period"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    if data.get("rating_self") is not None:
        cols.append("rating_self"); vals.append(int(data["rating_self"]))
    if data.get("review_id") not in (None, ""):
        cols.append("review_id"); vals.append(int(data["review_id"]))
    submit_now = bool(data.get("submit"))
    if not submit_now and data.get("submitted_at") is not None:
        cols.append("submitted_at"); vals.append(data["submitted_at"])
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO self_evaluation ({', '.join(cols)}) VALUES ({placeholders})"
    if submit_now:
        # Switch the placeholder list to include the SQL expression directly.
        cols.append("submitted_at")
        sql = (f"INSERT INTO self_evaluation ({', '.join(cols)}) VALUES "
               f"({placeholders}, strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    cur = conn.execute(sql, vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("period", "strengths", "areas_to_improve", "achievements",
                "goals_for_next_period"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "rating_self" in data:
        fields.append("rating_self = ?"); values.append(int(data["rating_self"]))
    if "review_id" in data:
        fields.append("review_id = ?")
        values.append(int(data["review_id"]) if data["review_id"] else None)
    if data.get("submit"):
        fields.append("submitted_at = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE self_evaluation SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn, item_id):
    conn.execute("DELETE FROM self_evaluation WHERE id = ?", (item_id,))
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
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/self_evaluation/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New evaluation</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Employee*<select name="employee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Period<input name="period" placeholder="2026-Q1 / FY26 H1"></label>
    <label>Strengths<textarea name="strengths"></textarea></label>
    <label>Areas to improve<textarea name="areas_to_improve"></textarea></label>
    <label>Achievements<textarea name="achievements"></textarea></label>
    <label>Goals for next period<textarea name="goals_for_next_period"></textarea></label>
    <label>Self-rating (1-5)<input name="rating_self" type="number" min="1" max="5"></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit" name="action" value="save">Save draft</button>
      <button type="submit" name="action" value="submit">Submit</button>
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
  payload.submit = (ev.submitter && ev.submitter.value === 'submit');
  delete payload.action;
  const r = await fetch('/api/m/self_evaluation', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete?'))) return;
  const r = await fetch('/api/m/self_evaluation/' + id, {{method: 'DELETE'}});
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
    from hrkit.templates import render_detail_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No evaluation with id {int(item_id)}"))
        return
    fields = [
        ("Employee", row.get("employee")),
        ("Period", row.get("period")),
        ("Strengths", row.get("strengths")),
        ("Areas to improve", row.get("areas_to_improve")),
        ("Achievements", row.get("achievements")),
        ("Goals for next period", row.get("goals_for_next_period")),
        ("Self-rating", row.get("rating_self")),
        ("Submitted at", row.get("submitted_at") or "(draft)"),
        ("Linked review id", row.get("review_id")),
        ("Created", row.get("created")),
    ]
    handler._html(200, render_detail_page(
        title=f"Self-evaluation — {row.get('employee') or ''}",
        nav_active=NAME, subtitle=row.get("period") or "",
        fields=fields, item_id=int(item_id),
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


ROUTES = {
    "GET": [
        (r"^/api/m/self_evaluation/(\d+)/?$", detail_api_json),
        (r"^/m/self_evaluation/?$", list_view),
        (r"^/m/self_evaluation/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/self_evaluation/?$", create_api),
        (r"^/api/m/self_evaluation/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/self_evaluation/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--employee-id", type=int, required=True)
    parser.add_argument("--period")
    parser.add_argument("--rating-self", type=int)


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "employee_id": args.employee_id,
        "period": getattr(args, "period", None),
        "rating_self": getattr(args, "rating_self", None),
    })
    log.info("self_eval_added id=%s employee=%s", new_id, args.employee_id)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\trating=%s\t%s",
                 row["id"], row.get("employee") or "",
                 row.get("rating_self") or "-",
                 row.get("submitted_at") or "(draft)")
    return 0


CLI = [
    ("self-eval-add", _add_create_args, _handle_create),
    ("self-eval-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "performance",
    "requires": ["employee"],
    "description": "Employee self-evaluation — strengths, areas, rating, goals.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
