"""In-process hook bus + Composio-backed integration handlers.

Wave 4 building blocks: a tiny pub/sub (`hooks`), three default handlers
(`composio_actions`), and a `register.register_default_hooks()` wiring fn.
"""
from __future__ import annotations

__all__ = ["hooks", "composio_actions", "register"]
