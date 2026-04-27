"""Module enable/disable feature flags.

Source of truth: ``.getset/config.json`` under the ``enabled_modules`` key.
Mirror: the SQLite ``settings`` table under ``ENABLED_MODULES`` (JSON list).
Both are kept in sync by :func:`set_enabled_modules`. Reads prefer the env
var ``ENABLED_MODULES`` when set (comma- or json-list), then config.json,
then the DB mirror, then the all-on default.

Always-on core (cannot be disabled): ``department``, ``employee``, ``role``.
Every other module references ``employee_id`` (FK), and ``employee``
references ``department_id`` and ``role_id``, so locking these three on
keeps the FK story clean for the eight dependent modules.

This module is stdlib-only and does not import server.py.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Iterable

from . import config as cfg

log = logging.getLogger(__name__)

ALL_MODULES: tuple[str, ...] = (
    "department", "employee", "role", "document",
    "leave", "attendance",
    "payroll", "performance",
    "onboarding", "exit_record",
    "recruitment",
)

ALWAYS_ON: frozenset[str] = frozenset({"department", "employee", "role"})

MODULE_REQUIRES: dict[str, frozenset[str]] = {
    "department":  frozenset(),
    "employee":    frozenset({"department", "role"}),
    "role":        frozenset({"department"}),
    "document":    frozenset({"employee"}),
    "leave":       frozenset({"employee"}),
    "attendance":  frozenset({"employee"}),
    "payroll":     frozenset({"employee"}),
    "performance": frozenset({"employee"}),
    "onboarding":  frozenset({"employee"}),
    "exit_record": frozenset({"employee"}),
    "recruitment": frozenset(),
}

DB_KEY = "ENABLED_MODULES"
ENV_KEY = "ENABLED_MODULES"
CONFIG_KEY = "enabled_modules"


def _parse_list(raw: object) -> list[str] | None:
    """Coerce a stored value into a list of module slugs, or ``None`` if invalid."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if s.startswith("["):
            try:
                items = json.loads(s)
            except (TypeError, ValueError):
                return None
        else:
            items = [p.strip() for p in s.split(",")]
    else:
        return None
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        slug = item.strip().lower()
        if slug in ALL_MODULES and slug not in out:
            out.append(slug)
    return out or None


def _normalize(slugs: Iterable[str]) -> list[str]:
    """Return a deterministic, deduped, always-on-included module list."""
    seen: set[str] = set(ALWAYS_ON)
    for s in slugs:
        if isinstance(s, str):
            slug = s.strip().lower()
            if slug in ALL_MODULES:
                seen.add(slug)
    return [m for m in ALL_MODULES if m in seen]


def enabled_modules(conn: sqlite3.Connection | None = None) -> list[str]:
    """Return the set of enabled module slugs in canonical order.

    Resolution order:
        1. ``ENABLED_MODULES`` environment variable (comma or json list)
        2. ``.getset/config.json`` ``enabled_modules`` key
        3. ``settings`` table ``ENABLED_MODULES`` row
        4. Default: every module enabled
    """
    env_val = os.environ.get(ENV_KEY)
    if env_val:
        parsed = _parse_list(env_val)
        if parsed:
            return _normalize(parsed)

    root = cfg.find_workspace()
    if root is not None:
        try:
            settings = cfg.load_settings(root)
        except Exception:  # pragma: no cover - corrupt config falls through
            settings = {}
        parsed = _parse_list(settings.get(CONFIG_KEY))
        if parsed:
            return _normalize(parsed)

    if conn is not None:
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (DB_KEY,)
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None:
            parsed = _parse_list(row["value"] if hasattr(row, "keys") else row[0])
            if parsed:
                return _normalize(parsed)

    return list(ALL_MODULES)


def is_enabled(slug: str, conn: sqlite3.Connection | None = None) -> bool:
    return slug in enabled_modules(conn)


def validate_selection(slugs: Iterable[str]) -> tuple[list[str], list[str]]:
    """Apply rules to a user-supplied selection.

    Returns ``(normalized, errors)``. Always-on modules are silently added.
    A module whose ``requires`` set is not satisfied produces an error.
    """
    normalized = _normalize(slugs)
    errors: list[str] = []
    chosen = set(normalized)
    for slug in normalized:
        missing = MODULE_REQUIRES.get(slug, frozenset()) - chosen
        if missing:
            errors.append(
                f"{slug} requires: {', '.join(sorted(missing))}"
            )
    return normalized, errors


def set_enabled_modules(
    conn: sqlite3.Connection | None,
    slugs: Iterable[str],
) -> list[str]:
    """Persist the enabled-modules list to config.json AND the settings table.

    Always-on modules are forced in. Returns the normalized list that was
    written. Raises ``ValueError`` on dependency violation. The DB mirror is
    best-effort: a sqlite error is logged but does not abort the config.json
    write (the file remains the canonical source).
    """
    normalized, errors = validate_selection(slugs)
    if errors:
        raise ValueError("; ".join(errors))

    root = cfg.find_workspace()
    if root is not None:
        try:
            settings = cfg.load_settings(root)
        except Exception:
            settings = {}
        settings[CONFIG_KEY] = normalized
        cfg.save_settings(root, settings)

    if conn is not None:
        try:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (DB_KEY, json.dumps(normalized)),
            )
        except sqlite3.Error as exc:
            log.warning("failed to mirror enabled_modules to DB: %s", exc)

    return normalized
