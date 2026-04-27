from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

from . import branding
from . import chat as chat_mod
from . import db as dbmod
from . import feature_flags
from . import integrations_ui
from . import recipes_ui
from . import scanner as scanner_mod
from . import settings_ui
from . import uploads
from . import wizard
from .integrations.register import register_default_hooks
from .config import (
    DEFAULT_COLUMNS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_STATUSES,
    IST,
    MARKER,
    db_path,
)
from .frontmatter import dump as fm_dump
from .frontmatter import parse as fm_parse
from .models import Activity, Folder

# Module registry — populated at server startup from hrkit.modules.__all__
# Each entry: {"GET": [(regex, handler_fn, module_slug), ...], "POST": [...], "DELETE": [...]}
# The module_slug is matched against feature_flags.enabled_modules() at dispatch
# time so disabled modules fall through to 404 without a separate route table.
MODULE_ROUTES: dict[str, list[tuple[re.Pattern, Any, str]]] = {
    "GET": [], "POST": [], "DELETE": [],
}


CONN: Any = None
ROOT: Optional[Path] = None

BAD_CHARS = set('\\/<>:"|?*')

_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".html": "text/html; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _mime_for(name: str) -> str:
    return _MIME.get(Path(name).suffix.lower(), "application/octet-stream")


def _pick_resume(attachments: list[str]) -> Optional[str]:
    pdfs = [a for a in attachments if a.lower().endswith(".pdf")]
    if not pdfs:
        return None
    def score(n: str) -> int:
        ln = n.lower()
        if "draft" in ln or "sample" in ln or "plaint" in ln:
            return -10
        if re.search(r"\b(cv|resume|curriculum)\b", ln):
            return 100
        if "cv" in ln or "resume" in ln:
            return 50
        return 0
    pdfs.sort(key=lambda n: (-score(n), n.lower()))
    return pdfs[0]


def _read_evaluation(folder: Path) -> str:
    ev = folder / "evaluation.md"
    if not ev.exists():
        return ""
    try:
        text = ev.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    _, body = fm_parse(text)
    return body or text


def _sanitize_name(name: str) -> str:
    if not name:
        raise ValueError("empty name")
    name = name.strip()
    if not name or name in (".", ".."):
        raise ValueError("invalid name")
    if ".." in name:
        raise ValueError("invalid name")
    for ch in name:
        if ch in BAD_CHARS or ord(ch) < 32:
            raise ValueError(f"invalid character in name: {ch!r}")
    return name


def _sanitize_filename(fn: str) -> str:
    if not fn:
        raise ValueError("empty filename")
    if "/" in fn or "\\" in fn or ".." in fn:
        raise ValueError("invalid filename")
    for ch in fn:
        if ch in '<>:"|?*' or ord(ch) < 32:
            raise ValueError("invalid filename character")
    return fn


def _now_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _as_int(v: Any) -> int:
    if isinstance(v, bool):
        raise ValueError("not an int")
    if isinstance(v, int):
        return v
    return int(str(v))


def _folder_path(f: Folder) -> Path:
    return Path(f.path)


def _read_marker_text(folder: Path) -> str:
    m = folder / MARKER
    return m.read_text(encoding="utf-8", errors="replace") if m.exists() else ""


def _write_marker(folder: Path, fm: dict, body: str) -> None:
    (folder / MARKER).write_text(fm_dump(fm, body), encoding="utf-8")


def _update_task_status(task: Folder, new_status: str) -> None:
    path = _folder_path(task)
    m = path / MARKER
    if not m.exists():
        raise FileNotFoundError(f"no {MARKER} in {path}")
    text = m.read_text(encoding="utf-8", errors="replace")
    now = _now_iso()

    if re.search(r"^status:", text, flags=re.MULTILINE):
        text = re.sub(r"^status:\s*.*$", f'status: "{new_status}"', text,
                      count=1, flags=re.MULTILINE)
    else:
        fm, body = fm_parse(text)
        fm["status"] = new_status
        text = fm_dump(fm, body)

    if re.search(r"^updated:", text, flags=re.MULTILINE):
        text = re.sub(r"^updated:\s*.*$", f'updated: "{now}"', text,
                      count=1, flags=re.MULTILINE)
    else:
        fm, body = fm_parse(text)
        fm["updated"] = now
        text = fm_dump(fm, body)

    if new_status in ("hired", "rejected"):
        if re.search(r"^closed:", text, flags=re.MULTILINE):
            text = re.sub(r"^closed:\s*.*$", f'closed: "{now}"', text,
                          count=1, flags=re.MULTILINE)
        else:
            fm, body = fm_parse(text)
            fm["closed"] = now
            text = fm_dump(fm, body)

    m.write_text(text, encoding="utf-8")


