# Architecture

A 5-minute tour of how HR-Kit is wired internally. Read this before submitting
non-trivial PRs or extending the system.

## Top-level

```
┌─────────────────────────────────────────────────────────────────┐
│  HR person's laptop                                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  python -m hrkit serve   (one process, no Docker)       │    │
│  │  ─────────────────────────────────────────────────────  │    │
│  │   ┌──────────────┐  ┌──────────────┐  ┌─────────────┐   │    │
│  │   │  HTTP server │  │  Module      │  │  AI agent   │   │    │
│  │   │  (stdlib)    │  │  registry    │  │  (PydanticAI│   │    │
│  │   │              │  │  (11 mods)   │  │   slim)     │   │    │
│  │   └──────┬───────┘  └──────┬───────┘  └──────┬──────┘   │    │
│  │          │                 │                 │          │    │
│  │   ┌──────┴─────────────────┴─────────────────┴──────┐   │    │
│  │   │            SQLite (.hrkit/hrkit.db)            │   │    │
│  │   │  source of truth — 14 HR tables + activity log   │   │    │
│  │   └─────────────────────┬────────────────────────────┘   │    │
│  │                         │                                │    │
│  │   ┌─────────────────────┴────────────────────────────┐   │    │
│  │   │  Folders (.hrkit/uploads/employee/<id>/...)     │   │    │
│  │   │  attachments only — resumes, contracts, payslips │   │    │
│  │   └──────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  Browser → http://127.0.0.1:8765/                               │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │  BYOK (user pastes their own keys)
                            ▼
        ┌───────────────────────────────────────────┐
        │  External — only if configured            │
        │  ┌─────────────┐    ┌─────────────────┐   │
        │  │ AI provider │    │ Composio        │   │
        │  │ (OpenRouter │    │ (Gmail / Drive  │   │
        │  │  or Upfyn)  │    │  / Calendar)    │   │
        │  └─────────────┘    └─────────────────┘   │
        └───────────────────────────────────────────┘
```

Everything below the dashed line is opt-in. The app is fully usable with
**zero external services configured** — you just don't get AI or Composio
features.

## Request lifecycle

A `GET /m/employee/1` request flows through:

1. `hrkit/server.py:do_GET` matches the URL.
2. Module registry dispatch finds `employee.detail_view` registered for
   `^/m/employee/(\d+)/?$` (registered at startup from `MODULE['routes']`).
3. `detail_view(handler, item_id=1)` reads `handler.server.conn` (the shared
   SQLite connection) and calls `get_row(conn, 1)`.
4. The row is rendered via `templates.render_detail_page(...)` which wraps
   the field grid in `templates.render_module_page(...)` which provides the
   shared top nav.
5. HTML response sent back via `handler._html(200, html)`.

## The module registry

The single most important convention. Every file in `hrkit/modules/` exports
a top-level `MODULE` dict:

```python
MODULE = {
    "name":  "employee",
    "label": "Employees",
    "icon":  "users",
    "ensure_schema": ensure_schema,    # idempotent CREATE TABLE IF NOT EXISTS
    "routes": {
        "GET":    [(regex, handler), ...],
        "POST":   [(regex, handler), ...],
        "DELETE": [(regex, handler), ...],
    },
    "cli": [(name, build_parser_fn, handle_fn), ...],
}
```

`server.py:_register_modules()` loops over `hrkit.modules.__all__` and
populates the global `MODULE_ROUTES` dict at startup. `cli.py` does the same
for subcommands.

This is what makes new modules a drop-in: add a file, add to `__all__`, done.

## Settings resolution

Three layers, read in this order:

1. **Environment variable** (e.g. `APP_NAME=Acme HR`)
2. **`settings` table** in SQLite (set via `/settings` page or `hrkit settings` CLI)
3. **Default** (e.g. `"HR Desk"` for app name)

All accessors live in `hrkit/branding.py`. Other code MUST go through these
helpers — never read `os.environ` or query the `settings` table directly.

## Migrations

`hrkit/migrations/*.sql` files are applied in lexicographic order by
`migration_runner.apply_all(conn)`. Applied versions are recorded in the
`schema_migrations` table, so re-running is a no-op.

`db.open_db()` calls `apply_all()` on every connection open. Safe and fast.

## Integration hooks

`hrkit/integrations/hooks.py` is a tiny in-process pub/sub. Modules emit
events at meaningful moments:

```python
hooks.emit("recruitment.hired", {...payload...}, conn=conn)
```

Default handlers (`hrkit/integrations/composio_actions.py`) wrap Composio
calls. They no-op gracefully if the user hasn't pasted a Composio key, so
hooks are always safe to call.

`register_default_hooks()` is called once during `server.run()`.

## AI agent

`hrkit/ai.py` exposes one function: `run_agent(prompt, *, conn, tools=...)`.
It builds a `pydantic_ai.Agent` whose model is an `OpenAIChatModel` pointed
at the user's chosen `base_url` (OpenRouter or Upfyn).

`hrkit/chat.py` registers a single `query_records(module, op, args)` tool
that dispatches to all 11 modules — this is how the chat UI gets full HR
data access without registering 44 individual tools.

## File-format constants

Three names exist for backward compatibility with workspaces created before
the rename to `hrkit`:

- `META_DIR = ".hrkit"` (workspace metadata directory)
- `MARKER = "hrkit.md"` (workspace/department/position marker file)
- `DB_NAME = "hrkit.db"` (SQLite filename)
- `HRKIT_ROOT` env var (workspace root override)

These are file-format identifiers, NOT brand. Don't rename them — it would
break existing user data.

## Where to look when

| Question | File |
|---|---|
| How do I add a route? | `hrkit/modules/<name>.py` — append to `ROUTES` |
| How do I add a CLI command? | Same file — append to `CLI` |
| Where do I add a new HR table? | `hrkit/migrations/00N_*.sql` |
| How does the AI agent work? | `hrkit/ai.py` + `hrkit/chat.py` |
| How does Composio dispatch? | `hrkit/composio_client.py` + `hrkit/integrations/` |
| Where is the brand resolved? | `hrkit/branding.py` |
| Where do file uploads land? | `hrkit/uploads.py` → `<workspace>/.hrkit/uploads/employee/<id>/` |
