# Your HR App - User Manual

A practical, end-to-end guide for the HR practitioner who installed this
on their own laptop and wants to actually run their HR week with it.

This app is **white-label**. We refer to it throughout as `${APP_NAME}` -
substitute whatever name you set in `APP_NAME` (default `HR Desk`).
Wherever this manual writes `<app>` for a CLI command, use the binary
your install produced (currently `hrkit`).

---

## 1. First-run setup (5 steps)

### Step 1 - Install Python and the app

You need Python 3.10 or later. Verify:

```bash
python --version
```

Install your HR app from PyPI (or the wheel your IT desk hands you):

```bash
pip install your-hr-app
```

The install registers a single console script - call it `<app>` from any
shell. The only Python dependency added is `pydantic-ai-slim[openai]`.

### Step 2 - Create a workspace folder

Pick a folder on your laptop where the company's HR data will live. This
becomes the **workspace**.

```bash
<app> init "D:\My-HR"
```

That command creates the folder, a `getset.md` marker (workspace metadata),
and an empty `.getset/` subdirectory for the database and config.

### Step 3 - Start the server

```bash
cd "D:\My-HR"
<app> serve
```

The server starts on `http://127.0.0.1:8765/` and your default browser opens
to it. Leave that terminal running; close the browser tab whenever you like
- the server keeps going. Press **Ctrl+C** in the terminal to stop.

If port 8765 is busy, use `<app> serve --port 9000`.

### Step 4 - Open `/settings` and paste your keys

Click the gear icon in the sidebar, or go directly to
`http://127.0.0.1:8765/settings`. Paste:

- **AI API key** - from OpenRouter (`https://openrouter.ai/keys`) or Upfyn
  (`https://ai.upfyn.com`). Pick the matching provider in the dropdown.
- **AI model** - leave the default (`meta-llama/llama-3.3-70b-instruct:free`)
  or pick something heavier. Any OpenAI-compatible chat model works.
- **Composio API key** - from `https://app.composio.dev/`. Optional, only
  needed for Gmail-driven recruitment.
- **App name** - whatever you want this install branded as.

Click **Save**. Click **Test connection** next to each section to confirm
the keys actually authenticate.

### Step 5 - Start using it

You're done. From the home page:

1. Add a department (`/m/department`).
2. Add a role inside it (`/m/role`).
3. Add your first employee (`/m/employee`).
4. Add a leave type (`/m/leave`) - e.g. "Casual" with 12 days/year.

You're now ready for daily HR work.

---

## 2. The `/settings` page tour

```
+---------------------------------------------------------------+
|  ${APP_NAME} settings                                          |
+---------------------------------------------------------------+
|                                                                |
|  Branding                                                      |
|    App name:        [ Acme HR              ]                   |
|    Theme:           ( ) light  ( ) dark   ( ) auto             |
|                                                                |
|  AI provider                                                   |
|    Provider:        [v] OpenRouter | Upfyn                     |
|    API key:         [ sk-***...a1b2 ] [Reveal] [Replace]       |
|    Model:           [ meta-llama/llama-3.3-70b-instruct:free ] |
|    [Test connection]                                           |
|                                                                |
|  Composio                                                      |
|    API key:         [ comp-***...x7y8 ]                        |
|    Connected apps:  Gmail (linked)  [Open Composio dashboard]  |
|    [Test connection]                                           |
|                                                                |
|  Workspace                                                     |
|    Root:            D:\My-HR                                    |
|    DB:              D:\My-HR\.getset\getset.db                  |
|    Activity rows:   1,284                                      |
|                                                                |
|  [Save]                                                        |
+---------------------------------------------------------------+
```

What lives where:

| Field             | Stored in                            | Env override         |
|-------------------|--------------------------------------|----------------------|
| App name          | `settings` table + `.getset/config.json` | `APP_NAME`        |
| AI provider       | `settings` table                     | `AI_PROVIDER`        |
| AI API key        | `.getset/config.json` (cleartext)    | `AI_API_KEY`         |
| AI model          | `settings` table                     | `AI_MODEL`           |
| Composio API key  | `.getset/config.json` (cleartext)    | `COMPOSIO_API_KEY`   |
| Workspace root    | filesystem                           | `GETSET_ROOT`        |

Keys are masked in the UI as `sk-***...last4`. Click **Reveal** to see the
full value; **Replace** to overwrite it.

---

## 3. Modules

