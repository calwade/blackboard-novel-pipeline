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
import { renderGenreTree } from './genreTree.js';

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

  // -------- 保存展开状态（按稳定 key 收集，rebuild 后恢复） --------
  // bug fix: 之前 polling 每 2-4 秒重建 DOM 把 is-open 全清掉，
  // 用户感受为"展开后过几秒缩回去"。
  // 用 data-tree-key 作稳定标识符（chapter:N / section:title），
  // rebuild 后按 key 恢复 is-open 状态。
  const openKeys = new Set();
  tree.querySelectorAll('[data-tree-key].is-open').forEach((node) => {
    openKeys.add(node.getAttribute('data-tree-key'));
  });

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
  tree.appendChild(sectionHeader('chapters/', { defaultOpen: true, key: 'section:chapters' }, openKeys));
  const chWrap = el('div', { class: 'tree-group-items' });
  s.chapters.forEach((ch) => {
    const produced = [
      ch.has_plan, ch.has_md, ch.has_verdict,
      ch.has_summary, ch.has_slop_patch, ch.has_char_patch,
    ].filter(Boolean).length;
    const total = 6;
    const groupKey = `chapter:${ch.ch}`;
    const label = el('div', {
      class: 'tree-group-label',
      onclick: (e) => toggleGroup(e.currentTarget),
      dataset: { treeKey: groupKey },
    },
      el('span', { class: 'tree-caret' }, ICONS.caret),
      el('span', { class: 'tree-group-name' }, `ch${String(ch.ch).padStart(3, '0')}  ${ch.title.replace(/^第[一二三四五六七八九十]+章\s*·\s*/, '')}`),
      el('span', { class: 'tree-group-count' }, `${produced}/${total}`),
    );
    // Auto-open: 当前章默认展开；其他章按用户上次手动展开状态恢复
    const userOpened = openKeys.has(groupKey);
    const openDefault = ch.ch === currentChapter || userOpened;
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
  tree.appendChild(sectionHeader('bookkeeping/ · Lesson-3 ledgers', { defaultOpen: true, key: 'section:bookkeeping' }, openKeys));
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
  tree.appendChild(sectionHeader('state/ · 题材事实', { defaultOpen: true, key: 'section:genre-facts' }, openKeys));
  GENRE_FACTS.forEach(([p, name, icon]) => tree.appendChild(treeItem(p, name, icon)));

  // -------------------------------------------------------
  // 4) state/ · 运行时 meta — logs + bootstrap artifacts
  // -------------------------------------------------------
  tree.appendChild(sectionHeader('state/ · 运行时 meta', { defaultOpen: true, key: 'section:runtime-meta' }, openKeys));
  RUNTIME_META.forEach(([p, name, icon]) => tree.appendChild(treeItem(p, name, icon)));

  // -------------------------------------------------------
  // 5) rules/ — universal Progressive Disclosure set
  // -------------------------------------------------------
  const rulesKey = 'section:rules';
  const rulesOpen = openKeys.has(rulesKey);
  tree.appendChild(sectionHeader('rules/ · universal', { defaultOpen: false, key: rulesKey }, openKeys));
  const rulesWrap = el('div', { class: 'tree-section-items', 'data-collapsible-items': '' });
  [
    ['rules/00-information-priority.md', '00-information-priority.md'],
    ['rules/iron-laws.md',               'iron-laws.md'],
    ['rules/landmines.md',               'landmines.md'],
    ['rules/writing-style-core.md',      'writing-style-core.md'],
    ['rules/writing-iron-laws.md',       'writing-iron-laws.md'],
    ['rules/ai-rhythm-taboos.md',        'ai-rhythm-taboos.md'],
  ].forEach(([p, name]) => rulesWrap.appendChild(treeItem(p, name, ICONS.section)));
  rulesWrap.style.display = rulesOpen ? '' : 'none';
  tree.appendChild(rulesWrap);

  // -------------------------------------------------------
  // 6) project/ — repo-level pinned docs
  // -------------------------------------------------------
  const projKey = 'section:project';
  const projOpen = openKeys.has(projKey);
  tree.appendChild(sectionHeader('project/', { defaultOpen: false, key: projKey }, openKeys));
  const projWrap = el('div', { class: 'tree-section-items', 'data-collapsible-items': '' });
  projWrap.appendChild(treeItem('AGENTS.md', 'AGENTS.md', ICONS.pinned));
  projWrap.style.display = projOpen ? '' : 'none';
  tree.appendChild(projWrap);
}

/**
 * Render a section divider. When `collapsible` is truthy, clicking
 * the header toggles the immediately-following sibling container
 * (the `data-collapsible-items` wrapper). Non-collapsible sections
 * render their items directly and ignore the click.
 *
 * 第 3 个参数 openKeys 是当前已展开的 key 集合（来自上次 render 前的快照），
 * 用于让用户手动展开过的 section 在重建后保持展开。
 */
function sectionHeader(title, opts = {}, openKeys = null) {
  const { defaultOpen = true, key = null } = opts;
  // 优先级：用户已展开 > defaultOpen
  const userOpened = key && openKeys && openKeys.has(key);
  const isOpen = userOpened || defaultOpen;
  const hdr = el('div', {
    class: 'tree-section-header' + (isOpen ? ' is-open' : ''),
    onclick: (e) => toggleSection(e.currentTarget),
    dataset: key ? { treeKey: key } : {},
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


