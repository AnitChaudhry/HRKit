"""Recruitment HR module.

Owns CRUD over the ``recruitment_candidate`` table created by migration
``001_full_hr_schema.sql``. The legacy folder-native hiring kanban remains
intact — Agent 4's ``hiring_migrator`` imports those folder rows into this
DB-primary table on first run. This module just reads/writes the new table
and resolves ``position_folder_id`` against the existing ``folders`` table
for human-friendly position labels.

Follows the registry contract from AGENTS_SPEC.md Section 1: a single
top-level ``MODULE`` dict, no top-level side effects, stdlib only.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import date
from typing import Any

log = logging.getLogger(__name__)

NAME = "recruitment"
LABEL = "Recruitment"
ICON = "user-plus"
GMAIL_FETCH_ACTION = "GMAIL_FETCH_EMAILS"

# Columns shown in the list view (in order).
LIST_COLUMNS = (
    "name",
    "email",
    "position",
    "status",
    "score",
    "applied_at",
)

# Allowed values for recruitment_candidate.status (mirrors CHECK in 001).
ALLOWED_STATUS = (
    "applied",
    "screening",
    "interview",
    "offer",
    "hired",
    "rejected",
)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def ensure_schema(conn: sqlite3.Connection) -> None:
    """No-op. The ``recruitment_candidate`` table is created by migration 001."""
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _has_folders_table(conn: sqlite3.Connection) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='folders'"
    )
    return cur.fetchone() is not None


def list_rows(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return candidates joined with the position folder name.

    Optionally filter by ``status``. Newest applications first.
    """
    join = (
        "LEFT JOIN folders f ON f.id = c.position_folder_id"
        if _has_folders_table(conn)
        else ""
    )
    position_select = "f.name AS position" if _has_folders_table(conn) else "NULL AS position"
    where = ""
    params: tuple[Any, ...] = ()
    if status:
        if status not in ALLOWED_STATUS:
            raise ValueError(f"status must be one of {ALLOWED_STATUS}")
        where = "WHERE c.status = ?"
        params = (status,)
    sql = f"""
        SELECT c.id, c.name, c.email, c.phone, c.source, c.status, c.score,
               c.recommendation, c.applied_at, c.evaluated_at,
               c.resume_path, c.position_folder_id,
               {position_select}
        FROM recruitment_candidate c
        {join}
        {where}
        ORDER BY c.applied_at DESC, c.id DESC
    """
    cur = conn.execute(sql, params)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    join = (
        "LEFT JOIN folders f ON f.id = c.position_folder_id"
        if _has_folders_table(conn)
        else ""
    )
    position_select = "f.name AS position" if _has_folders_table(conn) else "NULL AS position"
    cur = conn.execute(
        f"""
        SELECT c.*, {position_select}
        FROM recruitment_candidate c
        {join}
        WHERE c.id = ?
        """,
        (item_id,),
    )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_positions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List position folders (for the create-form select)."""
    if not _has_folders_table(conn):
        return []
    cur = conn.execute(
        "SELECT id, name FROM folders WHERE type = 'position' ORDER BY name"
    )
    return [{"id": r["id"], "label": r["name"]} for r in cur.fetchall()]


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    """Insert a candidate row. Returns the new id."""
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    status = (data.get("status") or "applied").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")

    applied_at = (data.get("applied_at") or "").strip() or date.today().isoformat()

    metadata = data.get("metadata_json")
    if isinstance(metadata, dict):
        metadata = json.dumps(metadata)
    elif metadata is None:
        metadata = "{}"

    position_folder_id = data.get("position_folder_id")
    if position_folder_id in ("", None):
        position_folder_id = None
    else:
        position_folder_id = int(position_folder_id)

    score = data.get("score")
    score = int(score) if score not in (None, "") else 0

    cur = conn.execute(
        """
        INSERT INTO recruitment_candidate (
            position_folder_id, name, email, phone, source, status,
            score, recommendation, applied_at, evaluated_at,
            resume_path, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            position_folder_id,
            name,
            (data.get("email") or "").strip(),
            (data.get("phone") or "").strip(),
            (data.get("source") or "").strip(),
            status,
            score,
            (data.get("recommendation") or "").strip(),
            applied_at,
            (data.get("evaluated_at") or "").strip(),
            (data.get("resume_path") or "").strip(),
            metadata,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    """Patch only the fields supplied."""
    fields: list[str] = []
    values: list[Any] = []
    simple = (
        "name", "email", "phone", "source", "status", "score",
        "recommendation", "applied_at", "evaluated_at", "resume_path",
        "position_folder_id",
    )
    for key in simple:
        if key in data:
            value = data[key]
            if key == "status" and value not in ALLOWED_STATUS:
                raise ValueError(f"status must be one of {ALLOWED_STATUS}")
            if key == "position_folder_id" and value in ("", None):
                value = None
            elif key == "position_folder_id":
                value = int(value)
            fields.append(f"{key} = ?")
            values.append(value)
    if "metadata_json" in data:
        meta = data["metadata_json"]
        if isinstance(meta, dict):
            meta = json.dumps(meta)
        fields.append("metadata_json = ?")
        values.append(meta)
    if not fields:
        return
    fields.append(
        "updated = strftime('%Y-%m-%dT%H:%M:%S','now','+05:30')"
    )
    values.append(item_id)
    conn.execute(
        f"UPDATE recruitment_candidate SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()


def move_status(conn: sqlite3.Connection, item_id: int, status: str) -> dict[str, Any]:
    """Transition a candidate to ``status``. Returns the updated row.

    Raises ``ValueError`` for invalid status, ``LookupError`` if not found.
    """
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    row = get_row(conn, item_id)
    if not row:
        raise LookupError(f"candidate {item_id} not found")
    update_row(conn, item_id, {"status": status})
    return get_row(conn, item_id) or {}


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM recruitment_candidate WHERE id = ?", (item_id,))
    conn.commit()


def promote_to_employee(conn: sqlite3.Connection, item_id: int) -> int:
    """Create an ``employee`` row from a hired candidate. Returns new employee id.

    The candidate must exist and be in ``hired`` status. The new employee
    inherits ``full_name`` from candidate.name and ``email`` from
    candidate.email; ``status='active'`` and ``hire_date`` is today (IST date).
    A unique ``employee_code`` is auto-generated as ``EMP{employee_id:04d}``.
    """
    row = get_row(conn, item_id)
    if not row:
        raise LookupError(f"candidate {item_id} not found")
    if row.get("status") != "hired":
        raise ValueError("candidate must be in 'hired' status to promote")

    full_name = (row.get("name") or "").strip()
    email = (row.get("email") or "").strip()
    if not full_name:
        raise ValueError("candidate name is empty; cannot promote")
    if not email:
        raise ValueError("candidate email is empty; cannot promote")

    hire_date = date.today().isoformat()

    # Reserve an id by inserting with a placeholder code, then patch the code
    # to ``EMP{id:04d}`` so it's both unique and predictable.
    cur = conn.execute(
        """
        INSERT INTO employee (
            employee_code, full_name, email, hire_date, status
        ) VALUES (?, ?, ?, ?, 'active')
        """,
        (f"PENDING-{item_id}-{email}", full_name, email, hire_date),
    )
    new_id = int(cur.lastrowid)
    conn.execute(
        "UPDATE employee SET employee_code = ? WHERE id = ?",
        (f"EMP{new_id:04d}", new_id),
    )
    conn.commit()
    log.info("recruitment_promoted candidate_id=%s employee_id=%s", item_id, new_id)
    return new_id


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
                      positions: list[dict[str, Any]],
                      active_status: str | None) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}">{cells}'
            f'<td><a href="/m/recruitment/{row["id"]}">Open</a></td></tr>'
        )
    pos_opts = "".join(
        f'<option value="{p["id"]}">{_esc(p["label"])}</option>' for p in positions
    )
    status_filter_opts = "".join(
        f'<option value="{s}"{" selected" if s == active_status else ""}>{s}</option>'
        for s in ALLOWED_STATUS
    )
    today_iso = date.today().isoformat()
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Candidate</button>
  <button onclick="pullFromGmail()" title="Fetch unread emails as candidates via Composio Gmail">Pull from Gmail</button>
  <select onchange="filterStatus(this.value)">
    <option value="">All statuses</option>
    {status_filter_opts}
  </select>
  <input type="search" placeholder="Search..." oninput="filterText(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Name*<input name="name" required></label>
    <label>Email<input name="email" type="email"></label>
    <label>Phone<input name="phone"></label>
    <label>Source<input name="source" placeholder="referral / linkedin / ..."></label>
    <label>Position<select name="position_folder_id"><option value="">--</option>{pos_opts}</select></label>
    <label>Applied at<input name="applied_at" type="date" value="{today_iso}"></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Save</button>
    </menu>
  </form>
