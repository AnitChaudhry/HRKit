"""Employee HR module.

Owns CRUD over the ``employee`` table created by migration
``001_full_hr_schema.sql``. This file follows the registry contract from
AGENTS_SPEC.md Section 1 — a single top-level ``MODULE`` dict, no top-level
side effects, stdlib only.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

NAME = "employee"
LABEL = "Employees"
ICON = "users"

# Columns shown in the list view (in order).
LIST_COLUMNS = (
    "employee_code",
    "full_name",
    "email",
    "department",
    "role",
    "status",
)

# Allowed values for employee.status (mirrors the CHECK constraint in 001).
ALLOWED_STATUS = ("active", "on_leave", "exited")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def ensure_schema(conn: sqlite3.Connection) -> None:
    """No-op. The ``employee`` table is created by migration 001."""
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all employees joined with department and role names."""
    cur = conn.execute(
        """
        SELECT e.id, e.employee_code, e.full_name, e.email, e.phone,
               e.hire_date, e.employment_type, e.status, e.salary_minor,
               e.department_id, e.role_id, e.manager_id, e.location,
               d.name AS department, r.title AS role
        FROM employee e
        LEFT JOIN department d ON d.id = e.department_id
        LEFT JOIN role r ON r.id = e.role_id
        ORDER BY e.full_name
        """
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute(
        """
        SELECT e.*, d.name AS department, r.title AS role
        FROM employee e
        LEFT JOIN department d ON d.id = e.department_id
        LEFT JOIN role r ON r.id = e.role_id
        WHERE e.id = ?
        """,
        (item_id,),
    )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def _coerce_salary_minor(payload: dict[str, Any]) -> int | None:
    """Accept ``salary_minor`` (paise) or ``salary`` (rupees) from the payload."""
    if "salary_minor" in payload and payload["salary_minor"] not in (None, ""):
        return int(payload["salary_minor"])
    if "salary" in payload and payload["salary"] not in (None, ""):
        # Rupees -> paise. Accept the formatted display value too, e.g.
        # "₹95,000.00", because the generic edit dialog reuses display text.
        salary_text = str(payload["salary"]).strip().replace(",", "")
        candidates: list[str] = []
        buf: list[str] = []
        for ch in salary_text:
            if ch.isdigit() or ch == ".":
                buf.append(ch)
            elif buf:
                candidates.append("".join(buf))
                buf = []
        if buf:
            candidates.append("".join(buf))
        salary_text = max(
            candidates,
            key=lambda value: sum(1 for ch in value if ch.isdigit()),
            default="",
        )
        if not salary_text or not any(ch.isdigit() for ch in salary_text):
            return None
        rupees = float(salary_text)
        return int(round(rupees * 100))
    return None


def _next_employee_code(conn: sqlite3.Connection) -> str:
    """Generate an EMP-NNNN code if none was supplied. Migration 001 marks
    ``employee_code`` as ``NOT NULL UNIQUE`` with no default, so we must
    always provide a value."""
    cur = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS nxt FROM employee")
    return f"EMP-{int(cur.fetchone()['nxt']):04d}"


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    """Insert an employee row. Returns the new id."""
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip()
    if not full_name:
        raise ValueError("full_name is required")
    if not email:
        raise ValueError("email is required")

    status = (data.get("status") or "active").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")

    employee_code = data.get("employee_code")
    if not employee_code:
        employee_code = _next_employee_code(conn)

    metadata = data.get("metadata_json")
    if isinstance(metadata, dict):
        metadata = json.dumps(metadata)

    # Only include columns the caller actually supplied so SQLite applies the
    # NOT NULL DEFAULT '' from migration 001 for the rest.
    cols: list[str] = ["employee_code", "full_name", "email", "status"]
    vals: list[Any] = [employee_code, full_name, email, status]

    optional_text = (
        "phone", "dob", "gender", "marital_status", "hire_date",
        "employment_type", "location", "photo_path",
    )
    for key in optional_text:
        if data.get(key) is not None:
            cols.append(key)
            vals.append(data[key])

    optional_fk = ("department_id", "role_id", "manager_id")
    for key in optional_fk:
        if data.get(key) is not None and data.get(key) != "":
            cols.append(key)
            vals.append(data[key])

    salary_minor = _coerce_salary_minor(data)
    if salary_minor is not None:
        cols.append("salary_minor")
        vals.append(salary_minor)

    if metadata is not None:
        cols.append("metadata_json")
        vals.append(metadata)

    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO employee ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()
    return int(cur.lastrowid)


def _would_cycle(conn: sqlite3.Connection, employee_id: int,
                 proposed_manager_id: int | None) -> bool:
    """Return True if assigning proposed_manager_id to employee_id would loop.

    Walks up from the proposed manager. A loop happens when:
      - the proposed manager is the employee themselves
      - the proposed manager already reports (transitively) to the employee
    """
    if proposed_manager_id is None or proposed_manager_id == "":
        return False
    try:
        proposed_manager_id = int(proposed_manager_id)
    except (TypeError, ValueError):
        return False
    if proposed_manager_id == int(employee_id):
        return True
    seen: set[int] = set()
    current: int | None = proposed_manager_id
    while current is not None:
        if current in seen:
            return True
        seen.add(current)
        if current == int(employee_id):
            return True
        cur = conn.execute(
            "SELECT manager_id FROM employee WHERE id = ?", (current,)
        ).fetchone()
        if not cur:
            return False
        nxt = cur["manager_id"]
        current = int(nxt) if nxt not in (None, "") else None
    return False


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    """Patch only the fields supplied."""
    if "manager_id" in data:
        proposed = data["manager_id"]
        proposed_int = int(proposed) if proposed not in (None, "") else None
        if _would_cycle(conn, int(item_id), proposed_int):
            raise ValueError(
                "manager_id would create a reporting cycle"
            )

    fields: list[str] = []
    values: list[Any] = []
    simple = (
        "employee_code", "full_name", "email", "phone", "dob", "gender",
        "marital_status", "hire_date", "employment_type", "status",
        "department_id", "role_id", "manager_id", "location", "photo_path",
    )
    for key in simple:
        if key in data:
            if key in ("department_id", "role_id", "manager_id"):
                value = data[key]
                value = int(value) if value not in (None, "") else None
                fields.append(f"{key} = ?")
                values.append(value)
                continue
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "salary_minor" in data or "salary" in data:
        fields.append("salary_minor = ?")
        values.append(_coerce_salary_minor(data))
    if "metadata_json" in data:
        meta = data["metadata_json"]
        if isinstance(meta, dict):
            meta = json.dumps(meta)
        fields.append("metadata_json = ?")
        values.append(meta)
    if not fields:
        return
    values.append(item_id)
    conn.execute(
        f"UPDATE employee SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM employee WHERE id = ?", (item_id,))
    conn.commit()


def _list_options(conn: sqlite3.Connection, table: str, label_col: str) -> list[dict[str, Any]]:
    cur = conn.execute(f"SELECT id, {label_col} AS label FROM {table} ORDER BY {label_col}")
    return [{"id": r["id"], "label": r["label"]} for r in cur.fetchall()]


def _list_managers(conn: sqlite3.Connection,
                   exclude_id: int | None = None) -> list[dict[str, Any]]:
    """Return active employees as {id, label} for the manager picker.

    Excludes ``exclude_id`` (so an employee can't be set as their own manager)
    and excludes anyone who already reports — directly or transitively — to
    ``exclude_id``, so picking from this list cannot create a cycle.
    """
    rows = conn.execute(
        "SELECT id, employee_code, full_name FROM employee "
        "ORDER BY full_name"
    ).fetchall()
    if exclude_id is None:
        return [
            {
                "id": r["id"],
                "label": f"{r['full_name']} ({r['employee_code']})",
            }
            for r in rows
        ]

    # Build a set of ids that descend from exclude_id (cannot be its manager).
    forbidden: set[int] = {int(exclude_id)}
    children_of: dict[int, list[int]] = {}
    for r in rows:
        cur = conn.execute(
            "SELECT id FROM employee WHERE manager_id = ?", (r["id"],)
        ).fetchall()
        children_of[int(r["id"])] = [int(c["id"]) for c in cur]
    stack = [int(exclude_id)]
    while stack:
        nid = stack.pop()
        for child in children_of.get(nid, []):
            if child not in forbidden:
                forbidden.add(child)
                stack.append(child)

    return [
        {
            "id": r["id"],
            "label": f"{r['full_name']} ({r['employee_code']})",
        }
        for r in rows
        if int(r["id"]) not in forbidden
    ]


def _direct_reports(conn: sqlite3.Connection, manager_id: int) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT e.id, e.employee_code, e.full_name, e.email, e.status, "
        "       r.title AS role "
        "FROM employee e LEFT JOIN role r ON r.id = e.role_id "
        "WHERE e.manager_id = ? ORDER BY e.full_name",
        (int(manager_id),),
    )
    return [_row_to_dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def _esc(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_list_html(rows: list[dict[str, Any]],
                      depts: list[dict[str, Any]],
                      roles: list[dict[str, Any]],
                      managers: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}">{cells}'
            f'<td style="display:flex;gap:8px;align-items:center">'
            f'<a href="/m/employee/{row["id"]}" '
            f'style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;'
            f'color:var(--text);text-decoration:none;font-size:12px">Open</a>'
            f'<button onclick="deleteRow({row["id"]})">Delete</button></td></tr>'
        )
    dept_opts = "".join(
        f'<option value="{d["id"]}">{_esc(d["label"])}</option>' for d in depts
    )
    role_opts = "".join(
        f'<option value="{r["id"]}">{_esc(r["label"])}</option>' for r in roles
    )
    manager_opts = "".join(
        f'<option value="{m["id"]}">{_esc(m["label"])}</option>' for m in managers
    )
    status_opts = "".join(
        f'<option value="{s}"{" selected" if s == "active" else ""}>{s}</option>'
        for s in ALLOWED_STATUS
    )
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Employee</button>
  <a href="/m/employee/tree" style="padding:7px 14px;border:1px solid var(--border);border-radius:6px;color:var(--dim);text-decoration:none;font-size:13px">Org chart</a>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th>Actions</th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Full name*<input name="full_name" required></label>
    <label>Email*<input name="email" type="email" required></label>
    <label>Employee code<input name="employee_code"></label>
    <label>Phone<input name="phone"></label>
    <label>Department<select name="department_id"><option value="">--</option>{dept_opts}</select></label>
    <label>Role<select name="role_id"><option value="">--</option>{role_opts}</select></label>
    <label>Reports to<select name="manager_id"><option value="">-- (no manager)</option>{manager_opts}</select></label>
    <label>Hire date<input name="hire_date" type="date"></label>
    <label>Employment type<input name="employment_type" placeholder="full_time / contract"></label>
    <label>Status<select name="status">{status_opts}</select></label>
    <label>Salary (rupees)<input name="salary" type="number" step="0.01" min="0"></label>
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
  for (const k of ['department_id','role_id','manager_id']) if (payload[k] === '') delete payload[k];
  const r = await fetch('/api/m/employee', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete employee #' + id + '?'))) return;
  const r = await fetch('/api/m/employee/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else hrkit.toast('Delete failed', 'error');
}}
</script>
"""


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------
def list_view(handler) -> None:
    from hrkit.templates import render_module_page  # late import

    conn = handler.server.conn  # type: ignore[attr-defined]
    rows = list_rows(conn)
    depts = _list_options(conn, "department", "name")
    roles = _list_options(conn, "role", "title")
    managers = _list_managers(conn)
    body = _render_list_html(rows, depts, roles, managers)
    handler._html(200, render_module_page(title=LABEL, nav_active=NAME, body_html=body))


def _format_salary_minor(value: Any) -> str:
    """Format paise -> '₹X,XXX.XX'. Returns '' if value is None/blank."""
    if value is None or value == "":
        return ""
    try:
        paise = int(value)
    except (TypeError, ValueError):
        return str(value)
    rupees = paise / 100.0
    # Indian-style grouping is overkill here; use plain comma grouping.
    return f"₹{rupees:,.2f}"


def _count_entries(path: Path) -> int:
    try:
        return sum(1 for _ in path.iterdir())
    except OSError:
        return 0


def _relative_workspace_path(workspace_root: Path, target: Path) -> str:
    try:
        return target.relative_to(workspace_root).as_posix()
    except ValueError:
        return target.as_posix()


def detail_api_json(handler, item_id: int) -> None:
    """Return the raw employee row as JSON (back-compat for API clients)."""
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
                subtitle=f"No employee with id {int(item_id)}",
            ),
        )
        return

    manager_label = ""
    manager_id_int = row.get("manager_id")
    if manager_id_int not in (None, ""):
        mgr_cur = conn.execute(
            "SELECT id, employee_code, full_name FROM employee WHERE id = ?",
            (manager_id_int,),
        ).fetchone()
        if mgr_cur:
            manager_label = (
                f"{mgr_cur['full_name']} ({mgr_cur['employee_code']})"
            )

    fields: list[tuple[str, Any]] = [
        ("Employee code", row.get("employee_code")),
        ("Full name", row.get("full_name")),
        ("Email", row.get("email")),
        ("Phone", row.get("phone")),
        ("Status", row.get("status")),
        ("Department", row.get("department")),
        ("Role", row.get("role")),
        ("Reports to", manager_label),
        ("Employment type", row.get("employment_type")),
        ("Hire date", row.get("hire_date")),
        ("Date of birth", row.get("dob")),
        ("Gender", row.get("gender")),
        ("Marital status", row.get("marital_status")),
        ("Location", row.get("location")),
        ("Salary", _format_salary_minor(row.get("salary_minor"))),
        ("Photo path", row.get("photo_path")),
        ("Created", row.get("created")),
        ("Updated", row.get("updated")),
    ]

    # Documents for this employee.
    doc_cur = conn.execute(
        "SELECT id, doc_type, filename, expiry_date FROM document "
        "WHERE employee_id = ? ORDER BY uploaded_at DESC, id DESC",
        (int(item_id),),
    )
    doc_rows = doc_cur.fetchall()
    docs_table = (
        "<table><thead><tr><th>Type</th><th>Filename</th><th>Expiry</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{_esc(d['doc_type'])}</td>"
            f"<td><a href=\"/m/document/{int(d['id'])}\">{_esc(d['filename'])}</a></td>"
            f"<td>{_esc(d['expiry_date'])}</td></tr>"
            for d in doc_rows
        )
        + "</tbody></table>"
    ) if doc_rows else '<div class="empty">No documents on file.</div>'

    doc_body = (
        '<div style="display:flex;justify-content:flex-end;margin-bottom:8px">'
        '<button onclick="document.getElementById(\'doc-upload-dlg\').showModal()">'
        '+ Upload document</button>'
        '</div>'
        + docs_table
        + f"""
<dialog id="doc-upload-dlg">
  <form onsubmit="submitDocUpload(event)" enctype="multipart/form-data">
    <input type="hidden" name="employee_id" value="{int(item_id)}">
    <label>Document type*<input name="doc_type" required placeholder="e.g. PAN, contract"></label>
    <label>File*<input name="file" type="file" required></label>
    <label>Expiry date<input name="expiry_date" type="date"></label>
    <label>Notes<textarea name="notes"></textarea></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Upload</button>
    </menu>
  </form>
</dialog>
<script>
async function submitDocUpload(ev) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  if (fd.get('expiry_date') === '') fd.delete('expiry_date');
  const r = await fetch('/api/m/document/upload', {{method: 'POST', body: fd}});
  if (r.ok) location.reload(); else hrkit.toast('Upload failed: ' + await r.text(), 'error');
}}
</script>
"""
    )

    # Last 5 leave requests.
    lr_cur = conn.execute(
        "SELECT id, start_date, end_date, days, status, reason FROM leave_request "
        "WHERE employee_id = ? ORDER BY applied_at DESC, id DESC LIMIT 5",
        (int(item_id),),
    )
    lr_rows = lr_cur.fetchall()
    if lr_rows:
        lr_body = (
            "<table><thead><tr><th>From</th><th>To</th><th>Days</th>"
            "<th>Status</th><th>Reason</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{_esc(r['start_date'])}</td><td>{_esc(r['end_date'])}</td>"
                f"<td>{_esc(r['days'])}</td><td>{_esc(r['status'])}</td>"
                f"<td>{_esc(r['reason'])}</td></tr>"
                for r in lr_rows
            )
            + "</tbody></table>"
        )
    else:
        lr_body = '<div class="empty">No leave requests.</div>'

    # Custom fields editor (writes to metadata_json.custom).
    from hrkit import employee_fs as _efs
    custom_fields = _efs.get_custom_fields(conn, int(item_id))
    custom_rows_html = "".join(
        f'<tr><td><input class="cf-key" value="{_esc(k)}"></td>'
        f'<td><input class="cf-val" value="{_esc(v)}"></td>'
        f'<td><button onclick="this.closest(\'tr\').remove()">×</button></td></tr>'
        for k, v in custom_fields.items()
    )
    custom_body = f"""
