"""Approval module — generic multi-level approval workflow.

Owns ``approval`` (migration 002). Other modules (leave, expense,
salary_advance, promotion, ...) call :func:`request_approvals` to record
who needs to approve, then :func:`respond` updates each approver's verdict.

A request is fully approved when all levels for that ``(request_type,
request_id)`` are 'approved'; rejected on any 'rejected'.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Iterable

log = logging.getLogger(__name__)

NAME = "approval"
LABEL = "Approvals"
ICON = "check-square"

LIST_COLUMNS = ("request_type", "request_id", "level", "approver", "status", "responded_at")
ALLOWED_STATUS = ("pending", "approved", "rejected", "skipped")


def ensure_schema(conn): return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def request_approvals(conn: sqlite3.Connection, *, request_type: str,
                      request_id: int, approver_ids: Iterable[int]) -> list[int]:
    """Record an N-level approval chain. Returns inserted row ids in level order.

    No-op (returns ``[]``) when ``approver_ids`` is empty — useful when the
    employee has no manager and no HR approver is configured, so callers
    can wire this in unconditionally.
    """
    out: list[int] = []
    seen: set[int] = set()
    for level, approver_id in enumerate(approver_ids, start=1):
        approver_id = int(approver_id)
        if approver_id in seen:
            continue
        seen.add(approver_id)
        cur = conn.execute("""
            INSERT INTO approval (request_type, request_id, level, approver_id, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (request_type, int(request_id), int(level), approver_id))
        out.append(int(cur.lastrowid))
    conn.commit()
    return out


def default_approver_chain(conn: sqlite3.Connection, employee_id: int,
                           *, include_hr: bool = True) -> list[int]:
    """Resolve the default approver chain for an employee.

    Order: direct manager → HR approver (from settings ``HR_APPROVER_ID``).
    Each id is included only once and is never the employee themselves.
    Returns an empty list if neither is resolvable.
    """
    chain: list[int] = []
    seen: set[int] = {int(employee_id)}
    row = conn.execute(
        "SELECT manager_id FROM employee WHERE id = ?", (int(employee_id),)
    ).fetchone()
    if row and row["manager_id"] not in (None, ""):
        mgr = int(row["manager_id"])
        if mgr not in seen:
            chain.append(mgr); seen.add(mgr)
    if include_hr:
        try:
            hr_row = conn.execute(
                "SELECT value FROM settings WHERE key = 'HR_APPROVER_ID'"
            ).fetchone()
        except sqlite3.Error:
            hr_row = None
        if hr_row and hr_row["value"]:
            try:
                hr_id = int(hr_row["value"])
            except (TypeError, ValueError):
                hr_id = 0
            if hr_id and hr_id not in seen:
                chain.append(hr_id); seen.add(hr_id)
    return chain


def reflect_request_outcome(conn: sqlite3.Connection, *,
                            request_type: str, request_id: int,
                            outcome: str, comments: str = "") -> None:
    """Mirror a domain status flip ('approved' / 'rejected') onto every
    pending approval row for ``(request_type, request_id)``.

    Idempotent — already-decided approval rows are left alone. This lets
    leave/expense/advance modules keep their own bespoke status fields
    while still feeding the cross-module approval queue.
    """
    if outcome not in ("approved", "rejected"):
        return
    conn.execute("""
        UPDATE approval
        SET status = ?,
            responded_at = strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'),
            comments = ?
        WHERE request_type = ? AND request_id = ? AND status = 'pending'
    """, (outcome, comments or "", request_type, int(request_id)))
    conn.commit()


def respond(conn: sqlite3.Connection, approval_id: int, *,
            status: str, comments: str = "") -> None:
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    conn.execute("""
        UPDATE approval SET status = ?, comments = ?,
          responded_at = strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')
        WHERE id = ?
    """, (status, comments or "", int(approval_id)))
    conn.commit()


def request_status(conn: sqlite3.Connection, request_type: str,
                   request_id: int) -> dict[str, Any]:
    """Roll up the approval rows for a (type, id) into a single verdict."""
    rows = conn.execute(
        "SELECT level, status FROM approval WHERE request_type = ? AND request_id = ? "
        "ORDER BY level",
        (request_type, int(request_id))).fetchall()
    if not rows:
        return {"verdict": "no_approvals", "levels": []}
    levels = [{"level": r["level"], "status": r["status"]} for r in rows]
    if any(r["status"] == "rejected" for r in rows):
        return {"verdict": "rejected", "levels": levels}
    if all(r["status"] in ("approved", "skipped") for r in rows):
        return {"verdict": "approved", "levels": levels}
    return {"verdict": "pending", "levels": levels}


def list_rows(conn):
    cur = conn.execute("""
        SELECT a.*, e.full_name AS approver
        FROM approval a
        LEFT JOIN employee e ON e.id = a.approver_id
        ORDER BY a.created DESC, a.id DESC LIMIT 500
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("""
        SELECT a.*, e.full_name AS approver
        FROM approval a
        LEFT JOIN employee e ON e.id = a.approver_id
        WHERE a.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def _render_list_html(rows) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/approval/{row["id"]}\'">'
            f'{cells}<td>'
            f'<button onclick="event.stopPropagation();respond({row["id"]},\'approved\')">✓</button> '
            f'<button onclick="event.stopPropagation();respond({row["id"]},\'rejected\')">×</button>'
            f'</td></tr>')
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <span style="color:var(--dim);font-size:13px;margin-left:auto">
    Cross-module approval queue (leaves, expenses, advances, promotions, ...).</span>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows) or '<tr><td colspan="7" class="empty">No approvals queued.</td></tr>'}</tbody>
</table>
<script>
function filter(q) {{
  q = (q || '').toLowerCase();
  document.querySelectorAll('#rows tr').forEach(tr => {{
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
async function respond(id, verdict) {{
  const comments = verdict === 'rejected' ? prompt('Reason for rejection?', '') : '';
  if (verdict === 'rejected' && comments === null) return;
  const r = await fetch('/api/m/approval/' + id + '/respond', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{status: verdict, comments: comments || ''}})
  }});
  if (r.ok) location.reload(); else alert('Failed: ' + await r.text());
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
                      subtitle=f"No approval with id {int(item_id)}"))
        return
    fields = [
        ("Request type", row.get("request_type")),
        ("Request id", row.get("request_id")),
        ("Level", row.get("level")),
        ("Approver", row.get("approver")),
        ("Status", row.get("status")),
        ("Responded at", row.get("responded_at")),
        ("Comments", row.get("comments")),
        ("Created", row.get("created")),
    ]
    handler._html(200, render_detail_page(
        title=f"{row.get('request_type', '?')} #{row.get('request_id', '?')}",
        nav_active=NAME, subtitle=f"level {row.get('level')}",
        fields=fields, item_id=int(item_id),
    ))


def respond_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        respond(conn, int(item_id),
                status=payload.get("status") or "approved",
                comments=payload.get("comments") or "")
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True})


ROUTES = {
    "GET": [
        (r"^/api/m/approval/(\d+)/?$", detail_api_json),
        (r"^/m/approval/?$", list_view),
        (r"^/m/approval/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/approval/(\d+)/respond/?$", respond_api),
    ],
    "DELETE": [],
}


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s/#%s\tL%s\t%s",
                 row["id"], row["status"], row["request_type"],
                 row["request_id"], row["level"], row.get("approver") or "")
    return 0


CLI = [
    ("approval-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "operations",
    "requires": ["employee"],
    "description": "Generic multi-level approval workflow used by leave / expense / advance / promotion.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
