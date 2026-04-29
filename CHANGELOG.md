# Changelog

All notable changes to HR-Kit are documented here. Format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-04-30

### Added
- Full-width, full-height HR Desk shell with aligned sidebar, topbar, content
  surface, and responsive viewport behavior across Recipes, AI Chat, and module
  detail pages.
- Streaming AI Chat experience with token-by-token responses, stop control,
  queued follow-up messages, local conversation persistence, and retry-aware
  provider status.
- Right-side AI artifact viewer with automatic local saving for generated
  reports, HTML, email drafts, PDFs, and web/search notes.
- Functional chat attachments, workspace document upload previews, file viewer
  actions, local folder creation, open-file/open-folder controls, and richer
  document detail companion panels.
- Tool-level AI sandbox execution guard so local-only mode allows the provider
  request while blocking hidden outbound network calls from model-triggered
  tools and recipes.

## [1.1.1] - 2026-04-29

### Added
- Employee detail workspace controls for local HR files, HR notes, custom fields,
  reporting edits, and safer employee-folder synchronization.
- Performance dashboard date ranges and CSV exports for month-end HR reporting.
- Composio MCP sync from the Integrations page, including enabled-tool mirroring
  and chat-agent tools for search, schema lookup, execution, and connection
  management.

### Fixed
- UpfynAI model loading now sends browser-safe headers and filters voice/audio
  models out of chat-only selectors.
- Onboarding can move backward, uses the UpfynAI label consistently, and handles
  API-key/model setup more reliably.
- Project timesheet and approval UI wiring now supports HR edits without dropping
  related local data.

## [1.1.0] — 2026-04-27

Phase-2 expansion: 23 new modules covering the gaps vs Frappe HRMS, Odoo HR,
and Horilla. Feature parity now ≥ those three on every HR-shaped module that
fits the local-first / single-process moat. Architecture-level features
(mobile, LDAP/SSO, biometric, geofencing, i18n, ERPNext hook, scheduled
backups) are deferred — see `docs/ROADMAP.md`.

### Added — Tier A (16 + 2 HR-adjacent new modules)
- **Helpdesk** — employee support tickets with priority, assignee, resolution
- **Asset** — equipment register + assignment history (assign / return)
- **Skill** — skill catalog + per-employee level (beginner → expert), endorsements
- **Shift** — work shifts (timing + days) with employee assignments
- **Referral** — employee referrals + bonus tracking
- **Expense** — expense reports + reimbursement tracking, with categories
- **Survey** — pulse / feedback surveys with 5 question types, anonymous mode,
  public take-the-survey form
- **Goal** — OKR / KRA tracking with cascaded parent-goal hierarchy + progress %
- **Holiday calendar** — multi-region/department holiday calendars
- **Audit log** — read-only compliance log + `audit_log.record()` API for hooks
- **Promotion** — promotions / transfers / lateral moves with apply-to-employee
- **Self-evaluation** — employee fills own review (strengths / areas / rating)
- **Course** — eLearning catalog + per-employee enrollment + completion
- **Coaching** — 1:1 mentor/mentee sessions with agenda + action items
- **Vehicle (Fleet)** — company vehicles + employee assignment + mileage
- **Meal (Lunch)** — cafeteria menu + employee meal orders
- **Project** — projects with per-project timesheet entries (HR-adjacent)
- **Timesheet** — cross-project timesheet view + approval queue (HR-adjacent)

### Added — Tier B (payroll / approvals / exit extensions)
Tier B is **wired end-to-end** into the existing v1.0 flows. Each helper is
called automatically; the standalone CRUD pages remain for inspection /
manual override.
- **Tax slab + payroll_component.** `payroll.generate_payslips()` now looks
  up the most recent matching `tax_slab.fy_start` for the configured
  country / regime (settings keys `PAYROLL_TAX_COUNTRY` / `PAYROLL_TAX_REGIME`,
  defaults `IN` / `new`), calls `tax_slab.compute_tax_minor()` against the
  annual income, and emits one `payroll_component` row per line (basic
  earning + income tax + advance EMIs). `payslip.deductions_minor` and
  `net_minor` now reflect the computed tax.
- **Salary advance auto-deducted from payroll.** Approved or disbursed
  advances with a `repayment_schedule` of the form
  `{"emi_minor": N, "remaining_minor": M}` get one EMI deducted per
  payroll run. The schedule is updated in-place; the advance flips to
  `repaid` automatically when remaining hits zero.
- **Approval engine wired into leave / expense / salary_advance / promotion.**
  `leave.create_leave_request`, `expense.create_row` (when status is
  `submitted`), `salary_advance.create_row`, and `promotion.create_row`
  all call `approval.request_approvals()` to seed the cross-module queue
  using `approval.default_approver_chain(employee_id)` — direct manager
  → optional `HR_APPROVER_ID` setting. When the bespoke status field on
  any of these flips to approved/rejected, `approval.reflect_request_outcome()`
  mirrors that onto the pending approval rows. The `/m/approval` queue
  thus shows everything in one place, while the per-module pages still
  work as before.
- **Exit auto-computes F&F.** `exit_record.create_row()` now runs
  `f_and_f.calculate_fnf()` automatically using the employee's hire date,
  current salary, accrued leave (summed across `leave_balance` for the
  exit year), and Indian-default gratuity formula (≥ 5 years tenure). The
  breakdown is written into `exit_record.f_and_f_breakdown_json` /
  `gratuity_minor` / `f_and_f_amount_minor` / `f_and_f_settled_at`. The
  manual `/m/f_and_f/<id>` page still works for adjustments.
- `payroll_run.is_off_cycle` + `run_type` columns added (manual flagging
  via the existing payroll API today; UI toggle deferred).
- `payroll_component` rows are now populated by every payslip generation,
  giving downstream reporting tools a normalized per-line breakdown
  (groupable by component name and type).

### Added — Tier C (Composio integrations)
- **e-Sign** — signature requests via Composio (DocuSign / HelloSign / Dropbox
  Sign) or manual mode
- New Composio handlers: `create_calendar_event_for_onboarding`,
  `create_calendar_event_for_coaching`, `send_signature_request`
- New event hooks: `onboarding.task_created`, `coaching.session_scheduled`,
  `e_sign.request_created`

### Schema
- Migration `002_phase2_modules.sql`: 26 new tables + 6 ALTER TABLE columns
  on existing tables. Idempotent — safe to re-apply on existing v1.0 DBs.

### Roadmap (deferred)
- See `docs/ROADMAP.md` for mobile, LDAP/SSO, biometric, geofencing, i18n,
  ERPNext, scheduled backups — and why each is deferred rather than built.

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
