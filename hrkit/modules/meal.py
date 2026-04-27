"""Meal / lunch module — cafeteria menu + employee meal orders.

Owns ``meal`` and ``meal_order`` (migration 002).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "meal"
LABEL = "Lunch"
ICON = "utensils"

LIST_COLUMNS = ("name", "category", "price", "status", "orders_today")
ALLOWED_STATUS = ("active", "discontinued")
ALLOWED_CATEGORY = ("veg", "non_veg", "vegan", "jain")


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


def list_rows(conn):
    cur = conn.execute("""
        SELECT m.*,
               (SELECT COUNT(*) FROM meal_order o
                  WHERE o.meal_id = m.id
                    AND o.order_date = strftime('%Y-%m-%d','now','+05:30')
               ) AS orders_today
        FROM meal m ORDER BY m.name
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["price"] = _format_minor(d.get("price_minor"))
        out.append(d)
    return out


def get_row(conn, item_id):
    cur = conn.execute("SELECT * FROM meal WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def _coerce_minor(payload: dict[str, Any]) -> int | None:
    if "price_minor" in payload and payload["price_minor"] not in (None, ""):
        return int(payload["price_minor"])
    if "price" in payload and payload["price"] not in (None, ""):
        return int(round(float(payload["price"]) * 100))
    return None


def create_row(conn, data):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    cat = (data.get("category") or "veg").strip()
    if cat not in ALLOWED_CATEGORY:
        raise ValueError(f"category must be one of {ALLOWED_CATEGORY}")
    cols = ["name", "category"]; vals: list[Any] = [name, cat]
    if data.get("description") is not None:
        cols.append("description"); vals.append(data["description"])
    price = _coerce_minor(data)
    if price is not None:
        cols.append("price_minor"); vals.append(price)
    if data.get("available_days") is not None:
        cols.append("available_days"); vals.append(data["available_days"])
    if data.get("status") in ALLOWED_STATUS:
        cols.append("status"); vals.append(data["status"])
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO meal ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("name", "description", "category", "available_days", "status"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "price_minor" in data or "price" in data:
        fields.append("price_minor = ?"); values.append(_coerce_minor(data))
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE meal SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn, item_id):
    conn.execute("DELETE FROM meal WHERE id = ?", (item_id,))
    conn.commit()


def place_order(conn, employee_id: int, meal_id: int, quantity: int = 1,
                order_date: str | None = None) -> int:
    price = conn.execute(
        "SELECT price_minor FROM meal WHERE id = ?", (int(meal_id),)).fetchone()
    if not price:
        raise LookupError(f"meal {meal_id} not found")
    total = int(price["price_minor"] or 0) * max(1, int(quantity))
    cur = conn.execute("""
        INSERT INTO meal_order (employee_id, meal_id, quantity, total_minor, order_date)
        VALUES (?, ?, ?, ?, COALESCE(NULLIF(?, ''), strftime('%Y-%m-%d','now','+05:30')))
    """, (int(employee_id), int(meal_id), int(quantity), total, order_date or ""))
    conn.commit()
    return int(cur.lastrowid)


def _emp_options(conn):
    return [{"id": r["id"], "label": r["full_name"]}
            for r in conn.execute(
                "SELECT id, full_name FROM employee ORDER BY full_name").fetchall()]


def _render_list_html(rows) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/meal/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    cat_opts = "".join(f'<option value="{c}"{" selected" if c == "veg" else ""}>{c}</option>'
                       for c in ALLOWED_CATEGORY)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add meal</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Name*<input name="name" required></label>
    <label>Description<textarea name="description"></textarea></label>
    <label>Category<select name="category">{cat_opts}</select></label>
    <label>Price (₹)<input name="price" type="number" step="0.01" min="0"></label>
    <label>Available days (JSON, 1=Mon..7=Sun)<input name="available_days" value="[1,2,3,4,5]"></label>
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
  const r = await fetch('/api/m/meal', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete?'))) return;
  const r = await fetch('/api/m/meal/' + id, {{method: 'DELETE'}});
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
    from hrkit.templates import render_detail_page, detail_section
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No meal with id {int(item_id)}"))
        return
    orders = conn.execute("""
        SELECT o.id, o.order_date, o.quantity, o.total_minor, o.status,
               e.id AS employee_id, e.full_name
        FROM meal_order o
        JOIN employee e ON e.id = o.employee_id
        WHERE o.meal_id = ? ORDER BY o.order_date DESC, o.id DESC LIMIT 200
    """, (int(item_id),)).fetchall()
    if orders:
        rows_html = "".join(
            f"<tr><td>{_esc(o['order_date'])}</td>"
            f"<td><a href=\"/m/employee/{int(o['employee_id'])}\">{_esc(o['full_name'])}</a></td>"
            f"<td>{_esc(o['quantity'])}</td><td>{_format_minor(o['total_minor'])}</td>"
            f"<td>{_esc(o['status'])}</td></tr>"
            for o in orders)
        order_table = (f"<table><thead><tr><th>Date</th><th>Employee</th><th>Qty</th>"
                       f"<th>Total</th><th>Status</th></tr></thead><tbody>{rows_html}</tbody></table>")
    else:
        order_table = '<div class="empty">No orders yet.</div>'

    emps = _emp_options(conn)
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in emps)
    order_form = f"""
<form onsubmit="placeOrder(event,{int(item_id)})" style="display:flex;gap:8px;align-items:end">
  <label style="flex:1;margin:0">Employee
    <select name="employee_id" required style="width:100%;padding:7px 10px;
      background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px">
      <option value="">--</option>{emp_opts}
    </select>
  </label>
  <label style="margin:0">Qty
    <input name="quantity" type="number" min="1" value="1" style="width:80px"></label>
  <button>Order</button>
</form>
<script>
async function placeOrder(ev, mealId) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const r = await fetch('/api/m/meal/' + mealId + '/order', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Order failed', 'error');
}}
</script>
"""

    fields = [
        ("Name", row.get("name")),
        ("Description", row.get("description")),
        ("Category", row.get("category")),
        ("Price", _format_minor(row.get("price_minor"))),
        ("Available days", row.get("available_days")),
        ("Status", row.get("status")),
    ]
    related = (detail_section(title="Place order", body_html=order_form)
               + detail_section(title="Recent orders", body_html=order_table))
    handler._html(200, render_detail_page(
        title=row.get("name") or "Meal", nav_active=NAME,
        subtitle=row.get("category") or "",
        fields=fields, related_html=related,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"status": list(ALLOWED_STATUS), "category": list(ALLOWED_CATEGORY)},
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


def order_api(handler, meal_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    emp = payload.get("employee_id")
    if not emp:
        handler._json({"error": "employee_id required"}, code=400); return
    try:
        oid = place_order(conn, int(emp), int(meal_id),
                          quantity=int(payload.get("quantity") or 1),
                          order_date=payload.get("order_date") or "")
    except (LookupError, ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True, "order_id": oid})


ROUTES = {
    "GET": [
        (r"^/api/m/meal/(\d+)/?$", detail_api_json),
        (r"^/m/meal/?$", list_view),
        (r"^/m/meal/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/meal/(\d+)/order/?$", order_api),
        (r"^/api/m/meal/?$", create_api),
        (r"^/api/m/meal/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/meal/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--name", required=True)
    parser.add_argument("--category", default="veg", choices=list(ALLOWED_CATEGORY))
    parser.add_argument("--price", type=float)


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "name": args.name,
        "category": args.category,
        "price": getattr(args, "price", None),
    })
    log.info("meal_added id=%s name=%s", new_id, args.name)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s\t%s today",
                 row["id"], row["status"], row["category"],
                 row["name"], row.get("orders_today") or 0)
    return 0


CLI = [
    ("meal-add", _add_create_args, _handle_create),
    ("meal-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "operations",
    "requires": ["employee"],
    "description": "Cafeteria menu + employee meal orders.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
