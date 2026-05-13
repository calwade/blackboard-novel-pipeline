/* =========================================================
   ui/viewer.js — center-panel file viewer.
   openFile() is the entrypoint; renders the file as markdown /
   syntax-highlighted JSON / plain text into the appropriate pane
   and flips the center tab if needed.
   ========================================================= */

import { $, $$, el, fmtBytes, escapeHtml } from '../utils.js';
import { api } from '../api.js';
import { state } from '../state.js';
import { setCenterTab } from './tabs.js';

export async function openFile(path) {
  state.openFile = path;
  // mark active
  $$('.tree-item').forEach((n) => n.classList.toggle('is-active', n.dataset.path === path));

  // 虚拟路径分派：
  //   __preset__/<id>  → 调 /api/presets/<id>，渲染 preset 详情卡
  //   __novel__/<name> → 调 /api/novels/<name>/preview，渲染 txt 头部
  if (path.startsWith('__preset__/')) {
    return openPresetDetail(path.slice('__preset__/'.length));
  }
  if (path.startsWith('__novel__/')) {
    return openNovelPreview(path.slice('__novel__/'.length));
  }

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
    let url;
    if (state.view === 'genre' && state.genreJobId) {
      url = '/api/genre-file?job=' + encodeURIComponent(state.genreJobId)
          + '&path=' + encodeURIComponent(path);
    } else {
      url = '/api/file?path=' + encodeURIComponent(path);
    }
    const res = await api(url);
    renderViewer(viewerRoot, res);
    $('#viewer-meta').textContent = `${path}  ·  ${fmtBytes(res.size)}`;
  } catch (e) {
    viewerRoot.innerHTML = '';
    viewerRoot.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '无法加载'),
      el('div', { class: 'placeholder-sub' }, String(e.message))));
  }
}


async function openPresetDetail(presetId) {
  setCenterTab('chapter');
  const root = $('#viewer');
  root.innerHTML = '<div class="placeholder"><div class="placeholder-title">加载中…</div></div>';
  $('#viewer-meta').textContent = `preset: ${presetId}`;
  try {
    const detail = await api('/api/presets/' + encodeURIComponent(presetId));
    root.innerHTML = '';
    const card = el('article', { class: 'viewer preset-detail-card' });

    // 标题条
    card.appendChild(el('h1', {},
      detail.builtin ? '◆ ' : '◇ ',
      presetId,
      detail.builtin ? el('span', { class: 'preset-badge' }, '内置') : null,
    ));

    // 文件清单
    card.appendChild(el('h2', {}, '文件'));
    const filesList = el('ul', { class: 'preset-file-list' });
    (detail.files || []).forEach((fname) => {
      const li = el('li', {},
        el('a', {
          href: '#',
          onclick: (ev) => {
            ev.preventDefault();
            // 切到该 preset 的 job 视图若存在，否则提示
            // 这里简单实现：直接 open 该 preset 目录下的同名文件（需要一个 job 存在）
            // 更好的体验：切到"当前任务"并定位；此版本只是预览路径
            openFileInPresetDir(presetId, fname);
          },
        }, fname),
      );
      filesList.appendChild(li);
    });
    card.appendChild(filesList);

    // 素材来源
    if (detail.novels && detail.novels.length) {
      card.appendChild(el('h2', {}, '拆解来源 · novels/'));
      const novelsList = el('ul', { class: 'preset-file-list' });
      detail.novels.forEach((n) => {
        novelsList.appendChild(el('li', {}, n));
      });
      card.appendChild(novelsList);
    }

    // 操作区
    const actions = el('div', { class: 'preset-detail-actions' });
    actions.appendChild(el('a', { class: 'btn btn-ghost', href: `/presets/${presetId}` }, '→ 打开题材库独立页'));
    if (!detail.builtin) {
      actions.appendChild(el('button', {
        class: 'btn btn-ghost',
        onclick: () => deletePreset(presetId),
      }, '✕ 删除'));
    }
    card.appendChild(actions);

    root.appendChild(card);
  } catch (e) {
    root.innerHTML = '';
    root.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '无法加载 preset'),
      el('div', { class: 'placeholder-sub' }, String(e.message))));
  }
}


