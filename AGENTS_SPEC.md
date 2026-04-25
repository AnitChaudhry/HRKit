# AGENTS_SPEC.md — single source of truth for the Wave 1 swarm

This file is read by every Wave 1 agent. Follow the conventions exactly so all the
outputs compose without conflict in Wave 2 integration.

> **Project context.** This was a hiring kanban (`hrkit/`, Python stdlib,
> SQLite, folder-native). It is being pivoted into a full local HR app with:
>
> - **White-label brand** via env var `APP_NAME` (default `"HR Desk"`)
> - **BYOK AI** — OpenAI-compatible only — provider switch between OpenRouter
>   (`https://openrouter.ai/api/v1`) and Upfyn (`https://ai.upfyn.com/v1`)
> - **BYOK Composio** for app integrations (Gmail, etc.)
> - **In-app agent loop** via `pydantic-ai-slim[openai]` — no Claude CLI dep
> - **DB-primary** SQLite, with folders demoted to attachment storage
> - **5-step setup**: pip install → init → open settings → paste keys → use
>
> Existing files to reference (do **not** modify in Wave 1 — that's Wave 2):
> `hrkit/{cli,server,db,scanner,templates,config,frontmatter,models}.py`.

---

## 1. Module registry pattern (CRITICAL)

Every HR module file lives at `hrkit/modules/<name>.py` and exports a
single top-level `MODULE` dict:

```python
# hrkit/modules/<name>.py
from __future__ import annotations
import sqlite3
from typing import Any

NAME = "employee"          # url slug, table prefix, nav id
LABEL = "Employees"        # human-readable nav label
ICON = "users"             # short string; templates may map to emoji/svg

# ---- DB ----
def ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotent CREATE TABLE IF NOT EXISTS for this module's tables.
    Called by migration_runner during startup. Foreign keys allowed —
    only reference tables created in 001_full_hr_schema.sql."""

# ---- HTTP routes ----
# Each route handler signature: (handler, **path_params) -> None
# 'handler' is the BaseHTTPRequestHandler subclass instance from server.py
# It already provides _json(), _html(), _send(), _read_json() helpers.

def list_view(handler) -> None: ...
def detail_view(handler, item_id: int) -> None: ...
def create_api(handler) -> None: ...
def update_api(handler, item_id: int) -> None: ...
def delete_api(handler, item_id: int) -> None: ...

ROUTES = {
    "GET": [
        (r"^/m/employee/?$",          list_view),
        (r"^/m/employee/(\d+)/?$",    detail_view),
    ],
    "POST": [
        (r"^/api/m/employee/?$",          create_api),
        (r"^/api/m/employee/(\d+)/?$",    update_api),
    ],
    "DELETE": [
        (r"^/api/m/employee/(\d+)/?$",    delete_api),
    ],
}

# ---- CLI subcommands ----
# Each entry: (subcommand_name, build_parser_fn, handle_fn)
# build_parser_fn receives an argparse subparser to add args to.
# handle_fn receives the parsed argparse Namespace + a sqlite3.Connection.

def _add_create_args(p) -> None: ...
def _handle_create(args, conn) -> int: ...

CLI = [
    ("employee-add",  _add_create_args, _handle_create),
    ("employee-list", lambda p: None,   lambda a, c: 0),
]

MODULE = {
    "name": NAME,
    "label": LABEL,
    "icon": ICON,
    "ensure_schema": ensure_schema,
    "routes": ROUTES,
    "cli": CLI,
}
```

**Rules:**
- Module file must be a normal Python module — no top-level side effects.
- All module names are lower_snake_case and **unique** across the codebase.
- URL prefix is `/m/<name>` for HTML pages, `/api/m/<name>` for JSON.
- CLI subcommands are prefixed with the module name to avoid clashes.

The Wave 2 integrator iterates `hrkit.modules.__all__` (a list of module
names) and calls `register(server.Handler, module.MODULE)`. **Don't import
`server.py` from inside a module file** — that would create a circular import.

---

## 2. SQLite schema conventions

All tables created by Agent 4 in `hrkit/migrations/001_full_hr_schema.sql`:

- Primary key always `id INTEGER PRIMARY KEY`.
- Timestamps: `created TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))`,
  `updated TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','+05:30'))`.
- All money fields: `INTEGER` storing minor units (paise / cents). Never floats.
- All dates: `TEXT` in `YYYY-MM-DD`. All datetimes: `TEXT` in ISO-8601 with `+05:30`.
- All foreign keys: `... INTEGER REFERENCES other_table(id) ON DELETE SET NULL` (or `CASCADE` for child docs).
- Boolean: `INTEGER NOT NULL DEFAULT 0` (0/1), never TEXT 'true'/'false'.
- JSON blobs: `TEXT NOT NULL DEFAULT '{}'` storing valid JSON.
- Add an index on every FK column and every column the module filters by.
- All tables in this schema are **separate from** the existing `folders` and
  `activity` tables. Don't drop or alter those.

### The 13 module tables (Agent 4 must create exactly these)

```
department         id, name (UNIQUE), code, head_employee_id, parent_department_id, notes, created, updated
role               id, title, department_id, level, description, created, updated
employee           id, employee_code (UNIQUE), full_name, email (UNIQUE), phone,
                   dob, gender, marital_status, hire_date, employment_type,
                   status, department_id, role_id, manager_id, location,
                   salary_minor, photo_path, metadata_json, created, updated
document           id, employee_id (NOT NULL), doc_type, filename, file_path,
                   uploaded_at, expiry_date, notes, created
leave_type         id, name (UNIQUE), code, max_days_per_year, carry_forward, paid, created
leave_balance      id, employee_id, leave_type_id, year, allotted, used, pending,
                   UNIQUE(employee_id, leave_type_id, year)
leave_request      id, employee_id, leave_type_id, start_date, end_date, days,
                   reason, status, approver_id, applied_at, decided_at, created, updated
attendance         id, employee_id, date, check_in, check_out, hours_minor,
                   status, notes, UNIQUE(employee_id, date)
payroll_run        id, period (UNIQUE), status, processed_at, processed_by, notes, created
payslip            id, payroll_run_id, employee_id, gross_minor, deductions_minor,
                   net_minor, components_json, generated_at, file_path,
                   UNIQUE(payroll_run_id, employee_id)
performance_review id, employee_id, cycle, reviewer_id, status, score, rubric_json,
                   comments, submitted_at, created, updated
onboarding_task    id, employee_id, title, owner_id, due_date, status,
                   notes, completed_at, created, updated
exit_record        id, employee_id (UNIQUE), last_working_day, reason, exit_type,
                   notice_period_days, knowledge_transfer_status, asset_returned,
                   exit_interview_done, processed_at, created
recruitment_candidate
                   id, position_folder_id, name, email, phone, source, status,
                   score, recommendation, applied_at, evaluated_at,
                   resume_path, metadata_json, created, updated
```

`status` columns use these vocabularies (CHECK constraints):
- `employee.status`: active | on_leave | exited
- `leave_request.status`: pending | approved | rejected | cancelled
- `attendance.status`: present | absent | half_day | leave | holiday
- `payroll_run.status`: draft | processed | paid
- `performance_review.status`: draft | submitted | acknowledged
- `onboarding_task.status`: pending | in_progress | done
- `recruitment_candidate.status`: applied | screening | interview | offer | hired | rejected

Module files **must not** redeclare these tables. They use `ensure_schema()`
for module-specific helper tables only (or just `pass` if none).

---

## 3. Settings access

Settings live in three places, read in this order:

1. Environment variable
2. `settings` table in SQLite (existing `settings` k/v table — `get_setting` / `set_setting` in `db.py`)
3. Default

`hrkit/branding.py` (Agent 1) exports the canonical accessors. Other
agents must import these — do **not** read os.environ or the DB directly:

```python
from hrkit.branding import (
    app_name,                  # () -> str
    app_slug,                  # () -> str (lowercase, url-safe)
    ai_provider,               # (conn) -> "openrouter" | "upfyn"
    ai_api_key,                # (conn) -> str | ""
    ai_model,                  # (conn) -> str
    ai_base_url,               # (conn) -> str (derived from provider)
    composio_api_key,          # (conn) -> str | ""
    set_settings,              # (conn, dict) -> None
    masked,                    # (key: str) -> str  ("sk-***...last4")
)
```

Env var names (Agent 1 documents these):
`APP_NAME`, `AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL`,
`COMPOSIO_API_KEY`, `GETSET_ROOT` (existing).

Defaults:
- `APP_NAME` → `"HR Desk"`
- `AI_PROVIDER` → `"openrouter"`
- `AI_MODEL` → `"meta-llama/llama-3.3-70b-instruct:free"` (free OpenRouter model)
- All keys default to empty string.

---

## 4. AI agent contract (Agent 2 owns; Agent 6 consumes)

`hrkit/ai.py` exports exactly:

```python
async def run_agent(
    prompt: str,
    *,
    conn,                       # sqlite3.Connection (for settings)
    system: str = "",
    tools: list = None,         # list of pydantic_ai Tool / MCP server
    model: str | None = None,   # override settings
) -> str:
    """Run one agent turn. Returns the final text response."""

def chat_complete(
    messages: list[dict],
    *,
    conn,
    model: str | None = None,
) -> str:
    """Sync OpenAI-compatible chat completion. Used by simple flows."""

def health_check(conn) -> dict:
    """Returns {ok: bool, provider: str, model: str, error?: str}"""
```

The function reads provider/key/model via `branding.ai_*` helpers. Uses
`pydantic_ai.Agent` with a custom `OpenAIProvider(base_url=..., api_key=...)`.
**Do not** import `anthropic` or `claude-agent-sdk` anywhere.

---

## 5. HTTP handler helpers (already exist in server.py)

When writing module routes, assume the handler instance has these methods:

```python
handler._send(code, body_bytes, content_type)
handler._json(obj, code=200)
handler._html(code, html_str)
handler._read_json() -> dict
```

For HTML rendering, **import a small helper** that the integrator (Wave 2)
will provide in `templates.py`:

```python
from hrkit.templates import render_module_page
html = render_module_page(
    title="Employees",
    nav_active="employee",
    body_html="<table>...</table>",
)
```

For Wave 1, **assume this helper exists** — write your code that calls it.
The integrator adds it during Wave 2.

---

## 6. CRUD HTML skeleton (every module page looks the same)

To keep UIs consistent, each module's `list_view` returns:

```html
<div class="module-toolbar">
  <h1>{LABEL}</h1>
  <button onclick="openCreateForm()">+ Add {singular}</button>
  <input type="search" placeholder="Search..." oninput="filter(this.value)">
</div>
<table class="data-table">
  <thead><tr><th>...columns...</th></tr></thead>
  <tbody id="rows">...rows from DB...</tbody>
</table>
<dialog id="create-dlg">
  <form onsubmit="submitCreate(event)">
    <!-- fields -->
    <button type="submit">Save</button>
  </form>
</dialog>
<script>
  // POST /api/m/<name> for create, PUT-via-POST for update,
  // DELETE /api/m/<name>/<id> for delete
</script>
```

The integrator's CSS will style `.module-toolbar`, `.data-table`, `dialog` —
agents only need to emit semantic HTML with these class names.

---

## 7. Smoke test pattern

Each module agent writes one pytest at `tests/test_<name>.py`:

```python
import sqlite3, importlib, pytest
from hrkit.migration_runner import apply_all

@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    apply_all(c)
    yield c
    c.close()

def test_employee_create_list_delete(conn):
    mod = importlib.import_module("hrkit.modules.employee")
    # call CLI handler or direct DB helper to insert
    # assert SELECT returns the row
    # delete and assert empty
```

Each test must:
- Use `:memory:` SQLite
- Run migrations via `apply_all(conn)` (Agent 4 provides this)
- Test create + list + delete in one happy-path test
- No HTTP calls, no real AI, no real Composio

---

## 8. Code style rules

- Python 3.10+, type hints on all function signatures
- `from __future__ import annotations` at the top of every new file
- Stdlib only inside module files (`pydantic_ai` only inside `ai.py` and `evaluator.py`)
- No `print()` for debug — use logging via `import logging; log = logging.getLogger(__name__)`
- No bare `except:` — catch specific exceptions
- All file paths via `pathlib.Path`
- All datetimes IST: `from hrkit.config import IST; datetime.now(IST)`
- 4-space indent, double quotes, max line length 100

---

## 9. What each Wave 1 agent owns (no overlaps)

| Agent | New files | Modifies |
|-------|-----------|----------|
| 1 Branding | `hrkit/branding.py` | `hrkit/config.py` (add helpers) |
| 2 AI | `hrkit/ai.py`, `pyproject.toml` | none |
| 3 Composio | `hrkit/composio_client.py` | none |
| 4 Schema | `hrkit/migrations/__init__.py`, `hrkit/migrations/001_full_hr_schema.sql`, `hrkit/migration_runner.py`, `hrkit/hiring_migrator.py` | none |
| 5 Settings UI | `hrkit/settings_ui.py` | none |
| 6 Evaluator | `hrkit/evaluator.py` | none |
| 7 Employee+ | `hrkit/modules/__init__.py`, `hrkit/modules/employee.py`, `department.py`, `role.py`, `document.py`, `tests/test_employee.py`, `test_department.py`, `test_role.py`, `test_document.py` | none |
| 8 Leave | `hrkit/modules/leave.py`, `attendance.py`, tests | none |
| 9 Payroll | `hrkit/modules/payroll.py`, `performance.py`, tests | none |
| 10 Onboarding | `hrkit/modules/onboarding.py`, `exit_record.py`, tests | none |
| 11 Recruitment | `hrkit/modules/recruitment.py`, `tests/test_recruitment.py` | none |
| 12 Docs | `README.md`, `USER-MANUAL.md` | (overwrite both) |

Wave 2 (integrator) is the **only** one allowed to touch `cli.py`, `server.py`,
`db.py`, `templates.py`, `scanner.py`. Agents must NOT modify these.

`hrkit/modules/__init__.py` (created by Agent 7) must contain:
```python
__all__ = [
    "employee", "department", "role", "document",
    "leave", "attendance",
    "payroll", "performance",
    "onboarding", "exit_record",
    "recruitment",
]
```

---

## 10. Definition of done (each agent must verify before reporting)

- All listed files exist and parse (`python -c "import ast; ast.parse(open('file.py').read())"`)
- New tests pass (`pytest tests/test_<name>.py`) — if your module depends on
  Agent 4's migration runner, write the test but mark it with
  `pytest.skip("waits for Wave 2 integration")` if it fails on missing imports
- No imports from `claude_agent_sdk`, `anthropic`, `openai` (use `pydantic_ai`)
- No hardcoded brand strings — all UI titles use `branding.app_name()`
- Report: which files created, line counts, any deviation from spec, any
  blocker that needs Wave 2 to resolve
