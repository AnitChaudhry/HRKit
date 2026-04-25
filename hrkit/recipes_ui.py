"""Recipes page — list, create, edit, delete, run.

Routes (wired by server.py):

    GET  /recipes                       -> render_recipes_page()
    GET  /api/recipes                   -> handle_list(handler)
    POST /api/recipes                   -> handle_save(handler, body)
    POST /api/recipes/<slug>/run        -> handle_run(handler, slug, body)
    DELETE /api/recipes/<slug>          -> handle_delete(handler, slug)

Stdlib only.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hrkit import ai, ai_tools, recipes
from hrkit.templates import render_module_page

log = logging.getLogger(__name__)


def _workspace_root_for(handler) -> Path | None:
    server = getattr(handler, "server", None)
    root = getattr(server, "workspace_root", None) if server else None
    if root:
        return Path(root)
    try:
        from hrkit import server as server_mod
        if getattr(server_mod, "ROOT", None):
            return Path(server_mod.ROOT)
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# AI integration — recipes are exposed as tools
# ---------------------------------------------------------------------------
def build_recipe_tools(conn, workspace_root: Path) -> list:
    """Return one callable per recipe + a generic ``run_recipe(slug, inputs)``.

    The chat agent picks these up via :func:`hrkit.chat.handle_chat_message`.
    Each per-recipe callable is a thin shim that invokes the same execution
    path as the UI button — so AI and the user share one code path.
    """
    if workspace_root is None:
        return []

    tools: list = []

    def run_recipe(slug: str, inputs: dict | None = None) -> str:
        """Execute a saved recipe by slug, filling its prompt template with `inputs`."""
        recipe = recipes.load_recipe(workspace_root, slug)
        if recipe is None:
            return f"error: no recipe with slug '{slug}'"
        return recipes.render_recipe(recipe, inputs or {})

    tools.append(run_recipe)
    return tools


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
_PAGE_BODY = r"""
<style>
.rec-shell{max-width:1080px;margin:0 auto;padding:8px 0 40px}
.rec-head{display:flex;justify-content:space-between;align-items:flex-start;
  gap:14px;margin-bottom:18px}
.rec-head h1{margin:0;font-size:22px;font-weight:600;letter-spacing:-0.01em}
.rec-head .sub{color:var(--dim);font-size:13px;margin-top:4px}
.rec-head button{padding:7px 12px;border-radius:6px;background:var(--accent);
  color:#fff;border:none;cursor:pointer;font-size:12.5px;font-weight:500}
.rec-head button:hover{filter:brightness(1.08)}
.rec-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:12px}
.rec-card{background:var(--panel);border:1px solid var(--border);border-radius:8px;
  padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.rec-card h3{margin:0;font-size:14px;font-weight:600}
.rec-card .desc{color:var(--dim);font-size:12.5px;line-height:1.45;margin:0}
.rec-card .tools{font-size:11px;color:var(--mute);font-family:'JetBrains Mono','Menlo',monospace;
  word-break:break-all}
.rec-card .acts{display:flex;justify-content:flex-end;gap:8px;margin-top:6px}
.rec-card .acts button{padding:6px 12px;border-radius:6px;background:var(--accent);
  color:#fff;border:none;cursor:pointer;font-size:12px}
.rec-card .acts button.ghost{background:transparent;border:1px solid var(--border);color:var(--dim)}
.rec-card .acts button.ghost:hover{color:var(--text);border-color:var(--accent)}
.rec-card .acts button.danger{background:transparent;border:1px solid var(--red);color:var(--red)}
.rec-card .acts button.danger:hover{background:var(--red);color:#fff}
.empty{padding:30px;text-align:center;color:var(--dim);font-style:italic;
  background:var(--panel);border:1px dashed var(--border);border-radius:8px}
#editor-dialog{padding:0;background:transparent;border:none}
#editor-dialog .panel{background:var(--panel);border:1px solid var(--border);
  border-radius:10px;padding:22px 26px;width:600px;max-width:92vw;color:var(--text);
  max-height:90vh;overflow-y:auto}
#editor-dialog h2{margin:0 0 12px;font-size:16px}
#editor-dialog label{display:block;font-size:12px;color:var(--dim);
  margin-top:10px;margin-bottom:4px}
#editor-dialog input,#editor-dialog textarea{width:100%;padding:8px 10px;
  background:var(--bg);color:var(--text);border:1px solid var(--border);
  border-radius:6px;font-size:13px;font-family:inherit}
