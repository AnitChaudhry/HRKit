"""CSV export — one page that exports any module or imported table as CSV.

Two surfaces:

1. ``GET /m/csv_export`` — picker UI: choose module OR imported table,
   optionally narrow to a column subset, download.
2. ``GET /api/m/csv_export/<module>.csv`` — direct streaming export of a
   single module / imported table. Honoured by per-module "Export CSV"
   buttons (rendered by :mod:`hrkit.templates`).

Module exports go through each module's ``list_rows(conn)`` helper so the
output matches what the user sees in the UI. Imported tables go through
:mod:`hrkit.modules.csv_import.safe_select` which is sandboxed to
``imported_*`` tables only.
"""
from __future__ import annotations

import csv
import importlib
import io
import logging
import sqlite3
from typing import Any

from .. import feature_flags

log = logging.getLogger(__name__)

NAME = "csv_export"
LABEL = "CSV Export"
ICON = "download"


def ensure_schema(conn): return None


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------
def _module_rows(conn: sqlite3.Connection,
                 slug: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (rows, columns) by calling ``list_rows`` on a module."""
    if slug not in feature_flags.ALL_MODULES:
        raise ValueError(f"unknown module {slug!r}")
    mod = importlib.import_module(f"hrkit.modules.{slug}")
    list_fn = (
        getattr(mod, "list_rows", None)
        or getattr(mod, "list_requests", None)
        or getattr(mod, "list_runs", None)
        or getattr(mod, "list_records", None)
    )
    if not callable(list_fn):
        raise ValueError(f"module {slug!r} has no list helper")
    rows = list_fn(conn) or []
    if not rows:
        return [], []
    # Use the first row's keys as the canonical column order.
    columns = [k for k in rows[0].keys() if not k.endswith("_json")]
    return rows, columns


def _exportable_modules() -> list[dict[str, str]]:
    """Modules with a ``list_rows`` helper that produces dict rows."""
    out: list[dict[str, str]] = []
    for slug in feature_flags.ALL_MODULES:
        try:
            mod = importlib.import_module(f"hrkit.modules.{slug}")
        except Exception:
            continue
        if not (callable(getattr(mod, "list_rows", None))
                or callable(getattr(mod, "list_requests", None))
                or callable(getattr(mod, "list_runs", None))
                or callable(getattr(mod, "list_records", None))):
            continue
        md = getattr(mod, "MODULE", {}) or {}
        out.append({
            "slug": slug,
            "label": md.get("label") or slug.title(),
            "category": md.get("category") or "",
        })
    return out


def _imported_tables(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    from . import csv_import
    return csv_import.list_imported_tables(conn)


# ---------------------------------------------------------------------------
# Streaming writer
# ---------------------------------------------------------------------------
def _write_csv_response(handler, *, filename: str,
                        columns: list[str],
                        row_iter) -> None:
    """Buffer the CSV in memory then send it. Volume here is bounded by
    the source table sizes (modules + imported tables), so this is safe."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in row_iter:
        writer.writerow([_csv_cell(row, c) for c in columns])
    payload = buf.getvalue().encode("utf-8")
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/csv; charset=utf-8")
        handler.send_header("Content-Disposition",
                            f'attachment; filename="{filename}"')
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
    except Exception:  # noqa: BLE001
        log.exception("csv_export write failed")


def _csv_cell(row, col):
    """Tolerant cell extraction for sqlite3.Row, dict, or namespace."""
    if hasattr(row, "keys"):
        try:
            return row[col]
        except (KeyError, IndexError):
            return ""
    if isinstance(row, dict):
        return row.get(col, "")
    return getattr(row, col, "")


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------
def list_view(handler):
    from hrkit.templates import render_module_page
    conn = handler.server.conn  # type: ignore[attr-defined]
    modules = _exportable_modules()
    imports = _imported_tables(conn)

    mod_opts = "".join(
        f'<option value="module:{_esc(m["slug"])}">'
        f'{_esc(m["label"])} <small>({_esc(m["category"]) or "module"})</small>'
        f'</option>'
        for m in modules)
    imp_opts = "".join(
        f'<option value="imported:{_esc(t["table_name"])}">'
        f'{_esc(t["table_name"])} ({_esc(t["rows"])} rows)</option>'
        for t in imports)

    body = f"""
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <span style="color:var(--dim);font-size:13px;margin-left:auto">
    Export any module's data or any imported CSV table as a downloadable file.</span>
</div>
<div style="background:var(--panel);border:1px solid var(--border);border-radius:8px;
  padding:18px;max-width:560px">
  <h3 style="margin:0 0 12px;font-size:14px">Choose what to export</h3>
  <label style="font-weight:600;display:block;margin-bottom:6px">Source</label>
  <select id="src" style="width:100%;padding:8px 10px;background:var(--bg);
    color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:13px">
    <optgroup label="Modules">{mod_opts or '<option disabled>(none)</option>'}</optgroup>
    <optgroup label="Imported CSVs">{imp_opts or '<option disabled>(none yet — upload via /m/csv_import)</option>'}</optgroup>
  </select>
  <div style="display:flex;gap:10px;margin-top:14px">
    <button id="dl" style="padding:8px 14px">Download CSV</button>
    <button id="cols" class="ghost"
      style="padding:8px 14px;background:transparent;border:1px solid var(--border);
      color:var(--dim)">Show columns first</button>
  </div>
  <div id="cols-out" style="margin-top:14px;font-size:13px;color:var(--dim)"></div>
</div>
<script>
function parseSrc(value) {{
  if (!value) return null;
  const i = value.indexOf(':');
  return {{ kind: value.slice(0, i), name: value.slice(i + 1) }};
}}
document.getElementById('dl').addEventListener('click', async () => {{
  const sel = parseSrc(document.getElementById('src').value);
  if (!sel) {{ hrkit.toast('Pick something to export', 'info'); return; }}
  const url = sel.kind === 'imported'
    ? '/api/m/csv_import/' + encodeURIComponent(sel.name) + '/export.csv'
    : '/api/m/csv_export/' + encodeURIComponent(sel.name) + '.csv';
  window.location.href = url;
}});
document.getElementById('cols').addEventListener('click', async () => {{
  const sel = parseSrc(document.getElementById('src').value);
  if (!sel) return;
  const out = document.getElementById('cols-out');
  out.textContent = 'Loading...';
  try {{
    const url = sel.kind === 'imported'
      ? '/api/m/csv_export/imported/' + encodeURIComponent(sel.name) + '/columns'
      : '/api/m/csv_export/' + encodeURIComponent(sel.name) + '/columns';
    const r = await fetch(url);
    const j = await r.json();
    if (j.ok) {{
      out.innerHTML = '<strong>' + j.columns.length + ' columns:</strong><br><code>'
        + j.columns.join(', ') + '</code>';
    }} else {{
      out.textContent = j.error || 'failed';
    }}
  }} catch (e) {{ out.textContent = e.message; }}
}});
</script>
"""
    handler._html(200, render_module_page(
        title=LABEL, nav_active=NAME, body_html=body))


def module_export_api(handler, slug: str):
    """GET /api/m/csv_export/<slug>.csv — stream a module's list_rows as CSV."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        rows, columns = _module_rows(conn, slug)
    except (ValueError, ImportError) as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400); return
    if not rows:
        handler._json({"ok": False, "error": "no rows to export"}, code=404); return
    _write_csv_response(handler, filename=f"{slug}.csv",
                        columns=columns, row_iter=rows)


def module_columns_api(handler, slug: str):
    """GET /api/m/csv_export/<slug>/columns — preview column list."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        _, columns = _module_rows(conn, slug)
    except (ValueError, ImportError) as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400); return
    handler._json({"ok": True, "columns": columns})


