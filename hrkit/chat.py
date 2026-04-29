"""AI chat endpoint with module CRUD as tools.

Wave 4 / Agent A3.

Public surface:
    render_chat_page() -> str
    handle_chat_message(handler, body: dict) -> None  (async)

The chat surface is intentionally thin: a single ``query_records`` tool is
exposed to the agent that dispatches to the right module's ``list_rows`` /
``get_row`` / ``create_row`` / ``delete_row`` helpers (looked up by slug from
``hrkit.modules.__all__``). This is far simpler than registering 44 individual
tools and keeps the system prompt small.

Wave 4-B (server integrator) is responsible for wiring ``GET /chat`` to
``render_chat_page`` and ``POST /api/chat`` to ``handle_chat_message``.
"""

from __future__ import annotations

import importlib
import json
import logging
import traceback
from typing import Any, Callable

from pathlib import Path

from hrkit import (
    ai, ai_tools, artifacts, branding, chat_storage, composio_sdk,
    employee_fs, recipes_ui, sandbox, uploads,
)
from hrkit.templates import render_module_page

log = logging.getLogger(__name__)

# Operations the agent can ask query_records to perform. Kept as module-level
# constants so the dispatcher and the system prompt stay in sync.
_ALLOWED_OPS = ("list", "get", "create", "update", "delete")


# ---------------------------------------------------------------------------
# Module dispatch
# ---------------------------------------------------------------------------
def _allowed_modules(conn=None) -> list[str]:
    """Return the module slugs the agent may touch right now.

    Filters ``hrkit.modules.__all__`` through :mod:`feature_flags` so disabled
    modules disappear from the agent's view — both in the system prompt and
    in dispatch validation. With ``conn=None`` falls back to the registered
    set of all modules (used at import time before a workspace is available).
    """
    pkg = importlib.import_module("hrkit.modules")
    universe = list(getattr(pkg, "__all__", []))
    if conn is None:
        return universe
    try:
        from . import feature_flags
        enabled = set(feature_flags.enabled_modules(conn))
    except Exception:
        return universe
    return [m for m in universe if m in enabled]


def _load_module(slug: str, conn=None):
    """Import ``hrkit.modules.<slug>`` if it is whitelisted.

    Raises ``ValueError`` for unknown slugs (or slugs whose module is
    disabled in this workspace) so the LLM gets a clear, short error
    string back through the tool channel.
    """
    allowed = _allowed_modules(conn)
    if slug not in allowed:
        raise ValueError(
            f"module '{slug}' is not available. allowed: {', '.join(allowed)}"
        )
    return importlib.import_module(f"hrkit.modules.{slug}")


def _resolve_helper(mod, op: str) -> Callable:
    """Find the per-module helper for ``op``, accommodating naming variations.

    Most modules expose plain ``list_rows`` / ``get_row`` / ``create_row`` /
    ``delete_row``. A few use domain names (``list_requests``, ``create_run``
    etc.). We try the canonical names first, then fall back to a small set of
    well-known synonyms so dispatch keeps working without forcing every module
    to add shims.
    """
    canonical = {
        "list":   ("list_rows",),
        "get":    ("get_row",),
        "create": ("create_row",),
        "update": ("update_row",),
        "delete": ("delete_row",),
    }
    synonyms = {
        "list":   ("list_requests", "list_runs", "list_reviews", "list_attendance",
                   "list_tasks", "list_records", "list_candidates", "list_types"),
        "get":    ("get_request", "get_run", "get_review", "get_attendance",
                   "get_task", "get_record", "get_candidate"),
        "create": ("create_request", "create_run", "create_review",
                   "create_attendance", "create_task", "create_record",
                   "create_candidate", "create_leave_request", "create_entry"),
        "update": ("update_request", "update_run", "update_review",
                   "update_attendance", "update_task", "update_record",
                   "update_candidate", "update_entry"),
        "delete": ("delete_request", "delete_run", "delete_review",
                   "delete_attendance", "delete_task", "delete_record",
                   "delete_candidate", "delete_entry"),
    }
    for name in canonical.get(op, ()) + synonyms.get(op, ()):
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    raise ValueError(
        f"module '{getattr(mod, 'NAME', mod.__name__)}' has no '{op}' helper"
    )


class ConfirmationRequired(RuntimeError):
    """Raised when a destructive op was requested without ``confirm=true``.

    The dispatcher catches this and surfaces it as a tool reply so the LLM
    has to ask the user, get explicit consent, then call again with
    ``confirm=true``. Never user-visible directly — the agent reads the
    string and prompts.
    """


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def _record_ai_audit(conn, *, action: str, module: str,
                     entity_id: Any, changes: dict[str, Any]) -> None:
    """Write an AI-attributed row into the audit_log table. Best-effort —
    if the audit_log table doesn't exist (older workspace) we silently skip
    so the underlying op still succeeds."""
    try:
        from .modules import audit_log
    except Exception:  # noqa: BLE001
        return
    try:
        audit_log.record(
            conn,
            actor="ai",
            action=action,
            entity_type=module,
            entity_id=int(entity_id) if entity_id not in (None, "") else None,
            changes=changes,
        )
    except Exception as exc:  # noqa: BLE001 - audit must never break the op
        log.warning("audit_log.record failed for ai action %s: %s", action, exc)


def _dispatch(conn, module: str, op: str, args: dict[str, Any] | None) -> Any:
    """Call the right per-module helper for ``op``.

    Centralised so both the live tool and unit tests exercise the same path.
    Returns the helper's raw result (id / row / list / None).

    Two extra layers vs the simple dispatch:

    * **Destructive-action gate** — ``delete`` requires ``args.confirm=true``.
      Without it we raise :class:`ConfirmationRequired` so the agent has to
      ask the user. ``query_records`` catches the exception and returns the
      message as a tool reply; pydantic-ai's docstring already tells the
      model to confirm first.
    * **AI audit trail** — every successful create / update / delete is
      recorded in the ``audit_log`` table with ``actor='ai'`` and a
      ``changes_json`` blob containing the tool's arguments + the result
      id. The user views the trail at ``/m/audit_log``.
    """
    op = (op or "").strip().lower()
    if op not in _ALLOWED_OPS:
        raise ValueError(f"op must be one of {_ALLOWED_OPS}, got '{op}'")
    args = dict(args or {})
    confirm = _is_truthy(args.pop("confirm", False))
    mod = _load_module(module, conn)
    fn = _resolve_helper(mod, op)

    if op == "list":
        return fn(conn)
    if op == "get":
        item_id = args.get("id") or args.get("item_id")
        if item_id is None:
            raise ValueError("'get' requires args.id")
        return fn(conn, int(item_id))
    if op == "create":
        # Accept either {"data": {...}} or the data fields inline.
        data = args.get("data")
        if not isinstance(data, dict):
            data = {k: v for k, v in args.items() if k not in ("module", "op")}
        new_id = fn(conn, data)
        _record_ai_audit(conn, action=f"{module}.create",
                         module=module, entity_id=new_id,
                         changes={"data": data, "result": {"id": new_id}})
        return new_id
    if op == "update":
        item_id = args.get("id") or args.get("item_id")
        if item_id is None:
            raise ValueError("'update' requires args.id")
        data = args.get("data")
        if not isinstance(data, dict):
            data = {k: v for k, v in args.items()
                    if k not in ("module", "op", "id", "item_id")}
        if not data:
            raise ValueError("'update' requires args.data with at least one field")
        result = fn(conn, int(item_id), data)
        _record_ai_audit(conn, action=f"{module}.update",
                         module=module, entity_id=item_id,
                         changes={"data": data})
        return result
    if op == "delete":
        item_id = args.get("id") or args.get("item_id")
        if item_id is None:
            raise ValueError("'delete' requires args.id")
        if not confirm:
            raise ConfirmationRequired(
                f"Refusing to delete {module} #{item_id} without explicit "
                f"confirmation. Ask the user in chat. If they say yes, retry "
                f"the same call with args.confirm=true."
            )
        result = fn(conn, int(item_id))
        _record_ai_audit(conn, action=f"{module}.delete",
                         module=module, entity_id=item_id,
                         changes={"confirm": True})
        return result
    # Unreachable thanks to the guard above, but mypy-friendly.
    raise ValueError(f"unhandled op '{op}'")  # pragma: no cover


def _summarise(result: Any) -> str:
    """Compact stringification for tool replies.

    The system prompt asks the LLM not to dump full JSON, but we still need a
    machine-readable payload it can read. For lists we cap at the first 50
    rows so a runaway query can't blow the context window.
    """
    if result is None:
        return "ok"
    if isinstance(result, list):
        head = result[:50]
        more = len(result) - len(head)
        text = json.dumps(head, default=str, ensure_ascii=False)
        if more > 0:
            text += f"\n... ({more} more rows truncated)"
        return text
    if isinstance(result, (dict, int, float, str, bool)):
        return json.dumps(result, default=str, ensure_ascii=False)
    return str(result)


# ---------------------------------------------------------------------------
# pydantic-ai tool factory
# ---------------------------------------------------------------------------
def _build_query_tool(conn) -> Callable[..., str]:
    """Return a ``query_records`` callable bound to ``conn``.

    pydantic-ai inspects the wrapped function's signature for its tool schema,
    so we keep types simple (str / str / dict) and document each argument in
    the docstring — that doc string is what the LLM sees.
    """
    allowed = _allowed_modules(conn)
    allowed_str = ", ".join(allowed)

    def query_records(module: str, op: str, args: dict | None = None) -> str:
        """Query or modify HR records.

        Args:
          module: One of the HR module slugs ({modules}).
          op: One of 'list', 'get', 'create', 'update', 'delete'.
          args: For 'get' use {{"id": <int>}}. For 'create' use
                {{"data": {{...fields...}}}} or pass fields inline. For
                'update' use {{"id": <int>, "data": {{...fields_to_change...}}}}.
                For 'list' pass {{}} or omit. For 'delete' use
                {{"id": <int>, "confirm": true}} — the ``confirm: true``
                flag is REQUIRED. Without it the call returns a "confirm
                required" message; you must ask the user in chat first,
                wait for an explicit yes, then retry with confirm=true.

        Every successful create / update / delete is recorded in the
        audit_log table (actor='ai', timestamp, full args). The user can
        review or revert your work at /m/audit_log.

        Returns a JSON string with the result, or an error message prefixed
        with 'error:' / 'confirm required:'.
        """
        try:
            result = _dispatch(conn, module, op, args or {})
            return _summarise(result)
        except ConfirmationRequired as exc:
            return f"confirm required: {exc}"
        except (ValueError, TypeError, KeyError) as exc:
            return f"error: {exc}"
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("query_records failed: module=%s op=%s", module, op)
            return f"error: {type(exc).__name__}: {exc}"

    # Stuff the dynamic module list into the docstring so the LLM sees it.
    if query_records.__doc__:
        query_records.__doc__ = query_records.__doc__.replace("{modules}", allowed_str)
    return query_records


