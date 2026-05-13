/* =========================================================
   Novelforge · Preset Pipeline — client-side glue
   Minimal vanilla JS: fetch, render, poll. No framework.
   Pairs with web/app.py /api/presets/* endpoints and
   web/templates/presets/*.html views.

   Phase 5 cleanup: only wires endpoints that actually exist:
     GET  /api/presets                  · list
     GET  /api/presets/<id>             · files + novels + builtin
     DELETE /api/presets/<id>           · delete (non-builtin)
     POST /api/presets/new-from-novel   · kick off extraction
     GET  /api/presets/<id>/status      · poll extraction job
   ========================================================= */
(function () {
  'use strict';

  // ---------- tiny helpers ----------
  function $(sel, root) { return (root || document).querySelector(sel); }

  function el(tag, attrs, children) {
    const n = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === 'class') n.className = attrs[k];
        else if (k === 'text') n.textContent = attrs[k];
        else if (k === 'html') n.innerHTML = attrs[k];
        else if (k.startsWith('on') && typeof attrs[k] === 'function') {
          n.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        } else if (attrs[k] !== undefined && attrs[k] !== null && attrs[k] !== false) {
          n.setAttribute(k, attrs[k]);
        }
      }
    }
    (children || []).forEach(c => c && n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
    return n;
  }

  async function apiCall(path, opts) {
    opts = opts || {};
    const headers = opts.headers || {};
    if (opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const resp = await fetch(path, Object.assign({}, opts, { headers: headers }));
    let body = {};
    try { body = await resp.json(); } catch (_) {}
    if (!resp.ok || body.ok === false) {
      const reason = body.reason || body.detail || body.error || ('HTTP ' + resp.status);
      const err = new Error(reason);
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  function toast(msg, kind) {
    const t = $('#toast');
    if (!t) return;
    t.textContent = msg;
    t.className = 'toast toast-show' + (kind ? ' toast-' + kind : '');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.className = 'toast'; }, 3400);
  }

  // ========================================================
  // /presets — index page
  // ========================================================
  async function initIndex() {
    const grid = $('#genre-grid');
    const count = $('#genre-count');
    if (!grid) return;
    try {
      const data = await apiCall('/api/presets');
      const presets = data.presets || data.genres || [];
      if (count) count.textContent = presets.length + ' 个题材';
      grid.innerHTML = '';
      if (!presets.length) {
        grid.appendChild(el('div', { class: 'placeholder' }, [
          el('div', { class: 'placeholder-title', text: '还没有题材' }),
          el('div', { class: 'placeholder-sub', text: '用下方的「从原著拆出新 preset」开始。' }),
        ]));
        return;
      }
      presets.forEach(g => grid.appendChild(renderGenreCard(g)));
    } catch (e) {
      grid.innerHTML = '';
      grid.appendChild(el('div', { class: 'placeholder' }, [
        el('div', { class: 'placeholder-title', text: '加载失败' }),
        el('div', { class: 'placeholder-sub', text: e.message }),
      ]));
    }
  }

  function renderGenreCard(g) {
    const meta = [];
    if (g.tone) meta.push(el('span', { class: 'genre-chip', text: g.tone }));
    if (g.builtin) meta.push(el('span', { class: 'genre-chip genre-chip-amber', text: '内置' }));

    const title = g.display_name && g.display_name !== g.id ? g.display_name : g.id;

    const actions = [
      el('a', { class: 'btn', href: '/presets/' + encodeURIComponent(g.id) }, ['查看']),
    ];
    if (!g.builtin) {
      actions.push(el('button', {
        class: 'btn btn-danger',
        onclick: () => confirmDelete(g.id),
      }, ['删除']));
    }

    return el('article', { class: 'genre-card' }, [
      el('div', { class: 'genre-card-id', text: g.id }),
      el('h3', { class: 'genre-card-title', text: title }),
      el('div', { class: 'genre-card-meta' }, meta),
      el('div', { class: 'genre-card-actions' }, actions),
    ]);
  }

  async function confirmDelete(pid) {
    const ok = window.confirm(
      `确认删除题材「${pid}」？\n\n此操作不可撤销。如果有作品依赖此题材，可能会报错。`
    );
    if (!ok) return;
    try {
      await apiCall('/api/presets/' + encodeURIComponent(pid), { method: 'DELETE' });
      toast('已删除 ' + pid, 'ok');
      if ($('#genre-grid')) initIndex();
      else window.location.href = '/presets';
    } catch (e) {
      toast('删除失败: ' + e.message, 'err');
    }
  }

  // ========================================================
  // /presets/<id>  — detail
  // ========================================================
  async function initDetail(pid) {
    const delBtn = $('#btn-delete');
    if (delBtn) {
      delBtn.addEventListener('click', () => confirmDelete(pid));
    }
    await loadDetail(pid);
  }

  async function loadDetail(pid) {
    // Pull the summary (list) entry to get display_name / tone
    try {
      const list = await apiCall('/api/presets');
      const presets = list.presets || list.genres || [];
      const meta = presets.find(g => g.id === pid);
      if (meta) {
        $('#gd-title').textContent = meta.display_name || pid;
        const metaEl = $('#gd-meta');
        metaEl.innerHTML = '';
        if (meta.tone) metaEl.appendChild(el('span', { class: 'genre-chip', text: meta.tone }));
        if (meta.builtin) metaEl.appendChild(el('span', { class: 'genre-chip genre-chip-amber', text: '内置' }));
      }
    } catch (_) { /* fall through */ }

    // Pull the detail — files + novels + builtin
    const filesEl = $('#gd-files');
    const novelsEl = $('#gd-novels');
    try {
      const d = await apiCall('/api/presets/' + encodeURIComponent(pid));
      filesEl.innerHTML = '';
      if (!(d.files || []).length) {
        filesEl.appendChild(el('li', { class: 'placeholder', text: '（目录为空）' }));
      } else {
        d.files.forEach(name => {
          filesEl.appendChild(el('li', { class: 'genre-file' }, [
            el('span', { class: 'genre-file-name', text: name }),
          ]));
        });
      }

      novelsEl.innerHTML = '';
      if (!(d.novels || []).length) {
        novelsEl.appendChild(el('li', { class: 'placeholder', text: '（没有绑定的原著文件）' }));
      } else {
        d.novels.forEach(name => {
          novelsEl.appendChild(el('li', { class: 'genre-file' }, [
            el('span', { class: 'genre-file-name', text: name }),
          ]));
        });
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
      filesEl.innerHTML = '';
      filesEl.appendChild(el('li', { class: 'placeholder', text: '加载失败: ' + e.message }));
      novelsEl.innerHTML = '';
    }
  }

  // ======================================================
  // /presets/new · 3-tab page
  // ======================================================

  function initNewPage() {
    // Tab switching
    const tabs = document.querySelectorAll('.tabs-preset-new .tab');
    const panels = document.querySelectorAll('[data-panel]');
    tabs.forEach(t => t.addEventListener('click', () => {
      tabs.forEach(x => x.classList.toggle('tab-active', x === t));
      const active = t.dataset.tab;
      panels.forEach(p => p.hidden = p.dataset.panel !== active);
    }));

    initFromNovelForm();
    initFromDescriptionForm();
    initBlankForm();
  }

  function initFromNovelForm() {
    const form = document.getElementById('form-from-novel');
    if (!form) return;
    // Load novels pool into picker-body
    fetch('/api/novels').then(r => r.json()).then(data => {
      const body = document.getElementById('picker-body');
      const summary = document.getElementById('picker-summary');
      body.innerHTML = '';
      const novels = (data && data.novels) || [];
      summary.textContent = novels.length + ' 份素材';
      for (const n of novels) {
        const lbl = document.createElement('label');
        lbl.className = 'check-line';
        lbl.innerHTML = `<input type="checkbox" name="source" value="${n.name}"> ${n.name}`;
        body.appendChild(lbl);
      }
      // Enable submit when >=1 checked
      body.addEventListener('change', () => {
        const checked = body.querySelectorAll('input[name=source]:checked').length;
        document.getElementById('fn-submit').disabled = checked === 0;
      });
    }).catch(() => {
      const summary = document.getElementById('picker-summary');
      if (summary) summary.textContent = '加载素材库失败';
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const sources = fd.getAll('source');
      const payload = {
        id: fd.get('id'),
        sources,
        with_trial: fd.get('with_trial') === 'on',
      };
      const err = document.getElementById('fn-error');
      err.hidden = true;
      try {
        const r = await fetch('/api/presets/new-from-novel', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        if (r.status === 202) {
          const data = await r.json();
          pollPresetJob(data.preset_id);
        } else {
          const d = await r.json();
          err.textContent = d.reason || r.status;
          err.hidden = false;
        }
      } catch (ex) {
        err.textContent = String(ex);
        err.hidden = false;
      }
    });
  }

  function initFromDescriptionForm() {
    const form = document.getElementById('form-from-description');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const payload = {
        id: fd.get('id'),
        display_name: fd.get('display_name'),
        tone: fd.get('tone') || '',
        description: fd.get('description'),
      };
      const err = document.getElementById('fd-error');
      err.hidden = true;
      try {
        const r = await fetch('/api/presets/new-from-description', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        if (r.status === 202) {
          const data = await r.json();
          pollPresetJob(data.preset_id);
        } else {
          const d = await r.json();
          err.textContent = d.reason || r.status;
          err.hidden = false;
        }
      } catch (ex) {
        err.textContent = String(ex);
        err.hidden = false;
      }
    });
  }

  function initBlankForm() {
    const form = document.getElementById('form-blank');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const payload = {
        id: fd.get('id'),
        display_name: fd.get('display_name'),
        tone: fd.get('tone') || '',
      };
      const err = document.getElementById('fb-error');
      err.hidden = true;
      try {
        const r = await fetch('/api/presets/new-blank', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        if (r.ok) {
          const data = await r.json();
          location.href = '/presets/' + data.preset_id;
        } else {
          const d = await r.json();
          err.textContent = d.reason || r.status;
          err.hidden = false;
        }
      } catch (ex) {
        err.textContent = String(ex);
        err.hidden = false;
      }
    });
  }

  async function pollPresetJob(pid) {
    const box = document.getElementById('progress-box');
    const title = document.getElementById('progress-title');
    if (box) box.hidden = false;
    if (title) title.textContent = '正在处理：' + pid;
    for (let i = 0; i < 600; i++) {
      try {
        const r = await fetch(`/api/presets/${pid}/status`);
        const s = await r.json();
        if (s.state === 'done') {
          location.href = '/presets/' + pid;
          return;
        }
        if (s.state === 'failed') {
          if (title) title.textContent = '失败：' + (s.error || '');
          return;
        }
      } catch (e) {
        console.warn('poll error', e);
      }
      await new Promise(res => setTimeout(res, 1000));
    }
  }

  // Expose
  window.GenreUI = {
    initIndex: initIndex,
    initDetail: initDetail,
    initNewPage: initNewPage,
  };
})();
