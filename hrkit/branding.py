"""Canonical settings accessors for the HR app.

All other modules MUST import these helpers instead of reading os.environ
or the SQLite settings table directly. Read order is:

    1. Environment variable
    2. settings table (db.get_setting)
    3. Default

This is the single source of truth for branding + BYOK keys.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3

from .db import get_setting, set_setting

# ---- Defaults --------------------------------------------------------------

DEFAULT_APP_NAME = "HR Desk"
DEFAULT_AI_PROVIDER = "openrouter"
DEFAULT_AI_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

PROVIDER_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "upfyn": "https://ai.upfyn.com/v1",
}

# Env var names mapped to settings keys (settings keys == env var names here).
ENV_VAR_FOR_KEY = {
    "APP_NAME": "APP_NAME",
    "AI_PROVIDER": "AI_PROVIDER",
    "AI_API_KEY": "AI_API_KEY",
    "AI_MODEL": "AI_MODEL",
    "COMPOSIO_API_KEY": "COMPOSIO_API_KEY",
    # When '1' / 'true' / 'on' (default), the AI agent is sandboxed to local
    # data only — no web_search/web_fetch, no network-touching tools. Anything
    # in the agent's tool list must read from the SQLite DB or local files.
    "AI_LOCAL_ONLY": "AI_LOCAL_ONLY",
}


# ---- Internal --------------------------------------------------------------

def _read(conn: sqlite3.Connection | None, key: str, default: str = "") -> str:
    """Resolve a setting via env var, then DB, then default."""
    env_name = ENV_VAR_FOR_KEY.get(key, key)
    val = os.environ.get(env_name)
    if val is not None and val != "":
        return val
    if conn is not None:
        try:
            db_val = get_setting(conn, key, "")
        except sqlite3.Error:
            db_val = ""
        if db_val:
            return db_val
    return default


# ---- Public accessors ------------------------------------------------------

def app_name() -> str:
    """Return the human-readable application name.

    Resolution order: env var → workspace config.json (mirrored by
    ``set_settings``) → live DB connection at ``hrkit.server.CONN``
    (with a one-time mirror back to config.json on hit, so the next call
    short-circuits at the cheaper config.json path) → default. Lazy + best
    effort so this still works in CLI / test contexts with no live server.
    """
    val = os.environ.get("APP_NAME")
    if val:
        return val
    # Workspace config.json (mirrored by set_settings on writes).
    workspace_root = None
    try:
        from . import config as _cfg
        workspace_root = _cfg.find_workspace()
        if workspace_root is not None:
            data = _cfg.load_settings(workspace_root)
            cfg_val = data.get("app_name") or data.get("APP_NAME")
            if cfg_val:
                return str(cfg_val)
    except Exception:
        pass
    # Live server connection (only set while ``hrkit serve`` is running).
    try:
        import sys
        srv = sys.modules.get("hrkit.server")
        conn = getattr(srv, "CONN", None) if srv is not None else None
        if conn is not None:
            db_val = get_setting(conn, "APP_NAME", "")
            if db_val:
                # One-time backfill: settings table had a value but config.json
                # did not. Write it through so future reads are stateless.
                if workspace_root is not None:
                    try:
                        from . import config as _cfg
                        data = _cfg.load_settings(workspace_root)
                        if not data.get("app_name"):
                            data["app_name"] = db_val
                            _cfg.save_settings(workspace_root, data)
                    except Exception:
                        pass
                return db_val
    except Exception:
        pass
    return DEFAULT_APP_NAME


def app_slug() -> str:
    """Return a lowercase, url-safe slug derived from app_name()."""
    name = app_name().lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return slug or "hr-desk"


def ai_provider(conn: sqlite3.Connection | None) -> str:
    """Return the AI provider id ('openrouter' or 'upfyn')."""
    val = _read(conn, "AI_PROVIDER", DEFAULT_AI_PROVIDER).strip().lower()
    if val not in PROVIDER_BASE_URLS:
        return DEFAULT_AI_PROVIDER
    return val


def ai_api_key(conn: sqlite3.Connection | None) -> str:
    """Return the AI API key, or empty string if not configured."""
    return _read(conn, "AI_API_KEY", "")


def ai_model(conn: sqlite3.Connection | None) -> str:
    """Return the model id to use for AI calls."""
    return _read(conn, "AI_MODEL", DEFAULT_AI_MODEL)


def ai_base_url(conn: sqlite3.Connection | None) -> str:
    """Return the OpenAI-compatible base URL for the active provider."""
    provider = ai_provider(conn)
    return PROVIDER_BASE_URLS.get(provider, PROVIDER_BASE_URLS[DEFAULT_AI_PROVIDER])


def composio_api_key(conn: sqlite3.Connection | None) -> str:
    """Return the Composio API key, or empty string if not configured."""
    return _read(conn, "COMPOSIO_API_KEY", "")


def ai_local_only(conn: sqlite3.Connection | None) -> bool:
    """Return True when the AI agent should be hard-restricted to local data
    (no web tools, no Composio actions exposed as agent tools).

    Default: **False** — the agent is a full-capability sandboxed agent
    (web + Composio + workspace file writes). Only the path/network
    boundary is enforced (file ops stay inside the workspace; SQL stays
    inside this DB). Flip the setting ON only when the operator wants
    the agent denied web + external integration access — e.g. when
    handling unusually sensitive employee data and prompts must never
    reach the public internet.

    Reads ``AI_LOCAL_ONLY`` from env var first, then settings, then default.
    Truthy values: '1', 'true', 'on', 'yes' (case-insensitive).
    """
    raw = _read(conn, "AI_LOCAL_ONLY", "0")
    return str(raw).strip().lower() in ("1", "true", "on", "yes")


COMPOSIO_DISABLED_TOOLS_KEY = "COMPOSIO_DISABLED_TOOLS"


def composio_disabled_tools(conn: sqlite3.Connection | None) -> set[str]:
    """Return the set of action slugs the user has switched OFF.

    Stored as a JSON list under the ``COMPOSIO_DISABLED_TOOLS`` setting key.
    Slugs are upper-cased on read so callers can compare without normalising.
    Default = empty set (every action is enabled).
    """
    if conn is None:
        return set()
    try:
        raw = get_setting(conn, COMPOSIO_DISABLED_TOOLS_KEY, "")
    except sqlite3.Error:
        return set()
    if not raw:
        return set()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(s).upper() for s in parsed if str(s).strip()}


def set_composio_disabled_tools(
    conn: sqlite3.Connection,
    slugs: set[str] | list[str],
) -> None:
    """Persist the disabled-tools set as a JSON list. Empty = clear."""
    cleaned = sorted({str(s).upper() for s in (slugs or []) if str(s).strip()})
    set_setting(conn, COMPOSIO_DISABLED_TOOLS_KEY, json.dumps(cleaned))


def set_settings(conn: sqlite3.Connection, values: dict) -> None:
    """Persist a dict of {key: value} into the settings table + config.json.

    Keys are accepted case-insensitively ('app_name' or 'APP_NAME' both work)
    so HTTP forms (lowercase) and CLI args can use the same accessor as
    internal callers. Non-secret keys (currently APP_NAME) are mirrored to
    ``.hrkit/config.json`` so renderers without a live DB handle still see
    the right value. Empty / None values are skipped.
    """
    if not values:
        return
    persisted: dict[str, str] = {}
    for raw_key, value in values.items():
        key = str(raw_key).upper()
        if key not in ENV_VAR_FOR_KEY:
            continue
        if value is None:
            continue
        text = str(value)
        if text == "":
            continue
        set_setting(conn, key, text)
        persisted[key] = text

    if not persisted:
        return
    # Mirror non-secret keys to config.json so stateless readers can see them.
    try:
        from . import config as _cfg
        root = _cfg.find_workspace()
        if root is None:
            return
        data = _cfg.load_settings(root)
        if "APP_NAME" in persisted:
            data["app_name"] = persisted["APP_NAME"]
        _cfg.save_settings(root, data)
    except Exception:  # config write failures are non-fatal — DB is canonical
        pass


def masked(key: str) -> str:
    """Return a masked representation: first 3 + '***' + last 4 chars.

    Returns '' for empty / falsy input. For very short strings (<= 7 chars
    so the visible halves would overlap) returns just '***' to avoid leaking.
    """
    if not key:
        return ""
    s = str(key)
    if len(s) <= 7:
        return "***"
    return f"{s[:3]}***{s[-4:]}"
