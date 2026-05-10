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
//
// SNAPSHOT_BASE is mutable — judges can toggle between demo settings
// (gangster-HK-1983 / xianxia-ascension) via the segmented control in the
// static banner. The xianxia folder may not exist yet; see reloadAfterSwitch()
// for the graceful fallback.
const DEMO_SETTINGS = [
  { id: 'gangster', label: '港综 · 1983', base: './demo_snapshot/' },
  { id: 'xianxia',  label: '仙侠 · 飞升', base: './demo_snapshot_xianxia/' },
];
let activeDemo = 'gangster';
let SNAPSHOT_BASE = DEMO_SETTINGS[0].base;
const RULES_BASE   = './rules/';
const AGENTS_PATH  = './AGENTS.md';

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
  planner:              'PLANNER',
  generator:            'GENERATOR',
  evaluator:            'EVALUATOR',
  fixer:                'FIXER',
  summarizer:           'SUMMARIZER',
  arc_summarizer:       'ARC SUMMARIZER',
  book_summarizer:      'BOOK SUMMARIZER',
  status_card_updater:  'STATUS CARD',
  hook_keeper:          'HOOK KEEPER',
  resource_ledger:      'RESOURCE LEDGER',
  ai_slop_guard:        'AI-SLOP GUARD',
  character_guard:      'CHARACTER GUARD',
};