#editor-dialog textarea{min-height:140px;resize:vertical;line-height:1.45}
#editor-dialog .row{display:flex;gap:10px}
#editor-dialog .row > *{flex:1}
#editor-dialog menu{display:flex;justify-content:flex-end;gap:8px;margin:18px 0 0;padding:0}
#editor-dialog menu button{padding:7px 14px;border-radius:6px;background:var(--accent);
  color:#fff;border:none;cursor:pointer;font-size:13px}
#editor-dialog menu button.ghost{background:transparent;border:1px solid var(--border);color:var(--dim)}
.toast{position:fixed;bottom:24px;right:24px;background:var(--panel);
  border:1px solid var(--border);border-radius:8px;padding:10px 16px;
  font-size:13px;z-index:50;max-width:360px}
.toast.error{border-color:var(--red);color:var(--red)}
.toast.ok{border-color:var(--green);color:var(--green)}
</style>
<div class="rec-shell">
  <div class="rec-head">
    <div>
      <h1>Recipes</h1>
      <div class="sub">Named HR automations the AI can run on demand or you can fire from a button.</div>
    </div>
    <button onclick="openEditor(null)">+ New recipe</button>
  </div>
  <div id="content"><div class="empty">Loading…</div></div>
</div>
<dialog id="editor-dialog">
  <div class="panel">
    <h2 id="editor-title">New recipe</h2>
    <input type="hidden" id="ed-original-slug" value="">
    <div class="row">
      <div>
        <label>Slug</label>
        <input id="ed-slug" placeholder="send-offer-letter">
      </div>
      <div>
        <label>Name</label>
        <input id="ed-name" placeholder="Send offer letter">
      </div>
    </div>
    <label>Description</label>
    <input id="ed-description" placeholder="One-line summary">
    <label>Tools (comma-separated upper-case slugs)</label>
    <input id="ed-tools" placeholder="GMAIL_SEND_EMAIL, WEB_SEARCH">
    <label>Inputs (comma-separated names; placeholders use {name})</label>
    <input id="ed-inputs" placeholder="candidate_name, candidate_email, position">
    <label>Trigger event (optional, e.g. recruitment.hired)</label>
    <input id="ed-trigger" placeholder="">
    <label>Prompt template</label>
    <textarea id="ed-body" placeholder="Send a warm offer letter to {candidate_name} at {candidate_email} for the {position} role."></textarea>
    <menu>
      <button class="ghost" type="button" onclick="document.getElementById('editor-dialog').close()">Cancel</button>
      <button type="button" onclick="saveRecipe()">Save</button>
    </menu>
  </div>
</dialog>
<script>
const content = document.getElementById('content');
let recipes = [];

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function toast(msg, level) {
  const el = document.createElement('div');
  el.className = 'toast ' + (level || '');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function renderCard(r) {
  const tools = (r.tools || []).join(', ') || '—';
  return (
    '<div class="rec-card" data-slug="' + escapeHtml(r.slug) + '">' +
    '<h3>' + escapeHtml(r.name) + '</h3>' +
    '<p class="desc">' + escapeHtml(r.description || '(no description)') + '</p>' +
    '<div class="tools">tools: ' + escapeHtml(tools) + '</div>' +
    '<div class="acts">' +
    '  <button class="danger" onclick="deleteRecipe(\'' + escapeHtml(r.slug) + '\')">Delete</button>' +
    '  <button class="ghost" onclick="openEditor(\'' + escapeHtml(r.slug) + '\')">Edit</button>' +
    '  <button onclick="runRecipe(\'' + escapeHtml(r.slug) + '\')">Run</button>' +
    '</div>' +
    '</div>'
  );
}

async function load() {
  content.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const r = await fetch('/api/recipes');
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || 'load failed');
    recipes = data.recipes || [];
    if (!recipes.length) {
      content.innerHTML = '<div class="empty">No recipes yet. Click <b>New recipe</b> to define your first one.</div>';
      return;
    }
    content.innerHTML = '<div class="rec-grid">' + recipes.map(renderCard).join('') + '</div>';
  } catch (err) {
    content.innerHTML = '<div class="empty">Failed to load: ' + escapeHtml(err.message || err) + '</div>';
  }
}