</dialog>
<script>
function filterText(q) {{
  q = (q || '').toLowerCase();
  document.querySelectorAll('#rows tr').forEach(tr => {{
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
function filterStatus(s) {{
  const url = new URL(window.location.href);
  if (s) url.searchParams.set('status', s); else url.searchParams.delete('status');
  window.location.href = url.toString();
}}
async function submitCreate(ev) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const payload = Object.fromEntries(fd.entries());
  if (payload.position_folder_id === '') delete payload.position_folder_id;
  const r = await fetch('/api/m/recruitment', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function pullFromGmail() {{
  const q = prompt('Gmail search query (Enter for default = label:UNREAD newer_than:14d):');
  if (q === null) return;
  const body = q.trim() ? {{query: q.trim()}} : {{}};
  const r = await fetch('/api/m/recruitment/pull-emails', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body),
  }});
  const data = await r.json().catch(() => ({{ok: false, error: 'Bad response'}}));
  if (!r.ok || !data.ok) {{
    alert('Pull failed: ' + (data.error || ('HTTP ' + r.status)));
    return;
  }}
  alert('Fetched ' + data.fetched + ' message(s); created ' +
        (data.created_candidate_ids || []).length + ' candidate(s); skipped ' +
        (data.skipped_existing || []).length + ' duplicate(s).');
  location.reload();
}}
</script>
"""


def _render_detail_html(row: dict[str, Any]) -> str:
    rows: list[str] = []
    fields = [
        ("Name", row.get("name")),
        ("Email", row.get("email")),
        ("Phone", row.get("phone")),
        ("Source", row.get("source")),
        ("Position", row.get("position")),
        ("Status", row.get("status")),
        ("Score", row.get("score")),
        ("Applied at", row.get("applied_at")),
        ("Evaluated at", row.get("evaluated_at")),
    ]
    for label, value in fields:
        rows.append(
            f"<tr><th>{_esc(label)}</th><td>{_esc(value)}</td></tr>"
        )
    resume = row.get("resume_path") or ""
    if resume:
        rows.append(
            f'<tr><th>Resume</th><td><a href="{_esc(resume)}" target="_blank">'
            f'{_esc(resume)}</a></td></tr>'
        )
    if row.get("recommendation"):
        rows.append(
            f"<tr><th>Recommendation</th><td>{_esc(row.get('recommendation'))}</td></tr>"
        )
    status_buttons = "".join(
        f'<button onclick="moveStatus(\'{s}\')">Move to {s}</button> '
        for s in ALLOWED_STATUS
        if s != row.get("status")
    )
    promote_btn = ""
    if row.get("status") == "hired":
        promote_btn = (
            '<div class="promote-hint">'
            '<p>Candidate hired. Promote to an employee record:</p>'
            '<button onclick="promote()">Convert to employee</button>'
            "</div>"
        )
    item_id = row["id"]
    return f"""
<div class="module-toolbar">
  <h1>{_esc(row.get("name"))}</h1>
  <a href="/m/recruitment">&larr; Back</a>
</div>
<table class="data-table">
  <tbody>{''.join(rows)}</tbody>
</table>
<div class="status-actions">
  {status_buttons}
</div>
{promote_btn}
<script>
async function moveStatus(s) {{
  const r = await fetch('/api/m/recruitment/{item_id}/move', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{status: s}}),
  }});
  if (r.ok) location.reload(); else alert('Move failed: ' + await r.text());
}}
async function promote() {{
  if (!confirm('Convert this candidate to an employee?')) return;
  const r = await fetch('/api/m/recruitment/{item_id}/promote', {{method: 'POST'}});
  if (r.ok) {{
    const data = await r.json();
    alert('Created employee #' + data.employee_id);
    window.location.href = '/m/employee/' + data.employee_id;
  }} else {{
    alert('Promote failed: ' + await r.text());
  }}
}}
</script>
"""


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------
def _query_param(handler, key: str) -> str | None:
    """Pull a single query-string value from the handler's URL."""
    from urllib.parse import urlparse, parse_qs

    raw = getattr(handler, "path", "") or ""
    qs = parse_qs(urlparse(raw).query)
    values = qs.get(key)
    return values[0] if values else None


