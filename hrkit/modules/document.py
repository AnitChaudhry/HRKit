"""Document HR module.

Owns CRUD over the ``document`` table — employee paperwork (PAN, contracts,
certificates, ...). For Wave 1 the file content is referenced by string path;
binary upload handling lands in Wave 2. Schema lives in migration 001.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "document"
LABEL = "Documents"
ICON = "file-text"

LIST_COLUMNS = ("employee", "doc_type", "filename", "expiry_date")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def ensure_schema(conn: sqlite3.Connection) -> None:
    """No-op. The ``document`` table is created by migration 001."""
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def list_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT d.id, d.employee_id, d.doc_type, d.filename, d.file_path,
               d.uploaded_at, d.expiry_date, d.notes,
               e.full_name AS employee
        FROM document d
        LEFT JOIN employee e ON e.id = d.employee_id
        ORDER BY d.uploaded_at DESC, d.id DESC
        """
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM document WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    employee_id = data.get("employee_id")
    doc_type = (data.get("doc_type") or "").strip()
    filename = (data.get("filename") or "").strip()
    file_path = (data.get("file_path") or "").strip()
    if employee_id in (None, ""):
        raise ValueError("employee_id is required")
    if not doc_type:
        raise ValueError("doc_type is required")
    if not filename:
        raise ValueError("filename is required")
    if not file_path:
        raise ValueError("file_path is required")

    cols: list[str] = ["employee_id", "doc_type", "filename", "file_path"]
    vals: list[Any] = [int(employee_id), doc_type, filename, file_path]
    for key in ("expiry_date", "notes"):
        if data.get(key) is not None:
            cols.append(key)
            vals.append(data[key])

    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO document ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn: sqlite3.Connection, item_id: int, data: dict[str, Any]) -> None:
    fields: list[str] = []
    values: list[Any] = []
    for key in ("employee_id", "doc_type", "filename", "file_path", "expiry_date", "notes"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE document SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM document WHERE id = ?", (item_id,))
    conn.commit()


def _list_employees(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT id, full_name AS label FROM employee ORDER BY full_name")
    return [{"id": r["id"], "label": r["label"]} for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
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
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ Add Document</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Employee*<select name="employee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Document type*<input name="doc_type" required placeholder="e.g. PAN, contract"></label>
    <label>File*<input name="file" type="file" required></label>
    <label>Filename<input name="filename" placeholder="defaults to uploaded filename"></label>
    <label>Expiry date<input name="expiry_date" type="date"></label>
    <label>Notes<textarea name="notes"></textarea></label>
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
  // If no explicit filename was given, use the uploaded file's name.
  if (!fd.get('filename') && fd.get('file')) {{
    fd.set('filename', fd.get('file').name);
  }}
  if (fd.get('expiry_date') === '') fd.delete('expiry_date');
  const r = await fetch('/api/m/document/upload', {{method: 'POST', body: fd}});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete document #' + id + '?')) return;
  const r = await fetch('/api/m/document/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def list_view(handler) -> None:
    from hrkit.templates import render_module_page

    conn = handler.server.conn  # type: ignore[attr-defined]
    rows = list_rows(conn)
    body = _render_list_html(rows, _list_employees(conn))
    handler._html(200, render_module_page(title=LABEL, nav_active=NAME, body_html=body))


def detail_api_json(handler, item_id: int) -> None:
    """Return the raw document row as JSON (back-compat for API clients)."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id: int) -> None:
    from hrkit.templates import render_detail_page, detail_section

    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(
            404,
            render_detail_page(
                title="Not found",
                nav_active=NAME,
                subtitle=f"No document with id {int(item_id)}",
            ),
        )
        return

    emp_name = ""
    emp_row = None
    if row.get("employee_id"):
        cur = conn.execute(
            "SELECT id, employee_code, full_name, email, status "
            "FROM employee WHERE id = ?",
            (row["employee_id"],),
        )
        emp_row = cur.fetchone()
        if emp_row:
            emp_name = emp_row["full_name"]

    fields: list[tuple[str, Any]] = [
        ("Employee", emp_name),
        ("Document type", row.get("doc_type")),
        ("Filename", row.get("filename")),
        ("File path", row.get("file_path")),
        ("Uploaded at", row.get("uploaded_at")),
        ("Expiry date", row.get("expiry_date")),
        ("Notes", row.get("notes")),
        ("Created", row.get("created")),
    ]

    if emp_row:
        emp_body = (
            "<table><thead><tr><th>Code</th><th>Name</th>"
            "<th>Email</th><th>Status</th></tr></thead><tbody>"
            f"<tr><td>{_esc(emp_row['employee_code'])}</td>"
            f"<td><a href=\"/m/employee/{int(emp_row['id'])}\">{_esc(emp_row['full_name'])}</a></td>"
            f"<td>{_esc(emp_row['email'])}</td><td>{_esc(emp_row['status'])}</td></tr>"
            "</tbody></table>"
        )
    else:
        emp_body = '<div class="empty">No linked employee.</div>'

    related_html = detail_section(title="Employee", body_html=emp_body)

    subtitle_bits = [b for b in (row.get("doc_type"), emp_name) if b]
    download_btn = (
        f'<a href="/api/m/{NAME}/{int(item_id)}/download" '
        f'download="{_esc(row.get("filename") or "")}">Download</a>'
    ) if row.get("file_path") else ""
    html = render_detail_page(
        title=row.get("filename") or "Document",
        nav_active=NAME,
        subtitle=" · ".join(subtitle_bits),
        fields=fields,
        actions_html=download_btn,
        related_html=related_html,
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}",
        delete_redirect=f"/m/{NAME}",
    )
    handler._html(200, html)


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
        (r"^/api/m/document/(\d+)/?$", detail_api_json),
        (r"^/m/document/?$", list_view),
        (r"^/m/document/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/document/?$", create_api),
        (r"^/api/m/document/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/document/(\d+)/?$", delete_api),
    ],
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_create_args(parser) -> None:
    parser.add_argument("--employee-id", type=int, required=True)
    parser.add_argument("--doc-type", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--file-path", required=True)
    parser.add_argument("--expiry-date")
    parser.add_argument("--notes")


def _handle_create(args, conn: sqlite3.Connection) -> int:
    new_id = create_row(conn, {
        "employee_id": args.employee_id,
        "doc_type": args.doc_type,
        "filename": args.filename,
        "file_path": args.file_path,
        "expiry_date": getattr(args, "expiry_date", None),
        "notes": getattr(args, "notes", None),
    })
    log.info("document_added id=%s employee=%s", new_id, args.employee_id)
    return 0


def _handle_list(args, conn: sqlite3.Connection) -> int:
    for row in list_rows(conn):
        log.info(
            "%s\t%s\t%s\t%s",
            row["id"], row.get("employee") or "", row["doc_type"], row["filename"],
        )
    return 0


CLI = [
    ("document-add", _add_create_args, _handle_create),
    ("document-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
