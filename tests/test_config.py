"""Tests for hrkit.config — workspace discovery, auto-init, and migration."""

from __future__ import annotations

import os

from hrkit import config as cfg


def test_init_workspace_creates_marker_and_meta_dir(tmp_path):
    cfg.init_workspace(tmp_path)
    assert (tmp_path / cfg.MARKER).is_file()
    assert (tmp_path / cfg.META_DIR).is_dir()
    txt = (tmp_path / cfg.MARKER).read_text(encoding="utf-8")
    assert "type: workspace" in txt


def test_init_workspace_is_idempotent(tmp_path):
    cfg.init_workspace(tmp_path, name="First")
    first = (tmp_path / cfg.MARKER).read_text(encoding="utf-8")
    cfg.init_workspace(tmp_path, name="Second")
    second = (tmp_path / cfg.MARKER).read_text(encoding="utf-8")
    # Existing marker preserved (we don't clobber a configured workspace).
    assert first == second
    assert "First" in second


def test_find_workspace_uses_HRKIT_ROOT_env(tmp_path, monkeypatch):
    cfg.init_workspace(tmp_path)
    monkeypatch.setenv("HRKIT_ROOT", str(tmp_path))
    assert cfg.find_workspace() == tmp_path


def test_find_workspace_falls_back_to_legacy_GETSET_ROOT(tmp_path, monkeypatch):
    """Existing 1.0.0 users may have GETSET_ROOT in their shell config."""
    cfg.init_workspace(tmp_path)
    monkeypatch.delenv("HRKIT_ROOT", raising=False)
    monkeypatch.setenv("GETSET_ROOT", str(tmp_path))
    assert cfg.find_workspace() == tmp_path


def test_find_workspace_recognises_legacy_marker(tmp_path, monkeypatch):
    """Workspaces created with 1.0.0 (getset.md) must still be discoverable."""
    (tmp_path / cfg.LEGACY_MARKER).write_text(
        "---\ntype: workspace\nname: Legacy\n---\n", encoding="utf-8"
    )
    monkeypatch.setenv("HRKIT_ROOT", str(tmp_path))
    assert cfg.find_workspace() == tmp_path


def test_migrate_legacy_layout_renames_dir_db_and_marker(tmp_path):
    # Plant a 1.0.0-style workspace.
    legacy_marker = tmp_path / cfg.LEGACY_MARKER
    legacy_marker.write_text(
        "---\ntype: workspace\nname: Old\n---\n", encoding="utf-8"
    )
    legacy_dir = tmp_path / cfg.LEGACY_META_DIR
    legacy_dir.mkdir()
    (legacy_dir / cfg.LEGACY_DB_NAME).write_bytes(b"sqlite-bytes")

    actions = cfg.migrate_legacy_layout(tmp_path)

    assert (tmp_path / cfg.MARKER).is_file()
    assert (tmp_path / cfg.META_DIR).is_dir()
    assert (tmp_path / cfg.META_DIR / cfg.DB_NAME).is_file()
    assert not legacy_marker.exists()
    assert not legacy_dir.exists()
    # Three rename actions reported.
    assert len(actions) == 3


def test_migrate_legacy_layout_no_op_when_already_new(tmp_path):
    cfg.init_workspace(tmp_path)
    (tmp_path / cfg.META_DIR / cfg.DB_NAME).write_bytes(b"x")
    actions = cfg.migrate_legacy_layout(tmp_path)
    assert actions == []


def test_migrate_legacy_layout_refuses_to_clobber(tmp_path):
    """If both old and new dirs exist, leave them alone (don't lose data)."""
    (tmp_path / cfg.LEGACY_META_DIR).mkdir()
    (tmp_path / cfg.META_DIR).mkdir()
    actions = cfg.migrate_legacy_layout(tmp_path)
    # The legacy dir is left in place + a clear notice is returned.
    assert (tmp_path / cfg.LEGACY_META_DIR).exists()
    assert any("left as-is" in a for a in actions)
