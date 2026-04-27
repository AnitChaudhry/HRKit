"""First-run setup wizard.

When the workspace is fresh (no employees and no settings rows) the server
shows a 5-step wizard that captures:

1. ``APP_NAME`` — branding label
2. AI provider + key (skippable)
3. Module selection (skippable — default = all enabled)
4. First department
5. First employee

Each step posts to ``/api/wizard`` and is dispatched by
:func:`handle_wizard_step`. The frontend in :func:`render_wizard_page` walks
the user through the sequence and finally redirects to ``/m/employee``.

Stdlib only. The new HTTP routes are wired up by Wave 4 B; this module does
not import :mod:`hrkit.server`.
"""

from __future__ import annotations

import html
import logging
import sqlite3
from typing import Any

from . import branding
from . import feature_flags

log = logging.getLogger(__name__)

VALID_PROVIDERS = ("openrouter", "upfyn")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _safe_count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    try:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    except sqlite3.Error:
        return 0
    if row is None:
        return 0
    return int(row["c"] if hasattr(row, "keys") else row[0])


def needs_wizard(conn: sqlite3.Connection) -> bool:
    """Return ``True`` when the workspace is fresh and never set up."""
    if conn is None:
        return False
    employees = _safe_count(conn, "employee")
    settings_rows = _safe_count(conn, "settings")
    return employees == 0 and settings_rows == 0


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def _module_picker_html() -> str:
    """Render the checkbox grid for the wizard's modules step."""
    import importlib

    rows: list[str] = []
    for slug in feature_flags.ALL_MODULES:
        try:
            mod = importlib.import_module(f"hrkit.modules.{slug}")
            md = getattr(mod, "MODULE", {}) or {}
        except Exception:
            md = {}
        label = html.escape(md.get("label") or slug.title())
        desc = html.escape(md.get("description") or "")
        category = html.escape(md.get("category") or "hr")
        locked = slug in feature_flags.ALWAYS_ON
        checked = " checked"
        disabled = " disabled" if locked else ""
        lock_hint = (
            '<span class="wm-lock" title="Always on — core">core</span>'
            if locked else ""
        )
        rows.append(
            f'<label class="wm-row" data-cat="{category}">'
            f'<input type="checkbox" name="mod_{slug}" data-slug="{html.escape(slug)}"{checked}{disabled}>'
            f'<div class="wm-meta">'
            f'<div class="wm-head"><span class="wm-label">{label}</span>'
            f'<span class="wm-cat wm-cat-{category}">{category}</span>{lock_hint}</div>'
            f'<div class="wm-desc">{desc}</div>'
            f'</div></label>'
        )
    return "".join(rows)


def render_wizard_page(conn: sqlite3.Connection) -> str:
    """Return the full standalone HTML for the first-run wizard."""
    default_app_name = html.escape(branding.app_name() or "HR Desk")
    title = html.escape(branding.app_name() or "HR Desk")
    modules_html = _module_picker_html()
    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Welcome &middot; {title}</title>
