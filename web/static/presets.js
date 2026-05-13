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
    // Align with css/components/toast.css: .is-show / .is-error
    const errKind = kind === 'err' || kind === 'error';
    t.className = 'toast is-show' + (errKind ? ' is-error' : '');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.className = 'toast'; }, 3400);
  }

  // ========================================================
  // /presets — index page
  // ========================================================
  async function initIndex() {
    const grid = $('#genre-grid');
    if (!grid) return;
    try {
      const data = await apiCall('/api/presets');
      const presets = data.presets || data.genres || [];
      grid.innerHTML = '';
      if (!presets.length) {
        grid.appendChild(el('div', { class: 'placeholder' }, [
          el('div', { class: 'placeholder-title', text: '还没有 preset' }),
          el('div', { class: 'placeholder-sub', html: '点击右上角 <code>+ 新建 preset</code> 开始。' }),
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

  // Card uses .project-card base (card.css) + .preset-card modifier.
  // Clicking the card navigates to detail; the footer delete button
  // (non-builtin only) stops propagation.
  function renderGenreCard(g) {
    const title = g.display_name && g.display_name !== g.id ? g.display_name : g.id;
    const href = '/presets/' + encodeURIComponent(g.id);

    const tags = el('div', { class: 'project-card-meta' }, [
      g.builtin
        ? el('span', { class: 'project-card-tag', text: '内置' })
        : null,
      g.tone ? el('span', { class: 'project-card-tag', text: g.tone }) : null,
    ].filter(Boolean));

    const footChildren = [
      el('span', { class: 'preset-card-id', text: g.id }),
    ];
    if (!g.builtin) {
      footChildren.push(el('button', {
        class: 'btn btn-icon-del',
        title: '删除此 preset',
        onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); confirmDelete(g.id); },
      }, ['✕']));
    }

    return el('a', {
      class: 'project-card preset-card',
      href: href,
      style: 'text-decoration:none;',
    }, [
      el('div', { class: 'preset-card-title', text: title }),
      tags,
      el('div', { class: 'preset-card-foot' }, footChildren),
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
        if (meta.builtin) {
          metaEl.appendChild(el('span', { class: 'project-card-tag is-active', text: '内置' }));
        }
        if (meta.tone) {
          metaEl.appendChild(el('span', { class: 'project-card-tag', text: meta.tone, style: 'margin-left:6px;' }));
        }
      }
    } catch (_) { /* fall through */ }

    // Pull the detail — files + novels + builtin
    const filesEl = $('#gd-files');
    const novelsEl = $('#gd-novels');
    try {
      const d = await apiCall('/api/presets/' + encodeURIComponent(pid));
      filesEl.innerHTML = '';
      if (!(d.files || []).length) {
        filesEl.appendChild(el('li', { class: 'is-empty', text: '（目录为空）' }));
      } else {
        d.files.forEach(name => {
          filesEl.appendChild(el('li', { text: name }));
        });
      }

      novelsEl.innerHTML = '';
      if (!(d.novels || []).length) {
        novelsEl.appendChild(el('li', { class: 'is-empty', text: '（没有绑定的原著文件）' }));
      } else {
        d.novels.forEach(name => {
          novelsEl.appendChild(el('li', { text: name }));
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
      filesEl.appendChild(el('li', { class: 'is-empty', text: '加载失败: ' + e.message }));
      novelsEl.innerHTML = '';
    }
  }

  // ======================================================
  // /presets/new · 3-tab page
  // ======================================================

  function initNewPage() {
    // Tab switching — relies on the shared .tab/.tab-active vocabulary
    // from css/components/tabs.css; container class is .tabs-subpage.
    const tabs = document.querySelectorAll('.tabs-subpage .tab');
    const panels = document.querySelectorAll('[data-panel]');
    tabs.forEach(t => t.addEventListener('click', () => {
      tabs.forEach(x => {
        const active = x === t;
        x.classList.toggle('tab-active', active);
        x.setAttribute('aria-selected', active ? 'true' : 'false');
      });
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
    // Load novels pool into picker-body — rows use the .preset-picker-row
    // shape (css/pages/presets.css). Toggle .is-checked on the row for
    // the amber highlight.
    fetch('/api/novels').then(r => r.json()).then(data => {
      const body = document.getElementById('picker-body');
      const summary = document.getElementById('picker-summary');
      body.innerHTML = '';
      const novels = (data && data.novels) || [];
      summary.textContent = novels.length + ' 份素材';
      if (!novels.length) {
        const empty = document.createElement('div');
        empty.className = 'placeholder';
        empty.style.minHeight = '120px';
        empty.style.padding = '24px';
        empty.innerHTML = '<div class="placeholder-title">素材库为空</div>'
          + '<div class="placeholder-sub">去 <a href="/novels">素材库</a> 上传 .txt</div>';
        body.appendChild(empty);
        return;
      }
      for (const n of novels) {
        const lbl = document.createElement('label');
        lbl.className = 'preset-picker-row';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.name = 'source';
        cb.value = n.name;
        const text = document.createElement('span');
        text.textContent = n.name;
        lbl.appendChild(cb);
        lbl.appendChild(text);
        body.appendChild(lbl);
      }
      body.addEventListener('change', (ev) => {
        // Visual state
        if (ev.target && ev.target.name === 'source') {
          const row = ev.target.closest('.preset-picker-row');
          if (row) row.classList.toggle('is-checked', ev.target.checked);
        }
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

  // 4-bar phase order. Mirrors _PHASES in web/app.py.
  const PHASES = ['extract', 'merge', 'draft', 'validate'];

  function renderPhaseTimeline(root, phase) {
    if (!root) return;
    const curIdx = PHASES.indexOf(phase);
    PHASES.forEach((ph, i) => {
      const li = root.querySelector(`li[data-phase="${ph}"]`);
      if (!li) return;
      li.classList.toggle('is-done', curIdx === -1 ? false : i < curIdx);
      li.classList.toggle('is-active', i === curIdx);
    });
  }

  function ensureTimeline(box) {
    // Inject a 4-bar timeline + abort button into the progress box if the
    // template didn't ship with one. Keeps the presets page forward-compat
    // with older templates while letting new templates supply their own.
    let timeline = box.querySelector('[data-phase-timeline]');
    if (timeline) return { timeline, abortBtn: box.querySelector('[data-phase-abort]') };
    timeline = document.createElement('ol');
    timeline.className = 'phase-timeline phase-timeline-compact';
    timeline.setAttribute('data-phase-timeline', '');
    PHASES.forEach((ph) => {
      const label = ph.charAt(0).toUpperCase() + ph.slice(1);
      const li = document.createElement('li');
      li.setAttribute('data-phase', ph);
      li.innerHTML = `<span class="phase-name">${label}</span><span class="phase-bar"><span class="phase-bar-fill"></span></span>`;
      timeline.appendChild(li);
    });
    box.appendChild(timeline);
    const abortBtn = document.createElement('button');
    abortBtn.type = 'button';
    // No .btn-danger/.btn-sm in main components; use default .btn + inline size.
    abortBtn.className = 'btn';
    abortBtn.style.padding = '4px 10px';
    abortBtn.style.fontSize = '11px';
    abortBtn.style.marginLeft = '10px';
    abortBtn.textContent = '⏹ 中断';
    abortBtn.setAttribute('data-phase-abort', '');
    abortBtn.hidden = true;
    box.appendChild(abortBtn);
    return { timeline, abortBtn };
  }

  async function pollPresetJob(pid) {
    const box = document.getElementById('progress-box');
    const title = document.getElementById('progress-title');
    const detail = document.getElementById('progress-detail');
    if (box) box.hidden = false;
    if (title) title.textContent = '正在处理：' + pid;
    const parts = box ? ensureTimeline(box) : { timeline: null, abortBtn: null };
    const { timeline, abortBtn } = parts;

    let userAborted = false;
    if (abortBtn) {
      abortBtn.hidden = false;
      abortBtn.onclick = async () => {
        userAborted = true;
        abortBtn.disabled = true;
        // Preset abort endpoint: for symmetry, presets also reuse the
        // project-scoped abort if available; otherwise we just stop
        // polling (the filesystem is the source of truth anyway).
        try {
          await fetch(`/api/presets/${encodeURIComponent(pid)}/abort`, { method: 'POST' });
        } catch (_) { /* no-op: endpoint may not exist */ }
        if (title) title.textContent = '已请求中断：' + pid;
      };
    }

    const POLL_MS = 1000;
    // No hard iteration cap — long extractions are legitimate.
    while (true) {
      if (userAborted) return;
      try {
        const r = await fetch(`/api/presets/${pid}/status`);
        const s = await r.json();
        if (s.phase) renderPhaseTimeline(timeline, s.phase);
        if (detail) {
          if (s.phase) {
            detail.textContent = `${s.phase}${s.progress ? ' · ' + s.progress : ''}`;
          } else if (s.state === 'running') {
            detail.textContent = '启动中…';
          }
        }
        if (s.state === 'done') {
          if (timeline) {
            timeline.querySelectorAll('li').forEach((li) => {
              li.classList.remove('is-active');
              li.classList.add('is-done');
            });
          }
          location.href = '/presets/' + pid;
          return;
        }
        if (s.state === 'failed' || s.state === 'aborted' || s.state === 'unknown') {
          if (title) title.textContent = (s.state === 'aborted' ? '已中止' : '失败') + '：' + (s.error || s.state);
          if (abortBtn) abortBtn.hidden = true;
          return;
        }
      } catch (e) {
        console.warn('poll error', e);
      }
      await new Promise((res) => setTimeout(res, POLL_MS));
    }
  }

  // Expose
  window.GenreUI = {
    initIndex: initIndex,
    initDetail: initDetail,
    initNewPage: initNewPage,
  };
})();
