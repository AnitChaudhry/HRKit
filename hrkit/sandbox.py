"""AI sandbox enforcement.

When ``AI_LOCAL_ONLY`` is on (the default), the AI agent is constrained to
operate **only** on local data:

* The workspace's SQLite database (read + write through ``query_records``)
* Imported CSV tables in the workspace folder
* Per-employee files under ``employees/<EMP-CODE>/``
* User-defined recipes (which are themselves local Python callables)

It MUST NOT:

* Reach the public internet (no ``web_search`` / ``web_fetch``)
* Trigger Composio actions (those all touch external APIs)
* Read or write files outside the workspace root

This module provides three layers of enforcement, applied at runtime so the
restriction holds even if the LLM is jailbroken into trying to call a
forbidden tool:

1. :func:`filter_tools` — strips network-touching tools from the list
   passed into the agent. The agent literally cannot reference what it
   doesn't have.
2. :func:`assert_path_in_workspace` — used by file-touching tools to reject
   any ``..``/escaped path before the open() call.
3. :func:`network_disabled` — a context manager that monkey-patches
   ``urllib.request.urlopen``, ``http.client.HTTPConnection.request`` and
   ``socket.create_connection`` to raise :class:`NetworkBlocked` for the
   duration of an agent run. Belt-and-braces in case a tool somehow slips
   through ``filter_tools``.

Together these give a meaningful, enforced sandbox at the Python layer.
This is **not** an OS-level process sandbox (no seccomp, no AppContainer);
that requires an external dependency and OS-specific code. The Python-layer
sandbox is good enough for the threat model — a curious or jailbroken LLM,
not a malicious operator who already controls the workspace.
"""
from __future__ import annotations

import contextlib
import logging
import socket
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

from . import branding

log = logging.getLogger(__name__)


class NetworkBlocked(RuntimeError):
    """Raised by the sandbox when a network call is attempted in local-only
    mode. Carries the target host so logs can show what was blocked."""


# Names of tools that are network-touching and must be removed from the
# agent's tool list when sandboxed. Match by the function's ``__name__`` /
# slug (case-insensitive). Composio actions follow ``ACTION_VERB_NOUN``
# upper-snake convention and are always blocked when sandboxed.
_NETWORK_TOOL_NAMES: frozenset[str] = frozenset({
    "web_search",
    "web_fetch",
    "web_get",
    "http_get",
    "http_post",
    "fetch_url",
})


def is_sandboxed(conn) -> bool:
    """Return True when the agent is in local-only mode (the default).

    Thin wrapper around :func:`branding.ai_local_only` so callers don't have
    to know which env/setting key is the source of truth.
    """
    return branding.ai_local_only(conn)


def _tool_name(tool: Any) -> str:
    """Best-effort name extraction matching :mod:`hrkit.ai`'s helper."""
    for attr in ("name", "__name__"):
        val = getattr(tool, attr, None)
        if isinstance(val, str) and val:
            return val
    if isinstance(tool, dict):
        for key in ("name", "slug"):
            v = tool.get(key)
            if isinstance(v, str) and v:
                return v
    return ""


def _looks_like_composio_action(name: str) -> bool:
    """Composio actions are uppercase-underscore slugs like
    GMAIL_SEND_EMAIL or GOOGLECALENDAR_LIST_EVENTS. Anything matching that
    shape is treated as network-touching."""
    if not name:
        return False
    if not name.isupper():
        return False
    return "_" in name and len(name) > 6


def is_network_tool(tool: Any) -> bool:
    """Return True if the tool would touch the network.

    Conservative — when in doubt we drop the tool. Three criteria:

    * Name matches a known network-tool slug (web_search, web_fetch, ...).
    * Name looks like a Composio action slug (UPPER_CASE_WITH_UNDERSCORES).
    * The tool exposes a ``network`` attribute set to a truthy value.
    """
    name = _tool_name(tool)
    if name.lower() in _NETWORK_TOOL_NAMES:
        return True
    if _looks_like_composio_action(name):
        return True
    flag = getattr(tool, "network", None)
    if flag is True:
        return True
    if isinstance(tool, dict) and tool.get("network"):
        return True
    return False


def filter_tools(tools: Iterable[Any] | None, conn) -> list[Any]:
    """Drop network-touching tools when the workspace is sandboxed.

    No-op (returns the input as a list) when the sandbox is disabled, so the
    caller always passes the result through ``ai.run_agent`` without
    branching. Logs each dropped tool at INFO level so operators can see in
    ``hrkit serve`` output which tools the agent didn't get.
    """
    items = list(tools or [])
    if not is_sandboxed(conn):
        return items
    kept: list[Any] = []
    for tool in items:
        if is_network_tool(tool):
            log.info("sandbox: dropped network tool %r", _tool_name(tool) or tool)
            continue
        kept.append(tool)
    return kept