<style>
  /* Wizard uses the same token system as the rest of the app — light by
     default, dark via [data-theme="dark"] on <html>. */
  :root {{
    --bg:#f5f6f8; --panel:#ffffff; --panel-alt:#fafbfc;
    --border:#e5e7eb; --border-soft:#eef0f3;
    --text:#1f2937; --dim:#6b7280; --mute:#9ca3af;
    --accent:#ef4444; --accent-soft:rgba(239,68,68,0.10);
    --green:#10b981; --red:#ef4444;
    --row-hover:rgba(15,23,42,0.03);
    --shadow-md:0 1px 3px rgba(15,23,42,0.05),0 4px 16px rgba(15,23,42,0.06);
  }}
  [data-theme="dark"] {{
    --bg:#08090a; --panel:#14171d; --panel-alt:#0f1115;
    --border:rgba(255,255,255,0.08); --border-soft:rgba(255,255,255,0.05);
    --text:#e8eaed; --dim:#9aa0a6; --mute:#6b7280;
    --accent:#ef4444; --accent-soft:rgba(239,68,68,0.18);
    --row-hover:rgba(255,255,255,0.04);
    --shadow-md:0 12px 40px rgba(0,0,0,0.5);
  }}
  *,*::before,*::after {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: 'Inter', system-ui, sans-serif;
         background: var(--bg); color: var(--text); min-height: 100vh;
         -webkit-font-smoothing: antialiased;
         display: flex; align-items: center; justify-content: center; padding: 24px; }}
  .card {{ background: var(--panel); border: 1px solid var(--border);
           border-radius: 14px; padding: 32px 36px; width: 920px; max-width: 96vw;
           box-shadow: var(--shadow-md); }}
  h1 {{ margin: 0 0 6px; font-size: 22px; letter-spacing: -0.02em; font-weight: 700; }}
  .sub {{ color: var(--dim); font-size: 13px; margin-bottom: 18px; }}
  .steps {{ display: flex; gap: 6px; margin-bottom: 22px; }}
  .dot {{ flex: 1; height: 4px; background: var(--border); border-radius: 2px; }}
  .dot.active {{ background: var(--accent); }}
  .dot.done {{ background: var(--green); }}
  label {{ display: block; font-size: 12px; color: var(--dim); margin-top: 12px;
           margin-bottom: 4px; font-weight: 500; }}
  input, select, textarea {{ width: 100%; padding: 9px 11px; background: var(--panel-alt);
                              border: 1px solid var(--border); border-radius: 8px;
                              color: var(--text); font-size: 13px; font-family: inherit; }}
  input:focus, select:focus, textarea:focus {{ outline: none; border-color: var(--accent);
                                                box-shadow: 0 0 0 3px var(--accent-soft); }}
  .row {{ display: flex; gap: 12px; }}
  .row > * {{ flex: 1; }}
  .actions {{ display: flex; justify-content: space-between; gap: 8px; margin-top: 22px; }}
  button {{ padding: 9px 16px; border-radius: 8px; border: 1px solid var(--border);
            background: var(--panel); color: var(--text); font-size: 13px; cursor: pointer;
            font-family: inherit; font-weight: 500; }}
  button.primary {{ background: var(--accent); border-color: var(--accent);
                    color: #fff; font-weight: 600; }}
  button:hover {{ filter: brightness(1.04); }}
  button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
  .step {{ display: none; }}
  .step.active {{ display: block; }}
  .err {{ color: var(--red); font-size: 12px; margin-top: 10px; min-height: 16px; }}
  .skip {{ background: none; border: none; color: var(--dim); padding: 9px 0;
           cursor: pointer; font-weight: 500; }}
  .skip:hover {{ color: var(--text); }}
  .checkbox-row {{ display: flex; align-items: center; gap: 8px; margin-top: 14px;
                   color: var(--dim); font-size: 12px; }}
  .checkbox-row input {{ width: auto; margin: 0; }}
  .wm-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
              padding: 6px;
              border: 1px solid var(--border-soft); border-radius: 10px;
              background: var(--panel-alt); }}
  @media (max-width: 880px) {{ .wm-grid {{ grid-template-columns: 1fr 1fr; }} }}
  @media (max-width: 580px) {{ .wm-grid {{ grid-template-columns: 1fr; }} }}
  .wm-row {{ display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px;
             border-radius: 6px; cursor: pointer; margin: 0;
             background: var(--panel); border: 1px solid var(--border-soft); }}
  .wm-row:hover {{ border-color: var(--accent); }}
  .wm-row input {{ width: auto; margin-top: 3px; flex-shrink: 0; }}
  .wm-meta {{ flex: 1; min-width: 0; }}
  .wm-head {{ display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }}
  .wm-label {{ font-weight: 600; color: var(--text); font-size: 13px; }}
  .wm-cat {{ font-size: 9px; padding: 2px 7px; border-radius: 999px; text-transform: uppercase;
             letter-spacing: 0.6px; font-weight: 600;
             background: var(--row-hover); color: var(--dim); }}
  .wm-cat-core {{ background: var(--accent-soft); color: var(--accent); }}
  .wm-cat-hiring {{ background: rgba(245,158,11,0.14); color: #b45309; }}
  [data-theme="dark"] .wm-cat-hiring {{ color: #fcd34d; }}
  .wm-lock {{ font-size: 9px; padding: 2px 7px; border-radius: 999px; font-weight: 600;
              background: var(--row-hover); color: var(--mute); text-transform: uppercase;
              letter-spacing: 0.6px; }}
  .wm-desc {{ font-size: 11px; color: var(--dim); margin-top: 2px; line-height: 1.45; }}
  .wm-quick {{ display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }}
  .wm-quick button {{ padding: 4px 10px; font-size: 11px; }}
</style>
<script>
  // Apply persisted theme before paint to avoid a flash on the wizard.
  (function() {{
    try {{
      var t = localStorage.getItem('hrkit-theme');
      if (t === 'dark' || t === 'light') document.documentElement.setAttribute('data-theme', t);
    }} catch (e) {{}}
  }})();
</script>
</head>
<body>
<div class="card">
  <h1>Welcome to {title}</h1>
  <div class="sub">Five quick steps to set up your workspace.</div>
  <div class="steps">
    <div class="dot active" id="dot-1"></div>
    <div class="dot" id="dot-2"></div>
    <div class="dot" id="dot-3"></div>
    <div class="dot" id="dot-4"></div>
    <div class="dot" id="dot-5"></div>
  </div>

  <form class="step active" data-step="1">
    <label>App name</label>
    <input name="app_name" required value="{default_app_name}">
    <div class="actions">
      <span></span>
      <button type="submit" class="primary">Next</button>
    </div>
    <div class="err"></div>
  </form>

  <form class="step" data-step="2">
    <label>AI provider</label>
    <select name="ai_provider" id="wiz-ai-provider">
      <option value="openrouter">OpenRouter (recommended — has free models)</option>
      <option value="upfyn">Upfyn</option>
    </select>
    <label>API key</label>
    <input name="ai_api_key" id="wiz-ai-key" type="password" placeholder="sk-or-...">
    <div class="sub" style="margin-top:6px">
      <span id="wiz-ai-key-hint">Get an OpenRouter key at <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">openrouter.ai/keys</a> — free models work without billing.</span>
    </div>
    <div class="actions" style="margin-top:14px">
      <button type="button" id="wiz-ai-connect" class="primary">Connect &amp; load models</button>
    </div>
    <div id="wiz-ai-status" class="sub" style="margin-top:10px;min-height:18px"></div>

    <div id="wiz-ai-model-wrap" style="display:none;margin-top:10px">
      <label>Model</label>
      <select name="ai_model" id="wiz-ai-model"></select>
      <div class="sub" style="margin-top:6px">★ marks free models. The default is a free model so you can start without billing.</div>
    </div>

    <div class="actions" style="margin-top:14px">
      <button type="button" class="skip" data-skip="2">Skip (configure later)</button>
      <button type="submit" id="wiz-ai-next" class="primary" disabled>Next</button>
    </div>
    <div class="err"></div>
  </form>

  <form class="step" data-step="3">
    <label style="margin-top:0">Choose your modules</label>
    <div class="sub" style="margin-bottom:12px">
      Pick what your HR team actually uses. Departments, Employees and Roles
      are always on. You can change this later in <code>/settings</code>.
    </div>
    <div class="wm-quick">
      <button type="button" data-preset="all">Everything</button>
      <button type="button" data-preset="core">Core only</button>
      <button type="button" data-preset="hiring">Recruitment-focused</button>
      <button type="button" data-preset="hr">HR-focused</button>
    </div>
    <div class="wm-grid" id="wm-grid">
      {modules_html}
    </div>
    <div class="actions">
      <button type="button" class="skip" data-skip="3">Skip (enable all)</button>
      <button type="submit" class="primary">Next</button>
    </div>
    <div class="err"></div>
  </form>

  <form class="step" data-step="4">
    <label>First department name</label>
    <input name="name" required placeholder="e.g. Engineering">
    <label>Code (optional)</label>
    <input name="code" placeholder="ENG">
    <div class="actions">
      <span></span>
      <button type="submit" class="primary">Next</button>
    </div>
    <div class="err"></div>
  </form>

  <form class="step" data-step="5">
    <div class="row">
      <div>
        <label>Employee code</label>
        <input name="employee_code" required placeholder="EMP-001">
      </div>
      <div>
        <label>Full name</label>
        <input name="full_name" required>
      </div>
    </div>
    <label>Email</label>
    <input name="email" type="email" required>
    <label class="checkbox-row">
      <input type="checkbox" name="seed_sample_data" value="1">
      Load sample data so the app isn't empty on first open
    </label>
    <div class="actions">
      <span></span>
      <button type="submit" class="primary">Finish</button>
    </div>
    <div class="err"></div>
  </form>
</div>

<script>
let current = 1;
let dept_id = null;
const TOTAL_STEPS = 5;

function showStep(n) {{
  document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
  const target = document.querySelector('.step[data-step="' + n + '"]');
  if (target) target.classList.add('active');
  for (let i = 1; i <= TOTAL_STEPS; i++) {{
    const d = document.getElementById('dot-' + i);
    if (!d) continue;
    d.classList.remove('active', 'done');
    if (i < n) d.classList.add('done');
    else if (i === n) d.classList.add('active');
  }}
  current = n;
}}

// --- AI step (step 2) — Connect, load models, enable Next ----------------
const aiProviderEl = document.getElementById('wiz-ai-provider');
const aiKeyEl = document.getElementById('wiz-ai-key');
const aiKeyHintEl = document.getElementById('wiz-ai-key-hint');
const aiConnectBtn = document.getElementById('wiz-ai-connect');
const aiStatusEl = document.getElementById('wiz-ai-status');
const aiModelWrap = document.getElementById('wiz-ai-model-wrap');
const aiModelSel = document.getElementById('wiz-ai-model');
const aiNextBtn = document.getElementById('wiz-ai-next');

const PROVIDER_HINTS = {{
  openrouter: 'Get an OpenRouter key at <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">openrouter.ai/keys</a> — free models work without billing.',
  upfyn: 'Get an Upfyn API key at <a href="https://ai.upfyn.com/" target="_blank" rel="noreferrer">ai.upfyn.com</a>.',
}};

function setAiStatus(msg, kind) {{
  aiStatusEl.textContent = msg || '';
  aiStatusEl.style.color = kind === 'err' ? 'var(--err, #f88)' : (kind === 'ok' ? 'var(--ok, #6c6)' : 'var(--mute)');
}}

if (aiProviderEl) {{
  aiProviderEl.addEventListener('change', () => {{
    const p = aiProviderEl.value;
    if (aiKeyHintEl) aiKeyHintEl.innerHTML = PROVIDER_HINTS[p] || '';
    aiKeyEl.placeholder = p === 'upfyn' ? 'upfyn-...' : 'sk-or-...';
    // Reset connect state — provider change invalidates the previous test.
    aiModelWrap.style.display = 'none';
    aiModelSel.innerHTML = '';
    aiNextBtn.disabled = true;
    setAiStatus('', '');
  }});
}}

if (aiConnectBtn) {{
  aiConnectBtn.addEventListener('click', async () => {{
    const provider = aiProviderEl.value;
    const key = (aiKeyEl.value || '').trim();
    if (!key) {{
      setAiStatus('Paste your API key first.', 'err');
      aiKeyEl.focus();
      return;
    }}
    aiConnectBtn.disabled = true;
    setAiStatus('Connecting & verifying key…', '');
    try {{
      const r = await fetch('/api/wizard', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          step: 2,
          data: {{ ai_provider: provider, ai_api_key: key, verify: true }},
        }}),
      }});
      const body = await r.json();
      if (!r.ok || !body.ok) {{
        setAiStatus(body.error || 'Connection failed.', 'err');
        return;
      }}
      // Populate model dropdown.
      const models = body.models || [];
      if (!models.length) {{
        setAiStatus('Connected, but provider returned no models. Try again or pick a different provider.', 'err');
        return;
      }}
      // Sort: free first, then paid; alpha within each group.
      models.sort((a, b) => (a.free === b.free) ? a.id.localeCompare(b.id) : (a.free ? -1 : 1));
      aiModelSel.innerHTML = '';
      const frees = models.filter(m => m.free);
      const paids = models.filter(m => !m.free);
      function addGroup(label, list) {{
        if (!list.length) return;
        const g = document.createElement('optgroup');
        g.label = label;
        for (const m of list) {{
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = (m.free ? '★ ' : '') + m.id;
          g.appendChild(opt);
        }}
        aiModelSel.appendChild(g);
      }}
      addGroup('Free models', frees);
      addGroup('Paid models', paids);
      // Default to first free model if any, else first paid.
      const def = frees[0] || paids[0];
      if (def) aiModelSel.value = def.id;
      aiModelWrap.style.display = '';
      aiNextBtn.disabled = false;
      setAiStatus('✓ Connected. ' + models.length + ' models available — pick one and click Next.', 'ok');
    }} catch (err) {{
      setAiStatus('Network error: ' + err, 'err');
    }} finally {{
      aiConnectBtn.disabled = false;
    }}
  }});
}}

