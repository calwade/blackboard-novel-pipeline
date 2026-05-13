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
