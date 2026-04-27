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
        "<a href='/m/attendance/heatmap' "
        "   style='padding:7px 14px;border:1px solid var(--border);"
        "   border-radius:6px;color:var(--dim);text-decoration:none;font-size:13px'>"
        "  Heatmap overview</a>"
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


# ---------------------------------------------------------------------------
# Heatmap dashboard ("Claude session"–style overview)
# ---------------------------------------------------------------------------
_RANGE_OPTIONS: tuple[tuple[str, str, int | None], ...] = (
    ("all",  "All",   None),
    ("30d",  "30d",   30),
    ("7d",   "7d",    7),
)
_VIEW_OPTIONS: tuple[tuple[str, str], ...] = (
    ("overview", "Overview"),
    ("per_employee", "Per-employee"),
)
_DAY_LABELS: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _coerce_range(range_key: str) -> tuple[str, str, int | None]:
    """Resolve a range query-string param to (key, label, days)."""
    rk = (range_key or "30d").lower().strip()
    for key, label, days in _RANGE_OPTIONS:
        if key == rk:
            return key, label, days
    return ("30d", "30d", 30)


def _date_floor_sql(days: int | None, *, column: str = "date") -> tuple[str, list[Any]]:
    """Return (sql_clause, params) for ``<column> >= floor`` filters.

    ``column`` lets callers pass an aliased column (e.g. ``a.date``) without
    having to string-rewrite the result, which would also touch the
    ``date('now', ...)`` SQL function call.
    """
    if days is None:
        return "", []
    return (f"AND {column} >= date('now', ?, '+05:30')",
            [f"-{int(days)} days"])


def _collect_heatmap_kpis(conn: sqlite3.Connection,
                           days: int | None) -> dict[str, Any]:
    """Compute the 8 KPI values for the dashboard top tiles."""
    floor_clause, floor_params = _date_floor_sql(days)
    kpis: dict[str, Any] = {
        "checkins": 0, "avg_hours": 0.0, "active_days": 0,
        "current_streak": 0, "longest_streak": 0,
        "peak_hour": "—", "top_employee": "—", "holidays": 0,
    }

    # Total check-ins (rows with a non-empty check_in).
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM attendance "
        f"WHERE check_in <> '' {floor_clause}", floor_params,
    ).fetchone()
    kpis["checkins"] = int(row["n"]) if row else 0

    # Avg hours per active day.
    row = conn.execute(
        f"SELECT AVG(hours_minor) AS m FROM attendance "
        f"WHERE hours_minor > 0 {floor_clause}", floor_params,
    ).fetchone()
    avg_minutes = float(row["m"] or 0) if row else 0.0
    kpis["avg_hours"] = round(avg_minutes / 60.0, 1)

    # Distinct active days in range.
    row = conn.execute(
        f"SELECT COUNT(DISTINCT date) AS n FROM attendance "
        f"WHERE check_in <> '' {floor_clause}", floor_params,
    ).fetchone()
    kpis["active_days"] = int(row["n"]) if row else 0

    # Current + longest streak across distinct active days.
    days_active = [
        r["date"] for r in conn.execute(
            f"SELECT DISTINCT date FROM attendance "
            f"WHERE check_in <> '' {floor_clause} ORDER BY date DESC",
            floor_params,
        ).fetchall()
    ]
    kpis["current_streak"] = _streak_from_today(days_active)
    kpis["longest_streak"] = _longest_streak(sorted(days_active))

    # Peak hour: most frequent integer hour in check_in (HH:MM).
    row = conn.execute(
        f"SELECT substr(check_in, 1, 2) AS hh, COUNT(*) AS n "
        f"FROM attendance WHERE check_in <> '' {floor_clause} "
        f"GROUP BY hh ORDER BY n DESC LIMIT 1", floor_params,
    ).fetchone()
    if row and row["hh"]:
        try:
            h = int(row["hh"])
            suffix = "AM" if h < 12 else "PM"
            display_h = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
            kpis["peak_hour"] = f"{display_h} {suffix}"
        except (TypeError, ValueError):
            kpis["peak_hour"] = row["hh"]

    # Top employee: name with most check-ins in range. Reuse helper with
    # the aliased column so we don't string-rewrite the SQL clause.
    a_floor_clause, a_floor_params = _date_floor_sql(days, column="a.date")
    row = conn.execute(
        f"SELECT e.full_name AS name, COUNT(*) AS n "
        f"FROM attendance a JOIN employee e ON e.id = a.employee_id "
        f"WHERE a.check_in <> '' {a_floor_clause} "
        f"GROUP BY a.employee_id ORDER BY n DESC LIMIT 1", a_floor_params,
    ).fetchone()
    if row and row["name"]:
        kpis["top_employee"] = str(row["name"])

    # Holidays in range (the table exists from the v1.1 schema).
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM holiday WHERE 1=1 {floor_clause}",
            floor_params,
        ).fetchone()
        kpis["holidays"] = int(row["n"]) if row else 0
    except sqlite3.Error:
        kpis["holidays"] = 0

    return kpis


