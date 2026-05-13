/* =========================================================
   ui/tree.js — left-column file tree.
   renderTree() rebuilds the tree on every /api/state poll.

   Lane B Task #1: section order re-architected so the left
   column reads top-to-bottom in the order an author actually
   works through it:

     1. chapters/     — the work itself (current chapter auto-open)
     2. bookkeeping/  — Lesson-3 authoritative snapshot
     3. state/ · 题材事实   — genre fact packs (rarely edited)
     4. state/ · 运行时 meta — outline / progress / logs
     5. rules/        — universal Progressive Disclosure set
     6. project/      — repo-level pinned docs

   Previously the 11 "runtime meta" files were piled at the
   top, burying the chapter list. That inverted the attention
   pyramid: you had to scroll past log files to reach the work.

   Lane B Task #7: all JS-rendered glyphs go through the ICONS
   table so the visual vocabulary can shift in one file.
   ========================================================= */

import { $, el } from '../utils.js';
import { state } from '../state.js';
import { openFile } from './viewer.js';
import { ICONS } from '../icons.js';

// File lists extracted to module-level constants so the reorder
// intent is scannable without diving into renderTree().
const GENRE_FACTS = [
  // (path-in-state, display-name, icon, missingKey?)
  ['state/era.md',                 'era.md',                 ICONS.setting],
  ['state/writing-style-extra.md', 'writing-style-extra.md', ICONS.setting],
  ['state/iron-laws-extra.md',     'iron-laws-extra.md',     ICONS.setting],
  // resource_schema.yaml is optional — it shows up only when the book
  // provides one, so we let the bookkeeping flag tell us whether to
  // render it at all (handled inline below).
];

const RUNTIME_META = [
  ['state/setting.yaml',      'setting.yaml',      ICONS.setting],
  ['state/outline.json',      'outline.json',      ICONS.meta],
  ['state/progress.json',     'progress.json',     ICONS.meta],
  ['state/timeline.yaml',     'timeline.yaml',     ICONS.meta],
  ['state/characters.yaml',   'characters.yaml',   ICONS.meta],
  ['state/issues.jsonl',      'issues.jsonl',      ICONS.meta],
  ['state/debt.jsonl',        'debt.jsonl',        ICONS.meta],
  ['state/prompts_log.jsonl', 'prompts_log.jsonl', ICONS.meta],
];

