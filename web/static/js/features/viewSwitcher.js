/* =========================================================
   viewSwitcher.js — 顶栏"作品 / 题材"视图切换器
   ========================================================= */

import { $ } from '../utils.js';
import { state } from '../state.js';
import { pollState } from '../ui/polling.js';
import { refreshPrompts } from '../ui/inspector.js';

const VIEW_NOVEL = 'novel';
const VIEW_GENRE = 'genre';

/**
 * 初始化：从 URL 读 ?view=&job= 设置初始状态；
 * 监听切换按钮 + 下拉选择器；
 * 切换时更新 URL（history API，不刷新页面）并重新拉数据。
 */
export async function initViewSwitcher() {
  // 从 URL 读初始 view
  const url = new URL(location.href);
  const view = url.searchParams.get('view') || VIEW_NOVEL;
  const job = url.searchParams.get('job') || null;

  if (view === VIEW_GENRE) {
    // 先填充 jobs 下拉
    await populateJobSelector();
    // 如 URL 给了 job，选中它；否则选第一个
    const selector = $('#genre-job-selector');
    if (job) {
      selector.value = job;
    }
    if (!selector.value && selector.options.length > 0) {
      selector.value = selector.options[0].value;
    }
    state.view = VIEW_GENRE;
    state.genreJobId = selector.value || null;
    applyViewUI(VIEW_GENRE);
  } else {
    applyViewUI(VIEW_NOVEL);
  }

  // 按钮事件
  $('#view-btn-novel').addEventListener('click', () => switchView(VIEW_NOVEL));
  $('#view-btn-genre').addEventListener('click', () => switchView(VIEW_GENRE));

  // 下拉切换：换 job
  $('#genre-job-selector').addEventListener('change', async (e) => {
    state.genreJobId = e.target.value;
    _pushUrl();
    await pollState();
    await refreshPrompts();
  });
}


async function switchView(newView) {
  if (state.view === newView) return;

  if (newView === VIEW_GENRE) {
    await populateJobSelector();
    const selector = $('#genre-job-selector');
    const job = selector.value || (selector.options.length > 0 ? selector.options[0].value : null);
    if (!job) {
      alert('暂无题材任务。先在"题材库 → 新建"跑一个。');
      return;
    }
    state.view = VIEW_GENRE;
    state.genreJobId = job;
  } else {
    state.view = VIEW_NOVEL;
    state.genreJobId = null;
  }

  applyViewUI(newView);
  _pushUrl();
  await pollState();
  await refreshPrompts();
}


function applyViewUI(view) {
  $('#view-btn-novel').classList.toggle('is-active', view === VIEW_NOVEL);
  $('#view-btn-genre').classList.toggle('is-active', view === VIEW_GENRE);
  $('#view-btn-novel').setAttribute('aria-selected', view === VIEW_NOVEL);
  $('#view-btn-genre').setAttribute('aria-selected', view === VIEW_GENRE);

  const selector = $('#genre-job-selector');
  selector.style.display = view === VIEW_GENRE ? '' : 'none';

  // 作品特有控件：run panel / 覆盖题材按钮 / project 切换在题材视图隐藏
  const runPanel = $('#run-panel');
  if (runPanel) runPanel.style.display = view === VIEW_GENRE ? 'none' : '';
  const extractBtn = $('#btn-extract-genre-override');
  if (extractBtn) extractBtn.style.display = view === VIEW_GENRE ? 'none' : '';

  // 中间 tabs：题材视图下只保留 chapter（当成文件查看器）；
  // bookkeeping / debt / rules 在题材视图没意义，隐藏。
  ['bookkeeping', 'debt', 'rules'].forEach((name) => {
    const tab = document.querySelector(`.tab[data-tab="${name}"]`);
    if (tab) tab.style.display = view === VIEW_GENRE ? 'none' : '';
  });
}


async function populateJobSelector() {
  const selector = $('#genre-job-selector');
  try {
    const r = await fetch('/api/jobs');
    if (!r.ok) throw new Error('fetch failed');
    const data = await r.json();
    const jobs = (data.jobs || []).slice(0, 50);  // 只展示最近 50 个

    // 排序：运行中 > aborting > 最新完成的
    const rank = { running: 0, aborting: 1, done: 2, failed: 3, aborted: 4, interrupted: 5 };
    jobs.sort((a, b) => {
      const ra = rank[a.state] ?? 9;
      const rb = rank[b.state] ?? 9;
      if (ra !== rb) return ra - rb;
      return (b.updated_at || 0) - (a.updated_at || 0);
    });

    selector.innerHTML = '';
    if (jobs.length === 0) {
      selector.innerHTML = '<option value="">（无任务）</option>';
      return;
    }
    jobs.forEach((j) => {
      const opt = document.createElement('option');
      opt.value = j.job_id;
      const stateLabel = {
        running: '▶', aborting: '⏸', done: '✓', failed: '✕',
        aborted: '⊗', interrupted: '!',
      }[j.state] || '·';
      opt.textContent = `${stateLabel} ${j.label} (${j.kind})`;
      selector.appendChild(opt);
    });
  } catch (e) {
    selector.innerHTML = '<option value="">（加载失败）</option>';
  }
}


function _pushUrl() {
  const url = new URL(location.href);
  if (state.view === VIEW_GENRE) {
    url.searchParams.set('view', VIEW_GENRE);
    if (state.genreJobId) url.searchParams.set('job', state.genreJobId);
  } else {
    url.searchParams.delete('view');
    url.searchParams.delete('job');
  }
  history.replaceState(null, '', url.toString());
}


// 导出给 main.js 在 init 时手动调用
export function currentViewFromUrl() {
  const url = new URL(location.href);
  return {
    view: url.searchParams.get('view') || VIEW_NOVEL,
    job: url.searchParams.get('job') || null,
  };
}
