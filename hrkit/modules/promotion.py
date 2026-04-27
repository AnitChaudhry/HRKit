"""Promotion module — promotions, transfers, and lateral moves.

Owns ``promotion`` (migration 002). When a promotion's status flips to
``effective``, callers may apply the change to the employee row themselves
(role/department/salary). The module exposes :func:`apply_promotion` for that.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "promotion"
LABEL = "Promotions & Transfers"
ICON = "trending-up"

LIST_COLUMNS = ("employee", "type", "to_role", "to_department", "effective_date", "status")
ALLOWED_TYPE = ("promotion", "transfer", "lateral", "demotion")
ALLOWED_STATUS = ("proposed", "approved", "effective", "rejected", "cancelled")


def ensure_schema(conn): return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _format_minor(v):
    if v is None or v == "":
        return ""
    try:
        return f"₹{int(v)/100:,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _coerce_minor(v):
    if v is None or v == "":
        return None
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return None


def list_rows(conn):
    cur = conn.execute("""
        SELECT p.id, p.employee_id, p.type, p.effective_date, p.status, p.reason,
               p.from_salary_minor, p.to_salary_minor,
               e.full_name AS employee,
               fr.title AS from_role, tr.title AS to_role,
               fd.name AS from_department, td.name AS to_department
        FROM promotion p
        LEFT JOIN employee e ON e.id = p.employee_id
        LEFT JOIN role fr ON fr.id = p.from_role_id
        LEFT JOIN role tr ON tr.id = p.to_role_id
        LEFT JOIN department fd ON fd.id = p.from_department_id
        LEFT JOIN department td ON td.id = p.to_department_id
        ORDER BY p.effective_date DESC, p.id DESC
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("""
        SELECT p.*, e.full_name AS employee,
               fr.title AS from_role, tr.title AS to_role,
               fd.name AS from_department, td.name AS to_department,
               ap.full_name AS approver
        FROM promotion p
        LEFT JOIN employee e ON e.id = p.employee_id
        LEFT JOIN role fr ON fr.id = p.from_role_id
        LEFT JOIN role tr ON tr.id = p.to_role_id
        LEFT JOIN department fd ON fd.id = p.from_department_id
        LEFT JOIN department td ON td.id = p.to_department_id
        LEFT JOIN employee ap ON ap.id = p.approved_by
        WHERE p.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    employee_id = data.get("employee_id")
    if not employee_id:
        raise ValueError("employee_id is required")
    type_ = (data.get("type") or "promotion").strip()
    if type_ not in ALLOWED_TYPE:
        raise ValueError(f"type must be one of {ALLOWED_TYPE}")
    status = (data.get("status") or "proposed").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")

    # Snapshot the employee's current role/dept/salary as the "from" if not supplied
    cur = conn.execute(
        "SELECT role_id, department_id, salary_minor FROM employee WHERE id = ?",
        (int(employee_id),)).fetchone()
    if not cur:
        raise ValueError(f"employee {employee_id} not found")

    cols = ["employee_id", "type", "status",
            "from_role_id", "from_department_id", "from_salary_minor"]
    vals: list[Any] = [
        int(employee_id), type_, status,
        data.get("from_role_id") if data.get("from_role_id") is not None else cur["role_id"],
        data.get("from_department_id") if data.get("from_department_id") is not None else cur["department_id"],
        data.get("from_salary_minor") if data.get("from_salary_minor") is not None else cur["salary_minor"],
    ]
    for key in ("to_role_id", "to_department_id", "effective_date", "reason", "notes"):
        if data.get(key) not in (None, ""):
            cols.append(key); vals.append(data[key])
    if "to_salary_minor" in data and data["to_salary_minor"] not in (None, ""):
        cols.append("to_salary_minor"); vals.append(int(data["to_salary_minor"]))
    elif "to_salary" in data and data["to_salary"] not in (None, ""):
        cols.append("to_salary_minor"); vals.append(_coerce_minor(data["to_salary"]))
    if data.get("approved_by") not in (None, ""):
        cols.append("approved_by"); vals.append(int(data["approved_by"]))
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO promotion ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    new_id = int(cur.lastrowid)
    if status == "proposed":
        try:
            from . import approval as approval_mod
            chain = approval_mod.default_approver_chain(conn, int(employee_id))
            if chain:
                approval_mod.request_approvals(
                    conn, request_type="promotion",
                    request_id=new_id, approver_ids=chain)
        except Exception as exc:  # noqa: BLE001
            log.warning("approval.request_approvals failed for promotion %s: %s",
                        new_id, exc)
    return new_id


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("type", "status", "to_role_id", "to_department_id",
                "effective_date", "reason", "notes", "approved_by"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "to_salary_minor" in data:
        fields.append("to_salary_minor = ?"); values.append(int(data["to_salary_minor"]))
    elif "to_salary" in data:
        fields.append("to_salary_minor = ?"); values.append(_coerce_minor(data["to_salary"]))
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE promotion SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    new_status = data.get("status")
    if new_status in ("approved", "effective", "rejected", "cancelled"):
        outcome = "approved" if new_status in ("approved", "effective") else "rejected"
        try:
            from . import approval as approval_mod
            approval_mod.reflect_request_outcome(
                conn, request_type="promotion",
                request_id=int(item_id), outcome=outcome)
        except Exception as exc:  # noqa: BLE001
            log.warning("approval.reflect_request_outcome failed for promotion %s: %s",
                        item_id, exc)


def delete_row(conn, item_id):
    conn.execute("DELETE FROM promotion WHERE id = ?", (item_id,))
    conn.commit()


def apply_promotion(conn: sqlite3.Connection, promotion_id: int) -> None:
    """Apply an approved promotion to the employee row (role/dept/salary).
    Flips the promotion status to ``effective``."""
    p = conn.execute("SELECT * FROM promotion WHERE id = ?", (int(promotion_id),)).fetchone()
    if not p:
        raise LookupError(f"promotion {promotion_id} not found")
    fields, values = [], []
    if p["to_role_id"] not in (None, ""):
        fields.append("role_id = ?"); values.append(p["to_role_id"])
    if p["to_department_id"] not in (None, ""):
        fields.append("department_id = ?"); values.append(p["to_department_id"])
    if p["to_salary_minor"] not in (None, 0):
        fields.append("salary_minor = ?"); values.append(p["to_salary_minor"])
    if fields:
        values.append(p["employee_id"])
        conn.execute(f"UPDATE employee SET {', '.join(fields)} WHERE id = ?", values)
    conn.execute("UPDATE promotion SET status='effective' WHERE id = ?", (int(promotion_id),))
    conn.commit()


def _emp_options(conn):
    return [{"id": r["id"], "label": r["full_name"]}
            for r in conn.execute(
                "SELECT id, full_name FROM employee ORDER BY full_name").fetchall()]


def _role_options(conn):
    return [{"id": r["id"], "label": r["title"]}
            for r in conn.execute(
                "SELECT id, title FROM role ORDER BY title").fetchall()]


def _dept_options(conn):
    return [{"id": r["id"], "label": r["name"]}
            for r in conn.execute(
                "SELECT id, name FROM department ORDER BY name").fetchall()]


def _render_list_html(rows, employees, roles, depts) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/promotion/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    role_opts = "".join(f'<option value="{r["id"]}">{_esc(r["label"])}</option>' for r in roles)
    dept_opts = "".join(f'<option value="{d["id"]}">{_esc(d["label"])}</option>' for d in depts)
    type_opts = "".join(f'<option value="{t}"{" selected" if t == "promotion" else ""}>{t}</option>'
                        for t in ALLOWED_TYPE)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New move</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Employee*<select name="employee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Type<select name="type">{type_opts}</select></label>
    <label>To role<select name="to_role_id"><option value="">-- (no change)</option>{role_opts}</select></label>
    <label>To department<select name="to_department_id"><option value="">-- (no change)</option>{dept_opts}</select></label>
    <label>To salary (₹)<input name="to_salary" type="number" step="0.01" min="0"></label>
    <label>Effective date<input name="effective_date" type="date"></label>
    <label>Reason<textarea name="reason"></textarea></label>
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
  for (const k of ['to_role_id','to_department_id']) if (payload[k] === '') delete payload[k];
  const r = await fetch('/api/m/promotion', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete?')) return;
  const r = await fetch('/api/m/promotion/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""


def list_view(handler):
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME,
        body_html=_render_list_html(list_rows(conn),
                                    _emp_options(conn), _role_options(conn), _dept_options(conn))))


def detail_api_json(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id):
    from hrkit.templates import render_detail_page, detail_section
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No record with id {int(item_id)}"))
        return
    fields = [
        ("Employee", row.get("employee")),
        ("Type", row.get("type")),
        ("Status", row.get("status")),
        ("From role", row.get("from_role")),
        ("To role", row.get("to_role")),
        ("From department", row.get("from_department")),
        ("To department", row.get("to_department")),
        ("From salary", _format_minor(row.get("from_salary_minor"))),
        ("To salary", _format_minor(row.get("to_salary_minor"))),
        ("Effective date", row.get("effective_date")),
        ("Approver", row.get("approver")),
        ("Reason", row.get("reason")),
        ("Notes", row.get("notes")),
        ("Created", row.get("created")),
    ]
    apply_btn = ""
    if (row.get("status") or "") == "approved":
        apply_btn = f"""
<div style="margin:12px 0">
  <button onclick="applyMove({int(item_id)})">Apply to employee record</button>
  <span style="color:var(--dim);font-size:12px;margin-left:8px">
    Updates the employee's role/dept/salary and marks status as 'effective'.</span>
</div>
<script>
async function applyMove(id) {{
  if (!confirm('Apply this move to the employee record?')) return;
  const r = await fetch('/api/m/promotion/' + id + '/apply', {{method: 'POST'}});
  if (r.ok) location.reload(); else alert('Apply failed: ' + await r.text());
}}
</script>"""
    handler._html(200, render_detail_page(
        title=f"{row.get('type', '').title()} — {row.get('employee') or ''}",
        nav_active=NAME, subtitle=row.get("effective_date") or "",
        fields=fields,
        related_html=(detail_section(title="Apply", body_html=apply_btn) if apply_btn else ""),
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"status": list(ALLOWED_STATUS), "type": list(ALLOWED_TYPE)},
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


def apply_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        apply_promotion(conn, int(item_id))
    except (LookupError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True})


ROUTES = {
    "GET": [
        (r"^/api/m/promotion/(\d+)/?$", detail_api_json),
        (r"^/m/promotion/?$", list_view),
        (r"^/m/promotion/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/promotion/(\d+)/apply/?$", apply_api),
        (r"^/api/m/promotion/?$", create_api),
        (r"^/api/m/promotion/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/promotion/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--employee-id", type=int, required=True)
    parser.add_argument("--type", default="promotion", choices=list(ALLOWED_TYPE))
    parser.add_argument("--to-role-id", type=int)
    parser.add_argument("--to-department-id", type=int)
    parser.add_argument("--to-salary", type=float)
    parser.add_argument("--effective-date")
    parser.add_argument("--reason")


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "employee_id": args.employee_id,
        "type": args.type,
        "to_role_id": getattr(args, "to_role_id", None),
        "to_department_id": getattr(args, "to_department_id", None),
        "to_salary": getattr(args, "to_salary", None),
        "effective_date": getattr(args, "effective_date", None),
        "reason": getattr(args, "reason", None),
    })
    log.info("promotion_added id=%s employee=%s type=%s",
             new_id, args.employee_id, args.type)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s\t%s",
                 row["id"], row["status"], row.get("type"),
                 row.get("employee") or "", row.get("effective_date") or "")
    return 0


CLI = [
    ("promotion-add", _add_create_args, _handle_create),
    ("promotion-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "talent",
    "requires": ["employee", "role", "department"],
    "description": "Promotions, transfers, and lateral moves with role/dept/salary changes.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
