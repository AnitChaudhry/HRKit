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
    ai, ai_tools, branding, chat_storage, composio_sdk,
    employee_fs, recipes_ui, uploads,
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
                   "create_candidate", "create_leave_request"),
        "update": ("update_request", "update_run", "update_review",
                   "update_attendance", "update_task", "update_record",
                   "update_candidate"),
        "delete": ("delete_request", "delete_run", "delete_review",
                   "delete_attendance", "delete_task", "delete_record",
                   "delete_candidate"),
    }
    for name in canonical.get(op, ()) + synonyms.get(op, ()):
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    raise ValueError(
        f"module '{getattr(mod, 'NAME', mod.__name__)}' has no '{op}' helper"
    )


def _dispatch(conn, module: str, op: str, args: dict[str, Any] | None) -> Any:
    """Call the right per-module helper for ``op``.

    Centralised so both the live tool and unit tests exercise the same path.
    Returns the helper's raw result (id / row / list / None).
    """
    op = (op or "").strip().lower()
    if op not in _ALLOWED_OPS:
        raise ValueError(f"op must be one of {_ALLOWED_OPS}, got '{op}'")
    args = dict(args or {})
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
        return fn(conn, data)
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
        return fn(conn, int(item_id), data)
    if op == "delete":
        item_id = args.get("id") or args.get("item_id")
        if item_id is None:
            raise ValueError("'delete' requires args.id")
        return fn(conn, int(item_id))
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
          args: For 'get'/'delete' use {{"id": <int>}}. For 'create' use
                {{"data": {{...fields...}}}} or pass fields inline. For
                'update' use {{"id": <int>, "data": {{...fields_to_change...}}}}.
                For 'list' pass {{}} or omit.

        Returns a JSON string with the result, or an error message prefixed
        with 'error:'. Always confirm with the user before calling 'delete'.
        """
        try:
            result = _dispatch(conn, module, op, args or {})
            return _summarise(result)
        except (ValueError, TypeError, KeyError) as exc:
            return f"error: {exc}"
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("query_records failed: module=%s op=%s", module, op)
            return f"error: {type(exc).__name__}: {exc}"

    # Stuff the dynamic module list into the docstring so the LLM sees it.
    if query_records.__doc__:
        query_records.__doc__ = query_records.__doc__.replace("{modules}", allowed_str)
    return query_records


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
        "Always confirm actions before deleting. "
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
        " You also have web_search(query) and web_fetch(url) for live web lookups."
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
        body = body or {}
        message = (body.get("message") or "").strip()
        attachments_in = body.get("attachments") or []
        if not message and not attachments_in:
            handler._json({"ok": False, "error": "message or attachment required"}, code=400)
            return

        conn = handler.server.conn  # type: ignore[attr-defined]
        workspace_root = _workspace_root_for(handler)

        # Inline attachment text so the AI can read files the user pinned.
        full_message = _augment_with_attachments(workspace_root, message, attachments_in)
        prompt = _format_history(body.get("history"), full_message)

        # Optional per-employee context: when the chat is "talking about"
        # someone, prefix the system prompt with their full record + notes.
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
        tool = _build_query_tool(conn)
        # Module CRUD is always available. Web tools are gated behind the
        # AI_LOCAL_ONLY setting (default ON) so HR data never leaves the
        # local process unless the operator explicitly opts the agent into
        # network tools. Recipes are user-defined templates and are local.
        tools: list = [tool, *_build_imported_table_tools(conn)]
        if not branding.ai_local_only(conn):
            tools.extend(ai_tools.builtin_tools())
        if workspace_root is not None:
            try:
                tools.extend(recipes_ui.build_recipe_tools(conn, workspace_root))
            except Exception as exc:  # noqa: BLE001
                log.warning("recipes_ui.build_recipe_tools failed: %s", exc)
        model_override = (body.get("model") or "").strip() or None

        try:
            reply = await ai.run_agent(
                prompt, conn=conn, system=system, tools=tools, model=model_override,
            )
        except RuntimeError as exc:
            handler._json({"ok": False, "error": str(exc)}, code=502)
            return

        # Persist the turn to disk if we know the workspace root.
        conversation_id = (body.get("conversation_id") or "").strip()
        if workspace_root:
            try:
                if not conversation_id:
                    conversation_id = chat_storage.new_conversation_id(message)
                # Reload prior messages so we append rather than overwrite.
                existing = chat_storage.load_conversation(
                    workspace_root=workspace_root,
                    conversation_id=conversation_id,
                ) or {}
                messages = list(existing.get("messages") or body.get("history") or [])
                messages.append({
                    "role": "user", "content": message, "attachments": attachments_in,
                })
                messages.append({"role": "assistant", "content": reply})
                chat_storage.save_conversation(
                    workspace_root=workspace_root,
                    conversation_id=conversation_id,
                    messages=messages,
                    model=model_override,
                    employee_code=employee_code_for_save,
                )
            except Exception as exc:  # noqa: BLE001 - persistence is best-effort
                log.warning("chat_storage.save failed: %s", exc)

        handler._json({"ok": True, "reply": reply, "conversation_id": conversation_id})
    except Exception as exc:
        log.error("handle_chat_message failed: %s\n%s", exc, traceback.format_exc())
        handler._json({"ok": False, "error": ai.friendly_error(exc)}, code=500)


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
      </div>
      <div class="head-controls">
        <select id="model-select" title="Pick which model handles this conversation">
          <option value="">Default model</option>
        </select>
        <button class="icon" type="button" onclick="newConversation()">Clear</button>
      </div>
    </div>
    <div id="messages"><div class="empty">Say hello to get started.</div></div>
    <div id="attached-chips" class="attached-chips" style="display:none"></div>
    <form class="chat-input" onsubmit="sendMessage(event)">
      <button type="button" class="attach" onclick="document.getElementById('file-input').click()" title="Attach a file">📎</button>
      <input type="file" id="file-input" multiple style="display:none" onchange="onAttach(this.files)">
      <textarea id="chat-input" placeholder="Ask anything... (Shift+Enter for newline)"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage(event);}"></textarea>
      <button type="submit" class="send" id="send-btn">Send</button>
    </form>
  </section>
</div>
<script>
let history = [];
let conversationId = null;
let attached = [];   // [{id, filename, size}]
let employeeId = null;
let employeeCode = '';
const msgEl = document.getElementById('messages');
const inputEl = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const modelSel = document.getElementById('model-select');
const convoListEl = document.getElementById('convo-list');
const attachedChipsEl = document.getElementById('attached-chips');
const empCtxSel = document.getElementById('employee-context');
const chatSubEl = document.getElementById('chat-sub');

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function clearEmpty() {
  const e = msgEl.querySelector('.empty');
  if (e) e.remove();
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
      chip.textContent = '📎 ' + a.filename;
      att.appendChild(chip);
    });
    wrap.appendChild(att);
  }
  msgEl.appendChild(wrap);
  msgEl.scrollTop = msgEl.scrollHeight;
  return wrap;
}

function newConversation() {
  history = [];
  conversationId = null;
  attached = [];
  renderAttached();
  msgEl.innerHTML = '<div class="empty">New conversation. Say hello to start.</div>';
  refreshConvoList();
}

function renderAttached() {
  if (!attached.length) {
    attachedChipsEl.style.display = 'none';
    attachedChipsEl.innerHTML = '';
    return;
  }
  attachedChipsEl.style.display = '';
  attachedChipsEl.innerHTML = attached.map((a, i) => (
    '<span class="chip">📎 ' + escapeHtml(a.filename) +
    ' <button onclick="removeAttachment(' + i + ')" title="Remove">×</button></span>'
  )).join('');
}

function removeAttachment(idx) {
  attached.splice(idx, 1);
  renderAttached();
}

async function onAttach(fileList) {
  if (!fileList || !fileList.length) return;
  for (const file of fileList) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch('/api/chat/upload', {method: 'POST', body: fd});
      const data = await r.json();
      if (!r.ok || !data.ok) throw new Error(data.error || 'upload failed');
      attached.push({id: data.id, filename: data.filename, size: data.size});
    } catch (err) {
      alert('Attach failed: ' + (err.message || err));
    }
  }
  document.getElementById('file-input').value = '';
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
    modelSel.innerHTML = '<option value="">Default model</option>';
    for (const m of data.models) {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = (m.free ? '★ ' : '') + m.id + (m.free ? '  (free)' : '');
      modelSel.appendChild(opt);
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
    if (!data.ok) return;
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
    const r = await fetch(url);
    const data = await r.json();
    if (!r.ok || !data.ok) { alert('Load failed: ' + (data.error || '')); return; }
    conversationId = id;
    history = data.messages || [];
    msgEl.innerHTML = '';
    if (!history.length) {
      msgEl.innerHTML = '<div class="empty">(empty conversation)</div>';
    } else {
      for (const turn of history) {
        appendMessage(turn.role, turn.content || '', {attachments: turn.attachments || []});
      }
    }
    refreshConvoList();
  } catch (err) {
    alert('Load failed: ' + err);
  }
}

async function sendMessage(ev) {
  ev.preventDefault();
  const text = (inputEl.value || '').trim();
  if (!text && !attached.length) return;
  inputEl.value = '';
  sendBtn.disabled = true;
  const sentAttachments = attached.slice();
  appendMessage('user', text || '(attachment only)', {attachments: sentAttachments});
  const thinking = appendMessage('assistant', 'Thinking...', {cls: 'thinking'});
  const payload = {
    message: text,
    history: history.slice(),
    model: modelSel.value || '',
    attachments: sentAttachments,
    conversation_id: conversationId,
    employee_id: employeeId,
  };
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await r.json().catch(() => ({ok: false, error: 'Bad JSON response'}));
    thinking.remove();
    if (r.ok && data.ok) {
      appendMessage('assistant', data.reply || '(no reply)');
      history.push({role: 'user', content: text, attachments: sentAttachments});
      history.push({role: 'assistant', content: data.reply || ''});
      if (data.conversation_id) conversationId = data.conversation_id;
      attached = [];
      renderAttached();
      refreshConvoList();
    } else {
      appendMessage('assistant', data.error || ('HTTP ' + r.status), {cls: 'error', who: 'Error'});
    }
  } catch (err) {
    thinking.remove();
    appendMessage('assistant', 'Network error: ' + err, {cls: 'error', who: 'Error'});
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

loadEmployees();
loadModels();
refreshConvoList();
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
