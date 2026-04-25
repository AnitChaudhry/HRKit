from __future__ import annotations
import html as htmllib
import json
from typing import Any

from .config import COLUMN_ACCENT, COLUMN_LABEL, STATUS_TO_COLUMN
from .models import Folder
from . import branding


CSS = r"""
:root[data-theme="dark"] {
  --bg:#08090a; --surface:#0f1115; --panel:#14171d;
  --border:rgba(255,255,255,0.08); --border-s:rgba(255,255,255,0.16);
  --text:#e8eaed; --dim:#9aa0a6; --mute:#5f6368;
  --accent:#6366f1; --cyan:#22d3ee; --amber:#f59e0b;
  --green:#10b981; --red:#f43f5e; --violet:#8b5cf6;
}
:root[data-theme="light"] {
  --bg:#faf9f6; --surface:#ffffff; --panel:#f5f3ee;
  --border:rgba(15,23,42,0.10); --border-s:rgba(15,23,42,0.20);
  --text:#1a1a1a; --dim:#5c5c5c; --mute:#909090;
  --accent:#4f46e5; --cyan:#0891b2; --amber:#d97706;
  --green:#059669; --red:#dc2626; --violet:#7c3aed;
}
*{box-sizing:border-box}
*{scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--dim) 30%,transparent) transparent}
*::-webkit-scrollbar{width:9px;height:9px}
*::-webkit-scrollbar-track{background:transparent}
*::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--dim) 30%,transparent);
  border-radius:5px;border:2px solid transparent;background-clip:padding-box}
*::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb,var(--dim) 55%,transparent);
  background-clip:padding-box;border:2px solid transparent}
*::-webkit-scrollbar-corner{background:transparent}
html,body{margin:0;padding:0;background:var(--bg);color:var(--text);
  font-family:'Inter',system-ui,sans-serif;font-size:14px;line-height:1.45;
  -webkit-font-smoothing:antialiased;letter-spacing:-0.01em;
  height:100%;overflow:hidden}
button{font-family:inherit;cursor:pointer;border:none;background:none;color:inherit;padding:0}
input,textarea,select{font-family:inherit;color:inherit}
a{color:inherit;text-decoration:none}
a:hover{color:var(--accent)}

.layout{display:grid;grid-template-columns:260px 1fr 0;height:100vh;overflow:hidden;
  transition:grid-template-columns .25s ease}
.layout.collapsed{grid-template-columns:56px 1fr 0}
.layout.artifact-open{grid-template-columns:260px 0 minmax(0,1fr)}
.layout.collapsed.artifact-open{grid-template-columns:56px 0 minmax(0,1fr)}
.layout.artifact-open main.content{display:none}

aside.side{background:var(--surface);border-right:1px solid var(--border);
  display:flex;flex-direction:column;height:100vh;overflow:visible;position:relative;z-index:10;
  grid-column:1}
.side-toggle{position:absolute;right:-13px;top:54px;width:26px;height:26px;
  border-radius:50%;background:var(--surface);border:1px solid var(--border-s);
  display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:30;
  color:var(--dim);font-size:11px;font-weight:700;
  box-shadow:0 2px 8px rgba(0,0,0,0.22);transition:transform .2s,color .15s,border-color .15s,background-color .15s}
.side-toggle:hover{color:var(--text);border-color:var(--accent)}
.layout.collapsed .side-toggle{transform:rotate(180deg)}
.layout.collapsed .nav,
.layout.collapsed .side-foot,
.layout.collapsed .brand-text{display:none}
.layout.collapsed .side-head{padding:14px 0;justify-content:center}
.side-head{padding:14px 16px;border-bottom:1px solid var(--border);display:flex;gap:10px;align-items:center}
.brand-mark{width:32px;height:32px;border-radius:9px;
  background:linear-gradient(135deg,#6366f1,#ec4899);display:flex;align-items:center;
  justify-content:center;color:#fff;font-weight:700;font-size:14px}
.brand-name{font-weight:700;font-size:14px;letter-spacing:-0.02em;line-height:1}
.brand-tag{font-size:9.5px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-top:2px}

.nav{padding:8px 10px;overflow-y:auto;overflow-x:hidden;flex:1;min-height:0}
.nav-section{font-size:10px;color:var(--mute);text-transform:uppercase;
  letter-spacing:0.8px;padding:8px 8px 4px;font-weight:600}
.nav-item{display:flex;align-items:center;gap:6px;padding:5px 8px;
  border-radius:6px;font-size:12.5px;color:var(--dim);cursor:pointer;user-select:none}
.nav-item:hover{background:var(--panel);color:var(--text)}
.nav-item.active{background:color-mix(in srgb,var(--accent) 15%,transparent);color:var(--text);font-weight:500}
.nav-caret{width:12px;font-size:10px;color:var(--mute);flex-shrink:0;text-align:center}
.nav-type{font-size:9px;font-family:'JetBrains Mono',monospace;color:var(--mute);
  text-transform:uppercase;padding:1px 5px;border:1px solid var(--border);border-radius:4px;margin-left:auto}
.nav-children{padding-left:14px;display:none}
.nav-children.open{display:block}
.nav-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1}

.side-foot{padding:10px 14px;border-top:1px solid var(--border);display:flex;
  gap:6px;align-items:center;font-size:11px;color:var(--dim)}

main.content{display:flex;flex-direction:column;min-width:0;
  height:100vh;overflow-y:auto;overflow-x:hidden;grid-column:2}

header.top{display:flex;align-items:center;justify-content:space-between;
  padding:14px 24px;border-bottom:1px solid var(--border);gap:16px;flex-wrap:wrap;
  background:var(--bg);position:sticky;top:0;z-index:5}
.crumbs{display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--dim);flex-wrap:wrap}
.crumbs a:hover{color:var(--text)}
.crumbs .sep{color:var(--mute)}
.crumbs .cur{color:var(--text);font-weight:500}

.page-title{font-size:20px;font-weight:700;letter-spacing:-0.02em;margin:0}
.page-sub{font-size:12px;color:var(--dim);margin-top:2px}

.stats{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.stat{display:flex;flex-direction:column;line-height:1.1}
.stat .v{font-size:18px;font-weight:700;font-variant-numeric:tabular-nums}
.stat .k{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:0.8px;margin-top:2px}

.top-btns{display:flex;gap:8px;align-items:center}
.btn{padding:6px 11px;border-radius:7px;border:1px solid var(--border);
  font-size:12px;font-weight:500;background:var(--surface);transition:border-color .15s;color:inherit}
.btn:hover{border-color:var(--border-s)}
.btn-primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn-primary:hover{border-color:var(--accent);filter:brightness(1.1)}
.btn-danger{background:var(--red);color:#fff;border-color:var(--red)}

section.pane{padding:20px 24px}

.cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:14px 16px;display:flex;flex-direction:column;gap:8px;
  transition:border-color .15s,transform .12s,box-shadow .15s}
.tile:hover{border-color:var(--border-s);transform:translateY(-2px);
  box-shadow:0 6px 14px -6px rgba(0,0,0,0.3)}
.tile-top{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.tile-title{font-weight:600;font-size:14.5px;letter-spacing:-0.01em}
.tile-meta{font-size:11px;color:var(--dim);font-family:'JetBrains Mono',monospace}
.tile-desc{font-size:12.5px;color:var(--dim);line-height:1.4}
.tile-foot{display:flex;gap:6px;flex-wrap:wrap;font-size:10.5px;color:var(--mute);margin-top:auto;padding-top:6px}
.pill{font-size:10px;padding:2px 7px;border-radius:5px;font-weight:600;
  background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent);
  border:1px solid color-mix(in srgb,var(--accent) 24%,transparent)}

.status-chips{display:flex;flex-wrap:wrap;gap:6px}
.status-chip{font-size:11px;padding:3px 10px;border-radius:999px;
  background:var(--panel);color:var(--dim);border:1px solid var(--border);
  font-family:'JetBrains Mono',monospace}
.status-chip b{color:var(--text);font-weight:700;margin-right:4px}

main.board{display:grid;grid-template-columns:repeat(5,minmax(240px,1fr));
  gap:12px;padding:16px 24px 40px;align-items:start}
.column{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  display:flex;flex-direction:column;max-height:calc(100vh - 170px)}
.col-head{display:flex;align-items:center;gap:8px;padding:11px 13px;
  border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--surface);
  border-radius:12px 12px 0 0;z-index:1}
.dot{width:8px;height:8px;border-radius:50%}
.col-title{font-weight:600;font-size:12.5px;flex:1}
.col-count{background:var(--panel);color:var(--dim);padding:1px 7px;border-radius:7px;
  font-size:10.5px;font-weight:600;font-variant-numeric:tabular-nums}
.col-new{font-size:12px;color:var(--dim);padding:1px 7px;border:1px solid var(--border);border-radius:6px}
.col-new:hover{color:var(--text);border-color:var(--border-s)}
.col-body{padding:8px;display:flex;flex-direction:column;gap:7px;overflow-y:auto;min-height:100px;flex:1}
.empty{color:var(--mute);text-align:center;padding:22px 0;font-size:11.5px;font-style:italic;
  border:1px dashed var(--border);border-radius:7px}

.card{background:var(--panel);border:1px solid var(--border);border-radius:9px;
  padding:9px 11px;cursor:grab;transition:border-color .15s,transform .12s,box-shadow .15s;
  display:flex;flex-direction:column;gap:5px}
.card:hover{border-color:var(--border-s);transform:translateY(-1px);
  box-shadow:0 4px 10px -4px rgba(0,0,0,0.25)}
.card:active{cursor:grabbing}
.card.drag-ghost{opacity:0.4}
.card.drag-chosen{cursor:grabbing}
.card-top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.name{font-weight:600;font-size:13px;letter-spacing:-0.01em;line-height:1.25}
.name a:hover{color:var(--accent)}
.top-right{display:flex;gap:6px;align-items:center;flex-shrink:0}

.score{font-family:'JetBrains Mono',monospace;font-size:11.5px;font-weight:700;
  padding:2px 6px;border-radius:5px;min-width:28px;text-align:center;
  font-variant-numeric:tabular-nums;border:1px solid transparent}
.score-strong{background:color-mix(in srgb,var(--green) 20%,transparent);color:var(--green);border-color:color-mix(in srgb,var(--green) 35%,transparent)}
.score-shortlist{background:color-mix(in srgb,var(--amber) 20%,transparent);color:var(--amber);border-color:color-mix(in srgb,var(--amber) 35%,transparent)}
.score-borderline{background:color-mix(in srgb,var(--cyan) 18%,transparent);color:var(--cyan);border-color:color-mix(in srgb,var(--cyan) 30%,transparent)}
.score-reject{background:color-mix(in srgb,var(--red) 20%,transparent);color:var(--red);border-color:color-mix(in srgb,var(--red) 35%,transparent)}
.score-unscored{background:var(--panel);color:var(--mute);border-color:var(--border)}

.outcome{font-size:9px;font-weight:800;letter-spacing:0.7px;padding:2px 6px;border-radius:5px}
.outcome-hired{background:color-mix(in srgb,var(--green) 20%,transparent);color:var(--green)}
.outcome-rejected{background:color-mix(in srgb,var(--red) 20%,transparent);color:var(--red)}

.priority{font-size:9.5px;font-weight:700;letter-spacing:0.5px;padding:2px 6px;border-radius:5px;text-transform:uppercase}
.priority-high{background:color-mix(in srgb,var(--red) 18%,transparent);color:var(--red)}
.priority-med{background:color-mix(in srgb,var(--amber) 18%,transparent);color:var(--amber)}
.priority-low{background:color-mix(in srgb,var(--cyan) 18%,transparent);color:var(--cyan)}

.role{font-size:11px;color:var(--dim);font-weight:500}
.chips{display:flex;flex-wrap:wrap;gap:4px}
.chips:empty{display:none}
.tag{font-size:9.5px;padding:2px 6px;border-radius:4px;font-weight:500;
  background:color-mix(in srgb,var(--accent) 12%,transparent);color:var(--accent);
  border:1px solid color-mix(in srgb,var(--accent) 20%,transparent)}
.next{font-size:11px;color:var(--text);
  background:color-mix(in srgb,var(--amber) 8%,transparent);
  border-left:2px solid var(--amber);padding:4px 7px;border-radius:4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.foot{display:flex;justify-content:space-between;font-size:10px;color:var(--dim);
  font-family:'JetBrains Mono',monospace}
.actions{display:flex;gap:5px;border-top:1px solid var(--border);padding-top:5px;margin-top:2px;flex-wrap:wrap}
.act{font-size:10px;padding:3px 7px;border-radius:5px;border:1px solid var(--border);
  color:var(--dim);background:transparent;font-weight:500;transition:all .15s}
.act:hover{color:var(--text);border-color:var(--border-s);background:var(--surface)}

.detail-grid{display:grid;grid-template-columns:1fr 280px;gap:22px}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px}
.panel h2{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.8px;
  color:var(--dim);margin:0 0 12px}
.kv{display:grid;grid-template-columns:110px 1fr;gap:6px 12px;font-size:12.5px}
.kv dt{color:var(--dim);font-weight:500}
.kv dd{margin:0;color:var(--text);word-break:break-word}
.kv a{color:var(--accent)}

.md-body{font-size:13.5px;line-height:1.65;white-space:pre-wrap;word-wrap:break-word;
  color:var(--text);font-family:'Inter',system-ui,sans-serif}

.attach-list{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:5px}
.attach-list li{display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:6px 10px;border:1px solid var(--border);border-radius:7px;font-size:12px}
.attach-list li:hover{border-color:var(--border-s)}
.attach-name{font-family:'JetBrains Mono',monospace;font-size:11.5px;word-break:break-all}

.activity-list{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:0}
.activity-list li{display:grid;grid-template-columns:120px 1fr;gap:12px;
  padding:8px 0;border-bottom:1px dashed var(--border);font-size:12.5px}
.activity-list li:last-child{border-bottom:none}
.activity-time{color:var(--dim);font-family:'JetBrains Mono',monospace;font-size:11px}
.activity-action{color:var(--text)}
.activity-action b{color:var(--accent)}

.toast{position:fixed;bottom:22px;right:22px;background:var(--surface);
  border:1px solid var(--border-s);padding:9px 13px;border-radius:8px;font-size:12px;
  box-shadow:0 12px 28px -8px rgba(0,0,0,0.4);opacity:0;transform:translateY(8px);
  transition:all .2s;pointer-events:none;z-index:100}
.toast.show{opacity:1;transform:translateY(0)}
.toast.err{border-color:var(--red);color:var(--red)}
.toast.ok{border-color:var(--green)}

#dlg-backdrop{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:none;
  align-items:center;justify-content:center;z-index:50}
#dlg-backdrop.show{display:flex}
.dlg{background:var(--surface);border:1px solid var(--border-s);border-radius:12px;
  padding:20px 22px;min-width:340px;box-shadow:0 20px 40px rgba(0,0,0,0.4)}
.dlg h3{margin:0 0 12px;font-size:15px;font-weight:600}
.dlg p{margin:0 0 14px;color:var(--dim);font-size:13px}
.dlg-row{display:flex;flex-direction:column;gap:4px;margin:0 0 12px}
.dlg-row label{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:0.5px;font-weight:600}
.dlg-row input,.dlg-row select{padding:7px 9px;border-radius:7px;border:1px solid var(--border);
  background:var(--bg);color:var(--text);font-size:13px}
.dlg-row input:focus,.dlg-row select:focus{outline:none;border-color:var(--accent)}
.dlg-btns{display:flex;gap:8px;justify-content:flex-end}

footer.foot-bar{padding:12px 24px;border-top:1px solid var(--border);
  font-size:11px;color:var(--dim);font-family:'JetBrains Mono',monospace;
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}

aside.artifact{background:var(--surface);border-left:1px solid var(--border);
  height:100vh;display:flex;flex-direction:column;overflow:hidden;min-width:0;grid-column:3}
.art-head{padding:14px 16px 12px;border-bottom:1px solid var(--border);
  display:flex;gap:10px;align-items:center;justify-content:space-between;
  background:var(--surface);flex-shrink:0}
.art-title-wrap{min-width:0;flex:1;display:flex;flex-direction:column;gap:3px}
.art-eyebrow{font-size:10px;text-transform:uppercase;letter-spacing:0.8px;
  color:var(--mute);font-weight:600;font-family:'JetBrains Mono',monospace}
.art-title{font-size:16px;font-weight:700;letter-spacing:-0.02em;line-height:1.2;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.art-head-btns{display:flex;gap:6px;align-items:center;flex-shrink:0}
.art-icon{width:28px;height:28px;border-radius:7px;border:1px solid var(--border);
  color:var(--dim);font-size:13px;display:flex;align-items:center;justify-content:center;
  cursor:pointer;transition:all .15s;background:transparent}
.art-icon:hover{color:var(--text);border-color:var(--border-s);background:var(--panel)}
.art-icon.close{font-size:18px;line-height:1}
.art-sub{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:0 16px 12px;
  border-bottom:1px solid var(--border);flex-shrink:0}
.art-chip{font-size:10.5px;padding:3px 8px;border-radius:5px;font-family:'JetBrains Mono',monospace;
  background:var(--panel);color:var(--dim);border:1px solid var(--border)}
.art-chip.st-applied{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 30%,transparent);
  background:color-mix(in srgb,var(--accent) 10%,transparent)}
.art-chip.st-screening{color:var(--cyan);border-color:color-mix(in srgb,var(--cyan) 30%,transparent);
  background:color-mix(in srgb,var(--cyan) 10%,transparent)}
.art-chip.st-interview{color:var(--amber);border-color:color-mix(in srgb,var(--amber) 30%,transparent);
  background:color-mix(in srgb,var(--amber) 10%,transparent)}
.art-chip.st-offer{color:var(--violet);border-color:color-mix(in srgb,var(--violet) 30%,transparent);
  background:color-mix(in srgb,var(--violet) 10%,transparent)}
.art-chip.st-hired{color:var(--green);border-color:color-mix(in srgb,var(--green) 30%,transparent);
  background:color-mix(in srgb,var(--green) 10%,transparent)}
.art-chip.st-rejected{color:var(--red);border-color:color-mix(in srgb,var(--red) 30%,transparent);
  background:color-mix(in srgb,var(--red) 10%,transparent)}
.art-pills{display:flex;gap:5px;padding:8px 16px 10px;border-bottom:1px solid var(--border);
  flex-wrap:wrap;align-items:center;background:var(--surface);flex-shrink:0}
.art-pill{font-size:10.5px;padding:4px 9px;border-radius:999px;border:1px solid var(--border);
  color:var(--dim);background:transparent;cursor:pointer;font-weight:500;
  transition:all .12s;display:inline-flex;align-items:center;gap:5px;white-space:nowrap;
  font-family:'Inter',system-ui,sans-serif;letter-spacing:0.1px}
.art-pill:hover{color:var(--text);border-color:var(--border-s);background:var(--panel)}
.art-pill.on{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 40%,transparent);
  background:color-mix(in srgb,var(--accent) 12%,transparent);font-weight:600}
.art-pill-dot{width:5px;height:5px;border-radius:50%;background:currentColor;opacity:0.7}
.art-pill:not(.on) .art-pill-dot{opacity:0.25}
.art-pills-spacer{flex:1}
.art-pills-hint{font-size:10px;color:var(--mute);font-family:'JetBrains Mono',monospace}

.art-body{flex:1;min-height:0;display:grid;
  grid-template-columns:minmax(0,var(--art-left,58fr)) 8px minmax(280px,var(--art-right,42fr));
  overflow:hidden;position:relative}
.art-body.no-left{grid-template-columns:0 0 minmax(0,1fr)}
.art-body.no-right{grid-template-columns:minmax(0,1fr) 0 0}
.art-body.no-left .art-divider,.art-body.no-right .art-divider{display:none}
.art-body.no-left .art-pdf-pane,.art-body.no-right .art-summary-pane{display:none !important}
.art-body.no-left{grid-template-columns:minmax(0,1fr) !important}
.art-body.no-right{grid-template-columns:minmax(0,1fr) !important}
.art-body.no-left .art-summary-pane,.art-body.no-right .art-pdf-pane{grid-column:1 !important}

.art-divider{background:transparent;cursor:col-resize;position:relative;
  transition:background-color .15s}
.art-divider::before{content:'';position:absolute;top:0;bottom:0;left:50%;
  width:1px;background:var(--border);transform:translateX(-50%)}
.art-divider:hover,.art-divider.dragging{background:color-mix(in srgb,var(--accent) 15%,transparent)}
.art-divider:hover::before,.art-divider.dragging::before{background:var(--accent);width:2px}
body.art-dragging{user-select:none;cursor:col-resize !important}
body.art-dragging iframe,body.art-dragging embed{pointer-events:none}

.art-sec{margin-bottom:12px;border:1px solid var(--border);border-radius:9px;
  background:var(--surface);display:flex;flex-direction:column;min-width:0}
.art-sec-head{border-radius:9px 9px 0 0}
.art-sec.hidden{display:none !important}
.art-sec.dragging{opacity:0.45}
.art-sec.drop-above{box-shadow:0 -3px 0 0 var(--accent) inset;border-color:var(--accent)}
.art-sec.drop-below{box-shadow:0 3px 0 0 var(--accent) inset;border-color:var(--accent)}
.art-sec.drop-tab{box-shadow:0 0 0 2px var(--accent) inset;border-color:var(--accent)}
.art-sec.collapsed .art-sec-content,.art-sec.collapsed .art-sec-resize{display:none}
.art-sec.collapsed .art-sec-head{border-radius:9px}
.art-sec.collapsed .art-sec-chevron{transform:rotate(-90deg)}
.art-sec.sized{overflow:hidden}
.art-sec.sized .art-sec-content{max-height:var(--sec-height,400px);overflow-y:auto}
.art-sec-content{overflow-wrap:anywhere}
.art-sec.tabbed .art-sec-content{overflow:visible}
.art-pane{display:none;min-width:0;overflow-wrap:anywhere}
.art-pane.active{display:block}

.art-sec-head{display:flex;align-items:center;gap:8px;padding:7px 10px 7px 8px;
  background:var(--panel);border-bottom:1px solid var(--border);
  user-select:none;font-family:'JetBrains Mono',monospace;font-size:10px;
  font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--dim);
  cursor:pointer}
.art-sec-chevron{flex-shrink:0;color:var(--mute);font-size:10px;line-height:1;
  transition:transform .15s;width:12px;text-align:center}
.art-sec-head:hover .art-sec-chevron{color:var(--text)}
.art-sec-drag{flex-shrink:0;color:var(--mute);font-size:12px;line-height:1;opacity:0.6;cursor:grab}
.art-sec-drag:active{cursor:grabbing}
.art-sec-head:hover .art-sec-drag{color:var(--text);opacity:1}
.art-sec-label{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.art-sec-count{font-family:'JetBrains Mono',monospace;font-size:9.5px;font-weight:600;
  padding:1px 6px;border-radius:4px;background:var(--surface);color:var(--mute);border:1px solid var(--border)}
.art-sec-close{flex-shrink:0;width:20px;height:20px;border-radius:5px;background:transparent;
  color:var(--mute);font-size:14px;line-height:1;cursor:pointer;
  display:flex;align-items:center;justify-content:center;transition:all .15s;padding:0}
.art-sec-close:hover{color:var(--red);background:color-mix(in srgb,var(--red) 15%,transparent)}
.art-sec-content{padding:12px 14px}
.art-sec-resize{height:7px;cursor:row-resize;background:transparent;position:relative;flex-shrink:0}
.art-sec-resize::after{content:'';position:absolute;left:50%;top:50%;
  width:26px;height:2px;background:var(--border);border-radius:1px;transform:translate(-50%,-50%);
  transition:background-color .15s,width .15s}
.art-sec-resize:hover::after,.art-sec-resize.dragging::after{background:var(--accent);width:40px}
body.art-v-dragging{user-select:none;cursor:row-resize !important}
body.art-v-dragging iframe,body.art-v-dragging embed{pointer-events:none}

/* tab groups */
.art-sec.tabbed .art-sec-head{padding:0 8px 0 0;overflow:hidden}
.art-sec-tabs{display:flex;flex:1;min-width:0;overflow-x:auto;gap:1px;align-items:stretch}
.art-tab{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:0.8px;color:var(--dim);cursor:pointer;
  padding:6px 8px 5px 10px;white-space:nowrap;
  border:none;background:transparent;
  border-bottom:2px solid transparent;margin-bottom:-1px;display:flex;align-items:center;gap:5px}
.art-tab.active{color:var(--accent);border-bottom-color:var(--accent);background:var(--surface)}
.art-tab:hover:not(.active){color:var(--text);background:var(--surface)}
.art-tab-label{cursor:pointer}
.art-tab-action{cursor:pointer;font-size:11px;color:var(--mute);padding:1px 4px;border-radius:3px;line-height:1;
  display:inline-flex;align-items:center;justify-content:center;min-width:14px;height:14px}
.art-tab-action:hover{color:var(--accent);background:color-mix(in srgb,var(--accent) 15%,transparent)}
.art-tab-action.close:hover{color:var(--red);background:color-mix(in srgb,var(--red) 15%,transparent)}

.art-pdf-pane{display:flex;flex-direction:column;
  background:var(--panel);overflow:hidden;min-width:0}
.art-pdf-head{padding:8px 12px;border-bottom:1px solid var(--border);display:flex;
  gap:6px;align-items:center;justify-content:space-between;background:var(--surface);flex-shrink:0}
.art-pdf-picker{font-size:11px;background:transparent;color:var(--text);
  border:1px solid var(--border);border-radius:6px;padding:4px 8px;max-width:60%;flex:1;min-width:0}
.art-pdf-picker:focus{outline:none;border-color:var(--accent)}
.art-pdf-actions{display:flex;gap:4px;flex-shrink:0}
.art-pdf-home{font-size:10px;padding:4px 9px;border-radius:6px;
  border:1px solid var(--border);color:var(--dim);background:transparent;cursor:pointer;
  font-family:'Inter',system-ui,sans-serif;font-weight:600;white-space:nowrap;
  display:inline-flex;align-items:center;gap:4px;transition:all .15s}
.art-pdf-home:hover{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 40%,transparent);
  background:color-mix(in srgb,var(--accent) 10%,transparent)}
.art-pdf-home[hidden]{display:none}
.art-pdf-view{flex:1;min-height:0;background:#1f2023;display:flex;align-items:center;justify-content:center}
.art-pdf-view embed,.art-pdf-view iframe{width:100%;height:100%;border:none;background:#1f2023}
.art-pdf-empty{color:var(--mute);font-size:12.5px;font-style:italic;text-align:center;padding:40px 20px}
.art-summary-pane{overflow-y:auto;padding:16px 18px 28px;display:flex;flex-direction:column;gap:18px;min-width:0}
@media (max-width:1400px){
  .layout.artifact-open{grid-template-columns:260px 0 minmax(0,1fr)}
  .layout.collapsed.artifact-open{grid-template-columns:56px 0 minmax(0,1fr)}
}
.md-h2{font-size:15px;font-weight:700;letter-spacing:-0.01em;margin:14px 0 6px;color:var(--text)}
.md-h3{font-size:13.5px;font-weight:700;margin:12px 0 4px;color:var(--text)}
.md-h4{font-size:12.5px;font-weight:700;margin:10px 0 4px;color:var(--dim);text-transform:uppercase;letter-spacing:0.5px}
.md-p{margin:0 0 8px;font-size:12.5px;line-height:1.6;color:var(--text)}
.md-p strong{color:var(--text);font-weight:700}
.md-p em{color:var(--dim);font-style:italic}
.md-p code{font-family:'JetBrains Mono',monospace;font-size:11.5px;padding:1px 5px;
  background:var(--panel);border:1px solid var(--border);border-radius:4px}
.md-hr{border:none;border-top:1px solid var(--border);margin:14px 0}
.md-ul{margin:0 0 8px;padding-left:18px;font-size:12.5px;line-height:1.55}
.md-ul li{margin-bottom:3px}
.art-section h3{font-size:10.5px;text-transform:uppercase;letter-spacing:0.9px;
  color:var(--mute);margin:0 0 8px;font-weight:700;font-family:'JetBrains Mono',monospace}
.art-md{font-size:13.5px;line-height:1.6;white-space:pre-wrap;word-wrap:break-word;color:var(--text)}
.art-md:empty::before{content:'(no body)';color:var(--mute);font-style:italic}
.art-kv{display:grid;grid-template-columns:110px 1fr;gap:6px 12px;font-size:12.5px}
.art-kv dt{color:var(--dim);font-weight:500;font-family:'JetBrains Mono',monospace;font-size:11.5px}
.art-kv dd{margin:0;color:var(--text);word-break:break-word}
.art-kv a{color:var(--accent);text-decoration:underline;text-decoration-color:color-mix(in srgb,var(--accent) 40%,transparent)}
.art-attach{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:5px}
.art-attach li{display:flex;align-items:center;gap:6px;
  padding:7px 10px;border:1px solid var(--border);border-radius:7px;font-size:12px;
  transition:border-color .15s,background-color .15s}
.art-attach li:hover{border-color:var(--border-s);background:var(--panel)}
.art-attach li.previewable{cursor:pointer}
.art-attach li.current{border-color:color-mix(in srgb,var(--accent) 50%,transparent);
  background:color-mix(in srgb,var(--accent) 8%,transparent)}
.art-attach-name{font-family:'JetBrains Mono',monospace;font-size:11.5px;overflow-wrap:anywhere;word-break:normal;flex:1;min-width:0;display:flex;align-items:flex-start;gap:6px;line-height:1.4}
.art-attach-icon{flex-shrink:0;font-size:13px;opacity:0.7}
.art-attach-badge{font-size:9px;font-weight:700;padding:1px 5px;border-radius:4px;
  background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent);
  letter-spacing:0.4px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;flex-shrink:0}
.art-attach-size{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--mute);flex-shrink:0}
.art-attach-btns{display:flex;gap:4px;flex-shrink:0;align-items:center}
.art-attach-btns .act{font-size:10px;padding:3px 8px}
.art-attach-btns .act-icon{padding:3px 6px;font-size:12px;line-height:1}
.art-act-list{list-style:none;padding:0;margin:0;display:flex;flex-direction:column}
.art-act-list li{display:grid;grid-template-columns:110px 1fr;gap:10px;
  padding:7px 0;border-bottom:1px dashed var(--border);font-size:12px}
.art-act-list li:last-child{border-bottom:none}
.art-act-time{color:var(--mute);font-family:'JetBrains Mono',monospace;font-size:10.5px;padding-top:1px}
.art-act-msg{color:var(--text)}
.art-act-msg b{color:var(--accent);font-weight:600}
.art-empty{color:var(--mute);font-size:12px;font-style:italic;padding:8px 0}
.art-loading{display:flex;align-items:center;justify-content:center;padding:40px 0;color:var(--dim);font-size:13px}
.art-path{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--mute);
  padding:8px 10px;border:1px solid var(--border);border-radius:6px;word-break:break-all;
  background:var(--panel);line-height:1.5}
.art-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:2px}

.card .name a{cursor:pointer}

@media (max-width:1100px){
  html,body{overflow:auto;height:auto}
  .layout{grid-template-columns:1fr;height:auto;overflow:visible}
  .layout.collapsed{grid-template-columns:1fr}
  .layout.artifact-open{grid-template-columns:1fr}
  .layout.collapsed.artifact-open{grid-template-columns:1fr}
  aside.side{position:static;height:auto;max-height:none;overflow:visible;grid-column:auto}
  main.content{height:auto;overflow:visible;grid-column:auto;display:flex}
  .layout.artifact-open main.content{display:flex}
  .side-toggle{display:none}
  main.board{grid-template-columns:repeat(3,1fr)}
  .detail-grid{grid-template-columns:1fr}
  aside.artifact{position:fixed;top:0;right:0;width:min(100%,420px);z-index:60;
    grid-column:auto;
    border-left:1px solid var(--border-s);box-shadow:-20px 0 40px rgba(0,0,0,0.3);
    transform:translateX(100%);transition:transform .22s ease;
    visibility:hidden}
  .layout.artifact-open aside.artifact{transform:translateX(0);visibility:visible}}
@media (max-width:720px){main.board{grid-template-columns:1fr}.column{max-height:none}
  aside.artifact{width:100%}}
"""


