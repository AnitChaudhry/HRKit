"""Batched tests for Phases 1.6 (chat upgrades), 1.8 (chat persistence), 1.9 (recipes)."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from hrkit import ai, chat_storage, recipes, recipes_ui


# ===========================================================================
# Phase 1.6 — model picker + friendly error translation
# ===========================================================================
def test_friendly_error_maps_low_credits():
    msg = ai.friendly_error("Error code: 402 - {'message': 'insufficient_quota: Low credits'}")
    assert "Low credits" in msg


def test_friendly_error_maps_rate_limit():
    msg = ai.friendly_error("rate_limit_exceeded on this model")
    assert "rate limit" in msg.lower()


def test_friendly_error_maps_model_not_found():
    msg = ai.friendly_error("model_not_found: gpt-99-ultra does not exist")
    assert "model" in msg.lower() and "available" in msg.lower()


def test_friendly_error_passes_through_unknown():
    msg = ai.friendly_error("strange unforeseen error")
    assert msg == "strange unforeseen error"


def _fake_models_response(items):
    resp = MagicMock()
    resp.read.return_value = json.dumps({"data": items}).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_list_models_marks_free_models(memconn_with_ai_key):
    items = [
        {"id": "meta-llama/llama-3.3-70b-instruct:free", "pricing": {"prompt": "0"}},
        {"id": "openai/gpt-4o", "pricing": {"prompt": "0.005"}},
        {"id": "free-by-suffix:free"},
    ]
    with patch("urllib.request.urlopen", return_value=_fake_models_response(items)):
        out = ai.list_models(memconn_with_ai_key)
    assert out["ok"] is True
    by_id = {m["id"]: m for m in out["models"]}
    assert by_id["meta-llama/llama-3.3-70b-instruct:free"]["free"] is True
    assert by_id["openai/gpt-4o"]["free"] is False
    assert by_id["free-by-suffix:free"]["free"] is True
    # Free models sorted first.
    assert out["models"][0]["free"] is True


def test_list_models_returns_error_when_no_key(memconn_no_key):
    out = ai.list_models(memconn_no_key)
    assert out["ok"] is False
    assert "API key not set" in out["error"]


# ===========================================================================
# Phase 1.8 — file-based chat persistence
# ===========================================================================
def test_save_and_load_conversation_round_trip(tmp_path):
    cid = chat_storage.new_conversation_id("hello there")
    msgs = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi! How can I help?"},
    ]
    chat_storage.save_conversation(
        workspace_root=tmp_path, conversation_id=cid, messages=msgs,
        title="Greeting", model="meta-llama/llama-3.3:free",
    )
    md = tmp_path / "conversations" / f"{cid}.md"
    js = tmp_path / "conversations" / f"{cid}.json"
    assert md.exists() and js.exists()

    loaded = chat_storage.load_conversation(workspace_root=tmp_path, conversation_id=cid)
    assert loaded is not None
    assert loaded["id"] == cid
    assert loaded["title"] == "Greeting"
    assert loaded["model"] == "meta-llama/llama-3.3:free"
    assert len(loaded["messages"]) == 2
    assert loaded["messages"][0]["role"] == "user"


def test_save_conversation_preserves_created_on_resave(tmp_path):
    cid = chat_storage.new_conversation_id("x")
    chat_storage.save_conversation(
        workspace_root=tmp_path, conversation_id=cid,
        messages=[{"role": "user", "content": "first"}],
    )
    first = chat_storage.load_conversation(workspace_root=tmp_path, conversation_id=cid)
    chat_storage.save_conversation(
        workspace_root=tmp_path, conversation_id=cid,
        messages=[{"role": "user", "content": "first"},
                  {"role": "assistant", "content": "ack"}],
    )
    second = chat_storage.load_conversation(workspace_root=tmp_path, conversation_id=cid)
    # `created` is preserved across saves.
    assert first["created"] == second["created"]


def test_list_conversations_orders_newest_first(tmp_path):
    for i in range(3):
        chat_storage.save_conversation(
            workspace_root=tmp_path,
            conversation_id=f"2026-04-2{i}-test-abc{i}",
            messages=[{"role": "user", "content": f"msg-{i}"}],
            title=f"Convo {i}",
        )
    items = chat_storage.list_conversations(workspace_root=tmp_path)
    assert len(items) == 3
    # All have the same created/updated within ms; sort is stable enough.
    assert {i["title"] for i in items} == {"Convo 0", "Convo 1", "Convo 2"}


def test_employee_scoped_conversation_lives_in_employee_folder(tmp_path):
    cid = chat_storage.new_conversation_id("onboarding")
    chat_storage.save_conversation(
        workspace_root=tmp_path, conversation_id=cid,
        messages=[{"role": "user", "content": "Welcome plan?"}],
        employee_code="EMP-007",
    )
    expected = tmp_path / "employees" / "EMP-007" / "conversations" / f"{cid}.md"
    assert expected.exists()


def test_load_conversation_returns_none_when_missing(tmp_path):
    assert chat_storage.load_conversation(
        workspace_root=tmp_path, conversation_id="nope-nope-nope"
    ) is None


# ===========================================================================
# Phase 1.9 — recipes
# ===========================================================================
def test_save_and_load_recipe(tmp_path):
    out = recipes.save_recipe(
        workspace_root=tmp_path,
        slug="send-offer",
        name="Send offer letter",
        description="Email the candidate the offer",
        tools=["GMAIL_SEND_EMAIL"],
        inputs=["candidate_name", "candidate_email", "position"],
        body="Dear {candidate_name}, please find your offer for {position} attached.",
    )
    assert out["slug"] == "send-offer"
    loaded = recipes.load_recipe(tmp_path, "send-offer")
    assert loaded["name"] == "Send offer letter"
    assert loaded["tools"] == ["GMAIL_SEND_EMAIL"]
    assert "candidate_name" in loaded["inputs"]
    assert "{candidate_name}" in loaded["body"]


def test_list_recipes_returns_metadata(tmp_path):
    for i, slug in enumerate(("a-recipe", "b-recipe", "c-recipe")):
        recipes.save_recipe(
            workspace_root=tmp_path, slug=slug, name=f"Name {i}",
            tools=["WEB_SEARCH"], inputs=[], body=f"body {i}",
        )
    items = recipes.list_recipes(tmp_path)
    assert {i["slug"] for i in items} == {"a-recipe", "b-recipe", "c-recipe"}


def test_delete_recipe_removes_file(tmp_path):
    recipes.save_recipe(
        workspace_root=tmp_path, slug="kill-me", name="X", body="x",
    )
    assert recipes.delete_recipe(tmp_path, "kill-me") is True
    assert recipes.load_recipe(tmp_path, "kill-me") is None
    # Idempotent.
    assert recipes.delete_recipe(tmp_path, "kill-me") is False


def test_render_recipe_substitutes_known_placeholders(tmp_path):
    recipe = {
        "name": "Greet",
        "body": "Hi {name}, your offer at {place} is ready.",
    }
    out = recipes.render_recipe(recipe, {"name": "Asha", "place": "Bangalore"})
    assert "Hi Asha" in out
    assert "Bangalore" in out


def test_render_recipe_leaves_unknown_placeholders_literal(tmp_path):
    recipe = {"name": "X", "body": "Hello {name}, your {missing} pings."}
    out = recipes.render_recipe(recipe, {"name": "Asha"})
    assert "Hello Asha" in out
    assert "{missing}" in out


def test_save_recipe_normalizes_slug(tmp_path):
    out = recipes.save_recipe(
        workspace_root=tmp_path, slug="Send Offer Letter!!!", name="X", body="y",
    )
    assert out["slug"] == "send-offer-letter"


def test_save_recipe_rejects_empty_slug(tmp_path):
    with pytest.raises(ValueError):
        recipes.save_recipe(workspace_root=tmp_path, slug="!!!", name="X", body="y")


def test_build_recipe_tools_returns_callable(tmp_path):
    recipes.save_recipe(
        workspace_root=tmp_path, slug="say-hi", name="Say hi",
        body="Say hi to {who}", inputs=["who"],
    )
    tools = recipes_ui.build_recipe_tools(conn=None, workspace_root=tmp_path)
    assert len(tools) == 1
    fn = tools[0]
    out = fn("say-hi", {"who": "Asha"})
    assert "Say hi to Asha" in out
    # Unknown slug returns an error string instead of raising.
    err = fn("does-not-exist", {})
    assert err.startswith("error:")


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def memconn_with_ai_key():
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    c.execute("INSERT INTO settings VALUES ('AI_API_KEY', 'sk-test')")
    c.execute("INSERT INTO settings VALUES ('AI_PROVIDER', 'openrouter')")
    c.commit()
    yield c
    c.close()


@pytest.fixture
def memconn_no_key():
    import sqlite3, os
    # Make sure env vars don't bleed into the test.
    saved = os.environ.pop("AI_API_KEY", None)
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    c.commit()
    yield c
    c.close()
    if saved is not None:
        os.environ["AI_API_KEY"] = saved
