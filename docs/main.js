/* =========================================================
   Blackboard Novel Pipeline — STATIC demo UI (GitHub Pages)
   Vanilla JS. No bundler, no framework, no server.
   Reads files directly from ../demo_snapshot/, ../rules/, ../AGENTS.md.
   ========================================================= */

'use strict';

// ---------- path resolution ----------
// The UI shows logical paths like `state/chapters/ch001.md` so the mental model
// matches the design doc (state lives in files). Internally, those paths
// resolve to files committed in the repo.
const SNAPSHOT_BASE = '../demo_snapshot/';
const RULES_BASE    = '../rules/';
const AGENTS_PATH   = '../AGENTS.md';

function resolvePath(logicalPath) {
  // `state/chapters/ch001.md`  -> `../demo_snapshot/chapters/ch001.md`
  // `state/outline.json`       -> `../demo_snapshot/outline.json`
  // `rules/24-iron-laws.md`    -> `../rules/24-iron-laws.md`
  // `AGENTS.md`                -> `../AGENTS.md`
  if (logicalPath === 'AGENTS.md') return AGENTS_PATH;
  if (logicalPath.startsWith('state/')) return SNAPSHOT_BASE + logicalPath.slice('state/'.length);
  if (logicalPath.startsWith('rules/')) return RULES_BASE + logicalPath.slice('rules/'.length);
  return logicalPath; // fallback
}

// ---------- constants ----------
const AGENT_LABEL = {
  planner:         'PLANNER',
  generator:       'GENERATOR',
  evaluator:       'EVALUATOR',
  fixer:           'FIXER',
  summarizer:      'SUMMARIZER',
  ai_slop_guard:   'AI-SLOP GUARD',
  character_guard: 'CHARACTER GUARD',
};

const state = {
  snapshot: null,
  chapters: [],
  prompts: [],
  openFile: null,
  openPromptIds: new Set(),
  activeCenterTab: 'chapter',
  activeRightTab: 'inspector',
  // cache: logical path -> { content, size, mimetype }
  fileCache: new Map(),
  // cache: logical path -> HEAD existence bool
  existCache: new Map(),
};

// ---------- dom helpers ----------
const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

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