def list_view(handler) -> None:
    from hrkit.templates import render_module_page  # late import

    conn = handler.server.conn  # type: ignore[attr-defined]
    status = _query_param(handler, "status")
    if status and status not in ALLOWED_STATUS:
        status = None
    rows = list_rows(conn, status=status)
    positions = list_positions(conn)
    body = _render_list_html(rows, positions, status)
    handler._html(200, render_module_page(title=LABEL, nav_active=NAME, body_html=body))


def kanban_view(handler) -> None:
    """Drag-and-drop kanban board with one column per status.

    Replaces the legacy folder-native /p/<id> hiring board. Uses the existing
    /api/m/recruitment/<id>/move endpoint for status transitions.
    """
    from hrkit.templates import render_module_page

    conn = handler.server.conn  # type: ignore[attr-defined]
    rows = list_rows(conn)
    by_status: dict[str, list[dict[str, Any]]] = {s: [] for s in ALLOWED_STATUS}
    for r in rows:
        s = r.get("status") or "applied"
        by_status.setdefault(s, []).append(r)
    body = _render_kanban_html(by_status)
    handler._html(200, render_module_page(title=f"{LABEL} board", nav_active=NAME, body_html=body))


def _render_kanban_html(by_status: dict[str, list[dict[str, Any]]]) -> str:
    """Render a 6-column drag-and-drop kanban (HTML5 native, no libs)."""
    column_titles = {
        "applied":   ("Applied",   "#6366f1"),
        "screening": ("Screening", "#22d3ee"),
        "interview": ("Interview", "#f59e0b"),
        "offer":     ("Offer",     "#8b5cf6"),
        "hired":     ("Hired",     "#10b981"),
        "rejected":  ("Rejected",  "#f43f5e"),
    }

    cols_html: list[str] = []
    for status_key in ALLOWED_STATUS:
        title, accent = column_titles.get(status_key, (status_key.title(), "#9aa0a6"))
        cards = by_status.get(status_key, [])
        card_html: list[str] = []
        for r in cards:
            name = _esc(r.get("name") or "(no name)")
            email = _esc(r.get("email") or "")
            score_v = r.get("score")
            score_chip = ""
            if score_v not in (None, "", 0, 0.0):
                score_chip = f'<span class="kb-score">{float(score_v):.1f}</span>'
            recm = r.get("recommendation") or ""
            recm_chip = f'<span class="kb-rec kb-rec-{_esc(recm.lower())}">{_esc(recm)}</span>' if recm else ""
            card_html.append(
                f'<div class="kb-card" draggable="true" data-id="{int(r["id"])}" '
                f'ondragstart="kbDragStart(event)" onclick="location.href=\'/m/recruitment/{int(r["id"])}\'">'
                f'<div class="kb-name">{name}</div>'
                f'<div class="kb-meta">{email}</div>'
                f'<div class="kb-chips">{score_chip}{recm_chip}</div>'
                f'</div>'
            )
        cols_html.append(f"""
<div class="kb-col" data-status="{_esc(status_key)}"
     ondragover="event.preventDefault()" ondrop="kbDrop(event, '{_esc(status_key)}')">
  <div class="kb-col-head" style="border-color:{accent}">
    <span class="kb-col-title">{_esc(title)}</span>
    <span class="kb-col-count">{len(cards)}</span>
  </div>
  <div class="kb-col-body">{''.join(card_html) or '<div class="kb-empty">drop candidates here</div>'}</div>
</div>""")

    return f"""
<style>
  .kb-toolbar{{display:flex;align-items:center;gap:12px;margin-bottom:14px}}
  .kb-toolbar h1{{margin:0;font-size:22px;font-weight:600}}
  .kb-toolbar a{{padding:6px 12px;border-radius:6px;color:var(--dim);
    text-decoration:none;font-size:13px;border:1px solid var(--border)}}
  .kb-toolbar a:hover{{color:var(--text);border-color:var(--accent)}}
  .kb-board{{display:grid;grid-template-columns:repeat(6,minmax(200px,1fr));
    gap:12px;align-items:start}}
  .kb-col{{background:var(--panel);border:1px solid var(--border);
    border-radius:10px;min-height:240px;display:flex;flex-direction:column}}
  .kb-col.over{{outline:2px dashed var(--accent);outline-offset:-4px}}
  .kb-col-head{{display:flex;justify-content:space-between;align-items:center;
    padding:10px 12px;border-bottom:2px solid;font-size:12px;font-weight:600;
    text-transform:uppercase;letter-spacing:0.5px}}
  .kb-col-count{{background:rgba(255,255,255,0.06);padding:2px 8px;
    border-radius:10px;font-weight:500}}
  .kb-col-body{{padding:8px;display:flex;flex-direction:column;gap:8px;flex:1}}
  .kb-card{{background:var(--bg);border:1px solid var(--border);border-radius:8px;
    padding:10px 12px;cursor:grab;transition:transform .12s,border-color .12s}}
  .kb-card:hover{{border-color:var(--accent);transform:translateY(-1px)}}
  .kb-card.dragging{{opacity:0.4;cursor:grabbing}}
  .kb-name{{font-weight:600;font-size:13.5px;margin-bottom:3px}}
  .kb-meta{{font-size:11.5px;color:var(--dim);word-break:break-all}}
  .kb-chips{{display:flex;gap:4px;margin-top:6px;flex-wrap:wrap}}
  .kb-score{{background:var(--accent);color:#fff;font-size:11px;
    padding:1px 7px;border-radius:10px;font-weight:600}}
  .kb-rec{{font-size:10px;padding:1px 7px;border-radius:10px;
    text-transform:uppercase;letter-spacing:0.4px;background:rgba(255,255,255,0.06);color:var(--dim)}}
  .kb-rec-shortlist{{background:rgba(16,185,129,0.18);color:#10b981}}
  .kb-rec-borderline{{background:rgba(245,158,11,0.18);color:#f59e0b}}
  .kb-rec-reject{{background:rgba(244,63,94,0.18);color:#f43f5e}}
  .kb-empty{{padding:14px;text-align:center;color:var(--dim);font-size:11.5px;font-style:italic}}
</style>
<div class="kb-toolbar">
  <h1>Recruitment board</h1>
  <a href="/m/recruitment">List view</a>
</div>
<div class="kb-board">{''.join(cols_html)}</div>
<script>
function kbDragStart(ev) {{
  ev.dataTransfer.setData('text/plain', ev.target.dataset.id);
  ev.target.classList.add('dragging');
  ev.dataTransfer.effectAllowed = 'move';
}}
async function kbDrop(ev, newStatus) {{
  ev.preventDefault();
  const id = ev.dataTransfer.getData('text/plain');
  if (!id) return;
  const r = await fetch('/api/m/recruitment/' + id + '/move', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{status: newStatus}}),
  }});
  if (r.ok) location.reload();
  else alert('Move failed: ' + (await r.text()));
}}
document.querySelectorAll('.kb-card').forEach(c => {{
  c.addEventListener('dragend', () => c.classList.remove('dragging'));
}});
</script>
"""


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

    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(
            title="Not found",
            nav_active=NAME,
            subtitle=f"No candidate with id {int(item_id)}",
        ))
        return

    fields: list[tuple[str, Any]] = [
        ("Name", row.get("name")),
        ("Email", row.get("email")),
        ("Phone", row.get("phone")),
        ("Source", row.get("source")),
        ("Position", row.get("position") or row.get("position_folder_id")),
        ("Status", row.get("status")),
        ("Score", row.get("score")),
        ("Recommendation", row.get("recommendation")),
        ("Applied at", _fmt_dt(row.get("applied_at"))),
        ("Evaluated at", _fmt_dt(row.get("evaluated_at"))),
        ("Resume path", row.get("resume_path")),
    ]

    rid = int(item_id)
    move_buttons: list[str] = []
    for s in ALLOWED_STATUS:
        if s == row.get("status"):
            continue
        move_buttons.append(
            f"<button onclick=\"fetch('/api/m/recruitment/{rid}/move',"
            f"{{method:'POST',headers:{{'Content-Type':'application/json'}},"
            f"body:JSON.stringify({{status:'{s}'}})}})"
            f".then(r=>r.ok?location.reload():"
            f"r.text().then(t=>alert('Move failed: '+t)))\""
            f">Move to {s}</button>"
        )
    actions_html = "".join(move_buttons)

    if row.get("status") == "hired":
        actions_html += (
            f"<button onclick=\""
            f"if(!confirm('Convert this candidate to an employee?'))return;"
            f"fetch('/api/m/recruitment/{rid}/promote',{{method:'POST'}})"
            f".then(r=>r.ok?r.json().then(d=>{{alert('Created employee #'+d.employee_id);"
            f"location.href='/m/employee/'+d.employee_id;}}):"
            f"r.text().then(t=>alert('Promote failed: '+t)))\""
            f">Convert to employee</button>"
        )

    related_html = ""
    if row.get("resume_path"):
        related_html = detail_section(
            title="Resume",
            body_html=(
                f'<a href="{_esc(row.get("resume_path"))}" target="_blank">'
                f'{_esc(row.get("resume_path"))}</a>'
            ),
        )

    page = render_detail_page(
        title=row.get("name") or "Candidate",
        nav_active=NAME,
        subtitle=f"{row.get('position') or ''} · status {row.get('status') or ''}",
        fields=fields,
        actions_html=actions_html,
        related_html=related_html,
        item_id=rid,
        api_path="/api/m/recruitment",
        delete_redirect="/m/recruitment",
    )
    handler._html(200, page)