Every module has the same shape - a list page with a search box, an
**Add** button that opens a dialog, inline edit, and a per-row delete.
URLs follow `/m/<module>` for HTML and `/api/m/<module>` for JSON.

### 3.1 Employees

The master record for every person on payroll. Each employee has a unique
`employee_code` (you choose the convention: `E001`, `ACME-042`, etc.), a
hire date, employment type (full-time / contractor / intern), department,
role, manager, location, salary in minor units (paise / cents - never
floats), and a metadata blob for whatever else you want to track.

To use it: open `/m/employee`, click **+ Add Employee**, fill the form,
save. Click any row to drill into the detail page where you can attach
documents, see leave balances, attendance, payslips, and reviews. The
photo path points to a file inside `attachments/employees/<code>/`.

### 3.2 Departments

Your org tree. Each department has a name (unique), a short code, an
optional head (an employee), and an optional parent department. Use the
parent field to model hierarchy (Engineering > Backend > Platform).

The **head_employee_id** drives default approver routing for leave
requests in that department - the head sees pending requests on their
home dashboard.

### 3.3 Roles

Job titles inside a department. Each role has a title, a level
(`junior` / `mid` / `senior` / `lead`), and a free-text description that
captures the JD. Roles are the join target for both employee positions
and recruitment openings, so keep the catalog tidy.

Bulk-add roles when you onboard a new department; it's much easier than
fixing them later when 30 employees already point at the wrong role.

### 3.4 Documents

Per-employee documents. Each row records `doc_type` (e.g. `aadhaar`,
`pan`, `offer_letter`, `nda`, `degree`), the original filename, the
on-disk `file_path` (typically under `attachments/employees/<code>/`), an
optional expiry date, and free-text notes.

The list page filters by employee and by doc type. Use the **expiring
soon** quick filter on the dashboard to chase down ID renewals before
they lapse.

### 3.5 Leave

Two halves: **leave types** (the catalog) and **leave requests** (the
flow).

- Configure types under `/m/leave/types` - name, code, max days/year,
  carry-forward yes/no, paid yes/no.
- Each employee gets a **leave balance** row per type per year (allotted,
  used, pending). The balance is recomputed when requests are approved
  or cancelled.
- Employees raise a request via `/m/leave/new`. The approver is auto-set
  to their manager (or department head if no manager). Status flows
  `pending -> approved | rejected | cancelled`.

The dashboard chip "Pending leave: 4" links straight to the inbox of
requests waiting for the current viewer to act on.

### 3.6 Attendance

Daily attendance rows, one per (employee, date). Each row captures
check-in time, check-out time, hours worked (in minor units, so 7h30m =
`27000000` microseconds, or whatever convention your install uses - the
form does the conversion), status (`present` / `absent` / `half_day` /
`leave` / `holiday`), and free-text notes.

Bulk import: drop a CSV at `/m/attendance/import`. Manual edit: click
any cell in the month grid view. The grid colour-codes by status so
you can spot patterns at a glance.

### 3.7 Payroll

Payroll runs and payslips. A **payroll run** represents one period
(e.g. `2026-04`) - draft, processed, or paid. When you process a run,
the app generates one **payslip** per active employee with
`gross_minor`, `deductions_minor`, `net_minor`, and a `components_json`
blob detailing each line item (basic, HRA, PF, TDS, etc.).

Generated PDFs land in `attachments/payslips/<period>/<employee_code>.pdf`.
Mark the run **paid** after you've actually disbursed the salaries; that
locks the rows so accidental edits don't blow up your audit trail.

### 3.8 Performance

Review cycles per employee. Each `performance_review` row tags an
employee, a cycle (e.g. `2026-H1`), a reviewer, a status, an overall
score, a `rubric_json` blob with per-criterion scores, and free-text
comments.

Workflow: `draft -> submitted -> acknowledged`. The reviewee
acknowledges in their own session - they don't need a separate login,
just a magic-link the system emails them via Composio.

### 3.9 Onboarding

Per-joiner checklist of tasks. Each task has a title, an owner (the
employee responsible for completing it), a due date, status (`pending` /
`in_progress` / `done`), and notes.

Templates: define a **default checklist** under `/m/onboarding/templates`
(e.g. "Day 1: laptop issued, Day 3: PF setup, Day 7: first 1:1"). When
you add a new employee with status `active` and a future hire date, the
template is auto-cloned into their task list.

### 3.10 Exits

Exit records. One row per departing employee (`UNIQUE` on
`employee_id`). Captures `last_working_day`, reason, exit type
(`resignation` / `termination` / `retirement` / `end_of_contract`),
notice period, knowledge transfer status, asset return status, exit
interview done flag, and the timestamp the record was processed.

