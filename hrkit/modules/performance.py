"""Performance review module.

A performance_review row tracks one review cycle for one employee. The
status flow is draft -> submitted -> acknowledged, each transition exposed
as a POST endpoint and a CLI subcommand.
"""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from ..branding import app_name

log = logging.getLogger(__name__)

NAME = "performance"
LABEL = "Performance"
ICON = "chart-line"

_VALID_STATUSES = ("draft", "submitted", "acknowledged")
_TRANSITIONS = {
    "draft": "submitted",
    "submitted": "acknowledged",
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def ensure_schema(conn: sqlite3.Connection) -> None:
    """No module-private tables — performance_review lives in 001_*.sql."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ist() -> str:
    try:
        from ..config import IST  # type: ignore[attr-defined]
        return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")
    except (ImportError, AttributeError):
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+05:30")


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def _validate_score(value: Any) -> float:
    """Coerce to float and clamp/validate to 0..10 range."""
    if value is None or value == "":
        return 0.0
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"score must be numeric: {value!r}") from exc
    if score < 0 or score > 10:
        raise ValueError("score must be between 0 and 10")
    return score


def _validate_rubric(value: Any) -> str:
    """Ensure rubric_json is a JSON-serialisable string. Returns the string."""
    if value is None or value == "":
        return "{}"
    if isinstance(value, str):
        try:
            json.loads(value)
        except ValueError as exc:
            raise ValueError(f"rubric_json is not valid JSON: {exc}") from exc
        return value
    try:
        return json.dumps(value, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"rubric_json is not JSON-serialisable: {exc}") from exc


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

def list_reviews(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT pr.id, pr.employee_id, pr.cycle, pr.reviewer_id,
               pr.status, pr.score, pr.comments,
               pr.submitted_at, pr.created, pr.updated,
               e.full_name AS employee_name,
               r.full_name AS reviewer_name
        FROM performance_review pr
        JOIN employee e ON e.id = pr.employee_id
        LEFT JOIN employee r ON r.id = pr.reviewer_id
        ORDER BY pr.created DESC, pr.id DESC
        """
    ).fetchall()
    return [_row_to_dict(r) or {} for r in rows]


