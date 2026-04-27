"""Full-and-final (F&F) settlement module — gratuity + last salary + leave encashment.

Reads from existing ``exit_record`` (extended in migration 002 with
``gratuity_minor``, ``f_and_f_amount_minor``, ``f_and_f_settled_at``,
``f_and_f_breakdown_json``). Provides a calc helper and a settle-now flow.

Indian Payment of Gratuity Act formula (default):
    gratuity = (last_drawn_salary × 15 × years_of_service) / 26
when years_of_service >= 5 (or earlier on death/disability).
Caller can override via :func:`calculate_fnf` arguments.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "f_and_f"
LABEL = "F&F Settlement"
ICON = "file-check"

LIST_COLUMNS = ("employee", "last_working_day", "exit_type",
                "gratuity", "f_and_f_amount", "settled")


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
        SELECT x.id, x.employee_id, x.last_working_day, x.exit_type,
               x.gratuity_minor, x.f_and_f_amount_minor, x.f_and_f_settled_at,
               x.f_and_f_breakdown_json,
               e.full_name AS employee, e.salary_minor AS current_salary_minor,
               e.hire_date
        FROM exit_record x
        LEFT JOIN employee e ON e.id = x.employee_id
        ORDER BY x.last_working_day DESC, x.id DESC
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["gratuity"] = _format_minor(d.get("gratuity_minor"))
        d["f_and_f_amount"] = _format_minor(d.get("f_and_f_amount_minor"))
        d["settled"] = "✓" if d.get("f_and_f_settled_at") else ""
        out.append(d)
    return out


def calculate_fnf(*, monthly_salary_minor: int, years_of_service: float,
                  unused_leave_days: int = 0,
                  bonuses_minor: int = 0,
                  deductions_minor: int = 0,
                  notice_period_days_unserved: int = 0,
                  apply_gratuity: bool | None = None) -> dict[str, Any]:
    """Compute a settlement breakdown.

    Default gratuity formula (India): ``salary × 15 × years / 26`` when
    years >= 5. Pass ``apply_gratuity=True`` to force compute regardless of
    tenure (for death/disability).
    """
    if apply_gratuity is None:
        apply_gratuity = years_of_service >= 5
    gratuity = 0
    if apply_gratuity and monthly_salary_minor > 0 and years_of_service > 0:
        gratuity = int(round(monthly_salary_minor * 15 * years_of_service / 26))

    daily_rate = monthly_salary_minor / 30 if monthly_salary_minor else 0
    leave_encashment = int(round(daily_rate * max(0, unused_leave_days)))
    notice_recovery = int(round(daily_rate * max(0, notice_period_days_unserved)))

    total = (
        monthly_salary_minor  # last month salary
        + leave_encashment
        + gratuity
        + max(0, bonuses_minor)
        - max(0, deductions_minor)
        - notice_recovery
    )
    return {
        "last_month_salary_minor": int(monthly_salary_minor),
        "leave_encashment_minor": leave_encashment,
        "gratuity_minor": gratuity,
        "bonuses_minor": int(bonuses_minor),
        "deductions_minor": int(deductions_minor),
        "notice_recovery_minor": notice_recovery,
        "total_minor": int(total),
        "apply_gratuity": bool(apply_gratuity),
        "years_of_service": float(years_of_service),
    }


def settle(conn: sqlite3.Connection, exit_record_id: int,
           breakdown: dict[str, Any]) -> None:
    """Persist the F&F breakdown back onto the exit_record row."""
    conn.execute("""
        UPDATE exit_record SET
          gratuity_minor = ?,
          f_and_f_amount_minor = ?,
          f_and_f_breakdown_json = ?,
          f_and_f_settled_at = strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')
        WHERE id = ?
    """, (int(breakdown.get("gratuity_minor") or 0),
          int(breakdown.get("total_minor") or 0),
          json.dumps(breakdown),
          int(exit_record_id)))
    conn.commit()


def _years_between(hire_date: str, exit_date: str) -> float:
    if not hire_date or not exit_date:
        return 0.0
    try:
        from datetime import datetime
        h = datetime.fromisoformat(hire_date[:10])
        e = datetime.fromisoformat(exit_date[:10])
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, (e - h).days / 365.25)


def _render_list_html(rows) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/f_and_f/{row["id"]}\'">'
            f'{cells}</tr>')
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <span style="color:var(--dim);font-size:13px;margin-left:auto">
    Exiting employees with their full-and-final settlement status.</span>
</div>
<div style="color:var(--dim);font-size:12px;margin-bottom:10px">
  Computes gratuity (India default formula) + leave encashment + last salary
  − notice-period recovery − any deductions. Stored on the exit record.
</div>
<table class="data-table">
  <thead><tr>{head}</tr></thead>
  <tbody id="rows">{''.join(body_rows) or '<tr><td colspan="6" class="empty">No exits yet.</td></tr>'}</tbody>
</table>
"""


