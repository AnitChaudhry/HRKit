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
/* Horilla-inspired light-default tokens. Dark mode is the toggle, applied via
   [data-theme="dark"] on <html>. The accent is coral (horilla's brand), kept
   identical across themes so badges and primary buttons read consistently. */
:root{
  --bg:#f5f6f8; --panel:#ffffff; --panel-alt:#fafbfc;
  --border:#e5e7eb; --border-soft:#eef0f3;
  --text:#1f2937; --dim:#6b7280; --mute:#9ca3af;
  --accent:#ef4444; --accent-soft:rgba(239,68,68,0.10); --accent-fg:#ffffff;
  --green:#10b981; --red:#ef4444; --amber:#f59e0b;
  --shadow-sm:0 1px 2px rgba(15,23,42,0.04),0 1px 3px rgba(15,23,42,0.06);
  --shadow-md:0 1px 3px rgba(15,23,42,0.05),0 4px 6px -1px rgba(15,23,42,0.05);
  --row-hover:rgba(15,23,42,0.03);
  --sidebar-w:240px; --topbar-h:56px;
}
[data-theme="dark"]{
  --bg:#0b0d12; --panel:#11141b; --panel-alt:#0e1117;
  --border:rgba(255,255,255,0.08); --border-soft:rgba(255,255,255,0.05);
  --text:#e8eaed; --dim:#9aa0a6; --mute:#6b7280;
  --accent:#ef4444; --accent-soft:rgba(239,68,68,0.18); --accent-fg:#ffffff;
  --shadow-sm:0 1px 2px rgba(0,0,0,0.4); --shadow-md:0 4px 12px rgba(0,0,0,0.5);
  --row-hover:rgba(255,255,255,0.04);
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);
  font-family:'Inter',system-ui,-apple-system,sans-serif;font-size:14px;
  -webkit-font-smoothing:antialiased}
a{color:inherit}

/* ---- Shell: sidebar + main column with topbar ---- */
.app-shell{display:flex;min-height:100vh}
.app-sidebar{width:var(--sidebar-w);background:var(--panel);
  border-right:1px solid var(--border);
  display:flex;flex-direction:column;position:sticky;top:0;height:100vh;
  overflow:hidden}
.app-sidebar-brand{padding:18px 22px;border-bottom:1px solid var(--border-soft);
  font-weight:700;font-size:15px;letter-spacing:-0.01em}
.app-sidebar-brand a{color:inherit;text-decoration:none;display:flex;
  align-items:center;gap:10px}
.app-sidebar-brand .brand-dot{width:24px;height:24px;border-radius:6px;
  background:var(--accent);color:var(--accent-fg);display:inline-flex;
  align-items:center;justify-content:center;font-size:13px;font-weight:700}
.app-sidebar-section{padding:16px 12px 6px;font-size:10.5px;color:var(--mute);
  text-transform:uppercase;letter-spacing:0.7px;font-weight:600}
.app-sidebar-nav{padding:0 8px 18px;flex:1;overflow-y:auto;scrollbar-width:thin}
.app-sidebar-nav a{display:flex;align-items:center;gap:10px;
  padding:8px 12px;border-radius:6px;color:var(--dim);text-decoration:none;
  font-size:13px;font-weight:500;line-height:1.2}
.app-sidebar-nav a:hover{color:var(--text);background:var(--row-hover)}
.app-sidebar-nav a.active{color:var(--accent);background:var(--accent-soft)}
.app-sidebar-nav a .nav-ic{width:16px;text-align:center;font-size:14px;flex-shrink:0}
.app-main{flex:1;min-width:0;display:flex;flex-direction:column}
.app-topbar{display:flex;align-items:center;gap:14px;height:var(--topbar-h);
  padding:0 24px;background:var(--panel);border-bottom:1px solid var(--border);
  position:sticky;top:0;z-index:10}
.app-topbar-title{font-size:14.5px;font-weight:600;color:var(--text);flex:1;min-width:0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.app-topbar-actions{display:flex;align-items:center;gap:6px}
.app-topbar-actions a,.app-topbar-actions button{padding:6px 12px;border-radius:6px;
  color:var(--dim);text-decoration:none;font-size:12.5px;font-weight:500;
  background:transparent;border:1px solid transparent;cursor:pointer}
.app-topbar-actions a:hover,.app-topbar-actions button:hover{color:var(--text);
  background:var(--row-hover)}
.app-topbar-actions a.cta{color:var(--accent);background:var(--accent-soft)}
.theme-toggle{width:32px;height:32px;display:inline-flex;align-items:center;
  justify-content:center;font-size:15px;border-radius:6px;color:var(--dim);
  background:transparent;border:1px solid transparent;cursor:pointer;padding:0}
.theme-toggle:hover{background:var(--row-hover);color:var(--text)}
.app-content{padding:24px 28px;max-width:1400px;margin:0 auto;width:100%}
@media (max-width:760px){
  .app-sidebar{position:fixed;left:-240px;transition:left .2s ease;z-index:20}
  .app-sidebar.open{left:0}
  .app-content{padding:18px}
}

/* ---- Module toolbar (page header inside content) ---- */
.module-toolbar{display:flex;align-items:center;gap:14px;margin-bottom:20px;
  flex-wrap:wrap}
.module-toolbar h1{margin:0;font-size:22px;font-weight:600;letter-spacing:-0.015em}
.module-toolbar .crumb{font-size:11.5px;color:var(--mute);text-transform:uppercase;
  letter-spacing:0.6px;margin-bottom:2px}
.module-toolbar button,.btn-primary{padding:7px 14px;border-radius:6px;
  background:var(--accent);color:var(--accent-fg);border:none;cursor:pointer;
  font-size:13px;font-weight:500;box-shadow:var(--shadow-sm)}
.module-toolbar button:hover,.btn-primary:hover{filter:brightness(1.05)}
.btn-ghost{padding:7px 14px;border-radius:6px;background:transparent;
  color:var(--text);border:1px solid var(--border);font-size:13px;font-weight:500;
  cursor:pointer}
.btn-ghost:hover{background:var(--row-hover);border-color:var(--dim)}
.module-toolbar input[type=search]{flex:1;max-width:340px;padding:7px 12px;
  background:var(--panel);border:1px solid var(--border);border-radius:6px;
  color:var(--text);font-size:13px}
.module-toolbar input[type=search]:focus{outline:none;border-color:var(--accent);
  box-shadow:0 0 0 3px var(--accent-soft)}

/* ---- Tabs ---- */
.module-tabs{display:flex;gap:4px;margin-bottom:18px;border-bottom:1px solid var(--border)}
.module-tabs a{padding:9px 16px;color:var(--dim);text-decoration:none;font-size:13px;
  font-weight:500;border-bottom:2px solid transparent;margin-bottom:-1px}
.module-tabs a.tab-active,.module-tabs a:hover{color:var(--accent);
  border-bottom-color:var(--accent)}

/* ---- Cards & data tables ---- */
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;
  box-shadow:var(--shadow-sm);padding:18px 20px}
