"""BYOK Composio v1 REST client.

A small stdlib-only wrapper around the Composio v1 REST API. The user's API
key is read from settings via ``branding.composio_api_key`` and sent in the
``X-API-Key`` header. No third-party Composio SDK is required — this keeps
the runtime footprint minimal and avoids a hard dependency.

Reference: https://backend.composio.dev/api/v1
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from hrkit.branding import composio_api_key

log = logging.getLogger(__name__)

BASE_URL = "https://backend.composio.dev/api/v1"
DEFAULT_TIMEOUT = 10  # seconds


class ComposioError(Exception):
    """Raised for non-2xx responses or transport-level failures."""

    def __init__(self, message: str, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _api_key(conn) -> str:
    key = composio_api_key(conn)
    if not key:
        raise ComposioError("Composio API key is not configured", status=None)
    return key


def _request(
    conn,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    """Perform a single HTTP request to the Composio API.

    Returns the parsed JSON body on success. Raises ``ComposioError`` for any
    non-2xx response or transport failure.
    """
    key = _api_key(conn)

    url = f"{BASE_URL}{path}"
    if params:
        # Drop None-valued params so callers can pass optionals freely.
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url = f"{url}?{urllib.parse.urlencode(clean)}"

    data: bytes | None = None
    headers = {
        "X-API-Key": key,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read()
        except Exception:  # noqa: BLE001 - best-effort read of error body
            pass
        text = raw.decode("utf-8", errors="replace")
        raise ComposioError(
            f"Composio HTTP {e.code} for {method} {path}: {text[:300]}",
            status=e.code,
            body=text,
        ) from e
    except urllib.error.URLError as e:
        raise ComposioError(
            f"Composio transport error for {method} {path}: {e.reason}",
            status=None,
        ) from e
    except TimeoutError as e:
        raise ComposioError(
            f"Composio request timed out for {method} {path}",
            status=None,
        ) from e

    if not (200 <= status < 300):
        text = raw.decode("utf-8", errors="replace")
        raise ComposioError(
            f"Composio HTTP {status} for {method} {path}: {text[:300]}",
            status=status,
            body=text,
        )

    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ComposioError(
            f"Composio returned non-JSON body for {method} {path}",
            status=status,
            body=raw.decode("utf-8", errors="replace"),
        ) from e


def _as_list(payload: Any) -> list[dict]:
    """Normalize Composio list responses.

    Composio sometimes returns a bare JSON array and sometimes wraps it in
    ``{"items": [...]}`` or similar. Be lenient and always return a list.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "connectedAccounts", "apps"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_configured(conn) -> bool:
    """Return True if a Composio API key is present in settings."""
    try:
        return bool(composio_api_key(conn))
    except Exception:  # noqa: BLE001 - settings access must never crash callers
        log.exception("composio.is_configured: failed to read API key")
        return False


def list_apps(conn) -> list[dict]:
    """List apps known to Composio (Gmail, Slack, ...)."""
    payload = _request(conn, "GET", "/apps")
    return _as_list(payload)


def list_connections(conn) -> list[dict]:
    """List the user's connected accounts."""
    payload = _request(conn, "GET", "/connectedAccounts")
    return _as_list(payload)


def init_connection(
    conn,
    app_slug: str,
    redirect_uri: str | None = None,
) -> dict:
    """Initiate an OAuth/connection flow for ``app_slug``.

    Returns a dict with at least ``redirect_url`` and ``connected_account_id``
    keys. Both keys are normalized from common Composio response shapes so
    callers don't have to special-case casings.
    """
    body: dict[str, Any] = {"appName": app_slug}
    if redirect_uri:
        body["redirectUri"] = redirect_uri

    payload = _request(conn, "POST", "/connectedAccounts/initiate", body=body)
    if not isinstance(payload, dict):
        raise ComposioError(
            "Composio init_connection: unexpected response shape",
            status=None,
        )

    redirect_url = (
        payload.get("redirect_url")
        or payload.get("redirectUrl")
        or payload.get("redirectURL")
        or ""
    )
    connected_account_id = (
        payload.get("connected_account_id")
        or payload.get("connectedAccountId")
        or payload.get("id")
        or ""
    )
    return {
        "redirect_url": redirect_url,
        "connected_account_id": connected_account_id,
        "raw": payload,
    }


def get_connection(conn, connected_account_id: str) -> dict:
    """Fetch a single connected-account record by id."""
    if not connected_account_id:
        raise ComposioError("connected_account_id is required", status=None)
    safe_id = urllib.parse.quote(connected_account_id, safe="")
    payload = _request(conn, "GET", f"/connectedAccounts/{safe_id}")
    return payload if isinstance(payload, dict) else {"raw": payload}


def execute_action(
    conn,
    action_slug: str,
    params: dict,
    connected_account_id: str | None = None,
) -> dict:
    """Execute a Composio action for the given connected account."""
    if not action_slug:
        raise ComposioError("action_slug is required", status=None)
    body: dict[str, Any] = {"input": params or {}}
    if connected_account_id:
        body["connectedAccountId"] = connected_account_id
    safe_slug = urllib.parse.quote(action_slug, safe="")
    payload = _request(conn, "POST", f"/actions/{safe_slug}/execute", body=body)
    return payload if isinstance(payload, dict) else {"raw": payload}


def health_check(conn) -> dict:
    """Lightweight readiness probe for the settings UI.

    Never raises — always returns a dict with ``ok`` and ``configured`` keys.
    When configured, performs a minimal ``GET /apps`` to validate the key.
    """
    configured = is_configured(conn)
    if not configured:
        return {"ok": False, "configured": False}
    try:
        _request(conn, "GET", "/apps")
        return {"ok": True, "configured": True}
    except ComposioError as e:
        return {
            "ok": False,
            "configured": True,
            "error": str(e),
            "status": e.status,
        }
    except Exception as e:  # noqa: BLE001 - health_check must never crash
        log.exception("composio.health_check: unexpected error")
        return {"ok": False, "configured": True, "error": str(e)}