JS_COMMON = r"""
(function initTheme(){
  try{
    var saved = localStorage.getItem('hrkit-theme');
    var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.setAttribute('data-theme', saved || (dark ? 'dark' : 'light'));
  }catch(e){}
})();
function toggleTheme(){
  var cur = document.documentElement.getAttribute('data-theme');
  var next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try{ localStorage.setItem('hrkit-theme', next); }catch(e){}
}
function toggleSidebar(){
  var layout = document.querySelector('.layout');
  if(!layout) return;
  var collapsed = layout.classList.toggle('collapsed');
  try{ localStorage.setItem('hrkit-sidebar', collapsed ? 'collapsed' : 'expanded'); }catch(e){}
}
(function initSidebar(){
  try{
    if(localStorage.getItem('hrkit-sidebar') === 'collapsed'){
      var layout = document.querySelector('.layout');
      if(layout) layout.classList.add('collapsed');
    }
  }catch(e){}
})();
function toast(msg, kind){
  var t = document.getElementById('toast');
  if(!t) return;
  t.textContent = msg;
  t.className = 'toast show ' + (kind || '');
  clearTimeout(t._tmo);
  t._tmo = setTimeout(function(){ t.className = 'toast'; }, 2500);
}
function nodeToggle(el){
  var ch = el.parentElement.querySelector(':scope > .nav-children');
  if(!ch) return;
  ch.classList.toggle('open');
  var car = el.querySelector('.nav-caret');
  if(car) car.textContent = ch.classList.contains('open') ? 'v' : '>';
  try{
    var key = 'hrkit-open-' + (el.dataset.nodeId || '');
    localStorage.setItem(key, ch.classList.contains('open') ? '1' : '0');
  }catch(e){}
}
(function restoreTree(){
  try{
    document.querySelectorAll('.nav-item[data-node-id]').forEach(function(it){
      var key = 'hrkit-open-' + it.dataset.nodeId;
      if(localStorage.getItem(key) === '1'){
        var ch = it.parentElement.querySelector(':scope > .nav-children');
        if(ch){ ch.classList.add('open'); var c = it.querySelector('.nav-caret'); if(c) c.textContent='v'; }
      }
    });
  }catch(e){}
})();
async function openFolder(fid){
  try{
    var r = await fetch('/api/open-folder',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({folder_id:fid})});
    if(!r.ok) throw new Error(await r.text());
    toast('Opening folder', 'ok');
  }catch(e){ toast('Failed: '+e.message,'err'); }
}
async function openFile(fid, filename){
  try{
    var r = await fetch('/api/open-file',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({folder_id:fid,filename:filename})});
    if(!r.ok) throw new Error(await r.text());
    toast('Opening ' + filename, 'ok');
  }catch(e){ toast('Failed: '+e.message,'err'); }
}
async function runScan(){
  try{
    toast('Scanning...', 'ok');
    var r = await fetch('/api/scan',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
    if(!r.ok) throw new Error(await r.text());
    var j = await r.json();
    toast('Scanned: ' + (j.seen||0) + ' folders', 'ok');
    setTimeout(function(){ location.reload(); }, 600);
  }catch(e){ toast('Scan failed: '+e.message, 'err'); }
}

// ---------- Artifact panel ----------
var _artTaskId = null;

function esc(s){
  if(s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

function cardOpen(e, id){
  if(e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return true;
  e.preventDefault();
  e.stopPropagation();
  openTaskArtifact(id);
  return false;
}

async function openTaskArtifact(id){
  _artTaskId = id;
  var layout = document.getElementById('layout');
  var summary = document.getElementById('art-summary-pane');
  var pdfView = document.getElementById('art-pdf-view');
  var picker = document.getElementById('art-pdf-picker');
  var pdfOpen = document.getElementById('art-pdf-open');
  document.getElementById('art-title').textContent = 'Loading...';
  document.getElementById('art-sub').innerHTML = '';
  summary.innerHTML = '<div class="art-loading">Loading...</div>';
  pdfView.innerHTML = '<div class="art-pdf-empty">Loading resume...</div>';
  picker.style.display = 'none';
  pdfOpen.style.display = 'none';
  layout.classList.add('artifact-open');
  document.getElementById('artifact').setAttribute('aria-hidden','false');
  try{
    var u = new URL(location.href);
    u.searchParams.set('task', id);
    history.replaceState({task:id}, '', u.pathname + '?' + u.searchParams.toString());
  }catch(e){}
  try{
    var r = await fetch('/api/task/' + id);
    if(!r.ok) throw new Error('HTTP ' + r.status);
    var d = await r.json();
    if(!d.ok) throw new Error(d.error || 'unknown');
    renderArtifact(d);
  }catch(e){
    summary.innerHTML = '<div class="art-empty">Failed to load: ' + esc(e.message) + '</div>';
    pdfView.innerHTML = '<div class="art-pdf-empty">No preview</div>';
  }
}

function closeArtifact(){
  var layout = document.getElementById('layout');
  layout.classList.remove('artifact-open');
  document.getElementById('artifact').setAttribute('aria-hidden','true');
  _artTaskId = null;
  try{
    var u = new URL(location.href);
    if(u.searchParams.has('task')){
      u.searchParams.delete('task');
      var qs = u.searchParams.toString();
      history.replaceState({}, '', u.pathname + (qs ? '?' + qs : ''));
    }
  }catch(e){}
}


function fmtBytes(n){
  if(!n && n !== 0) return '';
  if(n < 1024) return n + ' B';
  if(n < 1048576) return (n/1024).toFixed(1) + ' KB';
  if(n < 1073741824) return (n/1048576).toFixed(1) + ' MB';
  return (n/1073741824).toFixed(2) + ' GB';
}

function fmtTime(iso){
  if(!iso) return '';
  var s = iso.length >= 19 ? iso.substring(0,10) + ' ' + iso.substring(11,16) : iso;
  return s;
}

function mdToHtml(md){
  if(!md) return '';
  var lines = md.replace(/\r\n/g,'\n').split('\n');
  var out = [];
  var buf = [];
  var inList = false;
  function flushP(){ if(buf.length){ out.push('<p class="md-p">'+inlineMd(buf.join(' '))+'</p>'); buf = []; } }
  function flushList(){ if(inList){ out.push('</ul>'); inList = false; } }
  function inlineMd(s){
    s = s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^\*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    return s;
  }
  for(var i=0;i<lines.length;i++){
    var ln = lines[i];
    var raw = ln;
    ln = ln.replace(/\s+$/,'');
    if(!ln){ flushP(); flushList(); continue; }
    var m;
    if((m = ln.match(/^#### (.+)$/))){ flushP(); flushList(); out.push('<div class="md-h4">'+inlineMd(m[1])+'</div>'); continue; }
    if((m = ln.match(/^### (.+)$/))){ flushP(); flushList(); out.push('<div class="md-h3">'+inlineMd(m[1])+'</div>'); continue; }
    if((m = ln.match(/^## (.+)$/))){ flushP(); flushList(); out.push('<div class="md-h2">'+inlineMd(m[1])+'</div>'); continue; }
    if((m = ln.match(/^# (.+)$/))){ flushP(); flushList(); out.push('<div class="md-h2">'+inlineMd(m[1])+'</div>'); continue; }
    if(/^---+$/.test(ln)){ flushP(); flushList(); out.push('<hr class="md-hr">'); continue; }
    if((m = raw.match(/^[\-\*] (.+)$/))){ flushP(); if(!inList){ out.push('<ul class="md-ul">'); inList = true; } out.push('<li>'+inlineMd(m[1])+'</li>'); continue; }
    buf.push(ln);
  }
  flushP(); flushList();
  return out.join('');
}

var _artAttachments = [];
var _artTaskType = 'default';
var _artLayout = null;
var _artCurrentPdf = null;
var _artCurrentData = null;
var _artDefaultResume = null;

var ART_SECTIONS = [
  {key:'resume',   label:'Resume'},
  {key:'summary',  label:'Summary'},
  {key:'metadata', label:'Metadata'},
  {key:'activity', label:'Activity'},
  {key:'attach',   label:'Attachments'},
  {key:'path',     label:'Path'}
];
// sections that live in the right (scrollable) pane, reorderable
var ART_RIGHT_KEYS = ['summary','metadata','activity','attach','path'];
var ART_LABELS = {summary:'Summary', metadata:'Metadata', activity:'Activity', attach:'Attachments', path:'Path', resume:'Resume'};
var ART_DEFAULTS = {
  visible: {resume:true, summary:true, metadata:true, activity:true, attach:false, path:false},
  split: 58,
  groups: [['summary'],['metadata'],['activity'],['attach'],['path']],
  activeTab: {},
  collapsed: {},
  heights: {}
};

function artLayoutKey(type){ return 'hrkit-artlayout-' + (type || 'default'); }

function artLoadLayout(type){
  try{
    var raw = localStorage.getItem(artLayoutKey(type));
    if(!raw) return JSON.parse(JSON.stringify(ART_DEFAULTS));
    var parsed = JSON.parse(raw);
    // groups: array of arrays of keys. Ensure all ART_RIGHT_KEYS appear exactly once.
    var seen = {};
    var groups = [];
    if(Array.isArray(parsed.groups)){
      parsed.groups.forEach(function(g){
        if(!Array.isArray(g)) return;
        var filtered = [];
        g.forEach(function(k){
          if(ART_RIGHT_KEYS.indexOf(k) >= 0 && !seen[k]){ seen[k] = 1; filtered.push(k); }
        });
        if(filtered.length) groups.push(filtered);
      });
    }
    ART_RIGHT_KEYS.forEach(function(k){ if(!seen[k]) groups.push([k]); });
    return {
      visible: Object.assign({}, ART_DEFAULTS.visible, parsed.visible || {}),
      split: (typeof parsed.split === 'number' && parsed.split >= 15 && parsed.split <= 85) ? parsed.split : ART_DEFAULTS.split,
      groups: groups,
      activeTab: Object.assign({}, parsed.activeTab || {}),
      collapsed: Object.assign({}, parsed.collapsed || {}),
      heights: Object.assign({}, parsed.heights || {})
    };
  }catch(e){ return JSON.parse(JSON.stringify(ART_DEFAULTS)); }
}

function artSaveLayout(){
  try{ localStorage.setItem(artLayoutKey(_artTaskType), JSON.stringify(_artLayout)); }catch(e){}
}

function artSlugify(s){
  return String(s||'default').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'') || 'default';
}

function artApplyLayout(){
  if(!_artLayout) return;
  var body = document.getElementById('art-body');
  var v = _artLayout.visible;
  body.classList.toggle('no-left', !v.resume);
  var anyRight = ART_RIGHT_KEYS.some(function(k){ return v[k]; });
  body.classList.toggle('no-right', !anyRight);
  if(v.resume && anyRight){
    body.style.setProperty('--art-left', _artLayout.split + 'fr');
    body.style.setProperty('--art-right', (100 - _artLayout.split) + 'fr');
  }
  document.querySelectorAll('#art-pills .art-pill').forEach(function(p){
    var k = p.getAttribute('data-section');
    p.classList.toggle('on', !!v[k]);
  });
}

function artToggleRightPane(){
  if(!_artLayout) return;
  var anyRight = ART_RIGHT_KEYS.some(function(k){ return _artLayout.visible[k]; });
  if(anyRight){
    // collapse: stash current state, turn all off
    _artLayout._rightStash = {};
    ART_RIGHT_KEYS.forEach(function(k){
      _artLayout._rightStash[k] = _artLayout.visible[k];
      _artLayout.visible[k] = false;
    });
  }else{
    // expand: restore stash or defaults
    var stash = _artLayout._rightStash || ART_DEFAULTS.visible;
    ART_RIGHT_KEYS.forEach(function(k){
      _artLayout.visible[k] = !!stash[k];
    });
    // ensure at least summary is visible when expanding from fully-empty
    if(!ART_RIGHT_KEYS.some(function(k){ return _artLayout.visible[k]; })){
      _artLayout.visible.summary = true;
    }
  }
  artSaveLayout();
  renderArtifactSections(_artCurrentData);
  artApplyLayout();
}

function artFindGroup(key){
  for(var i=0;i<_artLayout.groups.length;i++){
    if(_artLayout.groups[i].indexOf(key) >= 0) return i;
  }
  return -1;
}

function artSecClose(key){
  if(!_artLayout) return;
  _artLayout.visible[key] = false;
  artSaveLayout();
  renderArtifactSections(_artCurrentData);
  artApplyLayout();
}

function artSecCloseGroup(groupIdx){
  if(!_artLayout || !_artLayout.groups[groupIdx]) return;
  _artLayout.groups[groupIdx].forEach(function(k){ _artLayout.visible[k] = false; });
  artSaveLayout();
  renderArtifactSections(_artCurrentData);
  artApplyLayout();
}

function artSecToggleCollapse(key){
  if(!_artLayout) return;
  _artLayout.collapsed[key] = !_artLayout.collapsed[key];
  artSaveLayout();
  var g = artFindGroup(key);
  // find DOM element for this group
  document.querySelectorAll('#art-summary-pane .art-sec').forEach(function(el){
    if(parseInt(el.getAttribute('data-group'),10) === g){
      el.classList.toggle('collapsed', !!_artLayout.collapsed[key]);
    }
  });
}

function artSwitchTab(groupIdx, key){
  if(!_artLayout) return;
  _artLayout.activeTab[groupIdx] = key;
  artSaveLayout();
  var grp = document.querySelector('#art-summary-pane .art-sec[data-group="'+groupIdx+'"]');
  if(!grp) return;
  grp.querySelectorAll('.art-tab').forEach(function(t){
    t.classList.toggle('active', t.getAttribute('data-key') === key);
  });
  grp.querySelectorAll('.art-pane').forEach(function(p){
    p.classList.toggle('active', p.getAttribute('data-key') === key);
  });
}

function artPopOutTab(groupIdx, key){
  if(!_artLayout) return;
  // Remove key from its current group; add as new standalone group
  _artLayout.groups = _artLayout.groups.map(function(g){ return g.filter(function(k){return k!==key;}); }).filter(function(g){return g.length;});
  _artLayout.groups.push([key]);
  delete _artLayout.activeTab[groupIdx];
  artSaveLayout();
  renderArtifactSections(_artCurrentData);
  artApplyLayout();
}

function artReorderGroups(fromKey, toKey, placeBefore, asTab){
  if(!_artLayout) return;
  // Remove fromKey from its group; drop the group if it becomes empty.
  var fromIdx = artFindGroup(fromKey);
  if(fromIdx >= 0){
    _artLayout.groups[fromIdx] = _artLayout.groups[fromIdx].filter(function(k){return k!==fromKey;});
    if(_artLayout.groups[fromIdx].length === 0) _artLayout.groups.splice(fromIdx,1);
  }
  var toIdx = artFindGroup(toKey);
  if(asTab && toIdx >= 0){
    _artLayout.groups[toIdx].push(fromKey);
  }else{
    var insertAt = toIdx >= 0 ? toIdx : _artLayout.groups.length;
    if(!placeBefore) insertAt += 1;
    _artLayout.groups.splice(insertAt, 0, [fromKey]);
  }
  artSaveLayout();
  renderArtifactSections(_artCurrentData);
  artApplyLayout();
}

var _artDragSec = null;

function artSecOnDragStart(e, key){
  _artDragSec = key;
  var el = e.currentTarget;
  el.classList.add('dragging');
  try{ e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', key); }catch(err){}
}

function artSecOnDragEnd(e){
  e.currentTarget.classList.remove('dragging');
  document.querySelectorAll('#art-summary-pane .art-sec').forEach(function(s){
    s.classList.remove('drop-above','drop-below','drop-tab');
  });
  _artDragSec = null;
}

function artSecOnDragOver(e){
  if(!_artDragSec) return;
  var el = e.currentTarget;
  var myKey = el.getAttribute('data-section') || '';
  if(el.getAttribute('data-group-keys') && el.getAttribute('data-group-keys').indexOf(_artDragSec) >= 0) return;
  e.preventDefault();
  try{ e.dataTransfer.dropEffect = 'move'; }catch(err){}
  var r = el.getBoundingClientRect();
  var y = e.clientY - r.top;
  el.classList.remove('drop-above','drop-below','drop-tab');
  if(y < r.height * 0.33) el.classList.add('drop-above');
  else if(y > r.height * 0.67) el.classList.add('drop-below');
  else el.classList.add('drop-tab');
}

function artSecOnDragLeave(e){
  e.currentTarget.classList.remove('drop-above','drop-below','drop-tab');
}

function artSecOnDrop(e){
  e.preventDefault();
  var el = e.currentTarget;
  var mode = el.classList.contains('drop-tab') ? 'tab'
           : (el.classList.contains('drop-above') ? 'before' : 'after');
  el.classList.remove('drop-above','drop-below','drop-tab');
  if(!_artDragSec) return;
  var targetKey = (el.getAttribute('data-group-keys') || '').split(',')[0];
  if(!targetKey || targetKey === _artDragSec){ _artDragSec = null; return; }
  artReorderGroups(_artDragSec, targetKey, mode === 'before', mode === 'tab');
  _artDragSec = null;
}

// ---------- vertical resize ----------
var _artResize = null;

function artStartResize(e, key){
  e.preventDefault();
  e.stopPropagation();
  var grp = e.target.closest('.art-sec');
  if(!grp) return;
  var content = grp.querySelector('.art-sec-content');
  if(!content) return;
  var startH = content.getBoundingClientRect().height;
  _artResize = {key: key, grp: grp, content: content, startY: e.clientY, startH: startH};
  document.body.classList.add('art-v-dragging');
  e.target.classList.add('dragging');
  document.addEventListener('mousemove', artOnResize);
  document.addEventListener('mouseup', artEndResize);
}

function artOnResize(e){
  if(!_artResize) return;
  var delta = e.clientY - _artResize.startY;
  var h = Math.max(80, Math.min(2000, _artResize.startH + delta));
  _artResize.grp.classList.add('sized');
  _artResize.grp.style.setProperty('--sec-height', h + 'px');
  _artResize._h = h;
}

function artEndResize(){
  if(!_artResize) return;
  if(_artResize._h && _artLayout){
    // save height for the first key in the group (or use the section key)
    var k = _artResize.key;
    if(k){ _artLayout.heights[k] = _artResize._h; }
    artSaveLayout();
  }
  document.body.classList.remove('art-v-dragging');
  document.querySelectorAll('.art-sec-resize.dragging').forEach(function(el){ el.classList.remove('dragging'); });
  document.removeEventListener('mousemove', artOnResize);
  document.removeEventListener('mouseup', artEndResize);
  _artResize = null;
}

function artResetHeight(e, key){
  e.preventDefault();
  e.stopPropagation();
  var grp = e.target.closest('.art-sec');
  if(!grp) return;
  grp.classList.remove('sized');
  grp.style.removeProperty('--sec-height');
  if(_artLayout){ delete _artLayout.heights[key]; artSaveLayout(); }
}

function artRenderPills(){
  var pills = document.getElementById('art-pills');
  var v = _artLayout.visible;
  var html = ART_SECTIONS.map(function(s){
    var on = v[s.key] ? ' on' : '';
    return '<button class="art-pill'+on+'" data-section="'+s.key+'" onclick="artTogglePill(\''+s.key+'\')"><span class="art-pill-dot"></span>'+esc(s.label)+'</button>';
  }).join('');
  pills.innerHTML = html;
}

function artTogglePill(key){
  if(!_artLayout) return;
  _artLayout.visible[key] = !_artLayout.visible[key];
  artSaveLayout();
  if(_artCurrentData) renderArtifactSections(_artCurrentData);
  artApplyLayout();
}

var _artDrag = null;

function artStartDrag(e){
  if(e.button !== 0) return;
  var body = document.getElementById('art-body');
  if(body.classList.contains('no-left') || body.classList.contains('no-right')) return;
  e.preventDefault();
  var rect = body.getBoundingClientRect();
  _artDrag = {x: e.clientX, width: rect.width, left: rect.left};
  document.body.classList.add('art-dragging');
  document.getElementById('art-divider').classList.add('dragging');
  document.addEventListener('mousemove', artOnDrag);
  document.addEventListener('mouseup', artEndDrag);
}

function artOnDrag(e){
  if(!_artDrag) return;
  var pct = ((e.clientX - _artDrag.left) / _artDrag.width) * 100;
  pct = Math.max(18, Math.min(82, pct));
  if(_artLayout){
    _artLayout.split = Math.round(pct * 10) / 10;
    var body = document.getElementById('art-body');
    body.style.setProperty('--art-split', 'minmax(0, ' + _artLayout.split + 'fr)');
    body.style.setProperty('--art-right', 'minmax(280px, ' + (100 - _artLayout.split) + 'fr)');
  }
}

function artEndDrag(){
  _artDrag = null;
  document.body.classList.remove('art-dragging');
  var d = document.getElementById('art-divider');
  if(d) d.classList.remove('dragging');
  document.removeEventListener('mousemove', artOnDrag);
  document.removeEventListener('mouseup', artEndDrag);
  artSaveLayout();
}

function artSwitchPdf(filename){
  var view = document.getElementById('art-pdf-view');
  if(!filename || !_artTaskId){
    view.innerHTML = '<div class="art-pdf-empty">No preview</div>';
    document.getElementById('art-pdf-open').style.display = 'none';
    _artCurrentPdf = null;
    return;
  }
  _artCurrentPdf = filename;
  var url = '/files/' + _artTaskId + '/' + encodeURIComponent(filename);
  view.innerHTML = '<embed src="'+esc(url)+'#toolbar=1&view=FitH" type="application/pdf">';
  document.getElementById('art-pdf-open').style.display = '';
  document.getElementById('art-pdf-open').setAttribute('data-url', url);
  if(_artLayout && !_artLayout.visible.resume){
    _artLayout.visible.resume = true;
    artSaveLayout();
    artApplyLayout();
  }
  var picker = document.getElementById('art-pdf-picker');
  if(picker && picker.value !== filename){
    for(var i=0;i<picker.options.length;i++){
      if(picker.options[i].value === filename){ picker.value = filename; break; }
    }
  }
  var home = document.getElementById('art-pdf-home');
  if(home){
    home.hidden = !(_artDefaultResume && filename !== _artDefaultResume);
  }
  document.querySelectorAll('#art-summary-pane .art-attach li').forEach(function(li){
    li.classList.toggle('current', li.getAttribute('data-fn') === filename);
  });
  if(_artCurrentData) renderArtifactSections(_artCurrentData);
  toast('Previewing ' + filename, 'ok');
}

function artBackToResume(){
  if(_artDefaultResume) artSwitchPdf(_artDefaultResume);
}

function attachIcon(name){
  var ext = (name||'').toLowerCase().split('.').pop();
  if(ext === 'pdf') return '&#128196;';
  if(ext === 'doc' || ext === 'docx') return '&#128221;';
  if(ext === 'xls' || ext === 'xlsx' || ext === 'csv') return '&#128202;';
  if(ext === 'ppt' || ext === 'pptx') return '&#128250;';
  if(ext === 'txt' || ext === 'md') return '&#128441;';
  if(ext === 'png' || ext === 'jpg' || ext === 'jpeg' || ext === 'gif' || ext === 'webp' || ext === 'svg') return '&#128444;';
  if(ext === 'zip' || ext === 'rar' || ext === '7z') return '&#128230;';
  return '&#128196;';
}

function attachRowClick(id, filename, isPdf){
  if(isPdf) artSwitchPdf(filename);
  else openFile(id, filename);
}

function attachView(id, filename){
  window.open('/files/' + id + '/' + encodeURIComponent(filename), '_blank');
}

function artOpenPdf(){
  var url = document.getElementById('art-pdf-open').getAttribute('data-url');
  if(url) window.open(url, '_blank');
}

function renderArtifact(d){
  _artCurrentData = d;
  _artAttachments = d.attachments || [];
  _artTaskType = artSlugify((d.metadata && d.metadata.task_type) || (d.parent && d.parent.name) || 'default');
  _artLayout = artLoadLayout(_artTaskType);

  document.getElementById('art-title').textContent = d.name || '(untitled)';
  document.getElementById('art-eyebrow').textContent = d.parent ? d.parent.name : 'Task';

  var sub = document.getElementById('art-sub');
  var subBits = [];
  if(d.status) subBits.push('<span class="art-chip st-'+esc(d.status)+'">'+esc(d.status)+'</span>');
  if(d.priority) subBits.push('<span class="art-chip">priority: '+esc(d.priority)+'</span>');
  (d.tags||[]).forEach(function(t){ subBits.push('<span class="tag">'+esc(t)+'</span>'); });
  sub.innerHTML = subBits.join('');

  artRenderPills();

  // PDF pane: populate picker, show resume
  var picker = document.getElementById('art-pdf-picker');
  var pdfs = (d.attachments||[]).filter(function(a){ return /\.pdf$/i.test(a.name); });
  _artDefaultResume = d.resume_filename || (pdfs.length ? pdfs[0].name : null);
  if(pdfs.length >= 1){
    var opts = pdfs.map(function(a){
      var sel = (a.name === d.resume_filename) ? ' selected' : '';
      return '<option value="'+esc(a.name)+'"'+sel+'>'+esc(a.name)+'</option>';
    }).join('');
    picker.innerHTML = opts;
    picker.style.display = pdfs.length > 1 ? '' : 'none';
  }else{
    picker.style.display = 'none';
  }
  if(_artDefaultResume){
    artSwitchPdf(_artDefaultResume);
  }else{
    document.getElementById('art-pdf-view').innerHTML =
      '<div class="art-pdf-empty">No PDF attached to this task.<br><br>'+
      'Attach a resume/CV PDF to the folder to preview it here.</div>';
    document.getElementById('art-pdf-open').style.display = 'none';
    var home = document.getElementById('art-pdf-home');
    if(home) home.hidden = true;
  }

  renderArtifactSections(d);
}

function buildSectionContent(key, d){
  var md = d.metadata || {};
  if(key === 'summary'){
    var inner, label;
    if(d.evaluation_body){
      label = 'AI Summary';
      inner = '<div class="art-md-rich">'+mdToHtml(d.evaluation_body)+'</div>';
      if(d.body){ inner += '<div class="md-h4" style="margin-top:14px">Email snippet</div><div class="art-md">'+esc(d.body)+'</div>'; }
    }else if(d.body){
      label = 'Summary';
      inner = '<div class="art-md">'+esc(d.body)+'</div>';
    }else{
      label = 'AI Summary';
      inner = '<div class="art-empty">No evaluation yet. Run the scoring skill to generate one.</div>';
    }
    return {label: label, inner: inner, count: ''};
  }
  if(key === 'metadata'){
    var reserved = {name:1,status:1,priority:1,tags:1,type:1};
    var rows = [];
    ['email','phone','source','role','department','received','overall_score','recommendation','next_action','thread_url','evaluated'].forEach(function(k){
      if(md[k] !== undefined && md[k] !== '' && md[k] !== null){
        var v = md[k];
        if(typeof v === 'object') v = JSON.stringify(v);
        var sv = String(v);
        var dd = /^https?:\/\//.test(sv) ? '<a href="'+esc(sv)+'" target="_blank">'+esc(sv.length>42?sv.substring(0,40)+'...':sv)+'</a>' : esc(sv);
        rows.push('<dt>'+esc(k)+'</dt><dd>'+dd+'</dd>');
        reserved[k] = 1;
      }
    });
    Object.keys(md).forEach(function(k){
      if(reserved[k]) return;
      var v = md[k];
      if(v === null || v === undefined || v === '') return;
      if(typeof v === 'object') v = JSON.stringify(v);
      var sv = String(v);
      var dd = /^https?:\/\//.test(sv) ? '<a href="'+esc(sv)+'" target="_blank">'+esc(sv)+'</a>' : esc(sv);
      rows.push('<dt>'+esc(k)+'</dt><dd>'+dd+'</dd>');
    });
    return {label:'Metadata', count: rows.length || '', inner: rows.length ? '<dl class="art-kv">'+rows.join('')+'</dl>' : '<div class="art-empty">No metadata</div>'};
  }
  if(key === 'attach'){
    var list = d.attachments || [];
    if(!list.length) return {label:'Attachments', count:'', inner:'<div class="art-empty">No attachments</div>'};
    var items = list.map(function(a){
      var isPdf = /\.pdf$/i.test(a.name);
      var isCur = isPdf && a.name === _artCurrentPdf;
      var cls = 'art-attach-row' + (isPdf ? ' previewable' : '') + (isCur ? ' current' : '');
      var nameAttr = esc(JSON.stringify(a.name));
      var icon = attachIcon(a.name);
      var badge = isCur ? '<span class="art-attach-badge">loaded</span>' : '';
      var mainLabel = isPdf ? (isCur ? 'Loaded' : 'Preview') : 'Open';
      var mainTitle = isPdf ? 'Preview in left pane' : 'Open in system app';
      var mainHandler = isPdf ? 'artSwitchPdf('+nameAttr+')' : 'openFile('+d.id+','+nameAttr+')';
      var mainBtn = '<button class="act" title="'+mainTitle+'" onclick="event.stopPropagation();'+mainHandler+'">'+mainLabel+'</button>';
      var extBtn = '<button class="act act-icon" title="Open in new tab" onclick="event.stopPropagation();attachView('+d.id+','+nameAttr+')">&#8599;</button>';
      return '<li class="'+cls+'" data-fn="'+esc(a.name)+'" onclick="attachRowClick('+d.id+','+nameAttr+','+(isPdf?'true':'false')+')">'+
        '<span class="art-attach-name"><span class="art-attach-icon">'+icon+'</span>'+esc(a.name)+badge+'</span>'+
        '<span class="art-attach-size">'+fmtBytes(a.size)+'</span>'+
        '<span class="art-attach-btns">'+mainBtn+extBtn+'</span>'+
        '</li>';
    }).join('');
    return {label:'Attachments', count:list.length, inner:'<ul class="art-attach">'+items+'</ul>'};
  }
  if(key === 'activity'){
    var list = d.activity || [];
    if(!list.length) return {label:'Activity', count:'', inner:'<div class="art-empty">No activity yet</div>'};
    var acts = list.map(function(a){
      var msg = esc(a.action);
      if(a.from_value || a.to_value){ msg += ' <b>'+esc(a.from_value||'-')+'</b> &rarr; <b>'+esc(a.to_value||'-')+'</b>'; }
      if(a.actor) msg += ' <span style="color:var(--mute)">by '+esc(a.actor)+'</span>';
      return '<li><span class="art-act-time">'+esc(fmtTime(a.at))+'</span><span class="art-act-msg">'+msg+'</span></li>';
    }).join('');
    return {label:'Activity', count:list.length, inner:'<ul class="art-act-list">'+acts+'</ul>'};
  }
  if(key === 'path'){
    return {label:'Path', count:'', inner:'<div class="art-path">'+esc(d.path||'')+'</div>'};
  }
  return {label:key, count:'', inner:''};
}

function renderArtifactSections(d){
  if(!d){
    document.getElementById('art-summary-pane').innerHTML = '<div class="art-empty" style="padding:30px">No task data.</div>';
    return;
  }
  if(!_artLayout){
    _artLayout = artLoadLayout(_artTaskType || 'default');
  }
  var md = d.metadata || {};
  var parts = [];

  // Actions row (always shown, outside group system)
  var actBtns = '<div class="art-sec" data-section="_actions" style="border:none;background:transparent;margin-bottom:12px;display:flex;flex-direction:row;gap:6px;flex-wrap:wrap">'+
    '<button class="btn" onclick="openFolder('+d.id+')">Open Folder</button>';
  if(d.has_evaluation){ actBtns += '<button class="btn" onclick="openFile('+d.id+',\'evaluation.md\')">Open Report</button>'; }
  if(md.thread_url){ actBtns += '<a class="btn" href="'+esc(md.thread_url)+'" target="_blank">Gmail</a>'; }
  actBtns += '</div>';
  parts.push(actBtns);

  var v = _artLayout.visible;
  var groups = _artLayout.groups || [];
  groups.forEach(function(grp, gIdx){
    var visibleKeys = grp.filter(function(k){ return v[k]; });
    if(!visibleKeys.length) return;
    var keysAttr = esc(visibleKeys.join(','));
    var active = _artLayout.activeTab[gIdx];
    if(!active || visibleKeys.indexOf(active) < 0) active = visibleKeys[0];
    var firstKey = visibleKeys[0];
    var isCollapsed = visibleKeys.every(function(k){ return _artLayout.collapsed[k]; });
    var sized = '';
    if(_artLayout.heights[firstKey]){ sized = 'sized'; }
    var styleAttr = _artLayout.heights[firstKey] ? ' style="--sec-height:'+_artLayout.heights[firstKey]+'px"' : '';

    var headInner;
    var contentInner;
    var secCls = 'art-sec ' + sized + (isCollapsed ? ' collapsed' : '') + (visibleKeys.length > 1 ? ' tabbed' : '');

    if(visibleKeys.length === 1){
      var c = buildSectionContent(visibleKeys[0], d);
      var keyAttr = esc(JSON.stringify(visibleKeys[0]));
      var countChip = (c.count === '' || c.count === 0) ? '' : '<span class="art-sec-count">'+esc(c.count)+'</span>';
      headInner =
        '<span class="art-sec-chevron" aria-hidden="true">&#9660;</span>'+
        '<span class="art-sec-drag" title="Drag to reorder / group" aria-hidden="true">&#8942;&#8942;</span>'+
        '<span class="art-sec-label">'+esc(c.label)+'</span>'+
        countChip+
        '<button class="art-sec-close" title="Close section" onclick="event.stopPropagation();artSecClose('+keyAttr+')">&times;</button>';
      contentInner = c.inner;
    }else{
      var tabsHtml = visibleKeys.map(function(k){
        var c = buildSectionContent(k, d);
        var isAct = k === active ? ' active' : '';
        var countChip = (c.count === '' || c.count === 0) ? '' : ' <span class="art-sec-count">'+esc(c.count)+'</span>';
        var kAttr = esc(JSON.stringify(k));
        return '<div class="art-tab'+isAct+'" data-key="'+esc(k)+'">'+
          '<span class="art-tab-label" onclick="event.stopPropagation();artSwitchTab('+gIdx+','+kAttr+')">'+esc(c.label)+countChip+'</span>'+
          '<span class="art-tab-action" title="Split out" onclick="event.stopPropagation();artPopOutTab('+gIdx+','+kAttr+')">&#8600;</span>'+
          '<span class="art-tab-action close" title="Close tab" onclick="event.stopPropagation();artSecClose('+kAttr+')">&times;</span>'+
        '</div>';
      }).join('');
      headInner = '<span class="art-sec-drag" title="Drag group">&#8942;&#8942;</span>'+
        '<div class="art-sec-tabs">'+tabsHtml+'</div>'+
        '<button class="art-sec-close" title="Close group" onclick="event.stopPropagation();artSecCloseGroup('+gIdx+')">&times;</button>';
      contentInner = visibleKeys.map(function(k){
        var c = buildSectionContent(k, d);
        var isAct = k === active ? ' active' : '';
        return '<div class="art-pane'+isAct+'" data-key="'+esc(k)+'">'+c.inner+'</div>';
      }).join('');
    }

    var firstKeyAttr = esc(JSON.stringify(firstKey));
    var onclickHead = visibleKeys.length === 1
      ? 'onclick="artSecToggleCollapse('+esc(JSON.stringify(visibleKeys[0]))+')"' : '';
    parts.push(
      '<div class="'+secCls+'" data-group="'+gIdx+'" data-group-keys="'+keysAttr+'" '+
      'draggable="true" '+
      'ondragstart="artSecOnDragStart(event,'+firstKeyAttr+')" '+
      'ondragend="artSecOnDragEnd(event)" '+
      'ondragover="artSecOnDragOver(event)" '+
      'ondragleave="artSecOnDragLeave(event)" '+
      'ondrop="artSecOnDrop(event)"'+styleAttr+'>'+
        '<div class="art-sec-head" '+onclickHead+'>'+headInner+'</div>'+
        '<div class="art-sec-content">'+contentInner+'</div>'+
        '<div class="art-sec-resize" ondblclick="artResetHeight(event,'+firstKeyAttr+')" onmousedown="artStartResize(event,'+firstKeyAttr+')" title="Drag to resize, double-click to reset"></div>'+
      '</div>');
  });

  var anyRight = ART_RIGHT_KEYS.some(function(k){ return _artLayout.visible[k]; });
  if(!anyRight){
    parts.push('<div class="art-empty" style="padding:30px;text-align:center">All detail sections are hidden. Click a pill at the top (Summary, Metadata, Activity, Attachments, Path) to show one.</div>');
  }
  document.getElementById('art-summary-pane').innerHTML = parts.join('');
  artApplyLayout();
}

window.addEventListener('keydown', function(e){
  if(e.key === 'Escape'){
    var l = document.getElementById('layout');
    if(l && l.classList.contains('artifact-open')) closeArtifact();
  }
});

(function initArtifactFromUrl(){
  try{
    var m = location.search.match(/[?&]task=(\d+)/);
    if(m){
      var l = document.getElementById('layout');
      if(l) l.classList.add('artifact-open');
      openTaskArtifact(parseInt(m[1],10));
    }
  }catch(e){
    var s = document.getElementById('art-summary-pane');
    if(s) s.innerHTML = '<div class="art-empty" style="padding:30px">Init error: '+String(e && e.message || e)+'</div>';
  }
})();

window.addEventListener('error', function(ev){
  try{
    var s = document.getElementById('art-summary-pane');
    if(s && !s.innerHTML.trim()){
      s.innerHTML = '<div class="art-empty" style="padding:30px;color:var(--red)">JS error: '+String(ev.message || ev.error)+'</div>';
    }
  }catch(e){}
});
"""


