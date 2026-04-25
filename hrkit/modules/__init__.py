"""HR module registry.

Each entry in ``__all__`` corresponds to a sibling ``<name>.py`` module that
exports a top-level ``MODULE`` dict (see AGENTS_SPEC.md, Section 1). The Wave
2 integrator iterates this list to register routes and CLI subcommands.

Module files in this package are deliberately stdlib-only so they can be
imported without optional dependencies (``pydantic_ai`` etc.) being present.
"""

from __future__ import annotations

__all__ = [
    "employee", "department", "role", "document",
    "leave", "attendance",
    "payroll", "performance",
    "onboarding", "exit_record",
    "recruitment",
]