function openEditor(slug) {
  const dlg = document.getElementById('editor-dialog');
  const title = document.getElementById('editor-title');
  const set = (id, val) => document.getElementById(id).value = val || '';
  if (slug) {
    const r = recipes.find(x => x.slug === slug);
    if (!r) return;
    title.textContent = 'Edit recipe';
    set('ed-original-slug', r.slug);
    set('ed-slug', r.slug);
    set('ed-name', r.name);
    set('ed-description', r.description);
    set('ed-tools', (r.tools || []).join(', '));
    set('ed-inputs', (r.inputs || []).join(', '));
    set('ed-trigger', r.trigger);
    fetch('/api/recipes/' + encodeURIComponent(r.slug)).then(rs => rs.json()).then(d => {
      if (d.ok && d.recipe) set('ed-body', d.recipe.body || '');
    });
  } else {
    title.textContent = 'New recipe';
    set('ed-original-slug', '');
    set('ed-slug', '');
    set('ed-name', '');
    set('ed-description', '');
    set('ed-tools', '');
    set('ed-inputs', '');
    set('ed-trigger', '');
    set('ed-body', '');
  }
  dlg.showModal();
}

async function saveRecipe() {
  const get = (id) => document.getElementById(id).value.trim();
  const payload = {
    slug: get('ed-slug'),
    name: get('ed-name'),
    description: get('ed-description'),
    tools: get('ed-tools'),
    inputs: get('ed-inputs'),
    trigger: get('ed-trigger'),
    body: document.getElementById('ed-body').value,
  };
  if (!payload.slug || !payload.name) {
    toast('Slug and name are required', 'error');
    return;
  }
  try {
    const r = await fetch('/api/recipes', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || 'save failed');
    document.getElementById('editor-dialog').close();
    toast('Saved ' + payload.slug, 'ok');
    load();
  } catch (err) {
    toast('Save failed: ' + (err.message || err), 'error');
  }
}

async function deleteRecipe(slug) {
  if (!confirm('Delete recipe ' + slug + '?')) return;
  try {
    const r = await fetch('/api/recipes/' + encodeURIComponent(slug), {method: 'DELETE'});
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || 'delete failed');
    toast('Deleted', 'ok');
    load();
  } catch (err) {
    toast('Delete failed: ' + (err.message || err), 'error');
  }
}

async function runRecipe(slug) {
  const recipe = recipes.find(r => r.slug === slug);
  if (!recipe) return;
  const inputs = {};
  for (const name of (recipe.inputs || [])) {
    const v = prompt('Value for ' + name + ':');
    if (v === null) return;
    inputs[name] = v;
  }
  try {
    const r = await fetch('/api/recipes/' + encodeURIComponent(slug) + '/run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({inputs}),
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || 'run failed');
    alert('Recipe reply:\n\n' + (data.reply || '(no reply)'));
  } catch (err) {
    toast('Run failed: ' + (err.message || err), 'error');
  }
}

