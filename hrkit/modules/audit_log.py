"""Audit log module — read-only compliance log of who did what when.

Owns ``audit_log`` (migration 002). The table is mainly *written* by other
modules / hooks via :func:`record`. This module exposes a list view + search
+ a JSON API so admins can audit changes.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "audit_log"
LABEL = "Audit Log"
ICON = "shield"

LIST_COLUMNS = ("occurred_at", "actor", "action", "entity_type", "entity_id")


def ensure_schema(conn: sqlite3.Connection) -> None:
    return None


def _row_to_dict(row): return {k: row[k] for k in row.keys()}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def record(conn: sqlite3.Connection, *, actor: str, action: str,
           entity_type: str = "", entity_id: int | None = None,
           changes: dict[str, Any] | None = None,
           ip_address: str = "", user_agent: str = "") -> int:
    """Insert one audit row. Stable signature so callers (hooks / handlers /
    AI tools) can record without reading the schema."""
    cur = conn.execute("""
        INSERT INTO audit_log (actor, action, entity_type, entity_id, changes_json,
                               ip_address, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (actor or "system", action, entity_type or "",
          entity_id, json.dumps(changes or {}),
          ip_address or "", user_agent or ""))
    conn.commit()
    return int(cur.lastrowid)


def list_rows(conn: sqlite3.Connection, *,
              entity_type: str | None = None,
              entity_id: int | None = None,
              actor: str | None = None,
              limit: int = 500) -> list[dict[str, Any]]:
    where = []; params: list[Any] = []
    if entity_type:
        where.append("entity_type = ?"); params.append(entity_type)
    if entity_id is not None:
        where.append("entity_id = ?"); params.append(int(entity_id))
    if actor:
        where.append("actor LIKE ?"); params.append(f"%{actor}%")
    sql = "SELECT * FROM audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY occurred_at DESC, id DESC LIMIT ?"
    params.append(int(limit))
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def get_row(conn, item_id):
    cur = conn.execute("SELECT * FROM audit_log WHERE id = ?", (item_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def _render_list_html(rows) -> str:
    head = "".join(f"<th>{_esc(c.replace('_', ' ').title())}</th>" for c in LIST_COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_esc(row.get(c))}</td>" for c in LIST_COLUMNS)
        body_rows.append(
            f'<tr data-id="{row["id"]}" onclick="location.href=\'/m/audit_log/{row["id"]}\'">'
            f'{cells}</tr>')
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <input type="search" placeholder="Filter by actor / action / entity..." oninput="filter(this.value)">
</div>
<div style="color:var(--dim);font-size:12px;margin-bottom:10px">
  Read-only. Showing the most recent 500 audit entries. Other modules write
  here automatically when they record changes.
</div>
<table class="data-table">
  <thead><tr>{head}</tr></thead>
  <tbody id="rows">{''.join(body_rows) or '<tr><td colspan="5" class="empty">No audit events yet.</td></tr>'}</tbody>
</table>
<script>
function filter(q) {{
  q = (q || '').toLowerCase();
  document.querySelectorAll('#rows tr').forEach(tr => {{
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
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
                      subtitle=f"No event with id {int(item_id)}"))
        return
    fields = [
        ("Occurred at", row.get("occurred_at")),
        ("Actor", row.get("actor")),
        ("Action", row.get("action")),
        ("Entity type", row.get("entity_type")),
        ("Entity id", row.get("entity_id")),
        ("Changes JSON", row.get("changes_json")),
        ("IP address", row.get("ip_address")),
        ("User agent", row.get("user_agent")),
    ]
    handler._html(200, render_detail_page(
        title=f"{row.get('action') or 'event'} — {row.get('entity_type') or 'system'}",
        nav_active=NAME, subtitle=row.get("actor") or "",
        fields=fields, item_id=int(item_id),
    ))


def list_api(handler):
    """GET /api/m/audit_log[?entity_type=&entity_id=&actor=&limit=]"""
    conn = handler.server.conn  # type: ignore[attr-defined]
    qs = getattr(handler, "_query", None) or {}
    if not isinstance(qs, dict):
        qs = {}
    rows = list_rows(
        conn,
        entity_type=qs.get("entity_type") or None,
        entity_id=int(qs["entity_id"]) if qs.get("entity_id") else None,
        actor=qs.get("actor") or None,
        limit=int(qs.get("limit") or 500),
    )
    handler._json({"ok": True, "rows": rows})


ROUTES = {
    "GET": [
        (r"^/api/m/audit_log/?$", list_api),
        (r"^/api/m/audit_log/(\d+)/?$", detail_api_json),
        (r"^/m/audit_log/?$", list_view),
        (r"^/m/audit_log/(\d+)/?$", detail_view),
    ],
    "POST": [],
    "DELETE": [],
}


def _handle_list(args, conn):
    for row in list_rows(conn, limit=getattr(args, "limit", 100)):
        log.info("%s\t%s\t%s\t%s/%s", row["occurred_at"], row["actor"],
                 row["action"], row["entity_type"], row["entity_id"])
    return 0


def _add_list_args(parser):
    parser.add_argument("--limit", type=int, default=100)


CLI = [
    ("audit-list", _add_list_args, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "compliance",
    "requires": [],
    "description": "Read-only compliance audit log of who did what when.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
