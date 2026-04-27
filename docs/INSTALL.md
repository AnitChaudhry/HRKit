# Install

HR-Kit ships from three channels — pick whichever fits your workflow. All
three install the same Python package; `npx` just hides `pip` from view.

## Prerequisites

| | Required | Why |
|---|---|---|
| **Python** | 3.10, 3.11, 3.12, or 3.13 | The app itself |
| **A modern browser** | Chrome / Edge / Firefox / Safari | The UI |
| **Node.js ≥ 18** | only for the npm wrapper | Hides `pip` for Node-native users |
| **OpenRouter / Upfyn API key** | optional | Powers the AI chat assistant. App works without one. |
| **Composio API key** | optional | Powers Gmail / Drive / Slack integrations. App works without one. |

Everything else (database, web server, queue) is bundled — no Docker, no
MariaDB, no Redis, no Nginx.

## A. From PyPI (recommended for Python users)

```bash
pip install hrkit
```

Package page: <https://pypi.org/project/hrkit/>

This installs the `hrkit` console script and pulls two transitive
dependencies (`pydantic-ai-slim[openai]` and `composio`).

Verify:

```bash
hrkit --version
```

## B. From npm (recommended for Node users)

```bash
# Run with npx — no global install needed
npx @thinqmesh/hrkit serve

# Or install globally so you can just type "hrkit"
npm install -g @thinqmesh/hrkit
hrkit serve
```

Package page: <https://www.npmjs.com/package/@thinqmesh/hrkit>

The npm package is a tiny (~7 KB) Node.js shim. On first run it:

1. Detects a Python ≥ 3.10 interpreter on your `$PATH` (or honours `HRKIT_PYTHON`).
2. Checks whether the `hrkit` Python package is present.
3. If not, runs `pip install hrkit` from PyPI.
4. Forwards your CLI args to `python -m hrkit <args>`.

You still need Python on the machine — the wrapper just removes the
"please install Python deps yourself" friction for Node-native users.

### Wrapper environment variables

| Variable | Default | Purpose |
|---|---|---|
| `HRKIT_PYTHON` | auto-detected | Force a specific Python interpreter |
| `HRKIT_INSTALL_SOURCE` | `pypi` | `pypi` (default) installs `hrkit` from PyPI; `git` installs from the GitHub `main` branch — useful for testing unreleased features |
| `HRKIT_PIP_NAME` | `hrkit` | Override the PyPI distribution name (rare) |
| `HRKIT_GIT_URL` | `git+https://github.com/AnitChaudhry/HRKit.git` | Override the GitHub install URL (only used when `HRKIT_INSTALL_SOURCE=git`) |

## C. From a GitHub Release (offline / pinned)

For air-gapped machines, or when you want a version frozen on disk:

1. Open <https://github.com/AnitChaudhry/HRKit/releases/latest>.
2. Download the `.whl` (or `.tar.gz` if you're building from source).
3. Install:

```bash
pip install ./hrkit-0.2.1-py3-none-any.whl
```

Or, in one shot:

```bash
pip install https://github.com/AnitChaudhry/HRKit/releases/download/v0.2.1/hrkit-0.2.1-py3-none-any.whl
```

## Upgrading

```bash
pip install --upgrade hrkit                  # PyPI
npm install -g @thinqmesh/hrkit@latest       # npm (global)
```

If you installed via `npx`, just rerun `npx @thinqmesh/hrkit serve` — npx
re-fetches the latest version each time unless you pin it.

## Uninstalling

```bash
pip uninstall hrkit                          # PyPI
npm uninstall -g @thinqmesh/hrkit            # npm (global)
```

Your workspace folder (everything under `<workspace>/.hrkit/`,
`<workspace>/employees/`, `<workspace>/conversations/`, etc.) is
**untouched** by uninstalling — your data stays put on disk.

## Troubleshooting

### "No Python 3.10+ interpreter found"

Install Python from <https://python.org/downloads/>. On Windows, tick
"Add Python to PATH" during install. After install, verify:

```bash
python --version       # should print 3.10.x or higher
```

If you have multiple Pythons, point the npm wrapper at the right one:

```bash
HRKIT_PYTHON=/path/to/python3.12 npx @thinqmesh/hrkit serve
```

### "pip install exited with code N"

Run the printed `pip install` command yourself to see the full error.
Usually it's:

* a network/proxy issue → try `pip install --index-url https://pypi.org/simple/ hrkit`
* a missing build toolchain (Windows users sometimes need [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/))

### "Port 8765 is already in use"

Another `hrkit serve` is running, or some other app grabbed the port. Pick
a different port:

```bash
hrkit serve --port 9000
```

### "hrkit: command not found"

`pip install --user` sometimes installs into a directory not on your
`$PATH`. Run:

```bash
python -m site --user-site
```

…and ensure the parent of that directory's `Scripts/` (Windows) or
`bin/` (mac/Linux) is on your `$PATH`. Or just run:

```bash
python -m hrkit serve
```

…which works regardless of `$PATH`.

## Next

You have HR-Kit installed. Now [open the Quickstart](QUICKSTART.md) for
the first 10 minutes.
