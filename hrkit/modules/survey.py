"""Survey module — pulse / feedback surveys with question types + responses.

Owns ``survey``, ``survey_question``, ``survey_response`` (migration 002).
Anonymous mode supported via the ``anonymous`` flag on survey + nullable
``employee_id`` on response.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "survey"
LABEL = "Surveys"
ICON = "clipboard-list"

LIST_COLUMNS = ("title", "status", "anonymous", "questions", "responses", "created")
ALLOWED_STATUS = ("draft", "active", "closed", "archived")
QUESTION_TYPES = ("text", "scale", "single_choice", "multiple_choice", "yes_no")


def ensure_schema(conn: sqlite3.Connection) -> None:
    return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("""
        SELECT s.id, s.title, s.description, s.status, s.anonymous, s.created, s.closes_at,
               (SELECT COUNT(*) FROM survey_question q WHERE q.survey_id = s.id) AS questions,
               (SELECT COUNT(*) FROM survey_response r WHERE r.survey_id = s.id) AS responses
        FROM survey s ORDER BY s.created DESC
    """)
    out = []
    for r in cur.fetchall():
        d = _row_to_dict(r)
        d["anonymous"] = "Yes" if d.get("anonymous") else "No"
        out.append(d)
    return out


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM survey WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    status = (data.get("status") or "draft").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["title", "status"]
    vals: list[Any] = [title, status]
    if data.get("description") is not None:
        cols.append("description"); vals.append(data["description"])
    if "anonymous" in data:
        cols.append("anonymous"); vals.append(1 if data["anonymous"] else 0)
    if data.get("created_by") is not None:
        cols.append("created_by"); vals.append(int(data["created_by"]))
    if data.get("closes_at"):
        cols.append("closes_at"); vals.append(data["closes_at"])
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO survey ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("title", "description", "status", "closes_at"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if "anonymous" in data:
        fields.append("anonymous = ?"); values.append(1 if data["anonymous"] else 0)
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE survey SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM survey WHERE id = ?", (item_id,))
    conn.commit()


def add_question(conn: sqlite3.Connection, survey_id: int,
                 question_text: str, question_type: str = "text",
                 options: list[str] | None = None,
                 required: bool = False, position: int | None = None) -> int:
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"question_type must be one of {QUESTION_TYPES}")
    if position is None:
        cur = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM survey_question WHERE survey_id = ?",
            (int(survey_id),))
        position = int(cur.fetchone()["p"])
    cur = conn.execute("""
        INSERT INTO survey_question (survey_id, position, question_text, question_type,
                                     options_json, required)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (int(survey_id), position, question_text, question_type,
          json.dumps(options or []), 1 if required else 0))
    conn.commit()
    return int(cur.lastrowid)


def submit_response(conn: sqlite3.Connection, survey_id: int,
                    answers: dict[str, Any], employee_id: int | None = None) -> int:
    cur = conn.execute("""
        INSERT INTO survey_response (survey_id, employee_id, answers_json)
        VALUES (?, ?, ?)
    """, (int(survey_id), employee_id, json.dumps(answers or {})))
    conn.commit()
    return int(cur.lastrowid)


