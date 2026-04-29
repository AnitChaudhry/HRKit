from __future__ import annotations

import asyncio
import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from hrkit import chat
from hrkit.modules import project


class _FakeHandler:
    def __init__(self, conn, workspace_root=None):
        self.server = SimpleNamespace(conn=conn, workspace_root=workspace_root)
        self.json_responses = []
        self.html_responses = []
        self.headers = []
        self.status_code = None
        self.wfile = BytesIO()

    def _json(self, obj, code: int = 200) -> None:
        self.json_responses.append((code, obj))

    def _html(self, code: int, html: str) -> None:
        self.html_responses.append((code, html))

    def send_response(self, code: int) -> None:
        self.status_code = code

    def send_header(self, key: str, value: str) -> None:
        self.headers.append((key, value))

    def end_headers(self) -> None:
        pass


def _seed_employee(conn) -> int:
    dept_id = conn.execute(
        "INSERT INTO department (name, code) VALUES (?, ?)",
        ("Engineering", "ENG"),
    ).lastrowid
    role_id = conn.execute(
        "INSERT INTO role (title, department_id) VALUES (?, ?)",
        ("Engineer", dept_id),
    ).lastrowid
    employee_id = conn.execute(
        """
        INSERT INTO employee(employee_code, full_name, email, department_id, role_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("EMP-CHAT-1", "Project Tester", "project.tester@example.com", dept_id, role_id),
    ).lastrowid
    conn.commit()
    return int(employee_id)


def test_chat_page_model_picker_hides_voice_models():
    html = chat.render_chat_page()

    assert "m.chat_compatible !== false" in html
    assert "voice/audio model(s) hidden" in html
    assert "Chatterbox" in html
    assert 'id="stop-btn"' in html
    assert "function stopStreaming()" in html
    assert "new AbortController()" in html
    assert "inline-flex" in html
    assert "pendingQueue.push" in html
    assert "runNextQueuedTurn()" in html
    assert "Full access" not in html
    assert ">Mic<" not in html
    assert ">Attach<" in html
    assert 'id="attach-btn"' in html
    assert "Attaching..." in html
    assert "rel_path: data.rel_path" in html
    assert "artifact-panel" in html
    assert ">Artifacts<" in html
    assert "grid-template-columns:minmax(280px,324px)" in html
    assert "max-width:none;width:100%" in html


def test_chat_rejects_voice_model_override(conn, monkeypatch):
    def fake_list_models(_conn):
        return {
            "ok": True,
            "models": [
                {
                    "id": "upfynai-chatterbox",
                    "chat_compatible": False,
                    "capabilities": ["voice-generation", "voice-cloning"],
                }
            ],
        }

    async def fail_run_agent(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("run_agent should not be called for voice models")

    monkeypatch.setattr(chat.ai, "list_models", fake_list_models)
    monkeypatch.setattr(chat.ai, "run_agent", fail_run_agent)

    handler = _FakeHandler(conn)
    asyncio.run(chat.handle_chat_message(
        handler,
        {"message": "hello", "model": "upfynai-chatterbox"},
    ))

    code, payload = handler.json_responses[0]
    assert code == 400
    assert payload["ok"] is False
    assert "not a chat model" in payload["error"]
    assert "voice-generation" in payload["error"]


def test_chat_api_persists_successful_conversation(conn, tmp_path, monkeypatch):
    async def fake_run_agent(*_args, **_kwargs):
        return "HR chat online"

    monkeypatch.setattr(chat.ai, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat.ai, "list_models", lambda _conn: {"ok": True, "models": []})

    handler = _FakeHandler(conn, workspace_root=tmp_path)
    asyncio.run(chat.handle_chat_message(handler, {"message": "Hello"}))

    code, payload = handler.json_responses[0]
    assert code == 200
    assert payload["ok"] is True
    assert payload["persisted"] is True
    assert payload["turns"] == 2
    assert payload["conversation_id"]
    saved = chat.chat_storage.load_conversation(
        workspace_root=tmp_path,
        conversation_id=payload["conversation_id"],
    )
    assert saved is not None
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]
    assert saved["messages"][1]["content"] == "HR chat online"
    assert payload["artifacts"]
    first_artifact = tmp_path / payload["artifacts"][0]["rel_path"]
    assert first_artifact.exists()
    assert "HR chat online" in first_artifact.read_text(encoding="utf-8")


def test_chat_api_treats_provider_busy_text_as_retryable(conn, tmp_path, monkeypatch):
    async def fake_run_agent(*_args, **_kwargs):
        return "Our servers are experiencing brief congestion. Please retry your message."

    monkeypatch.setattr(chat.ai, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat.ai, "list_models", lambda _conn: {"ok": True, "models": []})

    handler = _FakeHandler(conn, workspace_root=tmp_path)
    asyncio.run(chat.handle_chat_message(handler, {"message": "Hello"}))

    code, payload = handler.json_responses[0]
    assert code == 503
    assert payload["ok"] is False
    assert payload["retryable"] is True
    assert "temporarily busy" in payload["error"]
    assert not (tmp_path / "conversations").exists()


def test_chat_stream_sends_deltas_and_persists(conn, tmp_path, monkeypatch):
    async def fake_stream_agent(*_args, **_kwargs):
        yield "HR "
        yield "chat "
        yield "streaming"

    monkeypatch.setattr(chat.ai, "stream_agent", fake_stream_agent)
    monkeypatch.setattr(chat.ai, "list_models", lambda _conn: {"ok": True, "models": []})

    handler = _FakeHandler(conn, workspace_root=tmp_path)
    asyncio.run(chat.handle_chat_stream(handler, {"message": "Hello"}))

    raw = handler.wfile.getvalue().decode("utf-8")
    assert handler.status_code == 200
    assert ("Content-Type", "text/event-stream; charset=utf-8") in handler.headers
    assert "event: delta" in raw
    assert "HR " in raw
    assert "chat " in raw
    assert "event: done" in raw
    assert "HR chat streaming" in raw

    saved_ids = [p.stem for p in (tmp_path / "conversations").glob("*.json")]
    assert saved_ids
    saved = chat.chat_storage.load_conversation(
        workspace_root=tmp_path,
        conversation_id=saved_ids[0],
    )
    assert saved["messages"][1]["content"] == "HR chat streaming"
    assert saved["messages"][1]["artifacts"]


def test_chat_autosaves_html_and_email_artifacts(conn, tmp_path, monkeypatch):
    async def fake_run_agent(*_args, **_kwargs):
        return (
            "Subject: Monthly performance summary\n\n"
            "Dear team,\nAttached is the monthly performance summary.\n\n"
            "```html\n<html><body><h1>Performance</h1></body></html>\n```"
        )

    monkeypatch.setattr(chat.ai, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat.ai, "list_models", lambda _conn: {"ok": True, "models": []})

    handler = _FakeHandler(conn, workspace_root=tmp_path)
    asyncio.run(chat.handle_chat_message(handler, {"message": "Draft an email and HTML report"}))

    _code, payload = handler.json_responses[0]
    kinds = {item["kind"] for item in payload["artifacts"]}
    assert {"markdown", "html", "email"}.issubset(kinds)
    for item in payload["artifacts"]:
        assert (tmp_path / item["rel_path"]).exists()


def test_artifact_and_web_tools_save_to_workspace(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(chat.ai_tools, "web_search", lambda query: "1. Result\n   https://example.com")

    tools = chat._build_artifact_tools(tmp_path, conn, conversation_id="conv-1")
    tools += chat._build_builtin_tools(tmp_path, conn, conversation_id="conv-1")
    by_name = {tool.__name__: tool for tool in tools}

    pdf_result = by_name["create_pdf"]("April HR Report", "All teams are green.")
    assert "April HR Report" not in pdf_result  # result is a compact JSON envelope
    pdf_payload = json.loads(pdf_result)
    assert pdf_payload["ok"] is True
    assert pdf_payload["rel_path"].endswith(".pdf")
    assert (tmp_path / pdf_payload["rel_path"]).read_bytes().startswith(b"%PDF")

    search_result = by_name["WEB_SEARCH"]("hr trends")
    assert "Saved locally:" in search_result
    saved_rel = search_result.split("Saved locally:", 1)[1].strip()
    assert (tmp_path / saved_rel).exists()


def test_chat_tool_can_sync_timesheet_hours_back_to_project(conn):
    employee_id = _seed_employee(conn)

    project_id = chat._dispatch(conn, "project", "create", {
        "data": {
            "name": "Client Portal",
            "code": "CP-2026",
            "status": "active",
            "client": "Acme",
        }
    })
    entry_id = chat._dispatch(conn, "timesheet", "create", {
        "data": {
            "employee_id": employee_id,
            "project_id": project_id,
            "date": "2026-04-29",
            "hours": "7.25",
            "billable": "1",
            "description": "Chat-created project work",
        }
    })

    rows = project.list_rows(conn)
    synced = next(row for row in rows if row["id"] == project_id)
    assert synced["hours_logged"] == pytest.approx(7.25)

    entry = chat._dispatch(conn, "timesheet", "get", {"id": entry_id})
    assert entry["project"] == "Client Portal"
    assert entry["employee"] == "Project Tester"

    handler = _FakeHandler(conn)
    project.detail_view(handler, project_id)
    code, html = handler.html_responses[0]
    assert code == 200
    assert "+ Log time" in html
    assert "Recent entries" in html
    assert "Chat-created project work" in html
