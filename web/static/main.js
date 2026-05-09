/* =========================================================
   Blackboard Novel Pipeline — demo UI
   Vanilla JS. No bundler, no framework. Fetch + DOM.
   ========================================================= */

'use strict';

const AGENT_COLORS = {
  planner:         '#5aa7ff',
  generator:       '#62d97a',
  evaluator:       '#f85149',
  fixer:           '#ffb454',
  summarizer:      '#9aa5b5',
  ai_slop_guard:   '#b78dff',
  character_guard: '#3dd5c8',
};
const AGENT_LABEL = {
  planner: 'PLANNER',
  generator: 'GENERATOR',
  evaluator: 'EVALUATOR',
  fixer: 'FIXER',
  summarizer: 'SUMMARIZER',
  ai_slop_guard: 'AI-SLOP GUARD',
  character_guard: 'CHARACTER GUARD',
};

const state = {
  snapshot: null,          // /api/state last response
  status: { running: false },
  chapters: [],            // outline chapter meta
  prompts: [],             // /api/prompts latest snapshot
  openFile: null,          // currently-viewed file path
  openPromptIds: new Set(),// expanded prompt cards (persist across polls)
  activeCenterTab: 'chapter',
  activeRightTab: 'inspector',
  statusPollTimer: null,
  statePollTimer: null,
  promptsPollTimer: null,
};

// ---------- utilities ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function')
      node.addEventListener(k.slice(2).toLowerCase(), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function fmtBytes(b) {
  if (b == null) return '';
  if (b < 1024) return b + ' B';
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
  return (b / (1024 * 1024)).toFixed(2) + ' MB';
}

function fmtRelTime(ts) {
  if (!ts) return '';
  const now = Date.now() / 1000;
  const d = now - ts;
  if (d < 5) return 'just now';
  if (d < 60) return Math.round(d) + 's ago';
  if (d < 3600) return Math.round(d / 60) + 'm ago';
  if (d < 86400) return Math.round(d / 3600) + 'h ago';
  return new Date(ts * 1000).toLocaleString();
}

function fmtClock(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function parseChapterFromInputs(inputs) {
  if (!Array.isArray(inputs)) return null;
  for (const p of inputs) {
    const m = /ch(\d{3})\.(md|plan\.json|verdict\.json)/.exec(p) || /ch(\d{3})\.md/.exec(p);
    if (m) return parseInt(m[1], 10);
  }
  return null;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = j.detail || j.error || detail;
    } catch (_) { /* noop */ }
    throw new Error(`${r.status} ${detail}`);
  }
  return r.json();
}

function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.toggle('is-error', isErr);
  t.classList.add('is-show');
  clearTimeout(toast._h);
  toast._h = setTimeout(() => t.classList.remove('is-show'), 3200);
}

// ---------- top bar pills ----------
function renderPills() {
  const s = state.snapshot;
  const st = state.status;
  if (!s) return;
  const prog = s.progress || {};
  const curr = prog.current_chapter ?? 0;

  $('#pill-chapter').textContent = curr > 0 ? `${curr}/${s.chapters.length}` : `0/${s.chapters.length}`;

  const runPill = $('#pill-running').parentElement;
  let runLabel = 'idle';
  if (st.running) {
    runLabel = (st.kind === 'audit' ? 'audit · ch ' : 'full · ch ') + (st.chapter ?? '?');
  } else if (prog.in_flight && prog.in_flight.stage) {
    runLabel = prog.in_flight.stage + ' · ch ' + prog.in_flight.chapter;
  }
  $('#pill-running').textContent = runLabel;
  runPill.classList.toggle('pill-running', st.running || !!prog.in_flight);

  const debtPill = $('#pill-debt').parentElement;
  $('#pill-debt').textContent = s.debt_count;
  debtPill.classList.toggle('pill-debt-hot', s.debt_count > 0);

  $('#pill-calls').textContent = s.prompt_count;

  // debt tab badge
  const badge = $('#tab-debt-count');
  if (s.debt_count > 0) {
    badge.textContent = s.debt_count;
  } else {
    badge.textContent = '';
  }
}

