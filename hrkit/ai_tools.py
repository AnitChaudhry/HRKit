"""Built-in tools always available to the AI agent.

Two stdlib-only callables, exposed by default to the chat agent so even
free tool-calling models can do something useful without any Composio app
connected:

    web_search(query: str) -> str
    web_fetch(url: str) -> str

Both are subject to the existing ``COMPOSIO_DISABLED_TOOLS`` filter (their
slugs are ``WEB_SEARCH`` and ``WEB_FETCH`` upper-cased), so a user who
turns them off on the Integrations page sees them disappear from the
agent's tool list.

Stdlib only.
"""

from __future__ import annotations

import html as htmllib
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

log = logging.getLogger(__name__)

WEB_SEARCH_SLUG = "WEB_SEARCH"
WEB_FETCH_SLUG = "WEB_FETCH"

_USER_AGENT = "Mozilla/5.0 (compatible; HR-Kit/0.2; +https://thinqmesh.com)"
_TIMEOUT = 12.0
_MAX_BYTES = 1 * 1024 * 1024  # 1 MB cap on any single fetch
_MAX_RESULT_CHARS = 6000

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
    r'.*?<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = htmllib.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _http_get(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/html, */*;q=0.5"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        raw = resp.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise ValueError(f"response exceeds {_MAX_BYTES} bytes; refusing to read further")
    encoding = resp.headers.get_content_charset() if hasattr(resp, "headers") else None
    return raw.decode(encoding or "utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Public callables — exposed as AI tools
# ---------------------------------------------------------------------------
def web_search(query: str) -> str:
    """Search the web (DuckDuckGo HTML) and return the top results as text.

    Args:
      query: A short natural-language search query.

    Returns a plain-text list of up to 8 results in the form::

        1. <Title>
           <URL>
           <Snippet>

    On error returns a string starting with ``error:`` so the LLM can read
    and react. Never raises.
    """
    q = (query or "").strip()
    if not q:
        return "error: empty query"
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q})
    try:
        body = _http_get(url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return f"error: web_search transport failed: {exc}"
    matches = _DDG_RESULT_RE.findall(body)
    if not matches:
        return "no results"
    lines: list[str] = []
    for i, (raw_url, raw_title, raw_snippet) in enumerate(matches[:8], start=1):
        # DuckDuckGo wraps result urls in /l/?uddg=<encoded>... — try to unwrap.
        unwrapped = raw_url
        try:
            parsed = urllib.parse.urlparse(raw_url)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs and qs["uddg"]:
                unwrapped = urllib.parse.unquote(qs["uddg"][0])
        except (ValueError, KeyError):
            pass
        title = _strip_html(raw_title)
        snippet = _strip_html(raw_snippet)
        lines.append(f"{i}. {title}\n   {unwrapped}\n   {snippet}")
    return "\n\n".join(lines)


def web_fetch(url: str) -> str:
    """Fetch a URL and return its readable text content.

    Args:
      url: Full ``http(s)://`` URL.

    HTML is stripped to plain text. Result is capped at ~6 000 characters
    so the AI's context window doesn't blow up on a single page. On error
    returns a string starting with ``error:``. Never raises.
    """
    raw_url = (url or "").strip()
    if not raw_url:
        return "error: empty url"
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        return "error: only http/https URLs are allowed"
    try:
        body = _http_get(raw_url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return f"error: web_fetch transport failed: {exc}"
    text = _strip_html(body)
    if len(text) > _MAX_RESULT_CHARS:
        text = text[:_MAX_RESULT_CHARS] + f"\n... (truncated; {len(text) - _MAX_RESULT_CHARS} more chars)"
    return text


# ---------------------------------------------------------------------------
# Tool object exposed to pydantic-ai
# ---------------------------------------------------------------------------
# pydantic-ai inspects the wrapped function's name + signature for its
# tool schema. Setting __name__ explicitly to the upper-cased slug makes
# the disabled-tools filter pick them up under the same convention as
# Composio actions (UPPER_SNAKE).
web_search.__name__ = WEB_SEARCH_SLUG
web_fetch.__name__ = WEB_FETCH_SLUG


def builtin_tools() -> list[Callable[..., str]]:
    """Return the always-available web tools as a list of callables."""
    return [web_search, web_fetch]


__all__ = [
    "WEB_SEARCH_SLUG",
    "WEB_FETCH_SLUG",
    "web_search",
    "web_fetch",
    "builtin_tools",
]