load();
</script>
"""


def render_recipes_page() -> str:
    return render_module_page(title="Recipes", nav_active="", body_html=_PAGE_BODY)


# ---------------------------------------------------------------------------
# JSON API handlers
# ---------------------------------------------------------------------------
def handle_list(handler) -> None:
    workspace_root = _workspace_root_for(handler)
    if workspace_root is None:
        handler._json({"ok": True, "recipes": []})
        return
    try:
        items = recipes.list_recipes(workspace_root)
    except Exception as exc:  # noqa: BLE001
        log.exception("recipes.list failed")
        handler._json({"ok": False, "error": str(exc)}, code=500)
        return
    handler._json({"ok": True, "recipes": items})


def handle_get(handler, slug: str) -> None:
    workspace_root = _workspace_root_for(handler)
    if workspace_root is None:
        handler._json({"ok": False, "error": "workspace not configured"}, code=400)
        return
    recipe = recipes.load_recipe(workspace_root, slug)
    if recipe is None:
        handler._json({"ok": False, "error": "not found"}, code=404)
        return
    handler._json({"ok": True, "recipe": recipe})


def handle_save(handler, body: dict[str, Any]) -> None:
    workspace_root = _workspace_root_for(handler)
    if workspace_root is None:
        handler._json({"ok": False, "error": "workspace not configured"}, code=400)
        return
    body = body or {}
    slug = (body.get("slug") or "").strip()
    name = (body.get("name") or "").strip()
    if not slug or not name:
        handler._json({"ok": False, "error": "slug and name are required"}, code=400)
        return
    try:
        out = recipes.save_recipe(
            workspace_root=workspace_root,
            slug=slug,
            name=name,
            description=body.get("description") or "",
            tools=recipes._coerce_list(body.get("tools")),
            inputs=recipes._coerce_list(body.get("inputs")),
            trigger=body.get("trigger") or "",
            body=body.get("body") or "",
        )
    except (ValueError, OSError) as exc:
        handler._json({"ok": False, "error": str(exc)}, code=400)
        return
    handler._json({"ok": True, **out})


def handle_delete(handler, slug: str) -> None:
    workspace_root = _workspace_root_for(handler)
    if workspace_root is None:
        handler._json({"ok": False, "error": "workspace not configured"}, code=400)
        return
    deleted = recipes.delete_recipe(workspace_root, slug)
    handler._json({"ok": True, "deleted": deleted})


def handle_run(handler, slug: str, body: dict[str, Any]) -> None:
    """POST /api/recipes/<slug>/run — fill template + call AI scoped to recipe.tools."""
    import asyncio
    from hrkit import branding

    workspace_root = _workspace_root_for(handler)
    if workspace_root is None:
        handler._json({"ok": False, "error": "workspace not configured"}, code=400)
        return
    recipe = recipes.load_recipe(workspace_root, slug)
    if recipe is None:
        handler._json({"ok": False, "error": "not found"}, code=404)
        return
    body = body or {}
    inputs = body.get("inputs") if isinstance(body.get("inputs"), dict) else {}
    rendered = recipes.render_recipe(recipe, inputs)
    conn = handler.server.conn  # type: ignore[attr-defined]

    # Restrict the AI to the recipe's whitelisted tools (intersected with the
    # always-on web tools so even free models can do a web lookup if asked).
    allowed_slugs = {s.upper() for s in recipe.get("tools") or []}
    tools: list = list(ai_tools.builtin_tools()) if not allowed_slugs else []
    if allowed_slugs:
        for t in ai_tools.builtin_tools():
            if t.__name__.upper() in allowed_slugs:
                tools.append(t)

    system = (
        f"You are an HR assistant for {branding.app_name()}. "
        f"Run the recipe '{recipe['name']}': "
        f"{recipe.get('description') or 'no description provided'}. "
        f"Allowed tools: {', '.join(sorted(allowed_slugs)) or 'none beyond defaults'}. "
        "Confirm before any irreversible action."
    )

    try:
        reply = asyncio.run(ai.run_agent(rendered, conn=conn, system=system, tools=tools))
    except RuntimeError as exc:
        handler._json({"ok": False, "error": str(exc)}, code=502)
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("recipe.run failed")
        handler._json({"ok": False, "error": ai.friendly_error(exc)}, code=500)
        return
    handler._json({"ok": True, "reply": reply, "rendered_prompt": rendered})


__all__ = [
    "render_recipes_page",
    "build_recipe_tools",
    "handle_list",
    "handle_get",
    "handle_save",
    "handle_delete",
    "handle_run",
]
