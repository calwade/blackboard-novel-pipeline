/* =========================================================
   features/projectWizard.js — 4-step new-project wizard.
     1) basics (id / display_name / protagonist_name / chapter_count_target)
     2) genre starter (preset / extract / blank)
     3) outline starter (synopsis / blank)
     4) characters starter (brief / blank)

   Submits to POST /api/projects/new.
   If genre_starter === 'extract', the project is first created with a
   blank genre scaffold, then a POST /api/jobs is queued with kind
   `extract-to-project`, and the browser is redirected to
   /jobs/<job_id> where the user watches progress.

   Exports `renderNovelsCheckboxes` so features/extractOverride.js can
   re-use the checkbox rendering helper.
   ========================================================= */

import { $, $$ } from '../utils.js';
import { apiCall, toast } from '../api.js';

export async function openNewProjectWizard() {
  // Close the picker if open
  const picker = $('#dlg-project');
  if (picker && picker.open) picker.close();

  const dlg = $('#dlg-new-project');
  if (!dlg) return;

  // Reset form + step state
  const form = $('#project-wizard-form');
  if (form) form.reset();
  wizardGoToStep(1);
  $$('[data-wizard-error]').forEach((n) => { n.hidden = true; n.textContent = ''; });
  const statusEl = $('#np-create-status');
  if (statusEl) statusEl.hidden = true;

  // (Re-)wire step navigation, starter radios, and submit (idempotent).
  initProjectWizard();

  dlg.showModal();
}

function wizardGoToStep(n) {
  const dlg = $('#dlg-new-project');
  if (!dlg) return;
  dlg.querySelectorAll('[data-wizard-step]').forEach((s) => {
    s.hidden = Number(s.dataset.wizardStep) !== Number(n);
  });
}

