"""Asset module — company-issued equipment with assignment history.

Owns ``asset`` and ``asset_assignment`` tables (migration 002).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "asset"
LABEL = "Assets"
ICON = "package"

LIST_COLUMNS = ("asset_code", "name", "category", "current_holder", "status")
ALLOWED_STATUS = ("available", "assigned", "maintenance", "retired", "lost")


def ensure_schema(conn: sqlite3.Connection) -> None:
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _next_code(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS nxt FROM asset")
    return f"AST-{int(cur.fetchone()['nxt']):04d}"


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("""
        SELECT a.id, a.asset_code, a.name, a.category, a.serial_number,
               a.purchase_cost_minor, a.status, a.purchase_date,
               (SELECT e.full_name FROM asset_assignment aa
                  LEFT JOIN employee e ON e.id = aa.employee_id
                  WHERE aa.asset_id = a.id AND aa.returned_at = ''
                  ORDER BY aa.id DESC LIMIT 1) AS current_holder
        FROM asset a
        ORDER BY a.asset_code
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM asset WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def _coerce_cost_minor(payload: dict[str, Any]) -> int | None:
    if "purchase_cost_minor" in payload and payload["purchase_cost_minor"] not in (None, ""):
        return int(payload["purchase_cost_minor"])
    if "purchase_cost" in payload and payload["purchase_cost"] not in (None, ""):
        return int(round(float(payload["purchase_cost"]) * 100))
    return None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    code = data.get("asset_code") or _next_code(conn)
    status = (data.get("status") or "available").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["asset_code", "name", "status"]
    vals: list[Any] = [code, name, status]
    for key in ("category", "serial_number", "purchase_date", "notes"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    cost = _coerce_cost_minor(data)
    if cost is not None:
        cols.append("purchase_cost_minor"); vals.append(cost)
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO asset ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("asset_code", "name", "category", "serial_number", "purchase_date",
                "status", "notes"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "purchase_cost_minor" in data or "purchase_cost" in data:
        fields.append("purchase_cost_minor = ?"); values.append(_coerce_cost_minor(data))
    if not fields:
        return
    fields.append("updated = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    values.append(item_id)
    conn.execute(f"UPDATE asset SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM asset WHERE id = ?", (item_id,))
    conn.commit()


def assign_to_employee(conn: sqlite3.Connection, asset_id: int,
                       employee_id: int, notes: str = "") -> int:
    """Assign an asset to an employee and flip its status to 'assigned'."""
    cur = conn.execute(
        "INSERT INTO asset_assignment (asset_id, employee_id, notes) VALUES (?, ?, ?)",
        (int(asset_id), int(employee_id), notes or ""))
    conn.execute("UPDATE asset SET status='assigned' WHERE id = ?", (int(asset_id),))
    conn.commit()
    return int(cur.lastrowid)


def return_asset(conn: sqlite3.Connection, asset_id: int,
                 condition_out: str = "") -> None:
    """Mark the open assignment for this asset as returned and flip status."""
    conn.execute("""
        UPDATE asset_assignment
        SET returned_at = strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'),
            condition_out = ?
        WHERE asset_id = ? AND returned_at = ''
    """, (condition_out or "", int(asset_id)))
    conn.execute("UPDATE asset SET status='available' WHERE id = ?", (int(asset_id),))
    conn.commit()


def _emp_options(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT id, full_name AS label FROM employee ORDER BY full_name")
    return [{"id": r["id"], "label": r["label"]} for r in cur.fetchall()]


def _format_minor(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"₹{int(value)/100:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _render_list_html(rows: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/asset/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    status_opts = "".join(
        f'<option value="{s}"{" selected" if s == "available" else ""}>{s}</option>'
        for s in ALLOWED_STATUS)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Asset</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Name*<input name="name" required placeholder="MacBook Pro 14&quot;"></label>
    <label>Category<input name="category" placeholder="laptop / phone / desk / monitor"></label>
    <label>Serial number<input name="serial_number"></label>
    <label>Purchase date<input name="purchase_date" type="date"></label>
    <label>Purchase cost (₹)<input name="purchase_cost" type="number" step="0.01" min="0"></label>
    <label>Status<select name="status">{status_opts}</select></label>
    <label>Notes<textarea name="notes"></textarea></label>
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
  const r = await fetch('/api/m/asset', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete asset #' + id + '?')) return;
  const r = await fetch('/api/m/asset/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""


def list_view(handler) -> None:
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    body = _render_list_html(list_rows(conn))
    handler._html(200, render_module_page(title=LABEL, nav_active=NAME, body_html=body))


def detail_api_json(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No asset with id {int(item_id)}"))
        return

    # Assignment history
    hist = conn.execute("""
        SELECT aa.id, aa.assigned_at, aa.returned_at, aa.condition_out,
               e.full_name AS holder, e.id AS employee_id
        FROM asset_assignment aa
        LEFT JOIN employee e ON e.id = aa.employee_id
        WHERE aa.asset_id = ? ORDER BY aa.assigned_at DESC
    """, (int(item_id),)).fetchall()
    if hist:
        rows_html = "".join(
            f"<tr><td>{_esc(h['assigned_at'])}</td><td>{_esc(h['returned_at']) or '<em>holding</em>'}</td>"
            f"<td><a href=\"/m/employee/{int(h['employee_id'])}\">{_esc(h['holder'])}</a></td>"
            f"<td>{_esc(h['condition_out'])}</td></tr>"
            for h in hist)
        hist_body = (f"<table><thead><tr><th>Assigned</th><th>Returned</th><th>Holder</th>"
                     f"<th>Condition out</th></tr></thead><tbody>{rows_html}</tbody></table>")
    else:
        hist_body = '<div class="empty">No assignment history.</div>'

    emps = _emp_options(conn)
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in emps)
    assign_body = f"""
<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
  <select id="assign-to" style="flex:1;padding:7px 10px;background:var(--bg);
    color:var(--text);border:1px solid var(--border);border-radius:6px">
    <option value="">-- select employee --</option>{emp_opts}
  </select>
  <button onclick="assignTo({int(item_id)})">Assign</button>
  <button onclick="returnAsset({int(item_id)})" class="ghost">Mark returned</button>
</div>
<script>
async function assignTo(assetId) {{
  const sel = document.getElementById('assign-to');
  if (!sel.value) {{ alert('Pick an employee first'); return; }}
  const r = await fetch('/api/m/asset/' + assetId + '/assign', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{employee_id: parseInt(sel.value, 10)}})
  }});
  if (r.ok) location.reload(); else alert('Assign failed: ' + await r.text());
}}
async function returnAsset(assetId) {{
  if (!confirm('Mark asset returned?')) return;
  const r = await fetch('/api/m/asset/' + assetId + '/return', {{method: 'POST'}});
  if (r.ok) location.reload(); else alert('Return failed');
}}
</script>
"""

    fields = [
        ("Asset code", row.get("asset_code")),
        ("Name", row.get("name")),
        ("Category", row.get("category")),
        ("Serial number", row.get("serial_number")),
        ("Status", row.get("status")),
        ("Purchase date", row.get("purchase_date")),
        ("Purchase cost", _format_minor(row.get("purchase_cost_minor"))),
        ("Notes", row.get("notes")),
    ]
    related = (detail_section(title="Assign / return", body_html=assign_body)
               + detail_section(title="Assignment history", body_html=hist_body))
    handler._html(200, render_detail_page(
        title=row.get("name") or "Asset",
        nav_active=NAME,
        subtitle=row.get("asset_code") or "",
        fields=fields,
        related_html=related,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}",
        delete_redirect=f"/m/{NAME}",
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


def assign_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    emp = payload.get("employee_id")
    if not emp:
        handler._json({"error": "employee_id required"}, code=400); return
    try:
        new_id = assign_to_employee(conn, int(item_id), int(emp), payload.get("notes") or "")
    except sqlite3.IntegrityError as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True, "assignment_id": new_id})


def return_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    return_asset(conn, int(item_id), payload.get("condition_out") or "")
    handler._json({"ok": True})


ROUTES = {
    "GET": [
        (r"^/api/m/asset/(\d+)/?$", detail_api_json),
        (r"^/m/asset/?$", list_view),
        (r"^/m/asset/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/asset/(\d+)/assign/?$", assign_api),
        (r"^/api/m/asset/(\d+)/return/?$", return_api),
        (r"^/api/m/asset/?$", create_api),
        (r"^/api/m/asset/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/asset/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--category", default="general")
    parser.add_argument("--serial-number")
    parser.add_argument("--purchase-cost", type=float)
    parser.add_argument("--purchase-date")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "name": args.name,
        "category": args.category,
        "serial_number": getattr(args, "serial_number", None),
        "purchase_cost": getattr(args, "purchase_cost", None),
        "purchase_date": getattr(args, "purchase_date", None),
    })
    log.info("asset_added id=%s name=%s", new_id, args.name)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s", row["asset_code"], row["status"],
                 row.get("category") or "", row["name"])
    return 0


CLI = [
    ("asset-add", _add_create_args, _handle_create),
    ("asset-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "operations",
    "requires": ["employee"],
    "description": "Company asset register with employee assignment history.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
