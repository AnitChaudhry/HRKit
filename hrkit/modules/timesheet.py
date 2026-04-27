"""Timesheet module — global timesheet view across projects.

Reads ``timesheet_entry`` (created by migration 002, written by ``project``).
This module is a *view* over the same table — it gives HR a per-employee /
weekly hours dashboard without going through individual project pages, and
adds approve/reject endpoints.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "timesheet"
LABEL = "Timesheets"
ICON = "clock"

LIST_COLUMNS = ("date", "employee", "project", "hours", "billable", "approved")


def ensure_schema(conn): return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def list_rows(conn):
    cur = conn.execute("""
        SELECT t.*, e.full_name AS employee, p.name AS project
        FROM timesheet_entry t
        LEFT JOIN employee e ON e.id = t.employee_id
        LEFT JOIN project p ON p.id = t.project_id
        ORDER BY t.date DESC, t.id DESC LIMIT 500
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["billable"] = "Yes" if d.get("billable") else "No"
        d["approved"] = "✓" if d.get("approved") else ""
        out.append(d)
    return out


def get_row(conn, item_id):
    cur = conn.execute("""
        SELECT t.*, e.full_name AS employee, p.name AS project,
               ap.full_name AS approver
        FROM timesheet_entry t
        LEFT JOIN employee e ON e.id = t.employee_id
        LEFT JOIN project p ON p.id = t.project_id
        LEFT JOIN employee ap ON ap.id = t.approved_by
        WHERE t.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def approve_entry(conn, entry_id: int, approver_id: int) -> None:
    conn.execute("""
        UPDATE timesheet_entry SET
          approved = 1,
          approved_by = ?,
          approved_at = strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')
        WHERE id = ?
    """, (int(approver_id), int(entry_id)))
    conn.commit()


def reject_entry(conn, entry_id: int) -> None:
    conn.execute("UPDATE timesheet_entry SET approved = 0, approved_by = NULL, approved_at = '' "
                 "WHERE id = ?", (int(entry_id),))
    conn.commit()


def delete_entry(conn, entry_id):
    conn.execute("DELETE FROM timesheet_entry WHERE id = ?", (int(entry_id),))
    conn.commit()


def _render_list_html(rows) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}">{cells}'
            f'<td>'
            f'<button onclick="approve({row["id"]})">Approve</button> '
            f'<button onclick="del({row["id"]})">Delete</button>'
            f'</td></tr>')
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <span style="color:var(--dim);font-size:13px;margin-left:auto">
    Showing the most recent 500 entries.</span>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<div style="color:var(--dim);font-size:12px;margin-bottom:10px">
  Time is logged on individual projects (Projects → project → Log time).
  This list is the cross-project view + approval queue.
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows) or '<tr><td colspan="7" class="empty">No timesheet entries.</td></tr>'}</tbody>
</table>
<script>
function filter(q) {{
  q = (q || '').toLowerCase();
  document.querySelectorAll('#rows tr').forEach(tr => {{
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
async function approve(id) {{
  const r = await fetch('/api/m/timesheet/' + id + '/approve', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{approver_id: 1}})
  }});
  if (r.ok) location.reload(); else hrkit.toast('Approve failed', 'error');
}}
async function del(id) {{
  if (!(await hrkit.confirmDialog('Delete entry?'))) return;
  const r = await fetch('/api/m/timesheet/' + id, {{method: 'DELETE'}});
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
    from hrkit.templates import render_detail_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No entry with id {int(item_id)}"))
        return
    fields = [
        ("Date", row.get("date")),
        ("Employee", row.get("employee")),
        ("Project", row.get("project")),
        ("Hours", row.get("hours")),
        ("Billable", "Yes" if row.get("billable") else "No"),
        ("Description", row.get("description")),
        ("Approved", "Yes" if row.get("approved") else "No"),
        ("Approved by", row.get("approver")),
        ("Approved at", row.get("approved_at")),
    ]
    handler._html(200, render_detail_page(
        title=f"{row.get('hours')}h on {row.get('project') or 'project'}",
        nav_active=NAME, subtitle=row.get("date") or "",
        fields=fields, item_id=int(item_id),
        delete_redirect=f"/m/{NAME}",
    ))


def approve_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    approver = payload.get("approver_id")
    if not approver:
        handler._json({"error": "approver_id required"}, code=400); return
    approve_entry(conn, int(item_id), int(approver))
    handler._json({"ok": True})


def reject_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    reject_entry(conn, int(item_id))
    handler._json({"ok": True})


def delete_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    delete_entry(conn, int(item_id))
    handler._json({"ok": True})


ROUTES = {
    "GET": [
        (r"^/api/m/timesheet/(\d+)/?$", detail_api_json),
        (r"^/m/timesheet/?$", list_view),
        (r"^/m/timesheet/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/timesheet/(\d+)/approve/?$", approve_api),
        (r"^/api/m/timesheet/(\d+)/reject/?$", reject_api),
    ],
    "DELETE": [
        (r"^/api/m/timesheet/(\d+)/?$", delete_api),
    ],
}


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%sh\t%s",
                 row["id"], row["date"], row.get("employee") or "",
                 row.get("hours") or 0, row.get("project") or "")
    return 0


CLI = [
    ("timesheet-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "operations",
    "requires": ["employee", "project"],
    "description": "Cross-project timesheet view + approval queue.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