def list_view(handler):
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME, body_html=_render_list_html(list_rows(conn))))


def detail_view(handler, item_id):
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = conn.execute("""
        SELECT x.*, e.full_name AS employee, e.salary_minor AS current_salary_minor,
               e.hire_date
        FROM exit_record x LEFT JOIN employee e ON e.id = x.employee_id
        WHERE x.id = ?
    """, (int(item_id),)).fetchone()
    if not row:
        handler._html(404, render_module_page(
            title="Not found", nav_active=NAME,
            body_html='<div class="empty">Exit record not found.</div>'))
        return
    yos = _years_between(row["hire_date"] or "", row["last_working_day"] or "")
    breakdown_json = row["f_and_f_breakdown_json"] or "{}"
    body = f"""
<div class="module-toolbar">
  <h1>F&amp;F — {_esc(row['employee'] or '')}</h1>
  <a href="/m/f_and_f" style="font-size:13px;color:var(--accent);text-decoration:none">
    &larr; Back</a>
</div>
<table class="data-table" style="max-width:520px;margin-bottom:18px">
  <tr><td>Hire date</td><td>{_esc(row['hire_date'])}</td></tr>
  <tr><td>Last working day</td><td>{_esc(row['last_working_day'])}</td></tr>
  <tr><td>Years of service</td><td>{yos:.2f}</td></tr>
  <tr><td>Current monthly salary</td><td>{_format_minor(row['current_salary_minor'])}</td></tr>
  <tr><td>Notice period (days)</td><td>{row['notice_period_days']}</td></tr>
  <tr><td>Asset returned</td><td>{'Yes' if row['asset_returned'] else 'No'}</td></tr>
</table>
<h3 style="margin:14px 0 8px">Compute settlement</h3>
<form onsubmit="computeAndSettle(event,{int(item_id)},{int(row['current_salary_minor'] or 0)},{yos})"
  style="display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;max-width:520px">
  <label>Unused leave days<input name="unused_leave_days" type="number" min="0" value="0"></label>
  <label>Bonuses (₹)<input name="bonuses" type="number" step="0.01" min="0" value="0"></label>
  <label>Deductions (₹)<input name="deductions" type="number" step="0.01" min="0" value="0"></label>
  <label>Notice unserved (days)<input name="notice_unserved" type="number" min="0" value="0"></label>
  <button style="grid-column:span 2">Compute &amp; settle</button>
</form>
<h3 style="margin:14px 0 8px">Last computed breakdown</h3>
<pre style="background:var(--bg);padding:10px;border:1px solid var(--border);
  border-radius:6px;font-family:'JetBrains Mono',monospace;font-size:12.5px;
  white-space:pre-wrap">{_esc(breakdown_json)}</pre>
<script>
async function computeAndSettle(ev, exitId, salaryMinor, yos) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const payload = {{
    unused_leave_days: parseInt(fd.get('unused_leave_days') || 0, 10),
    bonuses_minor: Math.round(parseFloat(fd.get('bonuses') || 0) * 100),
    deductions_minor: Math.round(parseFloat(fd.get('deductions') || 0) * 100),
    notice_period_days_unserved: parseInt(fd.get('notice_unserved') || 0, 10),
    monthly_salary_minor: salaryMinor,
    years_of_service: yos,
  }};
  const r = await fetch('/api/m/f_and_f/' + exitId + '/settle', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Settle failed: ' + await r.text(), 'error');
}}
</script>
"""
    handler._html(200, render_module_page(
        title=f"F&F — {row['employee']}", nav_active=NAME, body_html=body))


def settle_api(handler, exit_record_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    breakdown = calculate_fnf(
        monthly_salary_minor=int(payload.get("monthly_salary_minor") or 0),
        years_of_service=float(payload.get("years_of_service") or 0),
        unused_leave_days=int(payload.get("unused_leave_days") or 0),
        bonuses_minor=int(payload.get("bonuses_minor") or 0),
        deductions_minor=int(payload.get("deductions_minor") or 0),
        notice_period_days_unserved=int(payload.get("notice_period_days_unserved") or 0),
        apply_gratuity=payload.get("apply_gratuity"),
    )
    settle(conn, int(exit_record_id), breakdown)
    handler._json({"ok": True, "breakdown": breakdown})


ROUTES = {
    "GET": [
        (r"^/m/f_and_f/?$", list_view),
        (r"^/m/f_and_f/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/f_and_f/(\d+)/settle/?$", settle_api),
    ],
    "DELETE": [],
}


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s\t%s",
                 row["id"], row.get("employee") or "",
                 row.get("last_working_day") or "",
                 row.get("f_and_f_amount") or "(not settled)",
                 row.get("settled") or "")
    return 0


CLI = [
    ("fnf-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "finance",
    "requires": ["employee", "exit_record"],
    "description": "Full-and-final settlement: gratuity + leave encashment + notice recovery.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