export function renderTree() {
  const s = state.snapshot;
  if (!s) return;
  const tree = $('#tree');
  tree.innerHTML = '';

  // -------------------------------------------------------
  // Genre view: flat list from /api/genre-state 返回的 files 数组
  // -------------------------------------------------------
  if (state.view === 'genre') {
    renderGenreTree(tree, s);
    return;
  }

  const bk = s.bookkeeping || {};
  const currentChapter = (s.progress && s.progress.current_chapter) || 1;

  // -------------------------------------------------------
  // 1) chapters/ — the work itself; most-visited section
  // -------------------------------------------------------
  tree.appendChild(sectionHeader('chapters/', { defaultOpen: true }));
  const chWrap = el('div', { class: 'tree-group-items' });
  s.chapters.forEach((ch) => {
    const produced = [
      ch.has_plan, ch.has_md, ch.has_verdict,
      ch.has_summary, ch.has_slop_patch, ch.has_char_patch,
    ].filter(Boolean).length;
    const total = 6;
    const label = el('div', { class: 'tree-group-label', onclick: (e) => toggleGroup(e.currentTarget) },
      el('span', { class: 'tree-caret' }, ICONS.caret),
      el('span', { class: 'tree-group-name' }, `ch${String(ch.ch).padStart(3, '0')}  ${ch.title.replace(/^第[一二三四五六七八九十]+章\s*·\s*/, '')}`),
      el('span', { class: 'tree-group-count' }, `${produced}/${total}`),
    );
    // Auto-open only the current chapter. Previously every chapter with
    // an `.md` on disk was expanded, which created a 12-group wall of
    // text once you were past chapter 10.
    const openDefault = ch.ch === currentChapter;
    if (openDefault) label.classList.add('is-open');

    const items = el('div', { class: 'tree-items', style: openDefault ? '' : 'display:none' },
      treeItem(`state/chapters/ch${String(ch.ch).padStart(3, '0')}.plan.json`,    'plan.json',    ICONS.plan,      !ch.has_plan),
      treeItem(`state/chapters/ch${String(ch.ch).padStart(3, '0')}.md`,           'chapter.md',   ICONS.chapter,   !ch.has_md),
      treeItem(`state/chapters/ch${String(ch.ch).padStart(3, '0')}.verdict.json`, 'verdict.json', ICONS.weigh,     !ch.has_verdict),
      treeItem(`state/summaries/ch${String(ch.ch).padStart(3, '0')}.md`,          'summary.md',   ICONS.summary,   !ch.has_summary),
      treeItem(`state/fixes/ch${String(ch.ch).padStart(3, '0')}.slop-patch.md`,   'slop-patch.md',ICONS.slop,      !ch.has_slop_patch),
      treeItem(`state/fixes/ch${String(ch.ch).padStart(3, '0')}.char-patch.md`,   'char-patch.md',ICONS.charGuard, !ch.has_char_patch),
    );
    const group = el('div', { class: 'tree-group' }, label, items);
    chWrap.appendChild(group);
  });
  tree.appendChild(chWrap);

  // -------------------------------------------------------
  // 2) bookkeeping/ — Lesson-3 Context-Reset authority
  // -------------------------------------------------------
  tree.appendChild(sectionHeader('bookkeeping/ · Lesson-3 ledgers', { defaultOpen: true }));
  [
    ['state/current_status_card.md', 'current_status_card.md', ICONS.status,  !bk.has_status_card],
    ['state/pending_hooks.md',       'pending_hooks.md',       ICONS.hook,    !bk.has_pending_hooks],
    // resource_schema.yaml + resource_ledger.md only render when the
    // book supplies a schema; for urban-romance etc. they stay hidden
    // rather than show as greyed "missing" rows.
    ...(bk.has_resource_schema ? [
      ['state/resource_schema.yaml', 'resource_schema.yaml', ICONS.setting, false],
      ['state/resource_ledger.md',   'resource_ledger.md',   ICONS.weigh,   !bk.has_resource_ledger],
    ] : []),
  ].forEach(([p, name, icon, missing]) => tree.appendChild(treeItem(p, name, icon, missing)));

  // -------------------------------------------------------
  // 3) state/ · 题材事实  — genre fact packs (edit rarely)
  // -------------------------------------------------------
  tree.appendChild(sectionHeader('state/ · 题材事实', { defaultOpen: true }));
  GENRE_FACTS.forEach(([p, name, icon]) => tree.appendChild(treeItem(p, name, icon)));

  // -------------------------------------------------------
  // 4) state/ · 运行时 meta — logs + bootstrap artifacts
  // -------------------------------------------------------
  tree.appendChild(sectionHeader('state/ · 运行时 meta', { defaultOpen: true }));
  RUNTIME_META.forEach(([p, name, icon]) => tree.appendChild(treeItem(p, name, icon)));

  // -------------------------------------------------------
  // 5) rules/ — universal Progressive Disclosure set
  // -------------------------------------------------------
  tree.appendChild(sectionHeader('rules/ · universal', { defaultOpen: false }));
  const rulesWrap = el('div', { class: 'tree-section-items', 'data-collapsible-items': '' });
  [
    ['rules/00-information-priority.md', '00-information-priority.md'],
    ['rules/24-iron-laws.md',            '24-iron-laws.md'],
    ['rules/18-landmines.md',            '18-landmines.md'],
    ['rules/writing-style-core.md',      'writing-style-core.md'],
  ].forEach(([p, name]) => rulesWrap.appendChild(treeItem(p, name, ICONS.section)));
  rulesWrap.style.display = 'none';
  tree.appendChild(rulesWrap);

  // -------------------------------------------------------
  // 6) project/ — repo-level pinned docs
  // -------------------------------------------------------
  tree.appendChild(sectionHeader('project/', { defaultOpen: false }));
  const projWrap = el('div', { class: 'tree-section-items', 'data-collapsible-items': '' });
  projWrap.appendChild(treeItem('AGENTS.md', 'AGENTS.md', ICONS.pinned));
  projWrap.style.display = 'none';
  tree.appendChild(projWrap);
}

/**
 * Render a section divider. When `collapsible` is truthy, clicking
 * the header toggles the immediately-following sibling container
 * (the `data-collapsible-items` wrapper). Non-collapsible sections
 * render their items directly and ignore the click.
 */
function sectionHeader(title, opts = {}) {
  const { defaultOpen = true } = opts;
  const hdr = el('div', {
    class: 'tree-section-header' + (defaultOpen ? ' is-open' : ''),
    onclick: (e) => toggleSection(e.currentTarget),
  }, title);
  return hdr;
}

