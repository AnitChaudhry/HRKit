"""SQL migration runner for hrkit.

Discovers ``.sql`` files inside the ``hrkit.migrations`` package and
applies them against an open ``sqlite3.Connection`` in lexicographic order.
Applied versions are recorded in ``schema_migrations(version, applied_at)``
so subsequent invocations are no-ops.

Design notes
------------
* Stdlib only.
* SQL files are read via ``importlib.resources`` (with a ``pkgutil`` fallback)
  so they ship with the installed package without relying on filesystem
  layout.
* Each migration runs inside a transaction; on failure the transaction is
  rolled back and the version is NOT recorded.
* Safe to call multiple times: already-applied versions are skipped silently.
"""

from __future__ import annotations

import logging
import pkgutil
import sqlite3
from importlib import resources
from typing import Iterable

log = logging.getLogger(__name__)

_MIGRATIONS_PACKAGE = "hrkit.migrations"
_BOOKKEEPING_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "  version    TEXT PRIMARY KEY,"
    "  applied_at TEXT NOT NULL DEFAULT "
    "    (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))"
    ")"
)


def _list_sql_files() -> list[str]:
    """Return sorted list of ``.sql`` filenames inside the migrations package."""
    names: list[str] = []
    try:
        # Python 3.9+: importlib.resources.files
        pkg = resources.files(_MIGRATIONS_PACKAGE)
        for entry in pkg.iterdir():
            name = entry.name
            if name.endswith(".sql") and entry.is_file():
                names.append(name)
    except (ModuleNotFoundError, AttributeError, FileNotFoundError):
        # Fallback: try pkgutil iteration via a known-loaded package
        import importlib

        try:
            mod = importlib.import_module(_MIGRATIONS_PACKAGE)
        except ModuleNotFoundError:
            return []
        if hasattr(mod, "__path__"):
            from pathlib import Path

            for p in mod.__path__:
                root = Path(p)
                if root.is_dir():
                    for f in root.iterdir():
                        if f.is_file() and f.suffix == ".sql":
                            names.append(f.name)
    # de-duplicate then sort lexicographically
    return sorted(set(names))


def _read_sql(filename: str) -> str:
    """Read a migration SQL file from the package as text (UTF-8)."""
    # Prefer importlib.resources for clean package-data access.
    try:
        return (
            resources.files(_MIGRATIONS_PACKAGE)
            .joinpath(filename)
            .read_text(encoding="utf-8")
        )
    except (ModuleNotFoundError, AttributeError, FileNotFoundError):
        data = pkgutil.get_data(_MIGRATIONS_PACKAGE, filename)
        if data is None:
            raise FileNotFoundError(
                f"Migration {filename!r} not found in {_MIGRATIONS_PACKAGE}"
            )
        return data.decode("utf-8")


def _ensure_bookkeeping(conn: sqlite3.Connection) -> None:
    conn.execute(_BOOKKEEPING_DDL)


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def _record_applied(conn: sqlite3.Connection, version: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (version,),
    )


def apply_all(conn: sqlite3.Connection) -> list[str]:
    """Apply every pending migration in lexicographic order.

    Parameters
    ----------
    conn:
        Open ``sqlite3.Connection``. Caller owns lifecycle. Foreign-key
        enforcement and other PRAGMAs should already be configured.

    Returns
    -------
    list[str]
        Migration filenames applied during *this* call. Empty list when
        nothing was pending.
    """
    _ensure_bookkeeping(conn)
    applied_now: list[str] = []

    files: Iterable[str] = _list_sql_files()
    already = _applied_versions(conn)

    for fname in files:
        if fname in already:
            continue
        sql = _read_sql(fname)
        log.info("applying migration %s", fname)
        # Use a manual transaction so a single failed migration is atomic.
        in_tx = conn.in_transaction
        try:
            if not in_tx:
                conn.execute("BEGIN")
            conn.executescript(sql)
            _record_applied(conn, fname)
            if not in_tx:
                conn.commit()
        except sqlite3.Error:
            if not in_tx:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
            log.exception("migration %s failed", fname)
            raise
        applied_now.append(fname)

    return applied_now


__all__ = ["apply_all"]
