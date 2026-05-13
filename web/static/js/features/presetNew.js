// /presets/new 三 tab 表单 → 提交 /api/jobs → 跳 /jobs/<id>
import { renderNovelsCheckboxes } from "./projectWizard.js";

async function submitJob(kind, target, params, sources = []) {
  const r = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, target, params, sources }),
  });
  if (!r.ok) {
    const err = (await r.json()).error || "提交失败";
    alert(err);
    return;
  }
  const { job_id } = await r.json();
  location.href = `/jobs/${job_id}`;
}

// 加载素材库到 from-novel tab 的 picker
async function loadNovelsPicker() {
  const box = document.getElementById("picker-body");
  const summary = document.getElementById("picker-summary");
  if (!box) return;
  try {
    const r = await fetch("/api/novels");
    if (!r.ok) throw new Error("fetch failed");
    const data = await r.json();
    const novels = data.novels || [];
    renderNovelsCheckboxes(box, novels, "sources");
    if (summary) summary.textContent = `${novels.length} 份素材`;
  } catch (e) {
    if (summary) summary.textContent = "加载失败";
    box.innerHTML = '<span class="form-hint">素材库加载失败</span>';
  }
}

document.getElementById("form-from-novel")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  const pid = f.elements["preset_id"].value.trim();
  const displayName = f.elements["display_name"].value.trim();
  const hint = (f.elements["hint"]?.value || "").trim();
  const sources = [...f.querySelectorAll('input[name="sources"]:checked')].map((x) => x.value);
  if (sources.length === 0) {
    alert("请至少勾选 2 本原著素材（NovelDNA 融合至少需要 2 本）");
    return;
  }
  if (sources.length < 2) {
    if (!confirm("只选 1 本？NovelDNA 建议选 2-4 本做交叉融合，单本也可继续。")) return;
  }
  submitJob(
    "from-novel",
    { type: "preset", id: pid },
    { display_name: displayName, hint },
    sources,
  );
});

document.getElementById("form-from-description")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  const pid = f.elements["preset_id"].value.trim();
  const displayName = f.elements["display_name"].value.trim();
  const tone = f.elements["tone"]?.value.trim() || "";
  const description = f.elements["description"].value.trim();
  submitJob(
    "from-description",
    { type: "preset", id: pid },
    { display_name: displayName, tone, description },
  );
});

document.getElementById("form-blank")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  const pid = f.elements["preset_id"].value.trim();
  const displayName = f.elements["display_name"].value.trim();
  const tone = f.elements["tone"].value.trim();
  submitJob("blank", { type: "preset", id: pid }, { display_name: displayName, tone });
});

// tab 切换保留原逻辑
document.querySelectorAll(".tabs-subpage [data-tab]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tabs-subpage [data-tab]").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const active = btn.dataset.tab;
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.style.display = p.dataset.tab === active ? "" : "none";
    });
  });
});

// 页面加载即拉素材库
loadNovelsPicker();