// ---------- fetching ----------
async function fetchText(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} · ${url}`);
  return r.text();
}

async function fetchJSON(url) {
  const txt = await fetchText(url);
  return JSON.parse(txt);
}

async function fetchJSONL(url) {
  try {
    const txt = await fetchText(url);
    return txt.split(/\r?\n/).filter(Boolean).map((line) => {
      try { return JSON.parse(line); } catch (_) { return null; }
    }).filter(Boolean);
  } catch (e) {
    console.warn('jsonl load failed:', url, e.message);
    return [];
  }
}

async function headOk(url) {
  if (state.existCache.has(url)) return state.existCache.get(url);
  try {
    // Some static hosts (incl. GitHub Pages) handle HEAD fine; fall back to GET w/ range on error.
    const r = await fetch(url, { method: 'HEAD', cache: 'no-cache' });
    const ok = r.ok;
    state.existCache.set(url, ok);
    return ok;
  } catch (_) {
    state.existCache.set(url, false);
    return false;
  }
}

function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.toggle('is-error', isErr);
  t.classList.add('is-show');
  clearTimeout(toast._h);
  toast._h = setTimeout(() => t.classList.remove('is-show'), 3200);
}

// ---------- build /api/state locally ----------
async function buildSnapshot() {
  const [progress, outline, issuesArr, debtArr, promptsArr] = await Promise.all([
    fetchJSON(SNAPSHOT_BASE + 'progress.json'),
    fetchJSON(SNAPSHOT_BASE + 'outline.json'),
    fetchJSONL(SNAPSHOT_BASE + 'issues.jsonl'),
    fetchJSONL(SNAPSHOT_BASE + 'debt.jsonl'),
    fetchJSONL(SNAPSHOT_BASE + 'prompts_log.jsonl'),
  ]);

  // cache prompts globally (newest first, capped)
  state.prompts = promptsArr.slice().reverse().slice(0, 50);

  const chapters = [];
  for (const entry of (outline.chapters || [])) {
    const n = entry.ch;
    const nnn = String(n).padStart(3, '0');
    const probes = await Promise.all([
      headOk(SNAPSHOT_BASE + `chapters/ch${nnn}.md`),
      headOk(SNAPSHOT_BASE + `chapters/ch${nnn}.plan.json`),
      headOk(SNAPSHOT_BASE + `chapters/ch${nnn}.verdict.json`),
      headOk(SNAPSHOT_BASE + `summaries/ch${nnn}.md`),
      headOk(SNAPSHOT_BASE + `fixes/ch${nnn}.slop-patch.md`),
      headOk(SNAPSHOT_BASE + `fixes/ch${nnn}.char-patch.md`),
    ]);
    chapters.push({
      ch: n,
      title: entry.title || `第 ${n} 章`,
      has_md: probes[0],
      has_plan: probes[1],
      has_verdict: probes[2],
      has_summary: probes[3],
      has_slop_patch: probes[4],
      has_char_patch: probes[5],
    });
  }

  return {
    progress, chapters,
    novel: { title: outline.title, subtitle: outline.subtitle, protagonist: outline.protagonist },
    debt: debtArr,
    issues: issuesArr,
    debt_count: debtArr.length,
    issue_count: issuesArr.length,
    prompt_count: promptsArr.length,
    readonly_mode: true,
    static_demo: true,
  };
}

// ---------- top bar pills ----------
function renderPills() {
  const s = state.snapshot;
  if (!s) return;
  const prog = s.progress || {};
  const curr = prog.current_chapter ?? 0;

  $('#pill-chapter').textContent =
    curr > 0 ? `${curr}/${s.chapters.length}` : `0/${s.chapters.length}`;

  const runPill = $('#pill-running').parentElement;
  $('#pill-running').textContent = 'snapshot';
  runPill.classList.remove('pill-running');

  const debtPill = $('#pill-debt').parentElement;
  $('#pill-debt').textContent = s.debt_count;
  debtPill.classList.toggle('pill-debt-hot', s.debt_count > 0);

  $('#pill-calls').textContent = s.prompt_count;

  const badge = $('#tab-debt-count');
  badge.textContent = s.debt_count > 0 ? String(s.debt_count) : '';
}

// ---------- file tree ----------
function renderTree() {
  const s = state.snapshot;
  if (!s) return;
  const tree = $('#tree');
  tree.innerHTML = '';

  // --- state/ root (only show files that actually exist)
  tree.appendChild(sectionHeader('state/ · root'));
  const rootFiles = [
    ['state/outline.json',      'outline.json',      '•'],
    ['state/progress.json',     'progress.json',     '•'],
    ['state/timeline.yaml',     'timeline.yaml',     '•'],
    ['state/characters.yaml',   'characters.yaml',   '•'],
    ['state/issues.jsonl',      'issues.jsonl',      '•'],
    ['state/debt.jsonl',        'debt.jsonl',        '•'],
    ['state/prompts_log.jsonl', 'prompts_log.jsonl', '•'],
  ];
  rootFiles.forEach(([p, name, icon]) => tree.appendChild(treeItem(p, name, icon)));

  // --- chapters/ folder
  tree.appendChild(sectionHeader('chapters/'));
  const chWrap = el('div', { class: 'tree-group-items' });
  s.chapters.forEach((ch) => {
    const produced = [
      ch.has_plan, ch.has_md, ch.has_verdict,
      ch.has_summary, ch.has_slop_patch, ch.has_char_patch,
    ].filter(Boolean).length;
    const total = 6;
    const hasAny = produced > 0;
    const label = el('div',
      { class: 'tree-group-label' + (hasAny ? '' : ' is-empty'),
        onclick: (e) => toggleGroup(e.currentTarget) },
      el('span', { class: 'tree-caret' }, '▶'),
      el('span', { class: 'tree-group-name' },
        `ch${String(ch.ch).padStart(3, '0')}  ${String(ch.title).replace(/^第[一二三四五六七八九十百千]+章\s*·\s*/, '')}`),
      el('span', { class: 'tree-group-count' }, `${produced}/${total}`),
    );
    // Auto-open any chapter with content (all 3 in the demo)
    const openDefault = hasAny;
    if (openDefault) label.classList.add('is-open');

    const nnn = String(ch.ch).padStart(3, '0');
    const items = el('div',
      { class: 'tree-items', style: openDefault ? '' : 'display:none' },
      treeItem(`state/chapters/ch${nnn}.plan.json`,    'plan.json',     '◇', !ch.has_plan),
      treeItem(`state/chapters/ch${nnn}.md`,           'chapter.md',    '✎', !ch.has_md),
      treeItem(`state/chapters/ch${nnn}.verdict.json`, 'verdict.json',  '⚖', !ch.has_verdict),
      treeItem(`state/summaries/ch${nnn}.md`,          'summary.md',    '≡', !ch.has_summary),
      treeItem(`state/fixes/ch${nnn}.slop-patch.md`,   'slop-patch.md', '△', !ch.has_slop_patch),
      treeItem(`state/fixes/ch${nnn}.char-patch.md`,   'char-patch.md', '☗', !ch.has_char_patch),
    );
    chWrap.appendChild(el('div', { class: 'tree-group' }, label, items));
  });
  tree.appendChild(chWrap);

  // --- rules/
  tree.appendChild(sectionHeader('rules/'));
  [
    ['rules/24-iron-laws.md',     '24-iron-laws.md'],
    ['rules/18-landmines.md',     '18-landmines.md'],
    ['rules/writing-style.md',    'writing-style.md'],
    ['rules/era-1983-hk.md',      'era-1983-hk.md'],
    ['rules/characters-canon.md', 'characters-canon.md'],
  ].forEach(([p, name]) => tree.appendChild(treeItem(p, name, '§')));

  // --- project root
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
  return el('div', {
    class: 'tree-item' + (missing ? ' is-missing' : '') + (state.openFile === path ? ' is-active' : ''),
    dataset: { path },
    title: missing ? `${path} — 尚未生成` : path,
    onclick: missing ? null : () => openFile(path),
  },
    el('span', { class: 'tree-item-icon' }, icon),
    el('span', { class: 'tree-item-name' }, name),
  );
}

// ---------- center viewer ----------
async function openFile(logicalPath) {
  state.openFile = logicalPath;
  $$('.tree-item').forEach((n) => n.classList.toggle('is-active', n.dataset.path === logicalPath));

  if (logicalPath.startsWith('rules/')) setCenterTab('rules');
  else setCenterTab('chapter');

  const viewerRoot = logicalPath.startsWith('rules/') ? $('#rules-viewer') : $('#viewer');
  viewerRoot.innerHTML = '<div class="placeholder"><div class="placeholder-title">加载中…</div></div>';
  $('#viewer-meta').textContent = logicalPath;

  try {
    const file = await loadFile(logicalPath);
    renderViewer(viewerRoot, file);
    $('#viewer-meta').textContent = `${logicalPath}  ·  ${fmtBytes(file.size)}`;
  } catch (e) {
    viewerRoot.innerHTML = '';
    viewerRoot.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '无法加载'),
      el('div', { class: 'placeholder-sub' }, String(e.message))));
  }
}

async function loadFile(logicalPath) {
  if (state.fileCache.has(logicalPath)) return state.fileCache.get(logicalPath);
  const url = resolvePath(logicalPath);
  const content = await fetchText(url);
  const file = {
    path: logicalPath,
    content,
    size: new Blob([content]).size,
    mimetype: guessMime(logicalPath),
  };
  state.fileCache.set(logicalPath, file);
  return file;
}

function guessMime(p) {
  const ext = (p.split('.').pop() || '').toLowerCase();
  return {
    md: 'text/markdown', json: 'application/json', jsonl: 'application/x-ndjson',
    yaml: 'text/yaml', yml: 'text/yaml',
  }[ext] || 'text/plain';
}

function renderViewer(root, file) {
  const ext = (file.path.split('.').pop() || '').toLowerCase();
  const isMd = ext === 'md';
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
    // We could js-yaml.load + re-stringify, but showing the raw yaml is
    // actually more honest (matches what the agent reads on disk).
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
  return s.replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function highlightJson(text, jsonl) {
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
  renderPrompts();
}

// ---------- debt ----------
function renderDebt() {
  const root = $('#debt-view');
  const debt = (state.snapshot && state.snapshot.debt) || [];
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
            el('span', { class: 'debt-landmine-pill', title: u.evidence || '' },
              u.landmine_id || '?'))),
        el('td',
          { style: 'color: var(--text-soft); font-family: var(--font-mono); font-size: 11px;' },
          fmtRelTime(d.ts)),
      )),
    ),
  );
  root.appendChild(table);
}

// ---------- prompt inspector ----------
function renderPrompts() {
  if (state.activeRightTab === 'inspector') renderInspector();
  else renderLog();
}

function renderInspector() {
  const root = $('#inspector');
  if (!state.prompts.length) {
    root.innerHTML = '';
    root.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '暂无 LLM 调用')));
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
              onclick: () => {
                const normalized = inp.replace(/^\.\//, '');
                const target = (normalized.startsWith('state/')
                  || normalized.startsWith('rules/')
                  || normalized === 'AGENTS.md')
                  ? normalized
                  : 'state/' + normalized;
                openFile(target);
              },
            }, inp))),
    ),
    inspSection('system prompt', el('pre', { class: 'insp-pre insp-pre-sys' }, p.system || '')),
    inspSection('user prompt',   el('pre', { class: 'insp-pre insp-pre-user' }, p.user || '')),
    inspSection(p.error ? 'error' : 'output',
      el('pre', { class: 'insp-pre insp-pre-output' },
        p.error ? JSON.stringify(p.error, null, 2) : (p.output || ''))),
    inspMeta(p),
  );

  return el('div', { class: 'insp-card' + (open ? ' is-open' : '') },
    el('div', { class: `insp-dot ag-${agent}` }),
    head,
    body,
  );
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
        setTimeout(() => {
          const cards = $$('.insp-card');
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
      el('span', { class: p.error ? 'log-err' : '' },
        p.error ? 'ERROR' : (p.inputs_read || []).join(', ')),
    ));
  });
}

// ---------- disabled actions ----------
function showReadonlyToast() {
  toast('静态演示只读。完整版本见 GitHub。', true);
}

// ---------- init ----------
function wireTabs() {
  $$('.tab[data-tab]').forEach((b) =>
    b.addEventListener('click', () => setCenterTab(b.dataset.tab)));
  $$('.tab[data-rtab]').forEach((b) =>
    b.addEventListener('click', () => setRightTab(b.dataset.rtab)));
}

function wireButtons() {
  $('#btn-run').addEventListener('click', (e) => { e.preventDefault(); showReadonlyToast(); });
  $('#btn-audit').addEventListener('click', (e) => { e.preventDefault(); showReadonlyToast(); });
  $('#btn-reload').addEventListener('click', () => location.reload());
}

async function init() {
  wireTabs();
  wireButtons();

  try {
    state.snapshot = await buildSnapshot();
  } catch (e) {
    $('#tree').innerHTML = '';
    $('#tree').appendChild(el('div', { class: 'tree-empty' },
      '无法加载 demo_snapshot/: ' + e.message));
    toast('加载失败: ' + e.message, true);
    return;
  }

  renderPills();
  renderTree();
  renderPrompts();

  // Auto-open the first produced chapter so judges see content within 2s.
  const produced = state.snapshot.chapters.find((c) => c.has_md);
  if (produced) {
    openFile(`state/chapters/ch${String(produced.ch).padStart(3, '0')}.md`);
  }
}

window.addEventListener('DOMContentLoaded', init);
