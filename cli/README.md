# @thinqmesh/hrkit

> npx wrapper for **HR-Kit** — a local, white-label, AI-augmented HR app
> in one Python package. This npm package shells out to `python -m hrkit`
> so users who only know npm can install and run HR-Kit without touching
> pip directly.

[![npm](https://img.shields.io/npm/v/@thinqmesh/hrkit?color=000)](https://www.npmjs.com/package/@thinqmesh/hrkit)
[![License: MIT](https://img.shields.io/badge/License-MIT-000.svg)](https://github.com/AnitChaudhry/HRKit/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/AnitChaudhry/HRKit?color=000)](https://github.com/AnitChaudhry/HRKit)

## What HR-Kit is

A complete HR application that runs entirely on the HR person's laptop.
Eleven modules (employees, departments, roles, documents, leave, attendance,
payroll, performance, onboarding, exits, recruitment), one SQLite file, one
Python process. AI assistant via your own OpenRouter or Upfyn key.
Composio integrations for Gmail / Calendar / Drive. No SaaS, no per-seat
fees, no vendor lock-in. **MIT licensed.**

The full repo, source, and Python README live at
**[github.com/AnitChaudhry/HRKit](https://github.com/AnitChaudhry/HRKit)**.

## Quick start

```bash
# Run with npx (recommended — no global install)
npx @thinqmesh/hrkit serve

# Or install globally
npm install -g @thinqmesh/hrkit
hrkit serve
```

That's it. The wrapper will:

1. Detect a Python 3.10+ interpreter on your system.
2. Check whether the `hrkit` Python package is installed.
3. If not, run `pip install hrkit` from PyPI (override the source with
   `HRKIT_INSTALL_SOURCE=git` if you want the GitHub `main` branch instead).
4. Forward your command to `python -m hrkit <args>`.

When `npx @thinqmesh/hrkit` is run with **no arguments**, it defaults to
`serve` — the same as `python -m hrkit serve`.

## Available commands

Anything the underlying Python `hrkit` CLI accepts. The most common ones:

| Command | What it does |
| --- | --- |
| `npx @thinqmesh/hrkit serve` | Start the app on **your own machine** at `http://127.0.0.1:8765/`. Browser opens automatically. The URL is local-only and stops working when you close the terminal. |
| `npx @thinqmesh/hrkit init <dir>` | Scaffold a new HR workspace folder |
| `npx @thinqmesh/hrkit settings` | Show or set BYOK API keys (AI provider, Composio) |
| `npx @thinqmesh/hrkit migrate` | Apply pending DB migrations to the workspace |
| `npx @thinqmesh/hrkit status` | Print workspace + database health |
| `npx @thinqmesh/hrkit activity` | Tail the workspace activity log |
| `npx @thinqmesh/hrkit --help` | Show all subcommands (delegates to the Python CLI) |

> **There is no hosted version of HR-Kit.** `http://127.0.0.1:8765/` is
> served by the `hrkit serve` process running on your own machine. It is
> unreachable from the public internet and dies the moment you stop the
> command.

Each HR module also adds its own subcommands (e.g. `employee-add`,
`leave-approve`, `payroll-run-create`). Run with `--help` to see them.

## Configuration

White-label your app instance via environment variables:

```bash
APP_NAME="Acme HR"            # title shown everywhere in the UI
AI_PROVIDER="openrouter"      # or "upfyn"
AI_API_KEY="sk-..."           # your provider key
COMPOSIO_API_KEY="..."        # for Gmail/Calendar/Drive integrations
```

You can also set these later via the in-app `/settings` page.

### Wrapper-specific env vars

These tune how this npm wrapper bootstraps Python:

| Variable | Default | Purpose |
| --- | --- | --- |
| `HRKIT_PYTHON` | (auto-detected) | Absolute path to a specific Python interpreter to use |
| `HRKIT_INSTALL_SOURCE` | `pypi` | Where to install from. `pypi` = `pip install hrkit` (default); `git` = `pip install` from the GitHub `main` branch (useful for testing unreleased features) |
| `HRKIT_PIP_NAME` | `hrkit` | Override the PyPI distribution name |
| `HRKIT_GIT_URL` | `git+https://github.com/AnitChaudhry/HRKit.git` | Override the GitHub install URL |

## Requirements

- **Node.js ≥ 18** (for this wrapper)
- **Python ≥ 3.10** with `pip` available
- A modern web browser (Chrome / Edge / Firefox / Safari)

That's it. No Docker, no databases to provision, no Redis.

## How it works

This wrapper is intentionally tiny — under 200 lines of Node.js.
On invocation it:

1. Looks for `python3` / `python` / `py -3` (Windows) until it finds a
   working interpreter ≥ 3.10. Honors `HRKIT_PYTHON` if set.
2. Runs `python -c "import hrkit"` to check whether the Python package is
   present.
3. If missing, prompts for confirmation and runs
   `python -m pip install --user <source>`.
4. Spawns `python -m hrkit <your args>` with `stdio: 'inherit'` so you see
   the Python app's output directly.

The actual app, all the data, and all the logic live in the Python package
at [github.com/AnitChaudhry/HRKit](https://github.com/AnitChaudhry/HRKit).
This package is just the install ergonomics for npm-native users.

## Troubleshooting

**"No Python 3.10+ interpreter found"** — Install Python from
<https://python.org/downloads/>. On Windows, choose the "Add to PATH" option
during install, or use `HRKIT_PYTHON=C:\path\to\python.exe`.

**"pip install exited with code N"** — Run the printed command yourself to
see the full error. Most often it's a network issue or a missing build
toolchain (the Python deps for `pydantic-ai-slim[openai]`).

**"hrkit installed but still not importable"** — `pip install --user`
sometimes installs into a directory that isn't on the active Python's
`sys.path`. Try `python -m site --user-site` to see where, and ensure that
matches the Python the wrapper picked up.

## License

[MIT](./LICENSE) © HR-Kit contributors

## Links

- Source code: <https://github.com/AnitChaudhry/HRKit>
- Issues: <https://github.com/AnitChaudhry/HRKit/issues>
- User manual: <https://github.com/AnitChaudhry/HRKit/blob/main/USER-MANUAL.md>
- Architecture: <https://github.com/AnitChaudhry/HRKit/blob/main/docs/ARCHITECTURE.md>