def _streak_from_today(dates_desc: list[str]) -> int:
    """Count consecutive days from today backward that appear in ``dates_desc``."""
    if not dates_desc:
        return 0
    from datetime import date, timedelta
    today = date.today()
    seen = set(dates_desc)
    streak = 0
    cursor = today
    while cursor.isoformat() in seen:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def _longest_streak(dates_asc: list[str]) -> int:
    """Longest run of consecutive days within a sorted-ascending list."""
    if not dates_asc:
        return 0
    from datetime import date, timedelta
    longest = 1
    run = 1
    prev = date.fromisoformat(dates_asc[0][:10])
    for d in dates_asc[1:]:
        try:
            cur = date.fromisoformat(d[:10])
        except ValueError:
            continue
        if cur - prev == timedelta(days=1):
            run += 1
            longest = max(longest, run)
        elif cur != prev:
            run = 1
        prev = cur
    return longest


def _build_overview_matrix(
        conn: sqlite3.Connection, days: int | None
) -> tuple[list[str], list[str], list[list[int]]]:
    """7-row × N-column matrix: rows = weekday Mon..Sun, cols = week-of-year."""
    floor_clause, floor_params = _date_floor_sql(days)
    rows = conn.execute(
        f"SELECT date, COUNT(*) AS n FROM attendance "
        f"WHERE check_in <> '' {floor_clause} GROUP BY date ORDER BY date",
        floor_params,
    ).fetchall()
    if not rows:
        return list(_DAY_LABELS), [], [[0] * 0 for _ in range(7)]

    from datetime import date, timedelta
    parsed: list[tuple[date, int]] = []
    for r in rows:
        try:
            parsed.append((date.fromisoformat(r["date"][:10]), int(r["n"])))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return list(_DAY_LABELS), [], [[0] * 0 for _ in range(7)]

    first = parsed[0][0]
    last = parsed[-1][0]
    # Anchor on the Monday of the first observed week.
    start = first - timedelta(days=first.weekday())
    weeks: list[date] = []
    cursor = start
    while cursor <= last:
        weeks.append(cursor)
        cursor = cursor + timedelta(days=7)
    n_weeks = len(weeks) or 1

    counts: dict[date, int] = {d: n for d, n in parsed}
    matrix: list[list[int]] = [[0] * n_weeks for _ in range(7)]
    for weekday in range(7):
        for w_idx, week_start in enumerate(weeks):
            cell_date = week_start + timedelta(days=weekday)
            matrix[weekday][w_idx] = counts.get(cell_date, 0)
    col_labels = [w.strftime("%b %d") if (w.day <= 7 or w == weeks[0]) else ""
                  for w in weeks]
    return list(_DAY_LABELS), col_labels, matrix


