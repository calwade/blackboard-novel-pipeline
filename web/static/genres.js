/* =========================================================
   Novelforge · Genre Pipeline — client-side glue
   Minimal vanilla JS: fetch, render, poll. No framework.
   Pairs with web/app.py /api/genres/* endpoints and
   web/templates/genres/*.html views.
   ========================================================= */
(function () {
  'use strict';

  // ---------- tiny helpers ----------
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function el(tag, attrs, children) {
    const n = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === 'class') n.className = attrs[k];
        else if (k === 'text') n.textContent = attrs[k];
        else if (k === 'html') n.innerHTML = attrs[k];
        else if (k.startsWith('on') && typeof attrs[k] === 'function') {
          n.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        } else if (attrs[k] !== undefined && attrs[k] !== null) {
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
    if (!resp.ok || body.ok === false || body.started === false) {
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
  // /genres — index page
  // ========================================================
  async function initIndex() {
    const grid = $('#genre-grid');
    const count = $('#genre-count');
    try {
      const data = await apiCall('/api/genres');
      const genres = data.genres || [];
      count.textContent = genres.length + ' 个题材';
      grid.innerHTML = '';
      if (!genres.length) {
        grid.appendChild(el('div', { class: 'placeholder' }, [
          el('div', { class: 'placeholder-title', text: '还没有题材' }),
          el('div', { class: 'placeholder-sub', text: '点击右上角「新建题材」开始。' }),
        ]));
        return;
      }
      genres.forEach(g => grid.appendChild(renderGenreCard(g)));
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
    if (g.genre) meta.push(el('span', { class: 'genre-chip genre-chip-amber', text: g.genre }));
    if (g.era) meta.push(el('span', { class: 'genre-chip genre-chip-cyan', text: g.era }));
    if (g.tone) meta.push(el('span', { class: 'genre-chip', text: g.tone }));
    meta.push(el('span', { class: 'genre-chip', text: (g.file_count || 0) + ' 份文件' }));
    if (g.has_build_status) {
      meta.push(el('span', { class: 'genre-chip genre-chip-amber', text: '.build/' }));
    }

    const title = g.display_name && g.display_name !== g.id ? g.display_name : g.id;

    const card = el('article', { class: 'genre-card' }, [
      el('div', { class: 'genre-card-id', text: g.id }),
      el('h3', { class: 'genre-card-title', text: title }),
      el('div', { class: 'genre-card-desc', text: describe(g) }),
      el('div', { class: 'genre-card-meta' }, meta),
      el('div', { class: 'genre-card-actions' }, [
        el('a', { class: 'btn', href: '/genres/' + encodeURIComponent(g.id) }, ['查看']),
        el('button', { class: 'btn', onclick: () => runAudit(g.id) }, ['审查']),
        el('button', { class: 'btn btn-danger', onclick: () => confirmDelete(g.id) }, ['删除']),
      ]),
    ]);
    return card;
  }

  function describe(g) {
    // Terse one-liner; avoids empty space if nothing to say.
    const bits = [];
    if (g.genre && g.era) bits.push(g.genre + ' · ' + g.era);
    else if (g.genre) bits.push(g.genre);
    else if (g.era) bits.push(g.era);
    if (g.tone) bits.push(g.tone);
    return bits.join(' / ') || '—';
  }

  async function runAudit(gid) {
    toast('正在审查 ' + gid + ' …');
    try {
      const r = await apiCall('/api/genres/' + encodeURIComponent(gid) + '/audit', { method: 'POST' });
      const msg = `${gid}: ${r.error_count || 0} error · ${r.warning_count || 0} warning`;
      toast(msg, r.error_count ? 'err' : 'ok');
    } catch (e) {
      toast('审查失败: ' + e.message, 'err');
    }
  }

  async function confirmDelete(gid) {
    const ok = window.confirm(`确认删除题材「${gid}」？\n\n此操作不可撤销。如果有作品依赖此题材，将会被拒绝。`);
    if (!ok) return;
    try {
      await apiCall('/api/genres/' + encodeURIComponent(gid), { method: 'DELETE' });
      toast('已删除 ' + gid, 'ok');
      initIndex();
    } catch (e) {
      toast('删除失败: ' + e.message, 'err');
    }
  }

  // ========================================================
  // /genres/new
  // ========================================================
  function initNew() {
    const form = $('#new-genre-form');
    const err = $('#f-error');
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      err.hidden = true;
      const data = {
        id: $('#f-id').value.trim(),
        name: $('#f-name').value.trim(),
        genre: $('#f-genre').value.trim(),
        era: $('#f-era').value.trim(),
        tone: $('#f-tone').value.trim(),
      };
      try {
        const r = await apiCall('/api/genres/new', {
          method: 'POST',
          body: JSON.stringify(data),
        });
        toast('已创建 ' + r.genre_id, 'ok');
        window.location.href = '/genres/' + encodeURIComponent(r.genre_id);
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
      }
    });
  }

  // ========================================================
  // /genres/<id>  — detail
  // ========================================================
  async function initDetail(gid) {
    // Wire up action buttons
    $('#btn-audit').addEventListener('click', async () => {
      const btn = $('#btn-audit'); btn.disabled = true;
      try {
        const r = await apiCall('/api/genres/' + encodeURIComponent(gid) + '/audit', { method: 'POST' });
        toast(`审查完成: ${r.error_count || 0} error · ${r.warning_count || 0} warning`, r.error_count ? 'err' : 'ok');
        loadDetail(gid);
      } catch (e) {
        toast('审查失败: ' + e.message, 'err');
      } finally { btn.disabled = false; }
    });
    $('#btn-fill').addEventListener('click', async () => {
      const btn = $('#btn-fill'); btn.disabled = true;
      try {
        const r = await apiCall('/api/genres/' + encodeURIComponent(gid) + '/fill', { method: 'POST' });
        const n = (r.filled || []).length;
        toast(n ? `补齐了 ${n} 份: ${r.filled.join(', ')}` : '没有缺失文件', 'ok');
        loadDetail(gid);
      } catch (e) {
        toast('补齐失败: ' + e.message, 'err');
      } finally { btn.disabled = false; }
    });
    $('#btn-delete').addEventListener('click', async () => {
      await confirmDelete(gid);
      // If we're still on this page after delete succeeded, bounce home.
      // confirmDelete calls initIndex() on success; on this page initIndex will
      // no-op (no #genre-grid) — so we redirect manually:
      setTimeout(() => {
        // If the genre is gone, detail fetch will now 404 — redirect.
        fetch('/api/genres/' + encodeURIComponent(gid) + '/status')
          .then(r => { if (r.status === 404) window.location.href = '/genres'; });
      }, 200);
    });

    await loadDetail(gid);
  }

  async function loadDetail(gid) {
    // Fetch genre list to find this entry's metadata
    let genreMeta = null;
    try {
      const list = await apiCall('/api/genres');
      genreMeta = (list.genres || []).find(g => g.id === gid);
    } catch (_) {}
    if (genreMeta) {
      $('#gd-title').textContent = genreMeta.display_name || gid;
      const meta = $('#gd-meta');
      meta.innerHTML = '';
      if (genreMeta.genre) meta.appendChild(el('span', { class: 'genre-chip genre-chip-amber', text: genreMeta.genre }));
      if (genreMeta.era) meta.appendChild(el('span', { class: 'genre-chip genre-chip-cyan', text: genreMeta.era }));
      if (genreMeta.tone) meta.appendChild(el('span', { class: 'genre-chip', text: genreMeta.tone }));
    }

    // Fetch file listing via /api/file on each expected file
    const expected = [
      { name: 'genre.yaml', required: true },
      { name: 'era.md', required: true },
      { name: 'writing-style-extra.md', required: true },
      { name: 'iron-laws-extra.md', required: true },
      { name: 'resource_schema.yaml', required: false },
    ];
    const filesEl = $('#gd-files');
    filesEl.innerHTML = '';
    for (const f of expected) {
      // We don't have a generic genre-file read endpoint; just display name.
      // The backend's file_count in /api/genres tells us *whether* they exist,
      // but not per-file. For per-file state, we probe via HEAD on /api/genre-file?
      // Simpler: call /api/genres and infer 4-5 present, then stat individually
      // by attempting /api/genre-files endpoint. To keep scope tight we render
      // just the list with a "tracked" badge.
      filesEl.appendChild(el('li', { class: 'genre-file' }, [
        el('span', { class: 'genre-file-name', text: f.name }),
        el('span', { class: 'genre-file-size', text: f.required ? '必需' : '可选' }),
      ]));
    }

    // Fetch build status + recent issues
    try {
      const status = await apiCall('/api/genres/' + encodeURIComponent(gid) + '/status');
      renderPhases($('#gd-phases'), status.phases || {}, status.has_build);
      renderInflight($('#gd-inflight'), status.in_flight);
      // Issues list — we piggyback on the status endpoint by reading the
      // genre_issues.jsonl via /api/file with the full build path.
      // Keep it simple: render nothing if we can't read it (not all builds
      // have been audited).
    } catch (e) {
      $('#gd-phases').innerHTML = '';
      $('#gd-phases').appendChild(el('div', { class: 'placeholder' }, [
        el('div', { class: 'placeholder-title', text: '暂无构建记录' }),
        el('div', { class: 'placeholder-sub', text: '跑一次审查或拆解会生成 .build/ 目录。' }),
      ]));
    }

    renderIssues($('#gd-issues'), gid);
  }

  function renderPhases(target, phases, hasBuild) {
    target.innerHTML = '';
    if (!hasBuild) {
      target.appendChild(el('div', { class: 'placeholder' }, [
        el('div', { class: 'placeholder-title', text: '暂无构建记录' }),
        el('div', { class: 'placeholder-sub', text: '跑一次审查或拆解会生成 .build/ 目录。' }),
      ]));
      return;
    }
    const order = ['extract', 'merge', 'draft', 'validate'];
    order.forEach(k => {
      const ph = phases[k] || { status: 'pending' };
      const bits = [];
      if (k === 'extract' && ph.batches_total) {
        bits.push(`${ph.batches_done || 0} / ${ph.batches_total} 批`);
      }
      target.appendChild(el('div', { class: 'genre-phase-row' }, [
        el('span', { class: 'genre-phase-row-name', text: k }),
        el('span', { class: 'genre-phase-row-detail', text: bits.join(' · ') || '—' }),
        el('span', { class: 'genre-phase-row-status status-' + (ph.status || 'pending'), text: ph.status || 'pending' }),
      ]));
    });
  }

  function renderInflight(target, inFlight) {
    if (!inFlight) { target.hidden = true; target.textContent = ''; return; }
    target.hidden = false;
    target.innerHTML = '';
    const parts = [inFlight.agent || 'agent'];
    if (inFlight.batch_id != null) parts.push('batch ' + inFlight.batch_id);
    if (inFlight.started_at) parts.push('since ' + inFlight.started_at);
    target.appendChild(document.createTextNode(parts.join(' · ')));
  }

  async function renderIssues(target, gid) {
    target.innerHTML = '';
    try {
      const r = await apiCall('/api/genres/' + encodeURIComponent(gid) + '/issues?limit=10');
      const issues = r.issues || [];
      if (!issues.length) {
        target.appendChild(el('div', { class: 'placeholder' }, [
          el('div', { class: 'placeholder-title', text: '暂无审查问题' }),
          el('div', { class: 'placeholder-sub', text: '跑一次审查会在此显示最新 10 条。' }),
        ]));
        return;
      }
      const header = el('div', { class: 'genre-issues-header', text:
        `最新 ${issues.length} 条 / 共 ${r.total || issues.length} 条` });
      target.appendChild(header);
      issues.forEach(it => {
        const sev = (it.severity || 'info').toLowerCase();
        target.appendChild(el('div', { class: 'genre-issue' }, [
          el('span', { class: 'genre-issue-sev sev-' + sev, text: sev }),
          el('span', { class: 'genre-issue-file', text: it.file || '—' }),
          el('span', { class: 'genre-issue-msg', text: it.message || '' }),
        ]));
      });
    } catch (e) {
      target.appendChild(el('div', { class: 'placeholder' }, [
        el('div', { class: 'placeholder-title', text: '无法读取问题列表' }),
        el('div', { class: 'placeholder-sub', text: e.message }),
      ]));
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  // ========================================================
  // /genres/<id>/extract — form
  // ========================================================
  function initExtract(gid) {
    const form = $('#extract-form');
    const err = $('#f-error');
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      err.hidden = true;
      const sources = $('#f-sources').value
        .split(/\r?\n/)
        .map(s => s.trim())
        .filter(Boolean);
      if (!sources.length) {
        err.textContent = '至少需要一个源文件路径。';
        err.hidden = false;
        return;
      }
      const body = {
        sources: sources,
        with_trial: $('#f-with-trial').checked,
        dry_run: $('#f-dry-run').checked,
      };
      try {
        await apiCall('/api/genres/' + encodeURIComponent(gid) + '/extract', {
          method: 'POST',
          body: JSON.stringify(body),
        });
        window.location.href = '/genres/' + encodeURIComponent(gid) + '/extract/progress';
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
      }
    });
  }

  // ========================================================
  // /genres/<id>/extract/progress — live poll
  // ========================================================
  function initProgress(gid) {
    $('#btn-abort').addEventListener('click', async () => {
      const ok = window.confirm('确认中断当前拆解任务？当前阶段完成后会停下。');
      if (!ok) return;
      try {
        await apiCall('/api/genres/' + encodeURIComponent(gid) + '/abort', { method: 'POST' });
        toast('已发出中断信号，等待下一阶段边界…');
      } catch (e) {
        toast('中断失败: ' + e.message, 'err');
      }
    });
    pollProgress(gid);
  }

  let _progressTimer = null;
  async function pollProgress(gid) {
    try {
      const s = await apiCall('/api/genres/' + encodeURIComponent(gid) + '/status');
      applyProgressState(s);
      const task = s.task || {};
      const phases = s.phases || {};
      const allDone = ['extract', 'merge', 'draft', 'validate']
        .every(k => (phases[k] || {}).status === 'done');
      const done = allDone || task.running === false;
      if (done) {
        renderFinish(s);
        const markEl = document.querySelector('.genre-detail-mark-spin');
        if (markEl) markEl.classList.remove('genre-detail-mark-spin');
        document.querySelector('.genre-detail-title').textContent =
          task.ok === false ? '构建中断 / 失败' : '构建完成';
        $('#btn-abort').hidden = true;
        $('#btn-back').hidden = false;
        return;
      }
    } catch (e) {
      // transient failure — keep polling
      console.warn('poll error', e);
    }
    _progressTimer = setTimeout(() => pollProgress(gid), 3000);
  }

  function applyProgressState(s) {
    const phases = s.phases || {};
    const order = ['extract', 'merge', 'draft', 'validate'];
    let activeSeen = false;
    order.forEach(k => {
      const ph = phases[k] || { status: 'pending' };
      const row = document.querySelector('.phase[data-phase="' + k + '"]');
      if (!row) return;
      row.classList.remove('phase-active', 'phase-done');
      if (ph.status === 'done') row.classList.add('phase-done');
      else if (ph.status === 'in_progress') { row.classList.add('phase-active'); activeSeen = true; }

      // progress bar width
      const fill = row.querySelector('.phase-bar-fill');
      let pct = 0;
      if (ph.status === 'done') pct = 100;
      else if (ph.status === 'in_progress') {
        if (k === 'extract' && ph.batches_total) {
          pct = Math.max(6, Math.round(100 * (ph.batches_done || 0) / ph.batches_total));
        } else {
          pct = 40;  // indeterminate-ish
        }
      }
      fill.style.width = pct + '%';

      // detail text
      const detail = row.querySelector('.phase-detail');
      if (k === 'extract' && ph.batches_total) {
        detail.textContent = `${ph.batches_done || 0} / ${ph.batches_total} 批` +
          (ph.last_batch_id ? ` · last batch ${ph.last_batch_id}` : '');
      } else {
        detail.textContent = ph.status || 'pending';
      }
    });

    // In-flight card
    const inflight = s.in_flight;
    const box = $('#gp-inflight');
    if (inflight) {
      box.hidden = false;
      $('#gp-agent').textContent = inflight.agent || 'agent';
      const bits = [];
      if (inflight.batch_id != null) bits.push('batch #' + inflight.batch_id);
      if (inflight.started_at) bits.push('started ' + inflight.started_at);
      $('#gp-agent-meta').textContent = bits.join(' · ');
    } else {
      box.hidden = true;
    }

    // Top meta
    const task = s.task || {};
    const metaBits = [];
    if (task.dry_run) metaBits.push('dry_run');
    if (task.with_trial) metaBits.push('with_trial');
    if (task.started_at) {
      const d = new Date(task.started_at * 1000);
      metaBits.push('起 ' + d.toLocaleTimeString());
    }
    if (!activeSeen && task.running === false) metaBits.push('空闲');
    $('#gp-meta').textContent = metaBits.join(' · ') || '—';
  }

  function renderFinish(s) {
    const box = $('#gp-finish');
    box.innerHTML = '';
    const task = s.task || {};
    if (task.ok === false && task.error) {
      box.appendChild(el('div', { class: 'finish-err' }, [
        el('strong', { text: task.error === 'aborted' ? '⏹ 已中断' : '✕ 失败' }),
        el('br'),
        document.createTextNode(task.error === 'aborted' ? '在下一阶段边界停下。' : task.error),
      ]));
    } else {
      box.appendChild(el('div', { class: 'finish-ok', text: '✓ 构建完成 — 4 阶段全部 done' }));
    }
  }

  // Expose
  window.GenreUI = {
    initIndex: initIndex,
    initNew: initNew,
    initDetail: initDetail,
    initExtract: initExtract,
    initProgress: initProgress,
  };
})();
