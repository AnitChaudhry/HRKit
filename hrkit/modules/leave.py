"""Leave module — covers leave_type, leave_balance and leave_request.

This single module file owns three related tables. The HTML list view uses
tab navigation ("Requests" | "Types" | "Balances") so the user can switch
between the three concerns without leaving the page. JSON CRUD endpoints
are namespaced by the sub-resource:

    GET  /m/leave/?tab=requests|types|balances
    POST /api/m/leave/                        -> create leave_request
    POST /api/m/leave/<id>                    -> update leave_request
    POST /api/m/leave/<id>/approve            -> approve leave_request
    POST /api/m/leave/<id>/reject             -> reject leave_request
    DELETE /api/m/leave/<id>                  -> delete leave_request
    POST /api/m/leave/types/                  -> create leave_type
    DELETE /api/m/leave/types/<id>            -> delete leave_type

The tables themselves are created by the central migration runner in
``001_full_hr_schema.sql``. ``ensure_schema`` is intentionally a no-op.
"""
from __future__ import annotations

import html as htmllib
import json
import logging
import sqlite3
from datetime import date, datetime
from typing import Any

log = logging.getLogger(__name__)

NAME = "leave"
LABEL = "Leave"
ICON = "calendar"


# ---- DB --------------------------------------------------------------------

def ensure_schema(conn: sqlite3.Connection) -> None:
    """No-op — leave_type, leave_balance and leave_request live in the
    central migration ``001_full_hr_schema.sql``."""
    pass


# ---- Helpers ---------------------------------------------------------------

_VALID_STATUS = ("pending", "approved", "rejected", "cancelled")


def _now_ist() -> str:
    """Return an ISO-8601 IST timestamp matching the SQL default format."""
    row = sqlite3.connect(":memory:").execute(
        "SELECT strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')"
    ).fetchone()
    return row[0] if row else datetime.utcnow().isoformat(timespec="seconds")


def _calc_days(start_date: str, end_date: str) -> int:
    """Inclusive day count between two YYYY-MM-DD strings.

    Returns 0 if either input is missing/invalid or end < start.
    """
    if not start_date or not end_date:
        return 0
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
    except ValueError:
        return 0
    if e < s:
        return 0
    return (e - s).days + 1


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


# ---- Direct DB API (used by tests + future API reuse) ---------------------

def create_leave_type(conn: sqlite3.Connection, *, name: str, code: str = "",
                      max_days_per_year: int = 0, carry_forward: int = 0,
                      paid: int = 1) -> int:
    """Insert a leave_type row, returning its new id."""
    cur = conn.execute(
        "INSERT INTO leave_type (name, code, max_days_per_year, carry_forward, paid) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, code, int(max_days_per_year), int(carry_forward), int(paid)),
    )
    conn.commit()
    return int(cur.lastrowid)


def create_leave_request(conn: sqlite3.Connection, *, employee_id: int,
                         leave_type_id: int, start_date: str, end_date: str,
                         reason: str = "") -> int:
    """Insert a leave_request with status='pending' and auto-calculated days."""
    days = _calc_days(start_date, end_date)
    cur = conn.execute(
        "INSERT INTO leave_request "
        "(employee_id, leave_type_id, start_date, end_date, days, reason, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        (int(employee_id), int(leave_type_id), start_date, end_date, days, reason),
    )
    conn.commit()
    return int(cur.lastrowid)


def set_status(conn: sqlite3.Connection, request_id: int, *, status: str,
               approver_id: int | None = None) -> bool:
    """Transition a leave_request to a new status. Returns True on success."""
    if status not in _VALID_STATUS:
        return False
    conn.execute(
        "UPDATE leave_request SET status = ?, approver_id = ?, "
        "decided_at = ?, updated = ? WHERE id = ?",
        (status, approver_id, _now_ist(), _now_ist(), int(request_id)),
    )
    conn.commit()
    return True