def detail_api_json(handler, item_id: int) -> None:
    """Return raw recruitment_candidate row as JSON."""
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


def move_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    status = (payload.get("status") or "").strip()
    try:
        row = move_status(conn, int(item_id), status)
    except LookupError as exc:
        handler._json({"error": str(exc)}, code=404)
        return
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    response: dict[str, Any] = {"ok": True, "status": row.get("status")}
    if row.get("status") == "hired":
        response["promote_hint"] = (
            "Candidate is hired. POST /api/m/recruitment/"
            f"{item_id}/promote to create an employee record."
        )
        response["promote_url"] = f"/api/m/recruitment/{item_id}/promote"
        # Fire integration hook (Composio Gmail offer letter, etc.)
        try:
            from hrkit.integrations import hooks
            response["integrations"] = hooks.emit("recruitment.hired", {
                "candidate_id": int(item_id),
                "name": row.get("name"),
                "email": row.get("email"),
                "position_folder_id": row.get("position_folder_id"),
            }, conn=conn)
        except Exception:
            pass
    handler._json(response)


def promote_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        new_employee_id = promote_to_employee(conn, int(item_id))
    except LookupError as exc:
        handler._json({"error": str(exc)}, code=404)
        return
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400)
        return
    handler._json({"ok": True, "employee_id": new_employee_id}, code=201)