def get_review(conn: sqlite3.Connection, review_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT pr.*, e.full_name AS employee_name,
               r.full_name AS reviewer_name
        FROM performance_review pr
        JOIN employee e ON e.id = pr.employee_id
        LEFT JOIN employee r ON r.id = pr.reviewer_id
        WHERE pr.id = ?
        """,
        (int(review_id),),
    ).fetchone()
    return _row_to_dict(row)


def create_review(
    conn: sqlite3.Connection,
    *,
    employee_id: int,
    cycle: str,
    reviewer_id: int | None = None,
    rubric_json: Any = None,
    comments: str = "",
    score: Any = 0,
) -> int:
    if not employee_id:
        raise ValueError("employee_id is required")
    if not cycle or not str(cycle).strip():
        raise ValueError("cycle is required")
    rubric = _validate_rubric(rubric_json)
    score_val = _validate_score(score)
    cur = conn.execute(
        """
        INSERT INTO performance_review(
            employee_id, cycle, reviewer_id, status, score,
            rubric_json, comments
        ) VALUES (?, ?, ?, 'draft', ?, ?, ?)
        """,
        (
            int(employee_id),
            str(cycle).strip(),
            int(reviewer_id) if reviewer_id else None,
            score_val,
            rubric,
            comments or "",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_review(
    conn: sqlite3.Connection, review_id: int, **fields: Any
) -> dict[str, Any]:
    review = get_review(conn, review_id)
    if review is None:
        raise ValueError(f"performance_review {review_id} not found")
    cols: list[str] = []
    values: list[Any] = []
    if "score" in fields:
        cols.append("score = ?")
        values.append(_validate_score(fields["score"]))
    if "rubric_json" in fields:
        cols.append("rubric_json = ?")
        values.append(_validate_rubric(fields["rubric_json"]))
    if "comments" in fields:
        cols.append("comments = ?")
        values.append(str(fields["comments"] or ""))
    if "cycle" in fields:
        cols.append("cycle = ?")
        values.append(str(fields["cycle"] or "").strip())
    if "reviewer_id" in fields:
        cols.append("reviewer_id = ?")
        rid = fields["reviewer_id"]
        values.append(int(rid) if rid else None)
    if not cols:
        return review
    cols.append("updated = ?")
    values.append(_now_ist())
    values.append(int(review_id))
    conn.execute(
        f"UPDATE performance_review SET {', '.join(cols)} WHERE id = ?", values
    )
    conn.commit()
    return get_review(conn, review_id) or {}


def transition(
    conn: sqlite3.Connection, review_id: int, target: str
) -> dict[str, Any]:
    """Move a review from one status to the next allowed state."""
    if target not in _VALID_STATUSES:
        raise ValueError(f"invalid status: {target!r}")
    review = get_review(conn, review_id)
    if review is None:
        raise ValueError(f"performance_review {review_id} not found")
    current = review.get("status") or "draft"
    expected = _TRANSITIONS.get(current)
    if expected != target:
        raise ValueError(
            f"invalid transition {current!r} -> {target!r}"
        )
    submitted_at = review.get("submitted_at") or ""
    if target == "submitted":
        submitted_at = _now_ist()
    conn.execute(
        """
        UPDATE performance_review
           SET status = ?, submitted_at = ?, updated = ?
         WHERE id = ?
        """,
        (target, submitted_at, _now_ist(), int(review_id)),
    )
    conn.commit()
    return get_review(conn, review_id) or {}


def delete_review(conn: sqlite3.Connection, review_id: int) -> None:
    conn.execute("DELETE FROM performance_review WHERE id = ?", (int(review_id),))
    conn.commit()


def _today_ist_date() -> str:
    try:
        from ..config import IST  # type: ignore[attr-defined]
        return datetime.now(IST).strftime("%Y-%m-%d")
    except (ImportError, AttributeError):
        return datetime.utcnow().strftime("%Y-%m-%d")


def _default_dashboard_range() -> tuple[str, str]:
    today = _today_ist_date()
    return today[:8] + "01", today


def _coerce_filter_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("date filters must use YYYY-MM-DD") from exc


def list_dashboard_rows(
    conn: sqlite3.Connection,
    *,
    date_from: Any = "",
    date_to: Any = "",
    status: Any = "",
) -> list[dict[str, Any]]:
    """Return performance rows filtered for the dashboard/export view."""
    date_from_s = _coerce_filter_date(date_from)
    date_to_s = _coerce_filter_date(date_to)
    if date_from_s and date_to_s and date_from_s > date_to_s:
        raise ValueError("date_from must be on or before date_to")

    status_s = str(status or "").strip().lower()
    if status_s and status_s not in _VALID_STATUSES:
        raise ValueError(f"invalid status filter: {status_s!r}")

    review_date_expr = (
        "COALESCE(NULLIF(substr(pr.submitted_at,1,10),''), substr(pr.created,1,10))"
    )
    rows = conn.execute(
        f"""
        SELECT pr.id, pr.employee_id, e.employee_code,
               e.full_name AS employee_name,
               d.name AS department, ro.title AS role,
               rv.full_name AS reviewer_name,
               pr.cycle, pr.status, pr.score, pr.comments,
               pr.submitted_at, pr.created,
               {review_date_expr} AS review_date
        FROM performance_review pr
        JOIN employee e ON e.id = pr.employee_id
        LEFT JOIN department d ON d.id = e.department_id
        LEFT JOIN role ro ON ro.id = e.role_id
        LEFT JOIN employee rv ON rv.id = pr.reviewer_id
        WHERE (? = '' OR date({review_date_expr}) >= date(?))
          AND (? = '' OR date({review_date_expr}) <= date(?))
          AND (? = '' OR pr.status = ?)
        ORDER BY review_date DESC, e.full_name COLLATE NOCASE, pr.id DESC
        """,
        (date_from_s, date_from_s, date_to_s, date_to_s, status_s, status_s),
    ).fetchall()
    return [_row_to_dict(r) or {} for r in rows]


def summarize_dashboard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute headline metrics + department rollups for dashboard cards."""
    scores: list[float] = []
    employees: set[int] = set()
    status_counts = {status: 0 for status in _VALID_STATUSES}
    departments: dict[str, list[float]] = {}
    top_rows: list[dict[str, Any]] = []

    for row in rows:
        employees.add(int(row.get("employee_id") or 0))
        status = str(row.get("status") or "draft")
        if status in status_counts:
            status_counts[status] += 1
        try:
            score = float(row.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        scores.append(score)
        dept = str(row.get("department") or "Unassigned")
        departments.setdefault(dept, []).append(score)
        top_rows.append({**row, "_score_float": score})

    department_rows = [
        {
            "department": dept,
            "reviews": len(vals),
            "avg_score": (sum(vals) / len(vals)) if vals else 0.0,
            "best_score": max(vals) if vals else 0.0,
        }
        for dept, vals in departments.items()
    ]
    department_rows.sort(key=lambda item: (-item["avg_score"], item["department"]))

    top_rows.sort(
        key=lambda item: (
            -item["_score_float"],
            str(item.get("review_date") or ""),
            str(item.get("employee_name") or ""),
        )
    )

    return {
        "total_reviews": len(rows),
        "employees_covered": len([emp for emp in employees if emp]),
        "avg_score": (sum(scores) / len(scores)) if scores else 0.0,
        "draft_count": status_counts["draft"],
        "submitted_count": status_counts["submitted"],
        "acknowledged_count": status_counts["acknowledged"],
        "department_rows": department_rows,
        "top_rows": top_rows[:5],
    }


def build_dashboard_csv(rows: list[dict[str, Any]]) -> str:
    """Serialize dashboard rows into a month-end friendly CSV export."""
    buf = io.StringIO()
    fieldnames = [
        "review_date",
        "employee_code",
        "employee_name",
        "department",
        "role",
        "reviewer_name",
        "cycle",
        "status",
        "score",
        "comments",
        "submitted_at",
        "created",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _employee_options(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT id, full_name FROM employee ORDER BY full_name COLLATE NOCASE"
    ).fetchall()
    return "".join(
        f"<option value=\"{int(r['id'])}\">{html.escape(r['full_name'])}</option>"
        for r in rows
    )


def _render_list(reviews: list[dict[str, Any]], emp_options: str) -> str:
    rows: list[str] = []
    for r in reviews:
        try:
            score = float(r.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        rows.append(
            "<tr>"
            f"<td><a href=\"/m/performance/{int(r['id'])}\">"
            f"{html.escape(r.get('employee_name') or '')}</a></td>"
            f"<td>{html.escape(r.get('cycle') or '')}</td>"
            f"<td>{html.escape(r.get('reviewer_name') or '')}</td>"
            f"<td>{html.escape(r.get('status') or 'draft')}</td>"
            f"<td>{score:.2f}</td>"
            "</tr>"
        )
    body = "".join(rows) or "<tr><td colspan=\"5\">No reviews yet.</td></tr>"

    return (
        "<div class=\"module-toolbar\">"
        f"<h1>{html.escape(LABEL)}</h1>"
        "<button onclick=\"openCreateForm()\">+ Add review</button>"
        "<a href=\"/m/performance/dashboard\" "
        "style=\"padding:7px 14px;border:1px solid var(--border);border-radius:6px;"
        "color:var(--dim);text-decoration:none;font-size:13px\">Dashboard</a>"
        "<input type=\"search\" placeholder=\"Search...\" "
        "oninput=\"filter(this.value)\">"
        "</div>"
        "<table class=\"data-table\">"
        "<thead><tr>"
        "<th>Employee</th><th>Cycle</th><th>Reviewer</th>"
        "<th>Status</th><th>Score</th>"
        "</tr></thead>"
        f"<tbody id=\"rows\">{body}</tbody>"
        "</table>"
        "<dialog id=\"create-dlg\">"
        "<form onsubmit=\"submitCreate(event)\">"
        f"<label>Employee <select name=\"employee_id\" required>{emp_options}</select></label>"
        "<label>Cycle <input name=\"cycle\" placeholder=\"2026-Q1\" required></label>"
        f"<label>Reviewer <select name=\"reviewer_id\">"
        f"<option value=\"\">—</option>{emp_options}</select></label>"
        "<label>Rubric JSON <textarea name=\"rubric_json\" rows=\"5\">"
        "{}</textarea></label>"
        "<label>Comments <textarea name=\"comments\"></textarea></label>"
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
        "var rj=(f.get('rubric_json')||'').trim()||'{}';"
        "try{JSON.parse(rj);}catch(err){hrkit.toast('Rubric JSON invalid', 'error');return;}"
        "var body={employee_id:Number(f.get('employee_id')),"
        "cycle:f.get('cycle'),"
        "reviewer_id:f.get('reviewer_id')?Number(f.get('reviewer_id')):null,"
        "rubric_json:rj,comments:f.get('comments')||''};"
        "var r=await fetch('/api/m/performance',{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});"
        "if(r.ok){location.reload();}else{var t=await r.text();hrkit.toast('Save failed: '+t, 'error');}}"
        "</script>"
    )


def _render_dashboard_page(
    *,
    rows: list[dict[str, Any]],
    date_from: str,
    date_to: str,
    status: str,
) -> str:
    summary = summarize_dashboard(rows)
    status_opts = ['<option value="">All statuses</option>']
    for value in _VALID_STATUSES:
        selected = " selected" if status == value else ""
        status_opts.append(
            f'<option value="{html.escape(value)}"{selected}>{html.escape(value.title())}</option>'
        )
    query = urlencode({
        "date_from": date_from,
        "date_to": date_to,
        "status": status,
    })
    cards = [
        ("Reviews", str(summary["total_reviews"])),
        ("Employees", str(summary["employees_covered"])),
        ("Average score", f'{summary["avg_score"]:.2f}'),
        ("Submitted", str(summary["submitted_count"] + summary["acknowledged_count"])),
    ]
    cards_html = "".join(
        "<div class=\"perf-card\">"
        f"<div class=\"perf-card-label\">{html.escape(label)}</div>"
        f"<div class=\"perf-card-value\">{html.escape(value)}</div>"
        "</div>"
        for label, value in cards
    )
    dept_rows = summary["department_rows"]
    dept_table = (
        "<table class=\"data-table\"><thead><tr><th>Department</th><th>Reviews</th>"
        "<th>Average score</th><th>Best score</th></tr></thead><tbody>"
        + "".join(
            "<tr>"
            f"<td>{html.escape(str(row['department']))}</td>"
            f"<td>{int(row['reviews'])}</td>"
            f"<td>{float(row['avg_score']):.2f}</td>"
            f"<td>{float(row['best_score']):.2f}</td>"
            "</tr>"
            for row in dept_rows
        )
        + "</tbody></table>"
    ) if dept_rows else '<div class="empty">No department rollups for this date range yet.</div>'

    top_rows = summary["top_rows"]
    top_table = (
        "<table class=\"data-table\"><thead><tr><th>Employee</th><th>Department</th>"
        "<th>Cycle</th><th>Status</th><th>Score</th></tr></thead><tbody>"
        + "".join(
            "<tr>"
            f"<td>{html.escape(str(row.get('employee_name') or ''))}</td>"
            f"<td>{html.escape(str(row.get('department') or ''))}</td>"
            f"<td>{html.escape(str(row.get('cycle') or ''))}</td>"
            f"<td>{html.escape(str(row.get('status') or ''))}</td>"
            f"<td>{float(row.get('_score_float') or 0):.2f}</td>"
            "</tr>"
            for row in top_rows
        )
        + "</tbody></table>"
    ) if top_rows else '<div class="empty">No scored reviews yet for this range.</div>'

    review_rows = (
        "<table class=\"data-table\"><thead><tr><th>Date</th><th>Employee</th>"
        "<th>Department</th><th>Reviewer</th><th>Cycle</th><th>Status</th><th>Score</th></tr></thead><tbody>"
        + "".join(
            "<tr>"
            f"<td>{html.escape(str(row.get('review_date') or ''))}</td>"
            f"<td><a href=\"/m/performance/{int(row['id'])}\">{html.escape(str(row.get('employee_name') or ''))}</a></td>"
            f"<td>{html.escape(str(row.get('department') or ''))}</td>"
            f"<td>{html.escape(str(row.get('reviewer_name') or ''))}</td>"
            f"<td>{html.escape(str(row.get('cycle') or ''))}</td>"
            f"<td>{html.escape(str(row.get('status') or ''))}</td>"
            f"<td>{float(row.get('score') or 0):.2f}</td>"
            "</tr>"
            for row in rows
        )
        + "</tbody></table>"
    ) if rows else '<div class="empty">No performance reviews match this date range.</div>'

    return (
        "<style>"
        ".perf-toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:18px}"
        ".perf-toolbar h1{margin:0;font-size:22px}"
        ".perf-toolbar .ghost{padding:7px 14px;border:1px solid var(--border);border-radius:6px;"
        "color:var(--dim);text-decoration:none;font-size:13px}"
        ".perf-toolbar .ghost:hover{border-color:var(--accent);color:var(--text)}"
        ".perf-filter{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;"
        "margin-bottom:18px;padding:14px;border:1px solid var(--border);border-radius:10px;background:var(--panel)}"
        ".perf-filter label{display:block;font-size:12px;color:var(--dim);margin-bottom:4px}"
        ".perf-filter input,.perf-filter select{width:100%;padding:8px 10px;border:1px solid var(--border);"
        "border-radius:6px;background:var(--bg);color:var(--text)}"
        ".perf-filter .actions{display:flex;gap:8px;align-items:end;flex-wrap:wrap}"
        ".perf-filter button{padding:8px 14px;border:none;border-radius:6px;background:var(--accent);color:#fff;cursor:pointer}"
        ".perf-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:18px}"
        ".perf-card{padding:14px;border:1px solid var(--border);border-radius:10px;background:var(--panel)}"
        ".perf-card-label{font-size:12px;color:var(--dim);margin-bottom:6px}"
        ".perf-card-value{font-size:26px;font-weight:700}"
        ".perf-section{margin-top:20px}"
        ".perf-section h2{margin:0 0 10px;font-size:15px}"
        ".perf-sub{color:var(--dim);font-size:13px}"
        "</style>"
        "<div class=\"perf-toolbar\">"
        "<h1>Performance dashboard</h1>"
        "<a class=\"ghost\" href=\"/m/performance\">Back to reviews</a>"
        f"<a class=\"ghost\" href=\"/api/m/performance/dashboard/export.csv?{html.escape(query)}\">Export CSV</a>"
        "</div>"
        "<div class=\"perf-sub\" style=\"margin-bottom:10px\">"
        "Choose a date range to generate a month-end performance view for HR and export it for your org."
        "</div>"
        "<form class=\"perf-filter\" method=\"GET\" action=\"/m/performance/dashboard\">"
        f"<div><label>From</label><input type=\"date\" name=\"date_from\" value=\"{html.escape(date_from)}\"></div>"
        f"<div><label>To</label><input type=\"date\" name=\"date_to\" value=\"{html.escape(date_to)}\"></div>"
        f"<div><label>Status</label><select name=\"status\">{''.join(status_opts)}</select></div>"
        "<div class=\"actions\">"
        "<button type=\"submit\">Build dashboard</button>"
        "<a class=\"ghost\" href=\"/m/performance/dashboard\">Reset</a>"
        "</div>"
        "</form>"
        f"<div class=\"perf-cards\">{cards_html}</div>"
        "<div class=\"perf-section\"><h2>Department summary</h2>"
        "<div class=\"perf-sub\" style=\"margin-bottom:8px\">Average score and volume by department for the selected range.</div>"
        f"{dept_table}</div>"
        "<div class=\"perf-section\"><h2>Top reviews</h2>"
        "<div class=\"perf-sub\" style=\"margin-bottom:8px\">Highest scores in the selected range.</div>"
        f"{top_table}</div>"
        "<div class=\"perf-section\"><h2>Review log</h2>"
        "<div class=\"perf-sub\" style=\"margin-bottom:8px\">Detailed records that will be exported.</div>"
        f"{review_rows}</div>"
    )


def _render_detail(review: dict[str, Any]) -> str:
    rid = int(review["id"])
    try:
        rubric = json.loads(review.get("rubric_json") or "{}")
    except (TypeError, ValueError):
        rubric = {}
    try:
        score = float(review.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    pretty = json.dumps(rubric, indent=2, sort_keys=True)

    status = review.get("status") or "draft"
    next_btn = ""
    target = _TRANSITIONS.get(status)
    if target:
        next_btn = (
            f"<button onclick=\"advance({rid},'{target}')\">"
            f"Move to {target}</button>"
        )

    return (
        "<div class=\"module-toolbar\">"
        f"<h1>Review · {html.escape(review.get('employee_name') or '')}</h1>"
        f"{next_btn}"
        "<a href=\"/m/performance\">Back</a>"
        "</div>"
        "<table class=\"data-table\">"
        "<tbody>"
        f"<tr><th>Employee</th><td>{html.escape(review.get('employee_name') or '')}</td></tr>"
        f"<tr><th>Cycle</th><td>{html.escape(review.get('cycle') or '')}</td></tr>"
        f"<tr><th>Reviewer</th><td>{html.escape(review.get('reviewer_name') or '')}</td></tr>"
        f"<tr><th>Status</th><td>{html.escape(status)}</td></tr>"
        f"<tr><th>Score</th><td>{score:.2f}</td></tr>"
        f"<tr><th>Comments</th><td>{html.escape(review.get('comments') or '')}</td></tr>"
        f"<tr><th>Submitted at</th><td>{html.escape(review.get('submitted_at') or '')}</td></tr>"
        "</tbody>"
        "</table>"
        f"<h2>Rubric</h2><pre>{html.escape(pretty)}</pre>"
        "<script>"
        "async function advance(id,target){"
        "var r=await fetch('/api/m/performance/'+id+'/'+target,{method:'POST'});"
        "if(r.ok){location.reload();}else{var t=await r.text();hrkit.toast('Failed: '+t, 'error');}}"
        "</script>"
    )


def _render_page(title: str, body: str) -> str:
    try:
        from ..templates import render_module_page  # type: ignore[attr-defined]
        return render_module_page(title=title, nav_active=NAME, body_html=body)
    except (ImportError, AttributeError):
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
    for attr in ("conn", "_conn", "db"):
        c = getattr(handler, attr, None)
        if c is not None:
            return c
    raise RuntimeError("handler has no SQLite connection attribute")


def list_view(handler) -> None:
    conn = _conn(handler)
    reviews = list_reviews(conn)
    emp_options = _employee_options(conn)
    body = _render_list(reviews, emp_options)
    handler._html(200, _render_page(f"{LABEL} · {app_name()}", body))


def dashboard_view(handler) -> None:
    conn = _conn(handler)
    parsed = urlparse(getattr(handler, "path", ""))
    query = parse_qs(parsed.query)
    date_from_q = str(query.get("date_from", [""])[0] or "").strip()
    date_to_q = str(query.get("date_to", [""])[0] or "").strip()
    status_q = str(query.get("status", [""])[0] or "").strip().lower()
    if not date_from_q and not date_to_q and not status_q:
        date_from_q, date_to_q = _default_dashboard_range()
    try:
        rows = list_dashboard_rows(
            conn,
            date_from=date_from_q,
            date_to=date_to_q,
            status=status_q,
        )
    except ValueError as exc:
        handler._html(400, _render_page(
            f"{LABEL} dashboard · {app_name()}",
            f'<div class="empty">{html.escape(str(exc))}</div>',
        ))
        return
    body = _render_dashboard_page(
        rows=rows,
        date_from=date_from_q,
        date_to=date_to_q,
        status=status_q,
    )
    handler._html(200, _render_page(f"{LABEL} dashboard · {app_name()}", body))


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
    review = get_review(conn, int(item_id))
    if review is None:
        handler._html(404, render_detail_page(
            title="Not found",
            nav_active=NAME,
            subtitle=f"No performance review with id {int(item_id)}",
        ))
        return

    try:
        rubric = json.loads(review.get("rubric_json") or "{}")
    except (TypeError, ValueError):
        rubric = {}
    try:
        score = float(review.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    pretty = json.dumps(rubric, indent=2, sort_keys=True)
    status = review.get("status") or "draft"

    fields: list[tuple[str, Any]] = [
        ("Employee", review.get("employee_name")),
        ("Cycle", review.get("cycle")),
        ("Reviewer", review.get("reviewer_name")),
        ("Status", status),
        ("Score", f"{score:.2f}"),
        ("Comments", review.get("comments")),
        ("Submitted at", _fmt_dt(review.get("submitted_at"))),
        ("Created", _fmt_dt(review.get("created"))),
        ("Updated", _fmt_dt(review.get("updated"))),
    ]

    rid = int(item_id)
    actions_html = ""
    if status == "draft":
        actions_html = (
            f"<button onclick=\"fetch('/api/m/performance/{rid}/submitted',"
            f"{{method:'POST'}}).then(r=>r.ok?location.reload():"
            f"r.text().then(t=>hrkit.toast('Submit failed: '+t, 'error')))\""
            f">Submit</button>"
        )
    elif status == "submitted":
        actions_html = (
            f"<button onclick=\"fetch('/api/m/performance/{rid}/acknowledged',"
            f"{{method:'POST'}}).then(r=>r.ok?location.reload():"
            f"r.text().then(t=>hrkit.toast('Acknowledge failed: '+t, 'error')))\""
            f">Acknowledge</button>"
        )

    rubric_body = f"""
<style>
  .rubric-editor textarea{{width:100%;min-height:220px;padding:10px 12px;
    background:var(--bg);color:var(--text);border:1px solid var(--border);
    border-radius:6px;font-family:'JetBrains Mono','Menlo',monospace;
    font-size:12.5px;line-height:1.5;resize:vertical}}
  .rubric-editor .rubric-actions{{display:flex;justify-content:flex-end;gap:8px;
    margin-top:8px;align-items:center}}
  .rubric-editor .hint{{margin-right:auto;color:var(--dim);font-size:12px}}
  .rubric-editor button{{padding:7px 14px;border-radius:6px;background:var(--accent);
    color:#fff;border:none;cursor:pointer;font-size:12px}}
</style>
<div class="rubric-editor">
  <textarea id="rubric-json" spellcheck="false">{html.escape(pretty)}</textarea>
  <div class="rubric-actions">
    <span class="hint">Edit the scoring rubric as JSON. Invalid JSON will not be saved.</span>
    <button onclick="saveRubric({rid})">Save rubric</button>
  </div>
</div>
<script>
async function saveRubric(id) {{
  const el = document.getElementById('rubric-json');
  const raw = el.value.trim() || '{{}}';
  try {{ JSON.parse(raw); }}
  catch (err) {{
    hrkit.toast('Rubric JSON invalid: ' + err.message, 'error');
    return;
  }}
  const r = await fetch('/api/m/performance/' + id, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{rubric_json: raw}}),
  }});
  if (r.ok) {{
    hrkit.toast('Rubric saved', 'success');
    location.reload();
  }} else {{
    hrkit.toast('Save failed: ' + await r.text(), 'error');
  }}
}}
</script>
"""
    related_html = detail_section(title="Rubric", body_html=rubric_body)

    page = render_detail_page(
        title=f"Review · {review.get('employee_name') or ''}",
        nav_active=NAME,
        subtitle=f"{review.get('cycle') or ''} · status {status}",
        fields=fields,
        actions_html=actions_html,
        related_html=related_html,
        item_id=rid,
        api_path="/api/m/performance",
        delete_redirect="/m/performance",
        exclude_edit_fields={
            "employee", "reviewer", "status", "submitted_at", "created", "updated",
        },
    )
    handler._html(200, page)


def detail_api_json(handler, item_id: int) -> None:
    """Return raw performance_review row as JSON."""
    review = get_review(_conn(handler), int(item_id))
    if review is None:
        handler._json({"error": "not found"}, code=404)
        return
    handler._json(review)


def dashboard_export_api(handler) -> None:
    conn = _conn(handler)
    parsed = urlparse(getattr(handler, "path", ""))
    query = parse_qs(parsed.query)
    date_from_q = str(query.get("date_from", [""])[0] or "").strip()
    date_to_q = str(query.get("date_to", [""])[0] or "").strip()
    status_q = str(query.get("status", [""])[0] or "").strip().lower()
    if not date_from_q and not date_to_q and not status_q:
        date_from_q, date_to_q = _default_dashboard_range()
    try:
        rows = list_dashboard_rows(
            conn,
            date_from=date_from_q,
            date_to=date_to_q,
            status=status_q,
        )
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=400)
        return

    body = build_dashboard_csv(rows).encode("utf-8")
    label_from = date_from_q or "all"
    label_to = date_to_q or "all"
    filename = f"performance-dashboard-{label_from}-to-{label_to}.csv"
    handler.send_response(200)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionError):
        return


def create_api(handler) -> None:
    conn = _conn(handler)
    payload = handler._read_json() or {}
    try:
        review_id = create_review(
            conn,
            employee_id=int(payload.get("employee_id") or 0),
            cycle=str(payload.get("cycle") or ""),
            reviewer_id=payload.get("reviewer_id"),
            rubric_json=payload.get("rubric_json"),
            comments=str(payload.get("comments") or ""),
            score=payload.get("score", 0),
        )
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"id": review_id, "status": "draft"}, code=201)


def update_api(handler, item_id: int) -> None:
    conn = _conn(handler)
    payload = handler._read_json() or {}
    try:
        updated = update_review(conn, int(item_id), **payload)
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"id": int(item_id), "status": updated.get("status")})


