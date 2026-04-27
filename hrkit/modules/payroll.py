"""Payroll module — payroll_run + payslip in one module.

Top-level list shows payroll runs by period (YYYY-MM). The detail view of a
run lists all payslips. Generate creates payslip rows for every active
employee (gross = employee.salary_minor); Process flips status to processed.

Money is stored as INTEGER paise; display as ``₹{value/100:.2f}``.
"""
from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
from datetime import datetime
from typing import Any

from ..branding import app_name

log = logging.getLogger(__name__)

NAME = "payroll"
LABEL = "Payroll"
ICON = "wallet"

# Regex used both at the API and CLI boundary to keep the period column safe.
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def ensure_schema(conn: sqlite3.Connection) -> None:
    """No module-private tables — payroll_run + payslip live in 001_*.sql."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _money(paise: int) -> str:
    """Render an integer paise amount as a rupee-prefixed string."""
    try:
        value = int(paise)
    except (TypeError, ValueError):
        value = 0
    return f"₹{value / 100:.2f}"


def _now_ist() -> str:
    """Return current IST ISO-8601 timestamp (matches schema default style)."""
    try:
        from ..config import IST  # type: ignore[attr-defined]
        return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")
    except (ImportError, AttributeError):
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+05:30")


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all payroll runs, newest period first, with payslip counts."""
    rows = conn.execute(
        """
        SELECT pr.id, pr.period, pr.status, pr.processed_at, pr.notes, pr.created,
               (SELECT COUNT(*) FROM payslip ps WHERE ps.payroll_run_id = pr.id)
                   AS employee_count
        FROM payroll_run pr
        ORDER BY pr.period DESC, pr.id DESC
        """
    ).fetchall()
    return [_row_to_dict(r) or {} for r in rows]


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM payroll_run WHERE id = ?", (int(run_id),)
    ).fetchone()
    return _row_to_dict(row)


def list_payslips(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ps.id, ps.payroll_run_id, ps.employee_id, ps.gross_minor,
               ps.deductions_minor, ps.net_minor, ps.components_json,
               ps.generated_at, ps.file_path,
               e.full_name AS employee_name, e.employee_code
        FROM payslip ps
        JOIN employee e ON e.id = ps.employee_id
        WHERE ps.payroll_run_id = ?
        ORDER BY e.full_name COLLATE NOCASE
        """,
        (int(run_id),),
    ).fetchall()
    return [_row_to_dict(r) or {} for r in rows]


def get_payslip(conn: sqlite3.Connection, payslip_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT ps.*, e.full_name AS employee_name, e.employee_code,
               pr.period AS payroll_period, pr.status AS payroll_status
        FROM payslip ps
        JOIN employee e ON e.id = ps.employee_id
        JOIN payroll_run pr ON pr.id = ps.payroll_run_id
        WHERE ps.id = ?
        """,
        (int(payslip_id),),
    ).fetchone()
    return _row_to_dict(row)


def create_run(
    conn: sqlite3.Connection, *, period: str, notes: str = ""
) -> int:
    """Insert a new payroll_run in draft status. Returns the new id."""
    period = (period or "").strip()
    if not _PERIOD_RE.match(period):
        raise ValueError("period must be YYYY-MM")
    cur = conn.execute(
        "INSERT INTO payroll_run(period, status, notes) VALUES (?, 'draft', ?)",
        (period, notes or ""),
    )
    conn.commit()
    return int(cur.lastrowid)


def _fy_start_for_period(conn: sqlite3.Connection, period: str,
                         country: str, regime: str) -> str:
    """Pick the most recent ``tax_slab.fy_start`` <= the run's first day for
    the given country+regime. Falls back to '' (no slab match) if none."""
    if not period:
        return ""
    first_day = f"{period}-01"  # period is YYYY-MM
    row = conn.execute(
        "SELECT fy_start FROM tax_slab "
        "WHERE country = ? AND regime = ? AND fy_start <> '' AND fy_start <= ? "
        "ORDER BY fy_start DESC LIMIT 1",
        (country, regime, first_day),
    ).fetchone()
    return row["fy_start"] if row else ""