<style>
  .cf-table{{width:100%;border-collapse:collapse;margin-bottom:8px}}
  .cf-table td{{padding:4px;border-bottom:1px solid var(--border)}}
  .cf-table input{{width:100%;padding:6px 8px;background:var(--bg);
    color:var(--text);border:1px solid var(--border);border-radius:4px;font-size:12.5px}}
  .cf-actions{{display:flex;gap:8px}}
  .cf-actions button{{padding:6px 12px;border-radius:6px;background:var(--accent);
    color:#fff;border:none;cursor:pointer;font-size:12px}}
  .cf-actions button.ghost{{background:transparent;border:1px solid var(--border);color:var(--dim)}}
</style>
<table class="cf-table" id="cf-table">
  <thead><tr><th>Key</th><th>Value</th><th></th></tr></thead>
  <tbody id="cf-rows">{custom_rows_html or '<tr><td colspan="3" style="color:var(--dim);padding:10px;text-align:center;font-style:italic">No custom fields. Add some below.</td></tr>'}</tbody>
</table>
<div class="cf-actions">
  <button class="ghost" onclick="addCustomRow()">+ Add row</button>
  <button onclick="saveCustomFields({int(item_id)})">Save custom fields</button>
</div>
<script>
function addCustomRow() {{
  const tbody = document.getElementById('cf-rows');
  // Drop the placeholder row if it's there.
  if (tbody.children.length === 1 && tbody.children[0].children.length === 1) tbody.innerHTML = '';
  const tr = document.createElement('tr');
  tr.innerHTML = '<td><input class="cf-key" placeholder="key"></td>' +
                 '<td><input class="cf-val" placeholder="value"></td>' +
                 '<td><button onclick="this.closest(\\'tr\\').remove()">×</button></td>';
  tbody.appendChild(tr);
}}
async function saveCustomFields(empId) {{
  const fields = {{}};
  document.querySelectorAll('#cf-rows tr').forEach(tr => {{
    const k = tr.querySelector('.cf-key'); const v = tr.querySelector('.cf-val');
    if (k && k.value.trim()) fields[k.value.trim()] = v ? v.value : '';
  }});
  const r = await fetch('/api/m/employee/' + empId + '/custom-fields', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{fields}}),
  }});
  if (r.ok) {{ hrkit.toast('Custom fields saved', 'success'); }}
  else {{ hrkit.toast('Save failed: ' + await r.text(), 'error'); }}
}}
</script>
"""

    # Free-form HR notes (writes to memory/notes.md on disk).
    notes_body = f"""