def _e(s: Any) -> str:
    return htmllib.escape("" if s is None else str(s))


def _score_band(score: Any) -> tuple[str, str]:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ("unscored", "-")
    if s >= 8.5:
        return ("strong", f"{s:.1f}")
    if s >= 7.0:
        return ("shortlist", f"{s:.1f}")
    if s >= 5.0:
        return ("borderline", f"{s:.1f}")
    return ("reject", f"{s:.1f}")


def _priority_class(p: str) -> str:
    p = (p or "").lower()
    if p in ("high", "urgent", "critical", "p0", "p1"):
        return "priority-high"
    if p in ("medium", "med", "normal", "p2"):
        return "priority-med"
    if p in ("low", "p3", "p4"):
        return "priority-low"
    return "priority-med"


def _render_tree(tree: dict, active_id: int | None = None) -> str:
    if not tree:
        return '<div style="padding:12px;color:var(--mute);font-size:11px">No workspace indexed yet.</div>'
    return _render_tree_nodes(tree.get("children", []), active_id)


def _render_tree_nodes(nodes: list, active_id: int | None) -> str:
    if not nodes:
        return ""
    out = []
    for node in nodes:
        nid = node.get("id")
        name = node.get("name", "")
        ntype = node.get("type", "")
        kids = node.get("children", [])
        href = _node_href(nid, ntype)
        is_active = (nid == active_id)
        caret = ">" if kids else "."
        active_cls = " active" if is_active else ""
        link_click = (
            f'onclick="return cardOpen(event,{_e(nid)})"'
            if ntype == "task" else 'onclick="event.stopPropagation()"'
        )
        if kids:
            out.append(f'<div class="nav-node">')
            out.append(
                f'<div class="nav-item{active_cls}" data-node-id="{_e(nid)}" '
                f'onclick="event.stopPropagation();nodeToggle(this)">'
                f'<span class="nav-caret">{caret}</span>'
                f'<a class="nav-name" href="{_e(href)}" {link_click}>{_e(name)}</a>'
                f'<span class="nav-type">{_e(ntype[:3])}</span>'
                f'</div>'
            )
            out.append('<div class="nav-children">')
            out.append(_render_tree_nodes(kids, active_id))
            out.append('</div>')
            out.append('</div>')
        else:
            out.append(
                f'<div class="nav-item{active_cls}">'
                f'<span class="nav-caret">-</span>'
                f'<a class="nav-name" href="{_e(href)}" {link_click}>{_e(name)}</a>'
                f'<span class="nav-type">{_e(ntype[:3])}</span>'
                f'</div>'
            )
    return "".join(out)