def _render_list_html(rows) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/survey/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New survey</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Title*<input name="title" required placeholder="Q4 engagement pulse"></label>
    <label>Description<textarea name="description"></textarea></label>
    <label><input type="checkbox" name="anonymous" value="1"> Anonymous</label>
    <label>Closes at<input name="closes_at" type="date"></label>
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
  payload.anonymous = fd.has('anonymous');
  const r = await fetch('/api/m/survey', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRow(id) {{
  if (!(await hrkit.confirmDialog('Delete survey #' + id + '?'))) return;
  const r = await fetch('/api/m/survey/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else hrkit.toast('Delete failed', 'error');
}}
</script>
"""


def list_view(handler) -> None:
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME,
        body_html=_render_list_html(list_rows(conn))))


def detail_api_json(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No survey with id {int(item_id)}"))
        return

    qs = conn.execute(
        "SELECT id, position, question_text, question_type, required, options_json "
        "FROM survey_question WHERE survey_id = ? ORDER BY position, id",
        (int(item_id),)).fetchall()
    if qs:
        rows_html = "".join(
            f"<tr><td>{q['position']}</td><td>{_esc(q['question_text'])}</td>"
            f"<td>{_esc(q['question_type'])}</td>"
            f"<td>{'yes' if q['required'] else 'no'}</td>"
            f"<td>{_esc(q['options_json'])}</td>"
            f"<td><button onclick=\"deleteQ({int(q['id'])})\">×</button></td></tr>"
            for q in qs)
        q_table = (f"<table><thead><tr><th>#</th><th>Question</th><th>Type</th>"
                   f"<th>Req</th><th>Options</th><th></th></tr></thead><tbody>{rows_html}</tbody></table>")
    else:
        q_table = '<div class="empty">No questions yet.</div>'

    type_opts = "".join(f'<option value="{t}">{t}</option>' for t in QUESTION_TYPES)
    q_form = f"""
<form onsubmit="addQuestion(event,{int(item_id)})" style="display:grid;
  grid-template-columns:2fr 1fr 1fr auto;gap:8px;margin-bottom:14px">
  <input name="question_text" required placeholder="Question text">
  <select name="question_type">{type_opts}</select>
  <input name="options" placeholder="Options (comma-sep, for choices)">
  <button>+ Add</button>
</form>
<script>
async function addQuestion(ev, surveyId) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const data = Object.fromEntries(fd.entries());
  data.options = (data.options || '').split(',').map(s => s.trim()).filter(Boolean);
  const r = await fetch('/api/m/survey/' + surveyId + '/questions', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(data),
  }});
  if (r.ok) location.reload(); else hrkit.toast('Add failed: ' + await r.text(), 'error');
}}
async function deleteQ(qid) {{
  if (!(await hrkit.confirmDialog('Delete question?'))) return;
  const r = await fetch('/api/m/survey/questions/' + qid, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else hrkit.toast('Delete failed', 'error');
}}
</script>
"""

    # Responses summary
    rcount = conn.execute(
        "SELECT COUNT(*) AS n FROM survey_response WHERE survey_id = ?", (int(item_id),)
    ).fetchone()["n"]
    resp_body = (
        f'<p><strong>{rcount}</strong> response{"" if rcount == 1 else "s"} collected. '
        f'<a href="/m/survey/{int(item_id)}/take">Take this survey →</a></p>'
    )

    fields = [
        ("Title", row.get("title")),
        ("Description", row.get("description")),
        ("Status", row.get("status")),
        ("Anonymous", "Yes" if row.get("anonymous") else "No"),
        ("Closes at", row.get("closes_at")),
        ("Created", row.get("created")),
    ]
    related = (detail_section(title="Add question", body_html=q_form)
               + detail_section(title="Questions", body_html=q_table)
               + detail_section(title="Responses", body_html=resp_body))
    handler._html(200, render_detail_page(
        title=row.get("title") or "Survey", nav_active=NAME, subtitle=row.get("status") or "",
        fields=fields, related_html=related,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"status": list(ALLOWED_STATUS)},
    ))


def take_view(handler, item_id: int) -> None:
    """Render a public take-the-survey form."""
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    survey = get_row(conn, int(item_id))
    if not survey:
        handler._html(404, render_module_page(
            title="Not found", nav_active=NAME,
            body_html='<div class="empty">Survey not found.</div>'))
        return
    qs = conn.execute(
        "SELECT id, position, question_text, question_type, required, options_json "
        "FROM survey_question WHERE survey_id = ? ORDER BY position, id",
        (int(item_id),)).fetchall()
    qhtml = []
    for q in qs:
        qid = int(q["id"])
        req = "required" if q["required"] else ""
        try:
            opts = json.loads(q["options_json"] or "[]")
        except (TypeError, ValueError):
            opts = []
        if q["question_type"] == "scale":
            opt_html = "".join(
                f'<label><input type="radio" name="q_{qid}" value="{i}" {req}> {i}</label>'
                for i in range(1, 6))
        elif q["question_type"] == "yes_no":
            opt_html = (f'<label><input type="radio" name="q_{qid}" value="yes" {req}> Yes</label>'
                        f'<label><input type="radio" name="q_{qid}" value="no" {req}> No</label>')
        elif q["question_type"] == "single_choice":
            opt_html = "".join(
                f'<label><input type="radio" name="q_{qid}" value="{_esc(o)}" {req}> {_esc(o)}</label>'
                for o in opts)
        elif q["question_type"] == "multiple_choice":
            opt_html = "".join(
                f'<label><input type="checkbox" name="q_{qid}" value="{_esc(o)}"> {_esc(o)}</label>'
                for o in opts)
        else:
            opt_html = f'<textarea name="q_{qid}" {req}></textarea>'
        qhtml.append(f"""
<div style="margin-bottom:18px;padding:12px;border:1px solid var(--border);border-radius:6px">
  <div style="font-weight:600;margin-bottom:8px">{_esc(q['question_text'])}{' *' if q['required'] else ''}</div>
  <div style="display:flex;flex-direction:column;gap:6px">{opt_html}</div>
</div>""")
    body = f"""
<div class="module-toolbar">
  <h1>{_esc(survey['title'])}</h1>
  <a href="/m/survey/{int(item_id)}" style="font-size:13px;color:var(--accent);text-decoration:none">
    &larr; Back to survey</a>
</div>
<p style="color:var(--dim);margin-bottom:16px">{_esc(survey['description'])}</p>
<form onsubmit="submitResponse(event,{int(item_id)})">
  {''.join(qhtml)}
  <button type="submit">Submit response</button>
</form>
<script>
async function submitResponse(ev, surveyId) {{
  ev.preventDefault();
  const answers = {{}};
  ev.target.querySelectorAll('input,textarea').forEach(el => {{
    if (el.type === 'checkbox') {{
      if (el.checked) {{
        const k = el.name; (answers[k] = answers[k] || []).push(el.value);
      }}
    }} else if (el.type === 'radio') {{
      if (el.checked) answers[el.name] = el.value;
    }} else {{
      answers[el.name] = el.value;
    }}
  }});
  const r = await fetch('/api/m/survey/' + surveyId + '/responses', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{answers}}),
  }});
  if (r.ok) {{ hrkit.toast('Thanks for your response.', 'info'); location.href = '/m/survey'; }}
  else {{ hrkit.toast('Submit failed: ' + await r.text(), 'error'); }}
}}
</script>
"""
    handler._html(200, render_module_page(
        title=survey["title"], nav_active=NAME, body_html=body))


def create_api(handler) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        new_id = create_row(conn, payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"id": new_id}, code=201)


def update_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        update_row(conn, int(item_id), payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True})


def delete_api(handler, item_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    delete_row(conn, int(item_id))
    handler._json({"ok": True})


def question_create_api(handler, survey_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        qid = add_question(
            conn, int(survey_id),
            question_text=payload.get("question_text") or "",
            question_type=payload.get("question_type") or "text",
            options=payload.get("options") or [],
            required=bool(payload.get("required")))
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"id": qid}, code=201)


def question_delete_api(handler, qid: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    conn.execute("DELETE FROM survey_question WHERE id = ?", (int(qid),))
    conn.commit()
    handler._json({"ok": True})


def response_create_api(handler, survey_id: int) -> None:
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    new_id = submit_response(
        conn, int(survey_id),
        answers=payload.get("answers") or {},
        employee_id=payload.get("employee_id"))
    handler._json({"id": new_id}, code=201)


ROUTES = {
    "GET": [
        (r"^/api/m/survey/(\d+)/?$", detail_api_json),
        (r"^/m/survey/?$", list_view),
        (r"^/m/survey/(\d+)/take/?$", take_view),
        (r"^/m/survey/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/survey/(\d+)/questions/?$", question_create_api),
        (r"^/api/m/survey/(\d+)/responses/?$", response_create_api),
        (r"^/api/m/survey/?$", create_api),
        (r"^/api/m/survey/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/survey/questions/(\d+)/?$", question_delete_api),
        (r"^/api/m/survey/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser) -> None:
    parser.add_argument("--title", required=True)
    parser.add_argument("--description")
    parser.add_argument("--anonymous", action="store_true")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "title": args.title,
        "description": getattr(args, "description", None),
        "anonymous": getattr(args, "anonymous", False),
    })
    log.info("survey_added id=%s title=%s", new_id, args.title)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s/%s responses", row["id"], row["status"],
                 row["title"], row["responses"], row["questions"])
    return 0


CLI = [
    ("survey-add", _add_create_args, _handle_create),
    ("survey-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "engagement",
    "requires": [],
    "description": "Pulse / feedback surveys with multiple question types.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
