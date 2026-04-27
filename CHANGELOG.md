# Changelog

All notable changes to HR-Kit are documented here. Format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-04-26

First stable release. Two big shifts since 0.2.1:

1. **Modules are now opt-in.** A first-run wizard step + a Modules card on
   `/settings` let the user enable or disable each HR feature. Disabled
   modules disappear from the navigation, the HTTP dispatcher (404s),
   the CLI subcommands, and the AI assistant's tool registry. Always-on
   core: `department`, `employee`, `role`. Everything else is the user's
   choice. State lives in `.hrkit/config.json` mirrored to the SQLite
   `settings` table; `ENABLED_MODULES` env var overrides both.
2. **Single unified shell.** The legacy folder-tree sidebar (rendered for
   `/`, `/activity`, and the kanban-era `/d/`, `/p/`, `/t/` URLs) is gone.
   Every page now uses the same top-nav module-page chrome, so the app no
   longer feels like two products stitched together.

### Added
- `hrkit/feature_flags.py` — central reader/writer for `enabled_modules`
  with always-on rules (`department`, `employee`, `role`), dependency
  validation (`MODULE_REQUIRES`), and config.json + DB mirror.
- Wizard step 3 (modules) with four presets: Everything, Core only,
  Recruitment-focused, HR-focused. Skip = all-on (legacy behavior).
- Settings UI: new "Modules" card with checkbox grid, category badges,
  always-on core greyed out, dependency hints inline.
- Employee detail page now shows **Reports to** (manager linked) and a
  **Reporting structure** section with: a manager-reassignment dropdown
  (auto-excludes self + descendants for unreachable cycles), a "View org
  chart" link, and a **Direct reports** table.
- New `/m/employee/tree` route — collapsible nested-card org chart rooted
  at top-level managers. Orphans (employees pointing at a deleted
  manager) surface in a separate "Reports to a deleted employee" group.
- Roles use a standard HR ladder dropdown (Intern, Junior, Senior, Team
  Lead, Assistant Manager, Manager, Senior Manager, Director, VP) via
  HTML5 `<datalist>`. Free text still accepted for backward compat with
  legacy `IC1`/`IC2`-style entries.
- Cycle prevention: `update_row` raises `ValueError` when an attempted
  `manager_id` change would create a reporting loop, in addition to the
  UI-level filtering.
- Home page (`/`) is a real dashboard now — hero banner with workspace
  name, stat cards keyed by enabled modules (Employees, Departments,
  Roles, Pending leave, Candidates), quick-action row, and a per-module
  card grid.
- `/api/settings/modules` POST endpoint for toggling enabled modules
  without going through the wizard.

### Changed
- `branding.app_name()` now resolves through env → `config.json` → live
  DB connection → default. Previously only checked the env var, so the
  wizard's app-name save never reached page renders. Fixed.
- `branding.set_settings()` mirrors `APP_NAME` to `config.json` so
  stateless renderers see the right brand.
- CLI subcommands belonging to disabled modules now refuse to run with a
  clear `module 'X' is disabled in this workspace` message instead of
  silently mutating data or crashing.
- AI chat's `_allowed_modules()` and `_dispatch()` filter through
  `feature_flags`, so the LLM's system prompt and tool docstring only
  list enabled modules. Dispatch to a disabled module returns a clear
  error string the LLM can read.
- Wizard renumbered: 1 app name → 2 AI key → 3 modules → 4 department →
  5 employee. Existing tests adjusted in lockstep.

### Removed
- `templates._page_shell`, `_sidebar`, `_render_tree`, `_render_tree_nodes`,
  `_node_href`, `_footer`, `_stats_chips`, `_meta_summary`,
  `_inline_tree_from_depts`, `_root_name_from_tree`, `_render_task_card`.
- `templates.render_landing`, `render_department`, `render_position`,
  `render_task`, and the old `render_activity` (replaced by
  `render_home_page` + `render_activity_page`).
- The 468-line legacy `CSS` constant (only used by the deleted shell).
- `templates._score_band`, `_priority_class` — both unreferenced.
- `server._serve_department`, `_serve_position`, `_serve_task`,
  `_build_tree`, and the `/api/tree` route — only consumed by the
  retired sidebar.
- Net `templates.py` shrunk from ~2,565 to ~1,352 lines (~47% smaller).

### Tests
- 181 passing (was 179 in 0.2.1; 2 new wizard step-3 tests added, 4
  existing tests updated for the renumbered wizard steps).

## [0.2.1]

### Added
- **Initial public release.** Local, white-label HR app — Python 3.10+
  with one dependency (`pydantic-ai-slim[openai]`).
- **11 HR modules**: employee, department, role, document, leave, attendance,
  payroll, performance, onboarding, exit_record, recruitment.
- **DB-primary SQLite** with idempotent migrations applied at startup; legacy
  folder-native hiring data auto-imported into the new schema.
- **HTML detail pages** for every module with field grid, related records,
  inline Edit dialog, and Delete button. JSON variant preserved at
  `/api/m/<module>/<id>`.
- **Drag-and-drop kanban** at `/m/recruitment/board` (6 status columns).
  Legacy `/d/<id>`, `/p/<id>`, `/t/<id>` URLs redirect here.
- **AI chat** at `/chat` — PydanticAI agent with all 11 modules exposed via a
  single `query_records(module, op, args)` tool.
- **BYOK Composio integrations** with hook system. Wired events:
  `recruitment.hired` → Gmail offer letter, `leave.approved` → Calendar block,
  `payroll.payslip_generated` → Drive upload. All gracefully no-op without keys.
- **Multipart file upload** at `/api/m/document/upload` (25 MB cap, path
  traversal protection); download at `/api/m/document/<id>/download`.
- **First-run wizard** at `/setup` — 4 steps: name app → paste AI key → first
  department → first employee. Fresh workspaces auto-redirect from `/`.
- **White-label brand** via `APP_NAME` env var; defaults to "HR Desk". Server
  banner, page titles, sidebar, footer, chat heading, and wizard all use it.
- **Settings page** at `/settings` for BYOK Composio + AI provider/key. Test
  buttons probe both backends. Keys masked in UI.
- **Two AI providers** out of the box: OpenRouter (free models available) and
  Upfyn (`ai.upfyn.com`). Same OpenAI-compatible client, swap `base_url`.
- **72 tests** passing in <0.5s.
