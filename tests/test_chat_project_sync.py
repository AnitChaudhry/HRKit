from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from hrkit import chat
from hrkit.modules import project


class _FakeHandler:
    def __init__(self, conn):
        self.server = SimpleNamespace(conn=conn)
        self.json_responses = []
        self.html_responses = []

    def _json(self, obj, code: int = 200) -> None:
        self.json_responses.append((code, obj))

    def _html(self, code: int, html: str) -> None:
        self.html_responses.append((code, html))


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