async function openFileInPresetDir(presetId, fname) {
  // 读 presets/<id>/<fname> 作为独立文件预览（复用 /api/file 的 "presets/" 路径白名单）
  setCenterTab('chapter');
  const viewerRoot = $('#viewer');
  viewerRoot.innerHTML = '<div class="placeholder"><div class="placeholder-title">加载中…</div></div>';
  const rel = `presets/${presetId}/${fname}`;
  $('#viewer-meta').textContent = rel;
  try {
    const res = await api('/api/file?path=' + encodeURIComponent(rel));
    renderViewer(viewerRoot, res);
    $('#viewer-meta').textContent = `${rel}  ·  ${fmtBytes(res.size)}`;
  } catch (e) {
    viewerRoot.innerHTML = '';
    viewerRoot.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '无法加载'),
      el('div', { class: 'placeholder-sub' }, String(e.message))));
  }
}


async function deletePreset(presetId) {
  if (!confirm(`删除 preset "${presetId}"？此操作不可撤销。`)) return;
  try {
    const r = await fetch('/api/presets/' + encodeURIComponent(presetId), { method: 'DELETE' });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert('删除失败：' + (err.reason || r.status));
      return;
    }
    // 刷新题材库列表
    state.genreListCache.presets = null;
    state.openFile = null;
    const tree = $('#tree');
    tree.innerHTML = '';
    const { renderTree } = await import('./tree.js');
    renderTree();
    // 中间 viewer 重置
    $('#viewer').innerHTML = '<div class="placeholder"><div class="placeholder-title">已删除</div></div>';
    $('#viewer-meta').textContent = '';
  } catch (e) {
    alert('删除失败：' + e.message);
  }
}


async function openNovelPreview(name) {
  setCenterTab('chapter');
  const root = $('#viewer');
  root.innerHTML = '<div class="placeholder"><div class="placeholder-title">加载预览…</div></div>';
  $('#viewer-meta').textContent = `novel: ${name}`;
  try {
    const r = await fetch('/api/novels/' + encodeURIComponent(name) + '/preview');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    root.innerHTML = '';
    const card = el('article', { class: 'viewer' });
    card.appendChild(el('h1', {}, `📄 ${name}`));
    const meta = el('div', { class: 'novel-preview-meta' });
    // /api/novels/<name>/preview 返回 {head, name, truncated}；
    // 但 /api/novels 列表返回 size_bytes / estimated_chapters / encoding_ok。
    // 这里两种字段都兼容显示。
    const sizeBytes = data.size_bytes ?? data.size;
    if (sizeBytes != null) meta.appendChild(el('span', {}, `大小: ${fmtBytes(sizeBytes)}`));
    const chapters = data.estimated_chapters ?? data.chapter_count;
    if (chapters != null) meta.appendChild(el('span', {}, `  ·  章节: ${chapters}`));
    if (data.encoding) meta.appendChild(el('span', {}, `  ·  编码: ${data.encoding}`));
    if (data.truncated) meta.appendChild(el('span', {}, `  ·  （仅开头片段）`));
    card.appendChild(meta);
    // /api/novels/<name>/preview 返回的是 {head, name, truncated}；
    // 兼容可能的 preview/content 字段写法
    const body = data.head || data.preview || data.content || '';
    if (body) {
      card.appendChild(el('h2', {}, '开头预览'));
      const pre = el('pre', { class: 'viewer-source' });
      pre.textContent = body;
      card.appendChild(pre);
    }
    // 操作
    const actions = el('div', { class: 'preset-detail-actions' });
    actions.appendChild(el('a', { class: 'btn btn-ghost', href: '/novels' }, '→ 打开素材库独立页'));
    card.appendChild(actions);
    root.appendChild(card);
  } catch (e) {
    root.innerHTML = '';
    root.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '无法加载预览'),
      el('div', { class: 'placeholder-sub' }, String(e.message))));
  }
}

export function renderViewer(root, file) {
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

export function highlightJson(text, jsonl) {
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
