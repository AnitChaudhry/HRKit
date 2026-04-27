"""Salary advance module — employee advance requests + approval + repayment.

Owns ``salary_advance`` (migration 002).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "salary_advance"
LABEL = "Salary Advances"
ICON = "wallet"

LIST_COLUMNS = ("employee", "amount", "request_date", "status", "approver")
ALLOWED_STATUS = ("requested", "approved", "disbursed", "rejected", "repaid", "cancelled")


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


def _coerce_minor(payload: dict[str, Any]) -> int | None:
    if "amount_minor" in payload and payload["amount_minor"] not in (None, ""):
        return int(payload["amount_minor"])
    if "amount" in payload and payload["amount"] not in (None, ""):
        return int(round(float(payload["amount"]) * 100))
    return None


def list_rows(conn):
    cur = conn.execute("""
        SELECT a.id, a.employee_id, a.amount_minor, a.request_date, a.status,
               a.disbursed_at, a.approved_at, a.notes,
               e.full_name AS employee,
               ap.full_name AS approver
        FROM salary_advance a
        LEFT JOIN employee e ON e.id = a.employee_id
        LEFT JOIN employee ap ON ap.id = a.approved_by
        ORDER BY a.request_date DESC, a.id DESC
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["amount"] = _format_minor(d.get("amount_minor"))
        out.append(d)
    return out


def get_row(conn, item_id):
    cur = conn.execute("""
        SELECT a.*, e.full_name AS employee, ap.full_name AS approver
        FROM salary_advance a
        LEFT JOIN employee e ON e.id = a.employee_id
        LEFT JOIN employee ap ON ap.id = a.approved_by
        WHERE a.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    employee_id = data.get("employee_id")
    if not employee_id:
        raise ValueError("employee_id is required")
    amount = _coerce_minor(data)
    if amount is None or amount <= 0:
        raise ValueError("amount must be > 0")
    status = (data.get("status") or "requested").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["employee_id", "amount_minor", "status"]
    vals: list[Any] = [int(employee_id), amount, status]
    for key in ("request_date", "reason", "notes"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    if data.get("repayment_schedule") is not None:
        v = data["repayment_schedule"]
        cols.append("repayment_schedule")
        vals.append(json.dumps(v) if isinstance(v, (dict, list)) else str(v))
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO salary_advance ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    new_id = int(cur.lastrowid)
    # Seed the approval queue when the request is born in 'requested' status.
    if status == "requested":
        try:
            from . import approval as approval_mod
            chain = approval_mod.default_approver_chain(conn, int(employee_id))
            if chain:
                approval_mod.request_approvals(
                    conn, request_type="salary_advance",
                    request_id=new_id, approver_ids=chain)
        except Exception as exc:  # noqa: BLE001
            log.warning("approval.request_approvals failed for advance %s: %s",
                        new_id, exc)
    return new_id


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("request_date", "reason", "notes", "status", "approved_by"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "amount_minor" in data or "amount" in data:
        fields.append("amount_minor = ?"); values.append(_coerce_minor(data))
    new_status = data.get("status")
    if new_status == "approved":
        fields.append("approved_at = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    if new_status == "disbursed":
        fields.append("disbursed_at = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    if "repayment_schedule" in data:
        v = data["repayment_schedule"]
        fields.append("repayment_schedule = ?")
        values.append(json.dumps(v) if isinstance(v, (dict, list)) else str(v))
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE salary_advance SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    # Mirror the status flip onto the approval queue.
    if new_status in ("approved", "disbursed", "rejected", "cancelled"):
        outcome = "approved" if new_status in ("approved", "disbursed") else "rejected"
        try:
            from . import approval as approval_mod
            approval_mod.reflect_request_outcome(
                conn, request_type="salary_advance",
                request_id=int(item_id), outcome=outcome)
        except Exception as exc:  # noqa: BLE001
            log.warning("approval.reflect_request_outcome failed for advance %s: %s",
                        item_id, exc)


def delete_row(conn, item_id):
    conn.execute("DELETE FROM salary_advance WHERE id = ?", (item_id,))
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
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/salary_advance/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Request advance</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Employee*<select name="employee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Amount (₹)*<input name="amount" type="number" step="0.01" min="1" required></label>
    <label>Reason<textarea name="reason"></textarea></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Submit</button>
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
  const r = await fetch('/api/m/salary_advance', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete?'))) return;
  const r = await fetch('/api/m/salary_advance/' + id, {{method: 'DELETE'}});
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
                      subtitle=f"No advance with id {int(item_id)}"))
        return
    fields = [
        ("Employee", row.get("employee")),
        ("Amount", _format_minor(row.get("amount_minor"))),
        ("Request date", row.get("request_date")),
        ("Status", row.get("status")),
        ("Approver", row.get("approver")),
        ("Approved at", row.get("approved_at")),
        ("Disbursed at", row.get("disbursed_at")),
        ("Reason", row.get("reason")),
        ("Repayment schedule", row.get("repayment_schedule")),
        ("Notes", row.get("notes")),
        ("Created", row.get("created")),
    ]
    handler._html(200, render_detail_page(
        title=f"Advance — {row.get('employee') or '?'}",
        nav_active=NAME, subtitle=_format_minor(row.get("amount_minor")),
        fields=fields, item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"status": list(ALLOWED_STATUS)},
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
        (r"^/api/m/salary_advance/(\d+)/?$", detail_api_json),
        (r"^/m/salary_advance/?$", list_view),
        (r"^/m/salary_advance/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/salary_advance/?$", create_api),
        (r"^/api/m/salary_advance/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/salary_advance/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--employee-id", type=int, required=True)
    parser.add_argument("--amount", type=float, required=True)
    parser.add_argument("--reason")


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "employee_id": args.employee_id,
        "amount": args.amount,
        "reason": getattr(args, "reason", None),
    })
    log.info("advance_added id=%s amount=%s", new_id, args.amount)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s",
                 row["id"], row["status"], row.get("amount") or "",
                 row.get("employee") or "")
    return 0


CLI = [
    ("advance-add", _add_create_args, _handle_create),
    ("advance-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "finance",
    "requires": ["employee"],
    "description": "Salary advance requests with approval, disbursement, and repayment tracking.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
