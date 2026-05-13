// /presets/new 三 tab 表单 → 提交 /api/jobs → 跳 /jobs/<id>
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

document.getElementById("form-from-novel")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  const pid = f.elements["preset_id"].value.trim();
  const displayName = f.elements["display_name"].value.trim();
  const sources = [...f.querySelectorAll('input[name="sources"]:checked')].map((x) => x.value);
  submitJob("from-novel", { type: "preset", id: pid }, { display_name: displayName }, sources);
});

document.getElementById("form-from-description")?.addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  const pid = f.elements["preset_id"].value.trim();
  const displayName = f.elements["display_name"].value.trim();
  const description = f.elements["description"].value.trim();
  submitJob("from-description", { type: "preset", id: pid }, { display_name: displayName, description });
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
