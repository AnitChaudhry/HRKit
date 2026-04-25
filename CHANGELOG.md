# Changelog

All notable changes to HR-Kit are documented here. Format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Initial release.** Local, white-label HR app — Python 3.10+ with one
  dependency (`pydantic-ai-slim[openai]`).
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
