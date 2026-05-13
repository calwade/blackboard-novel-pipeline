/* =========================================================
   Novelforge — demo UI entrypoint
   Vanilla JS ES modules. No bundler, no framework. Fetch + DOM.

   This file is intentionally small. It wires the DOMContentLoaded
   boot sequence and the handful of buttons that don't belong to a
   feature module. Everything else lives in ./ui/ and ./features/.
   ========================================================= */

import { $ } from './utils.js';
import { state } from './state.js';
import { wireTabs, setCenterTab } from './ui/tabs.js';
import { pollState, pollStatus, pollPrompts } from './ui/polling.js';
import { refreshPrompts } from './ui/inspector.js';
import { openFile } from './ui/viewer.js';
import { syncRunFields, doRun, doAbort } from './ui/runControls.js';
import { openProjectPicker } from './features/projectPicker.js';
import { openSettingsDialog } from './features/settings.js';
import { initExtractOverride } from './features/extractOverride.js';
import { checkOnboarding, showOnboarding } from './features/onboarding.js';
import { initViewSwitcher } from './features/viewSwitcher.js';

function wireButtons() {
  // Run panel
  $('#run-mode').addEventListener('change', () => { syncRunFields(); });
  $('#btn-run').addEventListener('click', doRun);
  $('#btn-abort').addEventListener('click', doAbort);
  $('#btn-reload').addEventListener('click', () => location.reload());

  // Project switcher + settings
  $('#btn-project').addEventListener('click', openProjectPicker);
  $('#btn-settings').addEventListener('click', openSettingsDialog);

  // Override-genre button + dialog (Phase 4 Task 4.7)
  initExtractOverride();

  // Generic dialog close (data-close-dialog)
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-close-dialog]');
    if (btn) {
      const dlg = btn.closest('dialog');
      if (dlg && dlg.open) dlg.close();
    }
  });

  // Close dialogs with backdrop click (native dialogs leave this to us)
  document.querySelectorAll('dialog.dlg').forEach((dlg) => {
    dlg.addEventListener('click', (e) => {
      // Click on the dialog element itself (not children) = backdrop
      const rect = dlg.getBoundingClientRect();
      const inside = e.clientX >= rect.left && e.clientX <= rect.right
                  && e.clientY >= rect.top  && e.clientY <= rect.bottom;
      if (!inside) dlg.close();
    });
  });

  syncRunFields();
}

// ---------- loading overlay helpers ----------

function setLoadingPhase(text) {
  const el = document.getElementById('loading-phase');
  if (el) el.textContent = text;
}

function hideLoadingOverlay() {
  const el = document.getElementById('loading-overlay');
  if (!el) return;
  el.classList.add('is-hiding');
  el.setAttribute('aria-busy', 'false');
}

async function init() {
  wireTabs();
  wireButtons();
  // View switcher 必须在 pollState 前初始化：它会读 URL ?view=&job=
  // 并把 state.view/state.genreJobId 设好，pollState 按此切换数据源。
  await initViewSwitcher();
  setLoadingPhase('读取 state/ 快照…');
  await pollState();

  // Onboarding gate — 仅在作品视图启用；题材视图不强制要求激活作品
  setLoadingPhase('检查配置…');
  if (state.view !== 'genre') {
    const gate = await checkOnboarding();
    if (gate.needed) {
      hideLoadingOverlay();
      await showOnboarding(gate.step);
      return;
    }
  }

  setLoadingPhase('加载 prompt log…');
  await refreshPrompts();
  setLoadingPhase('读取运行状态…');
  await pollStatus();
  pollPrompts();
  // fast state refresh
  (function loopState() {
    state.statePollTimer = setTimeout(async () => {
      await pollState();
      loopState();
    }, state.status.running ? 2000 : 4000);
  })();

  // Auto-open the first produced chapter on first load (novel 视图专属)
  setLoadingPhase('渲染界面…');
  if (state.view !== 'genre' && state.snapshot && state.snapshot.chapters && state.snapshot.chapters.length) {
    const produced = state.snapshot.chapters.find((c) => c.has_md);
    if (produced) openFile(`state/chapters/ch${String(produced.ch).padStart(3, '0')}.md`);
  }

  // 题材视图：首次加载自动打开第一个产物（era.md 优先，否则 genre_blueprint.yaml）
  if (state.view === 'genre' && state.snapshot && state.snapshot.files) {
    const files = state.snapshot.files;
    const prefer = files.find((f) => f.path === 'era.md')
                || files.find((f) => f.path.endsWith('genre_blueprint.yaml'))
                || files.find((f) => f.path.endsWith('extraction_tally.md'))
                || files.find((f) => f.kind === 'final')
                || files[0];
    if (prefer) openFile(prefer.path);
  }

  // Lane B Task #3: when the project is past ch1 AND a status card
  // exists, the "current time-point" ledgers are usually more useful
  // than the chapter-viewer default. We only do this on first paint;
  // thereafter the user's tab choice is respected (setCenterTab keeps
  // state, and the polling loop does not re-invoke this).
  //
  // Guards:
  //   1) snapshot must be loaded (otherwise we can't read progress)
  //   2) current_chapter > 1 — on a brand new project we want the
  //      chapter viewer so the author sees what they just wrote
  //   3) has_status_card — without the card the tab would just be
  //      a sea of placeholders, worse than the chapter view
  //   4) novel view only — genre view has no bookkeeping tab
  const snap = state.snapshot;
  if (state.view !== 'genre'
      && snap
      && (snap.progress?.current_chapter || 0) > 1
      && snap.bookkeeping?.has_status_card) {
    setCenterTab('bookkeeping');
  }

  requestAnimationFrame(hideLoadingOverlay);
}

window.addEventListener('DOMContentLoaded', init);