<style>
  #notes-editor{{width:100%;min-height:160px;padding:10px 12px;background:var(--bg);
    color:var(--text);border:1px solid var(--border);border-radius:6px;
    font-family:'JetBrains Mono','Menlo',monospace;font-size:12.5px;line-height:1.5;resize:vertical}}
  .notes-actions{{display:flex;justify-content:flex-end;gap:8px;margin-top:8px}}
  .notes-actions button{{padding:6px 12px;border-radius:6px;background:var(--accent);
    color:#fff;border:none;cursor:pointer;font-size:12px}}
  .notes-actions .hint{{color:var(--dim);font-size:11.5px;margin-right:auto;align-self:center}}
</style>
<textarea id="notes-editor" placeholder="HR notes (markdown). Saved to employees/{_esc(row.get('employee_code') or '')}/memory/notes.md — also fed to the AI when chatting in this employee's context."></textarea>
<div class="notes-actions">
  <span class="hint">Saved to disk + read by the AI as employee context.</span>
  <button onclick="saveNotes({int(item_id)})">Save notes</button>
</div>
<script>
(async function() {{
  try {{
    const r = await fetch('/api/m/employee/{int(item_id)}/notes');
    const data = await r.json();
    if (data.ok) document.getElementById('notes-editor').value = data.body || '';
  }} catch (err) {{}}
}})();
async function saveNotes(empId) {{
  const body = document.getElementById('notes-editor').value;
  const r = await fetch('/api/m/employee/' + empId + '/notes', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{body}}),
  }});
  if (r.ok) {{ hrkit.toast('Notes saved', 'success'); }}
  else {{ hrkit.toast('Save failed: ' + await r.text(), 'error'); }}
}}
</script>
"""

    workspace_root = _workspace_root_for(handler)
    workspace_body = (
        '<div class="empty">Workspace folder controls are unavailable until the '
        'local workspace is loaded.</div>'
    )
    employee_code = str(row.get("employee_code") or "").strip()
    if workspace_root is not None and employee_code:
        employee_dir = _efs.ensure_employee_layout(workspace_root, employee_code)
        try:
            _efs.write_employee_md(workspace_root, row)
        except OSError:
            pass
        docs_dir = _efs.documents_dir(workspace_root, employee_code)
        legal_dir = _efs.legal_dir(workspace_root, employee_code)
        convo_dir = _efs.conversations_dir(workspace_root, employee_code)
        memory_dir = _efs.memory_dir(workspace_root, employee_code)
        employee_md_path = employee_dir / "employee.md"
        employee_dir_rel = _relative_workspace_path(workspace_root, employee_dir)
        cards = [
            ("Employee folder", employee_dir_rel, "Profile file plus every HR artifact for this employee."),
            ("employee.md", _relative_workspace_path(workspace_root, employee_md_path),
             "Mirrored automatically from the employee profile."),
            ("Documents", _relative_workspace_path(workspace_root, docs_dir),
             f"{_count_entries(docs_dir)} file(s)"),
            ("Legal", _relative_workspace_path(workspace_root, legal_dir),
             f"{_count_entries(legal_dir)} file(s)"),
            ("Conversations", _relative_workspace_path(workspace_root, convo_dir),
             f"{_count_entries(convo_dir)} file(s)"),
            ("Memory", _relative_workspace_path(workspace_root, memory_dir),
             f"{_count_entries(memory_dir)} file(s)"),
        ]
        card_html = "".join(
            f'<div class="wk-card"><div class="wk-label">{_esc(label)}</div>'
            f'<div class="wk-path"><code>{_esc(path)}</code></div>'
            f'<div class="wk-meta">{_esc(meta)}</div></div>'
            for label, path, meta in cards
        )
        workspace_body = f"""