def delete_api(handler, item_id: int) -> None:
    conn = _conn(handler)
    delete_review(conn, int(item_id))
    handler._json({"id": int(item_id), "deleted": True})


def submit_api(handler, item_id: int) -> None:
    conn = _conn(handler)
    try:
        review = transition(conn, int(item_id), "submitted")
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"id": int(item_id), "status": review.get("status")})


def acknowledge_api(handler, item_id: int) -> None:
    conn = _conn(handler)
    try:
        review = transition(conn, int(item_id), "acknowledged")
    except ValueError as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"id": int(item_id), "status": review.get("status")})


ROUTES = {
    "GET": [
        (r"^/api/m/performance/dashboard/export\.csv$", dashboard_export_api),
        (r"^/m/performance/dashboard/?$", dashboard_view),
        (r"^/api/m/performance/(\d+)/?$", detail_api_json),
        (r"^/m/performance/?$", list_view),
        (r"^/m/performance/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/performance/?$", create_api),
        (r"^/api/m/performance/(\d+)/submitted/?$", submit_api),
        (r"^/api/m/performance/(\d+)/acknowledged/?$", acknowledge_api),
        (r"^/api/m/performance/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/performance/(\d+)/?$", delete_api),
    ],
}


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------

def _add_create_args(p) -> None:
    p.add_argument("--employee-id", type=int, required=True)
    p.add_argument("--cycle", required=True)
    p.add_argument("--reviewer-id", type=int, default=None)
    p.add_argument("--rubric-json", default="{}")
    p.add_argument("--comments", default="")
    p.add_argument("--score", type=float, default=0.0)


