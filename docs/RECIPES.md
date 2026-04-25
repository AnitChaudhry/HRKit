# Recipes

Recipes are named, reusable HR automations you define once and run from
**either** a button in the UI **or** the AI chat. Each recipe is a plain
markdown file in `<workspace>/recipes/<slug>.md` so you can read, edit,
share, or git-track them with your own tools.

## Anatomy

```markdown
---
type: recipe
slug: send-offer-letter
name: Send offer letter
description: Email a candidate their offer letter via Gmail.
trigger: ""                       # optional: domain event to auto-fire on
tools: [GMAIL_SEND_EMAIL]         # whitelist passed to the AI as the only tools
inputs: [candidate_name, candidate_email, position, salary]
---

Send a warm, professional offer letter to {candidate_name} at
{candidate_email} for the {position} role at a salary of {salary}.

Use the GMAIL_SEND_EMAIL tool to deliver it. Confirm before sending —
do NOT send anything without my explicit go-ahead.
```

| Frontmatter field | Purpose |
|---|---|
| `slug` | URL-safe identifier; auto-derived from `name` if you don't set it |
| `name` | Human-readable label shown on the UI button + tool list |
| `description` | One-line summary; helps the AI pick the right recipe |
| `trigger` | (future) domain event to auto-fire on (`recruitment.hired`, etc.) |
| `tools` | Upper-case Composio action slugs OR built-in tool names (`WEB_SEARCH`, `WEB_FETCH`) the recipe is allowed to call |
| `inputs` | Names of the values the recipe needs at run time. Each becomes a `{name}` placeholder you can use in the body |

The body is the **prompt template**. `{name}` placeholders are replaced
with the runtime payload before the AI sees the prompt. Unknown
placeholders stay literal so the AI knows what's missing.

## Creating one

Two ways:

### A. From the UI (`/recipes`)

Click **+ New recipe** → fill the form → **Save**. Writes the file for you.

### B. Hand-write the file

Drop a `.md` file in `<workspace>/recipes/`:

```bash
cat > my-workspace/recipes/birthday-greet.md <<'EOF'
---
type: recipe
slug: birthday-greet
name: Send birthday card
description: Send a Slack DM wishing the employee a happy birthday.
tools: [SLACK_SEND_DIRECT_MESSAGE]
inputs: [employee_name, slack_user_id]
---

Send a short, warm birthday DM to {employee_name} on Slack
(user id {slack_user_id}). Sign off as "the team at HR-Kit".
EOF
```

Reload `/recipes` → it shows up immediately.

## Running one

### From the UI

1. `/recipes` → click **Run** on the card.
2. The page prompts for each input listed in the recipe's `inputs`
   array.
3. The AI runs the rendered prompt with **only the recipe's whitelisted
   tools** plus the always-on web tools.
4. Reply (and any tool calls) shown in an alert.

### From the AI chat

The chat agent sees a `run_recipe(slug, inputs)` tool. Tell it:

```
Send the offer letter to Asha Iyer (asha@example.com) for the Senior
Engineer role at 18 LPA.
```

The AI matches the request to the `send-offer-letter` recipe, fills the
inputs, and either runs it (after confirming, since the recipe asked it
to) or asks you to confirm first.

## Best practices

- **Keep tools tight.** The fewer Composio actions in `tools`, the
  smaller the surface area the AI can touch when running the recipe.
- **Always say "confirm before sending"** in the body when the recipe
  has a side effect (email send, calendar create, payment). The AI
  will pause for your OK.
- **Use placeholders for everything that varies.** Hard-coding "Asha"
  in the body means you have to edit the file each time; using
  `{candidate_name}` keeps the recipe reusable.
- **One recipe = one outcome.** Don't chain unrelated steps; that's what
  the chat agent is for. Recipes are best when they're one prompt + one
  to three tools.

## Examples

### Send offer letter
```yaml
tools: [GMAIL_SEND_EMAIL]
inputs: [candidate_name, candidate_email, position, salary]
```

### Block calendar for an approved leave
```yaml
tools: [GOOGLECALENDAR_CREATE_EVENT]
inputs: [employee_name, start_date, end_date, leave_type]
```

### Onboard a new hire on Slack
```yaml
tools: [SLACK_SEND_CHANNEL_MESSAGE, SLACK_INVITE_USER_TO_CHANNEL]
inputs: [employee_name, slack_user_id, team_channel]
```

### Look up a candidate's GitHub profile
```yaml
tools: [WEB_SEARCH, WEB_FETCH]
inputs: [candidate_name, candidate_email]
```
(No Composio needed — just the always-on web tools.)

## Where they live

```
<workspace>/recipes/
├── send-offer-letter.md
├── birthday-greet.md
└── candidate-research.md
```

`git init` the workspace folder and you've got version-controlled
automations the whole HR team can review.

## Related

- [INTEGRATIONS.md](INTEGRATIONS.md) — how Composio actions get connected
- [AI-CHAT.md](AI-CHAT.md) — how the AI sees recipes as tools