def delete_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    delete_row(conn, int(item_id))
    handler._json({"ok": True})


# ---------------------------------------------------------------------------
# Notes + custom fields (Phase 1.11)
# ---------------------------------------------------------------------------
def _candidate_meta(conn, item_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT metadata_json FROM recruitment_candidate WHERE id = ?", (int(item_id),),
    ).fetchone()
    if not row:
        raise LookupError(f"candidate {item_id} not found")
    try:
        meta = json.loads(row["metadata_json"] or "{}")
    except (TypeError, ValueError):
        meta = {}
    return meta if isinstance(meta, dict) else {}


def _save_candidate_meta(conn, item_id: int, meta: dict) -> None:
    conn.execute(
        "UPDATE recruitment_candidate SET metadata_json = ? WHERE id = ?",
        (json.dumps(meta), int(item_id)),
    )
    conn.commit()


def notes_api(handler, item_id: int) -> None:
    """GET/POST /api/m/recruitment/<id>/notes — free-form HR notes."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    method = (getattr(handler, "command", "") or "").upper()
    try:
        meta = _candidate_meta(conn, int(item_id))
    except LookupError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=404)
        return
    if method == "GET":
        handler._json({"ok": True, "body": str(meta.get("notes") or "")})
        return
    body = handler._read_json() or {}
    text = body.get("body") if isinstance(body.get("body"), str) else ""
    meta["notes"] = text
    _save_candidate_meta(conn, item_id, meta)
    handler._json({"ok": True})


def custom_fields_api(handler, item_id: int) -> None:
    """GET/POST /api/m/recruitment/<id>/custom-fields — user-defined key/values."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    method = (getattr(handler, "command", "") or "").upper()
    try:
        meta = _candidate_meta(conn, int(item_id))
    except LookupError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=404)
        return
    custom = meta.get("custom") if isinstance(meta.get("custom"), dict) else {}
    if method == "GET":
        handler._json({"ok": True, "fields": custom})
        return
    body = handler._read_json() or {}
    fields_in = body.get("fields") if isinstance(body.get("fields"), dict) else {}
    cleaned: dict[str, Any] = {}
    for k, v in fields_in.items():
        key = str(k or "").strip()
        if key:
            cleaned[key] = v if v is None else str(v)
    meta["custom"] = cleaned
    _save_candidate_meta(conn, item_id, meta)
    handler._json({"ok": True, "fields": cleaned})


