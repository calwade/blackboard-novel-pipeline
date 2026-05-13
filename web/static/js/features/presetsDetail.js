/* =========================================================
   presetsDetail.js — /presets/<id> detail page.
   Wires:
     GET    /api/presets           · summary (display_name / tone)
     GET    /api/presets/<id>      · files + novels + builtin
     DELETE /api/presets/<id>      · delete (non-builtin only)

   The preset id is read from the page-head `data-preset-id` attribute.
   ========================================================= */

import { $, el } from '../utils.js';
import { apiCall, toast } from '../api.js';

async function confirmDelete(pid) {
  const ok = window.confirm(
    `确认删除题材「${pid}」？\n\n此操作不可撤销。如果有作品依赖此题材，可能会报错。`
  );
  if (!ok) return;
  try {
    await apiCall('/api/presets/' + encodeURIComponent(pid), { method: 'DELETE' });
    toast('已删除 ' + pid);
    window.location.href = '/presets';
  } catch (e) {
    toast('删除失败: ' + e.message, true);
  }
}

async function loadDetail(pid) {
  // Pull the summary (list) entry to get display_name / tone
  try {
    const list = await apiCall('/api/presets');
    const presets = list.presets || list.genres || [];
    const meta = presets.find(g => g.id === pid);
    if (meta) {
      const titleEl = $('#gd-title');
      if (titleEl) titleEl.textContent = meta.display_name || pid;
      const metaEl = $('#gd-meta');
      if (metaEl) {
        metaEl.innerHTML = '';
        if (meta.builtin) {
          metaEl.appendChild(el('span', { class: 'project-card-tag is-active' }, '内置'));
        }
        if (meta.tone) {
          metaEl.appendChild(el('span', {
            class: 'project-card-tag',
            style: 'margin-left:6px;',
          }, meta.tone));
        }
      }
    }
  } catch (_) { /* fall through */ }

  // Pull the detail — files + novels + builtin
  const filesEl = $('#gd-files');
  const novelsEl = $('#gd-novels');
  try {
    const d = await apiCall('/api/presets/' + encodeURIComponent(pid));
    if (filesEl) {
      filesEl.innerHTML = '';
      if (!(d.files || []).length) {
        filesEl.appendChild(el('li', { class: 'is-empty' }, '（目录为空）'));
      } else {
        d.files.forEach(name => {
          filesEl.appendChild(el('li', {}, name));
        });
      }
    }

    if (novelsEl) {
      novelsEl.innerHTML = '';
      if (!(d.novels || []).length) {
        novelsEl.appendChild(el('li', { class: 'is-empty' }, '（没有绑定的原著文件）'));
      } else {
        d.novels.forEach(name => {
          novelsEl.appendChild(el('li', {}, name));
        });
      }
    }

    // Enable delete only for non-builtin
    const del = $('#btn-delete');
    if (del && !d.builtin) {
      del.disabled = false;
      del.title = '删除这个题材';
    } else if (del) {
      del.disabled = true;
      del.title = '内置题材不可删除';
    }
  } catch (e) {
    if (filesEl) {
      filesEl.innerHTML = '';
      filesEl.appendChild(el('li', { class: 'is-empty' }, '加载失败: ' + e.message));
    }
    if (novelsEl) novelsEl.innerHTML = '';
  }
}

export async function initDetail() {
  // The preset id is exposed via the page-head `data-preset-id` attr.
  const head = document.querySelector('[data-preset-id]');
  const pid = head ? head.getAttribute('data-preset-id') : null;
  if (!pid) return;

  const delBtn = $('#btn-delete');
  if (delBtn) {
    delBtn.addEventListener('click', () => confirmDelete(pid));
  }
  await loadDetail(pid);
}

// Auto-boot on DOM ready.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initDetail);
} else {
  initDetail();
}
