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
        # Rupees -> paise (cents). Use round to avoid float drift.
        rupees = float(payload["salary"])
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


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    """Patch only the fields supplied."""
    fields: list[str] = []
    values: list[Any] = []
    simple = (
        "employee_code", "full_name", "email", "phone", "dob", "gender",
        "marital_status", "hire_date", "employment_type", "status",
        "department_id", "role_id", "manager_id", "location", "photo_path",
    )
    for key in simple:
        if key in data:
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
                      roles: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}">{cells}'
            f'<td><button onclick="deleteRow({row["id"]})">Delete</button></td></tr>'
        )
    dept_opts = "".join(
        f'<option value="{d["id"]}">{_esc(d["label"])}</option>' for d in depts
    )
    role_opts = "".join(
        f'<option value="{r["id"]}">{_esc(r["label"])}</option>' for r in roles
    )
    status_opts = "".join(
        f'<option value="{s}"{" selected" if s == "active" else ""}>{s}</option>'
        for s in ALLOWED_STATUS
    )
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Employee</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
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
  for (const k of ['department_id','role_id']) if (payload[k] === '') delete payload[k];
  const r = await fetch('/api/m/employee', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete employee #' + id + '?')) return;
  const r = await fetch('/api/m/employee/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
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
    body = _render_list_html(rows, depts, roles)
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

    fields: list[tuple[str, Any]] = [
        ("Employee code", row.get("employee_code")),
        ("Full name", row.get("full_name")),
        ("Email", row.get("email")),
        ("Phone", row.get("phone")),
        ("Status", row.get("status")),
        ("Department", row.get("department")),
        ("Role", row.get("role")),
        ("Manager id", row.get("manager_id")),
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
  if (r.ok) location.reload(); else alert('Upload failed: ' + await r.text());
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
  if (r.ok) {{ alert('Custom fields saved'); }}
  else {{ alert('Save failed: ' + await r.text()); }}
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
  if (r.ok) {{ alert('Notes saved'); }}
  else {{ alert('Save failed: ' + await r.text()); }}
}}
</script>
"""

    related_html = (
        detail_section(title="HR notes (free-form)", body_html=notes_body)
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


# ---------------------------------------------------------------------------
# Custom notes + custom fields (Phase 1.11)
# ---------------------------------------------------------------------------
def _workspace_root_for(handler):
    from pathlib import Path
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


ROUTES = {
    "GET": [
        (r"^/api/m/employee/(\d+)/notes/?$", notes_api),
        (r"^/api/m/employee/(\d+)/custom-fields/?$", custom_fields_api),
        (r"^/api/m/employee/(\d+)/?$", detail_api_json),
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
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