# ---------------------------------------------------------------------------
# Pull-from-Gmail (Phase 1.5)
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"<\s*([^<>\s]+@[^<>\s]+)\s*>|([^<>\s,]+@[^<>\s,]+)")


def _parse_email_address(raw: str) -> tuple[str, str]:
    """Return ``(name, email)`` from a ``Name <addr>`` style header."""
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    m = _EMAIL_RE.search(raw)
    email = ""
    if m:
        email = (m.group(1) or m.group(2) or "").strip()
    name = raw
    if email and email in raw:
        name = raw.replace(f"<{email}>", "").replace(email, "").strip().strip('"').strip()
    return name or email or raw, email


def _extract_gmail_messages(payload: Any) -> list[dict[str, Any]]:
    """Normalize the ``GMAIL_FETCH_EMAILS`` response into a flat message list.

    Composio variants seen in the wild:
        {"data": {"messages": [...]}}
        {"data": [...]}
        [...]
    Each message is expected to have at least an ``id`` and either a
    ``payload.headers`` array (raw Gmail API) or flattened ``subject``/
    ``from``/``snippet`` fields.
    """
    if isinstance(payload, dict):
        data = payload.get("data") or payload.get("result") or payload
        if isinstance(data, dict):
            messages = (
                data.get("messages")
                or data.get("results")
                or data.get("items")
                or []
            )
        else:
            messages = data
    else:
        messages = payload
    if not isinstance(messages, list):
        return []
    return [m for m in messages if isinstance(m, dict)]


