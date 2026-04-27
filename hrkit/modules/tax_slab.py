"""Tax slab module — payroll tax brackets per country / regime / FY.

Owns ``tax_slab`` (migration 002). Used at payroll-run time to compute
income tax. Helper :func:`compute_tax_minor` returns the tax amount in
minor units for a given annual income + regime.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "tax_slab"
LABEL = "Tax Slabs"
ICON = "percent"

LIST_COLUMNS = ("country", "regime", "fy_start", "slab_min_minor", "slab_max_minor",
                "rate_percent")
ALLOWED_REGIME = ("old", "new", "flat", "custom")


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
        SELECT * FROM tax_slab
        ORDER BY country, regime, fy_start, slab_min_minor
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("SELECT * FROM tax_slab WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    regime = (data.get("regime") or "new").strip()
    if regime not in ALLOWED_REGIME:
        raise ValueError(f"regime must be one of {ALLOWED_REGIME}")
    cols = ["name", "regime"]; vals: list[Any] = [name, regime]
    for key in ("country", "fy_start", "notes"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    for k_minor, k_rupees in (("slab_min_minor", "slab_min"), ("slab_max_minor", "slab_max")):
        if k_minor in data and data[k_minor] not in (None, ""):
            cols.append(k_minor); vals.append(int(data[k_minor]))
        elif k_rupees in data and data[k_rupees] not in (None, ""):
            cols.append(k_minor); vals.append(int(round(float(data[k_rupees]) * 100)))
    for key in ("rate_percent", "surcharge_percent"):
        if data.get(key) is not None:
            cols.append(key); vals.append(float(data[key]))
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO tax_slab ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("name", "country", "regime", "fy_start", "notes"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    for key in ("slab_min_minor", "slab_max_minor"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(int(data[key]))
    for key in ("rate_percent", "surcharge_percent"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(float(data[key]))
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE tax_slab SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn, item_id):
    conn.execute("DELETE FROM tax_slab WHERE id = ?", (item_id,))
    conn.commit()


def compute_tax_minor(conn: sqlite3.Connection, *,
                      annual_income_minor: int,
                      country: str = "IN", regime: str = "new",
                      fy_start: str = "") -> int:
    """Apply matching slabs to an annual income; return tax in minor units."""
    where = ["country = ?", "regime = ?"]
    params: list[Any] = [country, regime]
    if fy_start:
        where.append("fy_start = ?"); params.append(fy_start)
    rows = conn.execute(
        f"SELECT slab_min_minor, slab_max_minor, rate_percent, surcharge_percent "
        f"FROM tax_slab WHERE {' AND '.join(where)} "
        f"ORDER BY slab_min_minor",
        params).fetchall()
    if not rows:
        return 0
    tax = 0.0
    income = max(0, int(annual_income_minor))
    for r in rows:
        lo = int(r["slab_min_minor"] or 0)
        hi = int(r["slab_max_minor"] or 0)
        if income <= lo:
            break
        upper = income if (hi <= 0 or income < hi) else hi
        slab_amount = max(0, upper - lo)
        rate = float(r["rate_percent"] or 0) / 100.0
        surcharge = float(r["surcharge_percent"] or 0) / 100.0
        tax += slab_amount * rate * (1.0 + surcharge)
        if hi <= 0 or income <= hi:
            break
    return int(round(tax))


def _render_list_html(rows) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/tax_slab/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    regime_opts = "".join(f'<option value="{r}"{" selected" if r == "new" else ""}>{r}</option>'
                          for r in ALLOWED_REGIME)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add slab</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Name*<input name="name" required placeholder="e.g. FY26 New Regime — 5%"></label>
    <label>Country<input name="country" value="IN" maxlength="3"></label>
    <label>Regime<select name="regime">{regime_opts}</select></label>
    <label>FY start<input name="fy_start" type="date" placeholder="2026-04-01"></label>
    <label>Slab min (₹)<input name="slab_min" type="number" step="0.01" min="0"></label>
    <label>Slab max (₹, 0 for unlimited)<input name="slab_max" type="number" step="0.01" min="0"></label>
    <label>Rate (%)<input name="rate_percent" type="number" step="0.01" min="0" max="100"></label>
    <label>Surcharge (%)<input name="surcharge_percent" type="number" step="0.01" min="0" max="100"></label>
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
  const r = await fetch('/api/m/tax_slab', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete?'))) return;
  const r = await fetch('/api/m/tax_slab/' + id, {{method: 'DELETE'}});
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
                      subtitle=f"No slab with id {int(item_id)}"))
        return
    fields = [
        ("Name", row.get("name")),
        ("Country", row.get("country")),
        ("Regime", row.get("regime")),
        ("FY start", row.get("fy_start")),
        ("Slab min", _format_minor(row.get("slab_min_minor"))),
        ("Slab max", _format_minor(row.get("slab_max_minor")) or "(unlimited)"),
        ("Rate %", row.get("rate_percent")),
        ("Surcharge %", row.get("surcharge_percent")),
        ("Notes", row.get("notes")),
    ]
    handler._html(200, render_detail_page(
        title=row.get("name") or "Tax slab",
        nav_active=NAME, subtitle=f"{row.get('country')} / {row.get('regime')}",
        fields=fields, item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"regime": list(ALLOWED_REGIME)},
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
        (r"^/api/m/tax_slab/(\d+)/?$", detail_api_json),
        (r"^/m/tax_slab/?$", list_view),
        (r"^/m/tax_slab/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/tax_slab/?$", create_api),
        (r"^/api/m/tax_slab/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/tax_slab/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--name", required=True)
    parser.add_argument("--country", default="IN")
    parser.add_argument("--regime", default="new", choices=list(ALLOWED_REGIME))
    parser.add_argument("--slab-min", type=float, default=0)
    parser.add_argument("--slab-max", type=float, default=0)
    parser.add_argument("--rate-percent", type=float, default=0)


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "name": args.name,
        "country": args.country,
        "regime": args.regime,
        "slab_min": args.slab_min,
        "slab_max": args.slab_max,
        "rate_percent": args.rate_percent,
    })
    log.info("tax_slab_added id=%s name=%s", new_id, args.name)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s..%s @ %s%%",
                 row["id"], row["country"], row["regime"],
                 _format_minor(row["slab_min_minor"]),
                 _format_minor(row["slab_max_minor"]),
                 row["rate_percent"])
    return 0


CLI = [
    ("tax-slab-add", _add_create_args, _handle_create),
    ("tax-slab-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "finance",
    "requires": [],
    "description": "Income tax slabs / brackets per country, regime, financial year.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
