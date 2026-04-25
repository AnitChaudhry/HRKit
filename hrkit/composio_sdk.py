"""High-level Composio facade — SDK first, urllib fallback.

This module is the single integration point the rest of the app uses. It
prefers the official ``composio`` SDK (which gives access to the full
toolkit catalog, OAuth flows, and per-tool execution) and falls back to
the stdlib :mod:`hrkit.composio_client` if the SDK is not importable or
fails at runtime.

Both code paths return the same dict shapes so callers and tests don't
need to special-case the backend. See :func:`_normalize_*` for the
canonical shapes:

    list_apps    -> [{"slug": str, "name": str, "description": str,
                      "logo": str, "categories": [str]}]
    list_actions -> [{"slug": str, "name": str, "description": str,
                      "toolkit_slug": str, "deprecated": bool}]
    list_connections -> [{"id": str, "toolkit_slug": str,
                          "status": str, "created_at": str}]
    init_connection  -> {"redirect_url": str, "connected_account_id": str,
                         "raw": dict}
    execute_action   -> {"successful": bool, "data": dict, "error": str}

Stdlib + ``composio`` (when installed). Never imports from
:mod:`hrkit.server` or any module file.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from typing import Any

from hrkit import branding, composio_client
from hrkit.db import get_setting, set_setting

log = logging.getLogger(__name__)

USER_ID_KEY = "COMPOSIO_USER_ID"
DEFAULT_USER_ID_PREFIX = "hrkit-local-"


# ---------------------------------------------------------------------------
# SDK availability
# ---------------------------------------------------------------------------
def is_sdk_available() -> bool:
    """Return True if the high-level ``composio`` SDK can be imported."""
    try:
        import composio  # noqa: F401
    except ImportError:
        return False
    return True


def _client(conn: sqlite3.Connection):
    """Return a ``Composio`` SDK client, or None if unavailable / no key."""
    if conn is None:
        return None
    api_key = branding.composio_api_key(conn)
    if not api_key:
        return None
    try:
        from composio import Composio
    except ImportError:
        return None
    try:
        return Composio(api_key=api_key)
    except Exception as exc:  # noqa: BLE001 - SDK init must never crash callers
        log.warning("composio SDK init failed: %s", exc)
        return None


def user_id(conn: sqlite3.Connection) -> str:
    """Return the stable per-workspace user_id used for OAuth flows.

    Persisted in settings the first time it's read so OAuth tokens survive
    workspace renames. Derived from a hash of the conn's first-touch
    timestamp + the existing settings table identity, so two parallel
    workspaces don't collide if they happen to be at the same path.
    """
    existing = get_setting(conn, USER_ID_KEY, "")
    if existing:
        return existing
    seed = f"{id(conn)}-{branding.app_name()}"
    derived = DEFAULT_USER_ID_PREFIX + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    try:
        set_setting(conn, USER_ID_KEY, derived)
    except sqlite3.Error:
        pass
    return derived


# ---------------------------------------------------------------------------
# Normalizers — single source of truth for response shapes
# ---------------------------------------------------------------------------
def _normalize_app(item: Any) -> dict:
    """Convert an SDK toolkit item or urllib /apps row into the canonical dict."""
    if isinstance(item, dict):
        slug = item.get("slug") or item.get("key") or item.get("appId") or item.get("name") or ""
        return {
            "slug": str(slug).lower(),
            "name": str(item.get("name") or slug or ""),
            "description": str(item.get("description") or item.get("metaDescription") or ""),
            "logo": str(item.get("logo") or item.get("logoUrl") or ""),
            "categories": list(item.get("categories") or item.get("tags") or []),
        }
    # SDK Toolkit object — duck-type its attributes.
    return {
        "slug": str(getattr(item, "slug", "") or "").lower(),
        "name": str(getattr(item, "name", "") or ""),
        "description": str(
            getattr(item, "description", "")
            or getattr(item, "meta_description", "")
            or ""
        ),
        "logo": str(getattr(item, "logo", "") or ""),
        "categories": list(
            getattr(item, "categories", None) or getattr(item, "tags", None) or []
        ),
    }


def _normalize_action(item: Any) -> dict:
    """Convert an SDK Tool or urllib /actions row into the canonical dict."""
    if isinstance(item, dict):
        return {
            "slug": str(item.get("slug") or item.get("name") or "").upper(),
            "name": str(item.get("name") or item.get("displayName") or ""),
            "description": str(
                item.get("description") or item.get("human_description") or ""
            ),
            "toolkit_slug": str(
                item.get("toolkit_slug")
                or item.get("appName")
                or (item.get("toolkit") or {}).get("slug")
                or ""
            ).lower(),
            "deprecated": bool(item.get("deprecated") or item.get("is_deprecated")),
        }
    toolkit = getattr(item, "toolkit", None)
    if isinstance(toolkit, dict):
        toolkit_slug = toolkit.get("slug") or toolkit.get("name") or ""
    else:
        toolkit_slug = str(
            getattr(toolkit, "slug", "")
            or getattr(toolkit, "name", "")
            or ""
        )
    return {
        "slug": str(getattr(item, "slug", "") or "").upper(),
        "name": str(getattr(item, "name", "") or ""),
        "description": str(
            getattr(item, "human_description", "")
            or getattr(item, "description", "")
            or ""
        ),
        "toolkit_slug": str(toolkit_slug).lower(),
        "deprecated": bool(
            getattr(item, "deprecated", False)
            or getattr(item, "is_deprecated", False)
        ),
    }


def _normalize_connection(item: Any) -> dict:
    """Convert an SDK ConnectedAccount or urllib row into the canonical dict."""
    if isinstance(item, dict):
        toolkit = item.get("toolkit_slug") or item.get("appName") or ""
        if not toolkit:
            t = item.get("toolkit") or item.get("app") or {}
            if isinstance(t, dict):
                toolkit = t.get("slug") or t.get("name") or ""
        return {
            "id": str(item.get("id") or item.get("nanoid") or ""),
            "toolkit_slug": str(toolkit or "").lower(),
            "status": str(item.get("status") or "").upper(),
            "created_at": str(item.get("createdAt") or item.get("created_at") or ""),
        }
    toolkit = getattr(item, "toolkit_slug", None) or ""
    if not toolkit:
        t = getattr(item, "toolkit", None)
        if t is not None:
            toolkit = getattr(t, "slug", None) or getattr(t, "name", None) or ""
    return {
        "id": str(getattr(item, "id", "") or getattr(item, "nanoid", "") or ""),
        "toolkit_slug": str(toolkit or "").lower(),
        "status": str(getattr(item, "status", "") or "").upper(),
        "created_at": str(
            getattr(item, "created_at", "") or getattr(item, "createdAt", "") or ""
        ),
    }


def _normalize_execution(item: Any) -> dict:
    """Convert an SDK ToolExecutionResponse or urllib raw dict into canonical."""
    if isinstance(item, dict):
        return {
            "successful": bool(item.get("successful", item.get("ok", True))),
            "data": item.get("data") or item.get("result") or {},
            "error": str(item.get("error") or ""),
        }
    return {
        "successful": bool(getattr(item, "successful", True)),
        "data": getattr(item, "data", None) or {},
        "error": str(getattr(item, "error", "") or ""),
    }


# ---------------------------------------------------------------------------
# Public facade — try SDK, fall back to urllib
# ---------------------------------------------------------------------------
def is_configured(conn: sqlite3.Connection) -> bool:
    """Return True if a Composio API key is on file (either backend works)."""
    return composio_client.is_configured(conn)


def list_apps(conn: sqlite3.Connection, *, limit: int | None = 100) -> list[dict]:
    """List all Composio toolkits known to the user's account."""
    sdk = _client(conn)
    if sdk is not None:
        try:
            resp = sdk.toolkits.list(limit=limit)
            items = getattr(resp, "items", None) or list(resp or [])
            return [_normalize_app(it) for it in items]
        except Exception as exc:  # noqa: BLE001 - fall through to urllib
            log.info("composio SDK list_apps failed, falling back: %s", exc)
    try:
        return [_normalize_app(it) for it in composio_client.list_apps(conn)]
    except composio_client.ComposioError as exc:
        log.warning("composio list_apps failed: %s", exc)
        return []


