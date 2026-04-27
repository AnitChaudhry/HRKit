"""CSV import — turn an uploaded CSV into a queryable SQLite table.

Owns no static schema; instead, each upload creates a new table named
``imported_<sanitized_csv_basename>`` with columns inferred from the CSV
header. The AI agent can then read these tables via the
``query_imported_table`` tool wired in :mod:`hrkit.chat`.

Safety:
- All created tables MUST be prefixed with ``imported_`` so user-supplied
  names can never clobber HR-Kit core tables.
- Identifiers are quoted with ``"…"`` and have non-alphanumeric chars
  stripped, so even malicious header text can't break out of the DDL.
- Row inserts use parameterized queries.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

NAME = "csv_import"
LABEL = "CSV Import"
ICON = "upload"

LIST_COLUMNS = ("table_name", "columns", "rows", "created")
TABLE_PREFIX = "imported_"
SQL_TYPES = ("TEXT", "INTEGER", "REAL")
MAX_PREVIEW_ROWS = 25
MAX_DETECT_ROWS = 200


def ensure_schema(conn): return None


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


# ---------------------------------------------------------------------------
# Identifier sanitization
# ---------------------------------------------------------------------------
_IDENT_RE = re.compile(r"[^a-z0-9_]+")


def _sanitize_ident(raw: str, fallback: str = "col") -> str:
    """Lowercase, ASCII-strip, collapse to underscores. Prefix with the
    fallback if the sanitized result is empty or starts with a digit."""
    s = (raw or "").strip().lower()
    s = _IDENT_RE.sub("_", s)
    s = s.strip("_")
    if not s:
        s = fallback
    if s[0].isdigit():
        s = f"{fallback}_{s}"
    return s[:60]


def _table_name_for(filename: str) -> str:
    """Turn an uploaded filename into ``imported_<slug>``."""
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    base = base.rsplit(".", 1)[0]
    slug = _sanitize_ident(base, fallback="csv")
    return TABLE_PREFIX + slug


def _unique_columns(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for h in headers:
        col = _sanitize_ident(h, fallback="col")
        if col in seen:
            seen[col] += 1
            col = f"{col}_{seen[col]}"
        else:
            seen[col] = 0
        out.append(col)
    return out


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------
_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$|^-?\.\d+$|^-?\d+\.$")


def _infer_column_types(rows: list[list[str]],
                        ncols: int) -> list[str]:
    """Sample up to MAX_DETECT_ROWS to guess each column's SQL type."""
    types: list[str] = []
    for col_idx in range(ncols):
        all_int = True
        all_num = True
        any_value = False
        for row in rows[:MAX_DETECT_ROWS]:
            if col_idx >= len(row):
                continue
            val = (row[col_idx] or "").strip()
            if val == "":
                continue
            any_value = True
            if not _INT_RE.match(val):
                all_int = False
            if not (_INT_RE.match(val) or _FLOAT_RE.match(val)):
                all_num = False
                break
        if not any_value:
            types.append("TEXT")
        elif all_int:
            types.append("INTEGER")
        elif all_num:
            types.append("REAL")
        else:
            types.append("TEXT")
    return types


def _coerce_value(val: str, sql_type: str) -> Any:
    if val is None or val == "":
        return None
    if sql_type == "INTEGER":
        try:
            return int(val)
        except (TypeError, ValueError):
            return val  # fall back to raw string; SQLite will store as TEXT
    if sql_type == "REAL":
        try:
            return float(val)
        except (TypeError, ValueError):
            return val
    return val