def _model_override_error(conn, model_id: str | None) -> str | None:
    """Return a user-facing error when a selected model cannot handle chat."""
    model_id = (model_id or "").strip()
    if not model_id:
        return None

    def message(capabilities: list[str] | None = None) -> str:
        caps = ", ".join(capabilities or []) or "voice/audio"
        return (
            f"{model_id} is not a chat model ({caps}). "
            "Pick a text/chat UpfynAI model such as mini, auto, thinker, "
            "codium, or g1 for the HR assistant."
        )

    try:
        catalog = ai.list_models(conn)
    except Exception as exc:  # noqa: BLE001
        log.debug("model compatibility lookup failed: %s", exc)
        catalog = {}

    models = catalog.get("models") if isinstance(catalog, dict) else None
    if isinstance(models, list):
        for model in models:
            if not isinstance(model, dict):
                continue
            if str(model.get("id") or "").strip() != model_id:
                continue
            if model.get("chat_compatible") is False:
                raw_caps = model.get("capabilities") or []
                caps = [str(c) for c in raw_caps if str(c).strip()]
                return message(caps)
            return None

    # Fallback for older cached catalogs or hand-written API calls.
    lower = model_id.lower()
    if any(token in lower for token in ("chatterbox", "audio", "voice", "tts")):
        return message()
    return None


def _build_workspace_fs_tools(workspace_root: Path | None,
                               conn: Any = None) -> list[Callable[..., str]]:
    """Return file-touching tools bounded to ``workspace_root``.

    Lets the agent write HTML dashboards, CSV reports, markdown notes etc.
    into the workspace folder so the user can open them from the app's
    file browser. Every path is resolved through
    :func:`hrkit.sandbox.assert_path_in_workspace`, so attempts like
    ``../../etc/passwd`` or absolute paths outside the workspace raise a
    plain ``error: path escapes workspace`` instead of leaking data.

    Returned tools (no-op empty list when ``workspace_root`` is None — used
    at import time before a workspace is bound):
      - ``read_file(rel_path)``        -> file contents (text, capped 200 KB)
      - ``write_file(rel_path, body)`` -> "ok N bytes" / "error: ..."
      - ``append_file(rel_path, body)`` -> "ok appended N bytes"
      - ``make_folder(rel_path)``      -> "ok" / "error: ..."
      - ``list_workspace(rel_path?)``  -> JSON ``{path, entries[]}``

    Encoding is utf-8 throughout. Files larger than 1 MB on read are
    truncated; writes are size-capped at 5 MB to avoid runaway prompts
    that fill the disk.
    """
    if workspace_root is None:
        return []
    from . import sandbox

    root = Path(workspace_root)
    READ_CAP = 200 * 1024
    WRITE_CAP = 5 * 1024 * 1024

    def _resolve(rel_path: str) -> Path:
        return sandbox.assert_path_in_workspace(rel_path or "", root)

    def _audit(action: str, rel: str, **extra: Any) -> None:
        _record_ai_audit(
            conn, action=f"workspace.{action}", module="workspace",
            entity_id=None,
            changes={"rel_path": rel, **extra},
        )

    def read_file(rel_path: str) -> str:
        """Read a UTF-8 text file from the workspace.

        Args:
          rel_path: path relative to the workspace root, e.g.
            ``reports/Q3-headcount.html`` or ``employees/EMP-0001/notes.md``.

        Returns the file body, truncated to 200 KB. Returns a string
        starting with ``error:`` if the path escapes the workspace, the
        file doesn't exist, or it can't be decoded as text.
        """
        try:
            p = _resolve(rel_path)
        except ValueError as exc:
            return f"error: {exc}"
        if not p.exists():
            return f"error: no such file: {rel_path}"
        if not p.is_file():
            return f"error: not a file: {rel_path}"
        try:
            data = p.read_bytes()[:READ_CAP + 1]
        except OSError as exc:
            return f"error: read failed: {exc}"
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="replace")
        if len(data) > READ_CAP:
            text = text[:READ_CAP] + f"\n... (truncated; file > {READ_CAP} bytes)"
        return text

    def write_file(rel_path: str, body: str) -> str:
        """Create or overwrite a UTF-8 text file inside the workspace.

        Args:
          rel_path: path relative to the workspace root. Parent folders
            are created as needed. Common destinations:
              - ``reports/<name>.html`` for dashboards.
              - ``exports/<name>.csv`` for analysis dumps.
              - ``employees/<EMP-CODE>/memory/<note>.md`` for HR notes.
          body: file contents (utf-8 text). Capped at 5 MB.

        Returns ``"ok N bytes -> <relpath>"`` on success or an error
        string on failure.
        """
        if body is None:
            body = ""
        if not isinstance(body, str):
            body = str(body)
        if len(body.encode("utf-8")) > WRITE_CAP:
            return f"error: write too large (max {WRITE_CAP} bytes)"
        try:
            p = _resolve(rel_path)
        except ValueError as exc:
            return f"error: {exc}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        except OSError as exc:
            return f"error: write failed: {exc}"
        rel = str(p.relative_to(root)).replace("\\", "/")
        _audit("write_file", rel, bytes=len(body.encode("utf-8")))
        return f"ok {len(body.encode('utf-8'))} bytes -> {p.relative_to(root)}"

    def append_file(rel_path: str, body: str) -> str:
        """Append UTF-8 text to a file inside the workspace.

        Same path rules as ``write_file``. Creates the file if it
        doesn't exist. Useful for streaming logs or accumulating notes.
        """
        if body is None:
            body = ""
        if not isinstance(body, str):
            body = str(body)
        try:
            p = _resolve(rel_path)
        except ValueError as exc:
            return f"error: {exc}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            existing = 0
            if p.exists():
                existing = p.stat().st_size
            if existing + len(body.encode("utf-8")) > WRITE_CAP:
                return f"error: append would exceed cap (max {WRITE_CAP} bytes total)"
            with p.open("a", encoding="utf-8") as fh:
                fh.write(body)
        except OSError as exc:
            return f"error: append failed: {exc}"
        rel = str(p.relative_to(root)).replace("\\", "/")
        _audit("append_file", rel, bytes=len(body.encode("utf-8")))
        return f"ok appended {len(body.encode('utf-8'))} bytes -> {p.relative_to(root)}"

    def make_folder(rel_path: str) -> str:
        """Create a folder (and any missing parents) inside the workspace.

        Args:
          rel_path: path relative to the workspace root.

        Returns ``"ok -> <relpath>"`` on success. Idempotent — succeeds
        if the folder already exists.
        """
        try:
            p = _resolve(rel_path)
        except ValueError as exc:
            return f"error: {exc}"
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"error: mkdir failed: {exc}"
        rel = str(p.relative_to(root)).replace("\\", "/")
        _audit("make_folder", rel)
        return f"ok -> {p.relative_to(root)}"

    def list_workspace(rel_path: str = "") -> str:
        """List the contents of a workspace folder.

        Args:
          rel_path: subfolder relative to the workspace root. Empty
            string (default) lists the workspace root itself.

        Returns a JSON string ``{"path": "...", "entries": [...]}`` where
        each entry is ``{"name", "kind": "file"|"dir", "size", "rel_path"}``.
        Errors come back prefixed with ``error:``.
        """
        try:
            p = _resolve(rel_path or "")
        except ValueError as exc:
            return f"error: {exc}"
        if not p.exists():
            return f"error: no such path: {rel_path}"
        if not p.is_dir():
            return f"error: not a directory: {rel_path}"
        entries = []
        try:
            for child in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                try:
                    stat = child.stat()
                except OSError:
                    continue
                entries.append({
                    "name": child.name,
                    "kind": "dir" if child.is_dir() else "file",
                    "size": stat.st_size if child.is_file() else 0,
                    "rel_path": str(child.relative_to(root)).replace("\\", "/"),
                })
        except OSError as exc:
            return f"error: list failed: {exc}"
        rel = str(p.relative_to(root)).replace("\\", "/") or "."
        return json.dumps({"path": rel, "entries": entries}, ensure_ascii=False)

    # Make the tool functions tag themselves so sandbox.is_network_tool
    # never accidentally classifies them as network-touching.
    for fn in (read_file, write_file, append_file, make_folder, list_workspace):
        setattr(fn, "network", False)

    return [read_file, write_file, append_file, make_folder, list_workspace]


def _audit_artifact(conn: Any, action: str, artifact: dict[str, Any]) -> None:
    _record_ai_audit(
        conn, action=f"workspace.{action}", module="workspace",
        entity_id=None,
        changes={
            "rel_path": artifact.get("rel_path"),
            "filename": artifact.get("filename"),
            "kind": artifact.get("kind"),
            "size": artifact.get("size"),
        },
    )


def _build_artifact_tools(
    workspace_root: Path | None,
    conn: Any = None,
    *,
    employee_code: str | None = None,
    conversation_id: str = "",
    saved_artifacts: list[dict[str, Any]] | None = None,
) -> list[Callable[..., str]]:
    """Tools that save AI-created content into the local artifact library."""
    if workspace_root is None:
        return []
    root = Path(workspace_root)

    def save_artifact(kind: str, title: str, body: str, filename: str = "") -> str:
        """Save generated content into the workspace artifact folder.

        Args:
          kind: one of markdown, html, email, pdf, csv, json, text.
          title: human-readable title used for the filename when filename is empty.
          body: the content to save.
          filename: optional explicit filename.

        Returns JSON with rel_path so the user can open it from Workspace files.
        """
        try:
            item = artifacts.save_artifact_by_kind(
                root,
                kind=kind,
                title=title,
                body=body,
                filename=filename,
                conversation_id=conversation_id,
                employee_code=employee_code,
            )
        except Exception as exc:  # noqa: BLE001
            return f"error: save_artifact failed: {exc}"
        _audit_artifact(conn, "save_artifact", item)
        if saved_artifacts is not None:
            saved_artifacts.append(item)
        return json.dumps({"ok": True, **item}, ensure_ascii=False)

    def create_pdf(title: str, body: str, filename: str = "") -> str:
        """Create a simple PDF report in the workspace artifact folder.

        Use this when HR asks for a PDF/exportable report and the content is
        mostly text. For rich layouts, save HTML too.
        """
        try:
            item = artifacts.save_pdf_artifact(
                root,
                conversation_id=conversation_id,
                employee_code=employee_code,
                title=title,
                body=body,
                filename=filename,
            )
        except Exception as exc:  # noqa: BLE001
            return f"error: create_pdf failed: {exc}"
        _audit_artifact(conn, "create_pdf", item)
        if saved_artifacts is not None:
            saved_artifacts.append(item)
        return json.dumps({"ok": True, **item}, ensure_ascii=False)

    for fn in (save_artifact, create_pdf):
        setattr(fn, "network", False)
    return [save_artifact, create_pdf]