// ---------- LESSONS (pitch crosswalk: principle → code) ----------
const REPO_URL = 'https://github.com/CalWade/blackboard-novel-pipeline';
const LESSONS = [
  {
    n: 1,
    title: '反复失败时修工具而非提示',
    attribution: 'Anthropic',
    attribution_color: 'anthropic',
    principle: '状态沉到文件里 · 重启胜过修补',
    impl: [
      '所有 Agent 无状态, 每次调用 fresh context',
      '失败写入 state/issues.jsonl + state/debt.jsonl, Fixer 下一轮从文件读',
      '重跑整个章节只需一条命令: python -m src.pipeline --chapter N',
    ],
    code_pointers: [
      { label: 'src/blackboard.py', desc: '文件系统 = 共享记忆的唯一 source of truth', github_path: 'src/blackboard.py', logical_path: null },
      { label: 'src/pipeline.py',   desc: '每个 stage 都是独立 agent.run()',          github_path: 'src/pipeline.py',   logical_path: null },
      { label: 'state/issues.jsonl', desc: 'append-only 失败日志',                    github_path: null,                logical_path: 'state/issues.jsonl' },
    ],
  },
  {
    n: 2,
    title: '自评偏乐观, 必须分工',
    attribution: 'Anthropic',
    attribution_color: 'anthropic',
    principle: '干活的和验收的必须是不同的人',
    impl: [
      'Planner / Generator / Evaluator / Fixer / Summarizer 五个创作 Agent',
      'StatusCardUpdater / HookKeeper / ResourceLedger 三个 bookkeeping Agent (覆盖式)',
      'Evaluator 用对抗人设 (默认拒稿) + 结构化 JSON rubric (18 landmines × severity)',
      'Evaluator 看不到 Generator 的推理过程, 只看最终文件',
      '服务端重算 overall_pass, 不信模型自评 + skeleton detector 防模型复制示例',
    ],
    code_pointers: [
      { label: 'src/agents/evaluator.py', desc: '对抗人设 + JSON rubric + skeleton detector', github_path: 'src/agents/evaluator.py', logical_path: null },
      { label: 'rules/18-landmines.md',   desc: '18 个雷点的结构化判据 (通用)',              github_path: 'rules/18-landmines.md',   logical_path: 'rules/18-landmines.md' },
      { label: 'state/iron-laws-extra.md', desc: '题材特有铁律 (setting 注入)',              github_path: null,                      logical_path: 'state/iron-laws-extra.md' },
      { label: 'rules/00-information-priority.md', desc: '冲突仲裁协议 (9 级优先级 + R1..R5)', github_path: 'rules/00-information-priority.md', logical_path: 'rules/00-information-priority.md' },
    ],
  },
  {
    n: 3,
    title: 'Context Anxiety 需要 Reset',
    attribution: 'Cognition',
    attribution_color: 'cognition',
    principle: '直接丢弃旧窗口, 新窗口从文件读进度',
    impl: [
      '每次 LLM 调用都是 fresh session (见 Inspector: 每行 ≤6 文件, 无累积)',
      'Summarizer 严格只读最终 chapter, 不读 plan/verdict/issues (防 framing 后门泄漏)',
      'Planner 读 ≤2 份前章摘要 + 当前状态卡 + 伏笔池, 不读全文',
      'StatusCardUpdater 每章末覆盖 state/current_status_card.md — 进程重启读它即可恢复',
      'HookKeeper 每章末覆盖 state/pending_hooks.md — 避免 10+ 章漏伏笔',
      'ResourceLedger (可选) 每章末覆盖 state/resource_ledger.md — 仅当 setting 声明 schema',
    ],
    code_pointers: [
      { label: 'src/llm.py',                      desc: '每次调用新建 messages 数组, 无跨调用 memory', github_path: 'src/llm.py',                      logical_path: null },
      { label: 'src/agents/summarizer.py',        desc: 'Summarizer 只读 chapter file (严防泄漏)',    github_path: 'src/agents/summarizer.py',        logical_path: null },
      { label: 'src/agents/status_card_updater.py', desc: 'StatusCardUpdater — 唯一的当前时间点快照', github_path: 'src/agents/status_card_updater.py', logical_path: null },
      { label: 'src/agents/hook_keeper.py',       desc: 'HookKeeper — 待回收伏笔池',                  github_path: 'src/agents/hook_keeper.py',       logical_path: null },
      { label: 'state/current_status_card.md',    desc: 'Context Reset 的单一入口文件',               github_path: null,                              logical_path: 'state/current_status_card.md' },
      { label: 'state/prompts_log.jsonl',         desc: '每次调用的 inputs_read 清单 (见 Inspector)', github_path: null,                              logical_path: 'state/prompts_log.jsonl' },
    ],
  },
  {
    n: 4,
    title: 'AI Slop 每天还一点',
    attribution: 'OpenAI Codex',
    attribution_color: 'openai',
    principle: '黄金原则沉仓库 · 后台 Agent 定期扫 · 带债上线',
    impl: [
      'rules/*.md 是黄金原则 (24 iron laws + 18 landmines, 通用)',
      'settings/<name>/iron-laws-extra.md: 题材特有铁律 (setting 注入)',
      '2 个 Auditor 并行独立会话扫每一章 → state/fixes/chNNN.*-patch.md (类 PR)',
      'Evaluator 2 次 retry 仍不过 → shipped_with_debt, 写 debt.jsonl 不死循环',
    ],
    code_pointers: [
      { label: 'rules/24-iron-laws.md', desc: '通用 golden principles (题材无关)',       github_path: 'rules/24-iron-laws.md', logical_path: 'rules/24-iron-laws.md' },
      { label: 'src/auditors/',         desc: 'AISlopGuard + CharacterGuard (Fan-Out 并行)', github_path: 'src/auditors',      logical_path: null },
      { label: 'src/pipeline.py',       desc: '_append_debt: retries 用尽后带债上线',   github_path: 'src/pipeline.py',       logical_path: null },
      { label: 'state/debt.jsonl',      desc: '技术债账本 (每日可还)',                  github_path: null,                    logical_path: 'state/debt.jsonl' },
    ],
  },
  {
    n: 5,
    title: '规则文件宁缺毋滥',
    attribution: 'OpenAI',
    attribution_color: 'openai',
    principle: 'AGENTS.md 目录页 · 详细拆到子文档 · Progressive Disclosure',
    impl: [
      'AGENTS.md 仅 ~70 行, 纯索引 + 规则映射表',
      'rules/ 下 3 份通用规则 + settings/<name>/ 下 3 份题材规则',
      '每个 Agent 只加载它需要的那 1-2 份 (见 AGENTS.md 规则索引)',
    ],
    code_pointers: [
      { label: 'AGENTS.md',  desc: '70 行目录页, 规则按 agent 分派', github_path: 'AGENTS.md', logical_path: 'AGENTS.md' },
      { label: 'rules/',     desc: '3 份通用规则 (题材无关)',        github_path: 'rules',     logical_path: null },
      { label: 'settings/',  desc: '题材包目录, 每个 7 文件',        github_path: 'settings',  logical_path: null },
    ],
  },
];

