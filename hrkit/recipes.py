"""User-defined action recipes.

A recipe is a named, reusable HR automation: a prompt + a whitelist of
tools the AI is allowed to use to carry it out. Recipes live as plain
markdown files under ``<workspace>/recipes/<slug>.md`` so a person can
read, edit, version, or share them with their own tools — same pattern as
the rest of the workspace.

File format::

    ---
    type: recipe
    slug: send-offer-letter
    name: Send offer letter
    description: Email a candidate their offer letter via Gmail.
    trigger: ""                # optional: domain event to auto-fire on
    tools: [GMAIL_SEND_EMAIL]  # whitelist passed to AI as the only tools
    inputs: [candidate_name, candidate_email, position, salary]
    ---

    Send a warm, professional offer letter to {candidate_name} at
    {candidate_email} for the {position} role at a salary of {salary}.
    Use the GMAIL_SEND_EMAIL tool to deliver it. Confirm before sending.

The body of the file is the **prompt template**. Placeholders in
``{name}`` form are replaced with values from the ``inputs`` payload at
run time.

Stdlib only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterable

from hrkit import frontmatter as fm

log = logging.getLogger(__name__)

RECIPES_DIR = "recipes"

_BAD_CHARS = set('<>:"|?*\\/\x00')
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _safe_slug(value: str) -> str:
    s = (value or "").strip().lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    if not s:
        raise ValueError("recipe slug is required")
    return s[:80]


def recipes_root(workspace_root: str | Path) -> Path:
    return Path(workspace_root) / RECIPES_DIR


def recipe_path(workspace_root: str | Path, slug: str) -> Path:
    return recipes_root(workspace_root) / f"{_safe_slug(slug)}.md"


# ---------------------------------------------------------------------------
# Save / load / list / delete
# ---------------------------------------------------------------------------
def _coerce_list(value: Any) -> list[str]:
    if value in (None, "", [], "[]"):
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [s.strip() for s in re.split(r"[,\s]+", value) if s.strip()]
    return []


def save_recipe(
    *,
    workspace_root: str | Path,
    slug: str,
    name: str,
    description: str = "",
    tools: Iterable[str] | None = None,
    inputs: Iterable[str] | None = None,
    trigger: str = "",
    body: str = "",
) -> dict[str, str]:
    """Write a recipe markdown file. Idempotent on slug."""
    safe = _safe_slug(slug)
    path = recipe_path(workspace_root, safe)
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_dict = {
        "type": "recipe",
        "slug": safe,
        "name": (name or safe).strip(),
        "description": (description or "").strip(),
        "trigger": (trigger or "").strip(),
        "tools": [str(t).strip().upper() for t in (tools or []) if str(t).strip()],
        "inputs": [str(i).strip() for i in (inputs or []) if str(i).strip()],
    }
    path.write_text(fm.dump(fm_dict, body or ""), encoding="utf-8")
    return {"slug": safe, "path": str(path.resolve())}


def load_recipe(workspace_root: str | Path, slug: str) -> dict[str, Any] | None:
    path = recipe_path(workspace_root, slug)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm_dict, body = fm.parse(text)
    return {
        "slug": str(fm_dict.get("slug") or _safe_slug(slug)),
        "name": str(fm_dict.get("name") or slug),
        "description": str(fm_dict.get("description") or ""),
        "trigger": str(fm_dict.get("trigger") or ""),
        "tools": _coerce_list(fm_dict.get("tools")),
        "inputs": _coerce_list(fm_dict.get("inputs")),
        "body": body,
        "path": str(path.resolve()),
    }


def list_recipes(workspace_root: str | Path) -> list[dict[str, Any]]:
    folder = recipes_root(workspace_root)
    if not folder.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            fm_dict, _ = fm.parse(text)
        except OSError:
            continue
        if fm_dict.get("type") != "recipe":
            # be lenient — assume any .md in /recipes/ is a recipe by intent
            pass
        out.append({
            "slug": str(fm_dict.get("slug") or path.stem),
            "name": str(fm_dict.get("name") or path.stem),
            "description": str(fm_dict.get("description") or ""),
            "trigger": str(fm_dict.get("trigger") or ""),
            "tools": _coerce_list(fm_dict.get("tools")),
            "inputs": _coerce_list(fm_dict.get("inputs")),
        })
    return out


def delete_recipe(workspace_root: str | Path, slug: str) -> bool:
    path = recipe_path(workspace_root, slug)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError as exc:
        log.warning("delete_recipe: failed to unlink %s: %s", path, exc)
        return False


# ---------------------------------------------------------------------------
# Render — fill {placeholder} substitutions from a payload
# ---------------------------------------------------------------------------
def render_recipe(recipe: dict[str, Any], payload: dict[str, Any] | None) -> str:
    """Fill ``{name}`` placeholders in the recipe body with payload values.

    Unknown placeholders are left literal so the AI sees what's missing.
    """
    body = recipe.get("body") or recipe.get("description") or recipe.get("name") or ""
    payload = payload or {}

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key in payload and payload[key] not in (None, ""):
            return str(payload[key])
        return m.group(0)

    return _PLACEHOLDER_RE.sub(repl, body)


__all__ = [
    "RECIPES_DIR",
    "recipes_root",
    "recipe_path",
    "save_recipe",
    "load_recipe",
    "list_recipes",
    "delete_recipe",
    "render_recipe",
]