<style>
  .wk-actions{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}}
  .wk-actions button{{padding:6px 12px;border-radius:6px;background:var(--accent);
    color:#fff;border:none;cursor:pointer;font-size:12px}}
  .wk-actions button.ghost{{background:transparent;border:1px solid var(--border);color:var(--dim)}}
  .wk-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}
  .wk-card{{padding:12px;border:1px solid var(--border);border-radius:8px;background:var(--panel)}}
  .wk-label{{font-weight:600;margin-bottom:6px}}
  .wk-path{{font-size:12px;margin-bottom:6px;word-break:break-word}}
  .wk-path code{{background:var(--bg);padding:2px 6px;border-radius:4px}}
  .wk-meta{{font-size:12px;color:var(--dim);line-height:1.45}}
</style>
<div class="wk-actions">
  <button onclick="openWorkspacePath('{_esc(employee_dir_rel)}')">Open employee folder</button>
  <button class="ghost" onclick="openWorkspacePath('{_esc(_relative_workspace_path(workspace_root, docs_dir))}')">Open documents</button>
  <button class="ghost" onclick="openWorkspacePath('{_esc(_relative_workspace_path(workspace_root, memory_dir))}')">Open memory</button>
</div>
<div class="wk-grid">{card_html}</div>
<p style="margin:12px 0 0;color:var(--dim);font-size:12px">
  This gives HR direct control over the employee's local folder on this laptop. Update the employee record here and the mirrored
  <code>employee.md</code> file stays current for exports, AI context, and manual review.
</p>
<script>
async function openWorkspacePath(relPath) {{
  const r = await fetch('/api/workspace/open', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{path: relPath}})
  }});
  if (!r.ok) {{
    let err = 'Could not open folder';
    try {{ const j = await r.json(); err = j.error || err; }} catch (e) {{}}
    hrkit.toast(err, 'error');
  }}
}}
</script>
"""

    # Reporting structure: department/role/manager pickers + direct reports.
    depts = _list_options(conn, "department", "name")
    roles = _list_options(conn, "role", "title")
    current_dept = row.get("department_id")
    current_role = row.get("role_id")
    dept_options = ['<option value="">-- (no department)</option>']
    for d in depts:
        sel = " selected" if current_dept and int(current_dept) == int(d["id"]) else ""
        dept_options.append(f'<option value="{d["id"]}"{sel}>{_esc(d["label"])}</option>')
    role_options = ['<option value="">-- (no role)</option>']
    for r in roles:
        sel = " selected" if current_role and int(current_role) == int(r["id"]) else ""
        role_options.append(f'<option value="{r["id"]}"{sel}>{_esc(r["label"])}</option>')

    candidate_managers = _list_managers(conn, exclude_id=int(item_id))
    current_mgr = manager_id_int
    mgr_options = ['<option value="">-- (no manager)</option>']
    for m in candidate_managers:
        sel = " selected" if current_mgr is not None and int(current_mgr) == int(m["id"]) else ""
        mgr_options.append(
            f'<option value="{m["id"]}"{sel}>{_esc(m["label"])}</option>'
        )
    reports = _direct_reports(conn, int(item_id))
    if reports:
        reports_table = (
            "<table><thead><tr><th>Code</th><th>Name</th>"
            "<th>Role</th><th>Email</th><th>Status</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{_esc(rep['employee_code'])}</td>"
                f"<td><a href=\"/m/employee/{int(rep['id'])}\">{_esc(rep['full_name'])}</a></td>"
                f"<td>{_esc(rep.get('role') or '')}</td>"
                f"<td>{_esc(rep['email'])}</td><td>{_esc(rep['status'])}</td></tr>"
                for rep in reports
            )
            + "</tbody></table>"
        )
    else:
        reports_table = '<div class="empty">No direct reports.</div>'

    reporting_body = f"""
