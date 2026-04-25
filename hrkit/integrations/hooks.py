"""Tiny in-process pub/sub for HR domain events.

Module files (recruitment, leave, payroll, ...) call :func:`emit` with a
domain event name and a payload; registered handlers are invoked in
registration order. Errors raised by individual handlers are caught and
returned as ``{'ok': False, 'error': str(exc)}`` so that one bad handler
cannot break the others or the calling business flow.

No persistence, no retries, no async — this is intentionally the smallest
possible building block. Stdlib only.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

Handler = Callable[..., dict]

# event_name -> list of registered handlers (insertion order preserved)
_REGISTRY: dict[str, list[Handler]] = {}


def on(event_name: str, handler: Handler) -> None:
    """Register ``handler`` to be invoked when ``event_name`` is emitted.

    Handlers are called as ``handler(payload, conn=conn)`` and must return
    a dict. If the same handler is registered twice for the same event it
    will be called twice on emit — callers are responsible for de-duping.
    """
    if not event_name or not isinstance(event_name, str):
        raise ValueError("event_name must be a non-empty string")
    if not callable(handler):
        raise TypeError("handler must be callable")
    _REGISTRY.setdefault(event_name, []).append(handler)


def emit(event_name: str, payload: dict, *, conn: Any) -> list[dict]:
    """Invoke every handler registered for ``event_name``.

    Returns a list of result dicts in handler-call order. If a handler
    raises, the exception is caught and the slot is filled with
    ``{'ok': False, 'error': str(exc)}``. If no handlers are registered
    the returned list is empty.
    """
    handlers = list(_REGISTRY.get(event_name, ()))
    results: list[dict] = []
    for handler in handlers:
        try:
            result = handler(payload, conn=conn)
        except Exception as exc:  # noqa: BLE001 - one bad hook must not kill the rest
            log.exception("hook %s raised", event_name)
            results.append({"ok": False, "error": str(exc)})
            continue
        if not isinstance(result, dict):
            results.append(
                {"ok": False, "error": f"handler returned {type(result).__name__}, not dict"}
            )
            continue
        results.append(result)
    return results


def clear(event_name: str | None = None) -> None:
    """Remove handlers — for the named event or all events. Test helper."""
    if event_name is None:
        _REGISTRY.clear()
        return
    _REGISTRY.pop(event_name, None)


def registered(event_name: str) -> list[Handler]:
    """Return a shallow copy of handlers registered for ``event_name``."""
    return list(_REGISTRY.get(event_name, ()))