// Module preset buttons.
document.querySelectorAll('.wm-quick button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const preset = btn.dataset.preset;
    document.querySelectorAll('#wm-grid input[type=checkbox]').forEach(box => {{
      if (box.disabled) return;  // always-on rows
      const slug = box.dataset.slug;
      const cat = box.closest('.wm-row').dataset.cat;
      let on = true;
      if (preset === 'core') on = false;
      else if (preset === 'hiring') on = (cat === 'hiring');
      else if (preset === 'hr') on = (cat !== 'hiring');
      // 'all' leaves everything on.
      box.checked = on;
    }});
  }});
}});

document.querySelectorAll('.step').forEach(form => {{
  form.addEventListener('submit', async (ev) => {{
    ev.preventDefault();
    const step = parseInt(form.dataset.step, 10);
    const fd = new FormData(form);
    const data = Object.fromEntries(fd.entries());
    // Step 3 (modules): collect the checkbox grid into an array.
    if (step === 3) {{
      const enabled = [];
      document.querySelectorAll('#wm-grid input[type=checkbox]').forEach(box => {{
        if (box.checked) enabled.push(box.dataset.slug);
      }});
      data.enabled_modules = enabled;
    }}
    if (step === 5 && dept_id !== null) data.department_id = dept_id;
    const errEl = form.querySelector('.err');
    errEl.textContent = '';
    try {{
      const r = await fetch('/api/wizard', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ step: step, data: data }}),
      }});
      const body = await r.json();
      if (!r.ok || !body.ok) {{
        errEl.textContent = body.error || ('Step ' + step + ' failed');
        return;
      }}
      if (step === 4 && body.department_id) dept_id = body.department_id;
      if (body.next_step) showStep(body.next_step);
      else if (body.done) window.location.href = '/m/employee';
    }} catch (err) {{
      errEl.textContent = String(err);
    }}
  }});
}});

