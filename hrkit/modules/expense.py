"""Expense module — employee expense reports + reimbursements.

Owns ``expense`` and ``expense_category`` (migration 002).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "expense"
LABEL = "Expenses"
ICON = "receipt"

LIST_COLUMNS = ("expense_code", "employee", "category", "amount", "expense_date", "status")
ALLOWED_STATUS = ("draft", "submitted", "approved", "reimbursed", "rejected")


def ensure_schema(conn: sqlite3.Connection) -> None:
    return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _format_minor(v: Any) -> str:
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


def _next_code(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS nxt FROM expense")
    return f"EXP-{int(cur.fetchone()['nxt']):04d}"


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("""
        SELECT x.id, x.expense_code, x.employee_id, x.category_id, x.amount_minor,
               x.currency, x.expense_date, x.status, x.description,
               e.full_name AS employee, c.name AS category
        FROM expense x
        LEFT JOIN employee e ON e.id = x.employee_id
        LEFT JOIN expense_category c ON c.id = x.category_id
        ORDER BY x.expense_date DESC, x.id DESC
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["amount"] = _format_minor(d.get("amount_minor"))
        out.append(d)
    return out


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("""
        SELECT x.*, e.full_name AS employee, c.name AS category,
               ap.full_name AS approver
        FROM expense x
        LEFT JOIN employee e ON e.id = x.employee_id
        LEFT JOIN expense_category c ON c.id = x.category_id
        LEFT JOIN employee ap ON ap.id = x.approved_by
        WHERE x.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    employee_id = data.get("employee_id")
    if not employee_id:
        raise ValueError("employee_id is required")
    amount = _coerce_minor(data)
    if amount is None or amount <= 0:
        raise ValueError("amount must be > 0")
    code = data.get("expense_code") or _next_code(conn)
    status = (data.get("status") or "draft").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["expense_code", "employee_id", "amount_minor", "status"]
    vals: list[Any] = [code, int(employee_id), amount, status]
    for key in ("category_id", "expense_date", "description", "currency",
                "receipt_path", "notes"):
        if data.get(key) not in (None, ""):
            cols.append(key); vals.append(data[key])
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO expense ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    new_id = int(cur.lastrowid)
    # Seed the approval queue when the expense is born already-submitted.
    if status == "submitted":
        _seed_approvals(conn, new_id, int(employee_id))
    return new_id


def _seed_approvals(conn: sqlite3.Connection, expense_id: int,
                    employee_id: int) -> None:
    try:
        from . import approval as approval_mod
        chain = approval_mod.default_approver_chain(conn, int(employee_id))
        if chain:
            approval_mod.request_approvals(
                conn, request_type="expense",
                request_id=int(expense_id), approver_ids=chain)
    except Exception as exc:  # noqa: BLE001
        log.warning("approval.request_approvals failed for expense %s: %s",
                    expense_id, exc)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("expense_code", "category_id", "expense_date", "description",
                "currency", "receipt_path", "status", "notes"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "amount_minor" in data or "amount" in data:
        fields.append("amount_minor = ?"); values.append(_coerce_minor(data))
    new_status = data.get("status")
    if new_status == "approved":
        fields.append("approved_at = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    if new_status == "submitted":
        fields.append("submitted_at = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    if "approved_by" in data:
        fields.append("approved_by = ?"); values.append(data["approved_by"])
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE expense SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    # Keep the approval queue in sync with the bespoke status field.
    if new_status == "submitted":
        row = conn.execute(
            "SELECT employee_id FROM expense WHERE id = ?", (int(item_id),)
        ).fetchone()
        if row:
            # Avoid duplicating approvals if already seeded earlier.
            existing = conn.execute(
                "SELECT 1 FROM approval WHERE request_type='expense' AND request_id=?",
                (int(item_id),)
            ).fetchone()
            if not existing:
                _seed_approvals(conn, int(item_id), int(row["employee_id"]))
    elif new_status in ("approved", "rejected", "reimbursed"):
        outcome = "approved" if new_status in ("approved", "reimbursed") else "rejected"
        try:
            from . import approval as approval_mod
            approval_mod.reflect_request_outcome(
                conn, request_type="expense",
                request_id=int(item_id), outcome=outcome)
        except Exception as exc:  # noqa: BLE001
            log.warning("approval.reflect_request_outcome failed for expense %s: %s",
                        item_id, exc)


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM expense WHERE id = ?", (item_id,))
    conn.commit()


def _emp_options(conn):
    return [{"id": r["id"], "label": r["full_name"]}
            for r in conn.execute(
                "SELECT id, full_name FROM employee ORDER BY full_name").fetchall()]


def _cat_options(conn):
    return [{"id": r["id"], "label": r["name"]}
            for r in conn.execute(
                "SELECT id, name FROM expense_category ORDER BY name").fetchall()]


def _render_list_html(rows, employees, categories) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/expense/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    cat_opts = "".join(f'<option value="{c["id"]}">{_esc(c["label"])}</option>' for c in categories)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New expense</button>
  <a href="/m/expense/categories" style="padding:7px 14px;border:1px solid var(--border);
     border-radius:6px;color:var(--dim);text-decoration:none;font-size:13px">Categories</a>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Employee*<select name="employee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Category<select name="category_id"><option value="">-- (uncategorized)</option>{cat_opts}</select></label>
    <label>Amount (₹)*<input name="amount" type="number" step="0.01" min="0" required></label>
    <label>Currency<input name="currency" value="INR" maxlength="3"></label>
    <label>Expense date<input name="expense_date" type="date"></label>
    <label>Description<textarea name="description"></textarea></label>
    <label>Status<select name="status">
      <option value="draft" selected>draft</option>
      <option value="submitted">submitted</option></select></label>
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
  if (payload.category_id === '') delete payload.category_id;
  const r = await fetch('/api/m/expense', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete expense #' + id + '?')) return;
  const r = await fetch('/api/m/expense/' + id, {{method: 'DELETE'}});
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
            list_rows(conn), _emp_options(conn), _cat_options(conn))))


def detail_api_json(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No expense with id {int(item_id)}"))
        return
    fields = [
        ("Expense code", row.get("expense_code")),
        ("Employee", row.get("employee")),
        ("Category", row.get("category")),
        ("Amount", _format_minor(row.get("amount_minor"))),
        ("Currency", row.get("currency")),
        ("Expense date", row.get("expense_date")),
        ("Description", row.get("description")),
        ("Status", row.get("status")),
        ("Submitted", row.get("submitted_at")),
        ("Approved by", row.get("approver")),
        ("Approved at", row.get("approved_at")),
        ("Reimbursement date", row.get("reimbursement_date")),
        ("Receipt path", row.get("receipt_path")),
        ("Notes", row.get("notes")),
    ]
    handler._html(200, render_detail_page(
        title=row.get("description") or row.get("expense_code") or "Expense",
        nav_active=NAME, subtitle=row.get("expense_code") or "",
        fields=fields, item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"status": list(ALLOWED_STATUS)},
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


# ---------- Categories sub-view ----------
def category_list_view(handler) -> None:
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    cats = conn.execute(
        "SELECT id, name, code, max_amount_minor, notes FROM expense_category ORDER BY name"
    ).fetchall()
    rows_html = "".join(
        f"<tr><td>{_esc(c['name'])}</td><td>{_esc(c['code'])}</td>"
        f"<td>{_format_minor(c['max_amount_minor']) or '—'}</td><td>{_esc(c['notes'])}</td>"
        f"<td><button onclick=\"deleteCat({int(c['id'])})\">×</button></td></tr>"
        for c in cats)
    body = f"""
<div class="module-toolbar"><h1>Expense categories</h1>
  <a href="/m/expense" style="font-size:13px;color:var(--accent);text-decoration:none">&larr; Back</a></div>
<form onsubmit="addCat(event)" style="display:grid;grid-template-columns:repeat(4,1fr) auto;
  gap:8px;margin-bottom:14px">
  <input name="name" required placeholder="Name (e.g. Travel)">
  <input name="code" placeholder="Code (TRV)">
  <input name="max_amount" type="number" step="0.01" placeholder="Max amount (₹)">
  <input name="notes" placeholder="Notes">
  <button>+ Add</button>
</form>
<table class="data-table">
  <thead><tr><th>Name</th><th>Code</th><th>Max amount</th><th>Notes</th><th></th></tr></thead>
  <tbody>{rows_html or '<tr><td colspan="5" class="empty">No categories yet.</td></tr>'}</tbody>
</table>
<script>
async function addCat(ev) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const r = await fetch('/api/m/expense/categories', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else alert('Add failed: ' + await r.text());
}}
async function deleteCat(id) {{
  if (!confirm('Delete category?')) return;
  const r = await fetch('/api/m/expense/categories/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""
    handler._html(200, render_module_page(title="Expense categories", nav_active=NAME, body_html=body))


def category_create_api(handler) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    name = (payload.get("name") or "").strip()
    if not name:
        handler._json({"error": "name required"}, code=400); return
    cols = ["name"]; vals: list[Any] = [name]
    for key in ("code", "notes"):
        if payload.get(key) not in (None, ""):
            cols.append(key); vals.append(payload[key])
    if "max_amount" in payload and payload["max_amount"] not in (None, ""):
        cols.append("max_amount_minor")
        vals.append(int(round(float(payload["max_amount"]) * 100)))
    placeholders = ", ".join("?" for _ in cols)
    try:
        cur = conn.execute(
            f"INSERT INTO expense_category ({', '.join(cols)}) VALUES ({placeholders})", vals)
    except sqlite3.IntegrityError as exc:
        handler._json({"error": str(exc)}, code=400); return
    conn.commit()
    handler._json({"ok": True, "id": int(cur.lastrowid)})


def category_delete_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    conn.execute("DELETE FROM expense_category WHERE id = ?", (int(item_id),))
    conn.commit()
    handler._json({"ok": True})


ROUTES = {
    "GET": [
        (r"^/api/m/expense/(\d+)/?$", detail_api_json),
        (r"^/m/expense/categories/?$", category_list_view),
        (r"^/m/expense/?$", list_view),
        (r"^/m/expense/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/expense/categories/?$", category_create_api),
        (r"^/api/m/expense/?$", create_api),
        (r"^/api/m/expense/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/expense/categories/(\d+)/?$", category_delete_api),
        (r"^/api/m/expense/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser) -> None:
    parser.add_argument("--employee-id", type=int, required=True)
    parser.add_argument("--amount", type=float, required=True)
    parser.add_argument("--category-id", type=int)
    parser.add_argument("--description")
    parser.add_argument("--expense-date")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "employee_id": args.employee_id,
        "amount": args.amount,
        "category_id": getattr(args, "category_id", None),
        "description": getattr(args, "description", None),
        "expense_date": getattr(args, "expense_date", None),
    })
    log.info("expense_added id=%s amount=%s", new_id, args.amount)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s\t%s", row["expense_code"], row["status"],
                 row.get("employee") or "", row.get("amount") or "",
                 row.get("description") or "")
    return 0


CLI = [
    ("expense-add", _add_create_args, _handle_create),
    ("expense-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "finance",
    "requires": ["employee"],
    "description": "Expense reports + reimbursement tracking with category limits.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