// ---------- file tree ----------
function renderTree() {
  const s = state.snapshot;
  if (!s) return;
  const tree = $('#tree');
  tree.innerHTML = '';

  // Section: top-level state files
  tree.appendChild(sectionHeader('state/ · root'));
  [
    ['state/outline.json',     'outline.json'],
    ['state/progress.json',    'progress.json'],
    ['state/timeline.yaml',    'timeline.yaml'],
    ['state/characters.yaml',  'characters.yaml'],
    ['state/issues.jsonl',     'issues.jsonl'],
    ['state/debt.jsonl',       'debt.jsonl'],
    ['state/prompts_log.jsonl','prompts_log.jsonl'],
  ].forEach(([p, name]) => tree.appendChild(treeItem(p, name, '•')));

  // Section: chapters folder, one group per chapter
  tree.appendChild(sectionHeader('chapters/'));
  const chWrap = el('div', { class: 'tree-group-items' });
  s.chapters.forEach((ch) => {
    const produced = [
      ch.has_plan, ch.has_md, ch.has_verdict,
      ch.has_summary, ch.has_slop_patch, ch.has_char_patch,
    ].filter(Boolean).length;
    const total = 6;
    const label = el('div', { class: 'tree-group-label', onclick: (e) => toggleGroup(e.currentTarget) },
      el('span', { class: 'tree-caret' }, '▶'),
      el('span', { class: 'tree-group-name' }, `ch${String(ch.ch).padStart(3, '0')}  ${ch.title.replace(/^第[一二三四五六七八九十]+章\s*·\s*/, '')}`),
      el('span', { class: 'tree-group-count' }, `${produced}/${total}`),
    );
    // auto-open the current / latest chapter
    const openDefault = ch.ch === (s.progress.current_chapter || 1) || ch.has_md;
    if (openDefault) label.classList.add('is-open');

    const items = el('div', { class: 'tree-items', style: openDefault ? '' : 'display:none' },
      treeItem(`state/chapters/ch${String(ch.ch).padStart(3, '0')}.plan.json`,    'plan.json',       '◇', !ch.has_plan),
      treeItem(`state/chapters/ch${String(ch.ch).padStart(3, '0')}.md`,           'chapter.md',      '✎', !ch.has_md),
      treeItem(`state/chapters/ch${String(ch.ch).padStart(3, '0')}.verdict.json`, 'verdict.json',    '⚖', !ch.has_verdict),
      treeItem(`state/summaries/ch${String(ch.ch).padStart(3, '0')}.md`,          'summary.md',      '≡', !ch.has_summary),
      treeItem(`state/fixes/ch${String(ch.ch).padStart(3, '0')}.slop-patch.md`,   'slop-patch.md',   '△', !ch.has_slop_patch),
      treeItem(`state/fixes/ch${String(ch.ch).padStart(3, '0')}.char-patch.md`,   'char-patch.md',   '☗', !ch.has_char_patch),
    );
    const group = el('div', { class: 'tree-group' }, label, items);
    chWrap.appendChild(group);
  });
  tree.appendChild(chWrap);

  // Section: rules (Progressive Disclosure)
  tree.appendChild(sectionHeader('rules/'));
  [
    ['rules/24-iron-laws.md',     '24-iron-laws.md'],
    ['rules/18-landmines.md',     '18-landmines.md'],
    ['rules/writing-style.md',    'writing-style.md'],
    ['rules/era-1983-hk.md',      'era-1983-hk.md'],
    ['rules/characters-canon.md', 'characters-canon.md'],
  ].forEach(([p, name]) => tree.appendChild(treeItem(p, name, '§')));

  // Section: project root
  tree.appendChild(sectionHeader('project/'));
  tree.appendChild(treeItem('AGENTS.md', 'AGENTS.md', '★'));
}

