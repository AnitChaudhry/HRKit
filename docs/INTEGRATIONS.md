# Integrations (Composio)

HR-Kit ships with no integrations baked in. You bring a
[Composio](https://composio.dev/) account, plug in the apps you need, and
the AI agent + per-module flows can use them.

## What you get

- **Generic catalog** — all 200+ Composio apps (Gmail, Calendar, Drive,
  Slack, Notion, Linear, GitHub, Hubspot, …) reachable from one page.
- **OAuth-hosted by Composio** — when you click **Connect**, Composio
  handles the OAuth callback. Your local server never needs a public URL.
- **Per-tool toggles** — switch individual actions on/off. Disabled tools
  disappear from the AI's tool list (it can't call what isn't enabled).
- **Test buttons** — fire any action with an empty payload to confirm
  connectivity from inside the UI.
- **Local-folder mirror** — every record an action fetches (Gmail
  threads, Calendar events, Drive files, …) is written to disk as a
  paired `.md` (human-readable, with YAML frontmatter) + `.json` (raw API
  response) under `<workspace>/integrations/<app>/<resource>/<id>.{md,json}`.
  Browse / grep / edit with your own tools.

## Setup

### 1. Get a Composio key

Sign up at <https://app.composio.dev/> → Account → API Keys → Create.
Free tier covers personal HR use.

### 2. Paste it into HR-Kit

`/settings` → **Composio API key** → Save.

You can also set the env var instead:

```bash
COMPOSIO_API_KEY=ck_... hrkit serve
```

### 3. Connect an app

`/integrations` → **Show / hide** under "Available to connect" → click
**Connect** on the app you want.

A dialog shows a Composio-hosted URL. Click it (opens a new tab),
complete OAuth in the browser, return to the dialog, click **Open +
refresh** (or just **Close** then hit **Refresh** at the top of the
page).

The app moves up to **Connected** with status `ACTIVE`.

### 4. Toggle which actions the AI can use

Each connected app shows its actions as a list with a toggle. By default
all are **on**. Flip any off — that action disappears from the AI tool
list immediately. Persisted in `settings.COMPOSIO_DISABLED_TOOLS`
(JSON list of slugs).

### 5. Test before relying

The **Test** button next to each action runs it with an empty payload
and shows the response. Use this to confirm the OAuth scope is right
before you wire it into a recipe or hand the app to a teammate.

## How it's wired

There are two backends in front of Composio:

1. **`composio` SDK** (preferred) — the official Python SDK. Provides
   the `toolkits.list()`, `toolkits.authorize()`, `tools.execute()`,
   `connected_accounts.list()` calls.
2. **`composio_client.py`** — a stdlib `urllib`-only fallback for the same
   endpoints. Used automatically if the SDK fails to import or its calls
   raise.

Both paths flow through one normalizer in `hrkit/composio_sdk.py` so
callers see the same dict shapes regardless of which path served the
request:

```python
list_apps    -> [{"slug", "name", "description", "logo", "categories"}]
list_actions -> [{"slug", "name", "description", "toolkit_slug", "deprecated"}]
list_connections -> [{"id", "toolkit_slug", "status", "created_at"}]
init_connection  -> {"redirect_url", "connected_account_id", "raw"}
execute_action   -> {"successful", "data", "error"}
```

## The local-folder mirror

When an action fetches structured records, HR-Kit writes them to disk so
you (and any AI/agent your team uses later) can browse them as files:

```
<workspace>/integrations/
├── gmail/
│   ├── messages/<msg_id>.md         # frontmatter: subject, from, to, date, thread_id
│   ├── messages/<msg_id>.json       # raw Gmail API payload
│   └── threads/<thread_id>.md
├── googlecalendar/
│   └── events/<event_id>.{md,json}
├── googledrive/
│   └── files/<file_id>.{md,json}
└── slack/
    └── messages/<message_id>.{md,json}
```

The `.md` files use the same frontmatter format as `getset.md` markers,
so the workspace scanner and any standard markdown reader can parse them.
Edit them by hand if you want — the next fetch overwrites them with
fresh data, but only the records that come back are touched (the rest
stay).

## The pull-from-Gmail recruitment flow

If you have Gmail connected:

1. `/m/recruitment` → click **Pull from Gmail**.
2. Optional: type a Gmail search query (default
   `label:UNREAD newer_than:14d`).
3. Each fetched email becomes:
   - a `recruitment_candidate` row in the DB (skipped if a candidate
     with the same `from:` address already exists),
   - a paired `.md` + `.json` under `integrations/gmail/messages/`.

If you have an AI key configured, the existing evaluator can score each
new candidate automatically.

## Adding new actions to the AI's tool list

By default the AI gets:

- a `query_records` tool that dispatches to all 11 module CRUDs,
- `web_search` and `web_fetch` (no Composio needed),
- one callable per saved recipe (see [RECIPES.md](RECIPES.md)).

To expose a Composio action directly to the AI, define a recipe whose
`tools` list contains that action's slug. The recipe shows up to the AI
as a tool; running it scopes the AI to just those Composio actions.

## When something fails

- **`/integrations` shows an empty Connected list but I clicked Connect** —
  Composio takes a few seconds to flip the connection to `ACTIVE`. Hit
  **Refresh** after completing the browser OAuth.
- **AI says "Composio API key not configured"** — paste the key in
  `/settings` (it's a separate key from your AI provider key).
- **A tool returns "Low credits"** — Composio plan limit. Either upgrade
  on Composio's side or disable that tool in `/integrations` so the AI
  stops trying.
- **The mirror folder is empty** — the action might be returning a
  non-list payload (e.g., a single record without an obvious ID). The
  mirror only writes when it can extract an `id`. Open the action in
  `/integrations` → **Test** to see the raw response shape.

## Privacy

Everything Composio fetches lives **on your machine** in the workspace
folder. Composio's servers see the OAuth tokens and proxy the API calls
(that's how they offer 200 apps without you implementing each one), but
the resulting data lands locally. Nothing about your employees,
candidates, or HR records goes back to Composio's analytics — they only
see "this account ran action X with these arguments and got HTTP 200".
