from __future__ import annotations
import json, os
from datetime import timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

MARKER = "getset.md"
META_DIR = ".getset"
DB_NAME = "getset.db"
CONFIG_NAME = "config.json"

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
    env = os.environ.get("GETSET_ROOT")
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
    m = p / MARKER
    if not m.exists():
        return False
    try:
        txt = m.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "type: workspace" in txt or 'type: "workspace"' in txt


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