def _handle_create(args, conn) -> int:
    try:
        review_id = create_review(
            conn,
            employee_id=args.employee_id,
            cycle=args.cycle,
            reviewer_id=args.reviewer_id,
            rubric_json=args.rubric_json,
            comments=args.comments,
            score=args.score,
        )
    except ValueError as exc:
        log.error("performance-add: %s", exc)
        return 2
    log.info("performance_review created id=%s", review_id)
    return 0


def _add_id_arg(p) -> None:
    p.add_argument("--review-id", type=int, required=True)


def _handle_submit(args, conn) -> int:
    try:
        review = transition(conn, args.review_id, "submitted")
    except ValueError as exc:
        log.error("performance-submit: %s", exc)
        return 2
    log.info("review id=%s now status=%s", args.review_id, review.get("status"))
    return 0


def _handle_acknowledge(args, conn) -> int:
    try:
        review = transition(conn, args.review_id, "acknowledged")
    except ValueError as exc:
        log.error("performance-acknowledge: %s", exc)
        return 2
    log.info("review id=%s now status=%s", args.review_id, review.get("status"))
    return 0


def _handle_list(args, conn) -> int:
    for r in list_reviews(conn):
        log.info(
            "%s\t%s\t%s\t%s\t%s",
            r.get("id"), r.get("employee_name"),
            r.get("cycle"), r.get("status"), r.get("score"),
        )
    return 0


CLI = [
    ("performance-add", _add_create_args, _handle_create),
    ("performance-submit", _add_id_arg, _handle_submit),
    ("performance-acknowledge", _add_id_arg, _handle_acknowledge),
    ("performance-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "hr",
    "requires": ["employee"],
    "description": "Review cycles, rubric scoring, manager comments, status tracking.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
