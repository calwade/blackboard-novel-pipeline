/* =========================================================
   presetsList.js — /presets index page.
   Wires:
     GET    /api/presets           · list
     DELETE /api/presets/<id>      · delete (non-builtin only)
   ========================================================= */

import { $, el } from '../utils.js';
import { apiCall, toast } from '../api.js';

// Card uses .project-card base (card.css) + .preset-card modifier.
// Clicking the card navigates to detail; the footer delete button
// (non-builtin only) stops propagation.
function renderGenreCard(g) {
  const title = g.display_name && g.display_name !== g.id ? g.display_name : g.id;
  const href = '/presets/' + encodeURIComponent(g.id);

  const tagChildren = [
    g.builtin ? el('span', { class: 'project-card-tag' }, '内置') : null,
    g.tone ? el('span', { class: 'project-card-tag' }, g.tone) : null,
  ].filter(Boolean);
  const tags = el('div', { class: 'project-card-meta' }, ...tagChildren);

  const footChildren = [
    el('span', { class: 'preset-card-id' }, g.id),
  ];
  if (!g.builtin) {
    footChildren.push(
      el('button', {
        class: 'btn btn-icon-del',
        title: '删除此 preset',
        onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); confirmDelete(g.id); },
      }, '✕')
    );
  }

  return el('a', {
    class: 'project-card preset-card',
    href,
    style: 'text-decoration:none;',
  },
    el('div', { class: 'preset-card-title' }, title),
    tags,
    el('div', { class: 'preset-card-foot' }, ...footChildren),
  );
}

async function confirmDelete(pid) {
  const ok = window.confirm(
    `确认删除题材「${pid}」？\n\n此操作不可撤销。如果有作品依赖此题材，可能会报错。`
  );
  if (!ok) return;
  try {
    await apiCall('/api/presets/' + encodeURIComponent(pid), { method: 'DELETE' });
    toast('已删除 ' + pid);
    if ($('#genre-grid')) initList();
    else window.location.href = '/presets';
  } catch (e) {
    toast('删除失败: ' + e.message, true);
  }
}

export async function initList() {
  const grid = $('#genre-grid');
  if (!grid) return;
  try {
    const data = await apiCall('/api/presets');
    const presets = data.presets || data.genres || [];
    grid.innerHTML = '';
    if (!presets.length) {
      grid.appendChild(el('div', { class: 'placeholder' },
        el('div', { class: 'placeholder-title' }, '还没有 preset'),
        (() => {
          const sub = el('div', { class: 'placeholder-sub' });
          sub.innerHTML = '点击右上角 <code>+ 新建 preset</code> 开始。';
          return sub;
        })(),
      ));
      return;
    }
    presets.forEach(g => grid.appendChild(renderGenreCard(g)));
  } catch (e) {
    grid.innerHTML = '';
    grid.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '加载失败'),
      el('div', { class: 'placeholder-sub' }, e.message),
    ));
  }
}

// Auto-boot on DOM ready.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initList);
} else {
  initList();
}