def list_actions(conn: sqlite3.Connection, app_slug: str | None = None,
                 *, search: str | None = None, limit: int | None = 200) -> list[dict]:
    """List actions/tools, optionally filtered by app slug or text search."""
    sdk = _client(conn)
    if sdk is not None:
        try:
            tools = sdk.tools.get_raw_composio_tools(
                toolkits=[app_slug] if app_slug else None,
                search=search,
                limit=limit,
            )
            return [_normalize_action(t) for t in (tools or [])]
        except Exception as exc:  # noqa: BLE001
            log.info("composio SDK list_actions failed, falling back: %s", exc)
    # Best-effort urllib fallback (composio_client doesn't ship a list_actions yet).
    return []


def list_connections(conn: sqlite3.Connection) -> list[dict]:
    """List the user's connected accounts."""
    sdk = _client(conn)
    if sdk is not None:
        try:
            resp = sdk.connected_accounts.list()
            items = getattr(resp, "items", None) or list(resp or [])
            return [_normalize_connection(it) for it in items]
        except Exception as exc:  # noqa: BLE001
            log.info("composio SDK list_connections failed, falling back: %s", exc)
    try:
        return [_normalize_connection(it) for it in composio_client.list_connections(conn)]
    except composio_client.ComposioError as exc:
        log.warning("composio list_connections failed: %s", exc)
        return []