def _build_per_employee_matrix(
        conn: sqlite3.Connection, days: int | None, max_rows: int = 30
) -> tuple[list[str], list[str], list[list[int]]]:
    """Rows = top-N employees by activity, cols = days in the range
    (most recent on the right). Cell value = minutes worked that day."""
    floor_clause, floor_params = _date_floor_sql(days)
    a_floor_clause, a_floor_params = _date_floor_sql(days, column="a.date")
    rows = conn.execute(
        f"SELECT a.employee_id, e.full_name, a.date, COALESCE(a.hours_minor, 0) AS m "
        f"FROM attendance a JOIN employee e ON e.id = a.employee_id "
        f"WHERE a.check_in <> '' {a_floor_clause} "
        f"ORDER BY a.date",
        a_floor_params,
    ).fetchall()
    if not rows:
        return [], [], []

    from datetime import date, timedelta
    by_emp: dict[int, dict[str, int]] = {}
    names: dict[int, str] = {}
    dates_seen: set[date] = set()
    for r in rows:
        emp_id = int(r["employee_id"])
        try:
            d = date.fromisoformat(r["date"][:10])
        except (TypeError, ValueError):
            continue
        names[emp_id] = str(r["full_name"] or f"#{emp_id}")
        by_emp.setdefault(emp_id, {})[d.isoformat()] = int(r["m"])
        dates_seen.add(d)

    if not dates_seen:
        return [], [], []

    first = min(dates_seen)
    last = max(dates_seen)
    # Build a contiguous date axis from first..last for visual continuity.
    all_dates: list[date] = []
    cursor = first
    while cursor <= last:
        all_dates.append(cursor)
        cursor = cursor + timedelta(days=1)
    col_labels = [d.strftime("%d") if d.day != 1 else d.strftime("%b %d")
                  for d in all_dates]

    # Pick the top-N employees by total minutes in range.
    totals = sorted(
        ((emp_id, sum(by_emp[emp_id].values())) for emp_id in by_emp),
        key=lambda t: t[1], reverse=True,
    )[:max_rows]

    matrix: list[list[int]] = []
    row_labels: list[str] = []
    for emp_id, _total in totals:
        row_labels.append(names[emp_id])
        emp_days = by_emp[emp_id]
        matrix.append([emp_days.get(d.isoformat(), 0) for d in all_dates])
    return row_labels, col_labels, matrix


def _fun_fact(kpis: dict[str, Any], days: int | None) -> str:
    """A small HR-flavored footer line, picked deterministically from the
    KPIs so it changes as the data does."""
    checkins = int(kpis.get("checkins") or 0)
    avg = float(kpis.get("avg_hours") or 0)
    longest = int(kpis.get("longest_streak") or 0)
    if checkins == 0:
        return "No check-ins recorded yet — once your team starts logging time, this dashboard fills in."
    if longest >= 14:
        return f"Longest streak is {longest} consecutive days — someone needs a break."
    if avg >= 9.5:
        return f"Average day is {avg} hours — that's a long workday across {checkins} check-ins."
    if avg and avg < 6:
        return f"Average day is {avg} hours — light workdays across {checkins} check-ins."
    return f"{checkins} check-ins logged" + (
        f" over the last {days} days." if days else " across the full history.")


