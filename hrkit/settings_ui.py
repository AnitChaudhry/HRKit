"""Settings UI for the HR app — renders /settings page and handles save/test APIs.

Wave 1 Agent #5 deliverable. Imports only branding, ai, composio_client (and
stdlib). Must NOT import server.py — server.py imports this module via the
Wave 2 integrator and that would cause a circular import.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from hrkit import ai
from hrkit import branding
from hrkit import composio_client

log = logging.getLogger(__name__)

# Defaults for the AI Model placeholder per provider. Kept here (not in
# branding.py) because they are UI hints, not canonical config values.
_MODEL_PLACEHOLDERS: dict[str, str] = {
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "upfyn": "gpt-4o-mini",
}

_VALID_PROVIDERS: tuple[str, ...] = ("openrouter", "upfyn")


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def render_settings_page(conn) -> str:
    """Return full HTML for GET /settings.

    Reads current settings via the branding module. API keys are never echoed
    back into the form — only a masked preview is shown so the user knows a
    value is on file.
    """
    title = branding.app_name()
    provider = branding.ai_provider(conn) or "openrouter"
    if provider not in _VALID_PROVIDERS:
        provider = "openrouter"
    model = branding.ai_model(conn) or ""
    ai_key = branding.ai_api_key(conn) or ""
    composio_key = branding.composio_api_key(conn) or ""

    ai_key_masked = branding.masked(ai_key) if ai_key else ""
    composio_key_masked = branding.masked(composio_key) if composio_key else ""

    placeholder_or = html.escape(_MODEL_PLACEHOLDERS["openrouter"])
    placeholder_up = html.escape(_MODEL_PLACEHOLDERS["upfyn"])
    current_placeholder = html.escape(_MODEL_PLACEHOLDERS.get(provider, ""))

    title_esc = html.escape(title)
    app_name_esc = html.escape(title)
    model_esc = html.escape(model)
    ai_key_masked_esc = html.escape(ai_key_masked)
    composio_key_masked_esc = html.escape(composio_key_masked)

    or_selected = " selected" if provider == "openrouter" else ""
    up_selected = " selected" if provider == "upfyn" else ""

    ai_key_hint = (
        f'<div class="hint">Current: <code>{ai_key_masked_esc}</code> '
        f'(leave blank to keep)</div>'
        if ai_key_masked else '<div class="hint">No AI key on file.</div>'
    )
    composio_key_hint = (
        f'<div class="hint">Current: <code>{composio_key_masked_esc}</code> '
        f'(leave blank to keep)</div>'
        if composio_key_masked else '<div class="hint">No Composio key on file.</div>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Settings &middot; {title_esc}</title>
<style>
  :root {{
    --bg: #f7f8fa; --fg: #1f2330; --muted: #6b7280; --border: #d8dde5;
    --card: #ffffff; --accent: #2563eb; --accent-hover: #1d4ed8;
    --ok: #15803d; --err: #b91c1c;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px; background: var(--bg); color: var(--fg);
    font: 14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
  }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); margin: 0 0 20px; }}
  .card {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 8px; padding: 20px; margin-bottom: 16px;
  }}
  .card h2 {{ font-size: 16px; margin: 0 0 14px; }}
  .field {{ margin-bottom: 14px; }}
  label {{ display: block; font-weight: 600; margin-bottom: 4px; }}
  input[type=text], input[type=password], select {{
    width: 100%; padding: 8px 10px; font: inherit;
    border: 1px solid var(--border); border-radius: 6px; background: #fff;
  }}
  input:focus, select:focus {{ outline: 2px solid var(--accent); outline-offset: -1px; }}
  .hint {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  code {{ background: #eef1f6; padding: 1px 5px; border-radius: 3px; font-size: 12px; }}
  .row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  button {{
    padding: 8px 14px; border: 1px solid var(--border); border-radius: 6px;
    background: #fff; font: inherit; cursor: pointer;
  }}
  button.primary {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  button.primary:hover {{ background: var(--accent-hover); }}
  button:disabled {{ opacity: 0.6; cursor: progress; }}
  .status {{ margin-top: 8px; font-size: 13px; min-height: 18px; }}
  .status.ok {{ color: var(--ok); }}
  .status.err {{ color: var(--err); }}
  @media (max-width: 520px) {{
    body {{ padding: 12px; }}
    .card {{ padding: 14px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Settings</h1>
  <p class="sub">Configure {title_esc} branding, AI provider, and Composio integration.</p>

  <form id="settings-form" autocomplete="off">

    <div class="card">
      <h2>Branding</h2>
      <div class="field">
        <label for="app_name">App Name</label>
        <input type="text" id="app_name" name="app_name" value="{app_name_esc}"
               placeholder="HR Desk">
        <div class="hint">Shown in browser title and navigation.</div>
      </div>
    </div>

    <div class="card">
      <h2>AI (BYOK)</h2>
      <div class="field">
        <label for="ai_provider">AI Provider</label>
        <select id="ai_provider" name="ai_provider">
          <option value="openrouter"{or_selected}>OpenRouter</option>
          <option value="upfyn"{up_selected}>Upfyn</option>
        </select>
      </div>
      <div class="field">
        <label for="ai_api_key">AI API Key</label>
        <input type="password" id="ai_api_key" name="ai_api_key"
               placeholder="sk-..." autocomplete="new-password">
        {ai_key_hint}
      </div>
      <div class="field">
        <label for="ai_model">AI Model</label>
        <input type="text" id="ai_model" name="ai_model" value="{model_esc}"
               placeholder="{current_placeholder}"
               data-placeholder-openrouter="{placeholder_or}"
               data-placeholder-upfyn="{placeholder_up}">
        <div class="hint">Leave blank to use the provider default.</div>
      </div>
      <div class="row">
        <button type="button" id="test-ai">Test AI connection</button>
      </div>
      <div class="status" id="status-ai"></div>
    </div>

    <div class="card">
      <h2>Composio (BYOK)</h2>
      <div class="field">
        <label for="composio_api_key">Composio API Key</label>
        <input type="password" id="composio_api_key" name="composio_api_key"
               placeholder="comp-..." autocomplete="new-password">
        {composio_key_hint}
      </div>
      <div class="row">
        <button type="button" id="test-composio">Test Composio connection</button>
      </div>
      <div class="status" id="status-composio"></div>
    </div>

    <div class="card">
      <div class="row">
        <button type="submit" class="primary" id="save-btn">Save</button>
        <span class="status" id="status-save"></span>
      </div>
    </div>

  </form>
</div>

<script>
(function() {{
  const form = document.getElementById("settings-form");
  const providerEl = document.getElementById("ai_provider");
  const modelEl = document.getElementById("ai_model");

  function syncModelPlaceholder() {{
    const p = providerEl.value;
    const ph = modelEl.dataset["placeholder" + p.charAt(0).toUpperCase() + p.slice(1)];
    if (ph) modelEl.placeholder = ph;
  }}
  providerEl.addEventListener("change", syncModelPlaceholder);

  function setStatus(id, ok, msg) {{
    const el = document.getElementById(id);
    el.textContent = msg || "";
    el.className = "status " + (ok ? "ok" : "err");
  }}

  function collect() {{
    const data = {{
      app_name: document.getElementById("app_name").value.trim(),
      ai_provider: providerEl.value,
      ai_model: modelEl.value.trim(),
    }};
    const ak = document.getElementById("ai_api_key").value;
    const ck = document.getElementById("composio_api_key").value;
    if (ak) data.ai_api_key = ak;
    if (ck) data.composio_api_key = ck;
    return data;
  }}

  form.addEventListener("submit", async function(e) {{
    e.preventDefault();
    const btn = document.getElementById("save-btn");
    btn.disabled = true;
    setStatus("status-save", true, "Saving...");
    try {{
      const r = await fetch("/api/settings", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify(collect()),
      }});
      const j = await r.json();
      if (j.ok) {{
        setStatus("status-save", true, "Saved.");
        setTimeout(function() {{ window.location.reload(); }}, 600);
      }} else {{
        setStatus("status-save", false, "Error: " + (j.error || "save failed"));
      }}
    }} catch (err) {{
      setStatus("status-save", false, "Network error: " + err);
    }} finally {{
      btn.disabled = false;
    }}
  }});

  async function runTest(target, statusId, btnId) {{
    const btn = document.getElementById(btnId);
    btn.disabled = true;
    setStatus(statusId, true, "Testing...");
    try {{
      const r = await fetch("/api/settings/test", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{target: target}}),
      }});
      const j = await r.json();
      if (j.ok) {{
        const detail = j.provider ? " (" + j.provider + (j.model ? " / " + j.model : "") + ")" : "";
        setStatus(statusId, true, "OK" + detail);
      }} else {{
        setStatus(statusId, false, "Failed: " + (j.error || "unknown error"));
      }}
    }} catch (err) {{
      setStatus(statusId, false, "Network error: " + err);
    }} finally {{
      btn.disabled = false;
    }}
  }}

  document.getElementById("test-ai").addEventListener("click", function() {{
    runTest("ai", "status-ai", "test-ai");
  }});
  document.getElementById("test-composio").addEventListener("click", function() {{
    runTest("composio", "status-composio", "test-composio");
  }});
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# POST /api/settings
# ---------------------------------------------------------------------------
def handle_save_settings(handler, body: dict) -> None:
    """Validate the posted settings and persist them via branding.set_settings.

    Empty values for ai_api_key / composio_api_key are dropped (so users can
    update non-secret fields without retyping their keys). app_name and
    ai_provider are validated; ai_model is allowed to be blank (provider
    default kicks in).
    """
    if not isinstance(body, dict):
        handler._json({"ok": False, "error": "expected JSON object"}, 400)
        return

    updates: dict[str, str] = {}
    errors: list[str] = []

    if "app_name" in body:
        name = str(body.get("app_name") or "").strip()
        if not name:
            errors.append("app_name must not be blank")
        elif len(name) > 64:
            errors.append("app_name must be <= 64 characters")
        else:
            updates["app_name"] = name

    if "ai_provider" in body:
        prov = str(body.get("ai_provider") or "").strip().lower()
        if prov not in _VALID_PROVIDERS:
            errors.append(
                f"ai_provider must be one of {', '.join(_VALID_PROVIDERS)}"
            )
        else:
            updates["ai_provider"] = prov

    if "ai_model" in body:
        model = str(body.get("ai_model") or "").strip()
        # Empty is allowed — caller wants the provider default.
        updates["ai_model"] = model

    # Secret fields: only persist if a non-empty value was sent. This lets the
    # form submit without re-entering the key each time.
    if "ai_api_key" in body:
        key = str(body.get("ai_api_key") or "")
        if key.strip():
            updates["ai_api_key"] = key.strip()

    if "composio_api_key" in body:
        key = str(body.get("composio_api_key") or "")
        if key.strip():
            updates["composio_api_key"] = key.strip()

    if errors:
        handler._json({"ok": False, "error": "; ".join(errors)}, 400)
        return

    if not updates:
        handler._json({"ok": True, "saved": 0})
        return

    conn = _conn_for(handler)
    if conn is None:
        handler._json({"ok": False, "error": "no database connection"}, 500)
        return

    try:
        branding.set_settings(conn, updates)
    except Exception as exc:  # noqa: BLE001 — surface DB error to the UI
        log.exception("set_settings failed")
        handler._json({"ok": False, "error": f"save failed: {exc}"}, 500)
        return

    handler._json({"ok": True, "saved": len(updates)})


# ---------------------------------------------------------------------------
# POST /api/settings/test
# ---------------------------------------------------------------------------
def handle_test_connection(handler, body: dict) -> None:
    """Probe the AI or Composio backend using the saved keys.

    body: {"target": "ai" | "composio"}
    Returns whatever health_check() returned (already JSON-serialisable).
    """
    if not isinstance(body, dict):
        handler._json({"ok": False, "error": "expected JSON object"}, 400)
        return

    target = str(body.get("target") or "").strip().lower()
    if target not in ("ai", "composio"):
        handler._json({"ok": False, "error": "target must be 'ai' or 'composio'"}, 400)
        return

    conn = _conn_for(handler)
    if conn is None:
        handler._json({"ok": False, "error": "no database connection"}, 500)
        return

    try:
        if target == "ai":
            result: dict[str, Any] = ai.health_check(conn)
        else:
            result = composio_client.health_check(conn)
    except Exception as exc:  # noqa: BLE001 — health checks must never crash UI
        log.exception("%s health_check raised", target)
        handler._json({"ok": False, "error": f"{target} check raised: {exc}"}, 200)
        return

    if not isinstance(result, dict):
        handler._json(
            {"ok": False, "error": f"{target} health_check returned non-dict"}, 200
        )
        return

    # Normalise: ensure 'ok' key is present and boolean.
    result.setdefault("ok", False)
    result["ok"] = bool(result.get("ok"))
    handler._json(result)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _conn_for(handler) -> Any:
    """Resolve the SQLite connection from the handler.

    server.py keeps the live connection in module-global ``CONN``. Importing
    server here would be circular, so we walk the handler's class module
    instead. Tests (and the Wave 2 integrator) may also attach a ``conn``
    attribute directly to the handler — that wins if present.
    """
    direct = getattr(handler, "conn", None)
    if direct is not None:
        return direct
    mod = getattr(type(handler), "__module__", None)
    if not mod:
        return None
    import sys

    server_mod = sys.modules.get(mod)
    if server_mod is None:
        return None
    return getattr(server_mod, "CONN", None)
