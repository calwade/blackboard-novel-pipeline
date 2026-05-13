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

  // ========================================================
  // /presets — inline "新 preset from novel" form
  // ========================================================
  function initNewFromNovel() {
    const form = $('#new-from-novel-form');
    if (!form) return;

    const state = {
      novels: [],
      selected: new Set(),
    };

    // Load novels for picker
    loadNovels(state, updateSubmitState);

    $('#f-new-id').addEventListener('input', updateSubmitState);

    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const err = $('#f-error');
      err.hidden = true;
      const pid = $('#f-new-id').value.trim();
      const sources = Array.from(state.selected).map(n => 'novels/' + n);
      if (!pid) {
        err.textContent = '请输入新题材 id';
        err.hidden = false;
        return;
      }
      if (!sources.length) {
        err.textContent = '至少勾选一个原著文件';
        err.hidden = false;
        return;
      }
      const body = {
        id: pid,
        sources: sources,
        with_trial: $('#f-with-trial').checked,
      };
      try {
        await apiCall('/api/presets/new-from-novel', {
          method: 'POST',
          body: JSON.stringify(body),
        });
        showProgress(pid);
        pollJobStatus(pid);
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
      }
    });

    function updateSubmitState() {
      const btn = $('#btn-submit');
      const label = $('#submit-label');
      const pid = $('#f-new-id').value.trim();
      const count = state.selected.size;
      const enabled = !!pid && count > 0;
      btn.disabled = !enabled;
      label.textContent = count > 0 ? `启动拆解 · ${count} 个素材` : '启动拆解';
    }

    async function loadNovels(state, onChange) {
      const body = $('#picker-body');
      const summary = $('#picker-summary');
      try {
        const data = await apiCall('/api/novels');
        state.novels = data.novels || [];
        renderPicker(state, onChange);
      } catch (e) {
        body.innerHTML = '';
        body.appendChild(el('div', { class: 'placeholder' }, [
          el('div', { class: 'placeholder-title', text: '加载 /api/novels 失败' }),
          el('div', { class: 'placeholder-sub', text: e.message }),
        ]));
        summary.textContent = '—';
      }
    }

    function renderPicker(state, onChange) {
      const body = $('#picker-body');
      const summary = $('#picker-summary');
      body.innerHTML = '';
      if (!state.novels.length) {
        summary.textContent = '素材库为空';
        body.appendChild(el('div', { class: 'placeholder' }, [
          el('div', { class: 'placeholder-title', text: '素材库为空' }),
          el('div', { class: 'placeholder-sub', html:
            '请先去 <a href="/novels" target="_blank" rel="noopener">素材库</a> 上传小说文件。' }),
        ]));
        onChange();
        return;
      }
      summary.textContent = `${state.novels.length} 个素材 · 已选 ${state.selected.size}`;

      state.novels.forEach(n => {
        const checked = state.selected.has(n.name);
        const row = el('label', {
          class: 'novel-pick' + (checked ? ' is-checked' : ''),
        }, [
          el('input', {
            type: 'checkbox',
            class: 'novel-checkbox',
            'data-name': n.name,
            checked: checked ? 'checked' : null,
            onchange: (e) => {
              if (e.target.checked) state.selected.add(n.name);
              else state.selected.delete(n.name);
              row.classList.toggle('is-checked', e.target.checked);
              summary.textContent = `${state.novels.length} 个素材 · 已选 ${state.selected.size}`;
              onChange();
            },
          }),
          el('span', { class: 'novel-pick-box' }),
          el('div', { class: 'novel-pick-main' }, [
            el('div', { class: 'novel-pick-name', text: n.name }),
            el('div', { class: 'novel-pick-meta' }, [
              el('span', { text: n.size_human || '' }),
            ]),
          ]),
        ]);
        body.appendChild(row);
      });
      onChange();
    }
  }

  function showProgress(pid) {
    const box = $('#progress-box');
    if (!box) return;
    box.hidden = false;
    $('#progress-title').textContent = `拆解中 · ${pid}`;
    $('#progress-detail').textContent = '已提交，后台运行中…';
    $('#btn-submit').disabled = true;
  }

  async function pollJobStatus(pid) {
    try {
      const s = await apiCall('/api/presets/' + encodeURIComponent(pid) + '/status');
      const detail = $('#progress-detail');
      if (!detail) return;
      if (s.state === 'done') {
        $('#progress-title').textContent = `✓ 完成 · ${pid}`;
        detail.innerHTML = '';
        detail.appendChild(document.createTextNode('拆解完成 — '));
        detail.appendChild(el('a', { href: '/presets/' + encodeURIComponent(pid), text: '查看题材 →' }));
        toast('拆解完成: ' + pid, 'ok');
        return;
      }
      if (s.state === 'failed') {
        $('#progress-title').textContent = `✕ 失败 · ${pid}`;
        detail.textContent = s.error || '（无错误信息）';
        toast('拆解失败: ' + pid, 'err');
        return;
      }
      detail.textContent = s.state === 'running' ? '运行中…' : ('状态: ' + s.state);
    } catch (e) {
      console.warn('status poll error', e);
    }
    setTimeout(() => pollJobStatus(pid), 3000);
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
    initNewFromNovel: initNewFromNovel,
    initNewPage: initNewPage,
  };
})();
