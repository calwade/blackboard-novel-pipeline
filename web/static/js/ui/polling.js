/* =========================================================
   ui/polling.js — /api/state + /api/status + /api/prompts polling loops.
   Cadence adapts: faster when pipeline is running.
   ========================================================= */

import { api } from '../api.js';
import { toast } from '../api.js';
import { state } from '../state.js';
import { renderPills } from './pills.js';
import { renderTree } from './tree.js';
import { renderBrandSub } from './pills.js';
import { renderBookkeeping } from './bookkeeping.js';
import { refreshPrompts } from './inspector.js';

export async function pollState() {
  try {
    if (state.view === 'genre' && state.genreJobId) {
      // 题材视图：数据源换成 /api/genre-state?job=<id>
      // 响应形状 {job, files, counters, progress} 与 /api/state 不同，
      // 但 tree/pills 会按 view 分支处理。
      state.snapshot = await api('/api/genre-state?job=' + encodeURIComponent(state.genreJobId));
    } else {
      state.snapshot = await api('/api/state');
    }
    renderPills();
    renderTree();
    renderBrandSub();
    // If the bookkeeping tab is the current view, refresh its cards too.
    // Cheap: three tiny file reads; cards track content-hash to skip redundant DOM work.
    if (state.activeCenterTab === 'bookkeeping' && state.view === 'novel') {
      renderBookkeeping({ silent: true });
    }
  } catch (e) {
    // don't spam toasts on polling failures
    console.warn('state poll:', e.message);
  }
}

export async function pollStatus() {
  try {
    const prev = state.status.running;
    state.status = await api('/api/status');
    renderPills();
    if (prev && !state.status.running) {
      if (state.status.ok === false) {
        toast('流水线失败: ' + (state.status.error || '未知'), true);
      } else {
        toast('流水线完成 · 第 ' + state.status.chapter + ' 章');
        pollState();
        refreshPrompts();
      }
    }
  } catch (_) { /* tolerate */ }

  // adaptive cadence: faster when running
  const interval = state.status.running ? 1500 : 4000;
  state.statusPollTimer = setTimeout(pollStatus, interval);
}

export async function pollPrompts() {
  if (state.activeRightTab === 'inspector' || state.activeRightTab === 'log') {
    await refreshPrompts();
  }
  state.promptsPollTimer = setTimeout(pollPrompts, state.status.running ? 2500 : 5000);
}
