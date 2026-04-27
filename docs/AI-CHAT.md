# AI Chat (`/chat`)

The in-app AI assistant — a BYOK (bring-your-own-key) chat agent with
read/write access to your HR data via tool calls.

## Setup

`/settings` → paste an **AI API key** from one of:

- **OpenRouter** (<https://openrouter.ai/keys>) — many free tier models
  with tool-calling support
- **Upfyn** (<https://ai.upfyn.com>) — drop-in OpenAI-compatible gateway

Pick the matching provider in the dropdown. Save.

That's it. Open `/chat` and say hello.

## What it can do

| Capability | Powered by |
|---|---|
| Read any HR record | `query_records` tool — dispatches to all 11 module CRUDs (`employee`, `leave`, `payroll`, …) |
| Modify HR records | Same tool — but tell it **"always confirm before deleting"** in the system prompt; you can also disable specific module ops in code |
| Search the web | `web_search` (DuckDuckGo HTML, stdlib `urllib`) |
| Fetch a URL | `web_fetch` (urllib + HTML→text strip, capped at 6 KB) |
| Run a Composio action | Whatever you've connected at `/integrations`, gated by per-tool toggles |
| Run a saved recipe | `run_recipe(slug, inputs)` — see [RECIPES.md](RECIPES.md) |

## The chat header

| Control | What it does |
|---|---|
| **Talking about** dropdown (sidebar) | Scopes the conversation to one employee. The AI's system prompt is enriched with that employee's full record, custom fields, free-form HR notes, recent leave, and documents on file. The conversation is saved under that employee's folder so it shows up next time you talk about them. |
| **Default model** dropdown (top-right) | Per-conversation model override. Free models are marked with `★` and sorted first. The default model is whatever you picked in `/settings`. Models are fetched live from the provider's `/models` endpoint. |
| **Clear** button | Starts a new conversation (does **not** delete the saved one). |

## Attachments

Click the **📎** (paperclip) in the input box → pick one or more files.

Each file is:

1. Saved to `<workspace>/.hrkit/uploads/chat/<uuid>/<filename>` on disk.
2. Sent to the AI as inline text **if** the extension is in the
   text-extraction list:
   `.txt .md .markdown .rst .csv .tsv .json .yaml .yml .xml .html .htm
   .log .py .js .ts .tsx .jsx .java .go .rs .rb .sh .sql .env`
   …capped at 20,000 characters per file.
3. For binary types (PDFs, images, .docx) the AI receives a placeholder
   like `[binary file at .hrkit/uploads/chat/abc123/cv.pdf — cannot
   inline-read without an OCR/vision tool]` so it knows the file exists
   but can't read it directly.

To remove an attachment before sending, click the **×** on its chip.

## Conversations

Every conversation is written to disk as **two paired files** so a human
can browse the transcript and the app can re-load it losslessly:

```
<workspace>/conversations/<id>.md       # frontmatter + readable transcript
<workspace>/conversations/<id>.json     # raw turns (role, content, attachments)
```

When the **Talking about** dropdown is set to an employee, the files
land under that employee's folder instead:

```
<workspace>/employees/<EMP-CODE>/conversations/<id>.{md,json}
```

The sidebar lists prior conversations (newest first). Click any to
resume — the history seeds the next prompt so the AI has context.

## Graceful errors

When a model call fails, the chat surfaces a **short, user-friendly
message** instead of a stack trace. Common translations:

| Provider error | What you see |
|---|---|
| `insufficient_quota`, `insufficient credit`, `low credits` | "Low credits on your AI provider account. Pick a free model or top up." |
| `payment_required` | "Payment required by the provider. Pick a free model or top up your account." |
| `rate_limit`, `rate limit` | "Provider rate limit hit. Wait a few seconds and try again." |
| `model_not_found`, `does not exist` | "The selected model isn't available with this key. Try another model." |
| `unauthorized`, `invalid_api_key` | "Provider rejected the API key. Check it on the Settings page." |

Anything else passes through verbatim.

## Tool gating

The AI's tool list is filtered against `branding.composio_disabled_tools()`
before being passed to PydanticAI. Any tool whose name is in
`settings.COMPOSIO_DISABLED_TOOLS` (a JSON list of upper-case slugs) is
dropped silently. Toggle them on/off at `/integrations`.

If no Composio apps are connected, the AI still has access to:

- `query_records` (HR data)
- `web_search`, `web_fetch` (web)
- any saved recipes that don't require Composio tools

So even with zero integrations and a free model, the AI is useful.

## Privacy

- The chat agent runs **in-process** in the `hrkit serve` Python process.
- Each model call goes from your machine → your AI provider's API. The
  provider sees the prompts and tool calls. Nothing goes to ThinqMesh,
  Composio, or any third party HR-Kit doesn't list above.
- Conversations live on **your disk**. Delete the `<workspace>/conversations/`
  folder (or the per-employee one) to wipe history.

## Related

- [INTEGRATIONS.md](INTEGRATIONS.md) — connect Composio apps to expose more tools
- [RECIPES.md](RECIPES.md) — define named, reusable AI automations
