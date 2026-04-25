# Contributing to HR-Kit

Thanks for your interest in HR-Kit! This guide covers everything you need to
contribute code, docs, or bug reports.

## Quick start (development)

```bash
git clone https://github.com/<your-fork>/hrkit.git
cd hrkit
pip install -e ".[dev]"
python -m pytest tests/ -q
```

You should see `72 passed`. If anything fails, that's a bug — please open an
issue with the failure output.

## Project layout

```
hrkit/                    Python package (the app)
  modules/                One file per HR module (employee, leave, payroll, ...)
  migrations/             SQL migrations applied at startup
  integrations/           Composio hooks (Gmail / Calendar / Drive)
tests/                    Pytest suite — one file per module
website/                  Marketing landing page (React + Vite)
docs/                     Architecture and developer reference
.github/                  CI workflows + issue/PR templates
```

## Conventions

- **Stdlib only** inside `hrkit/modules/` and `hrkit/integrations/hooks.py`.
  The single accepted dependency is `pydantic-ai-slim[openai]` (used only by
  `hrkit/ai.py` and `hrkit/evaluator.py`).
- **DB-primary**: SQLite is the source of truth. Folders are attachment storage.
- **White-label**: never hardcode brand strings in Python. Use
  `branding.app_name()`. The OSS project name "HR-Kit" appears only in
  marketing/docs/license, never in the runtime UI.
- **Stay BYOK**: AI keys, Composio keys, etc. are user-provided. Never bake
  any vendor's key into the package.
- **Module registry pattern**: every HR module file exports a `MODULE` dict
  (see `AGENTS_SPEC.md` Section 1). Don't bypass it — the server and CLI
  iterate this dict.

## Adding a new HR module

1. Add a new SQL file under `hrkit/migrations/` (e.g. `002_my_module.sql`).
   The migration runner picks it up automatically on next startup.
2. Create `hrkit/modules/my_module.py` exporting `MODULE = {...}`.
3. Add `"my_module"` to `hrkit/modules/__init__.py:__all__`.
4. Add the module slug to `MODULE_NAV` in `hrkit/templates.py`.
5. Write `tests/test_my_module.py` — at least one happy-path CRUD test.
6. Run `pytest -q` — all existing tests must still pass.

## Code style

- Python 3.10+, type hints on public functions.
- `from __future__ import annotations` at the top of every new file.
- 4-space indent, double quotes, max line length 100.
- No `print()` for debug — use `logging`.
- No bare `except:` — catch specific exceptions.
- All datetimes IST: `from hrkit.config import IST; datetime.now(IST)`.

## Submitting changes

1. Open an issue describing the change first (unless it's a typo or trivial fix).
2. Fork, create a branch, commit with a clear message.
3. Run `python -m pytest tests/ -q` locally — all tests must pass.
4. Open a PR. CI will run the suite on Linux/Mac/Windows × Python 3.10/3.11/3.12.
5. A maintainer will review within a few days.

## Reporting bugs

Use the bug report template (`.github/ISSUE_TEMPLATE/bug_report.md`). Include:
- Python version (`python --version`)
- OS
- The exact command you ran
- Full traceback
- A minimal reproduction if possible

## Code of conduct

By participating, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).
TL;DR: be respectful, assume good faith, no harassment.

## License

By contributing, you agree your contributions will be licensed under the
[MIT License](LICENSE).
