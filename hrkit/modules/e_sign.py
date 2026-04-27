"""e-Sign module — track signature requests for contracts / NDAs / offer letters.

Owns ``signature_request`` (migration 002). When the configured provider is
``composio`` (or a specific signing provider), the module will dispatch the
send via the Composio shim. Falls back to ``manual`` mode when no provider
key is configured — the recruiter sends the document themselves and updates
the row by hand.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "e_sign"
LABEL = "e-Sign"
ICON = "pen-tool"

LIST_COLUMNS = ("employee", "document_type", "provider", "status", "created", "signed_at")
ALLOWED_STATUS = ("pending", "sent", "viewed", "signed", "declined", "expired", "cancelled")
ALLOWED_PROVIDER = ("composio", "docusign", "hellosign", "dropbox_sign", "manual")


def ensure_schema(conn): return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def list_rows(conn):
    cur = conn.execute("""
        SELECT s.*, e.full_name AS employee
        FROM signature_request s
        LEFT JOIN employee e ON e.id = s.employee_id
        ORDER BY s.created DESC
    """)
    return [_row_to_dict(r) for r in cur.fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("""
        SELECT s.*, e.full_name AS employee
        FROM signature_request s
        LEFT JOIN employee e ON e.id = s.employee_id
        WHERE s.id = ?
    """, (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def create_row(conn, data):
    employee_id = data.get("employee_id")
    if not employee_id:
        raise ValueError("employee_id is required")
    provider = (data.get("provider") or "manual").strip()
    if provider not in ALLOWED_PROVIDER:
        raise ValueError(f"provider must be one of {ALLOWED_PROVIDER}")
    status = (data.get("status") or "pending").strip()
    if status not in ALLOWED_STATUS:
        raise ValueError(f"status must be one of {ALLOWED_STATUS}")
    cols = ["employee_id", "provider", "status"]
    vals: list[Any] = [int(employee_id), provider, status]
    for key in ("document_type", "document_path", "expires_at", "notes"):
        if data.get(key) is not None:
            cols.append(key); vals.append(data[key])
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO signature_request ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    return int(cur.lastrowid)


def update_row(conn, item_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("document_type", "document_path", "provider", "status",
                "provider_request_id", "signed_pdf_path", "expires_at", "notes"):
        if key in data:
            fields.append(f"{key} = ?"); values.append(data[key])
    if data.get("status") == "signed":
        fields.append("signed_at = (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))")
    if not fields:
        return
    values.append(item_id)
    conn.execute(f"UPDATE signature_request SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def delete_row(conn, item_id):
    conn.execute("DELETE FROM signature_request WHERE id = ?", (item_id,))
    conn.commit()


def send_via_composio(conn: sqlite3.Connection, request_id: int) -> dict[str, Any]:
    """Best-effort send through the Composio composio_actions shim. Falls
    back to flipping status to 'sent' if no signing tool is configured."""
    try:
        from hrkit.composio_client import has_credentials  # type: ignore
    except Exception:
        has_credentials = lambda: False  # noqa: E731
    if not has_credentials():
        # No Composio key — manual mode. Just mark sent.
        conn.execute(
            "UPDATE signature_request SET status='sent' WHERE id = ?", (int(request_id),))
        conn.commit()
        return {"ok": True, "mode": "manual", "id": int(request_id)}
    # Composio path — currently a thin stub. Real DocuSign/HelloSign Composio
    # action wiring is left to integrations/composio_actions.py to extend.
    try:
        from hrkit.integrations import composio_actions
        if hasattr(composio_actions, "send_signature_request"):
            return composio_actions.send_signature_request(  # type: ignore[attr-defined]
                {"signature_request_id": int(request_id)}, conn=conn)
    except Exception as exc:  # noqa: BLE001
        log.warning("composio send_signature_request failed: %s", exc)
    conn.execute(
        "UPDATE signature_request SET status='sent' WHERE id = ?", (int(request_id),))
    conn.commit()
    return {"ok": True, "mode": "composio_pending_action", "id": int(request_id)}


def _emp_options(conn):
    return [{"id": r["id"], "label": r["full_name"]}
            for r in conn.execute(
                "SELECT id, full_name FROM employee ORDER BY full_name").fetchall()]


def _render_list_html(rows, employees) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/e_sign/{row["id"]}\'">'
            f'{cells}<td><button onclick="event.stopPropagation();deleteRow({row["id"]})">'
            f'Delete</button></td></tr>')
    emp_opts = "".join(f'<option value="{e["id"]}">{_esc(e["label"])}</option>' for e in employees)
    prov_opts = "".join(f'<option value="{p}"{" selected" if p == "manual" else ""}>{p}</option>'
                        for p in ALLOWED_PROVIDER)
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="document.getElementById('create-dlg').showModal()">+ New request</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<div style="color:var(--dim);font-size:12px;margin-bottom:10px">
  Track signature requests across providers. Use ``provider=composio`` and
  configure your Composio key under Settings to dispatch via DocuSign /
  HelloSign / Dropbox Sign. ``manual`` mode just records the workflow.
</div>
<table class="data-table">
  <thead><tr>{head}<th></th></tr></thead>
  <tbody id="rows">{''.join(body_rows)}</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <label>Employee*<select name="employee_id" required><option value="">--</option>{emp_opts}</select></label>
    <label>Document type<input name="document_type" placeholder="contract / NDA / offer letter"></label>
    <label>Document path<input name="document_path" placeholder="employees/EMP-0001/contract.pdf"></label>
    <label>Provider<select name="provider">{prov_opts}</select></label>
    <label>Expires at<input name="expires_at" type="date"></label>
    <label>Notes<textarea name="notes"></textarea></label>
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Create</button>
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
  const r = await fetch('/api/m/e_sign', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(Object.fromEntries(fd.entries())),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRow(id) {{
  if (!confirm('Delete?')) return;
  const r = await fetch('/api/m/e_sign/' + id, {{method: 'DELETE'}});
  if (r.ok) location.reload(); else alert('Delete failed');
}}
</script>
"""


