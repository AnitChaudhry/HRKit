"""HR module registry.

Each entry in ``__all__`` corresponds to a sibling ``<name>.py`` module that
exports a top-level ``MODULE`` dict (see AGENTS_SPEC.md, Section 1). The Wave
2 integrator iterates this list to register routes and CLI subcommands.

Module files in this package are deliberately stdlib-only so they can be
imported without optional dependencies (``pydantic_ai`` etc.) being present.
"""

from __future__ import annotations

__all__ = [
    # ----- Core (always-on) -----
    "department", "employee", "role",
    # ----- v1.0 modules -----
    "document",
    "leave", "attendance",
    "payroll", "performance",
    "onboarding", "exit_record",
    "recruitment",
    # ----- v1.1 Tier A: new HR modules -----
    "helpdesk",          # Employee support tickets
    "asset",             # Asset register + assignment history
    "skill",             # Skill catalog + employee_skill map
    "shift",             # Work shifts + employee assignments
    "referral",          # Employee referrals + bonuses
    "expense",           # Expense reports + reimbursements
    "survey",            # Pulse / feedback surveys
    "goal",              # OKR / KRA / objective tracking
    "holiday_calendar",  # Multi-region holiday calendars
    "audit_log",         # Compliance audit log
    "promotion",         # Promotions / transfers / lateral moves
    "self_evaluation",   # Employee self-review
    "course",            # eLearning / training catalog
    "coaching",          # 1:1 mentor / mentee sessions
    "vehicle",           # Fleet management
    "meal",              # Cafeteria / meal orders
    "project",           # Projects + per-project timesheet
    "timesheet",         # Cross-project timesheet view + approvals
    # ----- v1.1 Tier B: payroll / approval extensions -----
    "salary_advance",    # Salary advance requests
    "approval",          # Generic multi-level approval engine
    "tax_slab",          # Income-tax brackets
    "f_and_f",           # Full-and-final settlement (gratuity, leave encash, ...)
    # ----- v1.1 Tier C: integrations -----
    "e_sign",            # e-Signature requests via Composio / DocuSign
    # ----- v1.1 Data tools -----
    "csv_import",        # Upload CSV → queryable imported_* table for AI analysis
    "csv_export",        # Export any module / imported table as CSV
]