function initProjectWizard() {
  const dlg = $('#dlg-new-project');
  if (!dlg) return;
  const form = $('#project-wizard-form');
  if (!form) return;

  // Step navigation buttons (prev / next)
  dlg.querySelectorAll('[data-wizard-next]').forEach((btn) => {
    btn.onclick = () => {
      const from = Number(btn.closest('[data-wizard-step]')?.dataset.wizardStep || '1');
      if (!wizardValidateStep(from)) return;
      wizardGoToStep(btn.dataset.wizardNext);
    };
  });
  dlg.querySelectorAll('[data-wizard-prev]').forEach((btn) => {
    btn.onclick = () => wizardGoToStep(btn.dataset.wizardPrev);
  });

  // Genre starter radios → show/hide panels
  dlg.querySelectorAll('input[name="genre_starter"]').forEach((r) => {
    r.onchange = wizardUpdateGenrePanels;
  });
  wizardUpdateGenrePanels();

  // Load preset dropdown
  const presetSel = $('#select-from-preset');
  if (presetSel) {
    presetSel.innerHTML = '<option value="" disabled selected>加载中…</option>';
    fetch('/api/presets')
      .then((r) => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
      .then((data) => {
        const list = data.presets || [];
        if (!list.length) {
          presetSel.innerHTML = '<option value="" disabled selected>（尚无 preset）</option>';
          return;
        }
        presetSel.innerHTML = '';
        list.forEach((p) => {
          const opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = p.display_name || p.id;
          presetSel.appendChild(opt);
        });
      })
      .catch((e) => {
        presetSel.innerHTML = `<option value="" disabled selected>加载失败: ${e.message}</option>`;
      });
  }

  // Load novels pool for "extract" starter
  const pool = $('#novels-pool-checkboxes');
  if (pool) {
    pool.innerHTML = '<span class="form-hint">加载中…</span>';
    fetch('/api/novels')
      .then((r) => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
      .then((data) => {
        renderNovelsCheckboxes(pool, data.novels || [], 'extract_source');
      })
      .catch((e) => {
        pool.innerHTML = `<span class="form-error">加载失败: ${e.message}</span>`;
      });
  }

  // Submit handler
  form.onsubmit = (e) => {
    e.preventDefault();
    wizardSubmit();
  };
}

function wizardUpdateGenrePanels() {
  const dlg = $('#dlg-new-project');
  if (!dlg) return;
  const val = dlg.querySelector('input[name="genre_starter"]:checked')?.value;
  dlg.querySelectorAll('[data-genre-panel]').forEach((p) => {
    p.hidden = p.dataset.genrePanel !== val;
  });
}

function wizardValidateStep(step) {
  const dlg = $('#dlg-new-project');
  if (!dlg) return true;
  const fd = new FormData($('#project-wizard-form'));
  const errEl = dlg.querySelector(`[data-wizard-error="${step}"]`);
  const showErr = (msg) => { if (errEl) { errEl.textContent = msg; errEl.hidden = false; } };
  if (errEl) { errEl.hidden = true; errEl.textContent = ''; }

  if (step === 1) {
    const id = (fd.get('id') || '').toString().trim();
    if (!/^[a-z0-9_][a-z0-9_-]{0,63}$/.test(id)) {
      showErr('ID 必须是小写字母/数字/_/-，长度 ≤ 64');
      return false;
    }
    if (!(fd.get('display_name') || '').toString().trim()) {
      showErr('显示名必填');
      return false;
    }
    if (!(fd.get('protagonist_name') || '').toString().trim()) {
      showErr('主角姓名必填');
      return false;
    }
    const n = Number(fd.get('chapter_count_target'));
    if (!Number.isInteger(n) || n < 1) {
      showErr('目标章数必须是 ≥1 的整数');
      return false;
    }
  }
  if (step === 2) {
    const starter = fd.get('genre_starter');
    if (starter === 'preset' && !fd.get('from_preset')) {
      showErr('请选一个 preset');
      return false;
    }
    if (starter === 'extract' && fd.getAll('extract_source').length === 0) {
      showErr('请至少勾选一份原著素材');
      return false;
    }
  }
  return true;
}

export function renderNovelsCheckboxes(root, novels, fieldName) {
  root.innerHTML = '';
  if (!novels.length) {
    root.innerHTML = '<span class="form-hint">（素材库为空，去 /novels 上传）</span>';
    return;
  }
  novels.forEach((n) => {
    const name = n.name || n;
    const lbl = document.createElement('label');
    lbl.className = 'wizard-radio';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.name = fieldName;
    input.value = name;
    const txt = document.createElement('span');
    txt.textContent = ' ' + name;
    lbl.appendChild(input);
    lbl.appendChild(txt);
    root.appendChild(lbl);
  });
}

async function wizardSubmit() {
  const form = $('#project-wizard-form');
  if (!form) return;
  // Final validation on all steps
  for (const step of [1, 2]) {
    if (!wizardValidateStep(step)) {
      wizardGoToStep(step);
      return;
    }
  }

  const fd = new FormData(form);
  const starter = fd.get('genre_starter');
  const payload = {
    id: (fd.get('id') || '').toString().trim(),
    display_name: (fd.get('display_name') || '').toString().trim(),
    protagonist_name: (fd.get('protagonist_name') || '').toString().trim(),
    chapter_count_target: Number(fd.get('chapter_count_target')),
  };

  // Extract sources are only used to queue the extract-to-project job
  // AFTER the project skeleton has been created. They are NOT sent
  // in the /api/projects/new payload (the backend now rejects that).
  let extractSources = [];
  let extractWithTrial = false;

  if (starter === 'preset') {
    payload.from_preset = fd.get('from_preset');
  } else if (starter === 'extract') {
    extractSources = fd.getAll('extract_source');
    extractWithTrial = fd.get('extract_with_trial') === 'on';
    // Create project with blank genre first; job will overwrite genre files.
    payload.blank_genre = true;
  } else {
    payload.blank_genre = true;
  }

  // Outline starter — we ALWAYS create blank, then call draft-outline
  // afterwards if a synopsis was provided. This keeps the backend contract
  // single-path (create_project doesn't try to draft) and avoids the
  // duplicate-draft bug where both create_project AND the explicit draft
  // call would hit the LLM.
  const synopsis = (fd.get('outline_synopsis') || '').toString().trim();
  const blankOutlineChecked = fd.get('blank_outline') === 'on';
  const willDraftOutline = !blankOutlineChecked && synopsis.length > 0;
  payload.blank_outline = true;  // always blank at creation time

  // Characters starter — same pattern.
  const brief = (fd.get('characters_brief') || '').toString().trim();
  const blankCharsChecked = fd.get('blank_characters') === 'on';
  const willDraftCharacters = !blankCharsChecked && brief.length > 0;
  payload.blank_characters = true;

  const err4 = document.querySelector('[data-wizard-error="4"]');
  if (err4) { err4.hidden = true; err4.textContent = ''; }
  const statusEl = $('#np-create-status');
  const textEl = statusEl ? statusEl.querySelector('.wizard-status-text') : null;
  const markEl = statusEl ? statusEl.querySelector('.wizard-status-mark') : null;
  const submitBtn = $('#btn-wizard-submit');
  if (statusEl) {
    statusEl.hidden = false;
    statusEl.classList.remove('is-done', 'is-error');
    if (markEl) markEl.textContent = '◐';
    if (textEl) textEl.textContent = '正在创建作品…';
  }
  if (submitBtn) submitBtn.disabled = true;

  try {
    const r = await fetch('/api/projects/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok || body.ok === false) {
      const reason = body.reason || body.detail || body.error || ('HTTP ' + r.status);
      throw new Error(reason);
    }

    const pid = payload.id;

    // Sync path: skeleton + bootstrap done. Now fire draft calls if needed.
    await runPostCreationDrafts(pid, {
      synopsis: willDraftOutline ? synopsis : '',
      brief: willDraftCharacters ? brief : '',
      statusEl, textEl, markEl,
    });

    // If user picked "从原著拆", queue an extract-to-project job now and
    // redirect to the job detail page so they can watch progress.
    if (starter === 'extract') {
      if (textEl) textEl.textContent = '已创建作品 · 正在排入题材拆解任务…';
      const jobResp = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: 'extract-to-project',
          target: { type: 'project', id: pid },
          sources: extractSources,
          params: { with_trial: extractWithTrial },
        }),
      });
      const jobBody = await jobResp.json().catch(() => ({}));
      if (!jobResp.ok) {
        const reason = jobBody.error || jobBody.reason || ('HTTP ' + jobResp.status);
        throw new Error('创建题材任务失败: ' + reason);
      }
      const jobId = jobBody.job_id;
      if (!jobId) {
        throw new Error('后端没返回 job_id');
      }
      toast('已创建作品并排入题材拆解任务');
      location.href = '/jobs/' + encodeURIComponent(jobId);
      return;
    }

    if (statusEl) {
      statusEl.classList.add('is-done');
      if (markEl) markEl.textContent = '✓';
      if (textEl) textEl.textContent = '已创建 · 正在激活…';
    }
    // Activate the new project automatically
    try {
      await apiCall('/api/projects/activate', {
        method: 'POST',
        body: JSON.stringify({ id: pid }),
      });
    } catch (_) { /* activation best-effort */ }
    toast('已创建并激活 · ' + pid);
    setTimeout(() => location.reload(), 400);
  } catch (e) {
    if (statusEl) {
      statusEl.classList.add('is-error');
      if (markEl) markEl.textContent = '✕';
      if (textEl) textEl.textContent = '创建失败';
    }
    if (err4) {
      err4.textContent = e.message || '创建失败';
      err4.hidden = false;
    }
    if (submitBtn) submitBtn.disabled = false;
  }
}

// Call draft-outline / draft-characters after project creation. Soft-fails
// with a toast; the project is already created, so a drafter crash is a
// warning, not a hard error.
async function runPostCreationDrafts(pid, { synopsis, brief, statusEl, textEl, markEl }) {
  if (synopsis) {
    if (textEl) textEl.textContent = '起草大纲…';
    try {
      await apiCall(`/api/projects/${encodeURIComponent(pid)}/draft-outline`, {
        method: 'POST', body: JSON.stringify({ synopsis }),
      });
    } catch (e) {
      toast('大纲起草失败（可稍后在 ⎇ 按钮重试）: ' + e.message, true);
    }
  }
  if (brief) {
    if (textEl) textEl.textContent = '起草人物…';
    try {
      await apiCall(`/api/projects/${encodeURIComponent(pid)}/draft-characters`, {
        method: 'POST', body: JSON.stringify({ brief }),
      });
    } catch (e) {
      toast('人物起草失败（可稍后在 ⎇ 按钮重试）: ' + e.message, true);
    }
  }
}