def heatmap_view(handler) -> None:
    """GET /m/attendance/heatmap — Claude-session-style overview dashboard."""
    from hrkit.templates import (
        render_module_page, render_stat_grid, render_heatmap,
    )

    conn = _conn(handler)
    range_key, range_label, days = _coerce_range(_query_param(handler, "range", "30d"))
    view_key = _query_param(handler, "view", "overview")
    if view_key not in {k for k, _ in _VIEW_OPTIONS}:
        view_key = "overview"

    kpis = _collect_heatmap_kpis(conn, days)
    overview_rows, overview_cols, overview_matrix = _build_overview_matrix(conn, days)
    pe_rows, pe_cols, pe_matrix = _build_per_employee_matrix(conn, days)

    stat_specs = [
        {"label": "Check-ins", "value": kpis["checkins"]},
        {"label": "Avg hours / day", "value": kpis["avg_hours"]},
        {"label": "Active days", "value": kpis["active_days"]},
        {"label": "Holidays", "value": kpis["holidays"]},
        {"label": "Current streak", "value": f'{kpis["current_streak"]}d'},
        {"label": "Longest streak", "value": f'{kpis["longest_streak"]}d'},
        {"label": "Peak hour", "value": kpis["peak_hour"]},
        {"label": "Top employee", "value": kpis["top_employee"]},
    ]
    stat_grid_html = render_stat_grid(stat_specs)

    overview_html = render_heatmap(
        row_labels=overview_rows, col_labels=overview_cols,
        values=overview_matrix, row_label_header="Day",
        legend_label="check-ins",
    ) if overview_matrix and overview_matrix[0] else (
        '<div class="att-empty">No attendance data in this range.</div>'
    )

    pe_html = render_heatmap(
        row_labels=pe_rows, col_labels=pe_cols, values=pe_matrix,
        row_label_header="Employee",
        legend_label="minutes",
    ) if pe_matrix else (
        '<div class="att-empty">No employee activity in this range.</div>'
    )

    range_pills = "".join(
        f'<a class="att-pill{" is-on" if k == range_key else ""}" '
        f'href="?view={_esc(view_key)}&range={k}">{_esc(label)}</a>'
        for k, label, _d in _RANGE_OPTIONS
    )
    tabs = "".join(
        f'<a class="att-tab{" is-on" if k == view_key else ""}" '
        f'href="?view={k}&range={range_key}">{_esc(label)}</a>'
        for k, label in _VIEW_OPTIONS
    )

    body = f"""
<style>
  .att-card{{background:var(--panel);border:1px solid var(--border);
    border-radius:14px;padding:18px;margin-bottom:18px;box-shadow:var(--shadow-sm)}}
  .att-bar{{display:flex;align-items:center;gap:8px;margin-bottom:14px}}
  .att-bar .att-tabs{{display:flex;gap:4px;background:var(--row-hover);
    border-radius:10px;padding:4px}}
  .att-tab{{padding:6px 14px;border-radius:8px;color:var(--dim);
    text-decoration:none;font-size:13px;font-weight:500}}
  .att-tab.is-on{{background:var(--panel);color:var(--text);
    box-shadow:var(--shadow-sm)}}
  .att-bar .att-spacer{{flex:1}}
  .att-pills{{display:flex;gap:4px;background:var(--row-hover);
    border-radius:10px;padding:4px}}
  .att-pill{{padding:6px 14px;border-radius:8px;color:var(--dim);
    text-decoration:none;font-size:12.5px;font-weight:500}}
  .att-pill.is-on{{background:var(--panel);color:var(--text);
    box-shadow:var(--shadow-sm)}}
  .att-card .stat-grid{{margin:0 0 14px}}
  /* Larger, rounded heatmap cells per the Claude-session design. */
  .att-card .heatmap-table td{{width:18px;height:18px;border-radius:4px}}
  .att-card .heatmap-table{{border-spacing:4px}}
  .att-fact{{color:var(--dim);font-size:12.5px;margin:14px 2px 0}}
  .att-empty{{padding:30px;text-align:center;color:var(--dim);
    border:1px dashed var(--border);border-radius:10px;font-size:13px}}
  .att-toolbar{{display:flex;align-items:center;gap:12px;margin-bottom:14px}}
  .att-toolbar h1{{margin:0;font-size:22px;font-weight:600;color:var(--text)}}
  .att-toolbar a.list-link{{margin-left:auto;padding:6px 12px;border-radius:6px;
    color:var(--dim);text-decoration:none;font-size:13px;border:1px solid var(--border)}}
  .att-toolbar a.list-link:hover{{color:var(--text);border-color:var(--accent)}}
</style>
<div class="att-toolbar">
  <h1>Attendance overview</h1>
  <a class="list-link" href="/m/attendance">Day-by-day list</a>
</div>
<div class="att-card">
  <div class="att-bar">
    <div class="att-tabs">{tabs}</div>
    <span class="att-spacer"></span>
    <div class="att-pills">{range_pills}</div>
  </div>
  {stat_grid_html}
  <div class="att-heatmap-wrap" data-view="{_esc(view_key)}">
    {overview_html if view_key == "overview" else pe_html}
  </div>
  <div class="att-fact">{_esc(_fun_fact(kpis, days))}</div>
</div>
"""
    handler._html(200, render_module_page(
        title="Attendance overview", nav_active=NAME, body_html=body,
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
        (r"^/m/attendance/heatmap/?$",  heatmap_view),
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
    "category": "hr",
    "requires": ["employee"],
    "description": "Daily check-in / check-out, hours worked, leave / holiday status.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
