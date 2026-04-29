"""Integrations page — generic catalog of Composio apps + per-tool toggles.

Routes (wired by server.py):

    GET  /integrations                  -> render_integrations_page(conn)
    GET  /api/integrations/state        -> handle_state(handler)
    POST /api/integrations/connect      -> handle_connect(handler, body)
    POST /api/integrations/tool         -> handle_tool_toggle(handler, body)
    POST /api/integrations/test         -> handle_tool_test(handler, body)

Design notes:
* The Composio toolkit catalog has 200+ entries — rendering all of them at
  page-load time is unusable. We render a CURATED set (the apps most HR
  teams reach for) and provide a search box that proxies to
  ``composio_sdk.list_apps`` for everything else.
* OAuth is Composio-hosted: ``composio_sdk.init_connection`` returns a
  ``redirect_url`` that the user clicks in a new tab; Composio handles
  the callback, so this app needs no callback endpoint.
* Per-tool on/off state is persisted in ``settings.COMPOSIO_DISABLED_TOOLS``
  as a JSON list (default: every tool enabled). The AI agent honors this
  list via :func:`hrkit.branding.composio_disabled_tools`.
* The page degrades gracefully when no Composio key is on file: it shows
  an empty-state card pointing at /settings.

Stdlib only.
"""

from __future__ import annotations

import html
import logging
import sqlite3
from typing import Any

from hrkit import branding, composio_sdk
from hrkit.templates import render_module_page

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Curated catalog — the apps that show up before the user types in search
# ---------------------------------------------------------------------------
CURATED_APPS: list[dict[str, str]] = [
    {"slug": "gmail",          "name": "Gmail",
     "description": "Send and pull emails into recruitment + offer letters."},
    {"slug": "googlecalendar", "name": "Google Calendar",
     "description": "Block calendars when leave is approved."},
    {"slug": "googledrive",    "name": "Google Drive",
     "description": "Archive payslips and contracts to Drive."},
    {"slug": "slack",          "name": "Slack",
     "description": "Notify channels on hire, leave, payroll events."},
    {"slug": "notion",         "name": "Notion",
     "description": "Sync HR records into a Notion knowledge base."},
    {"slug": "linear",         "name": "Linear",
     "description": "Open onboarding tasks for new hires."},
    {"slug": "github",         "name": "GitHub",
     "description": "Provision repo access on hire, revoke on exit."},
    {"slug": "hubspot",        "name": "HubSpot",
     "description": "Pull candidates from your sales/recruiting CRM."},
]


