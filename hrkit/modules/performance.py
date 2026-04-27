"""Performance review module.

A performance_review row tracks one review cycle for one employee. The
status flow is draft -> submitted -> acknowledged, each transition exposed
as a POST endpoint and a CLI subcommand.
"""
from __future__ import annotations

import html
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

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
        "try{JSON.parse(rj);}catch(err){alert('Rubric JSON invalid');return;}"
        "var body={employee_id:Number(f.get('employee_id')),"
        "cycle:f.get('cycle'),"
        "reviewer_id:f.get('reviewer_id')?Number(f.get('reviewer_id')):null,"
        "rubric_json:rj,comments:f.get('comments')||''};"
        "var r=await fetch('/api/m/performance',{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});"
        "if(r.ok){location.reload();}else{var t=await r.text();alert('Save failed: '+t);}}"
        "</script>"
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
        "if(r.ok){location.reload();}else{var t=await r.text();alert('Failed: '+t);}}"
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
            f"r.text().then(t=>alert('Submit failed: '+t)))\""
            f">Submit</button>"
        )
    elif status == "submitted":
        actions_html = (
            f"<button onclick=\"fetch('/api/m/performance/{rid}/acknowledged',"
            f"{{method:'POST'}}).then(r=>r.ok?location.reload():"
            f"r.text().then(t=>alert('Acknowledge failed: '+t)))\""
            f">Acknowledge</button>"
        )

    rubric_body = f"<pre>{html.escape(pretty)}</pre>"
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
    )
    handler._html(200, page)


def detail_api_json(handler, item_id: int) -> None:
    """Return raw performance_review row as JSON."""
    review = get_review(_conn(handler), int(item_id))
    if review is None:
        handler._json({"error": "not found"}, code=404)
        return
    handler._json(review)


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