function sectionHeader(title) {
  return el('div', { class: 'tree-section-header' }, title);
}

function toggleGroup(labelEl) {
  labelEl.classList.toggle('is-open');
  const items = labelEl.nextElementSibling;
  if (items) items.style.display = labelEl.classList.contains('is-open') ? '' : 'none';
}

function treeItem(path, name, icon, missing = false) {
  const node = el('div', {
    class: 'tree-item' + (missing ? ' is-missing' : '') + (state.openFile === path ? ' is-active' : ''),
    dataset: { path },
    title: missing ? `${path} — 尚未生成` : path,
    onclick: missing ? null : () => openFile(path),
  },
    el('span', { class: 'tree-item-icon' }, icon),
    el('span', { class: 'tree-item-name' }, name),
  );
  return node;
}

// ---------- center viewer ----------
async function openFile(path) {
  state.openFile = path;
  // mark active
  $$('.tree-item').forEach((n) => n.classList.toggle('is-active', n.dataset.path === path));

  // decide which tab to focus
  if (path.startsWith('rules/')) {
    setCenterTab('rules');
  } else {
    setCenterTab('chapter');
  }

  const viewerRoot = path.startsWith('rules/') ? $('#rules-viewer') : $('#viewer');
  viewerRoot.innerHTML = '<div class="placeholder"><div class="placeholder-title">加载中…</div></div>';
  $('#viewer-meta').textContent = path;

  try {
    const res = await api('/api/file?path=' + encodeURIComponent(path));
    renderViewer(viewerRoot, res);
    $('#viewer-meta').textContent = `${path}  ·  ${fmtBytes(res.size)}`;
  } catch (e) {
    viewerRoot.innerHTML = '';
    viewerRoot.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '无法加载'),
      el('div', { class: 'placeholder-sub' }, String(e.message))));
  }
}