# ---------------------------------------------------------------------------
# State assembly
# ---------------------------------------------------------------------------
def _connected_by_slug(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Return ``{toolkit_slug: [connection, ...]}`` from the SDK."""
    out: dict[str, list[dict]] = {}
    for c in composio_sdk.list_connections(conn):
        slug = (c.get("toolkit_slug") or "").lower()
        if not slug:
            continue
        out.setdefault(slug, []).append(c)
    return out


def _actions_for(conn: sqlite3.Connection, slug: str) -> list[dict[str, Any]]:
    """List actions for an app, decorated with the user's enabled/disabled state."""
    disabled = branding.composio_disabled_tools(conn)
    actions = composio_sdk.list_actions(conn, app_slug=slug, limit=100)
    decorated: list[dict[str, Any]] = []
    for a in actions:
        if a.get("deprecated"):
            continue
        decorated.append({
            "slug": a["slug"],
            "name": a["name"] or a["slug"],
            "description": a["description"],
            "enabled": a["slug"] not in disabled,
        })
    return decorated


def _enabled_tool_slugs(state: dict[str, Any]) -> list[str]:
    """Return enabled Composio action slugs from a get_state payload."""
    slugs: list[str] = []
    for app in state.get("connected") or []:
        for action in app.get("actions") or []:
            if action.get("enabled") and action.get("slug"):
                slugs.append(str(action["slug"]).upper())
    return sorted(set(slugs))


def search_apps(conn: sqlite3.Connection, query: str = "",
                limit: int = 60) -> list[dict[str, Any]]:
    """Return apps matching ``query`` from the live Composio catalog.

    Used by the /integrations page search box to reach beyond the 8 curated
    apps. Falls back to filtering ``CURATED_APPS`` if the SDK is unreachable.
    """
    q = (query or "").strip().lower()
    try:
        all_apps = composio_sdk.list_apps(conn, limit=200)
    except Exception:
        all_apps = []
    if not all_apps:
        all_apps = list(CURATED_APPS)
    if q:
        out = [a for a in all_apps
               if q in (a.get("slug") or "").lower()
               or q in (a.get("name") or "").lower()
               or q in (a.get("description") or "").lower()]
    else:
        out = list(all_apps)
    return out[:limit]


def handle_search(handler) -> None:
    """GET /api/integrations/search?q=<query> — search the Composio catalog."""
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(handler.path)
    q = parse_qs(parsed.query).get("q", [""])[0]
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        results = search_apps(conn, q)
    except Exception as exc:  # noqa: BLE001
        log.exception("search_apps failed")
        handler._json({"ok": False, "error": str(exc)}, code=500)
        return
    handler._json({"ok": True, "query": q, "results": results})


def get_state(conn: sqlite3.Connection) -> dict[str, Any]:
    """Assemble the JSON payload that powers the integrations page."""
    configured = composio_sdk.is_configured(conn)
    if not configured:
        return {
            "ok": True,
            "configured": False,
            "connected": [],
            "available": list(CURATED_APPS),
            "mcp": composio_sdk.mcp_state(conn),
        }

    connected_map = _connected_by_slug(conn)

    connected: list[dict[str, Any]] = []
    for slug, conns in connected_map.items():
        # Pick a friendly name from the catalog if we have one, else the slug.
        catalog_match = next((a for a in CURATED_APPS if a["slug"] == slug), None)
        name = catalog_match["name"] if catalog_match else slug.title()
        connected.append({
            "slug": slug,
            "name": name,
            "description": catalog_match["description"] if catalog_match else "",
            "connections": [
                {"id": c["id"], "status": c["status"], "created_at": c["created_at"]}
                for c in conns
            ],
            "actions": _actions_for(conn, slug),
        })

    # Available = curated minus already-connected (so we don't show duplicate cards).
    available = [a for a in CURATED_APPS if a["slug"] not in connected_map]
    return {
        "ok": True,
        "configured": True,
        "connected": connected,
        "available": available,
        "mcp": composio_sdk.mcp_state(conn),
    }


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
_PAGE_BODY = r"""
<style>
.intg-shell{max-width:1100px;margin:0 auto;padding:8px 0 40px}
.intg-head{display:flex;justify-content:space-between;align-items:flex-start;
  gap:14px;margin-bottom:18px}
.intg-head h1{margin:0;font-size:22px;font-weight:600;letter-spacing:-0.01em}
.intg-head .sub{color:var(--dim);font-size:13px;margin-top:4px}
.intg-head button{padding:7px 12px;border-radius:6px;background:transparent;
  color:var(--dim);border:1px solid var(--border);cursor:pointer;font-size:12px}
.intg-head button:hover{color:var(--text);border-color:var(--accent)}
.banner{background:var(--panel);border:1px solid var(--border);border-radius:8px;
  padding:16px 18px;margin-bottom:22px;display:flex;justify-content:space-between;
  align-items:center;gap:12px}
.banner.warn{border-color:var(--amber);color:var(--text)}
.banner a{color:var(--accent);text-decoration:none;font-weight:500}
.banner a:hover{text-decoration:underline}
.section-title{font-size:11px;color:var(--dim);text-transform:uppercase;
  letter-spacing:0.6px;margin:18px 0 10px;font-weight:600}
.search-box{margin-bottom:14px;width:100%;max-width:380px;padding:8px 12px;
  background:var(--panel);border:1px solid var(--border);border-radius:6px;
  color:var(--text);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
  gap:12px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:8px;
  padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.card.preview{opacity:0.55;filter:saturate(0.6)}
.card.preview:hover{opacity:0.8}
.card .card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.card .card-name{font-weight:600;font-size:14px;margin:0}
.card .card-desc{color:var(--dim);font-size:12.5px;line-height:1.45;margin:0}
.badge{font-size:10.5px;padding:2px 8px;border-radius:10px;text-transform:uppercase;
  letter-spacing:0.5px;font-weight:600}
.badge.active{background:color-mix(in srgb,var(--green) 20%,transparent);color:var(--green)}
.badge.idle{background:color-mix(in srgb,var(--dim) 20%,transparent);color:var(--dim)}
.badge.expired{background:color-mix(in srgb,var(--red) 20%,transparent);color:var(--red)}
.card-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:6px}
.card-actions button{padding:6px 12px;border-radius:6px;background:var(--accent);
  color:#fff;border:none;cursor:pointer;font-size:12px;font-weight:500}
.card-actions button.ghost{background:transparent;border:1px solid var(--border);color:var(--dim)}
.card-actions button.ghost:hover{color:var(--text);border-color:var(--accent)}
.tools{margin-top:8px;border-top:1px solid var(--border);padding-top:10px;
  display:flex;flex-direction:column;gap:6px;max-height:280px;overflow-y:auto}
.tool-row{display:flex;align-items:center;gap:8px;font-size:12.5px}
.tool-row .tool-toggle{position:relative;width:30px;height:16px;
  background:var(--border);border-radius:10px;cursor:pointer;flex-shrink:0;
  transition:background .15s}
.tool-row .tool-toggle.on{background:var(--accent)}
.tool-row .tool-toggle::after{content:"";position:absolute;width:12px;height:12px;
  background:#fff;border-radius:50%;top:2px;left:2px;transition:transform .15s}
.tool-row .tool-toggle.on::after{transform:translateX(14px)}
.tool-row .tool-name{font-family:'JetBrains Mono','Menlo',monospace;font-size:11.5px;
  color:var(--text);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tool-row .tool-test{padding:3px 8px;font-size:10.5px;background:transparent;
  border:1px solid var(--border);color:var(--dim);border-radius:5px;cursor:pointer}
.tool-row .tool-test:hover{color:var(--text);border-color:var(--accent)}
.empty{padding:30px;text-align:center;color:var(--dim);font-style:italic;
  background:var(--panel);border:1px dashed var(--border);border-radius:8px}
#oauth-dialog{padding:22px 26px}
#oauth-dialog .panel{background:transparent;border:none;padding:0;color:var(--text)}
#oauth-dialog .panel h2{margin:0 0 8px;font-size:16px}
#oauth-dialog .panel p{margin:0 0 12px;color:var(--dim);font-size:13px}
#oauth-dialog .panel a{color:var(--accent);word-break:break-all;font-size:12px;
  display:block;background:var(--bg);padding:8px 10px;border-radius:6px;
  border:1px solid var(--border);margin-bottom:12px}
#oauth-dialog .panel menu{display:flex;justify-content:flex-end;gap:8px;margin:0}
#oauth-dialog .panel button{padding:7px 14px;border-radius:6px;background:var(--accent);
  color:#fff;border:none;cursor:pointer;font-size:13px}
#oauth-dialog .panel button.ghost{background:transparent;border:1px solid var(--border);color:var(--dim)}
.toast{position:fixed;bottom:24px;right:24px;background:var(--panel);
  border:1px solid var(--border);border-radius:8px;padding:10px 16px;
  font-size:13px;z-index:50;max-width:360px}
.toast.error{border-color:var(--red);color:var(--red)}
.toast.ok{border-color:var(--green);color:var(--green)}
.ghost-btn{padding:4px 10px;border-radius:5px;background:transparent;
  color:var(--dim);border:1px solid var(--border);cursor:pointer;font-size:11px;
  text-transform:none;letter-spacing:0}
.ghost-btn:hover{color:var(--text);border-color:var(--accent)}
.mcp-panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;
  padding:14px 16px;margin-bottom:18px;display:grid;gap:8px}
.mcp-panel .mcp-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.mcp-panel h3{margin:0;font-size:14px}
.mcp-panel p{margin:0;color:var(--dim);font-size:12.5px;line-height:1.5}
.mcp-panel code{background:var(--bg);padding:2px 6px;border-radius:4px;word-break:break-all}
.mcp-panel button{padding:6px 12px;border-radius:6px;background:var(--accent);
  color:#fff;border:none;cursor:pointer;font-size:12px;font-weight:500}
</style>
<div class="intg-shell">
  <div class="intg-head">
    <div>
      <h1>Integrations</h1>
      <div class="sub">Connect Composio apps. Anything you turn on here becomes available to the AI assistant.</div>
    </div>
    <button onclick="loadState(true)">Refresh</button>
  </div>
  <div id="content"><div class="empty">Loading…</div></div>
</div>
<dialog id="oauth-dialog">
  <div class="panel">
    <h2>Complete authorization</h2>
    <p>Open this link in your browser to finish connecting. When the page says success, return here and click Refresh.</p>
    <a id="oauth-url" target="_blank" rel="noopener">…</a>
    <menu>
      <button class="ghost" type="button" onclick="document.getElementById('oauth-dialog').close()">Close</button>
      <button type="button" onclick="window.open(document.getElementById('oauth-url').href, '_blank'); document.getElementById('oauth-dialog').close(); loadState(true)">Open + refresh</button>
    </menu>
  </div>
</dialog>
<script>
const content = document.getElementById('content');
let cachedState = null;

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

function statusBadge(status) {
  const s = (status || '').toLowerCase();
  if (s === 'active') return '<span class="badge active">Connected</span>';
  if (s === 'expired' || s === 'failed') return '<span class="badge expired">' + escapeHtml(status) + '</span>';
  return '<span class="badge idle">' + escapeHtml(status || 'pending') + '</span>';
}

function renderMcpPanel(state) {
  const mcp = state.mcp || {};
  const enabledCount = (state.connected || []).reduce((total, app) => {
    return total + (app.actions || []).filter(a => a.enabled).length;
  }, 0);
  const connectedCount = (state.connected || []).length;
  const details = mcp.configured
    ? '<p>MCP server <code>' + escapeHtml(mcp.server_id) + '</code> is synced with ' +
      escapeHtml((mcp.allowed_tools || []).length) + ' allowed tool(s).</p>' +
      (mcp.server_url ? '<p>URL: <code>' + escapeHtml(mcp.server_url) + '</code></p>' : '')
    : '<p>No MCP server synced yet. Sync after connecting apps so MCP clients see the same enabled tools HR selected here.</p>';
  return (
    '<div class="mcp-panel">' +
    '<div class="mcp-top"><div>' +
    '<h3>Composio MCP tool access</h3>' +
    '<p>' + connectedCount + ' connected app(s), ' + enabledCount + ' enabled tool(s). Tool toggles below also control the in-app AI assistant.</p>' +
    '</div><button onclick="syncMcp()" ' + (connectedCount ? '' : 'disabled') + '>Sync MCP tools</button></div>' +
    details +
    '</div>'
  );
}

function renderToolRow(appSlug, tool) {
  const toggleCls = tool.enabled ? 'tool-toggle on' : 'tool-toggle';
  return (
    '<div class="tool-row" data-slug="' + escapeHtml(tool.slug) + '">' +
    '<div class="' + toggleCls + '" onclick="toggleTool(this, \'' + escapeHtml(tool.slug) + '\')"></div>' +
    '<div class="tool-name" title="' + escapeHtml(tool.description) + '">' + escapeHtml(tool.slug) + '</div>' +
    '<button class="tool-test" onclick="testTool(\'' + escapeHtml(appSlug) + '\', \'' + escapeHtml(tool.slug) + '\')">Test</button>' +
    '</div>'
  );
}

function renderConnectedCard(app) {
  const status = app.connections.length ? app.connections[0].status : '';
  const tools = app.actions.length
    ? app.actions.map(a => renderToolRow(app.slug, a)).join('')
    : '<div class="empty" style="padding:14px;font-size:12px">No actions surfaced for this app yet.</div>';
  return (
    '<div class="card" data-slug="' + escapeHtml(app.slug) + '">' +
    '  <div class="card-head">' +
    '    <div>' +
    '      <h3 class="card-name">' + escapeHtml(app.name) + '</h3>' +
    '      <p class="card-desc">' + escapeHtml(app.description || '') + '</p>' +
    '    </div>' +
    '    ' + statusBadge(status) +
    '  </div>' +
    '  <div class="tools">' + tools + '</div>' +
    '</div>'
  );
}

function renderAvailableCard(app) {
  return (
    '<div class="card" data-slug="' + escapeHtml(app.slug) + '">' +
    '  <div class="card-head">' +
    '    <h3 class="card-name">' + escapeHtml(app.name) + '</h3>' +
    '  </div>' +
    '  <p class="card-desc">' + escapeHtml(app.description || '') + '</p>' +
    '  <div class="card-actions">' +
    '    <button onclick="connectApp(\'' + escapeHtml(app.slug) + '\')">Connect</button>' +
    '  </div>' +
    '</div>'
  );
}

function render(state) {
  if (!state.configured) {
    // Show a preview of what's possible, even without a key — the curated
    // catalog is rendered in disabled/locked state with a single CTA.
    const previewCards = (state.available || []).map(function(app) {
      return (
        '<div class="card preview" data-slug="' + escapeHtml(app.slug) + '">' +
        '<div class="card-head">' +
        '<h3 class="card-name">' + escapeHtml(app.name) + '</h3>' +
        '<span class="badge idle">locked</span>' +
        '</div>' +
        '<p class="card-desc">' + escapeHtml(app.description || '') + '</p>' +
        '</div>'
      );
    }).join('');
    content.innerHTML = (
      '<div class="banner warn">' +
      '<span>Add your Composio API key on the <a href="/settings">Settings page</a> to unlock these integrations. ' +
      'Composio handles the OAuth flow for Gmail, Drive, Slack, and 200+ other apps.</span>' +
      '</div>' +
      '<div class="section-title">Apps you\'ll be able to connect (' + (state.available || []).length + ')</div>' +
      '<div class="cards">' + previewCards + '</div>' +
      '<p style="margin-top:18px;font-size:12px;color:var(--dim);text-align:center">' +
      'Don\'t have a Composio key? Get one free at <a href="https://app.composio.dev/" target="_blank" rel="noopener">app.composio.dev</a> — sign up, copy the key, paste it on Settings.</p>'
    );
    return;
  }
  const parts = [];
  parts.push(renderMcpPanel(state));
  parts.push('<div class="section-title">Connected (' + state.connected.length + ')</div>');
  if (state.connected.length === 0) {
    parts.push('<div class="empty">No connected apps yet. Click <b>Connect a new app</b> below to get started.</div>');
  } else {
    parts.push('<div class="cards">' + state.connected.map(renderConnectedCard).join('') + '</div>');
  }
  // Available apps are hidden by default (per the user "only connected apps"
  // directive). Reveal-on-click keeps the curated catalog as a starting point
  // for new connections without rendering a 200-card wall on every visit.
  parts.push(
    '<div class="section-title" style="display:flex;justify-content:space-between;align-items:center">' +
    '<span>Available to connect (' + state.available.length + ')</span>' +
    '<button class="ghost-btn" onclick="toggleAvailable()">Show / hide</button>' +
    '</div>'
  );
  parts.push(
    '<div id="available-wrap" style="display:none">' +
    '<input type="search" class="search-box" placeholder="Search 200+ apps (Gmail, Slack, Notion, …)" oninput="searchAvailable(this.value)">' +
    '<div class="cards" id="available-cards">' + state.available.map(renderAvailableCard).join('') + '</div>' +
    '</div>'
  );
  content.innerHTML = parts.join('');
}

function toggleAvailable() {
  const w = document.getElementById('available-wrap');
  if (!w) return;
  w.style.display = (w.style.display === 'none') ? '' : 'none';
}

let _searchTimer = null;
async function searchAvailable(q) {
  // Debounced server-side search hitting the live Composio catalog (200+ apps).
  // Empty query falls back to the curated set already in the DOM.
  if (_searchTimer) clearTimeout(_searchTimer);
  _searchTimer = setTimeout(async function() {
    const wrap = document.getElementById('available-cards');
    if (!wrap) return;
    if (!q || !q.trim()) {
      // Restore the curated set from cached state.
      if (cachedState && cachedState.available) {
        wrap.innerHTML = cachedState.available.map(renderAvailableCard).join('');
      }
      return;
    }
    wrap.innerHTML = '<div class="empty" style="grid-column:1/-1">Searching…</div>';
    try {
      const r = await fetch('/api/integrations/search?q=' + encodeURIComponent(q));
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || 'search failed');
      if (!j.results.length) {
        wrap.innerHTML = '<div class="empty" style="grid-column:1/-1">No apps match "' + escapeHtml(q) + '".</div>';
        return;
      }
      wrap.innerHTML = j.results.map(renderAvailableCard).join('');
    } catch (err) {
      wrap.innerHTML = '<div class="empty" style="grid-column:1/-1">Search failed: ' + escapeHtml(err.message || err) + '</div>';
    }
  }, 250);
}

async function loadState(showToast) {
  content.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const r = await fetch('/api/integrations/state');
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || 'load failed');
    cachedState = data;
    render(data);
    if (showToast) toast('Refreshed', 'ok');
  } catch (err) {
    content.innerHTML = '<div class="banner warn">Failed to load: ' + escapeHtml(err.message || err) + '</div>';
  }
}

async function connectApp(slug) {
  try {
    const r = await fetch('/api/integrations/connect', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({app_slug: slug}),
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || 'connect failed');
    if (!data.redirect_url) throw new Error('Composio did not return an OAuth URL.');
    const link = document.getElementById('oauth-url');
    link.href = data.redirect_url;
    link.textContent = data.redirect_url;
    document.getElementById('oauth-dialog').showModal();
  } catch (err) {
    toast('Connect failed: ' + (err.message || err), 'error');
  }
}

async function toggleTool(el, slug) {
  const enable = !el.classList.contains('on');
  try {
    const r = await fetch('/api/integrations/tool', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slug, enabled: enable}),
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || 'toggle failed');
    el.classList.toggle('on', enable);
    toast((enable ? 'Enabled ' : 'Disabled ') + slug + '. Sync MCP to update external clients.', 'ok');
  } catch (err) {
    toast('Toggle failed: ' + (err.message || err), 'error');
  }
}

async function syncMcp() {
  toast('Syncing Composio MCP tools…');
  try {
    const r = await fetch('/api/integrations/mcp/sync', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || 'MCP sync failed');
    toast('MCP synced: ' + data.allowed_tools.length + ' tool(s) allowed', 'ok');
    loadState(false);
  } catch (err) {
    toast('MCP sync failed: ' + (err.message || err), 'error');
  }
}

async function testTool(appSlug, slug) {
  toast('Testing ' + slug + '…');
  try {
    const r = await fetch('/api/integrations/test', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slug, app_slug: appSlug}),
    });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || 'test failed');
    if (data.successful === false) {
      toast('Test ran but Composio returned an error: ' + (data.error || 'see logs'), 'error');
    } else {
      toast('Test OK: ' + slug, 'ok');
    }
  } catch (err) {
    toast('Test failed: ' + (err.message || err), 'error');
  }
}

loadState(false);
</script>
"""


def render_integrations_page(conn: sqlite3.Connection) -> str:
    """Return the full HTML for ``GET /integrations``."""
    return render_module_page(
        title="Integrations",
        nav_active="",
        body_html=_PAGE_BODY,
    )


# ---------------------------------------------------------------------------
# JSON API handlers
# ---------------------------------------------------------------------------
def handle_state(handler) -> None:
    """GET /api/integrations/state — return the page-state payload."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        handler._json(get_state(conn))
    except Exception as exc:  # noqa: BLE001
        log.exception("integrations state failed")
        handler._json({"ok": False, "error": str(exc)}, code=500)


def handle_connect(handler, body: dict[str, Any]) -> None:
    """POST /api/integrations/connect — start an OAuth flow."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    body = body or {}
    slug = (body.get("app_slug") or "").strip().lower()
    if not slug:
        handler._json({"ok": False, "error": "app_slug is required"}, code=400)
        return
    try:
        result = composio_sdk.init_connection(conn, slug)
    except Exception as exc:  # noqa: BLE001
        log.exception("integrations connect failed")
        handler._json({"ok": False, "error": str(exc)}, code=500)
        return
    if result.get("error"):
        handler._json({"ok": False, "error": result["error"]}, code=400)
        return
    handler._json({
        "ok": True,
        "redirect_url": result.get("redirect_url", ""),
        "connected_account_id": result.get("connected_account_id", ""),
    })


def handle_tool_toggle(handler, body: dict[str, Any]) -> None:
    """POST /api/integrations/tool — enable/disable a single action slug."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    body = body or {}
    slug = (body.get("slug") or "").strip().upper()
    enabled = bool(body.get("enabled"))
    if not slug:
        handler._json({"ok": False, "error": "slug is required"}, code=400)
        return
    disabled = set(branding.composio_disabled_tools(conn))
    if enabled:
        disabled.discard(slug)
    else:
        disabled.add(slug)
    branding.set_composio_disabled_tools(conn, disabled)
    handler._json({"ok": True, "enabled": enabled, "slug": slug})


def handle_tool_test(handler, body: dict[str, Any]) -> None:
    """POST /api/integrations/test — run a single action with an empty payload."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    body = body or {}
    slug = (body.get("slug") or "").strip().upper()
    if not slug:
        handler._json({"ok": False, "error": "slug is required"}, code=400)
        return
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    try:
        result = composio_sdk.execute_action(conn, slug, payload)
    except Exception as exc:  # noqa: BLE001
        log.exception("integrations test failed")
        handler._json({"ok": False, "error": str(exc)}, code=500)
        return
    handler._json({
        "ok": True,
        "successful": bool(result.get("successful")),
        "error": result.get("error", ""),
        "data": result.get("data") or {},
    })


def handle_mcp_sync(handler, body: dict[str, Any] | None = None) -> None:
    """POST /api/integrations/mcp/sync — mirror UI tool toggles to MCP."""
    conn = handler.server.conn  # type: ignore[attr-defined]
    try:
        state = get_state(conn)
        toolkits = [str(app["slug"]) for app in state.get("connected") or [] if app.get("slug")]
        allowed_tools = _enabled_tool_slugs(state)
        result = composio_sdk.sync_mcp_server(
            conn,
            toolkits=toolkits,
            allowed_tools=allowed_tools,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("integrations MCP sync failed")
        handler._json({"ok": False, "error": str(exc)}, code=500)
        return
    if not result.get("ok"):
        handler._json({"ok": False, "error": result.get("error", "MCP sync failed")}, code=400)
        return
    handler._json({
        "ok": True,
        "server_id": result.get("server_id", ""),
        "server_url": result.get("server_url", ""),
        "toolkits": result.get("toolkits", []),
        "allowed_tools": result.get("allowed_tools", []),
    })


__all__ = [
    "CURATED_APPS",
    "get_state",
    "render_integrations_page",
    "handle_state",
    "handle_connect",
    "handle_tool_toggle",
    "handle_tool_test",
    "handle_mcp_sync",
]