# ---------------------------------------------------------------------------
# Public ops
# ---------------------------------------------------------------------------
def list_imported_tables(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return every ``imported_*`` table with row count + column count."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'imported_%' ORDER BY name"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        name = r["name"]
        try:
            cols = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
            count_row = conn.execute(f'SELECT COUNT(*) AS n FROM "{name}"').fetchone()
        except sqlite3.Error:
            cols = []
            count_row = None
        out.append({
            "table_name": name,
            "columns": ", ".join(c[1] for c in cols),
            "rows": count_row[0] if count_row else 0,
            # Created timestamp isn't tracked separately; we include the table
            # name so the UI can sort lexicographically without a real ts.
            "created": "",
            "schema": [{"name": c[1], "type": c[2]} for c in cols],
        })
    return out


def describe_table(conn: sqlite3.Connection, table_name: str) -> dict[str, Any] | None:
    """Return ``{table_name, columns, rows}`` for a single imported table.

    Refuses any name that doesn't start with ``imported_`` — this is the
    sandbox boundary that prevents the AI / API from describing core tables.
    """
    if not _is_imported(table_name):
        return None
    cols = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    if not cols:
        return None
    count_row = conn.execute(f'SELECT COUNT(*) AS n FROM "{table_name}"').fetchone()
    return {
        "table_name": table_name,
        "columns": [{"name": c[1], "type": c[2]} for c in cols],
        "rows": count_row[0] if count_row else 0,
    }


def _is_imported(name: str) -> bool:
    """Strict allowlist: identifier-safe and starts with the imported_ prefix."""
    if not name or not isinstance(name, str):
        return False
    if not name.startswith(TABLE_PREFIX):
        return False
    return bool(re.match(r"^[a-z0-9_]+$", name))


def import_csv(conn: sqlite3.Connection, *,
               filename: str,
               raw_bytes: bytes,
               replace: bool = False) -> dict[str, Any]:
    """Parse the CSV bytes, create ``imported_<slug>``, insert rows.

    Returns ``{table, columns, rows_inserted, replaced}``. Raises
    :class:`ValueError` on malformed input or naming collisions.
    """
    if not raw_bytes:
        raise ValueError("empty file")
    table = _table_name_for(filename)
    if not _is_imported(table):
        raise ValueError(f"could not derive a safe table name from {filename!r}")

    # Decode as utf-8-sig to strip BOM if present, fall back to latin-1.
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="replace")

    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise ValueError("CSV has no header row") from exc
    if not headers:
        raise ValueError("CSV header is empty")

    columns = _unique_columns(headers)
    data_rows = [row for row in reader if row]
    if not data_rows:
        raise ValueError("CSV has no data rows")

    types = _infer_column_types(data_rows, len(columns))
    # Normalize: pad short rows with None, truncate long rows.
    ncols = len(columns)
    normalized: list[list[Any]] = []
    for row in data_rows:
        padded = list(row[:ncols]) + [""] * max(0, ncols - len(row))
        normalized.append([_coerce_value(v, types[i]) for i, v in enumerate(padded)])

    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None
    if table_exists and not replace:
        raise ValueError(
            f"table {table!r} already exists — pass replace=true to overwrite")

    if table_exists:
        conn.execute(f'DROP TABLE "{table}"')

    cols_ddl = ", ".join(f'"{c}" {t}' for c, t in zip(columns, types))
    conn.execute(f'CREATE TABLE "{table}" ({cols_ddl})')

    placeholders = ", ".join("?" for _ in columns)
    quoted_cols = ", ".join(f'"{c}"' for c in columns)
    conn.executemany(
        f'INSERT INTO "{table}" ({quoted_cols}) VALUES ({placeholders})',
        normalized,
    )
    conn.commit()

    return {
        "table": table,
        "columns": [{"name": c, "type": t} for c, t in zip(columns, types)],
        "rows_inserted": len(normalized),
        "replaced": table_exists,
    }


def drop_table(conn: sqlite3.Connection, table_name: str) -> bool:
    """Drop an imported table. Refuses anything outside the sandbox."""
    if not _is_imported(table_name):
        return False
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.commit()
    return True