def _build_builtin_tools(
    workspace_root: Path | None,
    conn: Any = None,
    *,
    employee_code: str | None = None,
    conversation_id: str = "",
    saved_artifacts: list[dict[str, Any]] | None = None,
) -> list[Callable[..., str]]:
    """Wrap built-in web tools so successful results are saved locally."""

    def _save_web_result(query_or_url: str, result: str, source_type: str) -> str:
        if not workspace_root or not result or result.startswith("error:"):
            return ""
        try:
            item = artifacts.save_web_result(
                workspace_root,
                query_or_url=query_or_url,
                result=result,
                source_type=source_type,
                conversation_id=conversation_id,
                employee_code=employee_code,
            )
            _audit_artifact(conn, source_type, item)
            if saved_artifacts is not None:
                saved_artifacts.append(item)
        except Exception as exc:  # noqa: BLE001
            log.warning("web artifact autosave failed: %s", exc)
            return ""
        return f"\n\nSaved locally: {item['rel_path']}"

    def web_search(query: str) -> str:
        """Search the web and save the result list to the local artifact folder."""
        result = ai_tools.web_search(query)
        return result + _save_web_result(query, result, "web_search")

    def web_fetch(url: str) -> str:
        """Fetch a URL and save the readable text to the local artifact folder."""
        result = ai_tools.web_fetch(url)
        return result + _save_web_result(url, result, "web_fetch")

    web_search.__name__ = ai_tools.WEB_SEARCH_SLUG
    web_fetch.__name__ = ai_tools.WEB_FETCH_SLUG
    web_search.network = True  # type: ignore[attr-defined]
    web_fetch.network = True  # type: ignore[attr-defined]
    return [web_search, web_fetch]


