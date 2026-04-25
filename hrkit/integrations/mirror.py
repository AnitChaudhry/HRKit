"""Local-folder mirror for Composio integration data.

Every record an integration fetches (Gmail thread, Calendar event, Drive
file, Slack message, ...) is written to TWO files under the workspace
root so the same data is reachable from both the app and a human file
browser:

    <workspace>/integrations/<app>/<resource>/<safe_id>.md     # human-readable
    <workspace>/integrations/<app>/<resource>/<safe_id>.json   # raw API payload

The .md file uses the existing ``hrkit.frontmatter`` format so the same
parser/scanner already used for ``getset.md`` markers can read it. The
.json sidecar preserves the original API response verbatim so reprocessing
is lossless.

Folder structure example::

    .                                       # = workspace root (HR-Kit home)
    ├── getset.md
    ├── .getset/getset.db
    └── integrations/
        ├── gmail/
        │   ├── threads/
        │   │   ├── 18a4f7c2bd33a91d.md
        │   │   └── 18a4f7c2bd33a91d.json
        │   └── messages/...
        ├── googlecalendar/
        │   └── events/...
        └── googledrive/
            └── files/...

Stdlib only.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from hrkit import frontmatter as fm

log = logging.getLogger(__name__)

INTEGRATIONS_DIR = "integrations"
_BAD_SEGMENT_CHARS = set('<>:"|?*\\/\x00')


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def integrations_root(workspace_root: str | Path) -> Path:
    """Return ``<workspace>/integrations`` as a Path."""
    return Path(workspace_root) / INTEGRATIONS_DIR


def _safe_segment(value: str) -> str:
    """Sanitize a single path segment (app, resource, id)."""
    text = (value or "").strip()
    if not text or text in (".", ".."):
        raise ValueError(f"invalid path segment: {value!r}")
    cleaned = "".join("_" if c in _BAD_SEGMENT_CHARS or ord(c) < 32 else c
                      for c in text)
    cleaned = cleaned.strip(" .")
    if not cleaned:
        raise ValueError(f"invalid path segment after sanitization: {value!r}")
    return cleaned[:120]


def record_dir(workspace_root: str | Path, app: str, resource: str) -> Path:
    """Return the directory that would hold records for ``(app, resource)``."""
    return integrations_root(workspace_root) / _safe_segment(app) / _safe_segment(resource)


def record_paths(
    workspace_root: str | Path,
    app: str,
    resource: str,
    record_id: str,
) -> tuple[Path, Path]:
    """Return ``(md_path, json_path)`` for a given record id."""
    base = record_dir(workspace_root, app, resource) / _safe_segment(record_id)
    return Path(str(base) + ".md"), Path(str(base) + ".json")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
def write_record(
    *,
    workspace_root: str | Path,
    app: str,
    resource: str,
    record_id: str,
    frontmatter: dict[str, Any],
    body: str = "",
    raw: Any = None,
) -> dict[str, str]:
    """Write a record's ``.md`` (frontmatter + body) and ``.json`` (raw) files.

    Idempotent on ``(app, resource, record_id)``: re-writing the same id
    overwrites the prior files so callers can refresh records freely.

    Returns ``{"md_path": str, "json_path": str}`` with the absolute paths
    that were written.
    """
    md_path, json_path = record_paths(workspace_root, app, resource, record_id)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    # Frontmatter: ensure id + a few standard fields are always present so a
    # human looking at the file can immediately tell what it is.
    fm_dict: dict[str, Any] = {
        "type": f"{_safe_segment(app)}-{_safe_segment(resource).rstrip('s')}",
        "id": str(record_id),
    }
    fm_dict.update(frontmatter or {})

    md_path.write_text(fm.dump(fm_dict, body or ""), encoding="utf-8")

    if raw is not None:
        json_path.write_text(
            json.dumps(raw, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
    elif json_path.exists():
        # Don't keep a stale sidecar from a previous write that included raw.
        json_path.unlink()

    return {"md_path": str(md_path.resolve()), "json_path": str(json_path.resolve())}


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def read_record(
    *,
    workspace_root: str | Path,
    app: str,
    resource: str,
    record_id: str,
) -> dict[str, Any] | None:
    """Read a previously-written record. Returns ``None`` if missing.

    Returned shape::

        {"frontmatter": dict, "body": str, "raw": dict | None,
         "md_path": str, "json_path": str}
    """
    md_path, json_path = record_paths(workspace_root, app, resource, record_id)
    if not md_path.exists():
        return None
    text = md_path.read_text(encoding="utf-8")
    fm_dict, body = fm.parse(text)
    raw: Any = None
    if json_path.exists():
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
    return {
        "frontmatter": fm_dict,
        "body": body,
        "raw": raw,
        "md_path": str(md_path.resolve()),
        "json_path": str(json_path.resolve()),
    }


def list_records(
    *,
    workspace_root: str | Path,
    app: str,
    resource: str,
) -> Iterable[dict[str, Any]]:
    """Yield every record under ``<workspace>/integrations/<app>/<resource>/``.

    Yields ``{"id": str, "frontmatter": dict, "md_path": str, "json_path": str}``
    one per ``.md`` file, sorted by filename. Bodies and raw payloads are not
    loaded — call :func:`read_record` for the full record.
    """
    folder = record_dir(workspace_root, app, resource)
    if not folder.exists():
        return
    for md_path in sorted(folder.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
            fm_dict, _ = fm.parse(text)
        except OSError:
            continue
        record_id = md_path.stem
        json_path = md_path.with_suffix(".json")
        yield {
            "id": record_id,
            "frontmatter": fm_dict,
            "md_path": str(md_path.resolve()),
            "json_path": str(json_path.resolve()),
        }


def delete_record(
    *,
    workspace_root: str | Path,
    app: str,
    resource: str,
    record_id: str,
) -> bool:
    """Remove the .md + .json files for a record. Returns True if anything was deleted."""
    md_path, json_path = record_paths(workspace_root, app, resource, record_id)
    deleted = False
    for p in (md_path, json_path):
        if p.exists():
            try:
                p.unlink()
                deleted = True
            except OSError as exc:
                log.warning("mirror.delete_record: could not unlink %s: %s", p, exc)
    return deleted


__all__ = [
    "INTEGRATIONS_DIR",
    "integrations_root",
    "record_dir",
    "record_paths",
    "write_record",
    "read_record",
    "list_records",
    "delete_record",
]
