"""Exit record HR module.

Owns CRUD over the ``exit_record`` table created by migration
``001_full_hr_schema.sql``. Follows the registry contract from
AGENTS_SPEC.md Section 1 - a single top-level ``MODULE`` dict, no
top-level side effects, stdlib only.

Schema notes
------------
``exit_record.employee_id`` is ``UNIQUE`` so each employee has at most one
exit record. Creating an exit record also flips ``employee.status`` to
``'exited'`` in the same transaction so the two pieces of state never drift.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any

from hrkit.config import IST

log = logging.getLogger(__name__)

NAME = "exit_record"
LABEL = "Exit Records"
ICON = "logout"

LIST_COLUMNS = ("employee", "last_working_day", "exit_type", "processed_at")

ALLOWED_EXIT_TYPES = ("resignation", "termination", "retirement")
ALLOWED_KT_STATUS = ("pending", "in_progress", "done")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def ensure_schema(conn: sqlite3.Connection) -> None:
    """No-op. The ``exit_record`` table is created by migration 001."""
    pass


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _now_ist_iso() -> str:
    return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S%z")


def _coerce_bool(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return 1 if int(value) != 0 else 0
    text = str(value).strip().lower()
    return 1 if text in ("1", "true", "yes", "on") else 0


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT x.id, x.employee_id, x.last_working_day, x.reason, x.exit_type,
               x.notice_period_days, x.knowledge_transfer_status,
               x.asset_returned, x.exit_interview_done, x.processed_at,
               x.created,
               e.full_name AS employee
        FROM exit_record x
        LEFT JOIN employee e ON e.id = x.employee_id
        ORDER BY x.last_working_day DESC, x.id DESC
        """
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute(
        """
        SELECT x.*, e.full_name AS employee
        FROM exit_record x
        LEFT JOIN employee e ON e.id = x.employee_id
        WHERE x.id = ?
        """,
        (item_id,),
    )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    """Insert an exit_record row AND flip ``employee.status = 'exited'``.

    Both writes happen in a single transaction so a failure leaves the
    DB consistent. Surfaces a friendly error when the unique constraint
    on ``employee_id`` fires (one exit record per employee).
    """
    employee_id = data.get("employee_id")
    if employee_id in (None, ""):
        raise ValueError("employee_id is required")
    employee_id = int(employee_id)

    exit_type = (data.get("exit_type") or "").strip()
    if exit_type and exit_type not in ALLOWED_EXIT_TYPES:
        raise ValueError(f"exit_type must be one of {ALLOWED_EXIT_TYPES}")

    kt_status = (data.get("knowledge_transfer_status") or "pending").strip()
    if kt_status and kt_status not in ALLOWED_KT_STATUS:
        raise ValueError(
            f"knowledge_transfer_status must be one of {ALLOWED_KT_STATUS}"
        )

    notice_period = data.get("notice_period_days") or 0
    try:
        notice_period = int(notice_period)
    except (TypeError, ValueError) as exc:
        raise ValueError("notice_period_days must be an integer") from exc

    # Verify employee exists and is active.
    cur = conn.execute(
        "SELECT id, status FROM employee WHERE id = ?", (employee_id,)
    )
    emp = cur.fetchone()
    if emp is None:
        raise ValueError(f"employee {employee_id} does not exist")
    if emp["status"] != "active":
        raise ValueError(
            f"employee {employee_id} is not active (status={emp['status']})"
        )

    processed_at = data.get("processed_at") or _now_ist_iso()

    in_tx = conn.in_transaction
    try:
        if not in_tx:
            conn.execute("BEGIN")
        try:
            ins = conn.execute(
                """
                INSERT INTO exit_record (
                    employee_id, last_working_day, reason, exit_type,
                    notice_period_days, knowledge_transfer_status,
                    asset_returned, exit_interview_done, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    data.get("last_working_day") or "",
                    data.get("reason") or "",
                    exit_type,
                    notice_period,
                    kt_status,
                    _coerce_bool(data.get("asset_returned")),
                    _coerce_bool(data.get("exit_interview_done")),
                    processed_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            # The UNIQUE(employee_id) constraint is the most likely culprit.
            msg = str(exc).lower()
            if "unique" in msg and "employee_id" in msg:
                raise ValueError(
                    f"employee {employee_id} already has an exit record"
                ) from exc
            raise
        conn.execute(
            "UPDATE employee SET status = 'exited' WHERE id = ?",
            (employee_id,),
        )
        if not in_tx:
            conn.commit()
    except Exception:
        if not in_tx:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        raise

    new_id = int(ins.lastrowid)
    # Auto-compute the F&F breakdown when the exit is processed at create-time.
    # Skipped silently if data is incomplete (e.g. no hire_date or salary).
    if processed_at:
        _auto_settle_fnf(conn, new_id, employee_id,
                         last_working_day=data.get("last_working_day") or "",
                         notice_period_days=notice_period,
                         override_bonuses_minor=int(data.get("bonuses_minor") or 0),
                         override_deductions_minor=int(data.get("deductions_minor") or 0))
    return new_id


def _auto_settle_fnf(conn: sqlite3.Connection, exit_record_id: int,
                     employee_id: int, *,
                     last_working_day: str,
                     notice_period_days: int = 0,
                     override_bonuses_minor: int = 0,
                     override_deductions_minor: int = 0) -> dict[str, Any] | None:
    """Best-effort F&F auto-compute. Never raises; returns the breakdown
    on success, ``None`` if anything was missing. Caller is the create_row
    happy path — failures must not break the exit insert."""
    try:
        from . import f_and_f
        emp = conn.execute(
            "SELECT salary_minor, hire_date FROM employee WHERE id = ?",
            (int(employee_id),)
        ).fetchone()
        if not emp:
            return None
        hire_date = (emp["hire_date"] or "").strip()
        salary_minor = int(emp["salary_minor"] or 0)
        if not hire_date or not last_working_day or salary_minor <= 0:
            log.debug("F&F auto-settle skipped for exit=%s: missing data", exit_record_id)
            return None
        years = f_and_f._years_between(hire_date, last_working_day)
        # Sum unused leave days across leave_balance rows for the year of exit.
        try:
            year = int((last_working_day or "")[:4])
        except (TypeError, ValueError):
            year = 0
        unused_leave_days = 0
        if year:
            row = conn.execute(
                "SELECT COALESCE(SUM(MAX(allotted - used - pending, 0)), 0) AS d "
                "FROM leave_balance WHERE employee_id = ? AND year = ?",
                (int(employee_id), year)
            ).fetchone()
            if row and row["d"] is not None:
                unused_leave_days = max(0, int(row["d"]))
        breakdown = f_and_f.calculate_fnf(
            monthly_salary_minor=salary_minor,
            years_of_service=years,
            unused_leave_days=unused_leave_days,
            bonuses_minor=int(override_bonuses_minor or 0),
            deductions_minor=int(override_deductions_minor or 0),
            notice_period_days_unserved=0,
        )
        f_and_f.settle(conn, int(exit_record_id), breakdown)
        return breakdown
    except Exception as exc:  # noqa: BLE001 - sidecar must not break exit creation
        log.warning("F&F auto-settle failed for exit_record %s: %s",
                    exit_record_id, exc)
        return None


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields: list[str] = []
    values: list[Any] = []
    simple = (
        "last_working_day", "reason", "exit_type", "notice_period_days",
        "knowledge_transfer_status", "processed_at",
    )
    for key in simple:
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    for bool_key in ("asset_returned", "exit_interview_done"):
        if bool_key in data:
            fields.append(f"{bool_key} = ?")
            values.append(_coerce_bool(data[bool_key]))
    if not fields:
        return
    values.append(item_id)
    conn.execute(
        f"UPDATE exit_record SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM exit_record WHERE id = ?", (item_id,))
    conn.commit()


def _list_active_employees(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, full_name AS label FROM employee "
        "WHERE status = 'active' ORDER BY full_name"
    )
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
                      employees: list[dict[str, Any]]) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}">{cells}'
            f'<td><button onclick="deleteRow({row["id"]})">Delete</button></td></tr>'
        )

    emp_opts = "".join(
        f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees
    )
    exit_opts = "".join(
        f'<option value="{t}">{t}</option>' for t in ALLOWED_EXIT_TYPES
    )
    kt_opts = "".join(
        f'<option value="{s}"{" selected" if s == "pending" else ""}>{s}</option>'
        for s in ALLOWED_KT_STATUS
    )

    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Exit Record</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Employee*<select name="employee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Last working day<input name="last_working_day" type="date"></label>
    <label>Reason<textarea name="reason" rows="2"></textarea></label>
    <label>Exit type<select name="exit_type"><option value="">--</option>{exit_opts}</select></label>
    <label>Notice period (days)<input name="notice_period_days" type="number" min="0" value="0"></label>
    <label>Knowledge transfer<select name="knowledge_transfer_status">{kt_opts}</select></label>
    <label><input name="asset_returned" type="checkbox" value="1"> Asset returned</label>
    <label><input name="exit_interview_done" type="checkbox" value="1"> Exit interview done</label>
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
  payload.asset_returned = ev.target.asset_returned.checked ? 1 : 0;
  payload.exit_interview_done = ev.target.exit_interview_done.checked ? 1 : 0;
  if (payload.exit_type === '') delete payload.exit_type;
  const r = await fetch('/api/m/exit_record', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete exit record #' + id + '?')) return;
  const r = await fetch('/api/m/exit_record/' + id, {{method: 'DELETE'}});
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
    employees = _list_active_employees(conn)
    body = _render_list_html(rows, employees)
    handler._html(200, render_module_page(title=LABEL, nav_active=NAME, body_html=body))


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


def _yesno(value: Any) -> str:
    try:
        return "Yes" if int(value or 0) else "No"
    except (TypeError, ValueError):
        return "No"


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page

    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(
            title="Not found",
            nav_active=NAME,
            subtitle=f"No exit record with id {int(item_id)}",
        ))
        return

    fields: list[tuple[str, Any]] = [
        ("Employee", row.get("employee") or row.get("employee_id")),
        ("Last working day", row.get("last_working_day")),
        ("Reason", row.get("reason")),
        ("Exit type", row.get("exit_type")),
        ("Notice period (days)", row.get("notice_period_days")),
        ("Knowledge transfer", row.get("knowledge_transfer_status")),
        ("Asset returned", _yesno(row.get("asset_returned"))),
        ("Exit interview done", _yesno(row.get("exit_interview_done"))),
        ("Processed at", _fmt_dt(row.get("processed_at"))),
        ("Created", _fmt_dt(row.get("created"))),
    ]

    rid = int(item_id)
    page = render_detail_page(
        title=f"Exit · {row.get('employee') or ''}",
        nav_active=NAME,
        subtitle=f"Last working day: {row.get('last_working_day') or '—'}",
        fields=fields,
        item_id=rid,
        api_path="/api/m/exit_record",
        delete_redirect="/m/exit_record",
    )
    handler._html(200, page)


def detail_api_json(handler, item_id: int) -> None:
    """Return raw exit_record row as JSON."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._json({"error": "not_found"}, code=404)
        return
    handler._json(row)


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


ROUTES = {
    "GET": [
        (r"^/api/m/exit_record/(\d+)/?$", detail_api_json),
        (r"^/m/exit_record/?$", list_view),
        (r"^/m/exit_record/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/exit_record/?$", create_api),
        (r"^/api/m/exit_record/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/exit_record/(\d+)/?$", delete_api),
    ],
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_create_args(parser) -> None:
    parser.add_argument("--employee-id", type=int, required=True)
    parser.add_argument("--last-working-day")
    parser.add_argument("--reason", default="")
    parser.add_argument("--exit-type", choices=list(ALLOWED_EXIT_TYPES))
    parser.add_argument("--notice-period-days", type=int, default=0)
    parser.add_argument(
        "--knowledge-transfer-status",
        choices=list(ALLOWED_KT_STATUS),
        default="pending",
    )
    parser.add_argument("--asset-returned", action="store_true")
    parser.add_argument("--exit-interview-done", action="store_true")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "employee_id": args.employee_id,
        "last_working_day": getattr(args, "last_working_day", None),
        "reason": getattr(args, "reason", ""),
        "exit_type": getattr(args, "exit_type", None),
        "notice_period_days": getattr(args, "notice_period_days", 0),
        "knowledge_transfer_status":
            getattr(args, "knowledge_transfer_status", "pending"),
        "asset_returned": getattr(args, "asset_returned", False),
        "exit_interview_done": getattr(args, "exit_interview_done", False),
    })
    log.info("exit_record_added id=%s employee_id=%s", new_id, args.employee_id)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info(
            "%s\t%s\t%s\t%s\t%s",
            row["id"], row.get("employee"), row.get("last_working_day"),
            row.get("exit_type"), row.get("processed_at"),
        )
    return 0


CLI = [
    ("exit-record-add", _add_create_args, _handle_create),
    ("exit-record-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "hr",
    "requires": ["employee"],
    "description": "Exit records, knowledge transfer, asset return, exit interview.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