function renderViewer(root, file) {
  const ext = (file.path.split('.').pop() || '').toLowerCase();
  const isMd = ext === 'md' || file.mimetype === 'text/markdown';
  const isJsonish = ext === 'json' || ext === 'jsonl';
  const isYaml = ext === 'yaml' || ext === 'yml';

  root.innerHTML = '';

  if (isMd && window.marked) {
    const html = window.marked.parse(file.content, { breaks: false, gfm: true });
    const article = el('div', { class: 'viewer' });
    article.innerHTML = html;
    root.appendChild(article);
  } else if (isJsonish) {
    const pre = el('pre', { class: 'viewer-source' });
    pre.innerHTML = highlightJson(file.content, ext === 'jsonl');
    root.appendChild(pre);
  } else if (isYaml) {
    const pre = el('pre', { class: 'viewer-source' });
    pre.textContent = file.content;
    root.appendChild(pre);
  } else {
    const pre = el('pre', { class: 'viewer-source' });
    pre.textContent = file.content;
    root.appendChild(pre);
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function highlightJson(text, jsonl) {
  // small, line-safe highlighter; pretty-prints .json but leaves .jsonl as-is
  let source = text;
  if (!jsonl) {
    try { source = JSON.stringify(JSON.parse(text), null, 2); } catch (_) { /* leave raw */ }
  }
  const escaped = escapeHtml(source);
  return escaped
    .replace(/(&quot;[^&]*?&quot;)\s*:/g, '<span class="src-key">$1</span>:')
    .replace(/: (&quot;.*?&quot;)/g, ': <span class="src-string">$1</span>')
    .replace(/\b(-?\d+(?:\.\d+)?)\b/g, '<span class="src-num">$1</span>')
    .replace(/\b(true|false)\b/g, '<span class="src-bool">$1</span>')
    .replace(/\bnull\b/g, '<span class="src-null">null</span>');
}

// ---------- center tabs ----------
function setCenterTab(name) {
  state.activeCenterTab = name;
  $$('.tab[data-tab]').forEach((b) => b.classList.toggle('tab-active', b.dataset.tab === name));
  $$('.tab-pane[data-pane]').forEach((p) => p.classList.toggle('tab-pane-active', p.dataset.pane === name));
  if (name === 'debt') renderDebt();
}

function setRightTab(name) {
  state.activeRightTab = name;
  $$('.tab[data-rtab]').forEach((b) => b.classList.toggle('tab-active', b.dataset.rtab === name));
  $$('.tab-pane[data-rpane]').forEach((p) => p.classList.toggle('tab-pane-active', p.dataset.rpane === name));
  renderPrompts(); // re-render current view
}

// ---------- debt ----------
async function renderDebt() {
  const root = $('#debt-view');
  try {
    const debt = await api('/api/debt');
    root.innerHTML = '';
    if (!debt.length) {
      root.appendChild(el('div', { class: 'debt-empty' },
        el('div', { class: 'debt-empty-mark' }, '✓'),
        el('div', null, '暂无技术债'),
        el('div', { style: 'color: var(--text-soft); font-size: 12px; margin-top: 8px;' },
          '每章都在 2 次 Fixer 重试内通过评审。'),
      ));
      return;
    }
    const table = el('table', { class: 'debt-table' },
      el('thead', null, el('tr', null,
        el('th', null, 'Chapter'),
        el('th', null, 'Retries'),
        el('th', null, 'Unresolved'),
        el('th', null, 'Top Unresolved Landmines'),
        el('th', null, 'When'),
      )),
      el('tbody', null,
        ...debt.map((d) => el('tr', null,
          el('td', null, 'ch ' + d.chapter),
          el('td', null, String(d.retries_used)),
          el('td', null, String((d.unresolved || []).length)),
          el('td', { class: 'debt-landmines' },
            ...(d.unresolved || []).slice(0, 5).map((u) =>
              el('span', { class: 'debt-landmine-pill', title: u.evidence || '' }, u.landmine_id || '?')),
          ),
          el('td', { style: 'color: var(--text-soft); font-family: var(--font-mono); font-size: 11px;' },
            fmtRelTime(d.ts)),
        )),
      ),
    );
    root.appendChild(table);
  } catch (e) {
    root.innerHTML = '';
    root.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, 'Debt 加载失败'),
      el('div', { class: 'placeholder-sub' }, e.message)));
  }
}

// ---------- prompt inspector (the money shot) ----------
async function refreshPrompts() {
  try {
    const arr = await api('/api/prompts?limit=80');
    state.prompts = arr;
    renderPrompts();
  } catch (_) { /* tolerate */ }
}

function renderPrompts() {
  if (state.activeRightTab === 'inspector') renderInspector();
  else renderLog();
}

function renderInspector() {
  const root = $('#inspector');
  if (!state.prompts.length) {
    root.innerHTML = '';
    root.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '等待 LLM 调用…'),
      el('div', { class: 'placeholder-sub' }, '点击顶栏「生成下一章」开始。')));
    return;
  }
  root.innerHTML = '';
  state.prompts.forEach((p) => root.appendChild(inspectorCard(p)));
}