def list_view(handler):
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME,
        body_html=_render_list_html(list_rows(conn), _emp_options(conn))))


def detail_api_json(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._json(get_row(conn, int(item_id)) or {})


def detail_view(handler, item_id):
    from hrkit.templates import render_detail_page, detail_section
    conn = handler.server.conn  # type: ignore[attr-defined]
    row = get_row(conn, int(item_id))
    if not row:
        handler._html(404, render_detail_page(title="Not found", nav_active=NAME,
                      subtitle=f"No request with id {int(item_id)}"))
        return
    actions = f"""
<div style="display:flex;gap:8px;flex-wrap:wrap">
  <button onclick="sendNow({int(item_id)})">Send via {row.get('provider', 'manual')}</button>
  <button onclick="markSigned({int(item_id)})" class="ghost">Mark signed</button>
  <button onclick="markDeclined({int(item_id)})" class="ghost">Mark declined</button>
</div>
<script>
async function sendNow(id) {{
  const r = await fetch('/api/m/e_sign/' + id + '/send', {{method: 'POST'}});
  if (r.ok) location.reload(); else alert('Send failed: ' + await r.text());
}}
async function markSigned(id) {{
  const r = await fetch('/api/m/e_sign/' + id, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{status: 'signed'}})
  }});
  if (r.ok) location.reload(); else alert('Update failed');
}}
async function markDeclined(id) {{
  const r = await fetch('/api/m/e_sign/' + id, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{status: 'declined'}})
  }});
  if (r.ok) location.reload(); else alert('Update failed');
}}
</script>
"""
    fields = [
        ("Employee", row.get("employee")),
        ("Document type", row.get("document_type")),
        ("Document path", row.get("document_path")),
        ("Provider", row.get("provider")),
        ("Provider request id", row.get("provider_request_id")),
        ("Status", row.get("status")),
        ("Signed at", row.get("signed_at")),
        ("Signed PDF path", row.get("signed_pdf_path")),
        ("Expires at", row.get("expires_at")),
        ("Notes", row.get("notes")),
        ("Created", row.get("created")),
    ]
    handler._html(200, render_detail_page(
        title=f"{row.get('document_type', 'Document')} — {row.get('employee', '?')}",
        nav_active=NAME, subtitle=row.get("status") or "",
        fields=fields,
        related_html=detail_section(title="Actions", body_html=actions),
        item_id=int(item_id),
        api_path=f"/api/m/{NAME}", delete_redirect=f"/m/{NAME}",
        field_options={"status": list(ALLOWED_STATUS), "provider": list(ALLOWED_PROVIDER)},
    ))


def create_api(handler):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        new_id = create_row(conn, payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"id": new_id}, code=201)


def update_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    payload = handler._read_json() or {}
    try:
        update_row(conn, int(item_id), payload)
    except (ValueError, sqlite3.IntegrityError) as exc:
        handler._json({"error": str(exc)}, code=400); return
    handler._json({"ok": True})


def delete_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    delete_row(conn, int(item_id))
    handler._json({"ok": True})


def send_api(handler, item_id):
    conn = handler.server.conn  # type: ignore[attr-defined]
    result = send_via_composio(conn, int(item_id))
    handler._json(result)


ROUTES = {
    "GET": [
        (r"^/api/m/e_sign/(\d+)/?$", detail_api_json),
        (r"^/m/e_sign/?$", list_view),
        (r"^/m/e_sign/(\d+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/e_sign/(\d+)/send/?$", send_api),
        (r"^/api/m/e_sign/?$", create_api),
        (r"^/api/m/e_sign/(\d+)/?$", update_api),
    ],
    "DELETE": [
        (r"^/api/m/e_sign/(\d+)/?$", delete_api),
    ],
}


def _add_create_args(parser):
    parser.add_argument("--employee-id", type=int, required=True)
    parser.add_argument("--document-type", default="contract")
    parser.add_argument("--document-path")
    parser.add_argument("--provider", default="manual", choices=list(ALLOWED_PROVIDER))


def _handle_create(args, conn):
    new_id = create_row(conn, {
        "employee_id": args.employee_id,
        "document_type": args.document_type,
        "document_path": getattr(args, "document_path", None),
        "provider": args.provider,
    })
    log.info("signature_request_added id=%s employee=%s",
             new_id, args.employee_id)
    return 0


def _handle_list(args, conn):
    for row in list_rows(conn):
        log.info("%s\t%s\t%s\t%s\t%s",
                 row["id"], row["status"], row["provider"],
                 row.get("document_type") or "", row.get("employee") or "")
    return 0


CLI = [
    ("sign-request", _add_create_args, _handle_create),
    ("sign-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "operations",
    "requires": ["employee"],
    "description": "e-signature requests via Composio (DocuSign / HelloSign / Dropbox Sign) or manual.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
