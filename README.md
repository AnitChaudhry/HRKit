# Your HR App

A folder + DB-backed local HR app that runs entirely on the HR person's
laptop. No servers to operate, no Docker, no cloud account to sign up for.
One Python process, one SQLite file, one workspace folder, and you own
all of it.

**Pick the modules you actually need.** A first-run wizard (or the Modules
card on `/settings`) lets you enable or disable each HR feature
independently — Departments, Employees and Roles are always on; everything
else (Leave, Payroll, Recruitment, …) is opt-in. Disabled modules
disappear from the top navigation, the CLI subcommands, and the AI
assistant's tool list, so the app shows only what your team uses.

The app is **white-label**: you set its name with the `APP_NAME` env var
or in `/settings` (default: `HR Desk`). Throughout this README we refer
to it as `${APP_NAME}` or simply "your HR app".

> If `APP_NAME=Acme HR`, the browser title, top nav header, page titles,
> and CLI banner all read **Acme HR**. Replace any mention of
> `${APP_NAME}` below with whatever you've named yours.

---

## What it gives you

A complete HR desk for a small or mid-sized company, all running locally:

| Module        | Covers                                                                 |
|---------------|------------------------------------------------------------------------|
| Employees     | Master record, codes, contact info, salary, manager chain, photo      |
| Departments   | Org tree with heads and parent departments                            |
| Roles         | Job titles + levels per department                                    |
| Documents     | Per-employee documents (ID proofs, contracts, certificates)           |
| Leave         | Leave types, balances per year, requests + approvals                  |
| Attendance    | Daily check-in / check-out, hours, leave / holiday status             |
| Payroll       | Periodic payroll runs and per-employee payslips                       |
| Performance   | Review cycles, rubric scoring, comments, status tracking              |
| Onboarding    | Joiner checklist with tasks, owners, due dates                        |
| Exits         | Exit records, knowledge transfer, asset return, exit interview        |
| Recruitment   | Kanban for candidates with AI-assisted scoring (the original board)   |

Each module gets its own page under `/m/<module>` and CRUD JSON API at
`/api/m/<module>`. Same look across the app, same keyboard flow.

---

## How it's built

