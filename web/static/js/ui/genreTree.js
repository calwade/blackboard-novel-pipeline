/* =========================================================
   ui/genreTree.js — 题材视图左侧树（从 tree.js 拆出）
   3 个 tab：当前任务 / 题材库 / 素材库。
   tab 切换不触发 pollState；仅本地重绘 #tree。
   ========================================================= */

import { $, el } from '../utils.js';
import { state } from '../state.js';
import { openFile } from './viewer.js';
import { ICONS } from '../icons.js';

// 外部入口：由 tree.js::renderTree() 在 view==='genre' 时调用
export function renderGenreTree(tree, s) {
  // Tab bar（复用 .tabs 组件词汇表：见 components/tabs.css）
  const tabBar = el('div', { class: 'tabs tree-tabs', role: 'tablist' });
  const tabs = [
    ['job',     '◉ 当前任务'],
    ['presets', '❖ 题材库'],
    ['novels',  '📚 素材库'],
  ];
  tabs.forEach(([key, label]) => {
    const active = state.genreLeftTab === key;
    const btn = el('button', {
      class: 'tab' + (active ? ' tab-active' : ''),
      role: 'tab',
      type: 'button',
      'aria-selected': active ? 'true' : 'false',
      'data-genre-tab': key,
      onclick: () => switchGenreLeftTab(key),
    }, label);
    tabBar.appendChild(btn);
  });
  tree.appendChild(tabBar);

  const body = el('div', { class: 'tree-tab-body' });
  tree.appendChild(body);

  if (state.genreLeftTab === 'job') {
    renderJobTab(body, s);
  } else if (state.genreLeftTab === 'presets') {
    renderPresetsTab(body);
  } else if (state.genreLeftTab === 'novels') {
    renderNovelsTab(body);
  }
}


function switchGenreLeftTab(key) {
  state.genreLeftTab = key;
  const tree = $('#tree');
  tree.innerHTML = '';
  renderGenreTree(tree, state.snapshot || {});
}


// ---------- Tab 1 · 当前任务 ----------
function renderJobTab(container, s) {
  const job = s.job || {};
  const files = s.files || [];
  const counters = s.counters || {};

  if (!s.job) {
    container.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '未选中任务'),
      el('div', { class: 'placeholder-sub' }, '顶栏下拉切换任务，或到题材库新建一个'),
    ));
    return;
  }

  // 元信息
  const meta = el('div', { class: 'tree-section-header is-open' }, `job · ${job.kind || '?'}`);
  container.appendChild(meta);
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
  container.appendChild(metaWrap);

  // 最终产物
  const finalFiles = files.filter((f) => f.kind === 'final');
  container.appendChild(el('div', { class: 'tree-section-header is-open' }, '题材包 · 最终产物'));
  if (finalFiles.length === 0) {
    container.appendChild(el('div', { class: 'tree-item is-missing' },
      el('span', { class: 'tree-item-icon' }, '○'),
      el('span', { class: 'tree-item-name' }, '（尚未生成）'),
    ));
  } else {
    finalFiles.forEach((f) => container.appendChild(
      genreTreeItem(f.path, f.path, iconForPath(f.path), false, f.size),
    ));
  }

  // .build/ 过程产物
  const buildFiles = files.filter((f) => f.kind === 'build');
  container.appendChild(el('div', { class: 'tree-section-header is-open' },
    `.build/ · 过程产物  (${buildFiles.length})`));
  const buckets = new Map();
  buildFiles.forEach((f) => {
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
    container.appendChild(el('div', { class: 'tree-group' }, label, body));
  }
}


// ---------- Tab 2 · 题材库 ----------
function renderPresetsTab(container) {
  const cached = state.genreListCache.presets;
  if (cached) {
    _paintPresetsList(container, cached);
  } else {
    container.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '加载题材库…')));
  }
  fetch('/api/presets').then((r) => r.json()).then((data) => {
    const presets = data.presets || [];
    state.genreListCache.presets = presets;
    container.innerHTML = '';
    _paintPresetsList(container, presets);
  }).catch((e) => {
    container.innerHTML = '';
    container.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '加载失败'),
      el('div', { class: 'placeholder-sub' }, String(e.message || e))));
  });
}


