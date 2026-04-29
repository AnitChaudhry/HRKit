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


def _coerce_bool(value: Any, *, default: bool = False) -> int:
    if value in (None, ""):
        return 1 if default else 0
    if isinstance(value, str):
        return 0 if value.strip().lower() in {"0", "false", "no", "off"} else 1
    return 1 if bool(value) else 0


def create_entry(conn, data: dict[str, Any]) -> int:
    employee_id = data.get("employee_id")
    project_id = data.get("project_id")
    date = (data.get("date") or "").strip()
    if not employee_id:
        raise ValueError("employee_id is required")
    if not project_id:
        raise ValueError("project_id is required")
    if not date:
        raise ValueError("date is required")
    try:
        hours = float(data.get("hours"))
    except (TypeError, ValueError) as exc:
        raise ValueError("hours must be numeric") from exc
    if hours <= 0 or hours > 24:
        raise ValueError("hours must be between 0 and 24")
    cur = conn.execute(
        """
        INSERT INTO timesheet_entry(
            employee_id, project_id, date, hours, billable, description
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(employee_id),
            int(project_id),
            date,
            hours,
            _coerce_bool(data.get("billable"), default=True),
            data.get("description") or "",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_entry(conn, entry_id: int, data: dict[str, Any]) -> None:
    fields: list[str] = []
    values: list[Any] = []
    for key in ("employee_id", "project_id", "date", "description", "approved_by"):
        if key in data:
            value = data[key]
            if key.endswith("_id") and value not in (None, ""):
                value = int(value)
            elif key.endswith("_id"):
                value = None
            fields.append(f"{key} = ?")
            values.append(value)
    if "hours" in data:
        try:
            hours = float(data["hours"])
        except (TypeError, ValueError) as exc:
            raise ValueError("hours must be numeric") from exc
        if hours <= 0 or hours > 24:
            raise ValueError("hours must be between 0 and 24")
        fields.append("hours = ?")
        values.append(hours)
    if "billable" in data:
        fields.append("billable = ?")
        values.append(_coerce_bool(data.get("billable"), default=True))
    if "approved" in data:
        fields.append("approved = ?")
        values.append(_coerce_bool(data.get("approved"), default=False))
    if "approved_at" in data:
        fields.append("approved_at = ?")
        values.append(data.get("approved_at") or "")
    if not fields:
        return
    values.append(int(entry_id))
    conn.execute(f"UPDATE timesheet_entry SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_entry(conn, entry_id):
    conn.execute("DELETE FROM timesheet_entry WHERE id = ?", (int(entry_id),))
    conn.commit()


def _emp_options(conn):
    return [{"id": r["id"], "label": r["full_name"]}
            for r in conn.execute(
                "SELECT id, full_name FROM employee ORDER BY full_name").fetchall()]


def _project_options(conn):
    return [{"id": r["id"], "label": r["name"]}
            for r in conn.execute(
                "SELECT id, name FROM project ORDER BY name").fetchall()]


def _render_list_html(rows, employees, projects) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}">{cells}'
            f'<td style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
            f'<a href="/m/timesheet/{row["id"]}" '
            f'style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;'
            f'color:var(--text);text-decoration:none;font-size:12px">Open</a>'
            f'<button onclick="openApprove({row["id"]})">Approve</button> '
            f'<button onclick="rejectEntry({row["id"]})">Reject</button> '
            f'<button onclick="del({row["id"]})">Delete</button>'
            f'</td></tr>')
    emp_opts = "".join(
        f'<option value="{int(e["id"])}">{_esc(e["label"])}</option>' for e in employees
    )
    project_opts = "".join(
        f'<option value="{int(p["id"])}">{_esc(p["label"])}</option>' for p in projects
    )
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Log time</button>
  <span style="color:var(--dim);font-size:13px;margin-left:auto">
    Showing the most recent 500 entries.</span>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<div style="color:var(--dim);font-size:12px;margin-bottom:10px">
  Time is logged on individual projects (Projects → project → Log time).
  This list is the cross-project view + approval queue.
</div>
<table class="data-table">
  <thead><tr>{head}<th>Actions</th></tr></thead>
  <tbody id="rows">{''.join(body_rows) or '<tr><td colspan="7" class="empty">No timesheet entries.</td></tr>'}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Employee*<select name="employee_id" required><option value="">-- employee --</option>{emp_opts}</select></label>
    <label>Project*<select name="project_id" required><option value="">-- project --</option>{project_opts}</select></label>
    <label>Date*<input name="date" type="date" required></label>
    <label>Hours*<input name="hours" type="number" step="0.25" min="0.25" max="24" required></label>
    <label>Billable<select name="billable"><option value="1" selected>Yes</option><option value="0">No</option></select></label>
    <label>Description<textarea name="description"></textarea></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Save</button>
    </menu>
  </form>
</dialog>
<dialog id="approve-dlg">
  <form onsubmit="submitApprove(event)">
    <input type="hidden" name="entry_id" id="approve-entry-id">
    <label>Approved by<select name="approver_id" required><option value="">-- approver --</option>{emp_opts}</select></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Approve</button>
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
  const r = await fetch('/api/m/timesheet', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload)
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
function openApprove(id) {{
  document.getElementById('approve-entry-id').value = id;
  document.getElementById('approve-dlg').showModal();
}}
async function submitApprove(ev) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const id = fd.get('entry_id');
  const r = await fetch('/api/m/timesheet/' + id + '/approve', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{approver_id: fd.get('approver_id')}})
  }});
  if (r.ok) location.reload(); else hrkit.toast('Approve failed', 'error');
}}
async function rejectEntry(id) {{
  const r = await fetch('/api/m/timesheet/' + id + '/reject', {{method:'POST'}});
  if (r.ok) location.reload(); else hrkit.toast('Reject failed', 'error');
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
        title=LABEL,
        nav_active=NAME,
        body_html=_render_list_html(
            list_rows(conn), _emp_options(conn), _project_options(conn)
        ),
    ))


def detail_api_json(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id):
    from hrkit.templates import render_detail_page, detail_section
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
    emp_opts = "".join(
        f'<option value="{int(e["id"])}">{_esc(e["label"])}</option>'
        for e in _emp_options(conn)
    )
    controls = f"""
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
  <select id="ts-approver" style="min-width:220px;padding:7px 10px;background:var(--bg);
    color:var(--text);border:1px solid var(--border);border-radius:6px">
    <option value="">-- approver --</option>{emp_opts}
  </select>
  <button onclick="approveFromDetail({int(item_id)})">Approve</button>
  <button onclick="rejectFromDetail({int(item_id)})">Reject</button>
</div>
<script>
async function approveFromDetail(id) {{
  const approver = document.getElementById('ts-approver').value;
  if (!approver) {{ hrkit.toast('Choose an approver first', 'info'); return; }}
  const r = await fetch('/api/m/timesheet/' + id + '/approve', {{
    method: 'POST', headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{approver_id: approver}})
  }});
  if (r.ok) location.reload(); else hrkit.toast('Approve failed: ' + await r.text(), 'error');
}}
async function rejectFromDetail(id) {{
  const r = await fetch('/api/m/timesheet/' + id + '/reject', {{method:'POST'}});
  if (r.ok) location.reload(); else hrkit.toast('Reject failed: ' + await r.text(), 'error');
}}
</script>
"""
    handler._html(200, render_detail_page(
        title=f"{row.get('hours')}h on {row.get('project') or 'project'}",
        nav_active=NAME, subtitle=row.get("date") or "",
        fields=fields,
        related_html=detail_section(title="Approval controls", body_html=controls),
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}",
        delete_redirect=f"/m/{NAME}",
        field_options={"billable": ["1", "0"], "approved": ["1", "0"]},
        exclude_edit_fields={"approved_by"},
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


def create_api(handler):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        entry_id = create_entry(conn, payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"id": entry_id}, code=201)


def update_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        update_entry(conn, int(item_id), payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
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
        (r"^/api/m/timesheet/?$", create_api),
        (r"^/api/m/timesheet/(\d+)/approve/?$", approve_api),
        (r"^/api/m/timesheet/(\d+)/reject/?$", reject_api),
        (r"^/api/m/timesheet/(\d+)/?$", update_api),
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