def _get_position_statuses(position: Folder) -> list[str]:
    raw = (position.metadata or {}).get("statuses")
    if isinstance(raw, list) and raw:
        return [str(x).strip().lower() for x in raw if str(x).strip()]
    return list(DEFAULT_STATUSES)


def _get_position_columns(position: Folder) -> list[str]:
    raw = (position.metadata or {}).get("columns")
    if isinstance(raw, list) and raw:
        return [str(x).strip().lower() for x in raw if str(x).strip()]
    return list(DEFAULT_COLUMNS)


def _list_attachments(folder: Folder) -> list[str]:
    path = _folder_path(folder)
    if not path.exists() or not path.is_dir():
        return []
    out: list[str] = []
    try:
        for entry in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_file() and entry.name != MARKER:
                out.append(entry.name)
    except OSError:
        return []
    return out


def _activity_for_folder(folder_id: int, limit: int = 50) -> list[dict]:
    rows = CONN.execute(
        "SELECT * FROM activity WHERE folder_id=? ORDER BY at DESC LIMIT ?",
        (folder_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _open_in_explorer(path: Path) -> None:
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _list_workspace_tree(rel: str = "") -> dict[str, Any]:
    """Return the contents of a workspace subdirectory as a JSON-friendly dict.

    ``rel`` is a forward-slash path relative to ROOT. Empty string means the
    workspace root itself. Raises ``FileNotFoundError`` if the resolved path
    is outside ROOT or does not exist (path traversal protection).
    """
    if ROOT is None:
        raise FileNotFoundError("workspace root is not set")
    rel = (rel or "").strip().lstrip("/").lstrip("\\")
    target = (ROOT / rel).resolve()
    root_resolved = ROOT.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise FileNotFoundError(
            f"path '{rel}' resolves outside the workspace"
        ) from exc
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"directory not found: {rel or '/'}")

    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append({
            "name": child.name,
            "kind": "dir" if child.is_dir() else "file",
            "size": int(stat.st_size) if child.is_file() else 0,
            "modified": int(stat.st_mtime),
            "rel_path": str(child.relative_to(root_resolved)).replace("\\", "/"),
        })
    return {
        "root": str(root_resolved),
        "rel": str(target.relative_to(root_resolved)).replace("\\", "/") if target != root_resolved else "",
        "entries": entries,
    }


def _open_file_os(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _scaffold_task_md(name: str, status: str, priority: str, tags: list[str]) -> str:
    now = _now_iso()
    fm = {
        "type": "task",
        "name": name,
        "status": status,
        "priority": priority or "",
        "tags": list(tags or []),
        "created": now,
        "updated": now,
    }
    body = f"# {name}\n\n"
    return fm_dump(fm, body)


def _safe_count(conn: Any, sql: str) -> int:
    """Run a COUNT(*) query, returning 0 if the table doesn't exist yet."""
    try:
        row = conn.execute(sql).fetchone()
    except Exception:
        return 0
    if row is None:
        return 0
    return int(row[0] if not hasattr(row, "keys") else row[list(row.keys())[0]])


def _collect_home_stats(conn: Any, enabled: list[str]) -> dict[str, int]:
    """Aggregate per-module counters used by the home page.

    Only queries the tables for enabled modules so a workspace with, say,
    recruitment disabled doesn't pay for the candidate count. All counters
    fall back to 0 if the underlying table is missing.
    """
    enabled_set = set(enabled)
    stats: dict[str, int] = {}
    if "employee" in enabled_set:
        stats["employee_count"] = _safe_count(
            conn, "SELECT COUNT(*) FROM employee WHERE status='active'")
    if "department" in enabled_set:
        stats["department_count"] = _safe_count(
            conn, "SELECT COUNT(*) FROM department")
    if "role" in enabled_set:
        stats["role_count"] = _safe_count(
            conn, "SELECT COUNT(*) FROM role")
    if "leave" in enabled_set:
        stats["pending_leave_count"] = _safe_count(
            conn, "SELECT COUNT(*) FROM leave_request WHERE status='pending'")
    if "recruitment" in enabled_set:
        stats["candidate_count"] = _safe_count(
            conn,
            "SELECT COUNT(*) FROM recruitment_candidate "
            "WHERE status NOT IN ('hired','rejected')",
        )
    return stats


def _generated_label() -> str:
    return datetime.now(IST).strftime("%d %b %Y %H:%M IST")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs) -> None:
        return

    def _send(self, code: int, body: bytes,
              content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError):
            pass

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _html(self, code: int, html: str) -> None:
        self._send(code, html.encode("utf-8"), "text/html; charset=utf-8")

    def _read_json(self) -> dict:
        n = int(self.headers.get("content-length", 0) or 0)
        if not n:
            return {}
        raw = self.rfile.read(n).decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON: {e}")

    @property
    def conn(self):
        """Per-request DB connection accessor (kept on the server instance).

        Modules use ``handler.server.conn`` (per AGENTS_SPEC §1) but some
        also probe ``handler.conn`` directly — support both.
        """
        return getattr(self.server, "conn", CONN)

    def do_GET(self) -> None:
        try:
            from . import templates
        except Exception as e:
            self._send(500, f"template import failed: {e}".encode("utf-8"),
                       "text/plain; charset=utf-8")
            return
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/" or path == "":
                # First-run: empty workspace -> wizard
                try:
                    if wizard.needs_wizard(self.conn):
                        self.send_response(302)
                        self.send_header("Location", "/setup")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                except Exception:
                    pass
                self._serve_landing(templates)
                return
            if path == "/activity":
                self._serve_activity(templates)
                return
            if path == "/healthz":
                self._serve_healthz()
                return
            if path == "/settings":
                self._html(200, settings_ui.render_settings_page(self.conn))
                return
            if path == "/integrations":
                self._html(200, integrations_ui.render_integrations_page(self.conn))
                return
            if path == "/api/integrations/state":
                integrations_ui.handle_state(self)
                return
            if path == "/api/integrations/search":
                integrations_ui.handle_search(self)
                return
            if path == "/recipes":
                self._html(200, recipes_ui.render_recipes_page())
                return
            if path == "/api/recipes":
                recipes_ui.handle_list(self)
                return
            if path == "/api/recipes/catalog":
                recipes_ui.handle_catalog(self)
                return
            m = re.match(r"^/api/recipes/([A-Za-z0-9_\-]+)/?$", path)
            if m:
                recipes_ui.handle_get(self, m.group(1))
                return
            if path == "/api/models":
                chat_mod.handle_models(self)
                return
            if path == "/api/chat/conversations":
                chat_mod.handle_list_conversations(self)
                return
            if path == "/api/employees/list":
                chat_mod.handle_employee_picklist(self)
                return
            m = re.match(r"^/api/chat/conversations/(.+)$", path)
            if m:
                from urllib.parse import unquote as _unq
                chat_mod.handle_get_conversation(self, _unq(m.group(1)))
                return
            if path == "/chat":
                self._html(200, chat_mod.render_chat_page(self.conn))
                return
            if path == "/setup":
                self._html(200, wizard.render_wizard_page(self.conn))
                return
            if path == "/api/stats":
                self._json(dbmod.stats(CONN))
                return
            if path == "/api/workspace/tree":
                rel = parse_qs(parsed.query).get("path", [""])[0]
                try:
                    self._json(_list_workspace_tree(rel))
                except FileNotFoundError as exc:
                    self._json({"ok": False, "error": str(exc)}, code=404)
                return

            m = re.match(r"^/api/m/document/(\d+)/download/?$", path)
            if m:
                uploads.serve_uploaded_file(self, int(m.group(1)))
                return

            # Legacy hiring URLs redirect to the new recruitment module.
            # /d/<id> (department) and /p/<id> (position) -> kanban board.
            # /t/<id> (task) -> recruitment candidate detail (best-effort: by
            #                   matching position_folder_id metadata if known).
            # When the recruitment module is disabled, fall back to / instead
            # of leaving the user on a 404.
            recruitment_on = feature_flags.is_enabled("recruitment", CONN)
            if re.match(r"^/d/\d+/?$", path) or re.match(r"^/p/\d+/?$", path):
                self.send_response(302)
                self.send_header(
                    "Location",
                    "/m/recruitment/board" if recruitment_on else "/",
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            m = re.match(r"^/t/(\d+)/?$", path)
            if m:
                if not recruitment_on:
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                # Try to find the matching recruitment_candidate by legacy folder_id.
                target = "/m/recruitment"
                try:
                    folder_id = int(m.group(1))
                    row = self.conn.execute(
                        "SELECT id FROM recruitment_candidate "
                        "WHERE json_extract(metadata_json,'$.legacy_folder_id') = ? LIMIT 1",
                        (folder_id,),
                    ).fetchone()
                    if row:
                        target = f"/m/recruitment/{int(row['id'])}"
                except Exception:
                    pass
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            m = re.match(r"^/api/task/(\d+)/?$", path)
            if m:
                self._api_task(int(m.group(1)))
                return
            m = re.match(r"^/files/(\d+)/(.+)$", path)
            if m:
                self._serve_file(int(m.group(1)), unquote(m.group(2)))
                return

            # Module registry dispatch
            if self._dispatch_module("GET", path):
                return

            self._send(404, b"404 not found", "text/plain; charset=utf-8")
        except Exception as e:
            self._send(500, f"server error: {e}".encode("utf-8"),
                       "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/move":
                self._api_move()
                return
            if path == "/api/scan":
                self._api_scan()
                return
            if path == "/api/open-folder":
                self._api_open_folder()
                return
            if path == "/api/workspace/open":
                self._api_open_workspace()
                return
            if path == "/api/open-file":
                self._api_open_file()
                return
            if path == "/api/create-task":
                self._api_create_task()
                return
            if path == "/api/settings":
                settings_ui.handle_save_settings(self, self._read_json())
                return
            if path == "/api/settings/modules":
                settings_ui.handle_save_modules(self, self._read_json())
                return
            if path == "/api/settings/test":
                settings_ui.handle_test_connection(self, self._read_json())
                return
            if path == "/api/chat":
                # chat handler is async — run it on the per-thread event loop
                import asyncio
                asyncio.run(chat_mod.handle_chat_message(self, self._read_json()))
                return
            if path == "/api/wizard":
                wizard.handle_wizard_step(self, self._read_json())
                return
            if path == "/api/integrations/connect":
                integrations_ui.handle_connect(self, self._read_json())
                return
            if path == "/api/integrations/tool":
                integrations_ui.handle_tool_toggle(self, self._read_json())
                return
            if path == "/api/integrations/test":
                integrations_ui.handle_tool_test(self, self._read_json())
                return
            if path == "/api/recipes":
                recipes_ui.handle_save(self, self._read_json())
                return
            m = re.match(r"^/api/recipes/([A-Za-z0-9_\-]+)/run/?$", path)
            if m:
                recipes_ui.handle_run(self, m.group(1), self._read_json())
                return
            if path == "/api/m/document/upload":
                uploads.handle_document_upload(self)
                return
            if path == "/api/chat/upload":
                uploads.handle_chat_upload(self)
                return

            # Module registry dispatch
            if self._dispatch_module("POST", path):
                return

            self._json({"ok": False, "error": "not found"}, 404)
        except ValueError as e:
            self._json({"ok": False, "error": str(e)}, 400)
        except FileNotFoundError as e:
            self._json({"ok": False, "error": str(e)}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)

    def do_DELETE(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            m = re.match(r"^/api/recipes/([A-Za-z0-9_\-]+)/?$", path)
            if m:
                recipes_ui.handle_delete(self, m.group(1))
                return
            if self._dispatch_module("DELETE", path):
                return
            self._json({"ok": False, "error": "not found"}, 404)
        except ValueError as e:
            self._json({"ok": False, "error": str(e)}, 400)
        except FileNotFoundError as e:
            self._json({"ok": False, "error": str(e)}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)

    def _dispatch_module(self, method: str, path: str) -> bool:
        """Try to match path against module registry. Returns True if handled.

        Routes whose owning module is disabled in feature_flags fall through
        so the request reaches the 404 branch.
        """
        enabled = set(feature_flags.enabled_modules(CONN))
        for pattern, handler_fn, slug in MODULE_ROUTES.get(method, []):
            m = pattern.match(path)
            if m:
                if slug not in enabled:
                    continue
                handler_fn(self, *m.groups())
                return True
        return False

    # ---- GET handlers -------------------------------------------------------
    def _serve_landing(self, templates) -> None:
        root_name = ROOT.name if ROOT else "Workspace"
        enabled = feature_flags.enabled_modules(CONN)
        stats = _collect_home_stats(CONN, enabled)
        html = templates.render_home_page(
            root_name=root_name, stats=stats, enabled=enabled,
        )
        self._html(200, html)

    def _serve_activity(self, templates) -> None:
        act = dbmod.recent_activity(CONN, 100)
        html = templates.render_activity_page(act)
        self._html(200, html)

    def _api_task(self, task_id: int) -> None:
        task = dbmod.folder_by_id(CONN, task_id)
        if not task or task.type != "task":
            self._json({"ok": False, "error": "task not found"}, 404)
            return
        parent = dbmod.folder_by_id(CONN, task.parent_id) if task.parent_id else None
        attach_paths = _list_attachments(task)
        folder_path = _folder_path(task)
        attachments = []
        for fn in attach_paths:
            try:
                sz = (folder_path / fn).stat().st_size
            except OSError:
                sz = 0
            attachments.append({"name": fn, "size": sz})
        activity = _activity_for_folder(task_id, 100)
        md = task.metadata or {}
        has_eval = (folder_path / "evaluation.md").exists() or \
                   bool(md.get("has_evaluation") or md.get("evaluated"))
        evaluation_body = _read_evaluation(folder_path) if has_eval else ""
        resume = _pick_resume(attach_paths)
        self._json({
            "ok": True,
            "id": task.id,
            "name": task.name,
            "path": task.path,
            "status": task.status,
            "priority": task.priority,
            "tags": task.tags,
            "body": task.body,
            "metadata": md,
            "created": task.created,
            "updated": task.updated,
            "closed": task.closed,
            "parent": {
                "id": parent.id, "name": parent.name, "type": parent.type,
            } if parent else None,
            "attachments": attachments,
            "activity": activity,
            "has_evaluation": has_eval,
            "evaluation_body": evaluation_body,
            "resume_filename": resume,
        })

    def _serve_file(self, task_id: int, filename: str) -> None:
        if ".." in filename or "/" in filename or "\\" in filename:
            self._send(400, b"invalid filename", "text/plain; charset=utf-8")
            return
        task = dbmod.folder_by_id(CONN, task_id)
        if not task:
            self._send(404, b"task not found", "text/plain; charset=utf-8")
            return
        folder = _folder_path(task)
        target = (folder / filename).resolve()
        try:
            folder_r = folder.resolve()
        except OSError:
            self._send(500, b"path error", "text/plain; charset=utf-8")
            return
        try:
            target.relative_to(folder_r)
        except ValueError:
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        if not target.exists() or not target.is_file():
            self._send(404, b"file not found", "text/plain; charset=utf-8")
            return
        try:
            data = target.read_bytes()
        except OSError as e:
            self._send(500, f"read error: {e}".encode("utf-8"), "text/plain; charset=utf-8")
            return
        mime = _mime_for(filename)
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("Content-Disposition", f'inline; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _serve_healthz(self) -> None:
        ok = CONN is not None and ROOT is not None and ROOT.exists()
        self._json({
            "ok": True,
            "root": str(ROOT) if ROOT else "",
            "db": str(db_path(ROOT)) if ROOT else "",
            "workspace_ok": bool(ok),
        })

    # ---- POST handlers ------------------------------------------------------
    def _api_move(self) -> None:
        body = self._read_json()
        task_id = _as_int(body.get("task_id"))
        new_status = str(body.get("status", "")).strip().lower()
        if not new_status:
            raise ValueError("status required")

        task = dbmod.folder_by_id(CONN, task_id)
        if not task or task.type != "task":
            raise FileNotFoundError("task not found")

        parent_pos = dbmod.folder_by_id(CONN, task.parent_id) if task.parent_id else None
        allowed = _get_position_statuses(parent_pos) if parent_pos else list(DEFAULT_STATUSES)
        if new_status not in allowed:
            raise ValueError(f"status '{new_status}' not allowed (valid: {', '.join(allowed)})")

        old_status = task.status or ""
        _update_task_status(task, new_status)

        # Re-read from disk to refresh DB row
        text = _read_marker_text(_folder_path(task))
        fm, body_md = fm_parse(text)
        task.status = new_status
        task.updated = str(fm.get("updated", task.updated))
        task.closed = str(fm.get("closed", task.closed))
        task.body = body_md
        reserved = {"type", "name", "status", "priority", "tags"}
        task.metadata = {k: v for k, v in fm.items() if k not in reserved}
        dbmod.upsert_folder(CONN, task)

        dbmod.log_activity(CONN, Activity(
            folder_id=task_id, action="status_change",
            from_value=old_status, to_value=new_status,
            actor="user", note="",
        ))
        self._json({"ok": True, "status": new_status})

    def _api_scan(self) -> None:
        if ROOT is None:
            raise ValueError("no workspace root")
        summary = scanner_mod.scan(CONN, ROOT, actor="user")
        self._json({"ok": True, **summary})

    def _api_open_folder(self) -> None:
        body = self._read_json()
        fid = _as_int(body.get("folder_id"))
        f = dbmod.folder_by_id(CONN, fid)
        if not f:
            raise FileNotFoundError("folder not found")
        path = _folder_path(f)
        if not path.exists():
            raise FileNotFoundError(f"folder missing on disk: {path}")
        _open_in_explorer(path)
        self._json({"ok": True})

    def _api_open_workspace(self) -> None:
        """POST /api/workspace/open — open a workspace path in OS file manager.

        Body: ``{"path": "<rel>"}`` where rel is empty for the workspace root,
        otherwise a forward-slash path relative to ROOT. Path traversal is
        blocked: anything resolving outside ROOT raises FileNotFoundError.
        """
        body = self._read_json()
        rel = str(body.get("path") or "").strip().lstrip("/").lstrip("\\")
        if ROOT is None:
            raise FileNotFoundError("workspace root is not set")
        target = (ROOT / rel).resolve()
        root_resolved = ROOT.resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError as exc:
            raise FileNotFoundError(
                f"path '{rel}' resolves outside the workspace"
            ) from exc
        if not target.exists():
            raise FileNotFoundError(f"path not found: {rel or '/'}")
        _open_in_explorer(target if target.is_dir() else target.parent)
        self._json({"ok": True, "opened": str(target)})

    def _api_open_file(self) -> None:
        body = self._read_json()
        fid = _as_int(body.get("folder_id"))
        filename = _sanitize_filename(str(body.get("filename", "")).strip())
        f = dbmod.folder_by_id(CONN, fid)
        if not f:
            raise FileNotFoundError("folder not found")
        target = _folder_path(f) / filename
        try:
            target_resolved = target.resolve()
            parent_resolved = _folder_path(f).resolve()
        except OSError:
            raise FileNotFoundError("cannot resolve path")
        if parent_resolved not in target_resolved.parents and target_resolved != parent_resolved:
            raise ValueError("filename escapes folder")
        if not target_resolved.exists() or not target_resolved.is_file():
            raise FileNotFoundError(f"file not found: {filename}")
        _open_file_os(target_resolved)
        self._json({"ok": True})

    def _api_create_task(self) -> None:
        body = self._read_json()
        pos_id = _as_int(body.get("position_id"))
        raw_name = str(body.get("name", "")).strip()
        name = _sanitize_name(raw_name)
        status = str(body.get("status", "applied")).strip().lower() or "applied"
        priority = str(body.get("priority", "")).strip().lower()
        tags = body.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t).strip() for t in tags if str(t).strip()]

        pos = dbmod.folder_by_id(CONN, pos_id)
        if not pos or pos.type != "position":
            raise FileNotFoundError("position not found")

        allowed = _get_position_statuses(pos)
        if status not in allowed:
            status = "applied" if "applied" in allowed else allowed[0]

        pos_path = _folder_path(pos)
        if not pos_path.exists():
            raise FileNotFoundError(f"position folder missing: {pos_path}")

        new_path = pos_path / name
        if new_path.exists():
            raise ValueError(f"folder already exists: {name}")

        new_path.mkdir(parents=True, exist_ok=False)
        md = _scaffold_task_md(name, status, priority, tags)
        (new_path / MARKER).write_text(md, encoding="utf-8")

        now = _now_iso()
        normalized_path = str(new_path.resolve()).replace("\\", "/")
        f = Folder(
            path=normalized_path,
            parent_id=pos_id,
            type="task",
            name=name,
            status=status,
            priority=priority,
            tags=tags,
            metadata={},
            body=f"# {name}\n\n",
            created=now,
            updated=now,
        )
        new_id = dbmod.upsert_folder(CONN, f)
        dbmod.log_activity(CONN, Activity(
            folder_id=new_id, action="created",
            to_value="task", actor="user", note=name,
        ))
        self._json({"ok": True, "id": new_id, "path": normalized_path})


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _register_modules() -> int:
    """Import every module in hrkit.modules.__all__ and register its
    routes into MODULE_ROUTES. Returns the count of modules registered."""
    import importlib
    from . import modules as mods_pkg

    count = 0
    for name in getattr(mods_pkg, "__all__", []):
        try:
            mod = importlib.import_module(f"hrkit.modules.{name}")
            module_dict = getattr(mod, "MODULE", None)
            if not module_dict:
                continue
            slug = module_dict.get("name") or name
            routes = module_dict.get("routes", {}) or {}
            for method in ("GET", "POST", "DELETE"):
                for pattern_str, handler_fn in routes.get(method, []):
                    MODULE_ROUTES[method].append(
                        (re.compile(pattern_str), handler_fn, slug)
                    )
            count += 1
        except Exception as exc:
            print(f"warning: could not load module '{name}': {exc}",
                  file=sys.stderr)
    return count


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
        root: Optional[Path] = None, *, open_browser: bool = True) -> int:
    global CONN, ROOT
    if root is None:
        raise ValueError("root is required")
    ROOT = Path(root).resolve()
    if not ROOT.exists():
        raise FileNotFoundError(f"workspace not found: {ROOT}")

    # Load .env if present so env vars override DB settings
    try:
        from .config import load_dotenv_if_present
        load_dotenv_if_present(ROOT)
    except Exception:
        pass

    CONN = dbmod.open_db(db_path(ROOT))

    # Register HR module routes
    module_count = _register_modules()

    # Register Composio integration hooks (recruitment.hired -> Gmail offer letter,
    # leave.approved -> Calendar block, payroll.payslip_generated -> Drive upload).
    # Idempotent — safe even if called twice.
    register_default_hooks()

    # Force localhost bind only
    if host not in ("127.0.0.1", "localhost", "::1"):
        host = "127.0.0.1"

    server = ThreadedHTTPServer((host, port), Handler)
    server.conn = CONN  # type: ignore[attr-defined]  # for handler.server.conn
    url = f"http://{host}:{port}/"
    name = branding.app_name()
    print(f"{name}: {url}")
    print(f"  root    = {ROOT}")
    print(f"  db      = {db_path(ROOT)}")
    print(f"  modules = {module_count} registered")
    print("Ctrl+C to stop.")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
        server.server_close()
    return 0
