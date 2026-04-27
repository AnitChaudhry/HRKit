# Quickstart

Ten minutes from `pip install` to a populated HR system you can browse.

> Heads-up: HR-Kit has **no hosted demo URL**.
> `http://127.0.0.1:8765/` only works on **your** machine, while
> `hrkit serve` is running. Closing the terminal stops the app.

## 1. Install

(See [INSTALL.md](INSTALL.md) if you want all three options.)

```bash
pip install hrkit
```

## 2. Create a workspace

A workspace is one folder on your laptop where the company's HR data lives.

```bash
hrkit init "D:\My-HR"      # Windows
hrkit init ~/my-hr         # mac / Linux
```

This creates the folder, a `hrkit.md` workspace marker, and a hidden
`.hrkit/` subdirectory for the SQLite database and config.

## 3. Start the server

```bash
cd "D:\My-HR"
hrkit serve
```

A few things happen:

1. The server starts on `http://127.0.0.1:8765/`.
2. Your default browser opens to it automatically.
3. Because the workspace is empty, you're redirected to `/setup` — the
   four-step first-run wizard.

Keep this terminal open. Closing it stops the app.

## 4. The first-run wizard

Four short steps:

1. **App name** — what the UI title bar will read. Defaults to "HR Desk"
   but you can name it anything ("Acme HR", "ThinqMesh People", etc.).
   This is the white-label name; the CLI binary stays `hrkit`.
2. **AI provider + key** — pick **OpenRouter** (free models available) or
   **Upfyn**, paste the key. **Skippable** if you don't want AI yet.
3. **First department** — e.g., "Engineering". You can skip and add later.
4. **First employee** — minimum: code (e.g., `EMP-001`), full name, email.
   Optionally tick **Load sample data** to populate the app with 8
   employees, 3 candidates, leave / payroll / onboarding seeds in mixed
   states. Strongly recommended for the first-time tour.

Click **Finish**. You land on `/m/employee` — the employee list.

## 5. Take the tour

The top nav has the main routes. Click around:

| Route | What it does |
|---|---|
| `/m/employee` | Employee directory + per-person folder structure |
| `/m/department` | Org chart |
| `/m/role` | Job titles per department |
| `/m/document` | Per-employee paperwork (PAN, contracts, etc.) |
| `/m/leave` | Leave types, balances, requests |
| `/m/recruitment` | Candidate list |
| `/m/recruitment/board` | **Drag-drop kanban** for the hiring pipeline |
| `/m/payroll` | Payroll runs + payslips |
| `/chat` | AI assistant — ask "list all engineers" or "who is on leave next week" |
| `/integrations` | Connect Composio apps (Gmail, Drive, Slack, …) |
| `/recipes` | User-defined HR automations the AI can run |
| `/settings` | API keys, white-label name |

## 6. (Optional) Connect an integration

If you pasted a Composio key in the wizard:

1. Go to `/integrations`.
2. Click **Show / hide** under "Available to connect" → click **Connect** on Gmail.
3. A dialog shows a Composio-hosted OAuth URL — click it. Composio handles
   the callback; your local server doesn't need a public URL.
4. Come back to `/integrations` and click **Refresh**. Gmail now shows
   under "Connected" with a list of toggleable actions.
5. Now go to `/m/recruitment` → click **Pull from Gmail** → unread emails
   become candidate rows + saved as paired `.md` + `.json` files under
   `<workspace>/integrations/gmail/messages/<id>.{md,json}`.

See [INTEGRATIONS.md](INTEGRATIONS.md) for the full flow.

## 7. (Optional) Talk to the AI about an employee

Click any employee. Scroll down to the **HR notes** section, type
something:

```
Strong performer Q3 2026. Hit 110% of OKRs. Promotable next cycle.
```

Click **Save notes**. (This writes to
`<workspace>/employees/<EMP-CODE>/memory/notes.md` on disk — you can
hand-edit that file in any editor.)

Now go to `/chat`. In the sidebar's **Talking about** dropdown, pick that
employee. Ask:

```
Should we promote them this cycle?
```

The AI's answer factors in their full record + your notes + recent
leave/documents. Conversation gets saved under
`<workspace>/employees/<EMP-CODE>/conversations/<date>-<slug>.{md,json}`
— the sidebar lets you resume any prior chat.

See [AI-CHAT.md](AI-CHAT.md) for the full feature set.

## 8. Stop the app

`Ctrl+C` in the terminal. The browser tab will start showing
"connection refused" — that's expected. Restart anytime with `hrkit serve`
in the workspace folder.

## What's on disk after step 7?

```
D:\My-HR\
├── hrkit.md                          # workspace marker
├── .hrkit\
│   ├── hrkit.db                      # SQLite — every structured record
│   └── uploads\                       # legacy upload location
├── employees\
│   └── EMP-001\
│       ├── employee.md                # frontmatter mirror of the DB row
│       ├── documents\                 # uploaded paperwork
│       ├── legal\                     # contracts, NDAs
│       ├── conversations\             # AI chats scoped to this person
│       └── memory\notes.md            # your free-form HR notes
├── conversations\                     # global chats (no employee context)
├── integrations\
│   └── gmail\messages\                # mirrored emails (.md + .json)
└── recipes\                           # user-defined automations
```

Open the folder in Explorer/Finder. Everything's a real file. Edit, grep,
git-add, share — it's just yours.