function _paintPresetsList(container, presets) {
  container.appendChild(el('div', { class: 'tree-section-header is-open' },
    `题材库  (${presets.length})`));
  if (presets.length === 0) {
    container.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '还没有 preset'),
      el('div', { class: 'placeholder-sub' }, '顶栏点 "+ 新建题材" 开始')));
    return;
  }
  presets.forEach((p) => {
    const virtualPath = `__preset__/${p.id}`;
    const label = (p.display_name && p.display_name !== p.id)
      ? `${p.display_name}  ·  ${p.id}` : p.id;
    const icon = p.builtin ? '◆' : '◇';
    container.appendChild(el('div', {
      class: 'tree-item' + (state.openFile === virtualPath ? ' is-active' : ''),
      dataset: { path: virtualPath },
      title: p.builtin ? `${p.id} · 内置 preset` : p.id,
      onclick: () => openFile(virtualPath),
    },
      el('span', { class: 'tree-item-icon' }, icon),
      el('span', { class: 'tree-item-name' }, label),
    ));
  });
}


// ---------- Tab 3 · 素材库 ----------
function renderNovelsTab(container) {
  const cached = state.genreListCache.novels;
  if (cached) {
    _paintNovelsList(container, cached);
  } else {
    container.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '加载素材库…')));
  }
  fetch('/api/novels').then((r) => r.json()).then((data) => {
    const novels = data.novels || [];
    state.genreListCache.novels = novels;
    container.innerHTML = '';
    _paintNovelsList(container, novels);
  }).catch((e) => {
    container.innerHTML = '';
    container.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '加载失败'),
      el('div', { class: 'placeholder-sub' }, String(e.message || e))));
  });
}


function _paintNovelsList(container, novels) {
  container.appendChild(el('div', { class: 'tree-section-header is-open' },
    `素材库  (${novels.length})`));
  if (novels.length === 0) {
    container.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '素材库为空'),
      el('div', { class: 'placeholder-sub' }, '到 /novels 上传 txt 文件')));
    return;
  }
  novels.forEach((n) => {
    const name = n.name || n;
    // /api/novels 返回字段：size_bytes / size_human / estimated_chapters / used_by_presets
    const sizeLabel = n.size_human || (n.size ? `${Math.round(n.size / 1024)}K` : '');
    const chapters = n.estimated_chapters;
    const sub = chapters ? `${sizeLabel}  ·  ${chapters}章` : sizeLabel;
    const virtualPath = `__novel__/${name}`;
    container.appendChild(el('div', {
      class: 'tree-item' + (state.openFile === virtualPath ? ' is-active' : ''),
      dataset: { path: virtualPath },
      title: `${name}${sub ? ' · ' + sub : ''}`,
      onclick: () => openFile(virtualPath),
    },
      el('span', { class: 'tree-item-icon' }, '📄'),
      el('span', { class: 'tree-item-name' }, name),
      el('span', { class: 'tree-group-count' }, sub),
    ));
  });
}


// ---------- 辅助（原 tree.js 的私有，genre 这边需要的那几个）----------

function genreTreeItem(path, name, icon, missing, size) {
  return el('div', {
    class: 'tree-item' + (missing ? ' is-missing' : '') + (state.openFile === path ? ' is-active' : ''),
    dataset: { path },
    title: `${path} · ${size || 0} bytes`,
    onclick: missing ? null : () => openFile(path),
  },
    el('span', { class: 'tree-item-icon' }, icon),
    el('span', { class: 'tree-item-name' }, name),
  );
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
    running: '运行中', aborting: '中止中', done: '已完成',
    failed: '失败', aborted: '已中止', interrupted: '已中断',
  }[s] || s || '—';
}


// 与 tree.js 里同名函数保持行为一致（label 的 is-open class 切换 + 兄弟 items 折叠）
function toggleGroup(labelEl) {
  labelEl.classList.toggle('is-open');
  const items = labelEl.nextElementSibling;
  if (items) items.style.display = labelEl.classList.contains('is-open') ? '' : 'none';
}