def assert_path_in_workspace(path: str | Path, workspace_root: str | Path) -> Path:
    """Resolve ``path`` and reject if it escapes ``workspace_root``.

    Returns the resolved absolute Path on success; raises ``ValueError``
    with a clear message otherwise. Intended for any tool that opens a
    file based on LLM-supplied input.
    """
    root = Path(workspace_root).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(
            f"path escapes workspace: {path!r} resolves outside {root}"
        )
    return candidate


# --- Network-disable context manager -----------------------------------------
#
# Some tools (especially user-defined recipes) might still attempt an HTTP
# call even after filter_tools has done its job. We backstop this by
# monkey-patching the three most common entry points to outbound networking
# in the stdlib for the duration of an agent run. The patch is thread-local
# via a ``threading.local`` flag so other threads (the HTTP server itself)
# keep working normally.

_local_state = threading.local()


def _is_blocked_in_this_thread() -> bool:
    return getattr(_local_state, "blocked", False)


_orig_urlopen = None
_orig_http_request = None
_orig_create_connection = None
_patched = False
_patch_lock = threading.Lock()


def _install_patches_once() -> None:
    """Install the monkey-patches lazily, just once per process."""
    global _orig_urlopen, _orig_http_request, _orig_create_connection, _patched
    with _patch_lock:
        if _patched:
            return
        import http.client
        import urllib.request

        _orig_urlopen = urllib.request.urlopen
        _orig_http_request = http.client.HTTPConnection.request
        _orig_create_connection = socket.create_connection

        def _guard_urlopen(*args, **kwargs):
            if _is_blocked_in_this_thread():
                target = args[0] if args else kwargs.get("url", "?")
                raise NetworkBlocked(
                    f"sandbox: blocked outbound HTTP to {target!r} "
                    f"(turn off AI_LOCAL_ONLY in /settings to allow)"
                )
            return _orig_urlopen(*args, **kwargs)

        def _guard_http_request(self, method, url, *args, **kwargs):
            if _is_blocked_in_this_thread():
                raise NetworkBlocked(
                    f"sandbox: blocked outbound {method} {self.host}{url!r} "
                    f"(turn off AI_LOCAL_ONLY in /settings to allow)"
                )
            return _orig_http_request(self, method, url, *args, **kwargs)

        def _guard_create_connection(address, *args, **kwargs):
            if _is_blocked_in_this_thread():
                host, _port = (address[0], address[1]) if isinstance(address, tuple) else (address, 0)
                if str(host) not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
                    raise NetworkBlocked(
                        f"sandbox: blocked socket connect to {host}"
                    )
            return _orig_create_connection(address, *args, **kwargs)

        urllib.request.urlopen = _guard_urlopen  # type: ignore[assignment]
        http.client.HTTPConnection.request = _guard_http_request  # type: ignore[assignment]
        socket.create_connection = _guard_create_connection  # type: ignore[assignment]
        _patched = True


@contextlib.contextmanager
def network_disabled():
    """Block outbound HTTP from this thread until the block exits.

    Loopback (127.0.0.1, ::1) is allowed so the agent can still hit its own
    server's APIs if a local tool needs to.

    Use as ``with sandbox.network_disabled(): await agent.run(...)``.
    """
    _install_patches_once()
    prev = getattr(_local_state, "blocked", False)
    _local_state.blocked = True
    try:
        yield
    finally:
        _local_state.blocked = prev


@contextlib.contextmanager
def network_disabled_if(conn):
    """Convenience: only enable the block when the workspace is sandboxed."""
    if is_sandboxed(conn):
        with network_disabled():
            yield
    else:
        yield


def status_summary(conn) -> str:
    """Single-line description for the startup banner / settings page."""
    if is_sandboxed(conn):
        return ("AI sandbox: ENABLED — agent restricted to this workspace's "
                "SQLite + local files; no web, no Composio.")
    return ("AI sandbox: DISABLED — agent can use web_search, web_fetch, "
            "and any connected Composio actions.")


__all__ = [
    "NetworkBlocked",
    "is_sandboxed",
    "is_network_tool",
    "filter_tools",
    "assert_path_in_workspace",
    "network_disabled",
    "network_disabled_if",
    "status_summary",
]
