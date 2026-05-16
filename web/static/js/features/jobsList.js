// /jobs 列表页：fetch /api/jobs?state=... 并渲染。
const listEl = document.getElementById("jobs-list");
let currentFilter = "all";

async function fetchJobs() {
  const qs = currentFilter === "all" ? "" : `?state=${currentFilter}`;
  const r = await fetch(`/api/jobs${qs}`);
  if (!r.ok) return [];
  return (await r.json()).jobs;
}

function kindLabel(kind) {
  return {
    "from-novel": "多本融合",
    "from-description": "从描述",
    "blank": "空壳",
  }[kind] || kind;
}

function stateBadge(state) {
  const map = {
    running: ["运行中", "badge-running"],
    aborting: ["中止中", "badge-aborting"],
    done: ["完成", "badge-done"],
    failed: ["失败", "badge-failed"],
    aborted: ["已中止", "badge-aborted"],
    interrupted: ["中断", "badge-interrupted"],
  };
  const [text, cls] = map[state] || [state, ""];
  return `<span class="badge ${cls}">${text}</span>`;
}

function renderRow(job) {
  const target = `${job.target.type}:${job.target.id}`;
  const progress = job.progress_text || "";
  const ago = new Date(job.updated_at * 1000).toLocaleString("zh-CN");
  // failed/aborted/interrupted 用 button 就地展开 log（无产物可看，不跳 genre view）
  // running/done 仍跳详情页（有产物可看）
  const isTerminalNoArtifact = ["failed", "aborted", "interrupted"].includes(job.state);
  const wrapperOpen = isTerminalNoArtifact
    ? `<button type="button" class="job-row" data-job-id="${job.job_id}">`
    : `<a class="job-row" href="/jobs/${job.job_id}">`;
  const wrapperClose = isTerminalNoArtifact ? `</button>` : `</a>`;
  return `
    <div class="job-row-wrap" data-job-id="${job.job_id}">
      ${wrapperOpen}
        <div class="job-row-main">
          <span class="job-kind">${kindLabel(job.kind)}</span>
          <span class="job-target">${target}</span>
          <span class="job-label">${job.label}</span>
        </div>
        <div class="job-row-meta">
          ${stateBadge(job.state)}
          <span class="job-progress">${progress}</span>
          <span class="job-time">${ago}</span>
        </div>
      ${wrapperClose}
      <div class="job-log-panel" hidden></div>
    </div>
  `;
}

async function showJobLog(jobId, panelEl) {
  if (!panelEl.hidden) {
    panelEl.hidden = true;
    panelEl.innerHTML = "";
    return;
  }
  panelEl.hidden = false;
  panelEl.innerHTML = `<div class="job-log-loading">加载中…</div>`;
  try {
    const [jobRes, logRes] = await Promise.all([
      fetch(`/api/jobs/${jobId}`),
      fetch(`/api/jobs/${jobId}/log`),
    ]);
    const job = jobRes.ok ? await jobRes.json() : {};
    const logData = logRes.ok ? await logRes.json() : { content: "" };
    const errorBlock = job.error
      ? `<div class="job-log-error"><strong>错误：</strong>${escapeHtml(job.error)}</div>`
      : "";
    panelEl.innerHTML = `
      ${errorBlock}
      <pre class="job-log-content">${escapeHtml(logData.content || "(空日志)")}</pre>
    `;
  } catch (e) {
    panelEl.innerHTML = `<div class="job-log-error">加载日志失败：${escapeHtml(String(e))}</div>`;
  }
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function render() {
  const jobs = await fetchJobs();
  if (jobs.length === 0) {
    listEl.innerHTML = `<div class="jobs-empty">暂无任务</div>`;
    return;
  }
  listEl.innerHTML = jobs.map(renderRow).join("");
  // 绑定 failed/aborted/interrupted 的就地展开
  listEl.querySelectorAll("button.job-row").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const wrap = btn.closest(".job-row-wrap");
      const panel = wrap?.querySelector(".job-log-panel");
      if (panel) showJobLog(btn.dataset.jobId, panel);
    });
  });
}

document.querySelectorAll(".filter-tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-tabs button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.state;
    render();
  });
});

// 初始渲染 + 每 3 秒自动刷新（running 的 job 会更新 progress）
const urlState = new URLSearchParams(location.search).get("state");
if (urlState) {
  currentFilter = urlState;
  document.querySelectorAll(".filter-tabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.state === urlState);
  });
}
render();
setInterval(render, 3000);