function toggleSection(hdrEl) {
  hdrEl.classList.toggle('is-open');
  // Only affects sections that render into a sibling container
  // marked with [data-collapsible-items]. Non-collapsible sections
  // (which render items directly as next siblings) are untouched.
  const next = hdrEl.nextElementSibling;
  if (next && next.hasAttribute && next.hasAttribute('data-collapsible-items')) {
    next.style.display = hdrEl.classList.contains('is-open') ? '' : 'none';
  }
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


/**
 * Render the genre-view tree from /api/genre-state response.
 *
 * Shape: {job, files:[{path, kind, size}, ...], counters, progress}
 *   kind='final'  → 题材包最终产物（era.md / writing-style-extra.md 等）
 *   kind='build'  → .build/* 过程产物
 *
 * 按两段展示：先"题材产物"（作者关心的），后".build/"（过程追溯）。
 */
function renderGenreTree(tree, s) {
  const job = s.job || {};
  const files = s.files || [];
  const counters = s.counters || {};

  // 任务元信息条
  const meta = el('div', { class: 'tree-section-header is-open' },
    `job · ${job.kind || '?'}`);
  tree.appendChild(meta);
  const metaWrap = el('div', { class: 'tree-section-items' });
  metaWrap.appendChild(el('div', { class: 'tree-item' },
    el('span', { class: 'tree-item-icon' }, '●'),
    el('span', { class: 'tree-item-name' },
      `${stateLabel(job.state)}  ·  ${job.progress_text || job.phase || ''}`),
  ));
  metaWrap.appendChild(el('div', { class: 'tree-item' },
    el('span', { class: 'tree-item-icon' }, '◆'),
    el('span', { class: 'tree-item-name' },
      `target: ${(job.target && job.target.type) || '?'}:${(job.target && job.target.id) || '?'}`),
  ));
  metaWrap.appendChild(el('div', { class: 'tree-item' },
    el('span', { class: 'tree-item-icon' }, '◆'),
    el('span', { class: 'tree-item-name' },
      `batches: ${counters.batches_done || 0}  ·  arcs: ${counters.arcs_done || 0}  ·  issues: ${counters.issues || 0}`),
  ));
  tree.appendChild(metaWrap);

  // 1) 最终产物（作者关心的）
  const finalFiles = files.filter((f) => f.kind === 'final');
  tree.appendChild(el('div', { class: 'tree-section-header is-open' }, '题材包 · 最终产物'));
  if (finalFiles.length === 0) {
    tree.appendChild(el('div', { class: 'tree-item is-missing' },
      el('span', { class: 'tree-item-icon' }, '○'),
      el('span', { class: 'tree-item-name' }, '（尚未生成）'),
    ));
  } else {
    finalFiles.forEach((f) => tree.appendChild(
      genreTreeItem(f.path, f.path, iconForPath(f.path), false, f.size),
    ));
  }

  // 2) .build/ 过程产物，按目录分组
  const buildFiles = files.filter((f) => f.kind === 'build');
  tree.appendChild(el('div', { class: 'tree-section-header is-open' },
    `.build/ · 过程产物  (${buildFiles.length})`));
  // 按前缀分桶
  const buckets = new Map();
  buildFiles.forEach((f) => {
    // 去掉 ".build/" 前缀，取第一段作为 bucket（否则 root 直出）
    const rel = f.path.replace(/^\.build\//, '');
    const parts = rel.split('/');
    const bucket = parts.length > 1 ? parts[0] + '/' : '(root)';
    if (!buckets.has(bucket)) buckets.set(bucket, []);
    buckets.get(bucket).push(f);
  });
  for (const [bucket, items] of buckets) {
    const label = el('div', { class: 'tree-group-label is-open',
      onclick: (e) => toggleGroup(e.currentTarget) },
      el('span', { class: 'tree-caret' }, ICONS.caret),
      el('span', { class: 'tree-group-name' }, bucket),
      el('span', { class: 'tree-group-count' }, String(items.length)),
    );
    const body = el('div', { class: 'tree-items' });
    items.forEach((f) => {
      const name = f.path.replace(/^\.build\//, '').replace(new RegExp('^' + bucket), '');
      body.appendChild(genreTreeItem(f.path, name || f.path, iconForPath(f.path), false, f.size));
    });
    tree.appendChild(el('div', { class: 'tree-group' }, label, body));
  }
}


function genreTreeItem(path, name, icon, missing, size) {
  const node = el('div', {
    class: 'tree-item' + (missing ? ' is-missing' : '') + (state.openFile === path ? ' is-active' : ''),
    dataset: { path },
    title: `${path} · ${size || 0} bytes`,
    onclick: missing ? null : () => openFile(path),
  },
    el('span', { class: 'tree-item-icon' }, icon),
    el('span', { class: 'tree-item-name' }, name),
  );
  return node;
}


function iconForPath(path) {
  if (path.endsWith('.md')) return ICONS.chapter || '◆';
  if (path.endsWith('.yaml') || path.endsWith('.yml')) return ICONS.setting || '◆';
  if (path.endsWith('.jsonl')) return ICONS.meta || '•';
  if (path.endsWith('.json')) return ICONS.meta || '•';
  return '◦';
}


function stateLabel(s) {
  return {
    running: '运行中',
    aborting: '中止中',
    done: '已完成',
    failed: '失败',
    aborted: '已中止',
    interrupted: '已中断',
  }[s] || s || '—';
}
