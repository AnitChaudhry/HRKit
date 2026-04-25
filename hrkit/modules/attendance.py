"""Attendance module — daily check-in / check-out tracker.

The ``attendance`` table is created by the central migration. Each row is
unique on ``(employee_id, date)``. ``hours_minor`` is stored as integer
*minutes* (per the project's "money/time always in minor units" rule) and is
auto-derived from ``check_in`` / ``check_out`` when both are supplied.
"""
from __future__ import annotations

import html as htmllib
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

NAME = "attendance"
LABEL = "Attendance"
ICON = "clock"


# ---- DB --------------------------------------------------------------------

def ensure_schema(conn: sqlite3.Connection) -> None:
    """No-op — the ``attendance`` table is created by the central
    migration in ``001_full_hr_schema.sql``."""
    pass


# ---- Helpers ---------------------------------------------------------------

_VALID_STATUS = ("present", "absent", "half_day", "leave", "holiday")


def _parse_time(value: str) -> datetime | None:
    """Accept either a full ISO datetime or a 'HH:MM' / 'HH:MM:SS' time."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    # Try full datetime first.
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    # Fall back to HH:MM[:SS] (date doesn't matter for diff).
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(value, fmt)
            return t
        except ValueError:
            continue
    return None


def _calc_minutes(check_in: str, check_out: str) -> int:
    """Inclusive minute count between check_in and check_out.

    Returns 0 when either side is empty/unparseable or check_out < check_in.
    """
    a = _parse_time(check_in)
    b = _parse_time(check_out)
    if a is None or b is None:
        return 0
    delta = (b - a).total_seconds()
    if delta < 0:
        return 0
    return int(delta // 60)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


# ---- Direct DB API --------------------------------------------------------

def create_attendance(conn: sqlite3.Connection, *, employee_id: int, date: str,
                      check_in: str = "", check_out: str = "",
                      status: str = "present", notes: str = "") -> int:
    """Insert an attendance row, returning its new id.

    ``hours_minor`` is auto-calculated as integer *minutes* when both
    check_in and check_out are supplied.
    """
    if status not in _VALID_STATUS:
        raise ValueError(f"invalid status: {status!r}")
    minutes = _calc_minutes(check_in, check_out)
    cur = conn.execute(
        "INSERT INTO attendance "
        "(employee_id, date, check_in, check_out, hours_minor, status, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (int(employee_id), date, check_in, check_out, minutes, status, notes),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_attendance(conn: sqlite3.Connection, row_id: int, **changes: Any) -> int:
    """Patch an attendance row. ``hours_minor`` is recomputed if either
    check_in or check_out changes."""
    if not changes:
        return 0
    allowed = {"date", "check_in", "check_out", "status", "notes"}
    fields: list[str] = []
    params: list[Any] = []
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key == "status" and value not in _VALID_STATUS:
            raise ValueError(f"invalid status: {value!r}")
        fields.append(f"{key} = ?")
        params.append(value)
    if not fields:
        return 0
    # Recompute hours_minor when either time field is touched.
    if "check_in" in changes or "check_out" in changes:
        existing = conn.execute(
            "SELECT check_in, check_out FROM attendance WHERE id = ?",
            (int(row_id),),
        ).fetchone()
        ci = changes.get("check_in", existing["check_in"] if existing else "")
        co = changes.get("check_out", existing["check_out"] if existing else "")
        fields.append("hours_minor = ?")
        params.append(_calc_minutes(ci, co))
    params.append(int(row_id))
    cur = conn.execute(
        "UPDATE attendance SET " + ", ".join(fields) + " WHERE id = ?",
        params,
    )
    conn.commit()
    return cur.rowcount


def delete_attendance(conn: sqlite3.Connection, row_id: int) -> bool:
    cur = conn.execute("DELETE FROM attendance WHERE id = ?", (int(row_id),))
    conn.commit()
    return cur.rowcount > 0


def list_attendance(conn: sqlite3.Connection, *,
                    employee_id: int | None = None,
                    month: str | None = None) -> list[dict[str, Any]]:
    """List attendance rows, optionally filtered by employee + YYYY-MM month."""
    sql = (
        "SELECT a.id, a.employee_id, a.date, a.check_in, a.check_out, "
        "       a.hours_minor, a.status, a.notes, "
        "       e.full_name AS employee_name "
        "FROM attendance a "
        "LEFT JOIN employee e ON e.id = a.employee_id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if employee_id is not None:
        sql += " AND a.employee_id = ?"
        params.append(int(employee_id))
    if month:
        sql += " AND substr(a.date,1,7) = ?"
        params.append(month)
    sql += " ORDER BY a.date DESC, a.id DESC"
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


# ---- HTML rendering --------------------------------------------------------

def _esc(value: Any) -> str:
    return htmllib.escape("" if value is None else str(value), quote=True)


def _format_hours(minutes: int) -> str:
    minutes = int(minutes or 0)
    if minutes <= 0:
        return "—"
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def _render_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for r in rows:
        body.append(
            "<tr data-id='{id}'>"
            "<td>{date}</td><td>{ci}</td><td>{co}</td>"
            "<td>{hours}</td>"
            "<td><span class='badge badge-{status}'>{status}</span></td>"
            "<td>"
            "  <button onclick='deleteRow({id})'>Delete</button>"
            "</td>"
            "</tr>".format(
                id=int(r["id"]),
                date=_esc(r.get("date")),
                ci=_esc(r.get("check_in")),
                co=_esc(r.get("check_out")),
                hours=_esc(_format_hours(r.get("hours_minor") or 0)),
                status=_esc(r.get("status")),
            )
        )
    return (
        "<table class='data-table'>"
        "<thead><tr>"
        "<th>Date</th><th>Check in</th><th>Check out</th>"
        "<th>Hours</th><th>Status</th><th>Actions</th>"
        "</tr></thead>"
        "<tbody id='rows'>" + "".join(body) + "</tbody>"
        "</table>"
    )


def _render_body(handler) -> str:
    conn = _conn(handler)
    emp_q = _query_param(handler, "employee_id", "")
    month_q = _query_param(handler, "month", "")
    employee_id = int(emp_q) if emp_q.isdigit() else None
    month = month_q if month_q else None
    rows = list_attendance(conn, employee_id=employee_id, month=month)

    toolbar = (
        "<div class='module-toolbar'>"
        "<h1>Attendance</h1>"
        "<form class='module-filter' method='get' action='/m/attendance/'>"
        f"  <input name='employee_id' type='number' placeholder='Employee id' "
        f"         value='{_esc(emp_q)}'>"
        f"  <input name='month' type='month' value='{_esc(month_q)}'>"
        "  <button type='submit'>Filter</button>"
        "</form>"
        "<button onclick='openCreateForm()'>+ Add row</button>"
        "<input type='search' placeholder='Search...' "
        "       oninput='filter(this.value)'>"
        "</div>"
    )
    table = _render_table(rows)
    dialog = (
        "<dialog id='create-dlg'>"
        "<form onsubmit='submitCreate(event)'>"
        "<label>Employee id <input type='number' name='employee_id' required></label>"
        "<label>Date <input type='date' name='date' required></label>"
        "<label>Check in <input type='time' name='check_in'></label>"
        "<label>Check out <input type='time' name='check_out'></label>"
        "<label>Status <select name='status'>"
        + "".join(f"<option value='{s}'>{s}</option>" for s in _VALID_STATUS)
        + "</select></label>"
        "<button type='submit'>Save</button>"
        "</form></dialog>"
    )
    script = (
        "<script>"
        "function openCreateForm(){document.getElementById('create-dlg').showModal();}"
        "function filter(q){const rows=document.querySelectorAll('#rows tr');"
        "  q=q.toLowerCase();rows.forEach(r=>{r.style.display="
        "  r.textContent.toLowerCase().includes(q)?'':'none';});}"
        "async function submitCreate(ev){ev.preventDefault();"
        "  const fd=new FormData(ev.target);const body={};"
        "  fd.forEach((v,k)=>{body[k]=v;});"
        "  await fetch('/api/m/attendance/',{method:'POST',"
        "    headers:{'content-type':'application/json'},"
        "    body:JSON.stringify(body)});"
        "  location.reload();}"
        "async function deleteRow(id){"
        "  await fetch('/api/m/attendance/'+id,{method:'DELETE'});"
        "  location.reload();}"
        "</script>"
    )
    return toolbar + table + dialog + script


# ---- HTTP handlers --------------------------------------------------------

def _conn(handler) -> sqlite3.Connection:
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
    except ImportError:  # pragma: no cover
        render_module_page = None
    body = _render_body(handler)
    if render_module_page is None:
        handler._html(200, f"<!doctype html><html><body>{body}</body></html>")
        return
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME, body_html=body,
    ))


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


def _detail_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT a.*, e.full_name AS employee_name
        FROM attendance a
        LEFT JOIN employee e ON e.id = a.employee_id
        WHERE a.id = ?
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
            subtitle=f"No attendance row with id {int(item_id)}",
        ))
        return

    fields: list[tuple[str, Any]] = [
        ("Date", row.get("date")),
        ("Employee", row.get("employee_name") or row.get("employee_id")),
        ("Check in", _fmt_dt(row.get("check_in"))),
        ("Check out", _fmt_dt(row.get("check_out"))),
        ("Hours", _format_hours(row.get("hours_minor") or 0)),
        ("Status", row.get("status")),
        ("Notes", row.get("notes")),
    ]

    # Last 7 attendance rows for the same employee.
    related_html = ""
    emp_id = row.get("employee_id")
    if emp_id is not None:
        recent = conn.execute(
            "SELECT id, date, check_in, check_out, hours_minor, status "
            "FROM attendance WHERE employee_id = ? "
            "ORDER BY date DESC, id DESC LIMIT 7",
            (int(emp_id),),
        ).fetchall()
        if recent:
            body = (
                "<table><thead><tr>"
                "<th>Date</th><th>In</th><th>Out</th><th>Hours</th><th>Status</th>"
                "</tr></thead><tbody>"
                + "".join(
                    f"<tr><td>"
                    f"<a href=\"/m/attendance/{int(r['id'])}\">{_esc(r['date'])}</a>"
                    f"</td><td>{_esc(r['check_in'])}</td>"
                    f"<td>{_esc(r['check_out'])}</td>"
                    f"<td>{_esc(_format_hours(r['hours_minor'] or 0))}</td>"
                    f"<td>{_esc(r['status'])}</td></tr>"
                    for r in recent
                )
                + "</tbody></table>"
            )
        else:
            body = '<div class="empty">No recent attendance.</div>'
        related_html = detail_section(
            title="Last 7 attendance rows", body_html=body,
        )

    rid = int(item_id)
    html = render_detail_page(
        title=f"Attendance · {row.get('date') or ''}",
        nav_active=NAME,
        subtitle=str(row.get("employee_name") or ""),
        fields=fields,
        related_html=related_html,
        item_id=rid,
        api_path="/api/m/attendance",
        delete_redirect="/m/attendance",
    )
    handler._html(200, html)


def detail_api_json(handler, item_id: int) -> None:
    """Return raw attendance row as JSON."""
    row = _detail_row(_conn(handler), int(item_id))
    if row is None:
        handler._json({"error": "not found"}, code=404)
        return
    handler._json(row)


def create_api(handler) -> None:
    payload = handler._read_json() or {}
    try:
        new_id = create_attendance(
            _conn(handler),
            employee_id=int(payload.get("employee_id") or 0),
            date=str(payload.get("date") or ""),
            check_in=str(payload.get("check_in") or ""),
            check_out=str(payload.get("check_out") or ""),
            status=str(payload.get("status") or "present"),
            notes=str(payload.get("notes") or ""),
        )
    except (ValueError, sqlite3.Error) as exc:
        log.warning("attendance create failed: %s", exc)
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"id": new_id}, code=201)


def update_api(handler, item_id: int) -> None:
    payload = handler._read_json() or {}
    try:
        changed = update_attendance(_conn(handler), int(item_id), **payload)
    except (ValueError, sqlite3.Error) as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"updated": changed})


def delete_api(handler, item_id: int) -> None:
    ok = delete_attendance(_conn(handler), int(item_id))
    handler._json({"deleted": 1 if ok else 0})


ROUTES = {
    "GET": [
        (r"^/api/m/attendance/(\d+)/?$",    detail_api_json),
        (r"^/m/attendance/?$",          list_view),
        (r"^/m/attendance/(\d+)/?$",    detail_view),
    ],
    "POST": [
        (r"^/api/m/attendance/?$",          create_api),
        (r"^/api/m/attendance/(\d+)/?$",    update_api),
    ],
    "DELETE": [
        (r"^/api/m/attendance/(\d+)/?$",    delete_api),
    ],
}


# ---- CLI subcommands ------------------------------------------------------

def _add_create_args(p) -> None:
    p.add_argument("--employee-id", type=int, required=True, dest="employee_id")
    p.add_argument("--date", required=True)
    p.add_argument("--check-in", default="", dest="check_in")
    p.add_argument("--check-out", default="", dest="check_out")
    p.add_argument("--status", default="present", choices=list(_VALID_STATUS))
    p.add_argument("--notes", default="")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_attendance(
        conn,
        employee_id=args.employee_id,
        date=args.date,
        check_in=args.check_in,
        check_out=args.check_out,
        status=args.status,
        notes=args.notes,
    )
    print(json.dumps({"id": new_id}))
    return 0


def _add_list_args(p) -> None:
    p.add_argument("--employee-id", type=int, default=None, dest="employee_id")
    p.add_argument("--month", default=None)


def _handle_list(args, conn: sqlite3.Connection) -> int:
    rows = list_attendance(conn, employee_id=args.employee_id, month=args.month)
    print(json.dumps(rows, default=str))
    return 0


CLI = [
    ("attendance-add",  _add_create_args, _handle_create),
    ("attendance-list", _add_list_args,   _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