def _node_href(nid: Any, ntype: str) -> str:
    if ntype == "department":
        return f"/d/{nid}"
    if ntype == "position":
        return f"/p/{nid}"
    if ntype == "task":
        return f"/t/{nid}"
    return "/"


def _sidebar(tree: dict, active_id: int | None, root_name: str) -> str:
    tree_html = _render_tree(tree, active_id)
    name = branding.app_name()
    initial = (name[:1] or "H").upper()
    return f"""<aside class="side">
  <button class="side-toggle" onclick="toggleSidebar()" title="Collapse sidebar" aria-label="Collapse sidebar">&#9664;</button>
  <div class="side-head">
    <div class="brand-mark">{_e(initial)}</div>
    <div class="brand-text">
      <div class="brand-name">{_e(name)}</div>
      <div class="brand-tag">{_e(root_name)}</div>
    </div>
  </div>
  <nav class="nav">
    <div class="nav-section">Workspace</div>
    <div class="nav-item" onclick="location.href='/'">
      <span class="nav-caret">#</span>
      <span class="nav-name">Home</span>
    </div>
    <div class="nav-item" onclick="location.href='/activity'">
      <span class="nav-caret">#</span>
      <span class="nav-name">Activity</span>
    </div>
    <div class="nav-section">Tree</div>
    {tree_html}
  </nav>
  <div class="side-foot">
    <button class="btn" onclick="runScan()">Scan</button>
    <button class="btn" onclick="toggleTheme()">Theme</button>
  </div>
</aside>"""