def init_connection(conn: sqlite3.Connection, app_slug: str) -> dict:
    """Start an OAuth flow for ``app_slug``; returns the redirect URL."""
    if not app_slug:
        return {"redirect_url": "", "connected_account_id": "", "raw": {},
                "error": "app_slug is required"}
    sdk = _client(conn)
    if sdk is not None:
        try:
            req = sdk.toolkits.authorize(user_id=user_id(conn), toolkit=app_slug)
            return {
                "redirect_url": getattr(req, "redirect_url", "") or "",
                "connected_account_id": getattr(req, "id", "") or "",
                "raw": {"id": getattr(req, "id", ""), "status": getattr(req, "status", "")},
            }
        except Exception as exc:  # noqa: BLE001
            log.info("composio SDK init_connection failed, falling back: %s", exc)
    try:
        return composio_client.init_connection(conn, app_slug)
    except composio_client.ComposioError as exc:
        return {"redirect_url": "", "connected_account_id": "", "raw": {},
                "error": str(exc)}


def execute_action(
    conn: sqlite3.Connection,
    action_slug: str,
    arguments: dict | None = None,
    *,
    connected_account_id: str | None = None,
) -> dict:
    """Run a Composio action; returns ``{successful, data, error}``."""
    arguments = arguments or {}
    sdk = _client(conn)
    if sdk is not None:
        try:
            resp = sdk.tools.execute(
                slug=action_slug,
                arguments=arguments,
                connected_account_id=connected_account_id,
                user_id=user_id(conn),
            )
            return _normalize_execution(resp)
        except Exception as exc:  # noqa: BLE001
            log.info("composio SDK execute_action failed, falling back: %s", exc)
    try:
        raw = composio_client.execute_action(
            conn, action_slug, arguments, connected_account_id=connected_account_id
        )
        return _normalize_execution(raw)
    except composio_client.ComposioError as exc:
        return {"successful": False, "data": {}, "error": str(exc)}


__all__ = [
    "is_sdk_available",
    "is_configured",
    "user_id",
    "list_apps",
    "list_actions",
    "list_connections",
    "init_connection",
    "execute_action",
]
