"""AI agent integration for HR Desk.

Implements the contract defined in AGENTS_SPEC.md Section 4.

Only this module (and ``evaluator.py``) is permitted to import ``pydantic_ai``.
All provider/key/model lookups go through ``hrkit.branding`` so settings
resolution stays consistent (env -> SQLite -> default).

Public surface:
    async run_agent(prompt, *, conn, system="", tools=None, model=None) -> str
    async stream_agent(prompt, *, conn, system="", tools=None, model=None)
    chat_complete(messages, *, conn, model=None) -> str
    health_check(conn) -> dict
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from typing import Any

from hrkit import sandbox
from hrkit.branding import (
    ai_api_key,
    ai_base_url,
    ai_model,
    ai_provider,
    composio_disabled_tools,
)

log = logging.getLogger(__name__)

# Reasonable defaults for network-bound calls. Kept short so the settings page
# health check feels snappy; agent runs override via their own timeout policy
# inside pydantic_ai if needed.
_HEALTH_TIMEOUT_SECONDS = 8.0
_CHAT_TIMEOUT_SECONDS = 60.0
_BROWSER_SAFE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


def _request_headers(api_key: str | None, *, json_body: bool = False) -> dict[str, str]:
    """Headers shared by all direct provider calls.

    Upfyn sits behind Cloudflare and rejects the default ``Python-urllib`` /
    ``OpenAI/Python`` user agents with HTTP 403 (Error 1010). A browser-like
    ``User-Agent`` keeps the request signature compatible across onboarding,
    settings, and chat flows.
    """
    headers = {
        "Accept": "application/json",
        "User-Agent": _BROWSER_SAFE_USER_AGENT,
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _build_openai_client(*, base_url: str, api_key: str):
    """Create an async OpenAI-compatible client with browser-safe headers."""
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - exercised via runtime error
        raise RuntimeError(
            "pydantic-ai-slim[openai] is not installed. "
            "Run: pip install 'pydantic-ai-slim[openai]>=1.0'"
        ) from exc

    return AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers={"User-Agent": _BROWSER_SAFE_USER_AGENT},
    )


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    """Extract a short user-facing message from a provider HTTP error."""
    raw = f"HTTP {exc.code}: {exc.reason}"
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - defensive: body streams can fail
        body = ""
    if not body:
        return friendly_error(raw)

    detail = ""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None

    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            parts = [str(err.get("code") or "").strip(), str(err.get("message") or "").strip()]
            detail = " ".join(p for p in parts if p).strip()
        elif isinstance(err, str):
            detail = err.strip()
        if not detail:
            parts = [str(payload.get("title") or "").strip(), str(payload.get("detail") or "").strip()]
            detail = " ".join(p for p in parts if p).strip()

    if not detail:
        detail = body.strip()[:300]

    if not detail:
        return friendly_error(raw)

    friendly = friendly_error(detail)
    if friendly != detail:
        return friendly
    return f"HTTP {exc.code}: {detail}"


def _tool_name(tool: Any) -> str:
    """Best-effort name extraction for a pydantic-ai Tool / callable / dict."""
    for attr in ("name", "__name__"):
        val = getattr(tool, attr, None)
        if isinstance(val, str) and val:
            return val.upper()
    if isinstance(tool, dict):
        for key in ("name", "slug"):
            v = tool.get(key)
            if isinstance(v, str) and v:
                return v.upper()
    return ""


def filter_disabled_tools(tools: list | None, conn) -> list:
    """Drop tools whose name matches a slug in ``COMPOSIO_DISABLED_TOOLS``.

    Comparison is case-insensitive (slugs are stored upper-cased). Tools
    without an extractable name pass through unchanged so that locally
    defined helpers (e.g., ``query_records``) are never accidentally hidden
    just because they don't expose a ``.name`` attribute.
    """
    if not tools:
        return list(tools or [])
    disabled = composio_disabled_tools(conn)
    if not disabled:
        return list(tools)
    kept: list = []
    for tool in tools:
        name = _tool_name(tool)
        if name and name in disabled:
            log.debug("ai: dropping disabled tool %s", name)
            continue
        kept.append(tool)
    return kept


def _resolve(conn, model_override: str | None) -> tuple[str, str, str, str]:
    """Pull provider/base_url/api_key/model from branding settings.

    Returns a tuple ``(provider, base_url, api_key, model)``. Caller decides
    how to react to a missing key — most callers should raise a clear error.
    """
    provider = ai_provider(conn)
    base_url = ai_base_url(conn)
    api_key = ai_api_key(conn)
    model = (model_override or ai_model(conn)).strip()
    return provider, base_url, api_key, model


def _require_key(api_key: str, provider: str) -> None:
    if not api_key:
        raise RuntimeError(
            f"AI API key is not configured for provider '{provider}'. "
            "Set AI_API_KEY env var or paste the key in Settings."
        )


def _build_agent(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    tools: list | None,
):
    """Construct a fresh pydantic_ai.Agent for a single run.

    Imported lazily so that ``import hrkit.ai`` succeeds even before
    the optional dependency is installed (useful during static checks and the
    Wave 1 smoke tests). The dependency IS required at call time.
    """
    try:
        from pydantic_ai import Agent
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
    except ImportError as exc:  # pragma: no cover - exercised via runtime error
        raise RuntimeError(
            "pydantic-ai-slim[openai] is not installed. "
            "Run: pip install 'pydantic-ai-slim[openai]>=1.0'"
        ) from exc

    provider = OpenAIProvider(
        openai_client=_build_openai_client(base_url=base_url, api_key=api_key)
    )
    chat_model = OpenAIChatModel(model, provider=provider)

    kwargs: dict[str, Any] = {}
    if system:
        kwargs["system_prompt"] = system
    if tools:
        kwargs["tools"] = list(tools)

    return Agent(chat_model, **kwargs)


async def run_agent(
    prompt: str,
    *,
    conn,
    system: str = "",
    tools: list | None = None,
    model: str | None = None,
) -> str:
    """Run one agent turn and return the final text response.

    Uses ``pydantic_ai.Agent`` against an OpenAI-compatible endpoint
    (OpenRouter or Upfyn). Provider/key/model are resolved per-call so the
    settings page can update them without restarting the server.
    """
    provider, base_url, api_key, model_name = _resolve(conn, model)
    _require_key(api_key, provider)

    # Honor the user's per-tool toggles set on /integrations, then guard each
    # remaining tool body when AI_LOCAL_ONLY is enabled.
    effective_tools = sandbox.guard_tools(filter_disabled_tools(tools, conn), conn)

    agent = _build_agent(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        system=system,
        tools=effective_tools,
    )

    log.debug("run_agent: provider=%s model=%s tools=%d (filtered from %d)",
              provider, model_name, len(effective_tools), len(tools or []))
    try:
        result = await agent.run(prompt)
    except Exception as exc:
        # Re-raise with a friendlier message attached so the chat UI can
        # show "Low credits" instead of a stack trace.
        nice = friendly_error(exc)
        raise RuntimeError(nice) from exc

    # pydantic-ai >= 1.0 exposes the final text as ``output`` on AgentRunResult.
    # Fall back gracefully across minor version names.
    text = getattr(result, "output", None)
    if text is None:
        text = getattr(result, "data", None)
    if text is None:
        text = str(result)
    return str(text)


async def stream_agent(
    prompt: str,
    *,
    conn,
    system: str = "",
    tools: list | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    """Stream one agent turn as text deltas.

    This uses pydantic-ai's streaming run path, so the browser receives the
    provider's partial text as it arrives while still keeping HR tools enabled.
    """
    provider, base_url, api_key, model_name = _resolve(conn, model)
    _require_key(api_key, provider)

    # Honor the user's per-tool toggles set on /integrations, then guard each
    # remaining tool body when AI_LOCAL_ONLY is enabled. The provider request
    # itself still needs network access for UpfynAI/OpenAI.
    effective_tools = sandbox.guard_tools(filter_disabled_tools(tools, conn), conn)

    agent = _build_agent(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        system=system,
        tools=effective_tools,
    )

    log.debug("stream_agent: provider=%s model=%s tools=%d (filtered from %d)",
              provider, model_name, len(effective_tools), len(tools or []))
    try:
        async with agent.run_stream(prompt) as result:
            async for chunk in result.stream_text(delta=True, debounce_by=None):
                if chunk:
                    yield str(chunk)
    except Exception as exc:
        # Re-raise with the same friendly provider wording as run_agent.
        nice = friendly_error(exc)
        raise RuntimeError(nice) from exc


def chat_complete(
    messages: list[dict],
    *,
    conn,
    model: str | None = None,
) -> str:
    """Synchronous OpenAI-compatible chat completion for simple flows.

    Talks directly to the configured base_url's ``/chat/completions`` endpoint
    via stdlib ``urllib`` — keeps this path dependency-free and avoids spinning
    up an event loop just to ask one question. Use ``run_agent`` for anything
    needing tools, streaming, or structured output.
    """
    provider, base_url, api_key, model_name = _resolve(conn, model)
    _require_key(api_key, provider)

    url = base_url.rstrip("/") + "/chat/completions"
    payload = {"model": model_name, "messages": messages}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=_request_headers(api_key, json_body=True),
    )
    try:
        with urllib.request.urlopen(req, timeout=_CHAT_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_http_error_detail(exc)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"chat_complete network error: {exc.reason}") from exc

    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"chat_complete: unexpected response shape: {data!r}") from exc


def list_models(conn) -> dict:
    """Fetch the model catalog from the configured provider's ``/models``.

    Returns a dict::

        {"ok": bool, "provider": str, "models": [
            {
                "id": str, "name": str, "free": bool, "context": int,
                "capabilities": list[str], "chat_compatible": bool,
            }
        ], "error": str | None}

    Free detection is best-effort: OpenRouter exposes ``pricing`` per model and
    we mark ``prompt == "0"`` as free; Upfyn doesn't separate free/paid yet
    so all models come back as ``free=False``. Never raises — surfaces any
    failure in the ``error`` field so the UI can render it cleanly.
    """
    provider, base_url, api_key, _ = _resolve(conn, None)
    out: dict[str, Any] = {"ok": False, "provider": provider, "models": [], "error": None}
    if not api_key:
        out["error"] = "API key not set"
        return out

    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(
        url,
        method="GET",
        headers=_request_headers(api_key),
    )
    try:
        with urllib.request.urlopen(req, timeout=_HEALTH_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        out["error"] = _http_error_detail(exc)
        return out
    except urllib.error.URLError as exc:
        out["error"] = f"network error: {exc.reason}"
        return out
    except (TimeoutError, OSError) as exc:
        out["error"] = f"connection failed: {exc}"
        return out

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        out["error"] = f"bad JSON from provider: {exc}"
        return out

    items = payload.get("data") or payload.get("models") or []
    if not isinstance(items, list):
        items = []

    models: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or item.get("name") or "").strip()
        if not mid:
            continue
        # Free detection: OpenRouter exposes pricing; Upfyn exposes either
        # ``free`` or zero credits.
        free = bool(item.get("free") is True)
        pricing = item.get("pricing")
        if isinstance(pricing, dict):
            prompt_price = str(pricing.get("prompt", "")).strip()
            if prompt_price in ("0", "0.0", "0.00", "0.000000"):
                free = True
        credits = item.get("credits_per_request")
        try:
            if credits is not None and float(credits) == 0:
                free = True
        except (TypeError, ValueError):
            pass
        # Heuristic fallback: ":free" suffix is OpenRouter's convention.
        if mid.endswith(":free"):
            free = True
        ctx = item.get("context_length") or item.get("context_window") or 0
        try:
            ctx = int(ctx)
        except (TypeError, ValueError):
            ctx = 0
        raw_caps = item.get("capabilities")
        capabilities = [
            str(c).strip().lower()
            for c in raw_caps
            if str(c).strip()
        ] if isinstance(raw_caps, list) else []
        non_chat_caps = {
            "audio-generation",
            "tts",
            "voice-generation",
            "voice-cloning",
            "image-generation",
            "video-generation",
        }
        chat_compatible = not capabilities or bool(set(capabilities) - non_chat_caps)
        max_tokens = item.get("max_tokens") or item.get("max_completion_tokens") or 0
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            max_tokens = 0
        models.append({
            "id": mid,
            "name": str(item.get("name") or mid),
            "free": bool(free),
            "context": ctx,
            "capabilities": capabilities,
            "chat_compatible": chat_compatible,
            "credits_per_request": credits,
            "max_tokens": max_tokens,
            "description": str(item.get("description") or ""),
        })

    # Free first, then alphabetical — UX hint that free models always work.
    models.sort(key=lambda m: (not m["free"], m["id"].lower()))
    out["ok"] = True
    out["models"] = models
    return out


# ---------------------------------------------------------------------------
# Friendly error translation
# ---------------------------------------------------------------------------
_FRIENDLY_ERROR_HINTS: tuple[tuple[str, str], ...] = (
    ("insufficient_quota", "Low credits on your AI provider account. Pick a free model or top up."),
    ("insufficient credit", "Low credits on your AI provider account. Pick a free model or top up."),
    ("low credits", "Low credits on your AI provider account. Pick a free model or top up."),
    ("payment required", "Payment required by the provider. Pick a free model or top up your account."),
    ("rate_limit", "Provider rate limit hit. Wait a few seconds and try again."),
    ("rate limit", "Provider rate limit hit. Wait a few seconds and try again."),
    ("model_not_found", "The selected model isn't available with this key. Try another model."),
    ("does not exist", "The selected model isn't available with this key. Try another model."),
    ("unauthorized", "Provider rejected the API key. Check it on the Settings page."),
    ("invalid_api_key", "Provider rejected the API key. Check it on the Settings page."),
)


def friendly_error(exc: BaseException | str) -> str:
    """Translate a raw provider error into a short user-facing string."""
    text = str(exc).lower()
    for needle, message in _FRIENDLY_ERROR_HINTS:
        if needle in text:
            return message
    return str(exc)


def health_check(conn) -> dict:
    """Probe the configured provider with a tiny GET ``/models`` request.

    Returns ``{ok, provider, model, error?}``. Never raises — surfaces the
    failure in the ``error`` field so the settings UI can render it cleanly.
    """
    provider, base_url, api_key, model_name = _resolve(conn, None)
    result: dict = {"ok": False, "provider": provider, "model": model_name}

    if not api_key:
        result["error"] = "API key not set"
        return result

    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(
        url,
        method="GET",
        headers=_request_headers(api_key),
    )
    try:
        with urllib.request.urlopen(req, timeout=_HEALTH_TIMEOUT_SECONDS) as resp:
            # We don't need the body — a 2xx is enough to confirm reachability
            # and a valid key. Read a small chunk to drain the socket cleanly.
            resp.read(1024)
        result["ok"] = True
        return result
    except urllib.error.HTTPError as exc:
        result["error"] = _http_error_detail(exc)
        return result
    except urllib.error.URLError as exc:
        result["error"] = f"network error: {exc.reason}"
        return result
    except (TimeoutError, OSError) as exc:
        result["error"] = f"connection failed: {exc}"
        return result
