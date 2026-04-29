"""Tests for hrkit.sandbox — AI sandbox enforcement."""

from __future__ import annotations

import inspect
import sqlite3
import urllib.request

import pytest

from hrkit import sandbox


def _conn_with(setting_value: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    if setting_value is not None:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("AI_LOCAL_ONLY", setting_value),
        )
    return conn


# ---------------------------------------------------------------------------
# is_sandboxed — defaults
# ---------------------------------------------------------------------------
def test_is_sandboxed_default_off(monkeypatch):
    """No env, no DB row, no conn -> sandbox is OFF (full-capability agent)."""
    monkeypatch.delenv("AI_LOCAL_ONLY", raising=False)
    assert sandbox.is_sandboxed(None) is False


def test_is_sandboxed_explicit_on_via_db(monkeypatch):
    """Operator opts into paranoid mode by setting AI_LOCAL_ONLY=1."""
    monkeypatch.delenv("AI_LOCAL_ONLY", raising=False)
    conn = _conn_with("1")
    assert sandbox.is_sandboxed(conn) is True


def test_is_sandboxed_env_overrides_db(monkeypatch):
    """Env wins over DB. DB OFF + env ON -> sandbox is ON."""
    monkeypatch.setenv("AI_LOCAL_ONLY", "1")
    conn = _conn_with("0")
    assert sandbox.is_sandboxed(conn) is True


# ---------------------------------------------------------------------------
# is_network_tool — name matching
# ---------------------------------------------------------------------------
def test_is_network_tool_recognises_web_search():
    def web_search(q): return ""  # noqa: E704
    assert sandbox.is_network_tool(web_search)


def test_is_network_tool_recognises_composio_action_slug():
    def fn(): pass
    fn.__name__ = "GMAIL_SEND_EMAIL"
    assert sandbox.is_network_tool(fn)


def test_is_network_tool_does_not_flag_local_helpers():
    def query_records(): pass
    def list_imported_tables(): pass
    def my_recipe(): pass
    assert not sandbox.is_network_tool(query_records)
    assert not sandbox.is_network_tool(list_imported_tables)
    assert not sandbox.is_network_tool(my_recipe)


def test_is_network_tool_honours_attribute_flag():
    def fn(): pass
    fn.network = True  # type: ignore[attr-defined]
    assert sandbox.is_network_tool(fn)


# ---------------------------------------------------------------------------
# filter_tools — drops network tools when sandboxed
# ---------------------------------------------------------------------------
def _make_tools():
    def query_records(): pass
    def web_search(q): return ""
    def web_fetch(url): return ""
    def composio_action(): pass
    composio_action.__name__ = "GOOGLECALENDAR_LIST_EVENTS"
    def my_local_recipe(): pass
    return [query_records, web_search, web_fetch, composio_action, my_local_recipe]


def test_filter_tools_strips_network_when_sandboxed(monkeypatch):
    monkeypatch.delenv("AI_LOCAL_ONLY", raising=False)
    conn = _conn_with("1")
    kept = sandbox.filter_tools(_make_tools(), conn)
    names = [t.__name__ for t in kept]
    assert "query_records" in names
    assert "my_local_recipe" in names
    assert "web_search" not in names
    assert "web_fetch" not in names
    assert "GOOGLECALENDAR_LIST_EVENTS" not in names


def test_filter_tools_passthrough_when_unsandboxed(monkeypatch):
    monkeypatch.setenv("AI_LOCAL_ONLY", "0")
    conn = _conn_with("0")
    tools = _make_tools()
    kept = sandbox.filter_tools(tools, conn)
    assert len(kept) == len(tools)


def test_filter_tools_handles_none_input(monkeypatch):
    monkeypatch.delenv("AI_LOCAL_ONLY", raising=False)
    assert sandbox.filter_tools(None, None) == []


# ---------------------------------------------------------------------------
# assert_path_in_workspace — path traversal
# ---------------------------------------------------------------------------
def test_assert_path_accepts_inside(tmp_path):
    inside = tmp_path / "documents" / "file.pdf"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.touch()
    resolved = sandbox.assert_path_in_workspace(inside, tmp_path)
    assert resolved == inside.resolve()


