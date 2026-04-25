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
    """Return the human-readable application name."""
    val = os.environ.get("APP_NAME")
    if val:
        return val
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
    """Persist a dict of {key: value} into the settings table.

    Keys are accepted case-insensitively ('app_name' or 'APP_NAME' both work)
    so HTTP forms (lowercase) and CLI args can use the same accessor as
    internal callers.
    Empty / None values are skipped (use a separate delete to clear).
    """
    if not values:
        return
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