const state = {
  snapshot: null,
  chapters: [],
  prompts: [],
  openFile: null,
  openPromptIds: new Set(),
  activeCenterTab: 'chapter',
  activeRightTab: 'inspector',
  lessonsRendered: false,
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
  if (d < 5) return '刚刚';
  if (d < 60) return Math.round(d) + ' 秒前';
  if (d < 3600) return Math.round(d / 60) + ' 分钟前';
  if (d < 86400) return Math.round(d / 3600) + ' 小时前';
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

  // Probe bookkeeping artifacts (C-23 / C-24 / C-25). These are global
  // (overwrite-style), not per-chapter, and may not yet exist in snapshots
  // produced before the bookkeeping layer was added. The UI degrades
  // gracefully: missing items render as dimmed 'not generated' rows.
  const [
    hasStatusCard, hasPendingHooks, hasResourceSchema, hasResourceLedger,
  ] = await Promise.all([
    headOk(SNAPSHOT_BASE + 'current_status_card.md'),
    headOk(SNAPSHOT_BASE + 'pending_hooks.md'),
    headOk(SNAPSHOT_BASE + 'resource_schema.yaml'),
    headOk(SNAPSHOT_BASE + 'resource_ledger.md'),
  ]);
  const bookkeeping = {
    has_status_card: hasStatusCard,
    has_pending_hooks: hasPendingHooks,
    has_resource_schema: hasResourceSchema,
    has_resource_ledger: hasResourceLedger,
  };

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
    bookkeeping,
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
  $('#pill-running').textContent = '快照';
  runPill.classList.remove('pill-running');

  const debtPill = $('#pill-debt').parentElement;
  $('#pill-debt').textContent = s.debt_count;
  debtPill.classList.toggle('pill-debt-hot', s.debt_count > 0);

  $('#pill-calls').textContent = s.prompt_count;

  const badge = $('#tab-debt-count');
  badge.textContent = s.debt_count > 0 ? String(s.debt_count) : '';
}

// Inject the active setting's title + subtitle into the top-bar brand line,
// so the UI reflects whichever setting was bootstrapped (not a hardcoded genre).
function renderBrandSub() {
  const el = document.getElementById('brand-sub');
  if (!el) return;
  const s = state.snapshot;
  const novel = (s && s.novel) || {};
  const parts = [];
  if (novel.title) parts.push(novel.title);
  if (novel.subtitle) parts.push(novel.subtitle);
  parts.push('多智能体小说写作流水线 · 只读快照');
  el.textContent = parts.join(' · ');

  // Page title too
  if (novel.title) {
    document.title = `Blackboard Novel Pipeline · ${novel.title} · 静态演示`;
  }
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
    ['state/setting.yaml',             'setting.yaml',             '◆'],
    ['state/outline.json',             'outline.json',             '•'],
    ['state/progress.json',            'progress.json',            '•'],
    ['state/timeline.yaml',            'timeline.yaml',            '•'],
    ['state/characters.yaml',          'characters.yaml',          '•'],
    ['state/era.md',                   'era.md',                   '◆'],
    ['state/writing-style-extra.md',   'writing-style-extra.md',   '◆'],
    ['state/iron-laws-extra.md',       'iron-laws-extra.md',       '◆'],
    ['state/issues.jsonl',             'issues.jsonl',             '•'],
    ['state/debt.jsonl',               'debt.jsonl',               '•'],
    ['state/prompts_log.jsonl',        'prompts_log.jsonl',        '•'],
  ];
  rootFiles.forEach(([p, name, icon]) => tree.appendChild(treeItem(p, name, icon)));

  // --- bookkeeping/ (Lesson-3 ledgers; may not exist in pre-C-23 snapshots)
  tree.appendChild(sectionHeader('bookkeeping/ (Lesson-3 ledgers)'));
  const bk = (s.bookkeeping || {});
  [
    ['state/current_status_card.md', 'current_status_card.md', '❂', !bk.has_status_card],
    ['state/pending_hooks.md',       'pending_hooks.md',       '⚑', !bk.has_pending_hooks],
    ['state/resource_schema.yaml',   'resource_schema.yaml',   '◆', !bk.has_resource_schema],
    ['state/resource_ledger.md',     'resource_ledger.md',     '⚖', !bk.has_resource_ledger],
  ].forEach(([p, name, icon, missing]) => tree.appendChild(treeItem(p, name, icon, missing)));

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
  tree.appendChild(sectionHeader('rules/ (universal)'));
  [
    ['rules/00-information-priority.md', '00-information-priority.md'],
    ['rules/24-iron-laws.md',            '24-iron-laws.md'],
    ['rules/18-landmines.md',            '18-landmines.md'],
    ['rules/writing-style-core.md',      'writing-style-core.md'],
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
  if (name === 'lessons') {
    if (!state.lessonsRendered) {
      renderLessons();
      state.lessonsRendered = true;
    }
    return;
  }
  renderPrompts();
}