.data-table{width:100%;border-collapse:separate;border-spacing:0;
  background:var(--panel);border:1px solid var(--border);border-radius:10px;
  overflow:hidden;font-size:13px;box-shadow:var(--shadow-sm)}
.data-table th,.data-table td{padding:11px 16px;text-align:left;
  border-bottom:1px solid var(--border-soft)}
.data-table th{background:var(--panel-alt);color:var(--dim);
  font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.6px}
.data-table tr:last-child td{border-bottom:none}
.data-table tr:hover td{background:var(--row-hover)}
.data-table a{color:var(--accent);text-decoration:none;font-weight:500}
.data-table a:hover{text-decoration:underline}
.data-table button{padding:4px 10px;border-radius:5px;background:transparent;
  border:1px solid var(--border);color:var(--dim);cursor:pointer;font-size:12px}
.data-table button:hover{color:var(--red);border-color:var(--red)}
.group-row td{background:var(--accent-soft);font-weight:600;color:var(--text)}

/* ---- Pills / badges ---- */
.pill{display:inline-block;padding:2px 10px;border-radius:999px;
  font-size:11.5px;font-weight:600;background:var(--accent-soft);color:var(--accent)}
.pill-mute{background:var(--row-hover);color:var(--dim)}
.pill-green{background:rgba(16,185,129,0.12);color:#047857}
[data-theme="dark"] .pill-green{color:#34d399}
.pill-amber{background:rgba(245,158,11,0.12);color:#b45309}
[data-theme="dark"] .pill-amber{color:#fbbf24}
.pill-red{background:rgba(239,68,68,0.12);color:#b91c1c}
[data-theme="dark"] .pill-red{color:#fca5a5}

/* ---- Dialogs ---- */
dialog{background:var(--panel);color:var(--text);border:1px solid var(--border);
  border-radius:12px;padding:22px 26px;
  min-width:min(420px,90vw);width:min(720px,96vw);max-width:96vw;
  max-height:90vh;overflow-y:auto;position:relative;box-sizing:border-box;
  box-shadow:var(--shadow-md)}
dialog::backdrop{background:rgba(15,23,42,0.45)}
[data-theme="dark"] dialog::backdrop{background:rgba(0,0,0,0.65)}
dialog form{display:flex;flex-direction:column;gap:12px;max-width:100%}
dialog label{display:flex;flex-direction:column;gap:4px;font-size:12px;
  color:var(--dim);font-weight:500}
dialog input,dialog select,dialog textarea{padding:8px 11px;background:var(--panel-alt);
  border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;
  max-width:100%;box-sizing:border-box;font-family:inherit}
dialog input:focus,dialog select:focus,dialog textarea:focus{outline:none;
  border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
dialog textarea{resize:vertical;min-height:64px}
dialog menu{display:flex;justify-content:flex-end;gap:8px;padding:0;margin:10px 0 0;
  list-style:none}
dialog button{padding:8px 16px;border-radius:6px;border:1px solid var(--border);
  background:transparent;color:var(--text);cursor:pointer;font-size:13px;font-weight:500}
dialog button:hover{background:var(--row-hover)}
dialog button[type=submit]{background:var(--accent);border-color:var(--accent);
  color:var(--accent-fg)}
dialog button[type=submit]:hover{filter:brightness(1.05);background:var(--accent)}

.empty{padding:40px;text-align:center;color:var(--dim);font-style:italic;
  background:var(--panel);border:1px dashed var(--border);border-radius:10px}

/* ---- Horilla archetypes: stat grid, kanban, heatmap, charts ---- */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:14px;margin-bottom:22px}
.stat-tile{padding:18px 20px;border:1px solid var(--border);border-radius:12px;
  background:var(--panel);box-shadow:var(--shadow-sm);
  display:flex;flex-direction:column;gap:6px;text-decoration:none;color:inherit;
  transition:box-shadow .15s ease,border-color .15s ease}
.stat-tile:hover{border-color:var(--accent);box-shadow:var(--shadow-md)}
.stat-tile-label{font-size:11.5px;color:var(--dim);text-transform:uppercase;
  letter-spacing:0.6px;font-weight:600}
.stat-tile-value{font-size:28px;font-weight:700;letter-spacing:-0.02em;color:var(--text)}
.stat-tile-delta{font-size:12px;color:var(--green);font-weight:500}
.stat-tile-delta.neg{color:var(--red)}
.stat-tile-icon{width:36px;height:36px;border-radius:8px;background:var(--accent-soft);
  color:var(--accent);display:inline-flex;align-items:center;justify-content:center;
  font-size:16px;font-weight:700;margin-bottom:4px}

.kanban{display:flex;gap:14px;padding:4px 2px 14px;min-height:400px;flex-wrap:wrap}
.kanban-col{flex:1 1 220px;min-width:0;background:var(--panel-alt);
  border:1px solid var(--border);border-radius:10px;
  display:flex;flex-direction:column;max-height:78vh}
@media (max-width:1100px){.kanban{flex-wrap:nowrap;overflow-x:auto}}
.kanban-col-head{padding:12px 14px;border-bottom:1px solid var(--border-soft);
  display:flex;align-items:center;gap:8px;font-weight:600;font-size:13px}
.kanban-col-head .col-count{margin-left:auto;font-size:11px;color:var(--dim);
  background:var(--row-hover);padding:2px 8px;border-radius:999px;font-weight:600}
.kanban-col-body{flex:1;overflow-y:auto;padding:10px 10px 14px;
  display:flex;flex-direction:column;gap:8px}
.kanban-card{background:var(--panel);border:1px solid var(--border);
  border-radius:8px;padding:12px 14px;font-size:13px;
  box-shadow:var(--shadow-sm);text-decoration:none;color:inherit;display:block;
  transition:transform .12s ease,box-shadow .12s ease,border-color .12s ease}
.kanban-card:hover{transform:translateY(-1px);box-shadow:var(--shadow-md);
  border-color:var(--accent)}
.kanban-card-title{font-weight:600;color:var(--text);margin-bottom:4px;
  font-size:13.5px;letter-spacing:-0.005em}
.kanban-card-sub{font-size:11.5px;color:var(--dim);line-height:1.45}
.kanban-card-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
.kanban-empty{padding:24px 12px;text-align:center;color:var(--mute);
  font-size:12px;font-style:italic}

.heatmap-wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--border);
  border-radius:12px;padding:18px;box-shadow:var(--shadow-sm)}
.heatmap-table{border-collapse:separate;border-spacing:3px;font-size:11px}
.heatmap-table th{font-weight:500;color:var(--dim);font-size:10.5px;text-align:left;
  padding:0 8px 4px 0;text-transform:uppercase;letter-spacing:0.5px}
.heatmap-table th.col{padding:0 0 4px;text-align:center;min-width:14px}
.heatmap-table td{width:14px;height:14px;border-radius:3px;background:var(--row-hover)}
.heatmap-table td.row-label{background:transparent;padding:0 8px 0 0;
  font-size:11.5px;color:var(--text);font-weight:500;width:auto;height:auto}
.heatmap-table td.lvl1{background:rgba(239,68,68,0.15)}
.heatmap-table td.lvl2{background:rgba(239,68,68,0.32)}
.heatmap-table td.lvl3{background:rgba(239,68,68,0.55)}
.heatmap-table td.lvl4{background:rgba(239,68,68,0.78)}
.heatmap-table td.lvl5{background:var(--accent)}
.heatmap-legend{display:flex;align-items:center;gap:6px;margin-top:10px;
  font-size:11px;color:var(--dim)}
.heatmap-legend .swatch{width:11px;height:11px;border-radius:2px;display:inline-block}

.chart-card{background:var(--panel);border:1px solid var(--border);border-radius:12px;
  padding:18px 20px;box-shadow:var(--shadow-sm)}
.chart-card-head{display:flex;justify-content:space-between;align-items:baseline;
  margin-bottom:14px}
.chart-card-title{font-size:13px;font-weight:600;color:var(--text)}
.chart-card-meta{font-size:11.5px;color:var(--dim)}
.chart-svg{width:100%;height:auto;display:block}
.chart-legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px;font-size:11.5px}
.chart-legend-item{display:flex;align-items:center;gap:6px;color:var(--dim)}
.chart-legend-item .dot{width:10px;height:10px;border-radius:2px;display:inline-block}
"""


# ---------------------------------------------------------------------------
# Branded dialog + toast helpers — replaces native alert / confirm / prompt
# ---------------------------------------------------------------------------
# Auto-injected into every module page by ``render_module_page``. The CSS
# uses the existing horilla theme tokens so light + dark modes both work.
BRANDED_DIALOGS_CSS = r"""
.hrkit-toast-host{position:fixed;top:18px;right:18px;display:flex;flex-direction:column;
  gap:8px;z-index:9999;pointer-events:none}
.hrkit-toast{pointer-events:auto;background:var(--panel);color:var(--text);
  border:1px solid var(--border);border-left:4px solid var(--accent);
  border-radius:10px;padding:10px 38px 10px 14px;font-size:13px;
  box-shadow:var(--shadow-md);min-width:240px;max-width:380px;position:relative;
  animation:hrkit-toast-in .18s ease-out}
.hrkit-toast.success{border-left-color:#10b981}
.hrkit-toast.error{border-left-color:#dc2626}
.hrkit-toast.info{border-left-color:var(--accent)}
.hrkit-toast .hrkit-toast-close{position:absolute;top:6px;right:6px;width:22px;
  height:22px;border:0;background:transparent;color:var(--dim);border-radius:6px;
  cursor:pointer;font-size:16px;line-height:1;display:flex;align-items:center;
  justify-content:center;padding:0}
.hrkit-toast .hrkit-toast-close:hover{background:var(--row-hover);color:var(--text)}
@keyframes hrkit-toast-in{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
@keyframes hrkit-toast-out{from{opacity:1}to{opacity:0;transform:translateY(-4px)}}

.hrkit-modal::backdrop{background:rgba(15,23,42,0.45)}
[data-theme="dark"] .hrkit-modal::backdrop{background:rgba(0,0,0,0.6)}
.hrkit-modal{border:1px solid var(--border);border-radius:14px;background:var(--panel);
  color:var(--text);box-shadow:var(--shadow-md);padding:0;min-width:340px;max-width:480px;
  font:14px/1.5 'Inter',sans-serif}
.hrkit-modal[open]{animation:hrkit-modal-in .14s ease-out}
@keyframes hrkit-modal-in{from{opacity:0;transform:translateY(-4px) scale(.98)}
  to{opacity:1;transform:none}}
.hrkit-modal-head{display:flex;align-items:center;gap:8px;padding:14px 16px 0}
.hrkit-modal-title{font-weight:600;font-size:14px;flex:1}
.hrkit-modal-close{width:28px;height:28px;border:0;background:transparent;color:var(--dim);
  border-radius:8px;cursor:pointer;font-size:18px;line-height:1;display:flex;align-items:center;
  justify-content:center;padding:0;margin:-4px -4px 0 0}
.hrkit-modal-close:hover{background:var(--row-hover);color:var(--text)}
.hrkit-modal-body{padding:8px 16px 0;color:var(--text);font-size:13.5px;line-height:1.55}
.hrkit-modal-input{width:100%;margin-top:10px;padding:8px 10px;background:var(--bg);
  color:var(--text);border:1px solid var(--border);border-radius:8px;font:inherit}
.hrkit-modal-input:focus{outline:2px solid var(--accent);outline-offset:-1px}
.hrkit-modal-actions{display:flex;justify-content:flex-end;gap:8px;padding:16px}
.hrkit-modal-btn{padding:7px 14px;border:1px solid var(--border);border-radius:8px;
  background:var(--panel);color:var(--text);cursor:pointer;font:inherit;font-size:13px}
.hrkit-modal-btn:hover{background:var(--row-hover)}
.hrkit-modal-btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.hrkit-modal-btn.primary:hover{background:color-mix(in srgb,var(--accent) 88%,#000 12%)}
.hrkit-modal-btn.danger{background:#dc2626;color:#fff;border-color:#dc2626}
.hrkit-modal-btn.danger:hover{background:#b91c1c}

/* Auto-close button injected on every <dialog> that doesn't already have one. */
.hrkit-dlg-close{position:absolute;top:8px;right:8px;width:28px;height:28px;
  border:0;background:transparent;color:var(--dim);border-radius:8px;cursor:pointer;
  font-size:18px;line-height:1;display:flex;align-items:center;justify-content:center;
  padding:0;z-index:2}
.hrkit-dlg-close:hover{background:var(--row-hover);color:var(--text)}

/* Baseline branded look for every native <dialog> on a module page that
   isn't one of our purpose-built .hrkit-modal popups. Lets the existing
   per-module dialogs (create / upload / assign / etc.) inherit the
   horilla theme without each module needing its own dialog CSS. */
dialog:not(.hrkit-modal){position:relative;border:1px solid var(--border);
  border-radius:14px;background:var(--panel);color:var(--text);
  box-shadow:var(--shadow-md);padding:18px 18px 14px;min-width:340px;
  max-width:520px;font:14px/1.55 'Inter',sans-serif}
dialog:not(.hrkit-modal)::backdrop{background:rgba(15,23,42,0.45)}
[data-theme="dark"] dialog:not(.hrkit-modal)::backdrop{background:rgba(0,0,0,0.6)}
dialog:not(.hrkit-modal)[open]{animation:hrkit-modal-in .14s ease-out}
dialog:not(.hrkit-modal) form{display:flex;flex-direction:column;gap:10px;
  margin:0;padding-top:6px}
dialog:not(.hrkit-modal) label{display:flex;flex-direction:column;gap:4px;
  font-size:12px;color:var(--dim);font-weight:500;margin:0}
dialog:not(.hrkit-modal) input[type=text],
dialog:not(.hrkit-modal) input[type=email],
dialog:not(.hrkit-modal) input[type=tel],
dialog:not(.hrkit-modal) input[type=number],
dialog:not(.hrkit-modal) input[type=date],
dialog:not(.hrkit-modal) input[type=time],
dialog:not(.hrkit-modal) input[type=datetime-local],
dialog:not(.hrkit-modal) input[type=month],
dialog:not(.hrkit-modal) input[type=password],
dialog:not(.hrkit-modal) input[type=search],
dialog:not(.hrkit-modal) input[type=url],
dialog:not(.hrkit-modal) input:not([type]),
dialog:not(.hrkit-modal) select,
dialog:not(.hrkit-modal) textarea{padding:8px 10px;background:var(--bg);
  color:var(--text);border:1px solid var(--border);border-radius:8px;
  font:13.5px 'Inter',sans-serif;width:100%}
dialog:not(.hrkit-modal) input:focus,
dialog:not(.hrkit-modal) select:focus,
dialog:not(.hrkit-modal) textarea:focus{outline:2px solid var(--accent);
  outline-offset:-1px;border-color:var(--accent)}
dialog:not(.hrkit-modal) textarea{min-height:64px;resize:vertical;font-family:inherit}
dialog:not(.hrkit-modal) input[type=checkbox],
dialog:not(.hrkit-modal) input[type=radio]{width:auto;accent-color:var(--accent)}
dialog:not(.hrkit-modal) menu{display:flex;justify-content:flex-end;gap:8px;
  padding:6px 0 0;margin:6px 0 0;border:0}
dialog:not(.hrkit-modal) button,
dialog:not(.hrkit-modal) menu button{padding:7px 14px;border:1px solid var(--border);
  border-radius:8px;background:var(--panel);color:var(--text);cursor:pointer;
  font:13px 'Inter',sans-serif}
dialog:not(.hrkit-modal) button:hover{background:var(--row-hover)}
dialog:not(.hrkit-modal) button[type=submit]{background:var(--accent);
  color:#fff;border-color:var(--accent);font-weight:500}
dialog:not(.hrkit-modal) button[type=submit]:hover{
  background:color-mix(in srgb,var(--accent) 88%,#000 12%)}
"""

BRANDED_DIALOGS_JS = r"""
(function() {
  'use strict';
  if (window.hrkit && window.hrkit.__init) return;
  const ns = (window.hrkit = window.hrkit || {});

  // --- toast() ------------------------------------------------------------
  let host = null;
  function getHost() {
    if (host && document.body.contains(host)) return host;
    host = document.createElement('div');
    host.className = 'hrkit-toast-host';
    document.body.appendChild(host);
    return host;
  }
  ns.toast = function(message, type) {
    const t = document.createElement('div');
    t.className = 'hrkit-toast ' + (type === 'success' || type === 'error' || type === 'info' ? type : 'info');
    t.textContent = String(message == null ? '' : message);
    const close = document.createElement('button');
    close.className = 'hrkit-toast-close';
    close.type = 'button';
    close.setAttribute('aria-label', 'Dismiss');
    close.textContent = '×';
    close.addEventListener('click', () => dismiss(t));
    t.appendChild(close);
    getHost().appendChild(t);
    const ttl = (type === 'error' ? 6500 : 3500);
    setTimeout(() => dismiss(t), ttl);
  };
  function dismiss(el) {
    if (!el || !el.parentNode) return;
    el.style.animation = 'hrkit-toast-out .18s ease-out forwards';
    setTimeout(() => el.parentNode && el.parentNode.removeChild(el), 200);
  }

  // --- confirmDialog / promptDialog --------------------------------------
  function buildModal(opts) {
    const dlg = document.createElement('dialog');
    dlg.className = 'hrkit-modal';
    const titleText = opts.title || (opts.kind === 'prompt' ? 'Input required' : 'Are you sure?');
    const okLabel = opts.okLabel || (opts.kind === 'prompt' ? 'Submit' : 'Confirm');
    const cancelLabel = opts.cancelLabel || 'Cancel';
    const okClass = opts.danger ? 'danger' : 'primary';
    const inputHtml = opts.kind === 'prompt'
      ? '<input class="hrkit-modal-input" id="hrkit-modal-input" autocomplete="off">'
      : '';
    dlg.innerHTML = (
      '<form method="dialog">'
      + '<div class="hrkit-modal-head">'
      + '<div class="hrkit-modal-title">' + escapeHtml(titleText) + '</div>'
      + '<button type="button" class="hrkit-modal-close" aria-label="Close">×</button>'
      + '</div>'
      + '<div class="hrkit-modal-body">' + escapeHtml(opts.message || '') + inputHtml + '</div>'
      + '<div class="hrkit-modal-actions">'
      + '<button type="button" class="hrkit-modal-btn" data-act="cancel">' + escapeHtml(cancelLabel) + '</button>'
      + '<button type="submit" class="hrkit-modal-btn ' + okClass + '" data-act="ok">' + escapeHtml(okLabel) + '</button>'
      + '</div>'
      + '</form>'
    );
    return dlg;
  }
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":"&#39;"})[c];
    });
  }
  function showModal(opts) {
    return new Promise(function(resolve) {
      const dlg = buildModal(opts || {});
      document.body.appendChild(dlg);
      const input = dlg.querySelector('#hrkit-modal-input');
      if (input && opts.defaultValue != null) input.value = String(opts.defaultValue);
      let resolved = false;
      function done(value) {
        if (resolved) return;
        resolved = true;
        try { dlg.close(); } catch (e) {}
        if (dlg.parentNode) dlg.parentNode.removeChild(dlg);
        resolve(value);
      }
      dlg.querySelector('.hrkit-modal-close').addEventListener('click', () =>
        done(opts.kind === 'prompt' ? null : false));
      dlg.querySelector('[data-act="cancel"]').addEventListener('click', () =>
        done(opts.kind === 'prompt' ? null : false));
      dlg.querySelector('form').addEventListener('submit', (ev) => {
        ev.preventDefault();
        if (opts.kind === 'prompt') done(input ? input.value : '');
        else done(true);
      });
      // Click outside modal closes (Cancel).
      dlg.addEventListener('click', (ev) => {
        const r = dlg.getBoundingClientRect();
        const inside = ev.clientX >= r.left && ev.clientX <= r.right
          && ev.clientY >= r.top && ev.clientY <= r.bottom;
        if (!inside) done(opts.kind === 'prompt' ? null : false);
      });
      dlg.addEventListener('cancel', (ev) => {
        ev.preventDefault();
        done(opts.kind === 'prompt' ? null : false);
      });
      try { dlg.showModal(); } catch (e) { dlg.setAttribute('open', ''); }
      if (input) setTimeout(() => input.focus(), 30);
    });
  }
  ns.confirmDialog = function(message, opts) {
    opts = opts || {};
    return showModal({
      kind: 'confirm', message: message,
      title: opts.title, okLabel: opts.okLabel, cancelLabel: opts.cancelLabel,
      danger: !!opts.danger,
    });
  };
  ns.promptDialog = function(message, defaultValue, opts) {
    opts = opts || {};
    return showModal({
      kind: 'prompt', message: message, defaultValue: defaultValue,
      title: opts.title, okLabel: opts.okLabel, cancelLabel: opts.cancelLabel,
    });
  };

  // --- × close + click-outside on every existing <dialog> ----------------
  function ensureCloseAffordance(dlg) {
    if (!dlg || dlg.classList.contains('hrkit-modal')) return; // already branded
    if (dlg.dataset.hrkitWired === '1') return;
    dlg.dataset.hrkitWired = '1';
    if (!dlg.querySelector('.hrkit-dlg-close')) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'hrkit-dlg-close';
      btn.setAttribute('aria-label', 'Close');
      btn.textContent = '×';
      btn.addEventListener('click', () => { try { dlg.close(); } catch (e) {} });
      dlg.appendChild(btn);
    }
    dlg.addEventListener('click', (ev) => {
      if (ev.target !== dlg) return; // only the backdrop
      try { dlg.close(); } catch (e) {}
    });
  }
  function wireAllDialogs(root) {
    (root || document).querySelectorAll('dialog').forEach(ensureCloseAffordance);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => wireAllDialogs());
  } else {
    wireAllDialogs();
  }
  // Wire any future dialogs created dynamically.
  const mo = new MutationObserver((muts) => {
    for (const m of muts) {
      m.addedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        if (n.tagName === 'DIALOG') ensureCloseAffordance(n);
        else if (n.querySelectorAll) wireAllDialogs(n);
      });
    }
  });
  mo.observe(document.body || document.documentElement, {childList: true, subtree: true});

  ns.__init = true;
})();
"""


def _module_nav(active: str) -> str:
    """Render the sidebar nav with module links grouped by category."""
    enabled = set(feature_flags.enabled_modules())
    # Map each slug to a single-glyph icon. Keep ASCII-safe for cp1252 consoles.
    ICONS = {
        "department": "#", "employee": "@", "role": "*",
        "document": "D", "leave": "L", "attendance": "A",
        "payroll": "$", "performance": "%", "onboarding": "O",
        "exit_record": "X", "recruitment": "R",
    }
    parts = ['<nav class="app-sidebar-nav">']
    parts.append('<div class="app-sidebar-section">Workspace</div>')
    parts.append('<a href="/" class="' + ('active' if active == 'home' else '') + '">'
                 '<span class="nav-ic">~</span>Home</a>')
    parts.append('<div class="app-sidebar-section">HR Modules</div>')
    for slug, label in MODULE_NAV:
        if slug not in enabled:
            continue
        cls = "active" if slug == active else ""
        ic = ICONS.get(slug, "-")
        parts.append(
            f'<a href="/m/{slug}" class="{cls}">'
            f'<span class="nav-ic">{ic}</span>{_e(label)}</a>'
        )
    parts.append('<div class="app-sidebar-section">Tools</div>')
    parts.append('<a href="/chat"><span class="nav-ic">+</span>AI Chat</a>')
    parts.append('<a href="/recipes"><span class="nav-ic">/</span>Recipes</a>')
    parts.append('<a href="/integrations"><span class="nav-ic">o</span>Integrations</a>')
    parts.append('<a href="/settings"><span class="nav-ic">.</span>Settings</a>')
    parts.append("</nav>")
    return "".join(parts)


HOME_CSS = r"""
.home-hero{padding:28px 26px;border:1px solid var(--border);border-radius:12px;
  background:linear-gradient(135deg,var(--accent-soft),var(--panel));
  margin-bottom:24px;box-shadow:var(--shadow-sm)}
.home-hero h1{margin:0 0 6px;font-size:26px;letter-spacing:-0.02em;font-weight:700}
.home-hero p{margin:0;color:var(--dim);font-size:14px}
.home-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}
@media (max-width:760px){.home-stats{grid-template-columns:repeat(2,1fr)}}
.home-stat{padding:18px 20px;border:1px solid var(--border);border-radius:12px;
  background:var(--panel);text-decoration:none;color:inherit;display:block;
  box-shadow:var(--shadow-sm);transition:box-shadow .15s ease,border-color .15s ease}
.home-stat:hover{border-color:var(--accent);box-shadow:var(--shadow-md)}
.home-stat .v{font-size:28px;font-weight:700;letter-spacing:-0.02em;display:block;
  color:var(--text)}
.home-stat .k{font-size:11.5px;color:var(--dim);text-transform:uppercase;
  letter-spacing:0.6px;margin-top:4px;display:block;font-weight:600}
.home-section-title{font-size:11.5px;color:var(--mute);text-transform:uppercase;
  letter-spacing:0.7px;margin:24px 0 12px;font-weight:600}
.home-quick{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.home-quick a{padding:9px 14px;border-radius:7px;background:var(--accent);
  color:var(--accent-fg);text-decoration:none;font-size:13px;font-weight:500;
  box-shadow:var(--shadow-sm)}
.home-quick a:hover{filter:brightness(1.05)}
.home-quick a.ghost{background:var(--panel);border:1px solid var(--border);
  color:var(--text);box-shadow:none}
.home-quick a.ghost:hover{background:var(--row-hover);border-color:var(--dim)}
.home-mods{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media (max-width:900px){.home-mods{grid-template-columns:repeat(2,1fr)}}
@media (max-width:560px){.home-mods{grid-template-columns:1fr}}
.home-mod{padding:18px;border:1px solid var(--border);border-radius:12px;
  background:var(--panel);text-decoration:none;color:inherit;
  box-shadow:var(--shadow-sm);
  transition:border-color .15s ease,box-shadow .15s ease,transform .15s ease;
  display:block}
.home-mod:hover{border-color:var(--accent);box-shadow:var(--shadow-md);
  transform:translateY(-1px)}
.home-mod-head{display:flex;gap:8px;align-items:center;margin-bottom:6px}
.home-mod-label{font-weight:600;font-size:14px;color:var(--text)}
.home-mod-cat{font-size:9.5px;padding:2px 8px;border-radius:999px;text-transform:uppercase;
  letter-spacing:0.6px;font-weight:600;background:var(--row-hover);color:var(--dim)}
.home-mod-cat-core{background:var(--accent-soft);color:var(--accent)}
.home-mod-cat-hiring{background:rgba(245,158,11,0.14);color:#b45309}
[data-theme="dark"] .home-mod-cat-hiring{color:#fcd34d}
.home-mod-desc{font-size:12px;color:var(--dim);line-height:1.5}
.home-empty{padding:30px;text-align:center;color:var(--dim);font-style:italic;
  border:1px dashed var(--border);border-radius:12px;background:var(--panel)}
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


def render_home_page(*, root_name: str, stats: dict[str, Any],
                     enabled: list[str]) -> str:
    """Render the workspace landing page using the module-page shell.

    ``stats`` is a dict of pre-aggregated values keyed by:
        employee_count, on_leave_count, exited_count,
        department_count, role_count,
        pending_leave_count, open_position_count, candidate_count,
        hires_by_month (list of {label, value} dicts for the last 6 months).
    Missing keys are treated as zero / empty. Stat tiles for disabled
    modules are skipped automatically.
    """
    enabled_set = set(enabled)
    app_name_str = branding.app_name()

    # Build the KPI tiles via render_stat_grid. Each tile is one
    # {label, value, href} dict — the archetype handles markup + theming.
    stat_specs: list[dict[str, Any]] = []
    if "employee" in enabled_set:
        stat_specs.append({
            "label": "Employees",
            "value": int(stats.get("employee_count", 0)),
            "href": "/m/employee",
        })
    if "department" in enabled_set:
        stat_specs.append({
            "label": "Departments",
            "value": int(stats.get("department_count", 0)),
            "href": "/m/department",
        })
    if "role" in enabled_set:
        stat_specs.append({
            "label": "Roles",
            "value": int(stats.get("role_count", 0)),
            "href": "/m/role",
        })
    if "leave" in enabled_set:
        stat_specs.append({
            "label": "Pending leave",
            "value": int(stats.get("pending_leave_count", 0)),
            "href": "/m/leave",
        })
    if "recruitment" in enabled_set:
        stat_specs.append({
            "label": "Candidates",
            "value": int(stats.get("candidate_count", 0)),
            "href": "/m/recruitment/board",
        })
    stat_grid_html = render_stat_grid(stat_specs)

    # Workforce status donut + hires-by-month bar — only if employee module
    # is enabled, since both come off the employee table.
    workforce_html = ""
    if "employee" in enabled_set:
        donut_slices = [
            {"label": "Active",
             "value": int(stats.get("employee_count", 0)),
             "color": "var(--accent)"},
            {"label": "On leave",
             "value": int(stats.get("on_leave_count", 0)),
             "color": "#f59e0b"},
            {"label": "Exited",
             "value": int(stats.get("exited_count", 0)),
             "color": "#6b7280"},
        ]
        donut = render_donut_svg(donut_slices, size=180, thickness=24,
                                  title="Workforce status",
                                  center_label="employees")
        bars = stats.get("hires_by_month") or []
        bar = render_bar_svg(bars, height=160,
                             title="Hires per month — last 6 months")
        workforce_html = (
            '<div class="home-charts">'
            f'<div class="home-chart-cell">{donut}</div>'
            f'<div class="home-chart-cell">{bar}</div>'
            '</div>'
        )

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
<style>
  /* Two-column charts row for the home page; collapses on narrow screens. */
  .home-charts{{display:grid;grid-template-columns:minmax(240px,1fr) 2fr;
    gap:14px;margin:14px 0 6px}}
  .home-chart-cell{{min-width:0}}
  @media (max-width: 720px){{.home-charts{{grid-template-columns:1fr}}}}
</style>
<section class="home-hero">
  <h1>{_e(app_name_str)}</h1>
  <p>Workspace: <strong>{_e(root_name)}</strong> &middot; running locally on this machine.</p>
</section>
{stat_grid_html or '<div class="home-empty">No stats yet — add your first records to populate this page.</div>'}
{workforce_html}
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
  }} catch (err) {{ hrkit.toast('Could not open: ' + err, 'error'); }}
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


_NON_EXPORTABLE_NAV = frozenset({
    "csv_import", "csv_export", "audit_log", "approval", "f_and_f",
})


def _export_csv_button(nav_active: str, enabled: set[str]) -> str:
    """Render an "Export CSV" link in the topbar of any module page that's
    backed by a regular ``list_rows`` table. Skipped for utility / read-only
    modules where the export wouldn't make sense (csv_import / audit_log /
    approval / f_and_f), and for modules the workspace has disabled."""
    if (nav_active in _NON_EXPORTABLE_NAV
            or "csv_export" not in enabled
            or nav_active not in enabled):
        return ""
    return (
        f'<a class="ghost" href="/api/m/csv_export/{nav_active}.csv" '
        f'title="Download this module\'s data as CSV" '
        f'style="padding:6px 12px;border:1px solid var(--border);'
        f'border-radius:6px;color:var(--dim);text-decoration:none;'
        f'font-size:12px">Export CSV</a>'
    )


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
    initial = (name[:1] or "H").upper()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_e(title)} &middot; {_e(name)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{MODULE_CSS}</style>
<style>{BRANDED_DIALOGS_CSS}</style>
<script>
  // Apply persisted theme before paint to avoid flash. Light is the default.
  (function() {{
    try {{
      var t = localStorage.getItem('hrkit-theme');
      if (t === 'dark' || t === 'light') {{
        document.documentElement.setAttribute('data-theme', t);
      }}
    }} catch (e) {{}}
  }})();
</script>
<script>{BRANDED_DIALOGS_JS}</script>
</head>
<body>
<div class="app-shell">
<aside class="app-sidebar">
  <div class="app-sidebar-brand">
    <a href="/"><span class="brand-dot">{_e(initial)}</span>{_e(name)}</a>
  </div>
  {_module_nav(nav_active)}
</aside>
<div class="app-main">
  <header class="app-topbar">
    <div class="app-topbar-title">{_e(title)}</div>
    <div class="app-topbar-actions">
      {board_link}
      {_export_csv_button(nav_active, enabled)}
      <button type="button" class="theme-toggle" id="hrkit-theme-toggle"
              aria-label="Toggle theme" title="Toggle light/dark">o</button>
    </div>
  </header>
  <main class="app-content">
{body_html}
  </main>
</div>
</div>
<script>
  (function() {{
    var btn = document.getElementById('hrkit-theme-toggle');
    if (!btn) return;
    function current() {{
      return document.documentElement.getAttribute('data-theme') || 'light';
    }}
    function setTheme(t) {{
      document.documentElement.setAttribute('data-theme', t);
      try {{ localStorage.setItem('hrkit-theme', t); }} catch (e) {{}}
      btn.textContent = t === 'dark' ? '*' : 'o';
    }}
    btn.textContent = current() === 'dark' ? '*' : 'o';
    btn.addEventListener('click', function() {{
      setTheme(current() === 'dark' ? 'light' : 'dark');
    }});
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
  if (r.ok) location.reload(); else hrkit.toast('Save failed: ' + await r.text(), 'error');
}}
async function deleteRecord(id) {{
  if (!(await hrkit.confirmDialog('Delete this record?'))) return;
  const r = await fetch('{api_path}/' + id, {{method: 'DELETE'}});
  if (r.ok) location.href = '{delete_redirect}'; else hrkit.toast('Delete failed', 'error');
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


# =============================================================================
# Horilla-style page archetypes (Phase 4b)
# =============================================================================
# Reusable Python helpers that emit horilla-equivalent visual primitives:
# stat-tile grid (dashboard), kanban board (recruitment / helpdesk),
# calendar heatmap (attendance), and inline-SVG donut + bar charts.
#
# All helpers return self-contained HTML using the classes defined in
# MODULE_CSS, so they Just Work on any module page that goes through
# render_module_page. No external chart library, no build step.

def render_stat_grid(stats):
    """Render a grid of stat tiles. ``stats`` is a list of dicts with keys
    ``label``, ``value``, optional ``href`` / ``icon`` / ``delta`` /
    ``delta_dir`` ('up' or 'down')."""
    if not stats:
        return ""
    tiles: list[str] = []
    for s in stats:
        label = _e(s.get("label") or "")
        value = _e(str(s.get("value") if s.get("value") is not None else "0"))
        href = s.get("href") or ""
        icon = s.get("icon") or ""
        delta = s.get("delta") or ""
        ddir = (s.get("delta_dir") or "").lower()
        delta_cls = " neg" if ddir == "down" else ""
        delta_html = (
            f'<div class="stat-tile-delta{delta_cls}">{_e(delta)}</div>'
            if delta else ""
        )
        icon_html = (
            f'<div class="stat-tile-icon">{_e(icon)}</div>' if icon else ""
        )
        tag = "a" if href else "div"
        attr = f' href="{_e(href)}"' if href else ""
        tiles.append(
            f'<{tag} class="stat-tile"{attr}>'
            f'{icon_html}'
            f'<div class="stat-tile-label">{label}</div>'
            f'<div class="stat-tile-value">{value}</div>'
            f'{delta_html}'
            f'</{tag}>'
        )
    return f'<div class="stat-grid">{"".join(tiles)}</div>'


def render_kanban_board(*, columns, items, get_column,
                        render_card=None, get_id=None):
    """Render a horizontal kanban with one column per ``columns`` entry.

    Args:
      columns: list of (slug, label) tuples — column order, left to right.
      items: iterable of dicts (or any object the callbacks accept).
      get_column: callable(item) -> column slug. Items whose slug isn't in
        ``columns`` go into a synthetic 'Other' column at the right.
      render_card: callable(item) -> HTML for the card body. Defaults to a
        simple title/subtitle layout reading item['title'] / item['subtitle'].
      get_id: callable(item) -> stable id for the card data attribute.
    """
    cols_by_slug: dict[str, list] = {slug: [] for slug, _label in columns}
    other: list = []
    for it in items:
        slug = get_column(it)
        if slug in cols_by_slug:
            cols_by_slug[slug].append(it)
        else:
            other.append(it)

    def _default_card(it):
        title = _e(str(it.get("title", "")))
        sub = _e(str(it.get("subtitle", "")))
        sub_html = f'<div class="kanban-card-sub">{sub}</div>' if sub else ""
        return f'<div class="kanban-card-title">{title}</div>{sub_html}'

    rc = render_card or _default_card

    def _render_col(slug, label, bucket):
        if not bucket:
            cards = '<div class="kanban-empty">- empty -</div>'
        else:
            parts: list[str] = []
            for it in bucket:
                cid = get_id(it) if get_id else ""
                attrs = (f' data-id="{_e(str(cid))}" data-col="{_e(slug)}"'
                         if cid else f' data-col="{_e(slug)}"')
                parts.append(
                    f'<div class="kanban-card"{attrs}>{rc(it)}</div>'
                )
            cards = "".join(parts)
        return (
            f'<div class="kanban-col" data-col="{_e(slug)}">'
            f'<div class="kanban-col-head">{_e(label)}'
            f'<span class="col-count">{len(bucket)}</span></div>'
            f'<div class="kanban-col-body">{cards}</div>'
            f'</div>'
        )

    parts = [_render_col(slug, label, cols_by_slug[slug])
             for slug, label in columns]
    if other:
        parts.append(_render_col("__other__", "Other", other))
    return f'<div class="kanban">{"".join(parts)}</div>'


def render_heatmap(*, row_labels, col_labels, values, max_value=None,
                   row_label_header="", legend_label="activity"):
    """Render an N x M heatmap (e.g. employees x days for attendance).

    Args:
      row_labels: list of N strings (row headers).
      col_labels: list of M strings (column headers, e.g. day numbers).
      values: 2D iterable [N][M] of numbers.
      max_value: clamp ceiling. None -> use observed max.
      row_label_header: text for the top-left corner cell.
      legend_label: noun for cell tooltips ('hours', 'present', etc.).
    """
    rows = list(row_labels or [])
    cols = list(col_labels or [])
    grid = [list(r or []) for r in (values or [])]
    flat = [v for r in grid for v in r if isinstance(v, (int, float))]
    observed_max = max(flat) if flat else 0
    ceiling = max_value if max_value is not None else observed_max
    if ceiling <= 0:
        ceiling = 1

    def _level(v):
        if not isinstance(v, (int, float)) or v <= 0:
            return 0
        ratio = min(1.0, v / float(ceiling))
        if ratio < 0.25:
            return 1
        if ratio < 0.5:
            return 2
        if ratio < 0.75:
            return 3
        if ratio < 1.0:
            return 4
        return 5

    head_cells = "".join(
        f'<th class="col">{_e(str(c))}</th>' for c in cols
    )
    body_rows: list[str] = []
    for i, label in enumerate(rows):
        row_vals = grid[i] if i < len(grid) else []
        cells: list[str] = []
        for j, _c in enumerate(cols):
            v = row_vals[j] if j < len(row_vals) else 0
            lvl = _level(v)
            cls = f"lvl{lvl}" if lvl > 0 else ""
            tip = (f'{label}: {v} {legend_label}'
                   if isinstance(v, (int, float)) else str(label))
            cells.append(f'<td class="{cls}" title="{_e(tip)}"></td>')
        body_rows.append(
            f'<tr><td class="row-label">{_e(str(label))}</td>'
            f'{"".join(cells)}</tr>'
        )

    legend = (
        '<div class="heatmap-legend">'
        '<span>Less</span>'
        '<span class="swatch" style="background:var(--row-hover)"></span>'
        '<span class="swatch" style="background:rgba(239,68,68,0.15)"></span>'
        '<span class="swatch" style="background:rgba(239,68,68,0.32)"></span>'
        '<span class="swatch" style="background:rgba(239,68,68,0.55)"></span>'
        '<span class="swatch" style="background:rgba(239,68,68,0.78)"></span>'
        '<span class="swatch" style="background:var(--accent)"></span>'
        '<span>More</span>'
        '</div>'
    )

    return (
        '<div class="heatmap-wrap">'
        '<table class="heatmap-table">'
        f'<thead><tr><th>{_e(row_label_header)}</th>{head_cells}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        '</table>'
        f'{legend}'
        '</div>'
    )


def render_donut_svg(slices, *, size=160, thickness=22, title="", center_label=""):
    """Render a donut chart as inline SVG. ``slices`` is a list of dicts::

        {"label": str, "value": float, "color": str (optional)}
    """
    import math as _math
    slices = [s for s in (slices or []) if (s.get("value") or 0) > 0]
    total = sum(float(s["value"]) for s in slices)
    palette = ["var(--accent)", "#10b981", "#f59e0b", "#3b82f6", "#a855f7",
               "#06b6d4", "#ec4899", "#84cc16"]
    radius = size / 2
    inner = radius - thickness
    cx = cy = radius

    if total <= 0:
        body = (
            f'<svg class="chart-svg" viewBox="0 0 {size} {size}" '
            f'style="max-width:{size}px;margin:0 auto">'
            f'<circle cx="{cx}" cy="{cy}" r="{inner + thickness/2:.2f}" '
            f'fill="none" stroke="var(--row-hover)" stroke-width="{thickness}"/>'
            f'</svg>'
            '<div class="chart-card-meta" style="text-align:center;margin-top:6px">'
            'No data yet</div>'
        )
    else:
        offset = -_math.pi / 2  # start at 12 o'clock
        paths: list[str] = []
        legend_items: list[str] = []
        for i, s in enumerate(slices):
            value = float(s["value"])
            color = s.get("color") or palette[i % len(palette)]
            angle = (value / total) * 2 * _math.pi
            end = offset + angle
            r_mid = inner + thickness / 2
            x1 = cx + r_mid * _math.cos(offset)
            y1 = cy + r_mid * _math.sin(offset)
            x2 = cx + r_mid * _math.cos(end)
            y2 = cy + r_mid * _math.sin(end)
            large_arc = 1 if angle > _math.pi else 0
            d = (f'M {x1:.2f} {y1:.2f} '
                 f'A {r_mid:.2f} {r_mid:.2f} 0 '
                 f'{large_arc} 1 {x2:.2f} {y2:.2f}')
            paths.append(
                f'<path d="{d}" fill="none" stroke="{color}" '
                f'stroke-width="{thickness}" stroke-linecap="butt"/>'
            )
            pct = (value / total) * 100
            legend_items.append(
                f'<span class="chart-legend-item">'
                f'<span class="dot" style="background:{color}"></span>'
                f'{_e(s.get("label") or "")} '
                f'<strong style="color:var(--text)">{pct:.0f}%</strong>'
                f'</span>'
            )
            offset = end
        center = (
            f'<text x="{cx}" y="{cy - 3}" text-anchor="middle" '
            f'style="font:600 18px Inter,sans-serif;fill:var(--text)">{int(total)}</text>'
            f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" '
            f'style="font:11px Inter,sans-serif;fill:var(--dim);'
            f'text-transform:uppercase;letter-spacing:0.5px">{_e(center_label)}</text>'
            if center_label else
            f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" '
            f'style="font:600 20px Inter,sans-serif;fill:var(--text)">{int(total)}</text>'
        )
        body = (
            f'<svg class="chart-svg" viewBox="0 0 {size} {size}" '
            f'style="max-width:{size}px;margin:0 auto">'
            f'{"".join(paths)}'
            f'{center}'
            f'</svg>'
            f'<div class="chart-legend">{"".join(legend_items)}</div>'
        )

    head = (
        f'<div class="chart-card-head">'
        f'<span class="chart-card-title">{_e(title)}</span></div>'
        if title else ""
    )
    return f'<div class="chart-card">{head}{body}</div>'


def render_bar_svg(bars, *, height=160, title="", y_label=""):
    """Render a vertical bar chart as inline SVG. ``bars`` is a list of dicts::

        {"label": str, "value": float, "color": str (optional)}
    """
    bars = list(bars or [])
    if not bars:
        return (
            '<div class="chart-card">'
            f'<div class="chart-card-head">'
            f'<span class="chart-card-title">{_e(title)}</span></div>'
            '<div class="chart-card-meta" style="text-align:center;padding:30px 0">'
            'No data yet</div></div>'
        )
    max_v = max(float(b.get("value") or 0) for b in bars) or 1.0
    bar_w = 28
    gap = 14
    pad_l, pad_r, pad_t, pad_b = 36, 16, 12, 30
    w = pad_l + len(bars) * (bar_w + gap) - gap + pad_r
    h = height + pad_t + pad_b

    rects: list[str] = []
    labels: list[str] = []
    palette = ["var(--accent)", "#10b981", "#f59e0b", "#3b82f6", "#a855f7"]
    grid: list[str] = []
    for frac, txt in ((0.0, "0"), (0.5, f"{int(max_v / 2)}"), (1.0, f"{int(max_v)}")):
        y = pad_t + height - (frac * height)
        grid.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
            f'stroke="var(--border-soft)" stroke-width="1"/>'
            f'<text x="{pad_l - 6}" y="{y + 3:.1f}" text-anchor="end" '
            f'style="font:10px Inter,sans-serif;fill:var(--mute)">{_e(txt)}</text>'
        )
    for i, b in enumerate(bars):
        v = float(b.get("value") or 0)
        bh = (v / max_v) * height
        x = pad_l + i * (bar_w + gap)
        y = pad_t + height - bh
        color = b.get("color") or palette[i % len(palette)]
        rects.append(
            f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{bh:.1f}" '
            f'rx="4" fill="{color}">'
            f'<title>{_e(str(b.get("label") or ""))}: {v:g}</title></rect>'
        )
        labels.append(
            f'<text x="{x + bar_w / 2}" y="{pad_t + height + 18}" '
            f'text-anchor="middle" style="font:11px Inter,sans-serif;fill:var(--dim)">'
            f'{_e(str(b.get("label") or ""))}</text>'
        )

    head = (
        f'<div class="chart-card-head">'
        f'<span class="chart-card-title">{_e(title)}</span>'
        f'<span class="chart-card-meta">{_e(y_label)}</span></div>'
    )
    return (
        '<div class="chart-card">'
        f'{head}'
        f'<svg class="chart-svg" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="xMidYMid meet">'
        f'{"".join(grid)}{"".join(rects)}{"".join(labels)}'
        '</svg>'
        '</div>'
    )
