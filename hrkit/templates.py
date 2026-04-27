from __future__ import annotations
import html as htmllib
import json
from typing import Any

from .config import COLUMN_ACCENT, COLUMN_LABEL, STATUS_TO_COLUMN
from .models import Folder
from . import branding
from . import feature_flags




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
  border-radius:10px;padding:22px 26px;
  min-width:min(420px,90vw);width:min(720px,96vw);max-width:96vw;
  max-height:90vh;overflow-y:auto;position:relative;box-sizing:border-box}
dialog::backdrop{background:rgba(0,0,0,0.6)}
dialog form{display:flex;flex-direction:column;gap:10px;max-width:100%}
dialog label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--dim)}
dialog input,dialog select,dialog textarea{padding:7px 10px;background:var(--bg);
  border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;
  max-width:100%;box-sizing:border-box}
dialog textarea{resize:vertical;min-height:64px}
dialog menu{display:flex;justify-content:flex-end;gap:8px;padding:0;margin:8px 0 0;list-style:none}
dialog button{padding:7px 14px;border-radius:6px;border:1px solid var(--border);
  background:transparent;color:var(--text);cursor:pointer;font-size:13px}
dialog button[type=submit]{background:var(--accent);border-color:var(--accent);color:#fff}
.dialog-close{position:absolute;top:10px;right:12px;width:28px;height:28px;
  display:flex;align-items:center;justify-content:center;border-radius:6px;
  border:1px solid transparent;background:transparent;color:var(--dim);
  cursor:pointer;font-size:18px;line-height:1;padding:0}
.dialog-close:hover{color:var(--text);background:rgba(255,255,255,0.06);border-color:var(--border)}
.group-row td{background:rgba(99,102,241,0.08);font-weight:600;color:var(--text)}
.empty{padding:40px;text-align:center;color:var(--dim);font-style:italic}
"""


def _module_nav(active: str) -> str:
    enabled = set(feature_flags.enabled_modules())
    parts = ['<nav class="app-nav">']
    for slug, label in MODULE_NAV:
        if slug not in enabled:
            continue
        cls = " active" if slug == active else ""
        parts.append(f'<a href="/m/{slug}" class="{cls.strip()}">{_e(label)}</a>')
    parts.append("</nav>")
    return "".join(parts)


HOME_CSS = r"""
.home-hero{padding:30px 24px;border:1px solid var(--border);border-radius:10px;
  background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 14%,var(--panel)),var(--panel));
  margin-bottom:22px}
.home-hero h1{margin:0 0 6px;font-size:26px;letter-spacing:-0.02em}
.home-hero p{margin:0;color:var(--dim);font-size:14px}
.home-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}
@media (max-width:760px){.home-stats{grid-template-columns:repeat(2,1fr)}}
.home-stat{padding:18px;border:1px solid var(--border);border-radius:10px;
  background:var(--panel);text-decoration:none;color:inherit;display:block;
  transition:border-color .15s ease}
.home-stat:hover{border-color:var(--accent)}
.home-stat .v{font-size:28px;font-weight:600;letter-spacing:-0.02em;display:block}
.home-stat .k{font-size:11.5px;color:var(--dim);text-transform:uppercase;
  letter-spacing:0.5px;margin-top:4px;display:block}
.home-section-title{font-size:13px;color:var(--dim);text-transform:uppercase;
  letter-spacing:0.6px;margin:24px 0 12px;font-weight:600}
