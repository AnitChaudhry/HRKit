"""Referral module — employee referrals + bonus tracking.

Owns ``referral`` (migration 002).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "referral"
LABEL = "Referrals"
ICON = "user-plus"

LIST_COLUMNS = ("candidate_name", "position_applied", "referrer", "status", "bonus")
ALLOWED_STATUS = ("submitted", "screened", "interviewed", "offered", "hired", "rejected", "withdrawn")


def ensure_schema(conn: sqlite3.Connection) -> None:
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


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


def _coerce_minor(payload: dict[str, Any], rupees_key="bonus", minor_key="bonus_minor") -> int | None:
    if minor_key in payload and payload[minor_key] not in (None, ""):
        return int(payload[minor_key])
    if rupees_key in payload and payload[rupees_key] not in (None, ""):
        return int(round(float(payload[rupees_key]) * 100))
    return None


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("""
        SELECT r.id, r.candidate_name, r.candidate_email, r.position_applied,
               r.status, r.bonus_minor, r.bonus_paid, r.submitted_at,
               e.full_name AS referrer
        FROM referral r
        LEFT JOIN employee e ON e.id = r.referrer_id
        ORDER BY r.submitted_at DESC
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["bonus"] = _format_minor(d.get("bonus_minor"))
        out.append(d)
    return out


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("""
        SELECT r.*, e.full_name AS referrer
        FROM referral r LEFT JOIN employee e ON e.id = r.referrer_id
        WHERE r.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    name = (data.get("candidate_name") or "").strip()
    referrer = data.get("referrer_id")
    if not name:
        raise ValueError("candidate_name is required")
    if not referrer:
        raise ValueError("referrer_id is required")
    status = (data.get("status") or "submitted").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["candidate_name", "referrer_id", "status"]
    vals: list[Any] = [name, int(referrer), status]
    for key in ("candidate_email", "candidate_phone", "position_applied", "notes"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    bonus = _coerce_minor(data)
    if bonus is not None:
        cols.append("bonus_minor"); vals.append(bonus)
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO referral ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("candidate_name", "candidate_email", "candidate_phone",
                "position_applied", "status", "notes"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "bonus_minor" in data or "bonus" in data:
        fields.append("bonus_minor = ?"); values.append(_coerce_minor(data))
    if "bonus_paid" in data:
        fields.append("bonus_paid = ?"); values.append(1 if data["bonus_paid"] else 0)
        if data["bonus_paid"]:
            fields.append("bonus_paid_at = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE referral SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM referral WHERE id = ?", (item_id,))
    conn.commit()


def _emp_options(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT id, full_name AS label FROM employee ORDER BY full_name")
    return [{"id": r["id"], "label": r["label"]} for r in cur.fetchall()]


def _render_list_html(rows, employees) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/referral/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New referral</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Candidate name*<input name="candidate_name" required></label>
    <label>Candidate email<input name="candidate_email" type="email"></label>
    <label>Phone<input name="candidate_phone"></label>
    <label>Position applied<input name="position_applied"></label>
    <label>Referrer*<select name="referrer_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Bonus (₹)<input name="bonus" type="number" step="0.01" min="0"></label>
    <label>Notes<textarea name="notes"></textarea></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Submit referral</button>
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
  const r = await fetch('/api/m/referral', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete referral #' + id + '?')) return;
  const r = await fetch('/api/m/referral/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""


def list_view(handler) -> None:
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME,
        body_html=_render_list_html(list_rows(conn), _emp_options(conn))))


def detail_api_json(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No referral with id {int(item_id)}"))
        return
    fields = [
        ("Candidate name", row.get("candidate_name")),
        ("Email", row.get("candidate_email")),
        ("Phone", row.get("candidate_phone")),
        ("Position applied", row.get("position_applied")),
        ("Referrer", row.get("referrer")),
        ("Status", row.get("status")),
        ("Bonus", _format_minor(row.get("bonus_minor"))),
        ("Bonus paid", "Yes" if row.get("bonus_paid") else "No"),
        ("Bonus paid at", row.get("bonus_paid_at")),
        ("Submitted", row.get("submitted_at")),
        ("Notes", row.get("notes")),
    ]
    handler._html(200, render_detail_page(
        title=row.get("candidate_name") or "Referral",
        nav_active=NAME, subtitle=row.get("position_applied") or "",
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


ROUTES = {
    "GET": [
        (r"^/api/m/referral/(\d+)/?$", detail_api_json),
        (r"^/m/referral/?$", list_view),
        (r"^/m/referral/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/referral/?$", create_api),
        (r"^/api/m/referral/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/referral/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser) -> None:
    parser.add_argument("--candidate-name", required=True)
    parser.add_argument("--referrer-id", type=int, required=True)
    parser.add_argument("--candidate-email")
    parser.add_argument("--position-applied")
    parser.add_argument("--bonus", type=float)


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "candidate_name": args.candidate_name,
        "referrer_id": args.referrer_id,
        "candidate_email": getattr(args, "candidate_email", None),
        "position_applied": getattr(args, "position_applied", None),
        "bonus": getattr(args, "bonus", None),
    })
    log.info("referral_added id=%s name=%s", new_id, args.candidate_name)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s", row["id"], row["status"],
                 row["candidate_name"], row.get("referrer") or "")
    return 0


CLI = [
    ("referral-add", _add_create_args, _handle_create),
    ("referral-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "talent",
    "requires": ["employee"],
    "description": "Employee referrals — track candidates, statuses, and bonuses.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
