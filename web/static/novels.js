/* =========================================================
   Novelforge · Novels library — client glue
   Drag-drop upload · per-file progress · table · preview drawer
   ========================================================= */
(function () {
  'use strict';

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
        } else if (attrs[k] !== null && attrs[k] !== undefined) {
          n.setAttribute(k, attrs[k]);
        }
      }
    }
    (children || []).forEach(c => c && n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
    return n;
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

  function humanSize(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    return (n / 1024 / 1024 / 1024).toFixed(1) + ' GB';
  }

  function formatChip(fmt) {
    // Visual weight tells the user at a glance whether chapter detection
    // will work. 'none' = red (detector gave up, treats as 1 chapter).
    let cls = 'fmt-chip';
    if (fmt === 'none') cls += ' fmt-none';
    else if (fmt === 'zh-standard' || fmt === 'en-standard') cls += ' fmt-strong';
    return el('span', { class: cls, text: fmt || '—' });
  }

  // ---------- LIST ----------
  async function refresh() {
    const tbody = $('#novels-tbody');
    try {
      const resp = await fetch('/api/novels');
      const data = await resp.json();
      const items = data.novels || [];
      renderStats(items);
      tbody.innerHTML = '';
      if (!items.length) {
        tbody.appendChild(el('tr', { class: 'novels-empty-row' }, [
          el('td', { colspan: 6 }, [
            el('div', { class: 'placeholder' }, [
              el('div', { class: 'placeholder-title', text: '还没有素材' }),
              el('div', { class: 'placeholder-sub', text: '拖入 .txt 文件开始 →' }),
            ]),
          ]),
        ]));
        return;
      }
      items.forEach(row => tbody.appendChild(renderRow(row)));
    } catch (e) {
      tbody.innerHTML = '';
      tbody.appendChild(el('tr', {}, [
        el('td', { colspan: 6 }, [
          el('div', { class: 'placeholder' }, [
            el('div', { class: 'placeholder-title', text: '加载失败' }),
            el('div', { class: 'placeholder-sub', text: e.message }),
          ]),
        ]),
      ]));
    }
  }

  function renderStats(items) {
    const wrap = $('#novels-stats');
    if (!wrap) return;
    if (!items.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const totalBytes = items.reduce((s, x) => s + (x.size_bytes || 0), 0);
    const totalCh = items.reduce((s, x) => s + (x.estimated_chapters || 0), 0);
    $('#stat-count').textContent = items.length;
    $('#stat-size').textContent = humanSize(totalBytes);
    $('#stat-chapters').textContent = totalCh.toLocaleString();
  }

  function renderRow(r) {
    const encCell = el('td', {
      class: 'col-enc ' + (r.encoding_ok ? 'ok' : 'bad'),
      title: r.encoding_ok ? 'UTF-8 有效' : 'UTF-8 解码失败',
      text: r.encoding_ok ? '✓' : '✗',
    });

    return el('tr', {}, [
      el('td', { class: 'col-name', title: r.path, text: r.name }),
      el('td', { class: 'col-size', text: r.size_human }),
      encCell,
      el('td', { class: 'col-chapters', text: (r.estimated_chapters || 0).toLocaleString() }),
      el('td', { class: 'col-format' }, [formatChip(r.detected_format)]),
      el('td', { class: 'col-actions' }, [
        el('button', {
          class: 'btn btn-ghost',
          title: '预览首 2000 字',
          onclick: () => openPreview(r.name),
        }, ['预览']),
        el('button', {
          class: 'btn btn-ghost',
          title: '删除',
          onclick: () => confirmDelete(r.name),
        }, ['删除']),
      ]),
    ]);
  }

  async function confirmDelete(name) {
    if (!window.confirm(`确认删除「${name}」？\n\n此操作不可撤销。`)) return;
    try {
      const resp = await fetch('/api/novels/' + encodeURIComponent(name), { method: 'DELETE' });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(body.reason || ('HTTP ' + resp.status));
      toast('已删除 ' + name, 'ok');
      refresh();
    } catch (e) {
      toast('删除失败: ' + e.message, 'err');
    }
  }

  // ---------- UPLOAD ----------
  function initDropzone() {
    const zone = $('#dropzone');
    const input = $('#file-input');
    if (!zone || !input) return;

    // click handled by native <label for>; we only wire drag
    ['dragenter', 'dragover'].forEach(ev => {
      zone.addEventListener(ev, e => {
        e.preventDefault();
        zone.classList.add('is-dragover');
      });
    });
    ['dragleave', 'drop'].forEach(ev => {
      zone.addEventListener(ev, e => {
        e.preventDefault();
        zone.classList.remove('is-dragover');
      });
    });
    zone.addEventListener('drop', e => {
      const files = Array.from(e.dataTransfer.files || []);
      if (files.length) uploadFiles(files);
    });
    input.addEventListener('change', e => {
      const files = Array.from(e.target.files || []);
      if (files.length) uploadFiles(files);
      input.value = '';  // allow re-selecting same file
    });
  }

  /**
   * Upload files one request per file (even though backend accepts
   * batches), so the user sees granular progress and one failing file
   * doesn't take down the whole queue visually.
   */
  async function uploadFiles(files) {
    const queue = $('#upload-queue');
    const rows = files.map(f => {
      const row = el('li', { class: 'upload-row' }, [
        el('span', { class: 'upload-row-name', title: f.name, text: f.name }),
        el('div', { class: 'upload-row-progress' }, [
          el('div', { class: 'upload-row-fill' }),
        ]),
        el('span', { class: 'upload-row-size', text: humanSize(f.size) }),
        el('span', { class: 'upload-row-status pending', text: '◐' }),
      ]);
      queue.appendChild(row);
      return row;
    });

    // Sequential upload to avoid hitting Flask MAX_CONTENT_LENGTH on big batches.
    for (let i = 0; i < files.length; i++) {
      await uploadOne(files[i], rows[i]);
    }
    refresh();

    // Auto-collapse queue after 5 s
    setTimeout(() => {
      queue.querySelectorAll('.upload-row.ok').forEach(r => r.remove());
    }, 5000);
  }

  function uploadOne(file, row) {
    return new Promise(resolve => {
      const fill = row.querySelector('.upload-row-fill');
      const status = row.querySelector('.upload-row-status');

      const fd = new FormData();
      fd.append('files', file, file.name);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/novels/upload', true);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = Math.round(100 * e.loaded / e.total);
          fill.style.width = pct + '%';
        }
      };
      xhr.onload = () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch (_) {}

        const uploaded = (body.uploaded || []).length > 0;
        const skipped = (body.skipped || []);

        row.classList.remove('pending');
        status.classList.remove('pending');
        if (uploaded) {
          row.classList.add('ok');
          status.classList.add('ok');
          status.textContent = '✓';
          fill.style.width = '100%';
        } else {
          row.classList.add('err');
          status.classList.add('err');
          status.textContent = '✗';
          const reason = (skipped[0] && skipped[0].reason) || body.reason || ('HTTP ' + xhr.status);
          status.title = reason;
          toast(file.name + ': ' + reason, 'err');
        }
        resolve();
      };
      xhr.onerror = () => {
        row.classList.add('err');
        status.textContent = '✗';
        status.title = 'network error';
        resolve();
      };
      xhr.send(fd);
    });
  }

  // ---------- PREVIEW ----------
  async function openPreview(name) {
    const drawer = $('#preview-drawer');
    $('#preview-title').textContent = name;
    $('#preview-meta').textContent = '加载中…';
    $('#preview-body').textContent = '';
    drawer.hidden = false;
    try {
      const resp = await fetch('/api/novels/' + encodeURIComponent(name) + '/preview');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      $('#preview-meta').textContent =
        `${data.head.length.toLocaleString()} 字` + (data.truncated ? ' · 已截断（仅显示前 2000 字）' : ' · 全文');
      $('#preview-body').textContent = data.head;
    } catch (e) {
      $('#preview-meta').textContent = '加载失败';
      $('#preview-body').textContent = e.message;
    }
  }

  function closePreview() {
    $('#preview-drawer').hidden = true;
  }

  // ---------- INIT ----------
  document.addEventListener('DOMContentLoaded', () => {
    initDropzone();
    $('#btn-refresh') && $('#btn-refresh').addEventListener('click', refresh);
    $('#preview-close') && $('#preview-close').addEventListener('click', closePreview);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') closePreview();
    });
    refresh();
  });
})();