def imported_columns_api(handler, table_name: str):
    """GET /api/m/csv_export/imported/<table>/columns — preview imported columns."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    from . import csv_import
    desc = csv_import.describe_table(conn, table_name)
    if desc is None:
        handler._json({"ok": False, "error": "no such table"}, code=404); return
    handler._json({"ok": True, "columns": [c["name"] for c in desc["columns"]]})


ROUTES = {
    "GET": [
        (r"^/api/m/csv_export/imported/(imported_[a-z0-9_]+)/columns/?$",
         imported_columns_api),
        (r"^/api/m/csv_export/([a-z_]+)/columns/?$", module_columns_api),
        (r"^/api/m/csv_export/([a-z_]+)\.csv$", module_export_api),
        (r"^/m/csv_export/?$", list_view),
    ],
    "POST": [],
    "DELETE": [],
}


def _add_export_args(parser):
    parser.add_argument("--module", required=True,
                        help="Module slug to export (e.g. employee, leave)")
    parser.add_argument("--out", required=True, help="Output CSV path")


def _handle_export(args, conn):
    from pathlib import Path
    rows, columns = _module_rows(conn, args.module)
    if not rows:
        log.warning("no rows to export from %s", args.module)
        return 1
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_csv_cell(row, c) for c in columns])
    log.info("exported %d rows from %s to %s", len(rows), args.module, out_path)
    return 0


CLI = [
    ("csv-export", _add_export_args, _handle_export),
]


MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "category": "data",
    "requires": [],
    "description": "Export any module or imported CSV table back out as CSV.",
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
