from __future__ import annotations
import json, os
from datetime import timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

MARKER = "hrkit.md"
META_DIR = ".hrkit"
DB_NAME = "hrkit.db"
CONFIG_NAME = "config.json"

# Legacy names from before the rename. Accepted on read for one release so
# 1.0.0 workspaces don't break; auto-migrated to the new names on first
# ``hrkit serve``. Remove in 2.0.0.
LEGACY_MARKER = "getset.md"
LEGACY_META_DIR = ".getset"
LEGACY_DB_NAME = "getset.db"

SETTINGS_KEYS = ["APP_NAME", "AI_PROVIDER", "AI_API_KEY", "AI_MODEL", "COMPOSIO_API_KEY"]

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
IGNORE_PREFIXES = ("_", ".")
IGNORE_NAMES = frozenset({"plugin", "node_modules", "__pycache__", "hrkit", ".git", ".venv", "venv"})

TYPES = ("workspace", "department", "position", "task")

DEFAULT_COLUMNS = ["applied", "screening", "interview", "offer", "closed"]
DEFAULT_STATUSES = ["applied", "screening", "interview", "offer", "hired", "rejected"]
STATUS_TO_COLUMN = {
    "applied": "applied", "screening": "screening", "interview": "interview",
    "offer": "offer", "hired": "closed", "rejected": "closed",
}
COLUMN_LABEL = {
    "applied": "Applied", "screening": "Screening", "interview": "Interview",
    "offer": "Offer", "closed": "Closed",
}
COLUMN_ACCENT = {
    "applied": "#6366f1", "screening": "#22d3ee", "interview": "#f59e0b",
    "offer": "#8b5cf6", "closed": "#10b981",
}


def find_workspace(start: Path | None = None) -> Path | None:
    """Return the nearest workspace root by walking up from ``start`` (or cwd).

    Resolution order:
      1. ``HRKIT_ROOT`` env var, then legacy ``GETSET_ROOT`` (one-release shim)
      2. ``start`` and each parent until a workspace marker is found
    Returns ``None`` if no workspace exists in scope.
    """
    env = os.environ.get("HRKIT_ROOT") or os.environ.get("GETSET_ROOT")
    if env:
        p = Path(env)
        if _is_workspace(p):
            return p
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if _is_workspace(p):
            return p
    return None


def _is_workspace(p: Path) -> bool:
    """A folder is a workspace if it has either ``hrkit.md`` (new) or
    ``getset.md`` (legacy 1.0.0) with ``type: workspace`` frontmatter."""
    for marker_name in (MARKER, LEGACY_MARKER):
        m = p / marker_name
        if not m.exists():
            continue
        try:
            txt = m.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "type: workspace" in txt or 'type: "workspace"' in txt:
            return True
    return False


def migrate_legacy_layout(root: Path) -> list[str]:
    """Rename legacy ``.getset/`` and ``getset.md`` to the new ``hrkit`` names.

    Idempotent. Returns a list of human-readable changes performed (empty if
    the workspace was already on the new layout). Refuses to clobber an
    existing target — if both old and new exist side by side, leaves the old
    one alone and returns a notice.
    """
    actions: list[str] = []
    legacy_dir = root / LEGACY_META_DIR
    new_dir = root / META_DIR
    if legacy_dir.is_dir() and not new_dir.exists():
        legacy_dir.rename(new_dir)
        actions.append(f"renamed {LEGACY_META_DIR}/ -> {META_DIR}/")
    elif legacy_dir.is_dir() and new_dir.exists():
        actions.append(
            f"both {LEGACY_META_DIR}/ and {META_DIR}/ exist — left as-is"
        )

    legacy_db = new_dir / LEGACY_DB_NAME
    new_db = new_dir / DB_NAME
    if legacy_db.is_file() and not new_db.exists():
        legacy_db.rename(new_db)
        actions.append(f"renamed {LEGACY_DB_NAME} -> {DB_NAME}")

    legacy_marker = root / LEGACY_MARKER
    new_marker = root / MARKER
    if legacy_marker.is_file() and not new_marker.exists():
        try:
            txt = legacy_marker.read_text(encoding="utf-8", errors="replace")
        except OSError:
            txt = ""
        if "type: workspace" in txt or 'type: "workspace"' in txt:
            legacy_marker.rename(new_marker)
            actions.append(f"renamed {LEGACY_MARKER} -> {MARKER}")
    return actions


def init_workspace(root: Path, name: str | None = None) -> None:
    """Create a fresh workspace marker + metadata dir at ``root``.

    Used by ``hrkit serve`` auto-init when the user runs HR-Kit in a folder
    that isn't a workspace yet. Safe to call when the workspace already
    exists (no-op if a marker is present).
    """
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER
    if not marker.exists() and not (root / LEGACY_MARKER).exists():
        display = name or root.name or "HR-Kit Workspace"
        body = (
            "---\n"
            "type: workspace\n"
            f"name: {display}\n"
            "theme: dark\n"
            f"port: {DEFAULT_PORT}\n"
            "---\n"
            f"# {display}\n"
        )
        marker.write_text(body, encoding="utf-8")
    meta_dir(root).mkdir(parents=True, exist_ok=True)


def meta_dir(root: Path) -> Path:
    return root / META_DIR


def db_path(root: Path) -> Path:
    return meta_dir(root) / DB_NAME


def config_file(root: Path) -> Path:
    return meta_dir(root) / CONFIG_NAME


def load_settings(root: Path) -> dict:
    f = config_file(root)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(root: Path, data: dict) -> None:
    f = config_file(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_dotenv_if_present(root: Path) -> int:
    """Read `.env` in workspace root and populate os.environ for missing keys.

    Stdlib-only minimal parser: supports KEY=VALUE per line, '#' comments,
    blank lines, and surrounding single/double quotes on the value. Existing
    environment variables are NEVER overwritten. Returns the number of keys
    that were loaded into the environment.
    """
    f = Path(root) / ".env"
    if not f.exists():
        return 0
    loaded = 0
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        loaded += 1
    return loaded