def _footer(generated: str) -> str:
    return f"""<footer class="foot-bar">
  <span>Generated {_e(generated)} &middot; {_e(branding.app_name())}</span>
  <span>127.0.0.1 &middot; local-only</span>
</footer>"""


def _page_shell(title: str, body: str, tree: dict, active_id: int | None,
                root_name: str, generated: str, extra_head: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<title>{_e(title)} &middot; {_e(branding.app_name())}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>{CSS}</style>
{extra_head}
</head>
<body>
<div class="layout" id="layout">
  {_sidebar(tree, active_id, root_name)}
  <main class="content">
    {body}
    {_footer(generated)}
  </main>
  <aside class="artifact" id="artifact" aria-hidden="true">
    <div class="art-head">
      <div class="art-title-wrap">
        <div class="art-eyebrow" id="art-eyebrow">Task</div>
        <div class="art-title" id="art-title">&nbsp;</div>
      </div>
      <div class="art-head-btns">
        <button class="art-icon close" onclick="closeArtifact()" title="Close (Esc)" aria-label="Close">&times;</button>
      </div>
    </div>
    <div class="art-sub" id="art-sub"></div>
    <div class="art-pills" id="art-pills"></div>
    <div class="art-body" id="art-body">
      <div class="art-pdf-pane" id="art-pdf-pane">
        <div class="art-pdf-head">
          <button class="art-pdf-home" id="art-pdf-home" onclick="artBackToResume()" title="Back to resume" hidden>&#8617; Resume</button>
          <select class="art-pdf-picker" id="art-pdf-picker" onchange="artSwitchPdf(this.value)" style="display:none"></select>
          <div class="art-pdf-actions">
            <button class="art-icon" id="art-pdf-open" onclick="artOpenPdf()" title="Open in new tab" aria-label="Open in new tab" style="display:none">&#8599;</button>
          </div>
        </div>
        <div class="art-pdf-view" id="art-pdf-view">
          <div class="art-pdf-empty">Select a task to preview</div>
        </div>
      </div>
      <div class="art-divider" id="art-divider" onmousedown="artStartDrag(event)" title="Drag to resize"></div>
      <div class="art-summary-pane" id="art-summary-pane">
        <div class="art-loading">Loading...</div>
      </div>
    </div>
  </aside>
</div>
<div id="toast" class="toast"></div>
<script>{JS_COMMON}</script>
</body>
</html>"""


def _stats_chips(stats: dict) -> str:
    by_status = stats.get("by_status", {}) if stats else {}
    if not by_status:
        return ""
    parts = []
    for k, v in by_status.items():
        parts.append(f'<span class="status-chip"><b>{v}</b>{_e(k or "none")}</span>')
    return f'<div class="status-chips">{"".join(parts)}</div>'


def _meta_summary(f: Folder) -> str:
    bits = []
    if f.metadata.get("description"):
        bits.append(_e(f.metadata.get("description")))
    elif f.body:
        bits.append(_e(f.body[:140] + ("..." if len(f.body) > 140 else "")))
    return bits[0] if bits else ""


def render_landing(root_name: str, departments: list[Folder], stats: dict, generated: str) -> str:
    total = stats.get("total", 0) if stats else 0
    by_type = stats.get("by_type", {}) if stats else {}
    by_status = stats.get("by_status", {}) if stats else {}

    cards = []
    for d in departments:
        pos_count = 0
        desc = _meta_summary(d)
        cards.append(f"""
        <a class="tile" href="/d/{_e(d.id)}">
          <div class="tile-top">
            <div class="tile-title">{_e(d.name)}</div>
            <span class="pill">DEPT</span>
          </div>
          <div class="tile-desc">{desc or "Department"}</div>
          <div class="tile-foot">
            <span>{_e(d.path)}</span>
          </div>
        </a>""")

    if not cards:
        cards.append('<div class="empty" style="grid-column:1/-1">No departments yet. Create a folder with a getset.md marker, then click Scan.</div>')

    status_chips = _stats_chips(stats)

    # tree fetched inline
    body = f"""
<header class="top">
  <div>
    <h1 class="page-title">{_e(root_name)}</h1>
    <div class="page-sub">{_e(by_type.get("department", 0))} departments &middot; {_e(by_type.get("position", 0))} positions &middot; {_e(by_type.get("task", 0))} tasks</div>
  </div>
  <div class="stats">
    <div class="stat"><span class="v">{total}</span><span class="k">Folders</span></div>
    <div class="stat"><span class="v">{_e(by_type.get("task", 0))}</span><span class="k">Tasks</span></div>
  </div>
  <div class="top-btns">
    <button class="btn" onclick="runScan()">Scan</button>
    <button class="btn" onclick="toggleTheme()">Theme</button>
  </div>
</header>
<section class="pane">
  {status_chips}
  <h2 style="font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:0.8px;margin:18px 0 12px;font-weight:600">Departments</h2>
  <div class="cards-grid">{"".join(cards)}</div>
</section>
"""
    tree = _inline_tree_from_depts(departments)
    return _page_shell(root_name, body, tree, None, root_name, generated)


def _inline_tree_from_depts(departments: list[Folder]) -> dict:
    return {
        "id": None, "name": "root", "type": "workspace",
        "children": [{"id": d.id, "name": d.name, "type": "department", "children": []} for d in departments]
    }


def render_department(dept: Folder, positions: list[Folder], stats: dict, generated: str, tree: dict) -> str:
    cards = []
    for p in positions:
        desc = _meta_summary(p)
        cards.append(f"""
        <a class="tile" href="/p/{_e(p.id)}">
          <div class="tile-top">
            <div class="tile-title">{_e(p.name)}</div>
            <span class="pill">POS</span>
          </div>
          <div class="tile-desc">{desc or "Position"}</div>
          <div class="tile-foot">
            <span>{_e(p.status or "")}</span>
            <span>{_e(p.priority or "")}</span>
          </div>
        </a>""")
    if not cards:
        cards.append('<div class="empty" style="grid-column:1/-1">No positions in this department.</div>')

    status_chips = _stats_chips(stats)
    root_name = _root_name_from_tree(tree)

    body = f"""
<header class="top">
  <div class="crumbs">
    <a href="/">Home</a>
    <span class="sep">/</span>
    <span class="cur">{_e(dept.name)}</span>
  </div>
  <div class="stats">
    <div class="stat"><span class="v">{len(positions)}</span><span class="k">Positions</span></div>
    <div class="stat"><span class="v">{_e(stats.get("total", 0))}</span><span class="k">Total</span></div>
  </div>
  <div class="top-btns">
    <button class="btn" onclick="openFolder({_e(dept.id)})">Open Folder</button>
    <button class="btn" onclick="toggleTheme()">Theme</button>
  </div>
</header>
<section class="pane">
  <h1 class="page-title">{_e(dept.name)}</h1>
  <div class="page-sub">{_e(_meta_summary(dept))}</div>
  <div style="margin-top:14px">{status_chips}</div>
  <h2 style="font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:0.8px;margin:18px 0 12px;font-weight:600">Positions</h2>
  <div class="cards-grid">{"".join(cards)}</div>
</section>
"""
    return _page_shell(dept.name, body, tree, dept.id, root_name, generated)


def _root_name_from_tree(tree: dict) -> str:
    return (tree or {}).get("name", "Workspace")


def render_position(position: Folder, tasks: list[Folder], columns: list[str],
                    statuses: list[str], generated: str, tree: dict) -> str:
    # Group tasks by column
    by_col: dict[str, list[Folder]] = {c: [] for c in columns}
    for t in tasks:
        col = STATUS_TO_COLUMN.get((t.status or "").lower(), columns[0] if columns else "applied")
        if col not in by_col:
            col = columns[0] if columns else "applied"
        by_col[col].append(t)

    # Score sort within column
    def _score_f(x: Folder) -> float:
        try:
            return float(x.metadata.get("overall_score", ""))
        except (TypeError, ValueError):
            return -1.0
    for c in by_col:
        by_col[c].sort(key=lambda x: (-_score_f(x), x.name))

    cols_html = []
    for col in columns:
        accent = COLUMN_ACCENT.get(col, "#6366f1")
        label = COLUMN_LABEL.get(col, col.title())
        items = by_col.get(col, [])
        cards = "\n".join(_render_task_card(t) for t in items)
        if not cards:
            cards = '<div class="empty">Drop here</div>'
        new_btn = ""
        if col == "applied":
            new_btn = f'<button class="col-new" onclick="openNewDlg()" title="New task">+</button>'
        cols_html.append(f"""
        <section class="column">
          <header class="col-head">
            <span class="dot" style="background:{_e(accent)}"></span>
            <span class="col-title">{_e(label)}</span>
            <span class="col-count">{len(items)}</span>
            {new_btn}
          </header>
          <div class="col-body" data-col="{_e(col)}">{cards}</div>
        </section>""")

    root_name = _root_name_from_tree(tree)
    pos_id = position.id or 0
    statuses_json = json.dumps(statuses)
    cols_json = json.dumps(columns)

    extra_head = '<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>'

    parent_crumbs = ""
    parent_id = position.parent_id
    if parent_id:
        parent_crumbs = f'<a href="/d/{_e(parent_id)}">Department</a><span class="sep">/</span>'

    body = f"""
<header class="top">
  <div class="crumbs">
    <a href="/">Home</a>
    <span class="sep">/</span>
    {parent_crumbs}
    <span class="cur">{_e(position.name)}</span>
  </div>
  <div class="stats">
    <div class="stat"><span class="v">{len(tasks)}</span><span class="k">Tasks</span></div>
  </div>
  <div class="top-btns">
    <button class="btn btn-primary" onclick="openNewDlg()">+ New Task</button>
    <button class="btn" onclick="openFolder({_e(pos_id)})">Open Folder</button>
    <button class="btn" onclick="runScan()">Scan</button>
    <button class="btn" onclick="toggleTheme()">Theme</button>
  </div>
</header>
<section class="pane" style="padding-bottom:0">
  <h1 class="page-title">{_e(position.name)}</h1>
  <div class="page-sub">{_e(_meta_summary(position))}</div>
</section>
<main class="board">
  {"".join(cols_html)}
</main>

<div id="dlg-backdrop">
  <div class="dlg">
    <h3>New task</h3>
    <div class="dlg-row">
      <label>Name</label>
      <input id="nt-name" type="text" placeholder="e.g. Jane Doe">
    </div>
    <div class="dlg-row">
      <label>Status</label>
      <select id="nt-status">
        {"".join(f'<option value="{_e(s)}">{_e(s)}</option>' for s in statuses)}
      </select>
    </div>
    <div class="dlg-row">
      <label>Priority</label>
      <select id="nt-priority">
        <option value="">(none)</option>
        <option value="high">high</option>
        <option value="medium" selected>medium</option>
        <option value="low">low</option>
      </select>
    </div>
    <div class="dlg-row">
      <label>Tags (comma separated)</label>
      <input id="nt-tags" type="text" placeholder="optional">
    </div>
    <div class="dlg-btns">
      <button class="btn" onclick="closeNewDlg()">Cancel</button>
      <button class="btn btn-primary" onclick="submitNew()">Create</button>
    </div>
  </div>
</div>

<script>
  const POSITION_ID = {pos_id};
  const STATUSES = {statuses_json};
  const COLUMNS = {cols_json};
  const COL_TO_STATUS_DEFAULT = {{
    "applied":"applied","screening":"screening","interview":"interview","offer":"offer"
  }};

  function openNewDlg(){{
    document.getElementById('nt-name').value = '';
    document.getElementById('nt-tags').value = '';
    document.getElementById('dlg-backdrop').classList.add('show');
    setTimeout(function(){{ document.getElementById('nt-name').focus(); }}, 50);
  }}
  function closeNewDlg(){{
    document.getElementById('dlg-backdrop').classList.remove('show');
  }}
  async function submitNew(){{
    var name = document.getElementById('nt-name').value.trim();
    if(!name){{ toast('Name required','err'); return; }}
    var status = document.getElementById('nt-status').value;
    var priority = document.getElementById('nt-priority').value;
    var tagsRaw = document.getElementById('nt-tags').value.trim();
    var tags = tagsRaw ? tagsRaw.split(',').map(function(s){{return s.trim();}}).filter(Boolean) : [];
    try{{
      var r = await fetch('/api/create-task',{{method:'POST',headers:{{'content-type':'application/json'}},
        body:JSON.stringify({{position_id:POSITION_ID,name:name,status:status,priority:priority,tags:tags}})}});
      if(!r.ok) throw new Error(await r.text());
      toast('Created','ok');
      closeNewDlg();
      setTimeout(function(){{ location.reload(); }}, 400);
    }}catch(e){{ toast('Failed: '+e.message,'err'); }}
  }}

  async function postMove(card, newStatus){{
    try{{
      var r = await fetch('/api/move',{{method:'POST',headers:{{'content-type':'application/json'}},
        body:JSON.stringify({{task_id:parseInt(card.dataset.id),status:newStatus}})}});
      if(!r.ok) throw new Error(await r.text());
      card.dataset.status = newStatus;
      toast(card.dataset.name + ' -> ' + newStatus, 'ok');
      setTimeout(function(){{ location.reload(); }}, 500);
    }}catch(e){{ toast('Move failed: '+e.message,'err');
      setTimeout(function(){{ location.reload(); }}, 700); }}
  }}

  // Close-dialog flow when dropping on closed column
  var pendingClose = null;
  function askClose(card, fromEl){{
    pendingClose = {{card:card, fromEl:fromEl}};
    var opts = ['hired','rejected'].filter(function(s){{ return STATUSES.indexOf(s) >= 0; }});
    if(opts.length === 0){{ opts = ['hired','rejected']; }}
    var chosen = window.prompt('Close as? (' + opts.join(' / ') + ')', opts[0]);
    if(!chosen || opts.indexOf(chosen) < 0){{
      fromEl.appendChild(card);
      pendingClose = null;
      return;
    }}
    pendingClose = null;
    postMove(card, chosen);
  }}

  document.querySelectorAll('.col-body').forEach(function(el){{
    new Sortable(el, {{
      group:'hrkit-tasks', animation:180,
      ghostClass:'drag-ghost', chosenClass:'drag-chosen',
      onEnd:function(evt){{
        var card = evt.item;
        var fromEl = evt.from;
        var toCol = evt.to.dataset.col;
        if(!toCol) return;
        if(toCol === 'closed'){{
          askClose(card, fromEl);
        }}else{{
          var newStatus = COL_TO_STATUS_DEFAULT[toCol] || toCol;
          if(newStatus === card.dataset.status) return;
          postMove(card, newStatus);
        }}
      }},
    }});
  }});

  document.addEventListener('keydown', function(e){{
    if(e.key === 'Escape') closeNewDlg();
  }});
</script>
"""
    return _page_shell(position.name, body, tree, position.id, root_name, generated, extra_head)


def _render_task_card(t: Folder) -> str:
    md = t.metadata or {}
    score = md.get("overall_score", "")
    band, score_label = _score_band(score)
    score_html = f'<span class="score score-{band}">{_e(score_label)}</span>' if score != "" else ""

    outcome = ""
    if (t.status or "").lower() == "hired":
        outcome = '<span class="outcome outcome-hired">HIRED</span>'
    elif (t.status or "").lower() == "rejected":
        outcome = '<span class="outcome outcome-rejected">REJECTED</span>'

    pri_html = ""
    if t.priority:
        pri_html = f'<span class="priority {_priority_class(t.priority)}">{_e(t.priority)}</span>'

    tags_html = "".join(f'<span class="tag">{_e(tg)}</span>' for tg in (t.tags or [])[:3])

    next_action = md.get("next_action", "")
    next_html = f'<div class="next" title="Next action">{_e(next_action)}</div>' if next_action else ""

    role = md.get("role", "")
    role_html = f'<div class="role">{_e(role)}</div>' if role else ""

    updated = t.updated or t.created or ""
    thread_url = md.get("thread_url", "")
    has_eval = bool(md.get("has_evaluation") or md.get("evaluated"))

    gmail_btn = ""
    if thread_url:
        gmail_btn = (
            f'<a class="act" href="{_e(thread_url)}" target="_blank" '
            f'onclick="event.stopPropagation()">Gmail</a>'
        )
    eval_btn = ""
    if has_eval:
        eval_btn = (
            f'<button class="act" onclick="event.stopPropagation();openFile({_e(t.id)},\'evaluation.md\')">Report</button>'
        )

    return f"""<div class="card" data-id="{_e(t.id)}" data-name="{_e(t.name)}" data-status="{_e(t.status)}">
  <div class="card-top">
    <div class="name"><a href="/t/{_e(t.id)}" onclick="return cardOpen(event,{_e(t.id)})">{_e(t.name)}</a></div>
    <div class="top-right">
      {outcome}
      {pri_html}
      {score_html}
    </div>
  </div>
  {role_html}
  <div class="chips">{tags_html}</div>
  {next_html}
  <div class="foot">
    <span>{_e(md.get("source", ""))}</span>
    <span>{_e((updated or "")[:10])}</span>
  </div>
  <div class="actions">
    <button class="act" onclick="event.stopPropagation();openFolder({_e(t.id)})">Folder</button>
    {eval_btn}
    {gmail_btn}
  </div>
</div>"""


def render_task(task: Folder, parent_position: Folder, attachments: list[str],
                activity: list[dict], generated: str, tree: dict) -> str:
    md = task.metadata or {}
    root_name = _root_name_from_tree(tree)

    # Metadata KV
    def kv(k: str, v: Any) -> str:
        if v is None or v == "":
            return ""
        return f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>"

    kv_rows = []
    kv_rows.append(kv("Name", task.name))
    kv_rows.append(kv("Status", task.status))
    kv_rows.append(kv("Priority", task.priority))
    if task.tags:
        kv_rows.append(f'<dt>Tags</dt><dd>{"".join(f"<span class=\'tag\' style=\'margin-right:4px\'>{_e(t)}</span>" for t in task.tags)}</dd>')
    for k, v in md.items():
        if k in ("name", "status", "priority", "tags", "type"):
            continue
        if isinstance(v, (list, dict)):
            kv_rows.append(kv(k, json.dumps(v)))
        else:
            kv_rows.append(kv(k, v))
    kv_rows.append(kv("Created", task.created))
    kv_rows.append(kv("Updated", task.updated))
    kv_rows.append(kv("Closed", task.closed))
    kv_rows.append(kv("Path", task.path))

    kv_html = "".join(r for r in kv_rows if r)

    attach_items = []
    for fn in attachments:
        attach_items.append(
            f'<li><span class="attach-name">{_e(fn)}</span>'
            f'<button class="act" onclick="openFile({_e(task.id)},{json.dumps(fn)})">Open</button></li>'
        )
    attach_html = "".join(attach_items) if attach_items else '<li style="color:var(--mute);font-style:italic;border:none">(no files)</li>'

    act_items = []
    for a in activity:
        at = a.get("at", "")
        action = a.get("action", "")
        fr = a.get("from_value", "")
        to = a.get("to_value", "")
        actor = a.get("actor", "")
        note = a.get("note", "")
        change = ""
        if fr or to:
            change = f' <b>{_e(fr or "-")}</b> -> <b>{_e(to or "-")}</b>'
        act_items.append(
            f'<li><span class="activity-time">{_e(at[:19])}</span>'
            f'<span class="activity-action">{_e(action)}{change} <span style="color:var(--mute)">by {_e(actor)}</span>'
            f'{(" - " + _e(note)) if note else ""}</span></li>'
        )
    act_html = "".join(act_items) if act_items else '<li style="color:var(--mute);font-style:italic;border:none">(no activity yet)</li>'

    parent_link = ""
    if parent_position and parent_position.id:
        parent_link = f'<a href="/p/{_e(parent_position.id)}">{_e(parent_position.name)}</a><span class="sep">/</span>'

    body_html = _e(task.body) if task.body else '<span style="color:var(--mute);font-style:italic">(empty)</span>'

    body = f"""
<header class="top">
  <div class="crumbs">
    <a href="/">Home</a>
    <span class="sep">/</span>
    {parent_link}
    <span class="cur">{_e(task.name)}</span>
  </div>
  <div class="top-btns">
    <button class="btn" onclick="openFolder({_e(task.id)})">Open Folder</button>
    <button class="btn" onclick="toggleTheme()">Theme</button>
  </div>
</header>
<section class="pane">
  <h1 class="page-title">{_e(task.name)}</h1>
  <div class="page-sub">{_e(task.status)} &middot; {_e(task.priority or "no priority")}</div>
  <div class="detail-grid" style="margin-top:18px">
    <div style="display:flex;flex-direction:column;gap:18px">
      <div class="panel">
        <h2>Body</h2>
        <div class="md-body">{body_html}</div>
      </div>
      <div class="panel">
        <h2>Activity</h2>
        <ul class="activity-list">{act_html}</ul>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:18px">
      <div class="panel">
        <h2>Metadata</h2>
        <dl class="kv">{kv_html}</dl>
      </div>
      <div class="panel">
        <h2>Attachments</h2>
        <ul class="attach-list">{attach_html}</ul>
      </div>
    </div>
  </div>
</section>
"""
    return _page_shell(task.name, body, tree, task.id, root_name, generated)


def render_activity(activity: list[dict], generated: str, tree: dict) -> str:
    root_name = _root_name_from_tree(tree)
    items = []
    for a in activity:
        at = a.get("at", "")
        action = a.get("action", "")
        fr = a.get("from_value", "")
        to = a.get("to_value", "")
        actor = a.get("actor", "")
        note = a.get("note", "")
        fname = a.get("folder_name", "")
        fid = a.get("folder_id")
        ftype = a.get("folder_type", "")
        href = _node_href(fid, ftype)
        change = ""
        if fr or to:
            change = f' <b>{_e(fr or "-")}</b> -> <b>{_e(to or "-")}</b>'
        items.append(
            f'<li><span class="activity-time">{_e(at[:19])}</span>'
            f'<span class="activity-action">'
            f'<a href="{_e(href)}">{_e(fname or "-")}</a> &middot; {_e(action)}{change} '
            f'<span style="color:var(--mute)">by {_e(actor)}</span>'
            f'{(" - " + _e(note)) if note else ""}'
            f'</span></li>'
        )
    list_html = "".join(items) if items else '<li style="color:var(--mute);font-style:italic;border:none">(no activity recorded)</li>'

    body = f"""
<header class="top">
  <div class="crumbs">
    <a href="/">Home</a>
    <span class="sep">/</span>
    <span class="cur">Activity</span>
  </div>
  <div class="top-btns">
    <button class="btn" onclick="runScan()">Scan</button>
    <button class="btn" onclick="toggleTheme()">Theme</button>
  </div>
</header>
<section class="pane">
  <h1 class="page-title">Activity feed</h1>
  <div class="page-sub">{len(activity)} most recent events across the workspace</div>
  <div class="panel" style="margin-top:18px">
    <ul class="activity-list">{list_html}</ul>
  </div>
</section>
"""
    return _page_shell("Activity", body, tree, None, root_name, generated)


# =============================================================================
# HR module pages (Wave 2 integration)
# =============================================================================
# Every module file in ``hrkit/modules/`` calls ``render_module_page``
# to wrap its CRUD body in a consistent shell with a top nav across all
# registered modules. The shell uses the white-label app name from
# ``branding.app_name()``.

MODULE_NAV = [
    ("employee",    "Employees"),
    ("department",  "Departments"),
    ("role",        "Roles"),
    ("document",    "Documents"),
    ("leave",       "Leave"),
    ("attendance",  "Attendance"),
    ("payroll",     "Payroll"),
    ("performance", "Performance"),
    ("onboarding",  "Onboarding"),
    ("exit_record", "Exits"),
    ("recruitment", "Recruitment"),
]


MODULE_CSS = r"""
:root{--bg:#0b0d12;--panel:#11141b;--border:rgba(255,255,255,0.08);
  --text:#e8eaed;--dim:#9aa0a6;--accent:#6366f1;--green:#10b981;--red:#f43f5e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;font-size:14px}
.app-bar{display:flex;align-items:center;gap:18px;padding:12px 24px;
  border-bottom:1px solid var(--border);background:var(--panel);
  position:sticky;top:0;z-index:10}
.app-brand{font-weight:700;font-size:15px;letter-spacing:-0.01em}
.app-brand a{color:inherit;text-decoration:none}
.app-nav{display:flex;gap:4px;flex:1;overflow-x:auto;scrollbar-width:thin}
.app-nav a{padding:6px 12px;border-radius:6px;color:var(--dim);
  text-decoration:none;font-size:13px;white-space:nowrap}
.app-nav a:hover{color:var(--text);background:rgba(255,255,255,0.04)}
.app-nav a.active{color:var(--text);background:color-mix(in srgb,var(--accent) 22%,transparent)}
.app-actions a{padding:6px 12px;border-radius:6px;color:var(--dim);
  text-decoration:none;font-size:13px}
.app-actions a:hover{color:var(--text)}
.app-content{padding:24px;max-width:1400px;margin:0 auto}
.module-toolbar{display:flex;align-items:center;gap:14px;margin-bottom:18px}
.module-toolbar h1{margin:0;font-size:22px;font-weight:600;letter-spacing:-0.01em}
.module-toolbar button{padding:7px 14px;border-radius:6px;background:var(--accent);
  color:#fff;border:none;cursor:pointer;font-size:13px;font-weight:500}
.module-toolbar button:hover{filter:brightness(1.08)}
.module-toolbar input[type=search]{flex:1;max-width:320px;padding:7px 12px;
  background:var(--panel);border:1px solid var(--border);border-radius:6px;
  color:var(--text);font-size:13px}
.module-tabs{display:flex;gap:6px;margin-bottom:14px;border-bottom:1px solid var(--border)}
.module-tabs a{padding:8px 14px;color:var(--dim);text-decoration:none;font-size:13px;
  border-bottom:2px solid transparent;margin-bottom:-1px}
.module-tabs a.tab-active,.module-tabs a:hover{color:var(--text);border-bottom-color:var(--accent)}
.data-table{width:100%;border-collapse:collapse;background:var(--panel);
  border:1px solid var(--border);border-radius:8px;overflow:hidden;font-size:13px}
.data-table th,.data-table td{padding:10px 14px;text-align:left;
  border-bottom:1px solid var(--border)}
.data-table th{background:rgba(255,255,255,0.02);color:var(--dim);
  font-weight:500;font-size:11.5px;text-transform:uppercase;letter-spacing:0.5px}
.data-table tr:last-child td{border-bottom:none}
.data-table tr:hover{background:rgba(255,255,255,0.02)}
.data-table button{padding:4px 10px;border-radius:4px;background:transparent;
  border:1px solid var(--border);color:var(--dim);cursor:pointer;font-size:12px}
.data-table button:hover{color:var(--red);border-color:var(--red)}
dialog{background:var(--panel);color:var(--text);border:1px solid var(--border);
  border-radius:10px;padding:22px;min-width:380px;max-width:560px}
dialog::backdrop{background:rgba(0,0,0,0.6)}
dialog form{display:flex;flex-direction:column;gap:10px}
dialog label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--dim)}
dialog input,dialog select,dialog textarea{padding:7px 10px;background:var(--bg);
  border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px}
dialog menu{display:flex;justify-content:flex-end;gap:8px;padding:0;margin:8px 0 0;list-style:none}
dialog button{padding:7px 14px;border-radius:6px;border:1px solid var(--border);
  background:transparent;color:var(--text);cursor:pointer;font-size:13px}
dialog button[type=submit]{background:var(--accent);border-color:var(--accent);color:#fff}
.group-row td{background:rgba(99,102,241,0.08);font-weight:600;color:var(--text)}
.empty{padding:40px;text-align:center;color:var(--dim);font-style:italic}
"""


def _module_nav(active: str) -> str:
    parts = ['<nav class="app-nav">']
    for slug, label in MODULE_NAV:
        cls = " active" if slug == active else ""
        parts.append(f'<a href="/m/{slug}" class="{cls.strip()}">{_e(label)}</a>')
    parts.append("</nav>")
    return "".join(parts)


def render_module_page(*, title: str, nav_active: str, body_html: str) -> str:
    """Return the full HTML for an HR module page.

    Used by every file in ``hrkit/modules/``. Wraps the module's
    CRUD body in a shared shell with a top nav and the white-label app name.
    """
    name = branding.app_name()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_e(title)} &middot; {_e(name)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{MODULE_CSS}</style>
</head>
<body>
<header class="app-bar">
  <div class="app-brand"><a href="/">{_e(name)}</a></div>
  {_module_nav(nav_active)}
  <div class="app-actions">
    <a href="/m/recruitment/board">Board</a>
    <a href="/chat">AI Chat</a>
    <a href="/recipes">Recipes</a>
    <a href="/integrations">Integrations</a>
    <a href="/settings">Settings</a>
  </div>
</header>
<main class="app-content">
{body_html}
</main>
</body>
</html>"""


# =============================================================================
# Shared detail-page helper (Wave 4)
# =============================================================================
# Every module's ``detail_view`` calls render_detail_page() to compose a
# consistent HTML page: heading, subtitle, field grid, action buttons, an
# optional related-records section, and an inline edit dialog backed by the
# module's existing /api/m/<name>/<id> POST endpoint.

DETAIL_CSS = r"""
.detail-head{display:flex;justify-content:space-between;align-items:flex-start;
  gap:18px;margin-bottom:22px;padding-bottom:14px;border-bottom:1px solid var(--border)}
.detail-head h1{margin:0;font-size:22px;font-weight:600;letter-spacing:-0.01em}
.detail-sub{color:var(--dim);font-size:13px;margin-top:4px}
.detail-actions{display:flex;gap:8px;align-items:center}
.detail-actions button,.detail-actions a{padding:7px 14px;border-radius:6px;
  background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:13px;
  text-decoration:none;font-family:inherit}
.detail-actions a.link-back{background:transparent;color:var(--dim);border:1px solid var(--border)}
.detail-actions a.link-back:hover{color:var(--text);border-color:var(--accent)}
.detail-actions button.danger{background:transparent;color:var(--red);border:1px solid var(--red)}
.detail-actions button.danger:hover{background:var(--red);color:#fff}
.detail-fields{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));
  gap:12px;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:18px}
.kv{display:flex;flex-direction:column;gap:4px;min-width:0}
.kv .k{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:0.5px}
.kv .v{font-size:13.5px;color:var(--text);word-break:break-word}
.detail-section{margin-top:24px;background:var(--panel);border:1px solid var(--border);
  border-radius:8px;overflow:hidden}
.detail-section .sec-head{padding:12px 16px;background:rgba(255,255,255,0.02);
  font-size:12px;font-weight:600;color:var(--dim);text-transform:uppercase;letter-spacing:0.5px;
  border-bottom:1px solid var(--border)}
.detail-section .sec-body{padding:16px}
.detail-section table{width:100%;border-collapse:collapse;font-size:13px}
.detail-section td,.detail-section th{padding:8px 10px;text-align:left;border-bottom:1px solid var(--border)}
.detail-section tr:last-child td{border-bottom:none}
"""


def render_detail_page(
    *,
    title: str,
    nav_active: str,
    subtitle: str = "",
    fields: list | None = None,
    actions_html: str = "",
    related_html: str = "",
    item_id: int | None = None,
    api_path: str = "",
    delete_redirect: str = "",
) -> str:
    """Render a consistent HTML detail page for any module record.

    Args:
      title: page heading and browser title.
      nav_active: module slug for top nav highlight.
      subtitle: optional second line under the heading.
      fields: list of ``(label, value)`` rows shown in the field grid.
              Values are HTML-escaped automatically; ``None`` becomes "".
      actions_html: ready-rendered HTML for the actions row (extra buttons).
      related_html: ready-rendered HTML for "Related records" sections.
      item_id, api_path, delete_redirect: enable the standard Edit/Delete
              flow if all three are provided. ``api_path`` is the JSON CRUD
              endpoint root (e.g. ``/api/m/employee``); ``delete_redirect``
              is where the browser goes after a successful delete.
    """
    import re as _re

    rows: list[str] = []
    for label, value in (fields or []):
        if value is None:
            value = ""
        rows.append(
            f'<div class="kv"><div class="k">{_e(label)}</div>'
            f'<div class="v">{_e(value)}</div></div>'
        )

    edit_btn = ""
    delete_btn = ""
    edit_dialog = ""
    edit_script = ""
    if item_id is not None and api_path and delete_redirect:
        edit_btn = (
            "<button onclick=\"document.getElementById('edit-dlg').showModal()\">Edit</button>"
        )
        delete_btn = (
            f"<button class=\"danger\" onclick=\"deleteRecord({int(item_id)})\">Delete</button>"
        )
        form_inputs: list[str] = []
        for label, value in (fields or []):
            slug = _re.sub(r"[^a-z0-9_]+", "_", str(label).lower()).strip("_")
            if not slug:
                continue
            form_inputs.append(
                f'<label>{_e(label)}<input name="{_e(slug)}" '
                f'value="{_e("" if value is None else value)}"></label>'
            )
        edit_dialog = f"""
<dialog id="edit-dlg">
  <form onsubmit="submitEdit(event)">
    {''.join(form_inputs)}
    <menu>
      <button type="button" onclick="this.closest('dialog').close()">Cancel</button>
      <button type="submit">Save</button>
    </menu>
  </form>
</dialog>"""
        edit_script = f"""
<script>
async function submitEdit(ev) {{
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const payload = {{}};
  for (const [k, v] of fd.entries()) if (v !== '') payload[k] = v;
  const r = await fetch('{api_path}/{int(item_id)}', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (r.ok) location.reload(); else alert('Save failed: ' + await r.text());
}}
async function deleteRecord(id) {{
  if (!confirm('Delete this record?')) return;
  const r = await fetch('{api_path}/' + id, {{method: 'DELETE'}});
  if (r.ok) location.href = '{delete_redirect}'; else alert('Delete failed');
}}
</script>"""

    body = f"""
<style>{DETAIL_CSS}</style>
<div class="detail-head">
  <div>
    <h1>{_e(title)}</h1>
    {f'<div class="detail-sub">{_e(subtitle)}</div>' if subtitle else ''}
  </div>
  <div class="detail-actions">
    {actions_html}
    {edit_btn}
    {delete_btn}
    <a href="/m/{_e(nav_active)}" class="link-back">&larr; Back</a>
  </div>
</div>
<div class="detail-fields">{''.join(rows) if rows else '<div class="empty">No fields.</div>'}</div>
{related_html}
{edit_dialog}
{edit_script}
"""
    return render_module_page(title=title, nav_active=nav_active, body_html=body)


def detail_section(*, title: str, body_html: str) -> str:
    """Render a labeled section block for use in render_detail_page's related_html."""
    return (
        f'<div class="detail-section">'
        f'<div class="sec-head">{_e(title)}</div>'
        f'<div class="sec-body">{body_html}</div></div>'
    )
