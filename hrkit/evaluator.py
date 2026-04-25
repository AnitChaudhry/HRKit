"""Candidate evaluator — replaces the old Claude-CLI ``task-evaluator`` subagent
with an in-process call to ``hrkit.ai.run_agent``.

Public API:
    evaluate_candidate(*, conn, candidate_folder, rubric_path) -> dict
    has_evaluation(candidate_folder) -> bool
    read_evaluation(candidate_folder) -> dict | None

The evaluation result is also persisted as ``evaluation.md`` inside
``candidate_folder`` with YAML frontmatter (parsed by
``hrkit.frontmatter``) plus a markdown body containing the summary.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from hrkit import ai, frontmatter
from hrkit.branding import app_name
from hrkit.config import IST

log = logging.getLogger(__name__)

EVALUATION_FILENAME = "evaluation.md"
_VALID_RECOMMENDATIONS = {"Shortlist", "Borderline", "Reject"}
_PDF_PROBE_BYTES = 1024  # first KB of the PDF, b64-encoded into the prompt
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def evaluate_candidate(
    *,
    conn,
    candidate_folder: Path,
    rubric_path: Path,
) -> dict:
    """Score a candidate by invoking the AI agent and persist ``evaluation.md``.

    Returns a dict with keys: ``overall_score``, ``recommendation``,
    ``next_action``, ``summary``.
    """
    candidate_folder = Path(candidate_folder)
    rubric_path = Path(rubric_path)

    if not candidate_folder.is_dir():
        raise FileNotFoundError(f"Candidate folder not found: {candidate_folder}")
    if not rubric_path.is_file():
        raise FileNotFoundError(f"Rubric file not found: {rubric_path}")

    rubric_text = rubric_path.read_text(encoding="utf-8", errors="replace")
    candidate_ctx = _collect_candidate_context(candidate_folder)

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(rubric_text, candidate_ctx)

    log.info("evaluator: running AI agent for %s", candidate_folder.name)
    raw = await ai.run_agent(user_prompt, conn=conn, system=system_prompt)

    parsed = _parse_and_validate(raw)

    timestamp = datetime.now(IST).isoformat(timespec="seconds")
    fm: dict[str, Any] = {
        "overall_score": parsed["overall_score"],
        "recommendation": parsed["recommendation"],
        "next_action": parsed["next_action"],
        "summary": parsed["summary"],
        "evaluated": timestamp,
    }
    body = _render_body(parsed, candidate_ctx)
    out_text = frontmatter.dump(fm, body)
    (candidate_folder / EVALUATION_FILENAME).write_text(out_text, encoding="utf-8")

    return {
        "overall_score": parsed["overall_score"],
        "recommendation": parsed["recommendation"],
        "next_action": parsed["next_action"],
        "summary": parsed["summary"],
    }


def has_evaluation(candidate_folder: Path) -> bool:
    """True iff ``evaluation.md`` exists inside ``candidate_folder``."""
    return (Path(candidate_folder) / EVALUATION_FILENAME).is_file()


def read_evaluation(candidate_folder: Path) -> dict | None:
    """Read the persisted evaluation. Returns ``None`` if missing."""
    path = Path(candidate_folder) / EVALUATION_FILENAME
    if not path.is_file():
        return None
    fm, body = frontmatter.parse(path.read_text(encoding="utf-8", errors="replace"))
    return {
        "overall_score": fm.get("overall_score"),
        "recommendation": fm.get("recommendation"),
        "next_action": fm.get("next_action"),
        "summary": fm.get("summary") or body.strip(),
        "evaluated": fm.get("evaluated"),
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _collect_candidate_context(folder: Path) -> dict[str, Any]:
    """Pull together everything we can hand to the AI from the candidate folder."""
    ctx: dict[str, Any] = {
        "folder_name": folder.name,
        "name": "",
        "email": "",
        "phone": "",
        "getset_body": "",
        "getset_frontmatter": {},
        "resume_files": [],
    }

    getset = folder / "getset.md"
    if getset.is_file():
        fm, body = frontmatter.parse(getset.read_text(encoding="utf-8", errors="replace"))
        ctx["getset_frontmatter"] = fm
        ctx["getset_body"] = body
        ctx["name"] = str(fm.get("name") or fm.get("candidate") or "").strip()
        ctx["email"] = str(fm.get("email") or "").strip()
        ctx["phone"] = str(fm.get("phone") or "").strip()

    # TODO: extract real text from PDF resumes. Stdlib has no PDF parser, so
    # for now we only surface filename + a base64 probe of the first KB.
    for pdf in sorted(folder.glob("*.pdf")):
        try:
            with pdf.open("rb") as fh:
                head = fh.read(_PDF_PROBE_BYTES)
        except OSError as exc:
            log.warning("evaluator: could not read %s: %s", pdf, exc)
            continue
        ctx["resume_files"].append({
            "filename": pdf.name,
            "size_bytes": pdf.stat().st_size,
            "head_b64": base64.b64encode(head).decode("ascii"),
        })

    return ctx


def _build_system_prompt() -> str:
    return (
        f"You are the candidate-evaluation agent inside {app_name()}. "
        "You read a hiring rubric and a candidate brief, then return a strict "
        "JSON object with exactly these keys: "
        '"overall_score" (number, 0-10, may be a float to one decimal), '
        '"recommendation" (one of "Shortlist", "Borderline", "Reject"), '
        '"next_action" (short imperative sentence telling the recruiter what to do next), '
        '"summary" (2-4 sentence justification grounded in the rubric). '
        "Do not include any prose outside the JSON object. "
        "Do not wrap the JSON in markdown fences. "
        "If a resume PDF is attached you cannot read its bytes — call out the "
        "missing detail in the summary and set the score conservatively."
    )


def _build_user_prompt(rubric_text: str, ctx: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.append("# Hiring rubric\n")
    parts.append(rubric_text.strip() or "(empty rubric)")
    parts.append("\n\n# Candidate\n")
    parts.append(f"- Folder: {ctx['folder_name']}")
    if ctx["name"]:
        parts.append(f"- Name: {ctx['name']}")
    if ctx["email"]:
        parts.append(f"- Email: {ctx['email']}")
    if ctx["phone"]:
        parts.append(f"- Phone: {ctx['phone']}")

    if ctx["getset_frontmatter"]:
        parts.append("\n## getset.md frontmatter\n")
        for k, v in ctx["getset_frontmatter"].items():
            parts.append(f"- {k}: {v}")

    if ctx["getset_body"]:
        parts.append("\n## getset.md body\n")
        parts.append(ctx["getset_body"].strip())

    if ctx["resume_files"]:
        parts.append("\n## Attached resume PDF(s)\n")
        parts.append(
            "Resume PDF attached — the runtime cannot extract text in this pass. "
            "If a key skill cannot be confirmed from the brief above, mention "
            "in the summary that the recruiter should request a parsed CV upload."
        )
        for r in ctx["resume_files"]:
            parts.append(
                f"- {r['filename']} ({r['size_bytes']} bytes); "
                f"first-KB base64 probe: {r['head_b64'][:120]}..."
            )

    parts.append(
        "\n\n# Output\nReturn ONLY the JSON object described in the system prompt."
    )
    return "\n".join(parts)


def _parse_and_validate(raw: str) -> dict[str, Any]:
    """Extract a JSON object from ``raw`` and validate the four required fields."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("evaluator: AI returned empty response")

    text = raw.strip()
    # Strip a leading code fence if present.
    if text.startswith("```"):
        text = text.strip("`")
        # Drop a possible language hint on the first line.
        if "\n" in text:
            first, _, rest = text.partition("\n")
            if first.strip().lower() in {"json", "javascript", "js"}:
                text = rest

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if not match:
            raise ValueError(f"evaluator: no JSON object found in response: {raw!r}")
        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise ValueError(f"evaluator: expected JSON object, got {type(data).__name__}")

    missing = [k for k in ("overall_score", "recommendation", "next_action", "summary") if k not in data]
    if missing:
        raise ValueError(f"evaluator: response missing fields: {missing}")

    try:
        score = float(data["overall_score"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"evaluator: overall_score not numeric: {data['overall_score']!r}") from exc
    score = max(0.0, min(10.0, score))

    rec = str(data["recommendation"]).strip()
    if rec not in _VALID_RECOMMENDATIONS:
        # Be forgiving on case but still validate.
        match = next((r for r in _VALID_RECOMMENDATIONS if r.lower() == rec.lower()), None)
        if not match:
            raise ValueError(
                f"evaluator: recommendation must be one of "
                f"{sorted(_VALID_RECOMMENDATIONS)}, got {rec!r}"
            )
        rec = match

    next_action = str(data["next_action"]).strip()
    summary = str(data["summary"]).strip()
    if not next_action:
        raise ValueError("evaluator: next_action is empty")
    if not summary:
        raise ValueError("evaluator: summary is empty")

    return {
        "overall_score": score,
        "recommendation": rec,
        "next_action": next_action,
        "summary": summary,
    }


def _render_body(parsed: dict[str, Any], ctx: dict[str, Any]) -> str:
    name = ctx["name"] or ctx["folder_name"]
    lines = [
        f"# Evaluation — {name}",
        "",
        f"**Score:** {parsed['overall_score']}/10  ",
        f"**Recommendation:** {parsed['recommendation']}  ",
        f"**Next action:** {parsed['next_action']}",
        "",
        "## Summary",
        "",
        parsed["summary"],
    ]
    return "\n".join(lines)
