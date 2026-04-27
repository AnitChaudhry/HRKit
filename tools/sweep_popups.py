"""One-shot migration: replace native JS alert/confirm/prompt with hrkit.* helpers.

Run from the repo root: ``python tools/sweep_popups.py``.

Substitution rules:
- ``alert(<args>)``   -> ``hrkit.toast(<args>, '<type>')`` where ``<type>`` is
  derived from the message text (failed/error/denied -> error, saved/created/
  uploaded/imported/fetched/done -> success, else info).
- ``confirm(<args>)`` -> ``(await hrkit.confirmDialog(<args>))``. Callers
  embed in ``if (!(...))`` so the parens preserve precedence.
- ``prompt(<args>)``  -> ``(await hrkit.promptDialog(<args>))``.

Balanced-paren matching is done by hand because ``re`` doesn't support
recursion. The walker only enters JS-shaped bodies inside Python files —
i.e. anywhere a literal ``alert(`` / ``confirm(`` / ``prompt(`` appears,
since this codebase only uses those identifiers as JS calls.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files we want to touch (Python sources that embed JS).
TARGETS = sorted({
    *ROOT.glob("hrkit/*.py"),
    *ROOT.glob("hrkit/modules/*.py"),
    *ROOT.glob("hrkit/integrations/*.py"),
})

# Tokens we deliberately leave alone — these lines are documentation /
# memos / our migration script itself, not JS.
SKIP_LINE_MARKERS = (
    "# Replace ", "# Sweep ", "# - ``alert", "# - ``confirm", "# - ``prompt",
    "# native alert", "# any native ",
)


def _find_balanced(src: str, start_idx: int) -> int:
    """Given ``src[start_idx]`` is '(', return the index of the matching ')'.
    Skips parens inside JS string literals + line comments. Returns -1 if not
    found (input was malformed)."""
    depth = 0
    i = start_idx
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        elif ch in ("'", '"', "`"):
            # Walk to the matching quote, honoring backslash escapes.
            quote = ch
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == quote:
                    break
                i += 1
        elif ch == "/" and i + 1 < n and src[i + 1] == "/":
            # Line comment — skip to end of line.
            while i < n and src[i] != "\n":
                i += 1
        i += 1
    return -1


_TYPE_RE_ERROR = re.compile(r"\b(failed|error|denied|could ?not|invalid)\b", re.I)
_TYPE_RE_OK = re.compile(
    r"\b(saved|created|uploaded|imported|fetched|done|sent|approved|published)\b", re.I)


def _toast_type(args: str) -> str:
    """Pick a toast type from the alert's argument source."""
    if _TYPE_RE_ERROR.search(args):
        return "error"
    if _TYPE_RE_OK.search(args):
        return "success"
    return "info"


# Patterns we want to find. Each is matched literal-wise; the argument
# extraction is balanced-paren aware via ``_find_balanced``.
_NEEDLES = ("alert(", "confirm(", "prompt(")


def _migrate(src: str, *, path: Path) -> tuple[str, dict[str, int]]:
    """Return (new_src, counts) for one file."""
    counts = {k: 0 for k in ("alert", "confirm", "prompt")}
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        # Find the nearest needle from here.
        next_idx = -1
        next_kind = ""
        for kind in _NEEDLES:
            j = src.find(kind, i)
            if j == -1:
                continue
            if next_idx == -1 or j < next_idx:
                next_idx = j
                next_kind = kind
        if next_idx == -1:
            out.append(src[i:])
            break

        # Skip if the line is a doc/comment (marked above).
        line_start = src.rfind("\n", 0, next_idx) + 1
        line_end = src.find("\n", next_idx)
        line = src[line_start:line_end if line_end != -1 else n]
        is_doc_line = any(line.lstrip().startswith(m) for m in SKIP_LINE_MARKERS)

        # Skip if preceded by an identifier char (e.g. ``hrkit.confirmDialog`` or
        # ``Math.alert`` style false positives).
        if next_idx > 0 and (src[next_idx - 1].isalnum() or src[next_idx - 1] in "._"):
            out.append(src[i:next_idx + 1])
            i = next_idx + 1
            continue

        # Find the matching close paren.
        open_paren = next_idx + len(next_kind) - 1
        close_paren = _find_balanced(src, open_paren)
        if close_paren == -1:
            out.append(src[i:next_idx + 1])
            i = next_idx + 1
            continue
        args = src[open_paren + 1:close_paren]
        out.append(src[i:next_idx])
        if is_doc_line:
            # Leave as-is (it's prose).
            out.append(src[next_idx:close_paren + 1])
        else:
            kind = next_kind.rstrip("(")
            if kind == "alert":
                ttype = _toast_type(args)
                out.append(f"hrkit.toast({args}, '{ttype}')")
                counts["alert"] += 1
            elif kind == "confirm":
                out.append(f"(await hrkit.confirmDialog({args}))")
                counts["confirm"] += 1
            elif kind == "prompt":
                out.append(f"(await hrkit.promptDialog({args}))")
                counts["prompt"] += 1
        i = close_paren + 1
    return "".join(out), counts


def main() -> int:
    totals = {"alert": 0, "confirm": 0, "prompt": 0, "files": 0}
    for path in TARGETS:
        if path.name == "ai_tools.py":
            continue  # has unrelated `alert` text in docs
        src = path.read_text(encoding="utf-8")
        new_src, counts = _migrate(src, path=path)
        if any(counts.values()):
            path.write_text(new_src, encoding="utf-8")
            totals["files"] += 1
            print(f"  {path.relative_to(ROOT)}: "
                  f"alert={counts['alert']}, confirm={counts['confirm']}, "
                  f"prompt={counts['prompt']}")
        for k in ("alert", "confirm", "prompt"):
            totals[k] += counts[k]
    print()
    print(f"Touched {totals['files']} files, "
          f"replaced {totals['alert']} alert(), "
          f"{totals['confirm']} confirm(), {totals['prompt']} prompt() calls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