function inspectorCard(p) {
  const agent = p.agent_name || 'unknown';
  const open = state.openPromptIds.has(p.id);
  const chapter = parseChapterFromInputs(p.inputs_read);
  const tokens = (p.usage && (p.usage.completion_tokens ?? p.usage.total_tokens)) || null;
  const promptTokens = p.usage && p.usage.prompt_tokens;

  const head = el('div', {
    class: 'insp-head',
    onclick: () => {
      if (state.openPromptIds.has(p.id)) state.openPromptIds.delete(p.id);
      else state.openPromptIds.add(p.id);
      renderInspector();
    },
  },
    el('div', { class: 'insp-row-1' },
      el('span', { class: `insp-agent insp-agent-${agent}` }, AGENT_LABEL[agent] || agent.toUpperCase()),
      chapter ? el('span', { class: 'insp-chapter' }, 'ch ' + chapter) : null,
      p.error ? el('span', { class: 'insp-err' }, 'ERROR') : null,
    ),
    el('div', { class: 'insp-time' }, fmtRelTime(p.ts)),
    el('div', { class: 'insp-row-2' },
      p.latency_ms != null ? metric('latency', (p.latency_ms / 1000).toFixed(1) + 's') : null,
      tokens ? metric('tokens', tokens + (promptTokens ? `  (+${promptTokens} in)` : '')) : null,
      p.model ? metric('model', p.model) : null,
      p.temperature != null ? metric('temp', p.temperature) : null,
    ),
  );

  const body = el('div', { class: 'insp-body' },
    el('div', { class: 'insp-callout' },
      el('strong', null, '📋 Fresh context · '),
      promptTokens ? `${promptTokens} prompt tokens, ` : '',
      'no prior conversation, no leftover memory. This call starts from zero.',
    ),
    inspSection('inputs_read',
      el('div', { class: 'insp-inputs' },
        ...(p.inputs_read || ['—']).map((inp) => inp === '—'
          ? el('span', { class: 'insp-input-chip' }, '—')
          : el('span', {
              class: 'insp-input-chip',
              onclick: () => openFile(inp.replace(/^\.\//, '').startsWith('state/') || inp.startsWith('rules/') || inp === 'AGENTS.md' ? inp : 'state/' + inp),
            }, inp))),
    ),
    inspSection('system prompt', el('pre', { class: 'insp-pre insp-pre-sys' }, p.system || '')),
    inspSection('user prompt',   el('pre', { class: 'insp-pre insp-pre-user' }, p.user || '')),
    inspSection(p.error ? 'error' : 'output',
      el('pre', { class: 'insp-pre insp-pre-output' }, p.error ? JSON.stringify(p.error, null, 2) : (p.output || ''))),
    inspMeta(p),
  );

  const card = el('div', { class: 'insp-card' + (open ? ' is-open' : '') },
    el('div', { class: `insp-dot ag-${agent}` }),
    head,
    body,
  );
  return card;
}

function metric(label, value) {
  return el('span', { class: 'insp-metric' },
    el('span', { class: 'insp-metric-label' }, label + ':'),
    el('span', { class: 'insp-metric-value' }, String(value)),
  );
}

function inspSection(label, body) {
  return el('div', { class: 'insp-section' },
    el('div', { class: 'insp-section-label' }, label),
    body,
  );
}

function inspMeta(p) {
  return el('div', { class: 'insp-section' },
    el('div', { class: 'insp-section-label' }, 'raw metadata'),
    el('div', { class: 'insp-meta-grid' },
      el('span', null, 'id'),            el('span', null, p.id || '—'),
      el('span', null, 'ts'),            el('span', null, fmtClock(p.ts)),
      el('span', null, 'model'),         el('span', null, p.model || '—'),
      el('span', null, 'temperature'),   el('span', null, p.temperature ?? '—'),
      el('span', null, 'response_fmt'),  el('span', null, p.response_format || 'text'),
      el('span', null, 'latency_ms'),    el('span', null, p.latency_ms ?? '—'),
    ),
  );
}

function renderLog() {
  const root = $('#log-view');
  root.innerHTML = '';
  if (!state.prompts.length) {
    root.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '尚无日志')));
    return;
  }
  state.prompts.forEach((p) => {
    const chapter = parseChapterFromInputs(p.inputs_read);
    const tokens = (p.usage && p.usage.completion_tokens) || '—';
    root.appendChild(el('div', {
      class: 'log-row',
      title: p.id,
      onclick: () => {
        setRightTab('inspector');
        state.openPromptIds.add(p.id);
        renderInspector();
        // scroll to card
        setTimeout(() => {
          const cards = $$('.insp-card');
          // newest first — find matching index
          const idx = state.prompts.findIndex((x) => x.id === p.id);
          if (cards[idx]) cards[idx].scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 50);
      },
    },
      el('span', { class: `log-bar ag-${p.agent_name}` }),
      el('span', { class: 'log-time' }, fmtClock(p.ts)),
      el('span', { class: `log-agent insp-agent-${p.agent_name}` }, (p.agent_name || '?').toUpperCase()),
      el('span', { class: 'log-ch' }, chapter ? 'ch' + chapter : '—'),
      el('span', { class: 'log-lat' }, p.latency_ms != null ? (p.latency_ms / 1000).toFixed(1) + 's' : '—'),
      el('span', { class: 'log-tok' }, String(tokens)),
      el('span', { class: p.error ? 'log-err' : '' }, p.error ? 'ERROR' : (p.inputs_read || []).join(', ')),
    ));
  });
}

