"""Smoke tests for hrkit.ai_tools — built-in web tools exposed to the AI."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from hrkit import ai_tools


def test_builtin_tools_lists_two_callables():
    tools = ai_tools.builtin_tools()
    assert len(tools) == 2
    names = [t.__name__ for t in tools]
    assert "WEB_SEARCH" in names
    assert "WEB_FETCH" in names


def test_web_search_returns_error_string_on_empty_query():
    out = ai_tools.web_search("")
    assert out.startswith("error:")


def test_web_fetch_rejects_non_http_url():
    out = ai_tools.web_fetch("file:///etc/passwd")
    assert "only http/https" in out


def test_web_fetch_returns_error_string_on_empty_url():
    out = ai_tools.web_fetch("")
    assert out.startswith("error:")


def _fake_response(body: bytes, charset: str | None = None):
    resp = MagicMock()
    resp.read.return_value = body
    resp.headers.get_content_charset.return_value = charset
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_web_fetch_strips_html_to_text():
    body = b"<html><body><h1>Hello</h1><p>World &amp; More</p></body></html>"
    with patch("urllib.request.urlopen", return_value=_fake_response(body, "utf-8")):
        out = ai_tools.web_fetch("https://example.com")
    assert "Hello" in out and "World & More" in out
    assert "<h1>" not in out


def test_web_search_parses_ddg_html_results():
    # Minimal DuckDuckGo HTML shape that the parser expects.
    html = (
        b'<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fone">'
        b'<b>One</b></a>'
        b'<a class="result__snippet" href="/l/?x=1">snippet one</a>'
        b'<a class="result__a" href="https://example.com/two">Two</a>'
        b'<a class="result__snippet" href="/l/?x=2">snippet two</a>'
    )
    with patch("urllib.request.urlopen", return_value=_fake_response(html, "utf-8")):
        out = ai_tools.web_search("hello")
    assert "1. One" in out
    assert "https://example.com/one" in out
    assert "snippet one" in out
    assert "2. Two" in out