<style>
  .rep-row{{display:flex;gap:8px;align-items:center;margin-bottom:10px}}
  .rep-row label{{flex:0 0 96px;color:var(--dim);font-size:12px;margin:0}}
  .rep-row select{{flex:1;padding:7px 10px;background:var(--bg);
    color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:13px}}
  .rep-row button{{padding:7px 14px;border-radius:6px;background:var(--accent);
    color:#fff;border:none;cursor:pointer;font-size:12px}}
  .rep-tree-link{{margin:14px 0 12px;font-size:12px}}
  .rep-tree-link a{{color:var(--accent);text-decoration:none}}
</style>
<div class="rep-row">
  <label>Department</label>
  <select id="dept-picker">{''.join(dept_options)}</select>
  <button onclick="saveAssignment({int(item_id)},'department_id','dept-picker')">Update</button>
</div>
<div class="rep-row">
  <label>Role</label>
  <select id="role-picker">{''.join(role_options)}</select>
  <button onclick="saveAssignment({int(item_id)},'role_id','role-picker')">Update</button>
</div>
<div class="rep-row">
  <label>Reports to</label>
  <select id="mgr-picker">{''.join(mgr_options)}</select>
  <button onclick="saveAssignment({int(item_id)},'manager_id','mgr-picker')">Update</button>
</div>
<div class="rep-tree-link"><a href="/m/employee/tree">&rarr; View full org chart</a></div>
<h4 style="margin:12px 0 6px;font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:0.5px">Direct reports</h4>
{reports_table}
<script>
async function saveAssignment(empId, field, pickerId) {{
  const sel = document.getElementById(pickerId);
  const value = sel.value === '' ? null : parseInt(sel.value, 10);
  const payload = {{}}; payload[field] = value;
  const r = await fetch('/api/m/employee/' + empId, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload();
  else {{
    let err = 'Update failed';
    try {{ const j = await r.json(); err = j.error || err; }} catch (e) {{}}
    hrkit.toast(err, 'info');
  }}
}}
</script>
"""

    related_html = (
        detail_section(title="Workspace folder", body_html=workspace_body)
        + detail_section(title="Reporting structure", body_html=reporting_body)
        + detail_section(title="HR notes (free-form)", body_html=notes_body)
        + detail_section(title="Custom fields", body_html=custom_body)
        + detail_section(title="Documents", body_html=doc_body)
        + detail_section(title="Recent leave requests", body_html=lr_body)
    )

    subtitle_bits = [b for b in (row.get("employee_code"), row.get("role"), row.get("department")) if b]
    html = render_detail_page(
        title=row.get("full_name") or "Employee",
        nav_active=NAME,
        subtitle=" · ".join(subtitle_bits),
        fields=fields,
        related_html=related_html,
        field_options={"status": list(ALLOWED_STATUS)},
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}",
        delete_redirect=f"/m/{NAME}",
        exclude_edit_fields={"reports_to", "department", "role", "created", "updated"},
        edit_field_names={"date_of_birth": "dob"},
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
    _sync_employee_workspace(handler, new_id)
    handler._json({"id": new_id}, code=201)


def update_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        update_row(conn, int(item_id), payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    _sync_employee_workspace(handler, int(item_id))
    handler._json({"ok": True})


def delete_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    delete_row(conn, int(item_id))
    handler._json({"ok": True})


# ---------------------------------------------------------------------------
# Custom notes + custom fields (Phase 1.11)
# ---------------------------------------------------------------------------
def _workspace_root_for(handler):
    server = getattr(handler, "server", None)
    root = getattr(server, "workspace_root", None) if server else None
    if root:
        return Path(root)
    try:
        from hrkit import server as server_mod
        if getattr(server_mod, "ROOT", None):
            return Path(server_mod.ROOT)
    except Exception:  # noqa: BLE001
        return None
    return None


def _sync_employee_workspace(handler, item_id: int) -> None:
    from hrkit import employee_fs
    conn = handler.server.conn  # type: ignore[attr-defined]
    workspace_root = _workspace_root_for(handler)
    if workspace_root is None:
        return
    try:
        employee_fs.write_employee_md_for_id(conn, workspace_root, int(item_id))
    except Exception:  # noqa: BLE001
        pass


def _employee_code_for(conn, item_id: int) -> str:
    row = conn.execute(
        "SELECT employee_code FROM employee WHERE id = ?", (int(item_id),),
    ).fetchone()
    return str(row["employee_code"] or "").strip() if row else ""


def notes_api(handler, item_id: int) -> None:
    """GET /api/m/employee/<id>/notes -> {body}; POST -> save."""
    from hrkit import employee_fs
    conn = handler.server.conn  # type: ignore[attr-defined]
    workspace_root = _workspace_root_for(handler)
    code = _employee_code_for(conn, item_id)
    if not code:
        handler._json({"ok": False, "error": "employee not found or has no employee_code"}, code=404)
        return
    if workspace_root is None:
        handler._json({"ok": False, "error": "workspace not configured"}, code=400)
        return
    method = (getattr(handler, "command", "") or "").upper()
    if method == "GET":
        handler._json({"ok": True, "body": employee_fs.read_notes(workspace_root, code)})
        return
    body = handler._read_json() or {}
    text = body.get("body") if isinstance(body.get("body"), str) else ""
    try:
        path = employee_fs.write_notes(workspace_root, code, text)
    except OSError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400)
        return
    handler._json({"ok": True, "path": str(path)})


def custom_fields_api(handler, item_id: int) -> None:
    """GET /api/m/employee/<id>/custom-fields -> {fields}; POST -> save."""
    from hrkit import employee_fs
    conn = handler.server.conn  # type: ignore[attr-defined]
    method = (getattr(handler, "command", "") or "").upper()
    if method == "GET":
        handler._json({"ok": True, "fields": employee_fs.get_custom_fields(conn, item_id)})
        return
    body = handler._read_json() or {}
    fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
    try:
        saved = employee_fs.set_custom_fields(conn, item_id, fields)
    except LookupError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=404)
        return
    # Refresh employee.md so the new fields show up on disk too.
    workspace_root = _workspace_root_for(handler)
    if workspace_root is not None:
        try:
            employee_fs.write_employee_md_for_id(conn, workspace_root, item_id)
        except Exception:  # noqa: BLE001
            pass
    handler._json({"ok": True, "fields": saved})


def _build_org_tree(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]],
                                                       dict[int, list[dict[str, Any]]],
                                                       list[dict[str, Any]]]:
    """Return (roots, children_by_parent, orphans).

    Roots = employees with no manager. Orphans = employees whose manager_id
    points at a row that doesn't exist (data integrity edge case — shown in
    a separate group so they aren't silently lost).
    """
    rows = conn.execute(
        "SELECT e.id, e.employee_code, e.full_name, e.email, e.status, "
        "       e.manager_id, e.photo_path, "
        "       r.title AS role, d.name AS department "
        "FROM employee e "
        "LEFT JOIN role r ON r.id = e.role_id "
        "LEFT JOIN department d ON d.id = e.department_id "
        "ORDER BY e.full_name"
    ).fetchall()
    all_ids: set[int] = {int(r["id"]) for r in rows}
    children: dict[int, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        mgr = d.get("manager_id")
        if mgr in (None, ""):
            roots.append(d)
        elif int(mgr) in all_ids:
            children.setdefault(int(mgr), []).append(d)
        else:
            orphans.append(d)
    return roots, children, orphans


def _render_tree_node(node: dict[str, Any],
                      children: dict[int, list[dict[str, Any]]]) -> str:
    kids = children.get(int(node["id"]), [])
    name = _esc(node.get("full_name") or "")
    code = _esc(node.get("employee_code") or "")
    role = _esc(node.get("role") or "")
    dept = _esc(node.get("department") or "")
    status = _esc(node.get("status") or "")
    role_pill = f'<span class="org-pill org-pill-role">{role}</span>' if role else ""
    dept_pill = f'<span class="org-pill org-pill-dept">{dept}</span>' if dept else ""
    count_badge = (
        f'<span class="org-count">{len(kids)} report{"s" if len(kids) != 1 else ""}</span>' if kids else ""
    )
    if kids:
        kids_html = (
            '<ul class="org-children">'
            + "".join(_render_tree_node(c, children) for c in kids)
            + "</ul>"
        )
        return f"""
<li>
  <details open class="org-card">
    <summary>
      <a class="org-name" href="/m/employee/{int(node["id"])}">{name}</a>
      <span class="org-code">{code}</span>
      {role_pill}
      {dept_pill}
      <span class="org-status org-status-{status}">{status}</span>
      {count_badge}
    </summary>
    {kids_html}
  </details>
</li>"""
    return f"""
<li class="org-leaf">
  <a class="org-name" href="/m/employee/{int(node["id"])}">{name}</a>
  <span class="org-code">{code}</span>
  {role_pill}
  {dept_pill}
  <span class="org-status org-status-{status}">{status}</span>
</li>"""


_ORG_TREE_CSS = """
.org-toolbar{display:flex;gap:12px;align-items:center;margin-bottom:18px}
.org-toolbar h1{margin:0;font-size:22px;font-weight:600}
.org-toolbar .org-meta{color:var(--dim);font-size:13px;margin-left:auto}
.org-tree{list-style:none;padding-left:0;margin:0}
.org-tree ul.org-children{list-style:none;padding-left:22px;margin:6px 0 0 0;
  border-left:1px solid var(--border)}
.org-card>summary{display:flex;gap:10px;align-items:center;cursor:pointer;
  padding:10px 12px;border:1px solid var(--border);border-radius:8px;
  background:var(--panel);margin:4px 0;list-style:none}
.org-card>summary::-webkit-details-marker{display:none}
.org-card>summary::before{content:"\\25B8";color:var(--dim);font-size:10px;
  display:inline-block;transition:transform .15s ease}
.org-card[open]>summary::before{transform:rotate(90deg)}
.org-leaf{display:flex;gap:10px;align-items:center;padding:10px 12px;
  border:1px solid var(--border);border-radius:8px;background:var(--panel);
  margin:4px 0;list-style:none}
.org-name{font-weight:600;color:var(--text);text-decoration:none}
.org-name:hover{text-decoration:underline}
.org-code{font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--dim)}
.org-sub{font-size:12px;color:var(--dim);flex:1}
.org-status{font-size:10px;padding:2px 8px;border-radius:3px;
  text-transform:uppercase;letter-spacing:0.5px;background:#eef1f6;color:#4b5563}
.org-status-active{background:#d1fae5;color:#065f46}
.org-status-on_leave{background:#fef3c7;color:#92400e}
.org-status-exited{background:#fee2e2;color:#991b1b}
.org-pill{font-size:11px;padding:2px 8px;border-radius:4px;
  background:rgba(255,255,255,0.04);color:var(--text);border:1px solid var(--border);
  white-space:nowrap}
.org-pill-role{background:color-mix(in srgb,var(--accent) 14%,transparent);
  color:#a5b4fc;border-color:color-mix(in srgb,var(--accent) 30%,transparent)}
.org-pill-dept{background:color-mix(in srgb,var(--cyan) 12%,transparent);
  color:#7dd3fc;border-color:color-mix(in srgb,var(--cyan) 25%,transparent)}
.org-count{font-size:11px;padding:2px 8px;border-radius:10px;
  background:color-mix(in srgb,var(--accent) 20%,transparent);color:var(--accent);
  margin-left:auto}
.org-empty{padding:40px;text-align:center;color:var(--dim);font-style:italic}
.org-orphans{margin-top:24px;padding-top:16px;border-top:1px dashed var(--border)}
.org-orphans h3{font-size:13px;color:var(--dim);text-transform:uppercase;
  letter-spacing:0.5px;margin:0 0 8px}
"""


def tree_view(handler) -> None:
    """GET /m/employee/tree — render the org chart as nested cards."""
    from hrkit.templates import render_module_page

    conn = handler.server.conn  # type: ignore[attr-defined]
    roots, children, orphans = _build_org_tree(conn)
    total = sum(1 for _ in conn.execute("SELECT 1 FROM employee"))

    if not roots and not orphans:
        body_html = (
            f'<style>{_ORG_TREE_CSS}</style>'
            '<div class="org-toolbar"><h1>Org chart</h1></div>'
            '<div class="org-empty">No employees yet. '
            '<a href="/m/employee">Add your first employee</a> to start.</div>'
        )
        handler._html(200, render_module_page(
            title="Org chart", nav_active=NAME, body_html=body_html))
        return

    tree_html = (
        '<ul class="org-tree">'
        + "".join(_render_tree_node(r, children) for r in roots)
        + "</ul>"
    )
    orphans_html = ""
    if orphans:
        orphans_html = (
            '<div class="org-orphans">'
            '<h3>Reports to a deleted employee</h3>'
            '<ul class="org-tree">'
            + "".join(_render_tree_node(o, children) for o in orphans)
            + '</ul></div>'
        )

    body_html = f"""
<style>{_ORG_TREE_CSS}</style>
<div class="org-toolbar">
  <h1>Org chart</h1>
  <span class="org-meta">{total} employee{'s' if total != 1 else ''} &middot; {len(roots)} top-level</span>
  <a href="/m/employee" style="font-size:13px;color:var(--accent);text-decoration:none">&larr; Back to list</a>
</div>
{tree_html}
{orphans_html}
"""
    handler._html(200, render_module_page(
        title="Org chart", nav_active=NAME, body_html=body_html))


ROUTES = {
    "GET": [
        (r"^/api/m/employee/(\d+)/notes/?$", notes_api),
        (r"^/api/m/employee/(\d+)/custom-fields/?$", custom_fields_api),
        (r"^/api/m/employee/(\d+)/?$", detail_api_json),
        (r"^/m/employee/tree/?$", tree_view),
        (r"^/m/employee/?$", list_view),
        (r"^/m/employee/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/employee/(\d+)/notes/?$", notes_api),
        (r"^/api/m/employee/(\d+)/custom-fields/?$", custom_fields_api),
        (r"^/api/m/employee/?$", create_api),
        (r"^/api/m/employee/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/employee/(\d+)/?$", delete_api),
    ],
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_create_args(parser) -> None:
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--employee-code")
    parser.add_argument("--phone")
    parser.add_argument("--department-id", type=int)
    parser.add_argument("--role-id", type=int)
    parser.add_argument("--hire-date")
    parser.add_argument("--employment-type")
    parser.add_argument("--status", default="active", choices=list(ALLOWED_STATUS))
    parser.add_argument("--salary", type=float, help="Salary in rupees (stored as paise)")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "full_name": args.full_name,
        "email": args.email,
        "employee_code": getattr(args, "employee_code", None),
        "phone": getattr(args, "phone", None),
        "department_id": getattr(args, "department_id", None),
        "role_id": getattr(args, "role_id", None),
        "hire_date": getattr(args, "hire_date", None),
        "employment_type": getattr(args, "employment_type", None),
        "status": getattr(args, "status", "active"),
        "salary": getattr(args, "salary", None),
    })
    log.info("employee_added id=%s email=%s", new_id, args.email)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s", row["id"], row["employee_code"], row["full_name"], row["email"])
    return 0


CLI = [
    ("employee-add", _add_create_args, _handle_create),
    ("employee-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "core",
    "requires": ["department", "role"],
    "description": "Master employee record — contact, salary, manager chain, photo.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