def list_requests(conn: sqlite3.Connection, *, status: str | None = None,
                  employee_id: int | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT lr.id, lr.employee_id, lr.leave_type_id, lr.start_date, "
        "       lr.end_date, lr.days, lr.reason, lr.status, lr.approver_id, "
        "       lr.applied_at, lr.decided_at, "
        "       e.full_name AS employee_name, lt.name AS leave_type_name "
        "FROM leave_request lr "
        "LEFT JOIN employee   e  ON e.id  = lr.employee_id "
        "LEFT JOIN leave_type lt ON lt.id = lr.leave_type_id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if status:
        sql += " AND lr.status = ?"
        params.append(status)
    if employee_id is not None:
        sql += " AND lr.employee_id = ?"
        params.append(int(employee_id))
    sql += " ORDER BY lr.applied_at DESC, lr.id DESC"
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def list_types(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, name, code, max_days_per_year, carry_forward, paid, created "
        "FROM leave_type ORDER BY name ASC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_balances(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT lb.id, lb.employee_id, lb.leave_type_id, lb.year, "
        "       lb.allotted, lb.used, lb.pending, "
        "       e.full_name AS employee_name, lt.name AS leave_type_name "
        "FROM leave_balance lb "
        "LEFT JOIN employee   e  ON e.id  = lb.employee_id "
        "LEFT JOIN leave_type lt ON lt.id = lb.leave_type_id "
        "ORDER BY e.full_name ASC, lt.name ASC, lb.year DESC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_request(conn: sqlite3.Connection, request_id: int) -> bool:
    cur = conn.execute("DELETE FROM leave_request WHERE id = ?", (int(request_id),))
    conn.commit()
    return cur.rowcount > 0


def delete_type(conn: sqlite3.Connection, type_id: int) -> bool:
    cur = conn.execute("DELETE FROM leave_type WHERE id = ?", (int(type_id),))
    conn.commit()
    return cur.rowcount > 0


# ---- HTML rendering --------------------------------------------------------

def _esc(value: Any) -> str:
    return htmllib.escape("" if value is None else str(value), quote=True)


def _render_requests_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for r in rows:
        body.append(
            "<tr data-id='{id}'>"
            "<td>{emp}</td><td>{lt}</td>"
            "<td>{sd} &rarr; {ed}</td><td>{days}</td>"
            "<td><span class='badge badge-{status}'>{status}</span></td>"
            "<td>{reason}</td>"
            "<td>"
            "  <button onclick='approveRequest({id})'>Approve</button>"
            "  <button onclick='rejectRequest({id})'>Reject</button>"
            "  <button onclick='deleteRequest({id})'>Delete</button>"
            "</td>"
            "</tr>".format(
                id=int(r["id"]),
                emp=_esc(r.get("employee_name") or r.get("employee_id")),
                lt=_esc(r.get("leave_type_name") or r.get("leave_type_id")),
                sd=_esc(r.get("start_date")),
                ed=_esc(r.get("end_date")),
                days=_esc(r.get("days")),
                status=_esc(r.get("status")),
                reason=_esc(r.get("reason")),
            )
        )
    return (
        "<table class='data-table'>"
        "<thead><tr>"
        "<th>Employee</th><th>Type</th><th>Dates</th><th>Days</th>"
        "<th>Status</th><th>Reason</th><th>Actions</th>"
        "</tr></thead>"
        "<tbody id='rows'>" + "".join(body) + "</tbody>"
        "</table>"
    )


def _render_types_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for r in rows:
        body.append(
            "<tr data-id='{id}'>"
            "<td>{name}</td><td>{code}</td>"
            "<td>{maxd}</td><td>{paid}</td>"
            "<td><button onclick='deleteType({id})'>Delete</button></td>"
            "</tr>".format(
                id=int(r["id"]),
                name=_esc(r.get("name")),
                code=_esc(r.get("code")),
                maxd=_esc(r.get("max_days_per_year")),
                paid="Yes" if int(r.get("paid") or 0) else "No",
            )
        )
    return (
        "<table class='data-table'>"
        "<thead><tr>"
        "<th>Name</th><th>Code</th><th>Max days/year</th><th>Paid</th><th>Actions</th>"
        "</tr></thead>"
        "<tbody id='rows'>" + "".join(body) + "</tbody>"
        "</table>"
    )


def _render_balances_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for r in rows:
        body.append(
            "<tr data-id='{id}'>"
            "<td>{emp}</td><td>{lt}</td><td>{year}</td>"
            "<td>{allotted}</td><td>{used}</td><td>{pending}</td>"
            "</tr>".format(
                id=int(r["id"]),
                emp=_esc(r.get("employee_name") or r.get("employee_id")),
                lt=_esc(r.get("leave_type_name") or r.get("leave_type_id")),
                year=_esc(r.get("year")),
                allotted=_esc(r.get("allotted")),
                used=_esc(r.get("used")),
                pending=_esc(r.get("pending")),
            )
        )
    return (
        "<table class='data-table'>"
        "<thead><tr>"
        "<th>Employee</th><th>Leave type</th><th>Year</th>"
        "<th>Allotted</th><th>Used</th><th>Pending</th>"
        "</tr></thead>"
        "<tbody id='rows'>" + "".join(body) + "</tbody>"
        "</table>"
    )


def _render_body(active_tab: str, conn: sqlite3.Connection) -> str:
    tabs_html = (
        "<nav class='module-tabs'>"
        + "".join(
            "<a class='tab{active}' href='/m/leave/?tab={t}'>{l}</a>".format(
                active=" tab-active" if active_tab == t else "",
                t=t, l=l,
            )
            for t, l in (("requests", "Requests"), ("types", "Types"),
                         ("balances", "Balances"))
        )
        + "</nav>"
    )

    if active_tab == "types":
        toolbar = (
            "<div class='module-toolbar'>"
            "<h1>Leave types</h1>"
            "<button onclick=\"openCreateForm('type')\">+ Add type</button>"
            "<input type='search' placeholder='Search...' "
            "       oninput=\"filter(this.value)\">"
            "</div>"
        )
        table = _render_types_table(list_types(conn))
        dialog = (
            "<dialog id='create-dlg'>"
            "<form onsubmit=\"submitCreate(event,'type')\">"
            "<label>Name <input name='name' required></label>"
            "<label>Code <input name='code'></label>"
            "<label>Max days/year <input type='number' name='max_days_per_year' value='0'></label>"
            "<label>Carry forward <input type='number' name='carry_forward' value='0'></label>"
            "<label>Paid <input type='checkbox' name='paid' checked></label>"
            "<button type='submit'>Save</button>"
            "</form></dialog>"
        )
    elif active_tab == "balances":
        toolbar = (
            "<div class='module-toolbar'>"
            "<h1>Leave balances</h1>"
            "<input type='search' placeholder='Search...' "
            "       oninput=\"filter(this.value)\">"
            "</div>"
        )
        table = _render_balances_table(list_balances(conn))
        dialog = ""
    else:  # requests
        toolbar = (
            "<div class='module-toolbar'>"
            "<h1>Leave requests</h1>"
            "<button onclick=\"openCreateForm('request')\">+ Add request</button>"
            "<input type='search' placeholder='Search...' "
            "       oninput=\"filter(this.value)\">"
            "</div>"
        )
        table = _render_requests_table(list_requests(conn))
        dialog = (
            "<dialog id='create-dlg'>"
            "<form onsubmit=\"submitCreate(event,'request')\">"
            "<label>Employee id <input type='number' name='employee_id' required></label>"
            "<label>Leave type id <input type='number' name='leave_type_id' required></label>"
            "<label>Start date <input type='date' name='start_date' required></label>"
            "<label>End date <input type='date' name='end_date' required></label>"
            "<label>Reason <textarea name='reason'></textarea></label>"
            "<button type='submit'>Save</button>"
            "</form></dialog>"
        )

    script = (
        "<script>"
        "function openCreateForm(_kind){document.getElementById('create-dlg').showModal();}"
        "function filter(q){const rows=document.querySelectorAll('#rows tr');"
        "  q=q.toLowerCase();rows.forEach(r=>{r.style.display="
        "  r.textContent.toLowerCase().includes(q)?'':'none';});}"
        "async function submitCreate(ev,kind){ev.preventDefault();"
        "  const fd=new FormData(ev.target);const body={};"
        "  fd.forEach((v,k)=>{body[k]=v;});"
        "  if(kind==='type'){body.paid=ev.target.paid.checked?1:0;"
        "    await fetch('/api/m/leave/types/',{method:'POST',"
        "      headers:{'content-type':'application/json'},"
        "      body:JSON.stringify(body)});}"
        "  else{await fetch('/api/m/leave/',{method:'POST',"
        "      headers:{'content-type':'application/json'},"
        "      body:JSON.stringify(body)});}"
        "  location.reload();}"
        "async function approveRequest(id){"
        "  await fetch('/api/m/leave/'+id+'/approve',{method:'POST'});"
        "  location.reload();}"
        "async function rejectRequest(id){"
        "  await fetch('/api/m/leave/'+id+'/reject',{method:'POST'});"
        "  location.reload();}"
        "async function deleteRequest(id){"
        "  await fetch('/api/m/leave/'+id,{method:'DELETE'});"
        "  location.reload();}"
        "async function deleteType(id){"
        "  await fetch('/api/m/leave/types/'+id,{method:'DELETE'});"
        "  location.reload();}"
        "</script>"
    )
    return tabs_html + toolbar + table + dialog + script


# ---- HTTP handlers ---------------------------------------------------------

def _conn(handler) -> sqlite3.Connection:
    """Pull the active sqlite3 connection from the handler.

    Wave 2's server.py is expected to expose ``handler.conn`` (or
    ``handler.server.conn``). We tolerate either shape.
    """
    conn = getattr(handler, "conn", None)
    if conn is None:
        conn = getattr(getattr(handler, "server", None), "conn", None)
    if conn is None:
        raise RuntimeError("handler has no sqlite connection attached")
    return conn


def _query_param(handler, key: str, default: str = "") -> str:
    path = getattr(handler, "path", "") or ""
    if "?" not in path:
        return default
    qs = path.split("?", 1)[1]
    for part in qs.split("&"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k == key:
            return v
    return default


def list_view(handler) -> None:
    try:
        from hrkit.templates import render_module_page
    except ImportError:  # pragma: no cover — Wave 2 wires this up
        render_module_page = None

    tab = _query_param(handler, "tab", "requests").lower()
    if tab not in ("requests", "types", "balances"):
        tab = "requests"
    body = _render_body(tab, _conn(handler))
    if render_module_page is None:
        handler._html(200, f"<!doctype html><html><body>{body}</body></html>")
        return
    html = render_module_page(title=LABEL, nav_active=NAME, body_html=body)
    handler._html(200, html)


def _fmt_dt(value: Any) -> str:
    """Trim fractional seconds from a datetime-ish string for display."""
    if value in (None, ""):
        return ""
    text = str(value)
    if "." not in text:
        return text
    head, tail = text.split(".", 1)
    # Drop digits up to first non-digit (which usually marks the timezone).
    i = 0
    while i < len(tail) and tail[i].isdigit():
        i += 1
    return head + tail[i:]


def _detail_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT lr.*, e.full_name AS employee_name,
               lt.name AS leave_type_name,
               a.full_name AS approver_name
        FROM leave_request lr
        LEFT JOIN employee   e  ON e.id  = lr.employee_id
        LEFT JOIN leave_type lt ON lt.id = lr.leave_type_id
        LEFT JOIN employee   a  ON a.id  = lr.approver_id
        WHERE lr.id = ?
        """,
        (int(item_id),),
    ).fetchone()
    return _row_to_dict(row)


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section

    conn = _conn(handler)
    row = _detail_row(conn, int(item_id))
    if row is None:
        handler._html(404, render_detail_page(
            title="Not found",
            nav_active=NAME,
            subtitle=f"No leave request with id {int(item_id)}",
        ))
        return

    fields: list[tuple[str, Any]] = [
        ("Employee", row.get("employee_name") or row.get("employee_id")),
        ("Leave type", row.get("leave_type_name") or row.get("leave_type_id")),
        ("Start date", row.get("start_date")),
        ("End date", row.get("end_date")),
        ("Days", row.get("days")),
        ("Status", row.get("status")),
        ("Approver", row.get("approver_name") or row.get("approver_id")),
        ("Reason", row.get("reason")),
        ("Applied at", _fmt_dt(row.get("applied_at"))),
        ("Decided at", _fmt_dt(row.get("decided_at"))),
    ]

    # Related: balance for this employee+leave_type for the start_date's year.
    related_html = ""
    start = str(row.get("start_date") or "")
    year = start[:4] if len(start) >= 4 and start[:4].isdigit() else ""
    if year and row.get("employee_id") and row.get("leave_type_id"):
        bal = conn.execute(
            "SELECT allotted, used, pending FROM leave_balance "
            "WHERE employee_id = ? AND leave_type_id = ? AND year = ?",
            (int(row["employee_id"]), int(row["leave_type_id"]), int(year)),
        ).fetchone()
        if bal is not None:
            body = (
                "<table><thead><tr>"
                "<th>Year</th><th>Allotted</th><th>Used</th><th>Pending</th>"
                "</tr></thead><tbody>"
                f"<tr><td>{_esc(year)}</td>"
                f"<td>{_esc(bal['allotted'])}</td>"
                f"<td>{_esc(bal['used'])}</td>"
                f"<td>{_esc(bal['pending'])}</td></tr>"
                "</tbody></table>"
            )
        else:
            body = (
                f'<div class="empty">No balance row for '
                f'{_esc(year)}.</div>'
            )
        related_html = detail_section(title="Leave balance", body_html=body)

    rid = int(item_id)
    actions_html = ""
    if (row.get("status") or "") == "pending":
        actions_html = (
            f"<button onclick=\"fetch('/api/m/leave/{rid}/approve',"
            f"{{method:'POST'}}).then(()=>location.reload())\">Approve</button>"
            f"<button onclick=\"fetch('/api/m/leave/{rid}/reject',"
            f"{{method:'POST'}}).then(()=>location.reload())\">Reject</button>"
        )

    html = render_detail_page(
        title=f"Leave request #{rid}",
        nav_active=NAME,
        subtitle=f"{row.get('employee_name') or ''} · "
                 f"{row.get('leave_type_name') or ''}",
        fields=fields,
        actions_html=actions_html,
        related_html=related_html,
        item_id=rid,
        api_path="/api/m/leave",
        delete_redirect="/m/leave",
    )
    handler._html(200, html)


def detail_api_json(handler, item_id: int) -> None:
    """Return raw leave_request dict as JSON (back-compat for API clients)."""
    conn = _conn(handler)
    row = _detail_row(conn, int(item_id))
    if row is None:
        handler._json({"error": "not found"}, code=404)
        return
    handler._json(row)


def create_api(handler) -> None:
    payload = handler._read_json() or {}
    try:
        new_id = create_leave_request(
            _conn(handler),
            employee_id=int(payload.get("employee_id") or 0),
            leave_type_id=int(payload.get("leave_type_id") or 0),
            start_date=str(payload.get("start_date") or ""),
            end_date=str(payload.get("end_date") or ""),
            reason=str(payload.get("reason") or ""),
        )
    except (ValueError, sqlite3.Error) as exc:
        log.warning("leave create failed: %s", exc)
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"id": new_id}, code=201)


def update_api(handler, item_id: int) -> None:
    payload = handler._read_json() or {}
    fields = []
    params: list[Any] = []
    for key in ("start_date", "end_date", "reason", "status",
                "leave_type_id", "employee_id"):
        if key in payload:
            fields.append(f"{key} = ?")
            params.append(payload[key])
    if not fields:
        handler._json({"updated": 0})
        return
    params.append(int(item_id))
    sql = "UPDATE leave_request SET " + ", ".join(fields) + ", updated = ? WHERE id = ?"
    params.insert(-1, _now_ist())
    conn = _conn(handler)
    cur = conn.execute(sql, params)
    conn.commit()
    handler._json({"updated": cur.rowcount})


def delete_api(handler, item_id: int) -> None:
    ok = delete_request(_conn(handler), int(item_id))
    handler._json({"deleted": 1 if ok else 0})


def approve_api(handler, item_id: int) -> None:
    conn = _conn(handler)
    ok = set_status(conn, int(item_id), status="approved")
    response: dict[str, Any] = {"ok": ok}
    if ok:
        try:
            from hrkit.integrations import hooks
            row = conn.execute(
                "SELECT employee_id, leave_type_id, start_date, end_date, days, reason "
                "FROM leave_request WHERE id=?",
                (int(item_id),),
            ).fetchone()
            if row:
                response["integrations"] = hooks.emit("leave.approved", {
                    "leave_request_id": int(item_id),
                    "employee_id": row["employee_id"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "days": row["days"],
                    "reason": row["reason"],
                }, conn=conn)
        except Exception:
            pass
    handler._json(response)


def reject_api(handler, item_id: int) -> None:
    ok = set_status(_conn(handler), int(item_id), status="rejected")
    handler._json({"ok": ok})


def create_type_api(handler) -> None:
    payload = handler._read_json() or {}
    try:
        new_id = create_leave_type(
            _conn(handler),
            name=str(payload.get("name") or "").strip(),
            code=str(payload.get("code") or ""),
            max_days_per_year=int(payload.get("max_days_per_year") or 0),
            carry_forward=int(payload.get("carry_forward") or 0),
            paid=int(payload.get("paid") or 0),
        )
    except (ValueError, sqlite3.Error) as exc:
        log.warning("leave_type create failed: %s", exc)
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"id": new_id}, code=201)


def delete_type_api(handler, item_id: int) -> None:
    ok = delete_type(_conn(handler), int(item_id))
    handler._json({"deleted": 1 if ok else 0})


ROUTES = {
    "GET": [
        (r"^/api/m/leave/(\d+)/?$",             detail_api_json),
        (r"^/m/leave/?$",                       list_view),
        (r"^/m/leave/(\d+)/?$",                 detail_view),
    ],
    "POST": [
        (r"^/api/m/leave/?$",                   create_api),
        (r"^/api/m/leave/types/?$",             create_type_api),
        (r"^/api/m/leave/(\d+)/approve/?$",     approve_api),
        (r"^/api/m/leave/(\d+)/reject/?$",      reject_api),
        (r"^/api/m/leave/(\d+)/?$",             update_api),
    ],
    "DELETE": [
        (r"^/api/m/leave/types/(\d+)/?$",       delete_type_api),
        (r"^/api/m/leave/(\d+)/?$",             delete_api),
    ],
}


# ---- CLI subcommands -------------------------------------------------------

def _add_type_args(p) -> None:
    p.add_argument("--name", required=True)
    p.add_argument("--code", default="")
    p.add_argument("--max-days", type=int, default=0, dest="max_days_per_year")
    p.add_argument("--no-paid", action="store_false", dest="paid", default=True)


def _handle_type_add(args, conn: sqlite3.Connection) -> int:
    new_id = create_leave_type(
        conn,
        name=args.name,
        code=args.code,
        max_days_per_year=args.max_days_per_year,
        paid=1 if args.paid else 0,
    )
    print(json.dumps({"id": new_id}))
    return 0


def _add_request_args(p) -> None:
    p.add_argument("--employee-id", type=int, required=True, dest="employee_id")
    p.add_argument("--type-id", type=int, required=True, dest="leave_type_id")
    p.add_argument("--start", required=True, dest="start_date")
    p.add_argument("--end", required=True, dest="end_date")
    p.add_argument("--reason", default="")


def _handle_request_add(args, conn: sqlite3.Connection) -> int:
    new_id = create_leave_request(
        conn,
        employee_id=args.employee_id,
        leave_type_id=args.leave_type_id,
        start_date=args.start_date,
        end_date=args.end_date,
        reason=args.reason,
    )
    print(json.dumps({"id": new_id}))
    return 0


def _handle_request_list(args, conn: sqlite3.Connection) -> int:
    rows = list_requests(conn)
    print(json.dumps(rows, default=str))
    return 0


CLI = [
    ("leave-type-add",     _add_type_args,    _handle_type_add),
    ("leave-request-add",  _add_request_args, _handle_request_add),
    ("leave-request-list", lambda p: None,    _handle_request_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "hr",
    "requires": ["employee"],
    "description": "Leave types, balances per year, requests and manager approvals.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