- **Stack**: Python 3.10+, SQLite, a tiny stdlib HTTP server, plain HTML/CSS/JS.
- **Single dependency**: [`pydantic-ai-slim[openai]`](https://ai.pydantic.dev/)
  for the in-app AI agent loop. No Claude CLI, no `anthropic` SDK, no Node.
- **DB-primary**: all module data lives in `<workspace>/.hrkit/hrkit.db`.
  Folders inside the workspace are demoted to **attachment storage** for
  things like resumes, signed contracts, and PDF payslips.
- **One unified shell**: every page (home, modules, recruitment kanban,
  org chart, settings, activity) uses the same top navigation. No more
  split between the legacy hiring view and the HR desk view.
- **Module-level feature flags**: enabled modules live in
  `.hrkit/config.json` mirrored to a `settings` table row, with
  `ENABLED_MODULES` env var as the override. Reads filter through every
  layer — UI nav, HTTP dispatcher, CLI subcommands, AI tool registry —
  so a disabled module is invisible everywhere.
- **Localhost-only HTTP**: the server binds to `127.0.0.1` by default. You
  can opt into `--host 0.0.0.0` for LAN access; there is no auth, so only
  do that on a trusted network.
- **No background workers, no message queues, no Redis.** One process. Ctrl+C
  to stop.

---

## Install

Three equivalent paths — pick whichever ecosystem you live in.

| Channel | Command | When to use |
|---|---|---|
| **PyPI** | `pip install hrkit` | You have Python 3.10+ already; you want the smallest footprint |
| **npm** | `npx @thinqmesh/hrkit serve` | You're a Node user; the wrapper transparently runs `pip install hrkit` for you on first use |
| **GitHub Release** | download wheel/sdist from [v1.0.0](https://github.com/AnitChaudhry/HRKit/releases/tag/v1.0.0) and `pip install ./hrkit-*.whl` | Air-gapped machine, or you want a frozen version pinned to disk |

### From PyPI (recommended for Python users)

```bash
pip install hrkit
```

The package is published at <https://pypi.org/project/hrkit/>. After install,
the `hrkit` CLI is on your `$PATH`.

### From npm (recommended for non-Python users)

```bash
# Run with npx (no global install — auto-installs the Python package on first run)
npx @thinqmesh/hrkit serve

# Or install the wrapper globally
npm install -g @thinqmesh/hrkit
hrkit serve
```

The npm package [`@thinqmesh/hrkit`](https://www.npmjs.com/package/@thinqmesh/hrkit)
is a tiny Node.js shim (under 200 lines) that detects Python ≥ 3.10 on your
machine, `pip install`s the actual app from PyPI on first run, and forwards
every command to the underlying Python CLI. You still need Python installed;
the shim just hides `pip` from view.

### From a GitHub Release (offline / pinned)

```bash
# Pick the asset URL from https://github.com/AnitChaudhry/HRKit/releases
pip install https://github.com/AnitChaudhry/HRKit/releases/download/v1.0.0/hrkit-1.0.0-py3-none-any.whl
```

> **Need more detail?** [`docs/INSTALL.md`](docs/INSTALL.md) covers
> prerequisites, upgrade paths, and troubleshooting. The whole docs
> tree is at [`docs/`](docs/) — Quickstart, AI chat, integrations,
> recipes, releasing.

## Three-step setup (the promise)

```bash
# 1. install (pick one of the install commands above)

# 2. cd into the folder you want HR-Kit to live in, then start it
cd "D:\My-HR" && hrkit serve
#    First run auto-creates `hrkit.md` + `.hrkit/` in this folder.
#    No separate `hrkit init` step needed — running the server in an
#    empty folder is enough. All workspace data (DB, config, uploads)
#    stays inside that folder.

# 3. on first run the browser opens a 5-step wizard:
#    - app name (white-label)
#    - AI provider + key + model (paste, click Connect, pick a free model)
#    - choose your modules (presets: Everything / Core only / Recruitment-focused / HR-focused)
#    - first department
#    - first employee
#    Every step except modules selection can be edited later in /settings.
```

That is the whole onboarding. No `.env` files to learn, no docker-compose,
no migrations to run by hand (the app runs them on first boot), no
separate workspace-init step. Closing the terminal stops the server —
there is no hosted SaaS version, every install runs on the user's own
laptop on `127.0.0.1`.

> **About installation scope.** `pip install hrkit` puts the *Python
> package* in your usual site-packages (that is how pip works). All
> *workspace data* — database, config, uploads, attachments — lives
> inside whichever folder you ran `hrkit serve` in. Pick one folder,
> back up that folder, you've backed up everything.

> **About `http://127.0.0.1:8765/`:** that is the address your own laptop
> serves the app on after step 3. It is unreachable from anywhere else,
> and it stops working the moment you close the terminal. There is no
> hosted SaaS version of HR-Kit — running the app on your own machine
> is the entire product.

> **Footnote on the binary name.** The console script installed by `pip
> install` is named `hrkit` (lowercase). The npm wrapper exposes the same
> name. The product brand "HR-Kit" appears only in marketing/docs — the UI
> label in the app itself is whatever you set with the `APP_NAME` env var.

---

## Modules — pick what you actually use

Every install enables all 11 modules by default, but most teams turn off
the ones they don't need. The module selector is on `/settings` and
follows three rules:

1. **Always-on core**: `Departments`, `Employees`, `Roles`. Every other
   HR table foreign-keys to `employee.id`, so these can't be turned off.
2. **HR modules**: `Documents`, `Leave`, `Attendance`, `Payroll`,
   `Performance`, `Onboarding`, `Exits`. Each is independent — disable
   any combination.
3. **Hiring**: `Recruitment` (candidate kanban + AI scoring + Gmail
   intake). Independent of everything else.

The setup wizard offers four presets to bootstrap quickly:

- **Everything** — all 11 modules on (default)
- **Core only** — Departments + Employees + Roles, nothing else
- **Recruitment-focused** — core + Recruitment, no HR ops
- **HR-focused** — everything except Recruitment

State lives in `<workspace>/.hrkit/config.json` (`enabled_modules` key)
mirrored to the SQLite `settings` table. The env var
`ENABLED_MODULES=leave,payroll,...` overrides both for one-shot testing.

When a module is disabled:

- It disappears from the top navigation
- `/m/<slug>...` URLs return 404
- CLI subcommands (`hrkit payroll-run`, `hrkit leave-request-add`, …)
  refuse to run with a clear "module is disabled" message
- The AI chat assistant's tool registry filters them out, so the LLM
  doesn't propose actions the app won't carry out

Re-enabling preserves data — disabling only hides routes and tools, it
never deletes rows.

## Org structure & reporting

Every employee has an optional `manager_id` field pointing at another
employee. The reporting structure surfaces in three places:

- The employee detail page shows **Reports to** (their manager, linked)
  and **Direct reports** (a table of everyone reporting to them)
- An inline **Reassign manager** dropdown auto-excludes the employee
  themselves and all their descendants, so a cycle is unreachable from
  the UI. The API enforces the same rule (`update_row` raises if
  `manager_id` would create a loop)
- `/m/employee/tree` renders the full org chart as nested collapsible
  cards, rooted at top-level managers (anyone whose `manager_id IS NULL`)

Roles use the standard HR ladder as suggestions in their level field:
Intern → Junior → Senior → Team Lead → Assistant Manager → Manager →
Senior Manager → Director → VP. Pick from the dropdown or type a
custom value.

## AI providers (BYOK, OpenAI-compatible only)

The app talks to any **OpenAI-compatible** chat completion endpoint. Two
are pre-wired in the settings page:

| Provider     | Base URL                            | Notes                                          |
|--------------|-------------------------------------|------------------------------------------------|
| OpenRouter   | `https://openrouter.ai/api/v1`      | Free tier available; many open-weight models   |
| Upfyn        | `https://ai.upfyn.com/v1`           | Drop-in OpenAI-compatible gateway              |

Switch providers from `/settings`. Default model is a free OpenRouter
Llama-3.3-70B-Instruct entry; override per request from the UI or via
the `AI_MODEL` env var.

You can also point at your own self-hosted OpenAI-compatible server by
overriding `AI_PROVIDER` and the base URL in `.hrkit/config.json`.

### Composio for app integrations

[Composio](https://composio.dev/) is used as the integrations backbone
(Gmail in particular, for the recruitment intake flow). Bring your own
Composio API key, paste it into `/settings`, and connect Gmail from the
Composio dashboard linked from the page.

If you don't paste a Composio key, the rest of the HR app still works -
only the recruitment-from-email pipeline goes idle.

---

## Configuration surface

Every setting can be supplied two ways: an environment variable or the
in-app `/settings` page (which writes to `.hrkit/config.json` inside
your workspace). Env vars win on conflict.

| Env var             | Default                                            | Where it goes                       |
|---------------------|----------------------------------------------------|-------------------------------------|
| `APP_NAME`          | `HR Desk`                                          | UI title, top-nav header, CLI banner|
| `AI_PROVIDER`       | `openrouter`                                       | `openrouter` or `upfyn`             |
| `AI_API_KEY`        | (empty)                                            | OpenAI-compatible API key           |
| `AI_MODEL`          | `meta-llama/llama-3.3-70b-instruct:free`           | Model identifier                    |
| `COMPOSIO_API_KEY`  | (empty)                                            | Composio API key                    |
| `ENABLED_MODULES`   | (all 11 enabled)                                   | Comma list or JSON, overrides config + DB |
| `HRKIT_ROOT`       | (auto-detected)                                    | Workspace folder path               |

### Where keys live

- The `/settings` page writes to `<workspace>/.hrkit/config.json`.
- That file lives **only on the user's laptop**. It is never uploaded.
- Keys are masked when shown back in the UI (`sk-***...last4`).
- Add `.hrkit/` to your global `.gitignore` if you ever put a workspace
  in a git repo - the cache and config should not be committed.

### Workspace layout

```
D:\My-HR\
|-- hrkit.md                    workspace marker (name, theme, port)
|-- .hrkit\
|   |-- hrkit.db                SQLite, all modules
|   `-- config.json              keys + per-workspace settings
|-- attachments\
|   |-- employees\<code>\        per-employee documents
|   |-- payslips\<period>\       generated PDFs
|   |-- resumes\<position>\      candidate resumes
|   `-- contracts\               signed contracts, NDAs
`-- ...departments and recruitment positions as folders...
```

The recruitment kanban still uses real folders (Department / Position /
Candidate) for backwards compatibility with the original tool. On first
boot the migrator copies anything it finds into the DB; from then on the
DB is primary and the folder tree is just for human filing.

---

## CLI cheat sheet

```bash
<app> init "D:\My-HR"                    # scaffold a new workspace
<app> serve                              # start the local server
<app> serve --port 9000 --no-browser     # custom port, headless
<app> scan                               # rebuild the cache from disk
<app> migrate                            # apply DB migrations
<app> migrate --dry-run                  # preview migrations
<app> status                             # workspace path, DB stats
<app> activity                           # last 20 activity rows
<app> --version
```

Each module also adds its own subcommands (e.g. `employee-add`,
`leave-grant`, `payroll-run`). Run `<app> --help` for the full list on
your install.

---

## Security notes

- The HTTP server binds to `127.0.0.1` by default. **No authentication is
  enforced** - it assumes the only thing on `localhost:8765` is you.
- Don't expose the port to the public internet. If you must reach it
  remotely, put it behind an SSH tunnel or a reverse proxy that does auth.
- AI keys are stored as cleartext inside `.hrkit/config.json` on the
  user's machine. Encrypt the laptop disk; that is the boundary.
- Composio handles its own OAuth tokens for connected apps - those are
  not stored locally; only your Composio API key is.
- All data is local. There is no telemetry. There is no phoning home.

---

## Roadmap

- Multi-user mode (currently single-user-per-laptop)
- Pluggable auth for the localhost UI
- Importers for common HRMS exports (BambooHR, Zoho, Keka)
- Native installers (`.exe`, `.dmg`, `.AppImage`) so no `pip` step

---

## License & Trademark

HR-Kit is **dual-licensed**:

- **AGPL-3.0** ([LICENSE](LICENSE)) for everyone. Free for personal,
  internal, and commercial use as long as you comply with copyleft —
  if you modify the source or host HR-Kit as a public service, you must
  publish your source under AGPL too. Cloning and extending is encouraged;
  forks must stay open and credit upstream.
- **Commercial license** ([COMMERCIAL.md](COMMERCIAL.md)) — buy this if you
  want to embed HR-Kit in a closed-source product, run a SaaS without
  publishing source, or rebrand HR-Kit for resale. Contact Anit Chaudhary to
  start a conversation.

**"HR-Kit" is a trademark of Anit Chaudhary.** The AGPL covers the *code*; the
trademark policy in [TRADEMARK.md](TRADEMARK.md) covers the *name*. You may
not rebrand a derivative work as HR-Kit, register a confusingly-similar
name, or use the HR-Kit logo on your own product without prior written
permission. (Honest references — "compatible with HR-Kit", "fork of HR-Kit"
— are always fine.)

> **Already on v1.0.0 (MIT)?** That release stays MIT — the relicense applies
> only to v1.1.0 and later. Anyone who downloaded the MIT tarballs keeps
> those rights forever.

Copyright © 2026 **Anit Chaudhary**. All rights reserved where not
explicitly granted by AGPL or the commercial license.

---

## Credits

Built on the shoulders of the Python standard library, SQLite, and
[`pydantic-ai`](https://ai.pydantic.dev/). The original recruitment
kanban (folder-native) lives on inside this app as the Recruitment
module.