// ---------- polling ----------
async function pollState() {
  try {
    state.snapshot = await api('/api/state');
    renderPills();
    renderTree();
  } catch (e) {
    // don't spam toasts on polling failures
    console.warn('state poll:', e.message);
  }
}

async function pollStatus() {
  try {
    const prev = state.status.running;
    state.status = await api('/api/status');
    renderPills();
    if (prev && !state.status.running) {
      if (state.status.ok === false) {
        toast('流水线失败: ' + (state.status.error || 'unknown'), true);
      } else {
        toast('流水线完成 · chapter ' + state.status.chapter);
        pollState();
        refreshPrompts();
      }
    }
  } catch (_) { /* tolerate */ }

  // adaptive cadence: faster when running
  const interval = state.status.running ? 1500 : 4000;
  state.statusPollTimer = setTimeout(pollStatus, interval);
}

async function pollPrompts() {
  if (state.activeRightTab === 'inspector' || state.activeRightTab === 'log') {
    await refreshPrompts();
  }
  state.promptsPollTimer = setTimeout(pollPrompts, state.status.running ? 2500 : 5000);
}

// ---------- actions ----------
async function runNextChapter() {
  const s = state.snapshot;
  if (!s) return;
  const next = (s.progress.current_chapter || 0) + 1;
  if (next > s.chapters.length) {
    toast('大纲已跑完（' + s.chapters.length + ' 章）', true);
    return;
  }
  try {
    await api('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: next }),
    });
    toast('开始生成 chapter ' + next);
    pollStatus();
  } catch (e) {
    toast('无法启动: ' + e.message, true);
  }
}

async function runAuditCurrent() {
  const s = state.snapshot;
  if (!s) return;
  const curr = s.progress.current_chapter || 1;
  try {
    await api('/api/audit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: curr }),
    });
    toast('重审 chapter ' + curr + ' · 仅 Auditor 风扇');
    pollStatus();
  } catch (e) {
    toast('无法启动: ' + e.message, true);
  }
}

// ---------- init ----------
function wireTabs() {
  $$('.tab[data-tab]').forEach((b) =>
    b.addEventListener('click', () => setCenterTab(b.dataset.tab)));
  $$('.tab[data-rtab]').forEach((b) =>
    b.addEventListener('click', () => setRightTab(b.dataset.rtab)));
}

function wireButtons() {
  $('#btn-run').addEventListener('click', runNextChapter);
  $('#btn-audit').addEventListener('click', runAuditCurrent);
  $('#btn-reload').addEventListener('click', () => location.reload());
}

async function init() {
  wireTabs();
  wireButtons();
  await pollState();
  await refreshPrompts();
  await pollStatus();
  pollPrompts();
  // fast state refresh
  (function loopState() {
    state.statePollTimer = setTimeout(async () => {
      await pollState();
      loopState();
    }, state.status.running ? 2000 : 4000);
  })();

  // Auto-open the first produced chapter on first load
  if (state.snapshot && state.snapshot.chapters.length) {
    const produced = state.snapshot.chapters.find((c) => c.has_md);
    if (produced) openFile(`state/chapters/ch${String(produced.ch).padStart(3, '0')}.md`);
  }
}

window.addEventListener('DOMContentLoaded', init);