def test_assert_path_relative_resolves_against_root(tmp_path):
    (tmp_path / "doc.txt").write_text("x")
    resolved = sandbox.assert_path_in_workspace("doc.txt", tmp_path)
    assert resolved == (tmp_path / "doc.txt").resolve()


def test_assert_path_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match="escapes workspace"):
        sandbox.assert_path_in_workspace("../outside.txt", tmp_path)


def test_assert_path_rejects_absolute_outside(tmp_path):
    other = tmp_path.parent / "elsewhere.txt"
    with pytest.raises(ValueError, match="escapes workspace"):
        sandbox.assert_path_in_workspace(other, tmp_path)


# ---------------------------------------------------------------------------
# network_disabled — runtime block
# ---------------------------------------------------------------------------
def test_network_disabled_blocks_urlopen():
    """Inside the context manager, urlopen on a non-loopback host raises."""
    with sandbox.network_disabled():
        with pytest.raises(sandbox.NetworkBlocked):
            urllib.request.urlopen("http://example.com/", timeout=2)


def test_network_disabled_releases_on_exit():
    """After the context manager exits, the patch is inactive in this thread."""
    with sandbox.network_disabled():
        pass
    # We don't actually try a real urlopen here (would need the network);
    # we just check the thread-local flag is reset.
    assert not sandbox._is_blocked_in_this_thread()


def test_network_disabled_if_noop_when_unsandboxed(monkeypatch):
    monkeypatch.setenv("AI_LOCAL_ONLY", "0")
    conn = _conn_with("0")
    with sandbox.network_disabled_if(conn):
        # Block flag stays False
        assert not sandbox._is_blocked_in_this_thread()


def test_network_disabled_if_blocks_when_sandboxed(monkeypatch):
    monkeypatch.delenv("AI_LOCAL_ONLY", raising=False)
    conn = _conn_with("1")
    with sandbox.network_disabled_if(conn):
        assert sandbox._is_blocked_in_this_thread()
    assert not sandbox._is_blocked_in_this_thread()


# ---------------------------------------------------------------------------
# status_summary — operator-facing string
# ---------------------------------------------------------------------------
def test_status_summary_reflects_setting(monkeypatch):
    monkeypatch.delenv("AI_LOCAL_ONLY", raising=False)
    on_conn = _conn_with("1")
    off_conn = _conn_with("0")
    assert "ENABLED" in sandbox.status_summary(on_conn)
    assert "DISABLED" in sandbox.status_summary(off_conn)


# ---------------------------------------------------------------------------
# guard_tool_execution - tool-level sandboxing
# ---------------------------------------------------------------------------
def test_guard_tool_execution_preserves_signature_and_blocks_when_sandboxed(monkeypatch):
    monkeypatch.delenv("AI_LOCAL_ONLY", raising=False)
    conn = _conn_with("1")

    def local_tool(rel_path: str, limit: int = 10) -> bool:
        return sandbox._is_blocked_in_this_thread()

    guarded = sandbox.guard_tool_execution(local_tool, conn)

    sig = inspect.signature(guarded)
    assert list(sig.parameters) == ["rel_path", "limit"]
    assert sig.parameters["limit"].default == 10
    assert guarded("notes.txt") is True
    assert not sandbox._is_blocked_in_this_thread()


def test_guard_tool_execution_noop_network_guard_when_unsandboxed(monkeypatch):
    monkeypatch.setenv("AI_LOCAL_ONLY", "0")
    conn = _conn_with("0")

    def local_tool() -> bool:
        return sandbox._is_blocked_in_this_thread()

    guarded = sandbox.guard_tool_execution(local_tool, conn)

    assert guarded() is False


def test_guard_tools_wraps_callable_list(monkeypatch):
    monkeypatch.delenv("AI_LOCAL_ONLY", raising=False)
    conn = _conn_with("1")

    def local_tool() -> bool:
        return sandbox._is_blocked_in_this_thread()

    wrapped = sandbox.guard_tools([local_tool, {"name": "dict_tool"}], conn)

    assert wrapped[0]() is True
    assert wrapped[1] == {"name": "dict_tool"}