def _flatten_gmail_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Return ``{id, thread_id, subject, from_name, from_email, to, date, body}``."""
    flat = {
        "id": str(msg.get("id") or msg.get("messageId") or ""),
        "thread_id": str(msg.get("threadId") or msg.get("thread_id") or ""),
        "subject": str(msg.get("subject") or ""),
        "from_name": "",
        "from_email": str(msg.get("from_email") or msg.get("sender") or ""),
        "to": str(msg.get("to") or ""),
        "date": str(msg.get("date") or msg.get("messageTimestamp") or ""),
        "body": str(msg.get("body") or msg.get("snippet") or msg.get("messageText") or ""),
    }
    if msg.get("from") and isinstance(msg["from"], str):
        name, email = _parse_email_address(msg["from"])
        flat["from_name"] = name
        flat["from_email"] = flat["from_email"] or email
    headers = msg.get("payload", {}).get("headers") if isinstance(msg.get("payload"), dict) else None
    if isinstance(headers, list):
        by_name = {str(h.get("name", "")).lower(): h.get("value", "") for h in headers if isinstance(h, dict)}
        flat["subject"] = flat["subject"] or by_name.get("subject", "")
        flat["date"] = flat["date"] or by_name.get("date", "")
        if "from" in by_name:
            name, email = _parse_email_address(by_name["from"])
            flat["from_name"] = flat["from_name"] or name
            flat["from_email"] = flat["from_email"] or email
        flat["to"] = flat["to"] or by_name.get("to", "")
    return flat


def _workspace_root_for_handler(handler) -> str | None:
    """Best-effort: return the workspace root path from server attrs."""
    server = getattr(handler, "server", None)
    root = getattr(server, "workspace_root", None) if server else None
    if root:
        return str(root)
    try:
        from hrkit import server as server_mod
        if getattr(server_mod, "ROOT", None):
            return str(server_mod.ROOT)
    except Exception:  # noqa: BLE001
        return None
    return None


def pull_emails_api(handler) -> None:
    """POST /api/m/recruitment/pull-emails — turn unread Gmail into candidates."""
    from hrkit import branding, composio_sdk
    from hrkit.integrations import mirror

    conn = handler.server.conn  # type: ignore[attr-defined]
    body = handler._read_json() or {}

    if not composio_sdk.is_configured(conn):
        handler._json({"ok": False, "error": "Composio API key not configured"}, code=400)
        return

    # Honor the user's per-tool toggle from /integrations.
    if GMAIL_FETCH_ACTION in branding.composio_disabled_tools(conn):
        handler._json({
            "ok": False,
            "error": f"{GMAIL_FETCH_ACTION} is disabled on the Integrations page.",
        }, code=400)
        return

    arguments: dict[str, Any] = {
        "query": str(body.get("query") or "").strip() or "label:UNREAD newer_than:14d",
        "max_results": int(body.get("max_results") or 25),
    }

    try:
        result = composio_sdk.execute_action(conn, GMAIL_FETCH_ACTION, arguments)
    except Exception as exc:  # noqa: BLE001
        log.exception("recruitment.pull_emails: SDK call failed")
        handler._json({"ok": False, "error": f"Composio call failed: {exc}"}, code=500)
        return

    if not result.get("successful"):
        handler._json({
            "ok": False,
            "error": result.get("error") or "Composio reported the action failed",
        }, code=502)
        return

    messages = _extract_gmail_messages(result.get("data"))
    workspace_root = _workspace_root_for_handler(handler)

    candidates_created: list[int] = []
    candidates_skipped: list[str] = []
    mirror_writes: list[dict[str, str]] = []

    for raw_msg in messages:
        flat = _flatten_gmail_message(raw_msg)
        msg_id = flat["id"]
        if not msg_id:
            continue

        # 1. Mirror to disk (when we know where to write).
        if workspace_root:
            try:
                paths = mirror.write_record(
                    workspace_root=workspace_root,
                    app="gmail",
                    resource="messages",
                    record_id=msg_id,
                    frontmatter={
                        "subject": flat["subject"],
                        "from": (
                            f"{flat['from_name']} <{flat['from_email']}>"
                            if flat["from_name"] and flat["from_email"]
                            else (flat["from_name"] or flat["from_email"])
                        ),
                        "to": flat["to"],
                        "date": flat["date"],
                        "thread_id": flat["thread_id"],
                    },
                    body=flat["body"],
                    raw=raw_msg,
                )
                mirror_writes.append(paths)
            except (OSError, ValueError) as exc:
                log.warning("recruitment.pull_emails: mirror.write_record failed for %s: %s",
                            msg_id, exc)

        # 2. Create candidate (skip if we already have one for this email).
        from_email = flat["from_email"].lower()
        existing = None
        if from_email:
            existing = conn.execute(
                "SELECT id FROM recruitment_candidate WHERE LOWER(email) = ? LIMIT 1",
                (from_email,),
            ).fetchone()
        if existing:
            candidates_skipped.append(from_email)
            continue

        candidate_name = (flat["from_name"] or from_email or "Unknown").strip()
        try:
            new_id = create_row(conn, {
                "name": candidate_name,
                "email": from_email,
                "source": "gmail",
                "metadata_json": {
                    "gmail_message_id": msg_id,
                    "gmail_thread_id": flat["thread_id"],
                    "subject": flat["subject"],
                    "received": flat["date"],
                },
            })
        except (ValueError, sqlite3.IntegrityError) as exc:
            log.warning("recruitment.pull_emails: create_row failed for %s: %s",
                        msg_id, exc)
            continue
        candidates_created.append(new_id)

    response: dict[str, Any] = {
        "ok": True,
        "fetched": len(messages),
        "created_candidate_ids": candidates_created,
        "skipped_existing": candidates_skipped,
        "mirrored": len(mirror_writes),
    }
    if not workspace_root:
        response["mirror_warning"] = "workspace root not resolved; on-disk mirror skipped"
    handler._json(response)


ROUTES = {
    "GET": [
        (r"^/api/m/recruitment/(\d+)/notes/?$", notes_api),
        (r"^/api/m/recruitment/(\d+)/custom-fields/?$", custom_fields_api),
        (r"^/api/m/recruitment/(\d+)/?$", detail_api_json),
        (r"^/m/recruitment/board/?$", kanban_view),
        (r"^/m/recruitment/?$", list_view),
        (r"^/m/recruitment/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/recruitment/pull-emails/?$", pull_emails_api),
        (r"^/api/m/recruitment/(\d+)/notes/?$", notes_api),
        (r"^/api/m/recruitment/(\d+)/custom-fields/?$", custom_fields_api),
        (r"^/api/m/recruitment/?$", create_api),
        (r"^/api/m/recruitment/(\d+)/?$", update_api),
        (r"^/api/m/recruitment/(\d+)/move/?$", move_api),
        (r"^/api/m/recruitment/(\d+)/promote/?$", promote_api),
    ],
    "DELETE": [
        (r"^/api/m/recruitment/(\d+)/?$", delete_api),
    ],
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_create_args(parser) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", default="")
    parser.add_argument("--phone", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--position-folder-id", type=int)
    parser.add_argument("--status", default="applied", choices=list(ALLOWED_STATUS))
    parser.add_argument("--applied-at", default="")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "name": args.name,
        "email": getattr(args, "email", "") or "",
        "phone": getattr(args, "phone", "") or "",
        "source": getattr(args, "source", "") or "",
        "position_folder_id": getattr(args, "position_folder_id", None),
        "status": getattr(args, "status", "applied"),
        "applied_at": getattr(args, "applied_at", "") or "",
    })
    log.info("recruitment_added id=%s name=%s", new_id, args.name)
    return 0


def _add_move_args(parser) -> None:
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--status", required=True, choices=list(ALLOWED_STATUS))


def _handle_move(args, conn: sqlite3.Connection) -> int:
    move_status(conn, args.id, args.status)
    log.info("recruitment_moved id=%s status=%s", args.id, args.status)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info(
            "%s\t%s\t%s\t%s\t%s",
            row["id"], row["name"], row["email"], row["status"], row["applied_at"],
        )
    return 0


CLI = [
    ("recruitment-add", _add_create_args, _handle_create),
    ("recruitment-move", _add_move_args, _handle_move),
    ("recruitment-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
