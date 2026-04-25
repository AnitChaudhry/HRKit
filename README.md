# Your HR App

A folder + DB-backed local HR app that runs entirely on the HR person's
laptop. No servers to operate, no Docker, no cloud account to sign up for.
One Python process, one SQLite file, one workspace folder, and you own
all of it.

The app is **white-label**: you set its name with the `APP_NAME` env var
(default: `HR Desk`). Throughout this README we refer to it as
`${APP_NAME}` or simply "your HR app".

> If `APP_NAME=Acme HR`, the browser title, sidebar header, page titles,
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
- **DB-primary**: all module data lives in `<workspace>/.getset/getset.db`.
  Folders inside the workspace are demoted to **attachment storage** for
  things like resumes, signed contracts, and PDF payslips.
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
| **GitHub Release** | download wheel/sdist from [v0.2.1](https://github.com/AnitChaudhry/HRKit/releases/tag/v0.2.1) and `pip install ./hrkit-*.whl` | Air-gapped machine, or you want a frozen version pinned to disk |

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
pip install https://github.com/AnitChaudhry/HRKit/releases/download/v0.2.1/hrkit-0.2.1-py3-none-any.whl
```

> **Need more detail?** [`docs/INSTALL.md`](docs/INSTALL.md) covers
> prerequisites, upgrade paths, and troubleshooting. The whole docs
> tree is at [`docs/`](docs/) — Quickstart, AI chat, integrations,
> recipes, releasing.

## Five-step setup (the promise)

```bash
# 1. install (pick one of the install commands above)

# 2. initialise a workspace folder
hrkit init "D:\My-HR"                    # creates the folder + .getset/ + workspace marker

# 3. start the server (this also opens your browser automatically)
cd "D:\My-HR" && hrkit serve

# 4. once step 3 is running, open http://127.0.0.1:8765/settings in your browser
#    (this URL is YOUR machine — it only works while `hrkit serve` is running.
#     it is NOT a hosted demo. closing the terminal stops the server.)
#    paste your AI key (OpenRouter or Upfyn) and your Composio key

# 5. start using it — add your first employee, department, leave type
```

That is the whole onboarding. Five steps, no `.env` files to learn, no
docker-compose, no migrations to run by hand (the app runs them on first
boot).

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
overriding `AI_PROVIDER` and the base URL in `.getset/config.json`.

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
in-app `/settings` page (which writes to `.getset/config.json` inside
your workspace). Env vars win on conflict.

| Env var             | Default                                            | Where it goes                       |
|---------------------|----------------------------------------------------|-------------------------------------|
| `APP_NAME`          | `HR Desk`                                          | UI title, sidebar header, CLI banner|
| `AI_PROVIDER`       | `openrouter`                                       | `openrouter` or `upfyn`             |
| `AI_API_KEY`        | (empty)                                            | OpenAI-compatible API key           |
| `AI_MODEL`          | `meta-llama/llama-3.3-70b-instruct:free`           | Model identifier                    |
| `COMPOSIO_API_KEY`  | (empty)                                            | Composio API key                    |
| `GETSET_ROOT`       | (auto-detected)                                    | Workspace folder path               |

### Where keys live

- The `/settings` page writes to `<workspace>/.getset/config.json`.
- That file lives **only on the user's laptop**. It is never uploaded.
- Keys are masked when shown back in the UI (`sk-***...last4`).
- Add `.getset/` to your global `.gitignore` if you ever put a workspace
  in a git repo - the cache and config should not be committed.

### Workspace layout

```
D:\My-HR\
|-- getset.md                    workspace marker (name, theme, port)
|-- .getset\
|   |-- getset.db                SQLite, all modules
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
- AI keys are stored as cleartext inside `.getset/config.json` on the
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

## License

MIT. See `pyproject.toml` for the canonical license declaration. You may
fork, rebrand, and redistribute under your own `APP_NAME`.

---

## Credits

Built on the shoulders of the Python standard library, SQLite, and
[`pydantic-ai`](https://ai.pydantic.dev/). The original recruitment
kanban (folder-native) lives on inside this app as the Recruitment
module.