document.querySelectorAll('button.skip').forEach(btn => {{
  btn.addEventListener('click', async () => {{
    const step = parseInt(btn.dataset.skip, 10);
    const r = await fetch('/api/wizard', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ step: step, data: {{ skip: true }} }}),
    }});
    const body = await r.json();
    if (body.next_step) showStep(body.next_step);
  }});
}});
</script>
</body>
</html>
"""
    return body


# ---------------------------------------------------------------------------
# Step handlers
# ---------------------------------------------------------------------------
def _ok(handler, **payload: Any) -> None:
    handler._json({"ok": True, **payload})


def _err(handler, msg: str, code: int = 400) -> None:
    handler._json({"ok": False, "error": msg}, code=code)


def _step1(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    name = (data.get("app_name") or "").strip()
    if not name:
        raise ValueError("app_name required")
    branding.set_settings(conn, {"app_name": name})
    return {"next_step": 2}


def _step2(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    if data.get("skip"):
        return {"next_step": 3}
    provider = (data.get("ai_provider") or "openrouter").strip().lower()
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"invalid AI provider: {provider}")
    key = (data.get("ai_api_key") or "").strip()
    model = (data.get("ai_model") or "").strip()

    # "Connect & load models" pre-flight: save provider + key, probe the
    # provider's /models endpoint, return the catalog so the wizard can
    # populate its model dropdown. Does NOT advance the wizard.
    if data.get("verify"):
        if not key:
            raise ValueError("API key required to connect")
        branding.set_settings(conn, {"ai_provider": provider, "ai_api_key": key})
        # Health-check first so we surface auth failures clearly. list_models()
        # uses the same key so a 401 here means the key is wrong.
        try:
            from . import ai as _ai
            health = _ai.health_check(conn)
            if not health.get("ok"):
                err = health.get("error") or "provider rejected the request"
                raise ValueError(f"connection failed: {err}")
            catalog = _ai.list_models(conn)
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface message to UI
            raise ValueError(f"connection failed: {exc}")
        if not catalog.get("ok"):
            raise ValueError(catalog.get("error") or "could not load models")
        return {
            "models": catalog.get("models", []),
            "verified": True,
        }

    # Normal Next: persist provider + key + model (model required so the
    # default OpenRouter free model isn't silently used for an Upfyn account).
    if not key:
        raise ValueError("API key required (or click Skip to configure later)")
    if not model:
        raise ValueError("pick a model from the list before continuing")
    branding.set_settings(conn, {
        "ai_provider": provider,
        "ai_api_key": key,
        "ai_model": model,
    })
    return {"next_step": 3}


def _step3(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    """Module enable/disable.

    Skip → leave the default (all modules on). Otherwise persist the user's
    selection via feature_flags.set_enabled_modules, which writes both
    config.json and the DB mirror.
    """
    if data.get("skip"):
        return {"next_step": 4}
    raw = data.get("enabled_modules")
    if not isinstance(raw, list):
        # Empty or missing → fall back to all-on (same as skip).
        return {"next_step": 4}
    try:
        feature_flags.set_enabled_modules(conn, raw)
    except ValueError as exc:
        raise ValueError(f"module selection: {exc}")
    return {"next_step": 4}


def _step4(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("department name required")
    code = (data.get("code") or "").strip() or None
    cur = conn.execute(
        "INSERT INTO department (name, code) VALUES (?, ?)",
        (name, code),
    )
    conn.commit()
    return {"next_step": 5, "department_id": int(cur.lastrowid)}


def _step5(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    code = (data.get("employee_code") or "").strip()
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip()
    if not code:
        raise ValueError("employee_code required")
    if not full_name:
        raise ValueError("full_name required")
    if not email:
        raise ValueError("email required")
    dept_id = data.get("department_id")
    try:
        dept_int = int(dept_id) if dept_id not in (None, "", 0) else None
    except (TypeError, ValueError):
        dept_int = None
    cur = conn.execute(
        "INSERT INTO employee (employee_code, full_name, email, department_id)"
        " VALUES (?, ?, ?, ?)",
        (code, full_name, email, dept_int),
    )
    conn.commit()
    result: dict[str, Any] = {"done": True, "employee_id": int(cur.lastrowid)}

    # Optional: seed canonical sample data so first-runners see a populated app.
    if data.get("seed_sample_data"):
        try:
            from . import seeds
            result["seeded"] = seeds.load_sample_data(conn)
        except Exception as exc:  # pragma: no cover - non-fatal
            log.warning("sample data seed failed: %s", exc)
            result["seed_error"] = str(exc)

    return result


_STEPS = {1: _step1, 2: _step2, 3: _step3, 4: _step4, 5: _step5}


def handle_wizard_step(handler, body: dict[str, Any]) -> None:
    """POST /api/wizard — dispatch a single wizard step.

    Body shape: ``{step: 1|2|3|4|5, data: {...}}``. Returns
    ``{ok: True, next_step|done, ...}``.
    """
    if not isinstance(body, dict):
        _err(handler, "invalid body")
        return
    raw_step = body.get("step")
    try:
        step = int(raw_step)
    except (TypeError, ValueError):
        _err(handler, "invalid step")
        return
    fn = _STEPS.get(step)
    if fn is None:
        _err(handler, f"unknown step {step}")
        return
    data = body.get("data") or {}
    if not isinstance(data, dict):
        _err(handler, "data must be an object")
        return
    conn = getattr(handler.server, "conn", None) if getattr(handler, "server", None) else None
    if conn is None:
        conn = getattr(handler, "conn", None)
    if conn is None:
        _err(handler, "no DB connection", code=500)
        return
    try:
        result = fn(conn, data)
    except (ValueError, sqlite3.IntegrityError) as exc:
        _err(handler, str(exc))
        return
    _ok(handler, **result)


__all__ = [
    "needs_wizard",
    "render_wizard_page",
    "handle_wizard_step",
]