// ---------- LESSONS (static build: every pointer opens GitHub) ----------
function renderLessons() {
  const root = $('#lessons-panel');
  if (!root) return;
  root.innerHTML = '';
  LESSONS.forEach((lesson) => root.appendChild(lessonCard(lesson)));
}

function lessonCard(lesson) {
  return el('div', { class: 'lesson-card', dataset: { n: lesson.n } },
    el('div', { class: 'lesson-card-head' },
      el('div', { class: 'lesson-n' }, `Lesson ${String(lesson.n).padStart(2, '0')}`),
      el('div', { class: `lesson-attr attr-${lesson.attribution_color}` }, lesson.attribution),
    ),
    el('h3', { class: 'lesson-title' }, lesson.title),
    el('div', { class: 'lesson-principle' }, lesson.principle),
    el('div', { class: 'lesson-section-label' }, '本项目落地'),
    el('ul', { class: 'lesson-impl' },
      ...lesson.impl.map((x) => el('li', null, x))),
    el('div', { class: 'lesson-section-label' }, '代码指针'),
    el('ul', { class: 'lesson-pointers' },
      ...lesson.code_pointers.map((p) => el('li', null, renderPointerStatic(p)))),
  );
}

function renderPointerStatic(p) {
  // Static build: always open GitHub. Prefer github_path; fall back to logical_path as a repo path.
  const repoPath = p.github_path || p.logical_path;
  const href = repoPath ? `${REPO_URL}/blob/main/${repoPath}` : '#';
  return el('a', {
    class: 'ptr-link',
    href,
    target: '_blank',
    rel: 'noopener',
    title: `GitHub · ${repoPath || p.label}`,
  },
    el('code', null, p.label),
    el('span', { class: 'ptr-desc' }, p.desc),
    el('span', { class: 'ptr-arrow' }, '↗'),
  );
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
      el('th', null, '章节'),
      el('th', null, '重试次数'),
      el('th', null, '未决'),
      el('th', null, 'Top 未决雷点'),
      el('th', null, '时间'),
    )),
    el('tbody', null,
      ...debt.map((d) => el('tr', null,
        el('td', null, '第 ' + d.chapter + ' 章'),
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
      chapter ? el('span', { class: 'insp-chapter' }, '第 ' + chapter + ' 章') : null,
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
      el('strong', null, '📋 全新上下文 · '),
      promptTokens ? `${promptTokens} 个 prompt tokens, ` : '',
      '无对话历史, 无残留记忆。本次调用从零开始。',
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
    inspSection(p.error ? '错误' : '输出',
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
    el('div', { class: 'insp-section-label' }, '原始元数据'),
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
      el('span', { class: 'log-ch' }, chapter ? '第' + chapter + '章' : '—'),
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

// ---------- demo-setting switcher ----------
// Judges can toggle between gangster-HK-1983 and xianxia-ascension without
// navigating away. Choice persists in localStorage. Missing folders fall back
// to gangster with a toast.
function initDemoSwitcher() {
  const saved = localStorage.getItem('bnp_demo_setting');
  if (saved === 'xianxia') {
    activeDemo = 'xianxia';
    SNAPSHOT_BASE = DEMO_SETTINGS[1].base;
  }
  $$('.demo-switcher button').forEach((btn) => {
    btn.classList.toggle('is-active', btn.dataset.demo === activeDemo);
    btn.addEventListener('click', () => setActiveDemo(btn.dataset.demo));
  });
}

async function setActiveDemo(id) {
  if (id === activeDemo) return;
  const conf = DEMO_SETTINGS.find((d) => d.id === id);
  if (!conf) return;
  activeDemo = id;
  SNAPSHOT_BASE = conf.base;
  localStorage.setItem('bnp_demo_setting', id);
  $$('.demo-switcher button').forEach((btn) => {
    btn.classList.toggle('is-active', btn.dataset.demo === id);
  });
  // Clear all snapshot-scoped state so we don't leak data across settings.
  state.snapshot = null;
  state.prompts = [];
  state.openFile = null;
  state.openPromptIds = new Set();
  state.fileCache = new Map();
  state.existCache = new Map();
  await reloadAfterSwitch();
}

async function reloadAfterSwitch() {
  try {
    state.snapshot = await buildSnapshot();
  } catch (e) {
    // Graceful fallback: if xianxia (or any non-gangster) snapshot can't be
    // loaded, revert to gangster and let the judge see something.
    if (activeDemo !== 'gangster') {
      const missingLabel = DEMO_SETTINGS.find((d) => d.id === activeDemo)?.label || activeDemo;
      toast(`${missingLabel} demo 尚未生成，已切回港综`, false);
      activeDemo = 'gangster';
      SNAPSHOT_BASE = DEMO_SETTINGS[0].base;
      localStorage.setItem('bnp_demo_setting', 'gangster');
      $$('.demo-switcher button').forEach((btn) => {
        btn.classList.toggle('is-active', btn.dataset.demo === 'gangster');
      });
      try {
        state.snapshot = await buildSnapshot();
      } catch (e2) {
        toast('加载失败: ' + e2.message, true);
        return;
      }
    } else {
      toast('加载失败: ' + e.message, true);
      return;
    }
  }
  renderPills();
  renderTree();
  renderPrompts();
  renderBrandSub();
  const produced = state.snapshot.chapters.find((c) => c.has_md);
  if (produced) {
    openFile(`state/chapters/ch${String(produced.ch).padStart(3, '0')}.md`);
  } else {
    // Newly-active demo hasn't produced any chapters — clear the viewer.
    const viewer = $('#viewer');
    if (viewer) {
      viewer.innerHTML = '';
      viewer.appendChild(el('div', { class: 'placeholder' },
        el('div', { class: 'placeholder-mark' }, '◐'),
        el('div', { class: 'placeholder-title' }, '该题材暂无已生成章节'),
        el('div', { class: 'placeholder-sub' }, '请等待流水线跑完, 或切换到其他题材。'),
      ));
    }
    $('#viewer-meta').textContent = '';
  }
}

async function init() {
  wireTabs();
  wireButtons();
  initDemoSwitcher();

  try {
    state.snapshot = await buildSnapshot();
  } catch (e) {
    // First-load fallback: if the persisted xianxia choice can't load, try
    // gangster before giving up entirely.
    if (activeDemo !== 'gangster') {
      const missingLabel = DEMO_SETTINGS.find((d) => d.id === activeDemo)?.label || activeDemo;
      toast(`${missingLabel} demo 尚未生成，已切回港综`, false);
      activeDemo = 'gangster';
      SNAPSHOT_BASE = DEMO_SETTINGS[0].base;
      localStorage.setItem('bnp_demo_setting', 'gangster');
      $$('.demo-switcher button').forEach((btn) => {
        btn.classList.toggle('is-active', btn.dataset.demo === 'gangster');
      });
      try {
        state.snapshot = await buildSnapshot();
      } catch (e2) {
        $('#tree').innerHTML = '';
        $('#tree').appendChild(el('div', { class: 'tree-empty' },
          '无法加载 demo_snapshot/: ' + e2.message));
        toast('加载失败: ' + e2.message, true);
        return;
      }
    } else {
      $('#tree').innerHTML = '';
      $('#tree').appendChild(el('div', { class: 'tree-empty' },
        '无法加载 demo_snapshot/: ' + e.message));
      toast('加载失败: ' + e.message, true);
      return;
    }
  }

  renderPills();
  renderTree();
  renderPrompts();
  renderBrandSub();

  // Auto-open the first produced chapter so judges see content within 2s.
  const produced = state.snapshot.chapters.find((c) => c.has_md);
  if (produced) {
    openFile(`state/chapters/ch${String(produced.ch).padStart(3, '0')}.md`);
  }
}

window.addEventListener('DOMContentLoaded', init);
