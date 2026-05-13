/* =========================================================
   features/extractOverride.js — ⎇ button on project home.
   Submits POST /api/jobs with kind `extract-to-project` and
   redirects the user to /jobs/<job_id> where they can watch
   progress. The dialog closes implicitly via navigation.
   ========================================================= */

import { $ } from '../utils.js';
import { apiCall, toast } from '../api.js';
import { state } from '../state.js';
import { renderNovelsCheckboxes } from './projectWizard.js';

export function initExtractOverride() {
  const btn = $('#btn-extract-genre-override');
  const dlg = $('#extract-override-dialog');
  if (!btn || !dlg) return;

  btn.onclick = async () => {
    // Need active project id
    const pid = getActiveProjectId();
    if (!pid) {
      toast('先激活一个作品', true);
      return;
    }
    // Load novels pool fresh
    const box = $('#override-novels-checkboxes');
    if (box) {
      box.innerHTML = '<span class="form-hint">加载中…</span>';
      try {
        const data = await apiCall('/api/novels');
        renderNovelsCheckboxes(box, data.novels || [], 'override_source');
      } catch (e) {
        box.innerHTML = `<span class="form-error">加载失败: ${e.message}</span>`;
      }
    }
    // Reset error state; re-enable the form in case it was disabled by a
    // prior attempt in the same page view.
    const errEl = $('#extract-override-error');
    if (errEl) { errEl.hidden = true; errEl.textContent = ''; }
    const form = $('#extract-override-form');
    if (form) {
      form.querySelectorAll('button, input').forEach((n) => { n.disabled = false; });
    }
    dlg.showModal();
  };

  const form = $('#extract-override-form');
  if (form) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const sources = fd.getAll('override_source');
      const errEl = $('#extract-override-error');
      if (errEl) { errEl.hidden = true; errEl.textContent = ''; }
      if (sources.length === 0) {
        if (errEl) { errEl.textContent = '请至少勾选一份素材'; errEl.hidden = false; }
        return;
      }
      const pid = getActiveProjectId();
      if (!pid) {
        if (errEl) { errEl.textContent = '找不到当前作品'; errEl.hidden = false; }
        return;
      }
      try {
        form.querySelectorAll('button, input').forEach((n) => { n.disabled = true; });
        const r = await fetch('/api/jobs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            kind: 'extract-to-project',
            target: { type: 'project', id: pid },
            sources,
            params: {
              with_trial: fd.get('override_with_trial') === 'on',
            },
          }),
        });
        const body = await r.json().catch(() => ({}));
        if (!r.ok) {
          const reason = body.error || body.reason || body.detail || ('HTTP ' + r.status);
          throw new Error(reason);
        }
        const jobId = body.job_id;
        if (!jobId) {
          throw new Error('后端没返回 job_id');
        }
        toast('已排入题材拆解任务');
        location.href = '/jobs/' + encodeURIComponent(jobId);
      } catch (e2) {
        if (errEl) { errEl.textContent = '失败: ' + e2.message; errEl.hidden = false; }
        form.querySelectorAll('button, input').forEach((n) => { n.disabled = false; });
      }
    };
  }
}

export function getActiveProjectId() {
  // Prefer live state snapshot (freshest); fall back to body data-attr.
  const fromState = state.snapshot
    && state.snapshot.progress
    && state.snapshot.progress.active_project;
  if (fromState) return fromState;
  return document.body.dataset.activeProject || null;
}
