"""Tests for hrkit.integrations.mirror — local-folder writeback for integrations."""

from __future__ import annotations

import json

import pytest

from hrkit.integrations import mirror


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def test_record_paths_layout(tmp_path):
    md, j = mirror.record_paths(tmp_path, "gmail", "threads", "abc123")
    assert md.parent == tmp_path / "integrations" / "gmail" / "threads"
    assert md.name == "abc123.md"
    assert j.name == "abc123.json"


def test_record_paths_sanitizes_segments(tmp_path):
    md, _ = mirror.record_paths(tmp_path, "gmail", "threads", "weird/id*name")
    # Slashes and globs in the id are replaced with _ so they don't escape the dir.
    assert "/" not in md.name and "*" not in md.name
    assert md.parent == tmp_path / "integrations" / "gmail" / "threads"


def test_record_paths_rejects_dot_segments(tmp_path):
    with pytest.raises(ValueError):
        mirror.record_paths(tmp_path, "gmail", "..", "x")
    with pytest.raises(ValueError):
        mirror.record_paths(tmp_path, "", "threads", "x")


# ---------------------------------------------------------------------------
# Write + read round trip
# ---------------------------------------------------------------------------
def test_write_creates_md_and_json_sidecar(tmp_path):
    raw = {"id": "msg-1", "from": "asha@example.com", "subject": "Application", "snippet": "Hi..."}
    out = mirror.write_record(
        workspace_root=tmp_path, app="gmail", resource="messages", record_id="msg-1",
        frontmatter={
            "subject": "Application: Senior Engineer",
            "from": "asha@example.com",
            "to": "hr@thinqmesh.com",
            "date": "2026-04-20T14:32:00Z",
        },
        body="Hi team,\n\nPlease find my application for the Senior Engineer role.",
        raw=raw,
    )
    md_path = tmp_path / "integrations" / "gmail" / "messages" / "msg-1.md"
    json_path = tmp_path / "integrations" / "gmail" / "messages" / "msg-1.json"
    assert md_path.exists()
    assert json_path.exists()
    assert out["md_path"] == str(md_path.resolve())
    assert out["json_path"] == str(json_path.resolve())
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "type: \"gmail-message\"" in text
    assert "id: \"msg-1\"" in text
    assert "subject:" in text
    assert "Hi team," in text
    sidecar = json.loads(json_path.read_text(encoding="utf-8"))
    assert sidecar == raw


def test_read_returns_frontmatter_body_and_raw(tmp_path):
    mirror.write_record(
        workspace_root=tmp_path, app="googlecalendar", resource="events", record_id="evt-1",
        frontmatter={"summary": "Anika — Annual Leave", "start": "2026-05-04"},
        body="Family wedding",
        raw={"id": "evt-1", "summary": "Anika — Annual Leave"},
    )
    rec = mirror.read_record(
        workspace_root=tmp_path, app="googlecalendar", resource="events", record_id="evt-1",
    )
    assert rec is not None
    assert rec["frontmatter"]["id"] == "evt-1"
    assert rec["frontmatter"]["summary"] == "Anika — Annual Leave"
    assert rec["frontmatter"]["type"] == "googlecalendar-event"
    assert "Family wedding" in rec["body"]
    assert rec["raw"] == {"id": "evt-1", "summary": "Anika — Annual Leave"}


def test_read_returns_none_when_missing(tmp_path):
    assert mirror.read_record(
        workspace_root=tmp_path, app="gmail", resource="messages", record_id="nope",
    ) is None


# ---------------------------------------------------------------------------
# Idempotence — re-writing the same id overwrites the prior files
# ---------------------------------------------------------------------------
def test_write_is_idempotent(tmp_path):
    for i in range(3):
        mirror.write_record(
            workspace_root=tmp_path, app="gmail", resource="threads", record_id="t-1",
            frontmatter={"iter": i}, body=f"version {i}", raw={"iter": i},
        )
    folder = tmp_path / "integrations" / "gmail" / "threads"
    files = sorted(p.name for p in folder.iterdir())
    # Exactly one .md and one .json — no duplicates.
    assert files == ["t-1.json", "t-1.md"]
    # And the latest content stuck.
    rec = mirror.read_record(
        workspace_root=tmp_path, app="gmail", resource="threads", record_id="t-1",
    )
    assert rec["frontmatter"]["iter"] == 2
    assert "version 2" in rec["body"]


def test_write_without_raw_clears_existing_sidecar(tmp_path):
    mirror.write_record(
        workspace_root=tmp_path, app="gmail", resource="messages", record_id="m-x",
        frontmatter={"subject": "first"}, body="b1", raw={"k": 1},
    )
    json_path = tmp_path / "integrations" / "gmail" / "messages" / "m-x.json"
    assert json_path.exists()
    # Re-write without raw — sidecar should be deleted to avoid stale data.
    mirror.write_record(
        workspace_root=tmp_path, app="gmail", resource="messages", record_id="m-x",
        frontmatter={"subject": "second"}, body="b2", raw=None,
    )
    assert not json_path.exists()


# ---------------------------------------------------------------------------
# list + delete
# ---------------------------------------------------------------------------
def test_list_records_yields_metadata(tmp_path):
    for i in range(3):
        mirror.write_record(
            workspace_root=tmp_path, app="gmail", resource="threads", record_id=f"t-{i}",
            frontmatter={"subject": f"sub-{i}"}, body=f"b{i}", raw={"i": i},
        )
    items = list(mirror.list_records(
        workspace_root=tmp_path, app="gmail", resource="threads",
    ))
    assert {it["id"] for it in items} == {"t-0", "t-1", "t-2"}
    assert all(it["frontmatter"].get("subject") for it in items)


def test_list_records_handles_missing_folder(tmp_path):
    items = list(mirror.list_records(
        workspace_root=tmp_path, app="never", resource="here",
    ))
    assert items == []


def test_delete_record_removes_both_files(tmp_path):
    mirror.write_record(
        workspace_root=tmp_path, app="gmail", resource="messages", record_id="m-z",
        frontmatter={"x": 1}, body="b", raw={"x": 1},
    )
    assert mirror.delete_record(
        workspace_root=tmp_path, app="gmail", resource="messages", record_id="m-z",
    ) is True
    folder = tmp_path / "integrations" / "gmail" / "messages"
    assert list(folder.iterdir()) == []
    # Calling again on an already-deleted id returns False.
    assert mirror.delete_record(
        workspace_root=tmp_path, app="gmail", resource="messages", record_id="m-z",
    ) is False