def safe_select(conn: sqlite3.Connection, table_name: str, *,
                columns: list[str] | None = None,
                where: dict[str, Any] | None = None,
                limit: int = 100) -> dict[str, Any]:
    """Run a parameterized SELECT against an imported table.

    - ``columns``: list of column names to project, all must exist on the
      table; ``None`` means ``*``.
    - ``where``: dict of ``{column: value}`` pairs, ANDed with ``=``. Values
      pass through as parameters; column names are validated against the
      table's schema before interpolation.
    - ``limit``: capped at 1000.

    Returns ``{columns, rows, total}``. Refuses tables outside the sandbox.
    """
    desc = describe_table(conn, table_name)
    if desc is None:
        raise ValueError(f"unknown imported table: {table_name!r}")
    valid_cols = {c["name"] for c in desc["columns"]}

    if columns:
        bad = [c for c in columns if c not in valid_cols]
        if bad:
            raise ValueError(f"unknown columns: {bad}")
        select_cols = ", ".join(f'"{c}"' for c in columns)
    else:
        columns = [c["name"] for c in desc["columns"]]
        select_cols = ", ".join(f'"{c}"' for c in columns)

    where = where or {}
    bad_where = [c for c in where if c not in valid_cols]
    if bad_where:
        raise ValueError(f"unknown where columns: {bad_where}")
    where_sql = ""
    params: list[Any] = []
    if where:
        clauses = []
        for col, val in where.items():
            clauses.append(f'"{col}" = ?')
            params.append(val)
        where_sql = " WHERE " + " AND ".join(clauses)

    try:
        limit = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        limit = 100
    params.append(limit)

    rows = conn.execute(
        f'SELECT {select_cols} FROM "{table_name}"{where_sql} LIMIT ?', params
    ).fetchall()
    return {
        "columns": columns,
        "rows": [dict(r) for r in rows],
        "total": desc["rows"],
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def _render_list_html(tables: list[dict[str, Any]]) -> str:
    rows_html = []
    for t in tables:
        rows_html.append(
            f'<tr><td><a href="/m/csv_import/{_esc(t["table_name"])}">'
            f'{_esc(t["table_name"])}</a></td>'
            f'<td>{_esc(t["columns"])}</td>'
            f'<td>{_esc(t["rows"])}</td>'
            f'<td><button onclick="dropTable(\'{_esc(t["table_name"])}\')">'
            f'Drop</button></td></tr>')
    body = "".join(rows_html) or (
        '<tr><td colspan="4" class="empty">No imported tables yet. Upload a '
        'CSV above to create one.</td></tr>'
    )
    return f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <span style="color:var(--dim);font-size:13px;margin-left:auto">
    Each upload creates a queryable <code>imported_*</code> table the AI agent can read.</span>
</div>
<div style="background:var(--panel);border:1px solid var(--border);border-radius:8px;
  padding:16px;margin-bottom:18px">
  <h3 style="margin:0 0 12px;font-size:14px">Upload a CSV</h3>
  <form id="up-form" enctype="multipart/form-data"
    style="display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:end">
    <input type="file" name="file" id="up-file" accept=".csv,text/csv" required>
    <label style="display:flex;gap:6px;align-items:center;font-size:13px;font-weight:normal">
      <input type="checkbox" id="up-replace" name="replace" value="1" style="width:auto">
      Replace if a table with this name exists
    </label>
    <button id="up-btn">Upload &amp; create table</button>
  </form>
  <div id="up-status" style="margin-top:10px;font-size:13px;color:var(--dim)"></div>
</div>
<table class="data-table">
  <thead><tr><th>Table</th><th>Columns</th><th>Rows</th><th></th></tr></thead>
  <tbody>{body}</tbody>
</table>
<script>
const form = document.getElementById('up-form');
const status = document.getElementById('up-status');
form.addEventListener('submit', async (ev) => {{
  ev.preventDefault();
  const fd = new FormData(form);
  if (!document.getElementById('up-replace').checked) fd.delete('replace');
  status.textContent = 'Uploading...';
  status.style.color = 'var(--dim)';
  try {{
    const r = await fetch('/api/m/csv_import/upload', {{method: 'POST', body: fd}});
    const j = await r.json();
    if (j.ok) {{
      status.style.color = 'var(--ok, #15803d)';
      status.textContent = `Created ${{j.table}} with ${{j.rows_inserted}} rows.`;
      setTimeout(() => location.reload(), 800);
    }} else {{
      status.style.color = 'var(--err, #b91c1c)';
      status.textContent = j.error || 'Upload failed';
    }}
  }} catch (e) {{
    status.style.color = 'var(--err, #b91c1c)';
    status.textContent = e.message || 'Upload failed';
  }}
}});
async function dropTable(name) {{
  if (!(await hrkit.confirmDialog(`Drop table ${{name}}? This deletes all imported rows.`))) return;
  const r = await fetch('/api/m/csv_import/' + encodeURIComponent(name), {{method: 'DELETE'}});
  if (r.ok) location.reload(); else hrkit.toast('Drop failed', 'error');
}}
</script>
"""


def _render_detail_html(table_name: str, desc: dict[str, Any],
                        preview: dict[str, Any]) -> str:
    cols_html = "".join(
        f"<tr><td><code>{_esc(c['name'])}</code></td>"
        f"<td>{_esc(c['type'])}</td></tr>"
        for c in desc["columns"])
    head = "".join(f"<th>{_esc(c['name'])}</th>" for c in desc["columns"])
    body_rows = []
    for row in preview["rows"]:
        cells = "".join(f"<td>{_esc(row.get(c['name']))}</td>" for c in desc["columns"])
        body_rows.append(f"<tr>{cells}</tr>")
    return f"""
<div class="module-toolbar">
  <h1>{_esc(table_name)}</h1>
  <a href="/m/csv_import" style="font-size:13px;color:var(--accent);text-decoration:none">
    &larr; Back to imports</a>
  <a href="/api/m/csv_import/{_esc(table_name)}/export.csv" download
    style="padding:7px 14px;border:1px solid var(--border);border-radius:6px;
    color:var(--dim);text-decoration:none;font-size:13px">Download CSV</a>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px">
  <div>
    <h3 style="margin:0 0 8px;font-size:14px">Schema</h3>
    <table class="data-table">
      <thead><tr><th>Column</th><th>Type</th></tr></thead>
      <tbody>{cols_html}</tbody>
    </table>
  </div>
  <div>
    <h3 style="margin:0 0 8px;font-size:14px">Stats</h3>
    <p>{desc["rows"]} rows total. Showing first {len(preview["rows"])}.</p>
    <p>The AI agent can query this table via the
       <code>query_imported_table</code> tool.</p>
  </div>
</div>
<h3 style="margin:0 0 8px;font-size:14px">Preview</h3>
<table class="data-table">
  <thead><tr>{head}</tr></thead>
  <tbody>{''.join(body_rows) or '<tr><td colspan="999" class="empty">No rows.</td></tr>'}</tbody>
</table>
"""


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------
def list_view(handler):
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME,
        body_html=_render_list_html(list_imported_tables(conn))))


def detail_view(handler, table_name: str):
    from hrkit.templates import render_module_page, render_detail_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    desc = describe_table(conn, table_name)
    if desc is None:
        handler._html(404, render_detail_page(
            title="Not found", nav_active=NAME,
            subtitle=f"No imported table named {table_name!r}"))
        return
    preview = safe_select(conn, table_name, limit=MAX_PREVIEW_ROWS)
    handler._html(200, render_module_page(
        title=table_name, nav_active=NAME,
        body_html=_render_detail_html(table_name, desc, preview)))


def upload_api(handler):
    from hrkit import uploads
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        parsed = uploads.parse_multipart(handler)
    except ValueError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400)
        return
    files = parsed.get("files") or []
    if not files:
        handler._json({"ok": False, "error": "no file uploaded"}, code=400); return
    file = files[0]
    replace = bool(parsed.get("fields", {}).get("replace"))
    try:
        result = import_csv(
            conn, filename=file.get("filename") or "upload.csv",
            raw_bytes=file.get("data") or b"", replace=replace)
    except ValueError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400); return
    except sqlite3.Error as exc:
        log.exception("csv import DB error")
        handler._json({"ok": False, "error": str(exc)}, code=500); return
    result["ok"] = True
    handler._json(result, code=201)


def drop_api(handler, table_name: str):
    conn = handler.server.conn  # type: ignore[attr-defined]
    if not drop_table(conn, table_name):
        handler._json({"ok": False, "error": "refused or no such table"}, code=400); return
    handler._json({"ok": True})


def export_csv_api(handler, table_name: str):
    """Stream the entire imported table as CSV for download."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    desc = describe_table(conn, table_name)
    if desc is None:
        handler._json({"ok": False, "error": "no such table"}, code=404); return
    cols = [c["name"] for c in desc["columns"]]
    quoted_cols = ", ".join(f'"{c}"' for c in cols)
    cur = conn.execute(f'SELECT {quoted_cols} FROM "{table_name}"')
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for row in cur:
        writer.writerow([row[c] for c in cols])
    payload = buf.getvalue().encode("utf-8")
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/csv; charset=utf-8")
        handler.send_header("Content-Disposition",
                            f'attachment; filename="{table_name}.csv"')
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
    except Exception:  # noqa: BLE001
        log.exception("csv export write failed")


ROUTES = {
    "GET": [
        (r"^/api/m/csv_import/(imported_[a-z0-9_]+)/export\.csv$", export_csv_api),
        (r"^/m/csv_import/?$", list_view),
        (r"^/m/csv_import/(imported_[a-z0-9_]+)/?$", detail_view),
    ],
    "POST": [
        (r"^/api/m/csv_import/upload/?$", upload_api),
    ],
    "DELETE": [
        (r"^/api/m/csv_import/(imported_[a-z0-9_]+)/?$", drop_api),
    ],
}


def _add_import_args(parser):
    parser.add_argument("--file", required=True, help="Path to a CSV file")
    parser.add_argument("--replace", action="store_true",
                        help="Drop the existing imported table if present")


def _handle_import(args, conn):
    from pathlib import Path
    p = Path(args.file)
    if not p.is_file():
        log.error("CSV not found: %s", p)
        return 1
    result = import_csv(conn, filename=p.name,
                        raw_bytes=p.read_bytes(), replace=args.replace)
    log.info("imported %s: %s rows, columns=%s",
             result["table"], result["rows_inserted"],
             [c["name"] for c in result["columns"]])
    return 0


def _handle_list(args, conn):
    for t in list_imported_tables(conn):
        log.info("%s\t%s rows\t(%s)", t["table_name"], t["rows"], t["columns"])
    return 0


CLI = [
    ("csv-import", _add_import_args, _handle_import),
    ("csv-imports-list", lambda p: None, _handle_list),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "data",
    "requires": [],
    "description": "Upload CSVs to create queryable imported_* tables for AI analysis.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
