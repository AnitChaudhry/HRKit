"""Smoke test for hrkit.evaluator.

We monkey-patch ``ai.run_agent`` so the test never touches a real LLM.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

try:
    from hrkit import ai, evaluator, frontmatter
except ImportError as exc:  # pragma: no cover - environment-dependent
    pytest.skip(f"hrkit.evaluator unavailable ({exc})", allow_module_level=True)


_FAKE_RESPONSE = (
    'Sure, here is the evaluation:\n'
    '```json\n'
    '{\n'
    '  "overall_score": 8.5,\n'
    '  "recommendation": "Shortlist",\n'
    '  "next_action": "Schedule a 30-minute technical screen.",\n'
    '  "summary": "Strong Python and SQL background, 6 years '
    'building HR/payroll software, IST timezone, references check out."\n'
    '}\n'
    '```\n'
)


def _make_candidate(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    getset = folder / "getset.md"
    getset.write_text(
        frontmatter.dump(
            {"name": "Asha Nair", "email": "asha@example.com", "phone": "+91-9000000000"},
            "Senior backend engineer, 6 yrs Python, ex-HR-tech.",
        ),
        encoding="utf-8",
    )


def test_evaluate_candidate_writes_evaluation(tmp_path, monkeypatch):
    candidate = tmp_path / "001-asha-nair"
    _make_candidate(candidate)
    rubric = tmp_path / "Rule.md"
    rubric.write_text(
        "# Rubric\n- Python proficiency (0-4)\n- HR domain (0-3)\n- Communication (0-3)\n",
        encoding="utf-8",
    )

    async def fake_run_agent(prompt, *, conn, system="", tools=None, model=None):
        # Sanity: prompt should contain rubric + candidate context.
        assert "Rubric" in prompt
        assert "Asha Nair" in prompt
        assert system  # system prompt must be supplied
        return _FAKE_RESPONSE

    monkeypatch.setattr(ai, "run_agent", fake_run_agent)

    result = asyncio.run(
        evaluator.evaluate_candidate(
            conn=None,  # fake_run_agent ignores it
            candidate_folder=candidate,
            rubric_path=rubric,
        )
    )

    assert result["overall_score"] == pytest.approx(8.5)
    assert result["recommendation"] == "Shortlist"
    assert "technical screen" in result["next_action"].lower()
    assert "Python" in result["summary"]

    assert evaluator.has_evaluation(candidate)

    persisted = evaluator.read_evaluation(candidate)
    assert persisted is not None
    assert persisted["overall_score"] == pytest.approx(8.5)
    assert persisted["recommendation"] == "Shortlist"
    assert persisted["evaluated"]  # IST timestamp written
    # Frontmatter timestamp should look ISO-8601 with +05:30 offset.
    assert "+05:30" in persisted["evaluated"]


def test_read_evaluation_missing(tmp_path):
    candidate = tmp_path / "empty"
    candidate.mkdir()
    assert evaluator.has_evaluation(candidate) is False
    assert evaluator.read_evaluation(candidate) is None


def test_parse_rejects_bad_recommendation(tmp_path, monkeypatch):
    candidate = tmp_path / "002-bad"
    _make_candidate(candidate)
    rubric = tmp_path / "Rule.md"
    rubric.write_text("rubric", encoding="utf-8")

    async def bad_agent(prompt, *, conn, system="", tools=None, model=None):
        return '{"overall_score": 5, "recommendation": "Maybe", ' \
               '"next_action": "x", "summary": "y"}'

    monkeypatch.setattr(ai, "run_agent", bad_agent)

    with pytest.raises(ValueError, match="recommendation"):
        asyncio.run(
            evaluator.evaluate_candidate(
                conn=None,
                candidate_folder=candidate,
                rubric_path=rubric,
            )
        )
