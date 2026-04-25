# hrkit

**Version:** 0.1.0
**Stack:** Python 3 stdlib only (no external dependencies)

hrkit is a folder-native project management app. Your project structure
lives on disk as real folders in a fixed three-level hierarchy, and each folder
is described by a tiny `getset.md` marker file. A SQLite cache is rebuilt by
scanning, and a small HTTP server renders a board UI over it.

```
Workspace/
|-- getset.md                    <- type: workspace
|-- Engineering/                 <- Department
|   |-- getset.md                <- type: department
|   |-- Senior-Backend/          <- Position (job requisition, etc.)
|   |   |-- getset.md            <- type: position
|   |   |-- Alice-Kumar/         <- Task (a candidate, a unit of work)
|   |   |   `-- getset.md        <- type: task
|   |   `-- Bob-Rao/
|   |       `-- getset.md
|-- Marketing/
|   `-- getset.md
```

Three levels: **Department -> Position -> Task**, all under a single
**Workspace** root. The filesystem is the source of truth. Everything else
(the SQLite cache, the HTML board) is regenerated from these files.

## The `getset.md` marker

Every folder in the hierarchy carries a `getset.md` with YAML frontmatter that
identifies its type and holds its metadata. Freeform markdown after the
frontmatter is preserved as the folder's body / notes.

### Workspace

```markdown
---
type: workspace
name: "Acme Hiring"
theme: dark
port: 8765
---
# Acme Hiring
```

### Department

```markdown
---
type: department
name: "Engineering"
description: "All engineering hiring"
---
```

### Position

```markdown
---
type: position
name: "Senior Backend Engineer"
role: "Backend, Python, distributed systems"
columns: [applied, screening, interview, offer, closed]
statuses: [applied, screening, interview, offer, hired, rejected]
---
```

### Task

```markdown
---
type: task
name: "Alice Kumar"
status: screening
priority: medium
tags: [python, remote]
created: "2026-04-24T10:00:00+05:30"
---
# Alice Kumar

Resume link, notes, interview feedback, etc.
```

## How to start

> The app runs **on your own machine**. `http://127.0.0.1:8765/` is the
> local address the server binds to once started; it is not a hosted demo
> and stops working as soon as you stop the server.

**Windows one-click:** double-click `start-hrkit.bat` in the workspace root.
It starts the local server on `http://127.0.0.1:8765/` and opens your
browser to it. Keep the console window open — closing it stops the app.

**Scan from a shortcut:** double-click `scan-hrkit.bat` to rebuild the cache.

**From a shell (any OS):**

```
python -m hrkit serve
python -m hrkit scan
```

Both will auto-discover the nearest workspace by walking up from the current
directory looking for a `getset.md` with `type: workspace`. Override with
`--path <dir>` or the `GETSET_ROOT` environment variable.

## CLI reference

```
hrkit serve                             # start server on 127.0.0.1:8765
hrkit serve --port 9000 --no-browser    # custom port, headless
hrkit scan                              # rescan the current workspace
hrkit scan --path D:\Acme-Hiring     # scan a specific root
hrkit init D:\My-Project                # scaffold a new workspace
hrkit init D:\X\MyDept --type department --name "My Department"
hrkit init D:\X\Dept\MyRole --type position --name "My Role"
hrkit init D:\X\Dept\Role\Task1 --type task --name "Task 1" --status applied
hrkit migrate                           # run migrations on current workspace
hrkit migrate --dry-run
hrkit status                            # workspace root, DB path, stats
hrkit activity                          # last 20 activity entries
hrkit --version
```

All commands accept `--path <dir>` to target a specific workspace instead of
relying on auto-discovery.

## The SQLite cache

The database lives at `<workspace>/.getset/getset.db`. It is **a cache, not a
source of truth.** You can delete the entire `.getset/` folder at any time;
the next `hrkit scan` will rebuild it from the `getset.md` files on
disk. Activity history is cached there too, so deleting it will drop the
change log — everything else rematerializes.

Schema (simplified):

- `folders` — one row per node (workspace / department / position / task)
- `activity` — append-only change log
- `watches` — external folders being tracked
- `settings` — key/value store

## Adding things manually

You do not need the CLI to grow the board. Just make the folder and drop in a
`getset.md`:

```
mkdir D:\Acme-Hiring\Engineering\Senior-Backend\Charlie-Singh
notepad D:\Acme-Hiring\Engineering\Senior-Backend\Charlie-Singh\getset.md
```

Paste the task frontmatter shown above, save, and run `hrkit scan`.
The new task appears on the board. Move the folder to a different position,
rescan — it moves on the board too. Rename the folder — same deal.

## How AI agents drive the board

Because the board is literally a tree of text files, any LLM or agent with
filesystem access can run it. Claude, Cursor, etc. can:

- create a new candidate folder and write its `getset.md`
- update a task's `status:` field to move it across columns
- append notes to the body of a `getset.md` after an interview
- rename a folder to reflect a candidate's legal name
- archive a task by setting `status: rejected` or moving the folder out

After any batch of edits, run `python -m hrkit scan` (or hit the scan
button in the UI) and everything is picked up. There's no API to learn — if
your agent can write a markdown file, it can run the board.

## Troubleshooting

- **`no workspace found`** — you're not inside a workspace. Either `cd` into
  one or pass `--path`. Run `hrkit init <dir>` to create a new one.
- **Port already in use** — `hrkit serve --port 9000`.
- **Weird state** — delete `<workspace>/.getset/` and rescan.

## License

Internal tooling. See the top-level repo for details.