def _build_composio_action_tools(
    conn,
    workspace_root: Path | None = None,
    *,
    employee_code: str | None = None,
    conversation_id: str = "",
    saved_artifacts: list[dict[str, Any]] | None = None,
) -> list[Callable[..., str]]:
    """Wrap configured Composio/MCP handlers as direct agent-callable tools.

    Returns an empty list when no Composio key is on file. We expose
    docs-style meta tools so the agent can discover, authenticate, inspect,
    and execute Composio tools at runtime, plus the four HR-friendly
    shortcuts we already register for event-driven hooks:

      - ``COMPOSIO_SEARCH_TOOLS`` / ``COMPOSIO_GET_TOOL_SCHEMAS``
      - ``COMPOSIO_MULTI_EXECUTE_TOOL`` / ``COMPOSIO_MANAGE_CONNECTIONS``
      - ``send_email(to, subject, body, html?)``  -> Gmail send
      - ``create_calendar_event(summary, start_date, end_date, description?)``
      - ``upload_to_drive(file_path, filename?, folder_id?)``
      - ``send_signature_request(signature_request_id)``

    Each tool returns a JSON-encoded result envelope. When sandboxed
    (``AI_LOCAL_ONLY=1``) these tools are still BUILT, then dropped by
    :func:`hrkit.sandbox.filter_tools` since their names look like
    Composio action slugs once flagged. We mark them with
    ``__name__`` upper-snake so the sandbox filter recognises them.
    """
    if not composio_sdk.is_configured(conn):
        return []
    try:
        from .integrations import composio_actions
    except Exception:  # noqa: BLE001
        return []
    disabled_tools = branding.composio_disabled_tools(conn)

    def _composio_audit(action: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        _record_ai_audit(
            conn, action=f"composio.{action}", module="composio",
            entity_id=None,
            changes={"args": args, "ok": bool(result.get("ok"))},
        )

    def _json_args(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {"text": value}
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        return {}

    def search_composio_tools(query: str = "", toolkit: str = "") -> str:
        """Discover enabled Composio tools available to HR.

        Args:
          query: optional text search such as "send email" or "calendar".
          toolkit: optional toolkit slug such as "gmail", "slack", or "github".

        Returns matching tool slugs, descriptions, and toolkit names as JSON.
        """
        try:
            actions = composio_sdk.list_actions(
                conn,
                app_slug=(toolkit or "").strip().lower() or None,
                search=(query or "").strip() or None,
                limit=25,
            )
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"
        out = []
        for action in actions:
            slug = str(action.get("slug") or "").upper()
            if not slug or slug in disabled_tools or action.get("deprecated"):
                continue
            out.append({
                "slug": slug,
                "name": action.get("name") or slug,
                "toolkit": action.get("toolkit_slug") or "",
                "description": action.get("description") or "",
            })
        return json.dumps(out, default=str, ensure_ascii=False)

    def get_composio_tool_schema(tool_slug: str) -> str:
        """Return input/output schema for one enabled Composio tool slug."""
        slug = (tool_slug or "").strip().upper()
        if not slug:
            return "error: tool_slug is required"
        if slug in disabled_tools:
            return f"error: {slug} is disabled by HR on the Integrations page"
        schema = composio_sdk.get_action_schema(conn, slug)
        return json.dumps(schema, default=str, ensure_ascii=False)

    def execute_composio_tool(tool_slug: str, arguments: dict | str | None = None) -> str:
        """Execute one enabled Composio tool with HR's connected account.

        Args:
          tool_slug: Composio action slug, for example GMAIL_SEND_EMAIL.
          arguments: tool input object matching the schema from
            COMPOSIO_GET_TOOL_SCHEMAS.
        """
        slug = (tool_slug or "").strip().upper()
        if not slug:
            return "error: tool_slug is required"
        if slug in disabled_tools:
            return f"error: {slug} is disabled by HR on the Integrations page"
        args = _json_args(arguments)
        if workspace_root is not None and "EMAIL" in slug:
            try:
                subject = str(args.get("subject") or args.get("title") or "Composio email draft")
                to = args.get("to") or args.get("recipient") or args.get("email") or ""
                body = args.get("body") or args.get("text") or args.get("message") or ""
                html_body = str(args.get("html") or args.get("html_body") or "")
                item = artifacts.save_email_artifact(
                    workspace_root,
                    conversation_id=conversation_id,
                    employee_code=employee_code,
                    title=subject,
                    body=f"To: {to}\nSubject: {subject}\n\n{body}",
                    html_body=html_body,
                )
                _audit_artifact(conn, "email_draft", item)
                if saved_artifacts is not None:
                    saved_artifacts.append(item)
            except Exception as exc:  # noqa: BLE001
                log.warning("generic email draft autosave failed: %s", exc)
        result = composio_sdk.execute_action(conn, slug, args)
        _record_ai_audit(
            conn, action=f"composio.{slug}", module="composio",
            entity_id=None, changes={"args": args, "ok": bool(result.get("successful"))},
        )
        return json.dumps(result, default=str, ensure_ascii=False)

    def manage_composio_connection(toolkit: str) -> str:
        """Create a Composio Connect Link for a toolkit the HR user needs."""
        slug = (toolkit or "").strip().lower()
        if not slug:
            return "error: toolkit is required"
        result = composio_sdk.init_connection(conn, slug)
        return json.dumps(result, default=str, ensure_ascii=False)

    def send_email(to: str, subject: str, body: str, html: str = "") -> str:
        """Send an email via the operator's connected Gmail account.

        Args:
          to: recipient email address.
          subject: email subject line.
          body: plain-text body. Used as the ``html`` value if ``html`` is empty.
          html: optional HTML body. If supplied, becomes the message body.

        Returns the raw Composio response as JSON, or an error string.
        """
        if workspace_root is not None:
            try:
                item = artifacts.save_email_artifact(
                    workspace_root,
                    conversation_id=conversation_id,
                    employee_code=employee_code,
                    title=subject or "AI email draft",
                    body=f"To: {to}\nSubject: {subject}\n\n{body}",
                    html_body=html,
                )
                _audit_artifact(conn, "email_draft", item)
                if saved_artifacts is not None:
                    saved_artifacts.append(item)
            except Exception as exc:  # noqa: BLE001
                log.warning("email draft autosave failed: %s", exc)
        result = composio_actions.send_offer_email(
            {"name": to, "email": to, "subject": subject,
             "body": html or body, "position": ""},
            conn=conn,
        )
        _composio_audit("send_email",
                        {"to": to, "subject": subject}, result)
        return json.dumps(result, default=str, ensure_ascii=False)

    def create_calendar_event(summary: str, start_date: str, end_date: str = "",
                              description: str = "") -> str:
        """Create a Google Calendar event in the operator's primary calendar."""
        result = composio_actions.block_calendar_for_leave(
            {"employee_name": summary, "leave_type": "",
             "start_date": start_date, "end_date": end_date or start_date,
             "reason": description},
            conn=conn,
        )
        _composio_audit("create_calendar_event",
                        {"summary": summary, "start_date": start_date,
                         "end_date": end_date}, result)
        return json.dumps(result, default=str, ensure_ascii=False)

    def upload_to_drive(file_path: str, filename: str = "", folder_id: str = "") -> str:
        """Upload a workspace file to the operator's Google Drive.

        ``file_path`` must already exist in the workspace; pair this with
        ``write_file`` if the agent generated the file in this turn.
        """
        result = composio_actions.upload_payslip_to_drive(
            {"file_path": file_path, "filename": filename, "folder_id": folder_id},
            conn=conn,
        )
        _composio_audit("upload_to_drive",
                        {"file_path": file_path, "filename": filename}, result)
        return json.dumps(result, default=str, ensure_ascii=False)

    def send_signature_request(signature_request_id: int) -> str:
        """Dispatch an existing ``signature_request`` row via the e-sign provider."""
        result = composio_actions.send_signature_request(
            {"signature_request_id": int(signature_request_id)}, conn=conn,
        )
        _composio_audit("send_signature_request",
                        {"signature_request_id": int(signature_request_id)}, result)
        return json.dumps(result, default=str, ensure_ascii=False)

    # Tag with upper-snake names so sandbox.is_network_tool correctly
    # treats these as network actions — they get dropped when the user
    # explicitly opts into AI_LOCAL_ONLY mode.
    send_email.__name__ = "GMAIL_SEND_EMAIL"
    create_calendar_event.__name__ = "GOOGLECALENDAR_CREATE_EVENT"
    upload_to_drive.__name__ = "GOOGLEDRIVE_UPLOAD_FILE"
    send_signature_request.__name__ = "ESIGN_SEND_REQUEST"
    search_composio_tools.__name__ = "COMPOSIO_SEARCH_TOOLS"
    get_composio_tool_schema.__name__ = "COMPOSIO_GET_TOOL_SCHEMAS"
    execute_composio_tool.__name__ = "COMPOSIO_MULTI_EXECUTE_TOOL"
    manage_composio_connection.__name__ = "COMPOSIO_MANAGE_CONNECTIONS"
    return [
        search_composio_tools,
        get_composio_tool_schema,
        execute_composio_tool,
        manage_composio_connection,
        send_email,
        create_calendar_event,
        upload_to_drive,
        send_signature_request,
    ]


def _build_imported_table_tools(conn) -> list[Callable[..., str]]:
    """Return read-only tools that let the agent see CSV-imported tables.

    These are local-only by construction: every call goes through
    :func:`hrkit.modules.csv_import.safe_select` which refuses any name
    outside the ``imported_*`` sandbox and uses parameterized queries.
    Returned even in LOCAL-ONLY mode because they don't touch the network.
    """
    try:
        from .modules import csv_import as csv_mod
    except Exception:  # noqa: BLE001 — module missing, no tools
        return []

    def list_imported_tables() -> str:
        """List every CSV-imported table available for analysis.

        Returns plain text: one line per table with row count + columns.
        Use this first to discover what data exists, then call
        ``describe_imported_table(name)`` to see the column types, and
        ``query_imported_table(name, ...)`` to read rows.
        """
        try:
            tables = csv_mod.list_imported_tables(conn)
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"
        if not tables:
            return "no imported tables yet (upload a CSV at /m/csv_import)"
        return "\n".join(
            f"- {t['table_name']}: {t['rows']} rows; columns: {t['columns']}"
            for t in tables)

    def describe_imported_table(name: str) -> str:
        """Return the column schema (name + SQL type) of an imported table.

        Args:
          name: table name, must start with ``imported_``.
        """
        try:
            desc = csv_mod.describe_table(conn, name)
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"
        if desc is None:
            return f"error: no imported table named {name!r}"
        cols = ", ".join(f"{c['name']} {c['type']}" for c in desc["columns"])
        return f"{desc['table_name']} ({desc['rows']} rows): {cols}"

    def query_imported_table(name: str,
                             columns: list | None = None,
                             where: dict | None = None,
                             limit: int = 50) -> str:
        """Read rows from an imported table with safe parameterized SELECT.

        Args:
          name: imported table name (must start with ``imported_``).
          columns: list of column names to return; ``None`` for all columns.
          where: dict of ``{column: value}``, ANDed with ``=``. Validated
                 against the table's schema.
          limit: max rows to return (capped at 1000, default 50).

        Returns a JSON string ``{columns, rows, total}`` or an error string
        prefixed with ``error:``. Refuses any name outside the sandbox.
        """
        try:
            result = csv_mod.safe_select(
                conn, name,
                columns=list(columns) if columns else None,
                where=dict(where) if where else None,
                limit=int(limit),
            )
        except (ValueError, TypeError) as exc:
            return f"error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"error: {type(exc).__name__}: {exc}"
        import json
        return json.dumps(result, default=str, ensure_ascii=False)

    return [list_imported_tables, describe_imported_table, query_imported_table]


def _build_system_prompt(conn=None) -> str:
    modules = ", ".join(_allowed_modules(conn))
    local_only = branding.ai_local_only(conn)
    base = (
        f"You are an HR assistant for {branding.app_name()}. "
        "Use the query_records tool to read or modify HR data. "
        f"Modules available: {modules}. "
        "Use list_imported_tables() / describe_imported_table(name) / "
        "query_imported_table(name, columns, where, limit) to read any CSV "
        "the user has imported into this workspace. "
        "DESTRUCTIVE-ACTION CONTRACT: every delete is gated. The first "
        "time you call query_records with op='delete', you'll get a "
        "'confirm required' message back — that is your cue to ASK THE "
        "USER in chat ('I'm about to delete X — should I?'), wait for "
        "their explicit yes, then retry the same call with "
        "args.confirm=true. Never invent a confirmation; always ask. "
        "AUDIT TRAIL: every successful create / update / delete you "
        "perform is logged in audit_log with actor='ai', a timestamp, "
        "and your full args. The user reviews your work at "
        "/m/audit_log — assume it's monitored. "
        "When listing, return a short summary, not the full JSON."
    )
    if local_only:
        return base + (
            " You are running in LOCAL-ONLY mode: every tool you have access "
            "to reads from this workspace's SQLite database or local files. "
            "You have NO ability to fetch or post anything to the public "
            "internet, send email, post to chat, or call any external API. "
            "Do not pretend to. If a question requires web data, say so."
        )
    return base + (
        " You operate inside a sandboxed full-capability agent harness:"
        " web_search(query) and web_fetch(url) for live web lookups;"
        " read_file / write_file / append_file / make_folder /"
        " list_workspace for the workspace folder; save_artifact(kind,"
        " title, body, filename?) and create_pdf(title, body, filename?)"
        " for HTML dashboards, email drafts, PDFs, web notes, reports;"
        " create reports under reports/, exports under exports/, and"
        " employees/<EMP-CODE>/ — every path stays inside the workspace);"
        " plus any Composio actions (send_email, create_calendar_event,"
        " upload_to_drive, send_signature_request, ...) that the operator"
        " has connected. Generate HTML dashboards or markdown reports"
        " when a question warrants it and tell the user where you saved"
        " the file."
    )


def _format_history(history: list[dict[str, Any]] | None, message: str) -> str:
    """Flatten prior turns into the user prompt.

    pydantic-ai's one-shot ``Agent.run`` takes a single string. We prefix the
    last few user/assistant turns so the model has conversational context
    without us managing message objects ourselves.
    """
    if not history:
        return message
    lines: list[str] = []
    # Keep only the trailing 12 turns to bound the prompt size.
    for turn in list(history)[-12:]:
        role = (turn.get("role") or "").strip().lower()
        content = (turn.get("content") or "").strip()
        if not content or role not in ("user", "assistant"):
            continue
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    lines.append(f"User: {message}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public: HTTP handler
# ---------------------------------------------------------------------------
def _workspace_root_for(handler) -> Path | None:
    server = getattr(handler, "server", None)
    root = getattr(server, "workspace_root", None) if server else None
    if root:
        return Path(root)
    try:
        from hrkit import server as server_mod
        if getattr(server_mod, "ROOT", None):
            return Path(server_mod.ROOT)
    except Exception:  # noqa: BLE001
        pass
    return None


def _augment_with_attachments(
    workspace_root: Path | None,
    message: str,
    attachments: list[dict[str, Any]] | None,
) -> str:
    """Append attached file text/notes to the message body sent to the AI."""
    if not attachments or not workspace_root:
        return message
    pieces = [message] if message else []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        rel = att.get("rel_path") or ""
        filename = att.get("filename") or "file"
        if not rel:
            # The chip in the UI may carry only id+filename; rebuild rel_path
            # from the known chat attachments dir layout.
            from .config import META_DIR
            upload_id = att.get("id") or ""
            if upload_id:
                rel = f"{META_DIR}/uploads/chat/{upload_id}/{filename}"
        if not rel:
            continue
        try:
            text = uploads.extract_text_for_ai(workspace_root, rel)
        except Exception as exc:  # noqa: BLE001
            text = f"[failed to extract {filename}: {exc}]"
        pieces.append(f"\n\n=== ATTACHMENT: {filename} ===\n{text}\n=== END ATTACHMENT ===")
    return "\n".join(pieces).strip() or message


def _is_retryable_provider_reply(text: str) -> bool:
    """Return True when the provider returned a busy/error sentence as text."""
    lower = str(text or "").strip().lower()
    busy_markers = (
        "servers are experiencing brief congestion",
        "please retry your message",
        "temporarily unavailable",
        "try again later",
        "server is busy",
    )
    return bool(lower) and any(marker in lower for marker in busy_markers)


def _prepare_chat_run(handler, body: dict[str, Any]) -> dict[str, Any]:
    """Validate a chat request and build the prompt/tools for one agent run."""
    body = body or {}
    message = (body.get("message") or "").strip()
    attachments_in = body.get("attachments") or []
    if not message and not attachments_in:
        raise ValueError("message or attachment required")

    conn = handler.server.conn  # type: ignore[attr-defined]
    workspace_root = _workspace_root_for(handler)

    # Inline attachment text so the AI can read files the user pinned.
    full_message = _augment_with_attachments(workspace_root, message, attachments_in)
    prompt = _format_history(body.get("history"), full_message)

    # Optional per-employee context: when the chat is "talking about" someone,
    # prefix the system prompt with their full record + notes.
    employee_id_raw = body.get("employee_id")
    employee_code_for_save: str | None = None
    try:
        employee_id = int(employee_id_raw) if employee_id_raw else None
    except (TypeError, ValueError):
        employee_id = None
    system = _build_system_prompt(conn)
    if employee_id and workspace_root is not None:
        try:
            ctx = employee_fs.build_ai_context(conn, workspace_root, employee_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("build_ai_context failed: %s", exc)
            ctx = ""
        if ctx:
            system += "\n\n--- Employee context ---\n" + ctx
        row = conn.execute(
            "SELECT employee_code FROM employee WHERE id = ?", (employee_id,),
        ).fetchone()
        if row and row["employee_code"]:
            employee_code_for_save = str(row["employee_code"]).strip() or None

    conversation_id = (body.get("conversation_id") or "").strip()
    if not conversation_id and workspace_root is not None:
        conversation_id = chat_storage.new_conversation_id(message)
    run_artifacts: list[dict[str, Any]] = []

    tool = _build_query_tool(conn)
    # Build the candidate tool list. The agent is a full-capability sandboxed
    # agent by default. ``filter_tools`` drops network-touching tools only when
    # the user has explicitly turned AI_LOCAL_ONLY back on.
    tools: list = [
        tool,
        *_build_imported_table_tools(conn),
        *_build_workspace_fs_tools(workspace_root, conn),
        *_build_artifact_tools(
            workspace_root, conn,
            employee_code=employee_code_for_save,
            conversation_id=conversation_id,
            saved_artifacts=run_artifacts,
        ),
        *_build_composio_action_tools(
            conn, workspace_root,
            employee_code=employee_code_for_save,
            conversation_id=conversation_id,
            saved_artifacts=run_artifacts,
        ),
        *_build_builtin_tools(
            workspace_root, conn,
            employee_code=employee_code_for_save,
            conversation_id=conversation_id,
            saved_artifacts=run_artifacts,
        ),
    ]
    if workspace_root is not None:
        try:
            tools.extend(recipes_ui.build_recipe_tools(conn, workspace_root))
        except Exception as exc:  # noqa: BLE001
            log.warning("recipes_ui.build_recipe_tools failed: %s", exc)
    tools = sandbox.filter_tools(tools, conn)

    model_override = (body.get("model") or "").strip() or None
    model_to_check = model_override or branding.ai_model(conn)
    model_error = _model_override_error(conn, model_to_check)
    if model_error:
        raise ValueError(model_error)

    return {
        "body": body,
        "conn": conn,
        "workspace_root": workspace_root,
        "message": message,
        "attachments": attachments_in,
        "prompt": prompt,
        "system": system,
        "tools": tools,
        "model": model_override,
        "employee_code": employee_code_for_save,
        "conversation_id": conversation_id,
        "history": body.get("history") or [],
        "tool_artifacts": run_artifacts,
    }


def _persist_chat_turn(
    *,
    conn: Any = None,
    workspace_root: Path | None,
    conversation_id: str,
    message: str,
    attachments: list[dict[str, Any]],
    history: list[dict[str, Any]],
    reply: str,
    model: str | None,
    employee_code: str | None,
    tool_artifacts: list[dict[str, Any]] | None = None,
) -> tuple[str, bool, int, list[dict[str, Any]]]:
    """Persist a completed turn and autosave user-visible artifacts."""
    persisted = False
    turn_count = 0
    saved_artifacts: list[dict[str, Any]] = list(tool_artifacts or [])
    if workspace_root:
        try:
            if not conversation_id:
                conversation_id = chat_storage.new_conversation_id(message)
            # Reload prior messages so we append rather than overwrite.
            existing = chat_storage.load_conversation(
                workspace_root=workspace_root,
                conversation_id=conversation_id,
                employee_code=employee_code,
            ) or {}
            messages = list(existing.get("messages") or history or [])
            messages.append({
                "role": "user", "content": message, "attachments": attachments,
            })
            messages.append({"role": "assistant", "content": reply})
            chat_storage.save_conversation(
                workspace_root=workspace_root,
                conversation_id=conversation_id,
                messages=messages,
                model=model,
                employee_code=employee_code,
            )
            persisted = True
            turn_count = len(messages)
            reply_artifacts = artifacts.autosave_chat_reply(
                workspace_root,
                conversation_id=conversation_id,
                employee_code=employee_code,
                user_message=message,
                reply=reply,
                turn_count=turn_count,
            )
            saved_artifacts.extend(reply_artifacts)
            for item in reply_artifacts:
                _audit_artifact(conn, "auto_save_reply", item)
            if saved_artifacts and messages:
                messages[-1]["artifacts"] = saved_artifacts
                chat_storage.save_conversation(
                    workspace_root=workspace_root,
                    conversation_id=conversation_id,
                    messages=messages,
                    model=model,
                    employee_code=employee_code,
                )
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            log.warning("chat_storage.save failed: %s", exc)
    return conversation_id, persisted, turn_count, saved_artifacts


class ClientDisconnected(RuntimeError):
    """Raised when a browser aborts an in-flight SSE chat stream."""


def _send_sse_event(handler, event: str, data: dict[str, Any]) -> None:
    """Write one server-sent event to the chat stream."""
    payload = (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    ).encode("utf-8")
    try:
        handler.wfile.write(payload)
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionError, OSError) as exc:
        raise ClientDisconnected("chat stream client disconnected") from exc


async def handle_chat_message(handler, body: dict[str, Any]) -> None:
    """Handle ``POST /api/chat``.

    Body shape::

        {"message": str,
         "history": [{"role": "user"|"assistant", "content": str}, ...],
         "model": str | None,                       # per-conversation override
         "attachments": [{id, filename, rel_path}], # from /api/chat/upload
         "conversation_id": str | None}             # null = start fresh

    Returns ``{"ok": True, "reply": str, "conversation_id": str}`` on
    success, else ``{"ok": False, "error": str}`` with HTTP 4xx/5xx.
    """
    try:
        try:
            ctx = _prepare_chat_run(handler, body)
        except ValueError as exc:
            handler._json({"ok": False, "error": str(exc)}, code=400)
            return

        try:
            # Belt-and-braces: even after filter_tools, wrap the agent run
            # in network_disabled_if(conn) so any leftover HTTP call from
            # within a tool raises NetworkBlocked instead of leaking data.
            with sandbox.network_disabled_if(ctx["conn"]):
                reply = await ai.run_agent(
                    ctx["prompt"], conn=ctx["conn"], system=ctx["system"],
                    tools=ctx["tools"], model=ctx["model"],
                )
            if _is_retryable_provider_reply(reply):
                handler._json({
                    "ok": False,
                    "error": (
                        "UpfynAI is temporarily busy. Retry the same message "
                        "in a few seconds."
                    ),
                    "retryable": True,
                }, code=503)
                return
        except sandbox.NetworkBlocked as exc:
            handler._json({"ok": False, "error": str(exc)}, code=403)
            return
        except RuntimeError as exc:
            handler._json({"ok": False, "error": str(exc)}, code=502)
            return

        conversation_id, persisted, turn_count, saved_artifacts = _persist_chat_turn(
            conn=ctx["conn"],
            workspace_root=ctx["workspace_root"],
            conversation_id=ctx["conversation_id"],
            message=ctx["message"],
            attachments=ctx["attachments"],
            history=ctx["history"],
            reply=reply,
            model=ctx["model"],
            employee_code=ctx["employee_code"],
            tool_artifacts=ctx.get("tool_artifacts") or [],
        )

        handler._json({
            "ok": True,
            "reply": reply,
            "conversation_id": conversation_id,
            "persisted": persisted,
            "turns": turn_count,
            "artifacts": saved_artifacts,
            "employee_code": ctx["employee_code"] or "",
        })
        return
    except Exception as exc:
        log.error("handle_chat_message failed: %s\n%s", exc, traceback.format_exc())
        handler._json({"ok": False, "error": ai.friendly_error(exc)}, code=500)


async def handle_chat_stream(handler, body: dict[str, Any]) -> None:
    """Handle ``POST /api/chat/stream`` as server-sent text deltas."""
    try:
        try:
            ctx = _prepare_chat_run(handler, body)
        except ValueError as exc:
            handler._json({"ok": False, "error": str(exc)}, code=400)
            return

        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()
        handler.close_connection = True

        _send_sse_event(handler, "meta", {
            "ok": True,
            "stream": True,
            "conversation_id": ctx["conversation_id"],
            "employee_code": ctx["employee_code"] or "",
        })

        chunks: list[str] = []
        try:
            # Keep the same sandbox guard as the JSON endpoint while letting
            # pydantic-ai stream the model's text deltas to the browser.
            with sandbox.network_disabled_if(ctx["conn"]):
                async for chunk in ai.stream_agent(
                    ctx["prompt"], conn=ctx["conn"], system=ctx["system"],
                    tools=ctx["tools"], model=ctx["model"],
                ):
                    chunks.append(chunk)
                    _send_sse_event(handler, "delta", {"text": chunk})

            reply = "".join(chunks).strip()
            if _is_retryable_provider_reply(reply):
                _send_sse_event(handler, "error", {
                    "ok": False,
                    "error": (
                        "UpfynAI is temporarily busy. Retry the same message "
                        "in a few seconds."
                    ),
                    "retryable": True,
                })
                return

            conversation_id, persisted, turn_count, saved_artifacts = _persist_chat_turn(
                conn=ctx["conn"],
                workspace_root=ctx["workspace_root"],
                conversation_id=ctx["conversation_id"],
                message=ctx["message"],
                attachments=ctx["attachments"],
                history=ctx["history"],
                reply=reply,
                model=ctx["model"],
                employee_code=ctx["employee_code"],
                tool_artifacts=ctx.get("tool_artifacts") or [],
            )
            _send_sse_event(handler, "done", {
                "ok": True,
                "reply": reply,
                "conversation_id": conversation_id,
                "persisted": persisted,
                "turns": turn_count,
                "artifacts": saved_artifacts,
                "employee_code": ctx["employee_code"] or "",
            })
        except sandbox.NetworkBlocked as exc:
            _send_sse_event(handler, "error", {"ok": False, "error": str(exc)})
        except RuntimeError as exc:
            _send_sse_event(handler, "error", {"ok": False, "error": str(exc)})
        except ClientDisconnected:
            log.info("chat stream stopped by browser")
        except Exception as exc:  # noqa: BLE001
            log.error("handle_chat_stream failed: %s\n%s", exc, traceback.format_exc())
            _send_sse_event(
                handler, "error",
                {"ok": False, "error": ai.friendly_error(exc)},
            )
    except Exception as exc:  # noqa: BLE001
        log.error("handle_chat_stream setup failed: %s\n%s", exc, traceback.format_exc())
        try:
            handler._json({"ok": False, "error": ai.friendly_error(exc)}, code=500)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Conversation API
# ---------------------------------------------------------------------------
def handle_list_conversations(handler) -> None:
    """GET /api/chat/conversations[?employee_code=X] — list saved transcripts."""
    workspace_root = _workspace_root_for(handler)
    if workspace_root is None:
        handler._json({"ok": True, "conversations": []})
        return
    # Pull optional employee_code filter from the query string.
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(getattr(handler, "path", "")).query)
    code_vals = qs.get("employee_code", [])
    employee_code = (code_vals[0].strip() if code_vals else "") or None
    try:
        items = chat_storage.list_conversations(
            workspace_root=workspace_root, employee_code=employee_code,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("list_conversations failed")
        handler._json({"ok": False, "error": str(exc)}, code=500)
        return
    handler._json({"ok": True, "conversations": items, "employee_code": employee_code or ""})


def handle_employee_picklist(handler) -> None:
    """GET /api/employees/list — lightweight ``[{id, code, name}]`` for pickers."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        cur = conn.execute(
            "SELECT id, employee_code, full_name FROM employee"
            " WHERE status != 'exited' ORDER BY full_name LIMIT 500"
        )
        items = [
            {"id": r["id"], "code": r["employee_code"], "name": r["full_name"]}
            for r in cur.fetchall()
        ]
    except Exception as exc:  # noqa: BLE001
        handler._json({"ok": False, "error": str(exc)}, code=500)
        return
    handler._json({"ok": True, "employees": items})


def handle_get_conversation(handler, conversation_id: str) -> None:
    """GET /api/chat/conversations/<id>[?employee_code=X] — load one transcript."""
    workspace_root = _workspace_root_for(handler)
    if workspace_root is None:
        handler._json({"ok": False, "error": "workspace not configured"}, code=400)
        return
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(getattr(handler, "path", "")).query)
    code_vals = qs.get("employee_code", [])
    employee_code = (code_vals[0].strip() if code_vals else "") or None
    try:
        convo = chat_storage.load_conversation(
            workspace_root=workspace_root,
            conversation_id=conversation_id,
            employee_code=employee_code,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("load_conversation failed")
        handler._json({"ok": False, "error": str(exc)}, code=500)
        return
    if convo is None:
        handler._json({"ok": False, "error": "not found"}, code=404)
        return
    handler._json({"ok": True, **convo})


def handle_models(handler) -> None:
    """GET /api/models — return the provider's model catalog."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        result = ai.list_models(conn)
    except Exception as exc:  # noqa: BLE001
        log.exception("list_models failed")
        handler._json({"ok": False, "error": str(exc)}, code=500)
        return
    handler._json(result)


# ---------------------------------------------------------------------------
# Public: HTML page
# ---------------------------------------------------------------------------
_CHAT_BODY = """
<style>
.chat-shell{display:grid;grid-template-columns:240px 1fr;gap:14px;
  height:calc(100vh - 140px);max-width:1180px;margin:0 auto}
.chat-side{background:var(--panel);border:1px solid var(--border);border-radius:8px;
  padding:10px;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.chat-side h2{margin:0 0 8px;font-size:11px;color:var(--dim);text-transform:uppercase;
  letter-spacing:0.7px;padding:4px 6px}
.chat-side button.new{padding:8px 10px;background:var(--accent);color:#fff;border:none;
  border-radius:6px;font-size:12.5px;cursor:pointer;margin-bottom:8px;font-weight:500}
.chat-side button.new:hover{filter:brightness(1.08)}
#convo-list{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:2px}
.convo-item{padding:7px 10px;border-radius:6px;font-size:12.5px;color:var(--dim);
  cursor:pointer;border:1px solid transparent;display:flex;flex-direction:column;gap:2px}
.convo-item:hover{background:var(--row-hover);color:var(--text)}
.convo-item.active{background:color-mix(in srgb,var(--accent) 18%,transparent);
  color:var(--text);border-color:color-mix(in srgb,var(--accent) 30%,transparent)}
.convo-item .convo-title{font-size:12.5px}
.convo-item .convo-meta{font-size:10.5px;color:var(--mute)}
.chat-main{display:flex;flex-direction:column;gap:14px;min-width:0}
.chat-head{display:flex;justify-content:space-between;align-items:center;
  gap:12px;padding-bottom:12px;border-bottom:1px solid var(--border)}
.chat-head h1{margin:0;font-size:20px;font-weight:600;letter-spacing:-0.01em}
.chat-head .chat-sub{color:var(--dim);font-size:12.5px;margin-top:2px}
.chat-status{margin-top:8px;display:inline-flex;align-items:center;gap:6px;
  padding:4px 9px;border-radius:999px;background:var(--row-hover);
  color:var(--dim);font-size:11.5px;border:1px solid var(--border)}
.chat-status.ok{background:rgba(16,185,129,0.10);color:#047857;border-color:rgba(16,185,129,0.20)}
.chat-status.warn{background:rgba(245,158,11,0.12);color:#92400e;border-color:rgba(245,158,11,0.24)}
.chat-status.error{background:rgba(239,68,68,0.10);color:#b91c1c;border-color:rgba(239,68,68,0.22)}
[data-theme="dark"] .chat-status.ok{color:#34d399}
[data-theme="dark"] .chat-status.warn{color:#fbbf24}
[data-theme="dark"] .chat-status.error{color:#fca5a5}
.chat-head .head-controls{display:flex;gap:8px;align-items:center}
.chat-head select{padding:6px 10px;background:var(--panel);color:var(--text);
  border:1px solid var(--border);border-radius:6px;font-size:12px;max-width:240px}
.chat-head button.icon{padding:6px 10px;border-radius:6px;background:transparent;
  color:var(--dim);border:1px solid var(--border);cursor:pointer;font-size:12px}
.chat-head button.icon:hover{color:var(--text);border-color:var(--accent)}
#messages{flex:1;overflow-y:auto;background:var(--panel);border:1px solid var(--border);
  border-radius:8px;padding:18px;display:flex;flex-direction:column;gap:14px;min-height:0}
.msg{display:flex;flex-direction:column;gap:4px;max-width:78%}
.msg .who{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:0.5px}
.msg .bubble{padding:10px 14px;border-radius:10px;background:var(--panel-alt);
  border:1px solid var(--border);color:var(--text);font-size:13.5px;line-height:1.5;
  white-space:pre-wrap;word-break:break-word}
.msg.user{align-self:flex-end;align-items:flex-end}
.msg.user .bubble{background:color-mix(in srgb,var(--accent) 22%,transparent);
  border-color:color-mix(in srgb,var(--accent) 35%,transparent)}
.msg.assistant{align-self:flex-start}
.msg.error .bubble{border-color:var(--red);color:var(--red)}
.msg.thinking .bubble{color:var(--dim);font-style:italic}
.msg .attachments{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.msg .attachments .chip{font-size:11px;padding:2px 8px;border-radius:10px;
  background:var(--bg);border:1px solid var(--border);color:var(--dim)}
.saved-artifacts{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.saved-artifacts button{border:1px solid var(--border);background:var(--panel);
  color:var(--dim);border-radius:999px;padding:5px 10px;font-size:12px;cursor:pointer}
.saved-artifacts button:hover{color:var(--text);border-color:var(--accent)}
.chat-input{display:flex;gap:10px;align-items:flex-end;background:var(--panel);
  border:1px solid var(--border);border-radius:8px;padding:10px}
.chat-input textarea{flex:1;min-height:46px;max-height:180px;resize:vertical;
  background:var(--bg);color:var(--text);border:1px solid var(--border);
  border-radius:6px;padding:10px 12px;font-family:inherit;font-size:13.5px;
  line-height:1.45}
.chat-input button.attach{padding:10px 12px;border-radius:6px;background:transparent;
  color:var(--dim);border:1px solid var(--border);cursor:pointer;font-size:14px}
.chat-input button.attach:hover{color:var(--text);border-color:var(--accent)}
.chat-input button.send{padding:10px 18px;border-radius:6px;background:var(--accent);
  color:#fff;border:none;cursor:pointer;font-size:13px;font-weight:500}
.chat-input button:disabled{opacity:0.5;cursor:not-allowed}
.attached-chips{display:flex;flex-wrap:wrap;gap:6px;padding:6px 10px;
  font-size:11.5px;color:var(--dim)}
.attached-chips .chip{background:var(--panel);border:1px solid var(--border);
  padding:3px 8px;border-radius:10px;display:flex;gap:6px;align-items:center}
.attached-chips .chip button{background:none;border:none;color:var(--dim);
  cursor:pointer;font-size:13px;padding:0;margin:0;line-height:1}
.attached-chips .chip button:hover{color:var(--red)}
.empty{padding:40px;text-align:center;color:var(--dim);font-style:italic}
.free-badge{font-size:9px;background:color-mix(in srgb,var(--green) 25%,transparent);
  color:var(--green);padding:1px 5px;border-radius:6px;margin-left:6px;
  text-transform:uppercase;letter-spacing:0.4px}

/* Three-pane chat workspace: conversations, chat, artifacts. */
.chat-shell{grid-template-columns:minmax(280px,324px) minmax(520px,1fr) minmax(320px,380px);
  gap:18px;height:calc(100vh - 118px);max-width:none;width:100%;padding:0}
.chat-side{border-radius:20px;padding:14px;background:color-mix(in srgb,var(--panel) 92%,transparent);
  box-shadow:0 18px 50px rgba(15,23,42,0.06);display:flex}
.chat-side button.new{border-radius:999px;padding:10px 14px}
.convo-item{border-radius:14px;padding:10px 12px}
.chat-main{gap:0;min-height:0;width:100%;max-width:none;margin:0;display:flex;flex-direction:column}
.chat-head{border:0;padding:2px 4px 12px;align-items:flex-start}
.chat-head h1{font-size:26px;letter-spacing:-0.04em}
.chat-head .chat-sub{font-size:13px;margin-top:4px}
.chat-head .head-controls{display:flex}
.chat-status{margin-top:10px;border-radius:999px}
#messages{background:transparent;border:0;border-radius:0;padding:18px 6px 26px;
  gap:22px;scroll-behavior:smooth;min-height:0;flex:1}
.msg{max-width:760px;width:min(760px,100%);gap:6px}
.msg.user{align-self:flex-end;align-items:flex-end}
.msg.assistant,.msg.error,.msg.thinking{align-self:flex-start;align-items:flex-start}
.msg .who{font-size:11px;color:var(--mute);text-transform:none;letter-spacing:0}
.msg .bubble{border:0;background:transparent;border-radius:0;padding:0;
  font-size:15.5px;line-height:1.65;box-shadow:none}
.msg.user .bubble{background:color-mix(in srgb,var(--accent) 11%,var(--panel));
  border:1px solid color-mix(in srgb,var(--accent) 22%,var(--border));
  border-radius:22px;padding:12px 16px;max-width:620px}
.msg.error .bubble{background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);
  border-radius:18px;padding:12px 14px}
.msg.thinking .bubble{font-style:normal;color:var(--mute)}
.chat-input{position:relative;left:auto;bottom:auto;transform:none;
  width:100%;display:flex;flex-direction:column;gap:8px;
  align-items:stretch;background:color-mix(in srgb,var(--panel) 96%,transparent);
  border:1px solid color-mix(in srgb,var(--border) 80%,transparent);
  border-radius:28px;padding:14px 16px 12px;box-shadow:0 20px 50px rgba(15,23,42,0.11);
  flex-shrink:0}
.chat-input textarea{width:100%;min-height:44px;max-height:190px;resize:none;
  background:transparent;border:0;border-radius:0;padding:4px 2px;font-size:16px;
  outline:none}
.composer-tools{display:flex;align-items:center;justify-content:space-between;gap:10px}
.composer-left,.composer-right{display:flex;align-items:center;gap:10px;min-width:0}
.composer-btn{height:34px;min-width:34px;border-radius:999px;border:1px solid var(--border);
  background:transparent;color:var(--dim);cursor:pointer;font-size:13px;padding:0 12px}
.composer-btn:hover{color:var(--text);border-color:var(--accent)}
.composer-btn.has-files{color:#047857;border-color:rgba(16,185,129,.35);
  background:rgba(16,185,129,.08)}
.composer-model{max-width:240px;border:0;background:transparent;color:var(--dim);
  font-size:13px;padding:7px 2px}
.chat-input button.send,.chat-input button.stop{height:36px;min-width:68px;border-radius:999px;padding:0 16px;
  color:#fff;border:none;font-size:13px;font-weight:700;line-height:1}
.chat-input button.send{background:#1f2937}
.chat-input button.stop{display:none;background:#ef4444}
.chat-input button:disabled{opacity:0.5;cursor:not-allowed}
.attached-chips{width:100%;margin:0 0 8px}
#messages > .empty{background:transparent!important;border:0!important;box-shadow:none!important;
  padding:110px 20px!important;color:var(--dim);font-size:15px}
.msg.queued{opacity:0.72}
.msg.queued .who{color:#b45309}
.msg.queued .bubble{border-style:dashed}
.artifact-panel{position:relative;top:auto;right:auto;bottom:auto;z-index:1;
  width:100%;height:100%;display:flex;flex-direction:column;
  background:color-mix(in srgb,var(--panel) 98%,transparent);
  border:1px solid var(--border);border-radius:24px;box-shadow:0 28px 80px rgba(15,23,42,0.18);
  overflow:hidden}
.artifact-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;
  padding:16px 18px;border-bottom:1px solid var(--border)}
.artifact-kicker{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.6px}
.artifact-title{font-size:16px;font-weight:700;color:var(--text);margin-top:3px;word-break:break-word}
.artifact-meta{font-size:12px;color:var(--dim);margin-top:4px;word-break:break-word}
.artifact-head button{display:none}
.artifact-list{display:flex;gap:8px;overflow-x:auto;padding:10px 14px;border-bottom:1px solid var(--border)}
.artifact-list button{white-space:nowrap;border:1px solid var(--border);background:var(--bg);
  color:var(--dim);border-radius:999px;padding:6px 10px;font-size:12px;cursor:pointer}
.artifact-list button.active,.artifact-list button:hover{color:var(--text);border-color:var(--accent)}
.artifact-body{flex:1;min-height:0;background:var(--bg)}
.artifact-body iframe{width:100%;height:100%;border:0;background:#fff}
.artifact-text{height:100%;overflow:auto;margin:0;padding:18px;font:12.5px/1.55 'JetBrains Mono','Menlo',monospace;
  white-space:pre-wrap;color:var(--text)}
@media (max-width:1180px){
  .chat-shell{grid-template-columns:minmax(0,1fr);max-width:none}
  .chat-side{display:none}
  .artifact-panel{position:fixed;left:12px;right:12px;top:68px;bottom:12px;width:auto;height:auto;z-index:30}
  .artifact-panel[hidden]{display:none}
  .artifact-head button{display:inline-flex;align-items:center;justify-content:center}
}
@media (max-width:860px){
  .chat-shell{height:auto;min-height:calc(100vh - 100px);padding:0}
  .chat-input{width:100%;margin-top:auto}
  #messages{padding-bottom:24px;min-height:55vh}
  .msg{width:100%}
}
</style>
<div class="chat-shell">
  <aside class="chat-side">
    <h2>Talking about</h2>
    <select id="employee-context" onchange="onEmployeeContextChanged()" style="width:100%;padding:7px 10px;
        background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;
        font-size:12.5px;margin-bottom:10px">
      <option value="">Anyone (no employee context)</option>
    </select>
    <h2>Conversations</h2>
    <button class="new" onclick="newConversation()">+ New chat</button>
    <div id="convo-list"><div class="empty" style="padding:14px;font-size:12px">No saved chats yet.</div></div>
  </aside>
  <section class="chat-main">
    <div class="chat-head">
      <div>
        <h1>AI Assistant</h1>
        <div class="chat-sub" id="chat-sub">Ask about employees, leave, payroll and more.</div>
        <div class="chat-status" id="chat-status">Ready. Chats save to this laptop.</div>
      </div>
      <div class="head-controls">
        <button class="icon" type="button" onclick="showArtifactPanel()">Artifacts</button>
        <button class="icon" type="button" onclick="newConversation()">New chat</button>
      </div>
    </div>
    <div id="messages"><div class="empty">Say hello to get started.</div></div>
    <div id="attached-chips" class="attached-chips" style="display:none"></div>
    <form class="chat-input" onsubmit="sendMessage(event)">
      <input type="file" id="file-input" multiple style="display:none" onchange="onAttach(this.files)">
      <textarea id="chat-input" placeholder="Ask anything... (Shift+Enter for newline)"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage(event);}"></textarea>
      <div class="composer-tools">
        <div class="composer-left">
          <button type="button" class="composer-btn" id="attach-btn"
            onclick="document.getElementById('file-input').click()" title="Attach a file">Attach</button>
        </div>
        <div class="composer-right">
          <select id="model-select" class="composer-model" title="Pick which model handles this conversation">
            <option value="">Default model</option>
          </select>
          <button type="button" class="stop" id="stop-btn" onclick="stopStreaming()" title="Stop the current response">Stop</button>
          <button type="submit" class="send" id="send-btn" title="Send">Send</button>
        </div>
      </div>
    </form>
  </section>
  <aside class="artifact-panel" id="artifact-panel">
  <div class="artifact-head">
    <div>
      <div class="artifact-kicker">Saved artifact</div>
      <div class="artifact-title" id="artifact-title">No artifact selected</div>
      <div class="artifact-meta" id="artifact-meta">AI-created files save to this laptop.</div>
    </div>
    <button type="button" onclick="closeArtifactPanel()" title="Close artifact viewer">x</button>
  </div>
  <div class="artifact-list" id="artifact-list"></div>
  <div class="artifact-body" id="artifact-body">
    <pre class="artifact-text">Select a saved artifact from the chat.</pre>
  </div>
</aside>
</div>
<script>
let history = [];
let conversationId = null;
let attached = [];   // [{id, filename, size}]
let employeeId = null;
let employeeCode = '';
let savedArtifacts = [];
const msgEl = document.getElementById('messages');
const inputEl = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const stopBtn = document.getElementById('stop-btn');
const attachBtn = document.getElementById('attach-btn');
const modelSel = document.getElementById('model-select');
const convoListEl = document.getElementById('convo-list');
const attachedChipsEl = document.getElementById('attached-chips');
const empCtxSel = document.getElementById('employee-context');
const chatSubEl = document.getElementById('chat-sub');
const chatStatusEl = document.getElementById('chat-status');
const artifactPanel = document.getElementById('artifact-panel');
const artifactTitle = document.getElementById('artifact-title');
const artifactMeta = document.getElementById('artifact-meta');
const artifactListEl = document.getElementById('artifact-list');
const artifactBody = document.getElementById('artifact-body');
let isStreaming = false;
let currentAbort = null;
let pendingQueue = [];

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function clearEmpty() {
  const e = msgEl.querySelector('.empty');
  if (e) e.remove();
}

function setStatus(text, kind) {
  if (!chatStatusEl) return;
  chatStatusEl.textContent = text;
  chatStatusEl.className = 'chat-status' + (kind ? ' ' + kind : '');
}

function updateComposerState() {
  if (sendBtn) {
    sendBtn.disabled = false;
    sendBtn.textContent = isStreaming ? 'Queue' : 'Send';
    sendBtn.title = isStreaming ? 'Queue this as the next turn' : 'Send';
  }
  if (stopBtn) {
    stopBtn.style.display = isStreaming ? 'inline-flex' : 'none';
  }
}

function appendMessage(role, content, opts) {
  opts = opts || {};
  clearEmpty();
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + role + (opts.cls ? ' ' + opts.cls : '');
  const who = document.createElement('div');
  who.className = 'who';
  who.textContent = role === 'user' ? 'You' : (opts.who || 'Assistant');
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = content;
  wrap.appendChild(who);
  wrap.appendChild(bubble);
  if (opts.attachments && opts.attachments.length) {
    const att = document.createElement('div');
    att.className = 'attachments';
    opts.attachments.forEach(a => {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.textContent = 'Attached: ' + a.filename;
      att.appendChild(chip);
    });
    wrap.appendChild(att);
  }
  msgEl.appendChild(wrap);
  msgEl.scrollTop = msgEl.scrollHeight;
  return wrap;
}

function artifactUrl(item) {
  return '/workspace/file?path=' + encodeURIComponent(item.rel_path || '');
}

function rememberArtifacts(items) {
  (items || []).forEach(item => {
    if (!item || !item.rel_path) return;
    if (!savedArtifacts.some(a => a.rel_path === item.rel_path)) {
      savedArtifacts.unshift(item);
    }
  });
  renderArtifactList();
}

function renderArtifactList(activePath) {
  if (!artifactListEl) return;
  if (!savedArtifacts.length) {
    artifactListEl.innerHTML = '<span style="color:var(--dim);font-size:12px">No artifacts yet</span>';
    return;
  }
  artifactListEl.innerHTML = '';
  savedArtifacts.forEach(item => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = item.filename || item.rel_path;
    if (activePath && item.rel_path === activePath) btn.classList.add('active');
    btn.onclick = () => openArtifact(item);
    artifactListEl.appendChild(btn);
  });
}

function appendArtifactChips(messageEl, items) {
  if (!messageEl || !items || !items.length) return;
  const box = document.createElement('div');
  box.className = 'saved-artifacts';
  items.forEach(item => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Saved: ' + (item.filename || item.rel_path || 'artifact');
    btn.title = item.rel_path || '';
    btn.onclick = () => openArtifact(item);
    box.appendChild(btn);
  });
  messageEl.appendChild(box);
}

async function openArtifact(item) {
  if (!item || !item.rel_path || !artifactPanel) return;
  rememberArtifacts([item]);
  artifactPanel.hidden = false;
  artifactTitle.textContent = item.filename || item.rel_path;
  artifactMeta.textContent = (item.kind || 'artifact') + ' - ' + item.rel_path;
  renderArtifactList(item.rel_path);
  const url = artifactUrl(item);
  const name = (item.filename || item.rel_path || '').toLowerCase();
  if (/\\.(html?|pdf|png|jpe?g|gif|webp|svg)$/i.test(name)) {
    artifactBody.innerHTML = '<iframe title="Artifact preview"></iframe>';
    artifactBody.querySelector('iframe').src = url;
    return;
  }
  artifactBody.innerHTML = '<pre class="artifact-text">Loading...</pre>';
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const text = await r.text();
    artifactBody.querySelector('.artifact-text').textContent = text;
  } catch (err) {
    artifactBody.querySelector('.artifact-text').textContent =
      'Could not load artifact: ' + (err.message || err);
  }
}

function closeArtifactPanel() {
  if (artifactPanel) artifactPanel.hidden = true;
}

function showArtifactPanel() {
  if (!artifactPanel) return;
  artifactPanel.hidden = false;
  renderArtifactList();
}

function newConversation() {
  if (isStreaming) stopStreaming();
  pendingQueue = [];
  savedArtifacts = [];
  renderArtifactList();
  if (window.matchMedia && window.matchMedia('(max-width: 860px)').matches) {
    closeArtifactPanel();
  } else {
    showArtifactPanel();
  }
  artifactTitle.textContent = 'No artifact selected';
  artifactMeta.textContent = 'AI-created files save to this laptop.';
  artifactBody.innerHTML = '<pre class="artifact-text">Artifacts from this chat will appear here.</pre>';
  history = [];
  conversationId = null;
  attached = [];
  renderAttached();
  updateComposerState();
  setStatus('Draft. First reply will save the chat on this laptop.', 'warn');
  msgEl.innerHTML = '<div class="empty">New conversation. Say hello to start.</div>';
  refreshConvoList();
}

function renderAttached() {
  if (!attached.length) {
    attachedChipsEl.style.display = 'none';
    attachedChipsEl.innerHTML = '';
    if (attachBtn) {
      attachBtn.textContent = 'Attach';
      attachBtn.classList.remove('has-files');
    }
    return;
  }
  attachedChipsEl.style.display = '';
  if (attachBtn) {
    attachBtn.textContent = attached.length + ' attached';
    attachBtn.classList.add('has-files');
  }
  attachedChipsEl.innerHTML = attached.map((a, i) => (
    '<span class="chip">Attached: ' + escapeHtml(a.filename) +
    ' <button onclick="removeAttachment(' + i + ')" title="Remove">x</button></span>'
  )).join('');
}

function removeAttachment(idx) {
  attached.splice(idx, 1);
  renderAttached();
}

async function onAttach(fileList) {
  if (!fileList || !fileList.length) return;
  const previousLabel = attachBtn ? attachBtn.textContent : '';
  if (attachBtn) {
    attachBtn.disabled = true;
    attachBtn.textContent = 'Attaching...';
  }
  for (const file of fileList) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch('/api/chat/upload', {method: 'POST', body: fd});
      const data = await r.json().catch(() => ({ok: false, error: 'Bad upload response'}));
      if (!r.ok || !data.ok) throw new Error(data.error || 'upload failed');
      attached.push({
        id: data.id,
        filename: data.filename,
        rel_path: data.rel_path || '',
        size: data.size,
      });
      setStatus('Attached ' + data.filename + '. It will be sent with your next message.', 'ok');
    } catch (err) {
      hrkit.toast('Attach failed: ' + (err.message || err), 'error');
      setStatus('Attach failed: ' + (err.message || err), 'error');
    }
  }
  document.getElementById('file-input').value = '';
  if (attachBtn) {
    attachBtn.disabled = false;
    attachBtn.textContent = previousLabel || 'Attach';
  }
  renderAttached();
}

async function loadEmployees() {
  try {
    const r = await fetch('/api/employees/list');
    const data = await r.json();
    if (!data.ok || !data.employees) return;
    for (const e of data.employees) {
      const opt = document.createElement('option');
      opt.value = e.id;
      opt.dataset.code = e.code || '';
      opt.textContent = (e.code ? e.code + ' — ' : '') + (e.name || '(no name)');
      empCtxSel.appendChild(opt);
    }
  } catch (err) { /* silent */ }
}

function onEmployeeContextChanged() {
  const opt = empCtxSel.options[empCtxSel.selectedIndex];
  employeeId = empCtxSel.value ? parseInt(empCtxSel.value, 10) : null;
  employeeCode = opt ? (opt.dataset.code || '') : '';
  if (employeeId) {
    chatSubEl.textContent = 'Talking about ' + (opt.textContent || '') + '. The AI sees this employee\\'s record + notes.';
  } else {
    chatSubEl.textContent = 'Ask about employees, leave, payroll and more.';
  }
  // Switching context starts a new conversation under that employee's folder.
  newConversation();
}

async function loadModels() {
  try {
    const r = await fetch('/api/models');
    const data = await r.json();
    if (!data.ok || !data.models || !data.models.length) return;
    const chatModels = data.models.filter(m => m.chat_compatible !== false);
    const hiddenNonChat = data.models.length - chatModels.length;
    modelSel.innerHTML = '<option value="">Default model</option>';
    if (!chatModels.length) {
      const opt = document.createElement('option');
      opt.disabled = true;
      opt.textContent = 'No chat models returned';
      modelSel.appendChild(opt);
      modelSel.title = 'Voice/audio models cannot power the HR assistant.';
      return;
    }
    for (const m of chatModels) {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = (m.free ? 'Free ' : '') + m.id + (m.free ? ' (free)' : '');
      modelSel.appendChild(opt);
    }
    if (hiddenNonChat) {
      const opt = document.createElement('option');
      opt.disabled = true;
      opt.textContent = hiddenNonChat + ' voice/audio model(s) hidden';
      modelSel.appendChild(opt);
      modelSel.title = 'Only chat-capable models are shown. Voice/audio models such as Chatterbox are hidden.';
    }
  } catch (err) {
    /* silent — picker stays at "Default model" */
  }
}

async function refreshConvoList() {
  try {
    const url = '/api/chat/conversations' + (employeeCode ? '?employee_code=' + encodeURIComponent(employeeCode) : '');
    const r = await fetch(url);
    const data = await r.json();
    if (!data.ok) {
      setStatus('Could not load saved chats: ' + (data.error || 'unknown error'), 'error');
      return;
    }
    if (!data.conversations.length) {
      convoListEl.innerHTML = '<div class="empty" style="padding:14px;font-size:12px">No saved chats yet.</div>';
      return;
    }
    convoListEl.innerHTML = data.conversations.map(c => (
      '<div class="convo-item' + (c.id === conversationId ? ' active' : '') +
      '" onclick="loadConversation(\\'' + escapeHtml(c.id) + '\\')">' +
      '<span class="convo-title">' + escapeHtml(c.title || c.id) + '</span>' +
      '<span class="convo-meta">' + escapeHtml(c.updated || c.created || '') + '</span>' +
      '</div>'
    )).join('');
  } catch (err) { /* silent */ }
}

async function loadConversation(id) {
  try {
    const url = '/api/chat/conversations/' + encodeURIComponent(id) +
                (employeeCode ? '?employee_code=' + encodeURIComponent(employeeCode) : '');
    if (isStreaming) stopStreaming();
    pendingQueue = [];
    const r = await fetch(url);
    const data = await r.json();
    if (!r.ok || !data.ok) { hrkit.toast('Load failed: ' + (data.error || ''), 'error'); return; }
    conversationId = id;
    history = data.messages || [];
    setStatus('Loaded saved chat: ' + id, 'ok');
    msgEl.innerHTML = '';
    if (!history.length) {
      msgEl.innerHTML = '<div class="empty">(empty conversation)</div>';
    } else {
      savedArtifacts = [];
      for (const turn of history) {
        const node = appendMessage(turn.role, turn.content || '', {attachments: turn.attachments || []});
        if (turn.artifacts && turn.artifacts.length) {
          rememberArtifacts(turn.artifacts);
          appendArtifactChips(node, turn.artifacts);
        }
      }
    }
    refreshConvoList();
  } catch (err) {
    hrkit.toast('Load failed: ' + err, 'error');
  }
}

function parseSseBlock(block) {
  let eventName = 'message';
  const dataLines = [];
  for (const rawLine of block.split(/\\r?\\n/)) {
    const line = rawLine.trimEnd();
    if (!line || line.startsWith(':')) continue;
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim() || 'message';
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!dataLines.length) return null;
  let data = {};
  try {
    data = JSON.parse(dataLines.join('\\n'));
  } catch (err) {
    data = {text: dataLines.join('\\n')};
  }
  return {eventName, data};
}

async function readSse(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    const blocks = buffer.split(/\\n\\n/);
    buffer = blocks.pop() || '';
    for (const block of blocks) {
      const parsed = parseSseBlock(block);
      if (parsed) onEvent(parsed.eventName, parsed.data);
    }
  }
  buffer += decoder.decode();
  const parsed = parseSseBlock(buffer);
  if (parsed) onEvent(parsed.eventName, parsed.data);
}

function stopStreaming() {
  if (!isStreaming || !currentAbort) return;
  currentAbort.abort();
  setStatus('Stopping current response...', 'warn');
}

function queueTurn(text, sentAttachments) {
  const queued = appendMessage(
    'user',
    text || '(attachment only)',
    {attachments: sentAttachments, cls: 'queued', who: 'Queued'}
  );
  pendingQueue.push({text, attachments: sentAttachments, queued});
  setStatus(
    'Queued ' + pendingQueue.length + ' message' + (pendingQueue.length === 1 ? '' : 's') + ' for the next turn.',
    'warn'
  );
}

function runNextQueuedTurn() {
  if (isStreaming || !pendingQueue.length) return;
  const next = pendingQueue.shift();
  if (next.queued) {
    next.queued.remove();
  }
  setTimeout(() => runChatTurn(next.text, next.attachments), 0);
}

async function runChatTurn(text, sentAttachments) {
  isStreaming = true;
  currentAbort = new AbortController();
  updateComposerState();
  setStatus(
    pendingQueue.length
      ? 'Streaming from UpfynAI... ' + pendingQueue.length + ' queued.'
      : 'Streaming from UpfynAI...',
    ''
  );

  appendMessage('user', text || '(attachment only)', {attachments: sentAttachments});
  const assistant = appendMessage('assistant', 'Thinking...', {cls: 'thinking'});
  const assistantBubble = assistant.querySelector('.bubble');
  const assistantWho = assistant.querySelector('.who');
  const payload = {
    message: text,
    history: history.slice(),
    model: modelSel.value || '',
    attachments: sentAttachments,
    conversation_id: conversationId,
    employee_id: employeeId,
  };
  let streamedText = '';
  let completed = false;
  let streamErrored = false;
  let stopped = false;
  try {
    const r = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
      signal: currentAbort.signal,
    });
    if (!r.ok || !r.body) {
      const data = await r.json().catch(() => ({ok: false, error: 'HTTP ' + r.status}));
      throw new Error(data.error || ('HTTP ' + r.status));
    }

    await readSse(r, (eventName, data) => {
      if (eventName === 'delta') {
        const chunk = data.text || '';
        if (!chunk) return;
        streamedText += chunk;
        assistant.classList.remove('thinking');
        assistantBubble.textContent = streamedText;
        msgEl.scrollTop = msgEl.scrollHeight;
        return;
      }
      if (eventName === 'error') {
        streamErrored = true;
        assistant.classList.remove('thinking');
        assistant.classList.add('error');
        assistantWho.textContent = data.retryable ? 'Retryable error' : 'Error';
        assistantBubble.textContent = data.retryable
          ? ((data.error || 'Provider busy') + '\\n\\nRetry the same message; it was not saved as a finished turn.')
          : (data.error || 'Stream failed');
        setStatus(data.retryable ? 'Provider busy. Message not saved; retry when ready.' : assistantBubble.textContent, 'error');
        return;
      }
      if (eventName === 'done') {
        completed = true;
        assistant.classList.remove('thinking');
        const finalText = data.reply || streamedText || '(no reply)';
        assistantBubble.textContent = finalText;
        if (data.artifacts && data.artifacts.length) {
          rememberArtifacts(data.artifacts);
          appendArtifactChips(assistant, data.artifacts);
          openArtifact(data.artifacts[0]);
        }
        history.push({role: 'user', content: text, attachments: sentAttachments});
        history.push({role: 'assistant', content: finalText, artifacts: data.artifacts || []});
        if (data.conversation_id) conversationId = data.conversation_id;
        setStatus(
          data.persisted
            ? ('Saved locally as ' + conversationId)
            : 'Reply received, but this workspace could not save the chat.',
          data.persisted ? 'ok' : 'warn'
        );
        refreshConvoList();
      }
    });
    if (!completed && !streamErrored) {
      throw new Error('Stream ended before the chat was saved.');
    }
  } catch (err) {
    stopped = err && err.name === 'AbortError';
    assistant.classList.remove('thinking');
    assistant.classList.add(stopped ? 'queued' : 'error');
    assistantWho.textContent = stopped ? 'Stopped' : 'Error';
    assistantBubble.textContent = stopped
      ? ((streamedText || 'Response stopped.') + '\\n\\nStopped by you. This partial reply was not saved.')
      : ('Network error: ' + (err.message || err));
    setStatus(
      stopped ? 'Stopped. Partial reply was not saved.' : 'Network error. Message was not saved.',
      stopped ? 'warn' : 'error'
    );
  } finally {
    isStreaming = false;
    currentAbort = null;
    updateComposerState();
    inputEl.focus();
    runNextQueuedTurn();
  }
}

async function sendMessage(ev) {
  ev.preventDefault();
  const text = (inputEl.value || '').trim();
  if (!text && !attached.length) return;
  const sentAttachments = attached.slice();
  inputEl.value = '';
  attached = [];
  renderAttached();
  if (isStreaming) {
    queueTurn(text, sentAttachments);
    return;
  }
  await runChatTurn(text, sentAttachments);
}

loadEmployees();
loadModels();
refreshConvoList();
updateComposerState();
inputEl.focus();
</script>
"""


def render_chat_page(conn=None) -> str:
    """Return the full HTML for the AI assistant page.

    Reuses the shared module shell so the chat picks up the dark theme,
    top-nav, and white-label app name automatically. ``nav_active=''`` keeps
    every module nav item un-highlighted (chat is not a module).

    When no AI API key is configured, prepends a banner that links to
    ``/settings`` so the user fixes onboarding instead of typing a message
    and receiving a cryptic 502.
    """
    body = _CHAT_BODY
    if conn is not None:
        try:
            if not branding.ai_api_key(conn):
                banner = (
                    '<div style="max-width:1180px;margin:0 auto 14px auto;'
                    'padding:14px 18px;border:1px solid var(--border);'
                    'border-radius:8px;background:rgba(255,200,80,0.08);'
                    'color:var(--text);font-size:13.5px;line-height:1.5">'
                    '<strong>AI is not configured yet.</strong> '
                    'Open <a href="/settings" style="color:var(--accent);'
                    'text-decoration:underline">Settings</a> to add an '
                    'OpenRouter or Upfyn API key (free models work without '
                    'billing). The assistant will be unavailable until then.'
                    '</div>'
                )
                body = banner + _CHAT_BODY
        except Exception:  # noqa: BLE001 — never break chat over banner
            pass
    return render_module_page(
        title="AI Assistant",
        nav_active="",
        body_html=body,
    )