When you flip an exit to `processed`, the employee row's `status` flips
to `exited` and they vanish from active leave/payroll runs (but still
appear in historical reports).

### 3.11 Recruitment

The original kanban that this whole project grew from. See section 4.

---

## 4. The recruitment kanban (DB-primary)

Recruitment is a kanban over `recruitment_candidate` rows linked to a
`position_folder_id` (the legacy folder ID from the original tool). The
flow:

1. **Open a position** - either via the UI (`/m/recruitment/new-position`)
   or by creating the folder by hand and running `<app> scan`. Set its
   keywords so the email matcher knows what subjects to route here.
2. **Pull candidates** - the `<app> recruit-pull` command (or the
   **Pull from inbox** button on the position page) calls Composio's
   Gmail tools, scans recent mail with attachments, deduplicates by
   sender email, and creates one `recruitment_candidate` row per new
   applicant. Resumes are saved under
   `attachments/resumes/<position-slug>/<candidate-slug>/`.
3. **AI evaluation** - each new candidate is auto-scored by the
   `task-evaluator` agent against the position's `Rule.md` rubric.
   Results land in `score`, `recommendation`, and a generated
   `evaluation.md` attachment.
4. **Triage** - drag candidates between the columns
   `applied -> screening -> interview -> offer -> hired | rejected`.
5. **Promote** - hire? See section 5.

### Auto-migration from the old folder layout

If you upgraded from the original folder-native tool, on first boot the
**hiring migrator** scans your existing `Department/Position/Candidate`
tree and copies every candidate into `recruitment_candidate` with their
existing status, score, evaluation, and `position_folder_id`. The folder
tree is preserved as-is for attachment storage; the DB is now primary
for everything else.

The migrator is idempotent - rerunning it does not create duplicates.
It logs every migrated candidate to the activity table so you can audit
the import.

### Status vocabulary

```
applied     just came in, no triage yet
screening   under review, possibly waiting on docs
interview   at least one round scheduled or done
offer       offer extended, awaiting acceptance
hired       accepted; ready to promote to employee
rejected    closed, will not move forward
```

---

## 5. Promote candidate to employee

When a candidate accepts an offer, you don't re-key their data - the
**Promote** button on the candidate detail page does it:

1. Open `/m/recruitment/<candidate_id>`.
2. Click **Promote to employee**.
3. The dialog pre-fills employee fields from the candidate's
   `name`, `email`, `phone`, `metadata_json`, and the position's role +
   department. You fill in:
   - `employee_code` (the form suggests the next free one).
   - `hire_date` (defaults to today).
   - `employment_type`, `salary_minor`, `manager_id`, `location`.
4. Click **Save**. The app:
   - Inserts a new `employee` row.
   - Sets the candidate's `status` to `hired`.
   - Records the link in the activity log
     (`promote: candidate #N -> employee #M`).
   - Clones any resume / cover-letter attachments from
     `attachments/resumes/...` to `attachments/employees/<new_code>/`.
   - Auto-creates an onboarding task list from the default template if
     one is set.

You can promote a candidate even from `interview` if the offer was
implicit; the status flips to `hired` automatically as part of the
promote action.

---

## 6. Working with attachments

Attachments are real files inside the workspace. The app stores only the
`file_path` in the DB. Folders to know:

```
<workspace>\
  attachments\
    employees\<code>\         per-employee documents
    resumes\<position>\<cand> candidate resumes
    contracts\<code>\         offer letters, NDAs, signed contracts
    payslips\<YYYY-MM>\       generated PDFs per run
    reviews\<cycle>\          uploaded review forms or 360 sheets
```

Things to remember:

- **Always upload through the UI** if you can - it puts the file in the
  right place and inserts the `document` / `payslip` / etc. row.
- **If you drop a file by hand**, run `<app> scan` afterwards. The
  scanner discovers untracked files and creates orphan rows you can
  then assign.
- **Don't move files out of `attachments/`** while the DB still
  references them - you'll get broken links in the UI. Use the **Move**
  action on the document detail page instead, which updates the row.
- **Backups**: zip the entire workspace folder. That captures the DB,
  the config, and every attachment in one go.

---

## 7. Working with AI features

The AI is used in three places today:

1. **Recruitment evaluation** - per-candidate scoring against the
   position's `Rule.md`.