.home-quick{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.home-quick a{padding:9px 14px;border-radius:6px;background:var(--accent);color:#fff;
  text-decoration:none;font-size:13px;font-weight:500}
.home-quick a:hover{filter:brightness(1.1)}
.home-quick a.ghost{background:transparent;border:1px solid var(--border);color:var(--text)}
.home-mods{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media (max-width:900px){.home-mods{grid-template-columns:repeat(2,1fr)}}
@media (max-width:560px){.home-mods{grid-template-columns:1fr}}
.home-mod{padding:16px;border:1px solid var(--border);border-radius:10px;
  background:var(--panel);text-decoration:none;color:inherit;
  transition:border-color .15s ease,transform .15s ease;display:block}
.home-mod:hover{border-color:var(--accent);transform:translateY(-1px)}
.home-mod-head{display:flex;gap:8px;align-items:center;margin-bottom:6px}
.home-mod-label{font-weight:600;font-size:14px}
.home-mod-cat{font-size:9.5px;padding:2px 6px;border-radius:3px;text-transform:uppercase;
  letter-spacing:0.5px;background:rgba(255,255,255,0.05);color:var(--dim)}
.home-mod-cat-core{background:rgba(99,102,241,0.18);color:#a5b4fc}
.home-mod-cat-hiring{background:rgba(245,158,11,0.18);color:#fcd34d}
.home-mod-desc{font-size:12px;color:var(--dim);line-height:1.45}
.home-empty{padding:30px;text-align:center;color:var(--dim);font-style:italic;
  border:1px dashed var(--border);border-radius:10px}
.fs-panel{border:1px solid var(--border);border-radius:10px;background:var(--panel);
  padding:14px 16px;margin-top:10px}
.fs-head{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.fs-path{flex:1;min-width:0;font-family:'JetBrains Mono','Menlo',monospace;font-size:11.5px;
  color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fs-head button{padding:6px 12px;border-radius:6px;background:var(--accent);color:#fff;
  border:none;cursor:pointer;font-size:12px}
.fs-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:6px}
.fs-row{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:6px;
  background:var(--bg);border:1px solid var(--border);font-size:12.5px}
.fs-row.dir{cursor:pointer}
.fs-row.dir:hover{border-color:var(--accent)}
.fs-icon{width:18px;flex-shrink:0;text-align:center;color:var(--dim);font-size:13px}
.fs-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fs-meta{font-size:10.5px;color:var(--mute);font-family:'JetBrains Mono','Menlo',monospace}
.fs-row button.open-btn{padding:3px 9px;font-size:11px;background:transparent;
  color:var(--dim);border:1px solid var(--border);border-radius:4px;cursor:pointer}
.fs-row button.open-btn:hover{color:var(--text);border-color:var(--accent)}
"""


def render_home_page(*, root_name: str, stats: dict[str, int],
                     enabled: list[str]) -> str:
    """Render the workspace landing page using the module-page shell.

    ``stats`` is a dict of pre-aggregated counts keyed by:
        employee_count, department_count, role_count,
        pending_leave_count, open_position_count, candidate_count.
    Missing keys are treated as zero. Stat cards for disabled modules are
    skipped automatically.
    """
    enabled_set = set(enabled)
    app_name_str = branding.app_name()

    def stat(slug: str, value: int, label: str, href: str) -> str:
        if slug not in enabled_set:
            return ""
        return (
            f'<a class="home-stat" href="{href}">'
            f'<span class="v">{value}</span>'
            f'<span class="k">{_e(label)}</span></a>'
        )

    stat_cards: list[str] = []
    if "employee" in enabled_set:
        stat_cards.append(stat("employee",
                               int(stats.get("employee_count", 0)),
                               "Employees", "/m/employee"))
    if "department" in enabled_set:
        stat_cards.append(stat("department",
                               int(stats.get("department_count", 0)),
                               "Departments", "/m/department"))
    if "role" in enabled_set:
        stat_cards.append(stat("role",
                               int(stats.get("role_count", 0)),
                               "Roles", "/m/role"))
    if "leave" in enabled_set:
        stat_cards.append(stat("leave",
                               int(stats.get("pending_leave_count", 0)),
                               "Pending leave", "/m/leave"))
    if "recruitment" in enabled_set:
        stat_cards.append(stat("recruitment",
                               int(stats.get("candidate_count", 0)),
                               "Candidates", "/m/recruitment/board"))

    quick_actions: list[str] = []
    if "employee" in enabled_set:
        quick_actions.append('<a href="/m/employee">+ Add Employee</a>')
    if "department" in enabled_set:
        quick_actions.append('<a class="ghost" href="/m/department">+ Add Department</a>')
    if "employee" in enabled_set:
        quick_actions.append('<a class="ghost" href="/m/employee/tree">View Org Chart</a>')
    if "recruitment" in enabled_set:
        quick_actions.append('<a class="ghost" href="/m/recruitment/board">Hiring Board</a>')

    # Module catalog cards — one per enabled module, links into its page.
    import importlib
    mod_cards: list[str] = []
    for slug, label in MODULE_NAV:
        if slug not in enabled_set:
            continue
        try:
            mod = importlib.import_module(f"hrkit.modules.{slug}")
            md = getattr(mod, "MODULE", {}) or {}
        except Exception:
            md = {}
        category = md.get("category") or "hr"
        desc = md.get("description") or ""
        mod_cards.append(
            f'<a class="home-mod" href="/m/{slug}">'
            f'<div class="home-mod-head">'
            f'<span class="home-mod-label">{_e(label)}</span>'
            f'<span class="home-mod-cat home-mod-cat-{_e(category)}">{_e(category)}</span>'
            f'</div>'
            f'<div class="home-mod-desc">{_e(desc)}</div>'
            f'</a>'
        )

    body_html = f"""
<style>{HOME_CSS}</style>
<section class="home-hero">
  <h1>{_e(app_name_str)}</h1>
  <p>Workspace: <strong>{_e(root_name)}</strong> &middot; running locally on this machine.</p>
</section>
<div class="home-stats">
  {''.join(stat_cards) or '<div class="home-empty" style="grid-column:1/-1">No stats yet — add your first records to populate this page.</div>'}
</div>
<div class="home-section-title">Quick actions</div>
<div class="home-quick">
  {''.join(quick_actions) or '<span style="color:var(--dim);font-size:13px">No actions available.</span>'}
</div>
<div class="home-section-title">Modules</div>
<div class="home-mods">{''.join(mod_cards)}</div>

<div class="home-section-title">Workspace files</div>
<div class="fs-panel">
  <div class="fs-head">
    <span class="fs-path" id="fs-path" title="">/</span>
    <button onclick="fsOpen('')">Open in Explorer/Finder</button>
  </div>
  <div class="fs-list" id="fs-list">Loading…</div>
</div>
<script>
async function fsLoad(rel) {{
  const url = '/api/workspace/tree' + (rel ? ('?path=' + encodeURIComponent(rel)) : '');
  const list = document.getElementById('fs-list');
  list.textContent = 'Loading…';
  try {{
    const r = await fetch(url);
    const j = await r.json();
    if (!r.ok || j.ok === false) {{ list.textContent = (j.error || 'Failed'); return; }}
    document.getElementById('fs-path').textContent = j.root + (j.rel ? ('/' + j.rel) : '');
    document.getElementById('fs-path').title = document.getElementById('fs-path').textContent;
    if (!j.entries.length) {{ list.innerHTML = '<div class=\"empty\" style=\"grid-column:1/-1\">Empty folder.</div>'; return; }}
    const fmtSize = function(n) {{
      if (n < 1024) return n + ' B';
      if (n < 1024*1024) return (n/1024).toFixed(1) + ' KB';
      return (n/1024/1024).toFixed(1) + ' MB';
    }};
    const esc = function(s) {{ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {{
      return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];
    }}); }};
    const rows = [];
    if (j.rel) {{
      const parent = j.rel.split('/').slice(0, -1).join('/');
      rows.push('<div class="fs-row dir" onclick="fsLoad(\\'' + esc(parent) + '\\')">' +
                '<div class="fs-icon">↰</div>' +
                '<div class="fs-name">..</div></div>');
    }}
    j.entries.forEach(function(e) {{
      const isDir = (e.kind === 'dir');
      const icon = isDir ? '📁' : '📄';
      const meta = isDir ? '' : fmtSize(e.size);
      const click = isDir ? ('onclick="fsLoad(\\'' + esc(e.rel_path) + '\\')"') : '';
      rows.push('<div class="fs-row ' + (isDir ? 'dir' : 'file') + '" ' + click + '>' +
                '<div class="fs-icon">' + icon + '</div>' +
                '<div class="fs-name" title="' + esc(e.name) + '">' + esc(e.name) + '</div>' +
                '<span class="fs-meta">' + meta + '</span>' +
                '<button class="open-btn" onclick="event.stopPropagation();fsOpen(\\'' + esc(e.rel_path) + '\\')">Open</button>' +
                '</div>');
    }});
    list.innerHTML = rows.join('');
  }} catch (err) {{ list.textContent = 'Error: ' + err; }}
}}
async function fsOpen(rel) {{
  try {{
    await fetch('/api/workspace/open', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{path: rel}}),
    }});
  }} catch (err) {{ alert('Could not open: ' + err); }}
}}
fsLoad('');
</script>
"""
    return render_module_page(title=app_name_str, nav_active="", body_html=body_html)


def render_activity_page(activity: list[dict]) -> str:
    """Render the workspace activity feed using the module-page shell."""
    rows: list[str] = []
    for a in activity:
        when = _e(a.get("at") or "")
        action = _e(a.get("action") or "")
        actor = _e(a.get("actor") or "")
        folder = _e(a.get("folder_name") or "")
        from_v = _e(a.get("from_value") or "")
        to_v = _e(a.get("to_value") or "")
        change = ""
        if from_v or to_v:
            change = f"{from_v or '∅'} &rarr; {to_v or '∅'}"
        rows.append(
            f'<tr><td>{when}</td><td>{action}</td>'
            f'<td>{folder}</td><td>{change}</td><td>{actor}</td></tr>'
        )
    table_body = (
        "".join(rows)
        or '<tr><td colspan="5" style="text-align:center;color:var(--dim);'
           'font-style:italic;padding:30px">No activity yet.</td></tr>'
    )
    body = (
        '<div class="module-toolbar"><h1>Recent activity</h1></div>'
        '<table class="data-table">'
        '<thead><tr><th>When</th><th>Action</th><th>Record</th>'
        '<th>Change</th><th>Actor</th></tr></thead>'
        f'<tbody>{table_body}</tbody>'
        '</table>'
    )
    return render_module_page(title="Activity", nav_active="", body_html=body)


def render_module_page(*, title: str, nav_active: str, body_html: str) -> str:
    """Return the full HTML for an HR module page.

    Used by every file in ``hrkit/modules/``. Wraps the module's
    CRUD body in a shared shell with a top nav and the white-label app name.
    """
    name = branding.app_name()
    enabled = set(feature_flags.enabled_modules())
    board_link = (
        '<a href="/m/recruitment/board">Board</a>'
        if "recruitment" in enabled else ""
    )
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
    {board_link}
    <a href="/chat">AI Chat</a>
    <a href="/recipes">Recipes</a>
    <a href="/integrations">Integrations</a>
    <a href="/settings">Settings</a>
  </div>
</header>
<main class="app-content">
{body_html}
</main>
<script>
// Auto-augment every <dialog> on the page with a × close button, click-outside-
// to-close, and an Esc-to-close shortcut. Native <dialog> already supports Esc
// when shown via showModal(); this script makes sure the close UX is consistent
// across the 16+ dialogs in the app without requiring each template to opt in.
(function() {{
  function augment(dlg) {{
    if (dlg.dataset.closeReady) return;
    dlg.dataset.closeReady = '1';
    if (!dlg.querySelector('.dialog-close')) {{
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'dialog-close';
      btn.setAttribute('aria-label', 'Close');
      btn.title = 'Close (Esc)';
      btn.textContent = '×';
      btn.addEventListener('click', function() {{ dlg.close(); }});
      dlg.insertBefore(btn, dlg.firstChild);
    }}
    // Click on the backdrop (outside the dialog content) closes it.
    dlg.addEventListener('click', function(ev) {{
      if (ev.target === dlg) dlg.close();
    }});
  }}
  function scan() {{
    document.querySelectorAll('dialog').forEach(augment);
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', scan);
  }} else {{
    scan();
  }}
  // Re-scan if dialogs are injected after page load (e.g. by render_detail_page's
  // edit dialog that gets stamped into the DOM by template helpers).
  var mo = new MutationObserver(scan);
  mo.observe(document.body, {{childList: true, subtree: true}});
}})();
</script>
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
    field_options: dict[str, list[str]] | None = None,
    exclude_edit_fields: set[str] | None = None,
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
        datalists: list[str] = []
        seen_lists: set[str] = set()
        opt_map = field_options or {}
        skip = exclude_edit_fields or set()
        for label, value in (fields or []):
            slug = _re.sub(r"[^a-z0-9_]+", "_", str(label).lower()).strip("_")
            if not slug or slug in skip:
                continue
            opts = opt_map.get(slug)
            list_attr = ""
            if opts:
                list_id = f"opts-{slug}"
                list_attr = f' list="{list_id}"'
                if list_id not in seen_lists:
                    options_html = "".join(
                        f'<option value="{_e(o)}">' for o in opts
                    )
                    datalists.append(f'<datalist id="{list_id}">{options_html}</datalist>')
                    seen_lists.add(list_id)
            form_inputs.append(
                f'<label>{_e(label)}<input name="{_e(slug)}"{list_attr} '
                f'value="{_e("" if value is None else value)}"></label>'
            )
        edit_dialog = f"""
{''.join(datalists)}
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