def _payroll_tax_settings(conn: sqlite3.Connection) -> tuple[str, str]:
    """Read PAYROLL_TAX_COUNTRY / PAYROLL_TAX_REGIME from the settings table.
    Defaults to IN / new."""
    country = "IN"
    regime = "new"
    try:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE key IN "
            "('PAYROLL_TAX_COUNTRY', 'PAYROLL_TAX_REGIME')"
        ).fetchall()
        for r in rows:
            if r["key"] == "PAYROLL_TAX_COUNTRY" and r["value"]:
                country = str(r["value"]).strip()
            elif r["key"] == "PAYROLL_TAX_REGIME" and r["value"]:
                regime = str(r["value"]).strip()
    except sqlite3.Error:
        pass
    return country, regime


def _open_advances_for(conn: sqlite3.Connection,
                       employee_id: int) -> list[dict[str, Any]]:
    """Return approved/disbursed salary_advance rows for an employee with
    a parseable repayment_schedule that still has remaining balance."""
    rows = conn.execute(
        "SELECT id, amount_minor, status, repayment_schedule "
        "FROM salary_advance "
        "WHERE employee_id = ? AND status IN ('approved', 'disbursed') "
        "ORDER BY id",
        (int(employee_id),),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        raw = r["repayment_schedule"] or "{}"
        try:
            schedule = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(schedule, dict):
            continue
        emi = int(schedule.get("emi_minor") or 0)
        remaining = schedule.get("remaining_minor")
        if remaining is None:
            # First-time deduction — start from full advance amount.
            remaining = int(r["amount_minor"] or 0)
        else:
            remaining = int(remaining)
        if emi <= 0 or remaining <= 0:
            continue
        out.append({
            "id": int(r["id"]),
            "emi_minor": emi,
            "remaining_minor": remaining,
            "schedule": schedule,
        })
    return out


def _apply_advance_repayment(conn: sqlite3.Connection, advance_id: int,
                             schedule: dict[str, Any], deducted_minor: int,
                             new_remaining: int) -> None:
    """Persist the updated repayment_schedule and flip status to 'repaid' if done."""
    schedule = dict(schedule or {})
    schedule["remaining_minor"] = max(0, int(new_remaining))
    schedule["last_deducted_minor"] = int(deducted_minor)
    schedule["last_deducted_at"] = _now_ist()
    if new_remaining <= 0:
        conn.execute(
            "UPDATE salary_advance SET repayment_schedule = ?, status = 'repaid' "
            "WHERE id = ?",
            (json.dumps(schedule), int(advance_id)),
        )
    else:
        conn.execute(
            "UPDATE salary_advance SET repayment_schedule = ? WHERE id = ?",
            (json.dumps(schedule), int(advance_id)),
        )


def _emit_component(conn: sqlite3.Connection, payslip_id: int, *,
                    name: str, type_: str, amount_minor: int,
                    calculation: str = "") -> None:
    """Insert one payroll_component row."""
    conn.execute(
        "INSERT INTO payroll_component (payslip_id, name, type, amount_minor, calculation) "
        "VALUES (?, ?, ?, ?, ?)",
        (int(payslip_id), name, type_, int(amount_minor), calculation or ""),
    )


def generate_payslips(conn: sqlite3.Connection, run_id: int) -> int:
    """Create payslip rows for every active employee.

    Per-employee flow:
      1. Earnings: ``employee.salary_minor`` becomes one ``basic`` component
         (extend by adding more earning components in the future).
      2. Tax: monthly tax = annual_tax / 12, where annual_tax is computed
         via :func:`hrkit.modules.tax_slab.compute_tax_minor` against the
         most recent matching ``fy_start`` for the configured country /
         regime (defaults: IN / new). If no slabs are configured tax is 0.
      3. Salary-advance repayment: any approved / disbursed
         ``salary_advance`` for this employee with a ``repayment_schedule``
         like ``{"emi_minor": N, "remaining_minor": M}`` is deducted
         (clamped to remaining), the schedule is updated, and the advance
         flips to ``repaid`` once remaining hits 0.
      4. ``payslip.deductions_minor`` is the sum of tax + EMI; ``net_minor``
         = gross − deductions; ``components_json`` retains a JSON snapshot
         for legacy callers, and individual ``payroll_component`` rows are
         emitted for queryable per-line breakdown.

    Idempotent: payslips already present (UNIQUE(payroll_run_id,
    employee_id)) are skipped — components and advance deductions are NOT
    re-applied for them. Returns the number of new payslips inserted.
    """
    from . import tax_slab as tax_slab_mod  # local import to avoid cycles

    run = get_run(conn, run_id)
    if run is None:
        raise ValueError(f"payroll_run {run_id} not found")

    period = str(run.get("period") or "")
    country, regime = _payroll_tax_settings(conn)
    fy_start = _fy_start_for_period(conn, period, country, regime)

    employees = conn.execute(
        "SELECT id, salary_minor FROM employee WHERE status = 'active' ORDER BY id"
    ).fetchall()

    inserted = 0
    for emp in employees:
        emp_id = int(emp["id"])
        gross = int(emp["salary_minor"] or 0)

        # Compute monthly tax from annual income.
        if fy_start and gross > 0:
            try:
                annual_tax = tax_slab_mod.compute_tax_minor(
                    conn,
                    annual_income_minor=gross * 12,
                    country=country, regime=regime, fy_start=fy_start,
                )
                monthly_tax = int(round(annual_tax / 12))
            except Exception as exc:  # noqa: BLE001
                log.warning("tax_slab.compute_tax_minor failed for emp=%s: %s",
                            emp_id, exc)
                monthly_tax = 0
        else:
            monthly_tax = 0

        # Find advance EMIs to deduct on this run.
        advances = _open_advances_for(conn, emp_id)
        emi_total = 0
        emi_breakdown: list[dict[str, Any]] = []
        for adv in advances:
            take = min(adv["emi_minor"], adv["remaining_minor"])
            if take <= 0:
                continue
            emi_total += take
            emi_breakdown.append({
                "advance_id": adv["id"],
                "emi_minor": take,
                "remaining_after": adv["remaining_minor"] - take,
                "schedule": adv["schedule"],
            })

        deductions = max(0, monthly_tax) + max(0, emi_total)
        net = max(0, gross - deductions)
        components = {"basic": gross}
        if monthly_tax:
            components["income_tax"] = -monthly_tax
        if emi_total:
            components["advance_repayment"] = -emi_total

        try:
            cur = conn.execute(
                """
                INSERT INTO payslip(
                    payroll_run_id, employee_id, gross_minor,
                    deductions_minor, net_minor, components_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(run_id), emp_id, gross, deductions, net,
                 json.dumps(components, separators=(",", ":"))),
            )
        except sqlite3.IntegrityError:
            # UNIQUE(payroll_run_id, employee_id) — already generated.
            log.debug("payslip exists for run=%s emp=%s", run_id, emp_id)
            continue

        payslip_id = int(cur.lastrowid)
        # Emit one component per line so /api/m/payroll can serve a queryable
        # breakdown (also lets reporting tools group by component name).
        _emit_component(conn, payslip_id,
                        name="basic", type_="earning",
                        amount_minor=gross,
                        calculation="employee.salary_minor")
        if monthly_tax:
            _emit_component(conn, payslip_id,
                            name="income_tax", type_="tax",
                            amount_minor=monthly_tax,
                            calculation=(f"compute_tax_minor(annual={gross*12}, "
                                         f"country={country}, regime={regime}, "
                                         f"fy_start={fy_start})/12"))
        for line in emi_breakdown:
            _emit_component(conn, payslip_id,
                            name=f"advance_repayment_#{line['advance_id']}",
                            type_="deduction",
                            amount_minor=line["emi_minor"],
                            calculation=f"salary_advance #{line['advance_id']} EMI")
            _apply_advance_repayment(
                conn, line["advance_id"], line["schedule"],
                deducted_minor=line["emi_minor"],
                new_remaining=line["remaining_after"])

        inserted += 1
    conn.commit()
    return inserted


def process_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    """Flip payroll_run.status from draft to processed."""
    run = get_run(conn, run_id)
    if run is None:
        raise ValueError(f"payroll_run {run_id} not found")
    if run["status"] not in ("draft", "processed"):
        raise ValueError(f"cannot process run in status {run['status']!r}")
    conn.execute(
        "UPDATE payroll_run SET status = 'processed', processed_at = ? WHERE id = ?",
        (_now_ist(), int(run_id)),
    )
    conn.commit()
    return get_run(conn, run_id) or {}


def delete_run(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("DELETE FROM payroll_run WHERE id = ?", (int(run_id),))
    conn.commit()


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _render_runs_table(runs: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for r in runs:
        rows.append(
            "<tr>"
            f"<td><a href=\"/m/payroll/{int(r['id'])}\">{html.escape(r['period'])}</a></td>"
            f"<td>{html.escape(r.get('status') or 'draft')}</td>"
            f"<td>{html.escape(r.get('processed_at') or '')}</td>"
            f"<td>{int(r.get('employee_count') or 0)}</td>"
            f"<td>{html.escape(r.get('notes') or '')}</td>"
            "</tr>"
        )
    body = "".join(rows) or "<tr><td colspan=\"5\">No payroll runs yet.</td></tr>"
    return (
        "<div class=\"module-toolbar\">"
        f"<h1>{html.escape(LABEL)}</h1>"
        "<button onclick=\"openCreateForm()\">+ Add payroll run</button>"
        "<input type=\"search\" placeholder=\"Search...\" "
        "oninput=\"filter(this.value)\">"
        "</div>"
        "<table class=\"data-table\">"
        "<thead><tr>"
        "<th>Period</th><th>Status</th><th>Processed at</th>"
        "<th>Employees</th><th>Notes</th>"
        "</tr></thead>"
        f"<tbody id=\"rows\">{body}</tbody>"
        "</table>"
        "<dialog id=\"create-dlg\">"
        "<form onsubmit=\"submitCreate(event)\">"
        "<label>Period <input type=\"month\" name=\"period\" required></label>"
        "<label>Notes <textarea name=\"notes\"></textarea></label>"
        "<button type=\"submit\">Save</button>"
        "</form>"
        "</dialog>"
        "<script>"
        "function openCreateForm(){document.getElementById('create-dlg').showModal();}"
        "function filter(q){q=(q||'').toLowerCase();"
        "document.querySelectorAll('#rows tr').forEach(function(tr){"
        "tr.style.display=tr.textContent.toLowerCase().indexOf(q)>-1?'':'none';});}"
        "async function submitCreate(e){e.preventDefault();"
        "var f=new FormData(e.target);"
        "var body={period:f.get('period'),notes:f.get('notes')||''};"
        "var r=await fetch('/api/m/payroll',{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});"
        "if(r.ok){location.reload();}else{alert('Save failed');}}"
        "</script>"
    )


def _render_run_detail(run: dict[str, Any], slips: list[dict[str, Any]]) -> str:
    rid = int(run["id"])
    slip_rows: list[str] = []
    total_net = 0
    for s in slips:
        net = int(s.get("net_minor") or 0)
        total_net += net
        slip_rows.append(
            "<tr>"
            f"<td><a href=\"/m/payroll/payslip/{int(s['id'])}\">"
            f"{html.escape(s.get('employee_name') or '')}</a></td>"
            f"<td>{html.escape(s.get('employee_code') or '')}</td>"
            f"<td>{_money(s.get('gross_minor') or 0)}</td>"
            f"<td>{_money(s.get('deductions_minor') or 0)}</td>"
            f"<td>{_money(net)}</td>"
            f"<td>{html.escape(s.get('generated_at') or '')}</td>"
            "</tr>"
        )
    if not slip_rows:
        slip_rows.append("<tr><td colspan=\"6\">No payslips yet — click Generate.</td></tr>")

    status = html.escape(run.get("status") or "draft")
    processed_at = html.escape(run.get("processed_at") or "")
    notes = html.escape(run.get("notes") or "")

    return (
        "<div class=\"module-toolbar\">"
        f"<h1>{html.escape(LABEL)} · {html.escape(run['period'])}</h1>"
        f"<button onclick=\"genSlips({rid})\">Generate payslips</button>"
        f"<button onclick=\"processRun({rid})\">Process run</button>"
        "<a href=\"/m/payroll\">Back</a>"
        "</div>"
        f"<p>Status: <strong>{status}</strong> &middot; Processed at: {processed_at}</p>"
        f"<p>Notes: {notes}</p>"
        "<table class=\"data-table\">"
        "<thead><tr>"
        "<th>Employee</th><th>Code</th><th>Gross</th><th>Deductions</th>"
        "<th>Net</th><th>Generated at</th>"
        "</tr></thead>"
        f"<tbody id=\"rows\">{''.join(slip_rows)}</tbody>"
        f"<tfoot><tr><td colspan=\"4\">Total net</td>"
        f"<td>{_money(total_net)}</td><td></td></tr></tfoot>"
        "</table>"
        "<script>"
        "async function genSlips(id){"
        "var r=await fetch('/api/m/payroll/'+id+'/generate',{method:'POST'});"
        "if(r.ok){location.reload();}else{alert('Generate failed');}}"
        "async function processRun(id){"
        "var r=await fetch('/api/m/payroll/'+id+'/process',{method:'POST'});"
        "if(r.ok){location.reload();}else{alert('Process failed');}}"
        "</script>"
    )


def _render_payslip_detail(slip: dict[str, Any]) -> str:
    try:
        components = json.loads(slip.get("components_json") or "{}")
    except (TypeError, ValueError):
        components = {}
    pretty = json.dumps(components, indent=2, sort_keys=True)
    return (
        "<div class=\"module-toolbar\">"
        f"<h1>Payslip · {html.escape(slip.get('employee_name') or '')}</h1>"
        f"<a href=\"/m/payroll/{int(slip['payroll_run_id'])}\">Back to run</a>"
        "</div>"
        "<table class=\"data-table\">"
        "<tbody>"
        f"<tr><th>Employee</th><td>{html.escape(slip.get('employee_name') or '')} "
        f"({html.escape(slip.get('employee_code') or '')})</td></tr>"
        f"<tr><th>Period</th><td>{html.escape(slip.get('payroll_period') or '')}</td></tr>"
        f"<tr><th>Run status</th><td>{html.escape(slip.get('payroll_status') or '')}</td></tr>"
        f"<tr><th>Gross</th><td>{_money(slip.get('gross_minor') or 0)}</td></tr>"
        f"<tr><th>Deductions</th><td>{_money(slip.get('deductions_minor') or 0)}</td></tr>"
        f"<tr><th>Net</th><td>{_money(slip.get('net_minor') or 0)}</td></tr>"
        f"<tr><th>Generated at</th><td>{html.escape(slip.get('generated_at') or '')}</td></tr>"
        "</tbody>"
        "</table>"
        f"<h2>Components</h2><pre>{html.escape(pretty)}</pre>"
    )


def _render_page(title: str, body: str) -> str:
    try:
        from ..templates import render_module_page  # type: ignore[attr-defined]
        return render_module_page(title=title, nav_active=NAME, body_html=body)
    except (ImportError, AttributeError):
        # Wave 1 fallback — Wave 2 integrator wires the real template.
        brand = html.escape(app_name())
        return (
            "<!doctype html><html><head>"
            f"<title>{html.escape(title)} · {brand}</title>"
            "</head><body>"
            f"<header><strong>{brand}</strong></header>"
            f"<main>{body}</main>"
            "</body></html>"
        )


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

def _conn(handler) -> sqlite3.Connection:
    # The Wave 2 integrator attaches the connection to the handler.
    # Look it up dynamically to avoid coupling to server.py here.
    for attr in ("conn", "_conn", "db"):
        c = getattr(handler, attr, None)
        if c is not None:
            return c
    raise RuntimeError("handler has no SQLite connection attribute")


def list_view(handler) -> None:
    conn = _conn(handler)
    runs = list_runs(conn)
    body = _render_runs_table(runs)
    handler._html(200, _render_page(f"{LABEL} · {app_name()}", body))


def _fmt_dt(value: Any) -> str:
    """Trim fractional seconds from a datetime-ish string for display."""
    if value in (None, ""):
        return ""
    text = str(value)
    if "." not in text:
        return text
    head, tail = text.split(".", 1)
    i = 0
    while i < len(tail) and tail[i].isdigit():
        i += 1
    return head + tail[i:]


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section

    conn = _conn(handler)
    run = get_run(conn, int(item_id))
    if run is None:
        handler._html(404, render_detail_page(
            title="Not found",
            nav_active=NAME,
            subtitle=f"No payroll run with id {int(item_id)}",
        ))
        return
    slips = list_payslips(conn, int(item_id))

    fields: list[tuple[str, Any]] = [
        ("Period", run.get("period")),
        ("Status", run.get("status") or "draft"),
        ("Processed at", _fmt_dt(run.get("processed_at"))),
        ("Processed by", run.get("processed_by")),
        ("Notes", run.get("notes")),
        ("Created", _fmt_dt(run.get("created"))),
        ("Payslips", len(slips)),
    ]

    if slips:
        slip_rows = []
        total_net = 0
        for s in slips:
            net = int(s.get("net_minor") or 0)
            total_net += net
            slip_rows.append(
                "<tr>"
                f"<td><a href=\"/m/payroll/payslip/{int(s['id'])}\">"
                f"{html.escape(s.get('employee_name') or '')}</a></td>"
                f"<td>{html.escape(s.get('employee_code') or '')}</td>"
                f"<td>{_money(s.get('gross_minor') or 0)}</td>"
                f"<td>{_money(s.get('deductions_minor') or 0)}</td>"
                f"<td>{_money(net)}</td>"
                f"<td>{html.escape(_fmt_dt(s.get('generated_at')))}</td>"
                "</tr>"
            )
        slip_body = (
            "<table><thead><tr>"
            "<th>Employee</th><th>Code</th><th>Gross</th>"
            "<th>Deductions</th><th>Net</th><th>Generated at</th>"
            "</tr></thead><tbody>"
            + "".join(slip_rows)
            + f"</tbody><tfoot><tr><td colspan=\"4\">Total net</td>"
            f"<td>{_money(total_net)}</td><td></td></tr></tfoot></table>"
        )
    else:
        slip_body = (
            '<div class="empty">No payslips yet — click Generate.</div>'
        )

    related_html = detail_section(title="Payslips", body_html=slip_body)
    rid = int(item_id)
    actions_html = (
        f"<button onclick=\"fetch('/api/m/payroll/{rid}/generate',"
        f"{{method:'POST'}}).then(r=>r.ok?location.reload():alert('Generate failed'))\""
        f">Generate payslips</button>"
        f"<button onclick=\"fetch('/api/m/payroll/{rid}/process',"
        f"{{method:'POST'}}).then(r=>r.ok?location.reload():alert('Process failed'))\""
        f">Process run</button>"
    )

    page = render_detail_page(
        title=f"{LABEL} · {run.get('period') or ''}",
        nav_active=NAME,
        subtitle=f"Status: {run.get('status') or 'draft'}",
        fields=fields,
        actions_html=actions_html,
        related_html=related_html,
        item_id=rid,
        api_path="/api/m/payroll",
        delete_redirect="/m/payroll",
    )
    handler._html(200, page)


def payslip_view(handler, payslip_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section

    conn = _conn(handler)
    slip = get_payslip(conn, int(payslip_id))
    if slip is None:
        handler._html(404, render_detail_page(
            title="Not found",
            nav_active=NAME,
            subtitle=f"No payslip with id {int(payslip_id)}",
        ))
        return

    try:
        components = json.loads(slip.get("components_json") or "{}")
    except (TypeError, ValueError):
        components = {}
    pretty = json.dumps(components, indent=2, sort_keys=True)

    fields: list[tuple[str, Any]] = [
        ("Employee",
         f"{slip.get('employee_name') or ''} "
         f"({slip.get('employee_code') or ''})"),
        ("Period", slip.get("payroll_period")),
        ("Run status", slip.get("payroll_status")),
        ("Gross", _money(slip.get("gross_minor") or 0)),
        ("Deductions", _money(slip.get("deductions_minor") or 0)),
        ("Net", _money(slip.get("net_minor") or 0)),
        ("Generated at", _fmt_dt(slip.get("generated_at"))),
        ("File path", slip.get("file_path")),
    ]

    components_body = f"<pre>{html.escape(pretty)}</pre>"
    related_html = detail_section(title="Components", body_html=components_body)

    actions_html = (
        f"<a href=\"/m/payroll/{int(slip['payroll_run_id'])}\" class=\"link-back\""
        f" style=\"text-decoration:none\">Back to run</a>"
    )

    page = render_detail_page(
        title=f"Payslip · {slip.get('employee_name') or ''}",
        nav_active=NAME,
        subtitle=f"Period {slip.get('payroll_period') or ''}",
        fields=fields,
        actions_html=actions_html,
        related_html=related_html,
    )
    handler._html(200, page)


def detail_api_json(handler, item_id: int) -> None:
    """Return raw payroll_run + payslips dict as JSON."""
    conn = _conn(handler)
    run = get_run(conn, int(item_id))
    if run is None:
        handler._json({"error": "not found"}, code=404)
        return
    run["payslips"] = list_payslips(conn, int(item_id))
    handler._json(run)


def payslip_api_json(handler, payslip_id: int) -> None:
    slip = get_payslip(_conn(handler), int(payslip_id))
    if slip is None:
        handler._json({"error": "not found"}, code=404)
        return
    handler._json(slip)


def create_api(handler) -> None:
    conn = _conn(handler)
    payload = handler._read_json() or {}
    period = str(payload.get("period") or "").strip()
    notes = str(payload.get("notes") or "")
    try:
        run_id = create_run(conn, period=period, notes=notes)
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    except sqlite3.IntegrityError as exc:
        handler._json({"error": f"duplicate period: {exc}"}, code=409)
        return
    handler._json({"id": run_id, "period": period, "status": "draft"}, code=201)


def update_api(handler, item_id: int) -> None:
    conn = _conn(handler)
    payload = handler._read_json() or {}
    fields: list[str] = []
    values: list[Any] = []
    for col in ("status", "notes"):
        if col in payload:
            fields.append(f"{col} = ?")
            values.append(str(payload[col]))
    if not fields:
        handler._json({"error": "no updatable fields"}, code=400)
        return
    values.append(int(item_id))
    conn.execute(f"UPDATE payroll_run SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    handler._json({"id": int(item_id), "updated": True})


def delete_api(handler, item_id: int) -> None:
    conn = _conn(handler)
    delete_run(conn, int(item_id))
    handler._json({"id": int(item_id), "deleted": True})


def generate_api(handler, item_id: int) -> None:
    conn = _conn(handler)
    try:
        count = generate_payslips(conn, int(item_id))
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=404)
        return
    response = {"id": int(item_id), "inserted": count}
    if count > 0:
        try:
            from hrkit.integrations import hooks
            response["integrations"] = hooks.emit("payroll.payslip_generated", {
                "payroll_run_id": int(item_id),
                "payslip_count": count,
            }, conn=conn)
        except Exception:
            pass
    handler._json(response)


def process_api(handler, item_id: int) -> None:
    conn = _conn(handler)
    try:
        run = process_run(conn, int(item_id))
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"id": int(item_id), "status": run.get("status")})


ROUTES = {
    "GET": [
        (r"^/api/m/payroll/payslip/(\d+)/?$", payslip_api_json),
        (r"^/api/m/payroll/(\d+)/?$", detail_api_json),
        (r"^/m/payroll/?$", list_view),
        (r"^/m/payroll/payslip/(\d+)/?$", payslip_view),
        (r"^/m/payroll/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/payroll/?$", create_api),
        (r"^/api/m/payroll/(\d+)/generate/?$", generate_api),
        (r"^/api/m/payroll/(\d+)/process/?$", process_api),
        (r"^/api/m/payroll/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/payroll/(\d+)/?$", delete_api),
    ],
}


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------

def _add_run_create_args(p) -> None:
    p.add_argument("--period", required=True, help="YYYY-MM")
    p.add_argument("--notes", default="")


def _handle_run_create(args, conn) -> int:
    try:
        run_id = create_run(conn, period=args.period, notes=args.notes)
    except ValueError as exc:
        log.error("payroll-run-add: %s", exc)
        return 2
    log.info("payroll_run created id=%s period=%s", run_id, args.period)
    return 0


def _add_run_generate_args(p) -> None:
    p.add_argument("--run-id", type=int, required=True)


def _handle_run_generate(args, conn) -> int:
    try:
        count = generate_payslips(conn, args.run_id)
    except ValueError as exc:
        log.error("payroll-generate: %s", exc)
        return 2
    log.info("inserted=%s payslips for run=%s", count, args.run_id)
    return 0


def _add_run_process_args(p) -> None:
    p.add_argument("--run-id", type=int, required=True)


def _handle_run_process(args, conn) -> int:
    try:
        run = process_run(conn, args.run_id)
    except ValueError as exc:
        log.error("payroll-process: %s", exc)
        return 2
    log.info("payroll_run id=%s now status=%s", args.run_id, run.get("status"))
    return 0


def _handle_run_list(args, conn) -> int:
    for r in list_runs(conn):
        log.info(
            "%s\t%s\t%s\t%s",
            r.get("period"), r.get("status"),
            r.get("employee_count"), r.get("processed_at") or "-",
        )
    return 0


CLI = [
    ("payroll-run-add", _add_run_create_args, _handle_run_create),
    ("payroll-generate", _add_run_generate_args, _handle_run_generate),
    ("payroll-process", _add_run_process_args, _handle_run_process),
    ("payroll-list", lambda p: None, _handle_run_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "hr",
    "requires": ["employee"],
    "description": "Periodic payroll runs and per-employee payslips with PDF export.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