2. **Document summarisation** - on the document detail page, click
   **Summarise** to get a 5-line precis of long PDFs (contracts,
   policies).
3. **Ask the agent** - the chat panel in the bottom-right is a
   `pydantic-ai` agent with read-only tools over the DB. It can answer
   things like "how many people are on leave next Monday?" or "show
   employees in Engineering hired in 2025".

Every AI call uses the provider + model from your `/settings` page.
Results are not stored or sent anywhere except the provider you chose.

To turn AI off entirely: clear the AI API key in settings. The non-AI
parts of the app continue to work.

---

## 8. Daily / weekly rhythms

A suggested rhythm so the system doesn't drift away from reality:

**Every morning**:

- Open `/`, glance at the dashboard chips: pending leaves, pending
  onboarding tasks due today, payroll run status, candidates in offer.
- `<app> recruit-pull --since 24h` if you want the email-driven intake.

**Every Monday**:

- Run attendance close-out for the previous week
  (`/m/attendance/close-week`). It auto-marks Saturday/Sunday as
  weekend and any unfilled weekday as `absent` so you can correct.
- Review the **expiring documents** list and chase the renewals.

**Every month-end**:

- `/m/payroll/new-run` - create the run for the period, review the
  preview, then **Process**, then mark **Paid** after disbursement.
- Send out review reminders if a performance cycle is open.

---

## 9. Troubleshooting

### AI key not working

- On `/settings`, click **Test connection**. The error message comes
  straight from the provider - read it carefully.
- 401 / "invalid api key" - you pasted the wrong value, or there's a
  trailing space. Click **Replace** and try again.
- 403 / "model not available" - your key doesn't have access to the
  model you set. Switch to a free model
  (`meta-llama/llama-3.3-70b-instruct:free` on OpenRouter) to confirm
  the key works at all, then upgrade your provider plan.
- 429 / "rate limited" - you've hit the free-tier ceiling. Upgrade or
  wait.

### Composio not connected

- On `/settings`, the **Connected apps** strip should list Gmail (or
  whatever you connected). If empty, click **Open Composio dashboard**
  and reconnect from there.
- After reconnecting, click **Test connection** in `/settings`. It
  calls a no-op tool and confirms the link.
- Recruit-pull failures often mean the Gmail OAuth token expired -
  reconnect from the Composio dashboard.

### Server won't start (port in use)

```bash
# Windows: see what's holding 8765
netstat -ano | findstr :8765
taskkill /PID <PID> /F

# or just pick a different port
<app> serve --port 9000
```

### Where are the logs?

- The terminal where you ran `<app> serve` is the live log stream.
- Persistent activity log: `/activity` in the UI, or
  `<app> activity` from the CLI. That covers every CRUD action,
  evaluation, payroll run, and login.
- Crash dumps and Python tracebacks: redirect the server's stderr
  into a file when you start it:

  ```bash
  <app> serve > "D:\My-HR\.getset\server.log" 2>&1
  ```

### The DB looks wrong / weird state

The DB is at `<workspace>/.getset/getset.db`. You can:

- **Inspect** it with any SQLite browser (DB Browser for SQLite, etc.).
- **Back it up** by copying the whole `.getset/` folder.
- **Rebuild caches** (folder tree only, not module data) by deleting
  the DB and rerunning `<app> scan`. **Warning** - that drops module
  data too. Only do this on a fresh install or if you have a backup.

### "I want to start over"

```bash
# delete the workspace and re-init
rmdir /S /Q "D:\My-HR"
<app> init "D:\My-HR"
```

That gives you a clean slate. Module data is gone; attachments inside
the workspace are gone too. Take a backup first if you might want any
of it.

---

## 10. Glossary

- **Workspace** - the root folder you `init`ed. Holds the DB, config,
  attachments, and (for recruitment) the legacy department/position
  folder tree.
- **`${APP_NAME}`** - the brand you set via `APP_NAME`. Appears in the
  UI, CLI banner, and email templates.
- **BYOK** - Bring Your Own Key. The app does not ship with credentials
  for any AI provider; you paste yours.
- **Composio** - the integrations platform that handles OAuth + tool
  calls to Gmail (and others). You bring your own Composio API key.
- **Module** - one of the eleven HR areas (employees, leave, payroll,
  etc.) plugged into the app via the module registry.
- **Activity log** - append-only record of every meaningful change. Use
  it to answer "who did what, when".
- **Promote** - the recruitment-to-employee handoff that creates an
  `employee` row from a hired candidate without re-keying.

---

Last updated: 2026-04-25.
