# Phase 4 · Web 层重构

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Phase Goal:**
1. 路由改名 `/genres*` → `/presets*`；删裸建路由
2. `POST /api/presets/new-from-novel` 产物落新 preset，从大池子 `/novels` 勾选 sources
3. `POST /api/projects/new` 接 4 步向导全字段
4. `POST /api/projects/<id>/extract-genre` + `/draft-outline` + `/draft-characters`
5. `GET /api/novels` 响应补 `used_by_presets`；`DELETE` 默认警告，`force=true` 真删
6. 模板改名 + 新建作品向导 UI 4 步三选一

**Phase Checkpoint 命令:**
```bash
.venv/bin/python3 -m pytest tests/test_web_presets_api.py tests/test_web_project_new_wizard.py tests/test_web_project_extract_genre.py tests/test_web_draft_endpoints.py tests/test_web_novels_usage.py -v
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py
```

---

## 文件结构

- Rename: `web/templates/genres/` → `web/templates/presets/`
- Delete: `web/templates/presets/new.html`（旧裸建页）
- Rename: `web/templates/presets/extract.html` → `web/templates/presets/new-from-novel.html`
- Modify: 上面每个模板里的 URL / 文案
- Modify: `web/templates/index.html`（作品首页），新增「⎇ 从原著覆盖当前题材配置」按钮 + 新建作品向导扩展第 2-4 步
- Rename: `web/static/genres.css` → `web/static/presets.css`；`web/static/genres.js` → `web/static/presets.js`
- Modify: `web/app.py`（大量路由改）
- Create: `tests/test_web_presets_api.py`
- Create: `tests/test_web_project_new_wizard.py`
- Create: `tests/test_web_project_extract_genre.py`
- Create: `tests/test_web_draft_endpoints.py`
- Create: `tests/test_web_novels_usage.py`
- Modify: 旧 `tests/test_web_genre_files_api.py`（skip 标注改指新 spec 文件路径 + 更新 doc 引用）
- Modify: `tests/test_web_and_pages_sync.py`（路由存在性检查按新路径）

---

## Task 4.1 · `/presets` API：列表 + 详情 + 删除

**Files:**
- Modify: `web/app.py`
- Create: `tests/test_web_presets_api.py`

- [ ] **Step 1:** 写 `tests/test_web_presets_api.py`：

```python
"""Preset management API: list / detail / delete."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app_with_presets(tmp_path: Path, monkeypatch):
    from src import config
    (tmp_path / "presets").mkdir()
    for gid in ("gangster-hk-1983", "xianxia-ascension", "my-custom"):
        pd = tmp_path / "presets" / gid
        pd.mkdir()
        (pd / "genre.yaml").write_text(f"id: {gid}\ndisplay_name: {gid}\n", encoding="utf-8")
        (pd / "era.md").write_text(f"era {gid}\n", encoding="utf-8")
        (pd / "novels").mkdir()

    (tmp_path / "projects").mkdir()
    (tmp_path / "novels").mkdir()

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")

    from web import app as web_app
    return web_app.app.test_client()


def test_get_api_presets_lists_all(app_with_presets):
    r = app_with_presets.get("/api/presets")
    assert r.status_code == 200
    data = r.get_json()
    ids = [p["id"] for p in data["presets"]]
    assert set(ids) >= {"gangster-hk-1983", "xianxia-ascension", "my-custom"}


def test_get_api_preset_detail(app_with_presets):
    r = app_with_presets.get("/api/presets/my-custom")
    assert r.status_code == 200
    data = r.get_json()
    assert data["id"] == "my-custom"
    assert "era.md" in data["files"]
    # built-in flag
    r2 = app_with_presets.get("/api/presets/gangster-hk-1983")
    assert r2.get_json()["builtin"] is True
    assert r.get_json()["builtin"] is False


def test_delete_preset_builtin_refused(app_with_presets):
    r = app_with_presets.delete("/api/presets/gangster-hk-1983")
    assert r.status_code == 403
    assert "built" in r.get_json()["reason"].lower() or "builtin" in r.get_json()["reason"].lower()


def test_delete_preset_custom_works(app_with_presets):
    r = app_with_presets.delete("/api/presets/my-custom")
    assert r.status_code == 200
    # confirm it's gone
    r2 = app_with_presets.get("/api/presets/my-custom")
    assert r2.status_code == 404


def test_get_preset_404(app_with_presets):
    r = app_with_presets.get("/api/presets/doesnotexist")
    assert r.status_code == 404


def test_view_presets_index_html(app_with_presets):
    r = app_with_presets.get("/presets")
    assert r.status_code == 200
    # page should mention at least one preset id
    assert b"gangster-hk-1983" in r.data


def test_old_genres_routes_gone(app_with_presets):
    """Old /genres* routes must return 404."""
    for path in ("/genres", "/genres/new", "/genres/gangster-hk-1983", "/api/genres"):
        r = app_with_presets.get(path)
        assert r.status_code == 404, f"old route {path} still serves"
```

定义内置 preset 列表：`BUILTIN_PRESETS = {"gangster-hk-1983", "xianxia-ascension", "urban-romance-contemporary"}`（放 `web/app.py` 或 `src/config.py` 皆可；本 plan 约定放 `src/config.py`）。

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_web_presets_api.py -v 2>&1 | tail -15
```

- [ ] **Step 3:** 修 `web/app.py`：

**删除**所有 `/genres*` 路由（整块）：`/genres`、`/genres/new`、`/genres/<gid>`、`/genres/<gid>/extract`、`/genres/<gid>/extract/progress`、`/api/genres`、`/api/genres/new`、`/api/genres/<gid>/fill`、`/api/genres/<gid>/audit`、`/api/genres/<gid>/extract`、`/api/genres/<gid>/abort`、`/api/genres/<gid>/status`、`/api/genres/<gid>/issues`、`DELETE /api/genres/<gid>`、`view_genres_index`、`view_genre_new`、`view_genre_detail`、`view_genre_extract_form`、`view_genre_extract_progress`。

**新增**：

```python
# ---- Preset API ----

BUILTIN_PRESETS = {"gangster-hk-1983", "xianxia-ascension", "urban-romance-contemporary"}


def _preset_dir(preset_id: str) -> Path:
    return config.PRESETS_DIR / preset_id


@app.get("/api/presets")
def api_presets_list():
    items = []
    if config.PRESETS_DIR.exists():
        for p in sorted(config.PRESETS_DIR.iterdir()):
            if not p.is_dir() or p.name.startswith("."):
                continue
            meta = {}
            gy = p / "genre.yaml"
            if gy.exists():
                import yaml
                try:
                    meta = yaml.safe_load(gy.read_text(encoding="utf-8")) or {}
                except yaml.YAMLError:
                    meta = {}
            items.append({
                "id": p.name,
                "display_name": meta.get("display_name", p.name),
                "tone": meta.get("tone", ""),
                "builtin": p.name in BUILTIN_PRESETS,
            })
    return {"presets": items}


@app.get("/api/presets/<pid>")
def api_preset_detail(pid: str):
    pd = _preset_dir(pid)
    if not pd.exists():
        return {"ok": False, "reason": "preset not found"}, 404
    files = [f.name for f in pd.iterdir() if f.is_file()]
    novels = []
    novels_dir = pd / "novels"
    if novels_dir.exists():
        novels = [n.name for n in novels_dir.iterdir() if n.is_file() and n.suffix == ".txt"]
    return {
        "id": pid,
        "files": files,
        "novels": novels,
        "builtin": pid in BUILTIN_PRESETS,
    }


@app.delete("/api/presets/<pid>")
def api_preset_delete(pid: str):
    if pid in BUILTIN_PRESETS:
        return {"ok": False, "reason": "built-in preset cannot be deleted"}, 403
    pd = _preset_dir(pid)
    if not pd.exists():
        return {"ok": False, "reason": "preset not found"}, 404
    import shutil
    shutil.rmtree(pd)
    return {"ok": True}


@app.get("/presets")
def view_presets_index():
    return render_template("presets/index.html")


@app.get("/presets/<pid>")
def view_preset_detail(pid: str):
    pd = _preset_dir(pid)
    if not pd.exists():
        abort(404)
    return render_template("presets/detail.html", preset_id=pid)
```

- [ ] **Step 4:** 把 `web/templates/genres/` 改名为 `web/templates/presets/`（`git mv`），编辑每个模板的文案（搜"题材"改为"预设"或保留；但 URL 必须改）：
  - `index.html`：列表，`fetch('/api/presets')`
  - `detail.html`：`<h1>预设 {preset_id}</h1>`，显示文件 + novels + 删除按钮（内置 disabled）
  - 删除 `new.html`（裸建页）
  - `extract.html` 改名为 `new-from-novel.html`（下一 task 用）
  - `_base.html` / `progress.html` 保留

用脚本替换：

```bash
git mv web/templates/genres web/templates/presets
# 删除裸建页
git rm web/templates/presets/new.html
```

并把模板内的 `/genres` / `/api/genres` 字串改为 `/presets` / `/api/presets`（用 python 脚本，排除历史文档）：

```bash
.venv/bin/python3 <<'PY'
from pathlib import Path
for p in Path("web/templates/presets").rglob("*.html"):
    t = p.read_text(encoding="utf-8")
    new = t.replace("/api/genres", "/api/presets").replace("'/genres", "'/presets").replace('"/genres', '"/presets').replace(">/genres<", ">/presets<")
    if new != t:
        p.write_text(new, encoding="utf-8")
        print("patched", p)
PY
```

- [ ] **Step 5:** `git mv web/static/genres.css web/static/presets.css` + `git mv web/static/genres.js web/static/presets.js`，同步修模板里的 `<link>` / `<script>` 引用。

- [ ] **Step 6:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_web_presets_api.py -v 2>&1 | tail -15
```

- [ ] **Step 7:** Commit

```bash
git add -A
git commit -m "feat(phase4): /presets API (list/detail/delete) + rename templates/static"
```

---

## Task 4.2 · `POST /api/presets/new-from-novel` 异步拆新 preset

**Files:**
- Modify: `web/app.py`
- Modify: `web/templates/presets/new-from-novel.html`（表单从大池子勾选）
- Create: 追加到 `tests/test_web_presets_api.py`

- [ ] **Step 1:** 写测试（追加）：

```python
def test_post_new_preset_from_novel_requires_sources(app_with_presets):
    r = app_with_presets.post("/api/presets/new-from-novel", json={"id": "newp"})
    assert r.status_code == 400
    assert "sources" in r.get_json()["reason"].lower()


def test_post_new_preset_from_novel_rejects_existing(app_with_presets, tmp_path):
    r = app_with_presets.post("/api/presets/new-from-novel", json={
        "id": "gangster-hk-1983",
        "sources": ["foo.txt"],
    })
    assert r.status_code == 409


def test_post_new_preset_from_novel_schedules_job(app_with_presets, monkeypatch):
    # Create source in pool
    (app_with_presets.application.config['_tmpdir'] := None)  # noop; use monkeypatch below
    from src import config
    (config.PROJECT_ROOT / "novels" / "src1.txt").write_text("x", encoding="utf-8")

    # Avoid real LLM by stubbing extract_to_preset
    captured = {}
    def fake_extract_to_preset(preset_id, *, sources, with_trial):
        captured.update(preset_id=preset_id, sources=sources)
        return {"preset_id": preset_id}
    monkeypatch.setattr("src.genre_extractor.to_preset.extract_to_preset", fake_extract_to_preset)

    r = app_with_presets.post("/api/presets/new-from-novel", json={
        "id": "new-preset",
        "sources": ["src1.txt"],
    })
    assert r.status_code == 202  # accepted, running in background
    # Wait for background job (polling pattern)
    import time
    for _ in range(20):
        s = app_with_presets.get("/api/presets/new-preset/status").get_json()
        if s.get("state") == "done":
            break
        time.sleep(0.05)
    assert captured["preset_id"] == "new-preset"
```

注：该 fixture 可能需要调整—实际实现时，测试可以不通过 Flask 路由触发后台，而是直接调函数。保留 happy path 测一个就够。

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_web_presets_api.py -v 2>&1 | tail -15
```

- [ ] **Step 3:** 改 `web/app.py`：

```python
# Track preset extraction jobs: preset_id -> {"state": "running|done|failed", "error": str|None}
_PRESET_JOBS: dict[str, dict] = {}
_PRESET_JOB_LOCK = threading.Lock()


@app.post("/api/presets/new-from-novel")
def api_preset_new_from_novel():
    body = request.get_json(silent=True) or {}
    pid = (body.get("id") or "").strip()
    sources = body.get("sources") or []
    if not pid:
        return {"ok": False, "reason": "id required"}, 400
    if not sources:
        return {"ok": False, "reason": "sources required"}, 400
    if _preset_dir(pid).exists():
        return {"ok": False, "reason": "preset already exists"}, 409

    with _PRESET_JOB_LOCK:
        if pid in _PRESET_JOBS and _PRESET_JOBS[pid].get("state") == "running":
            return {"ok": False, "reason": "job already running"}, 409
        _PRESET_JOBS[pid] = {"state": "running", "error": None}

    def worker():
        try:
            from src.genre_extractor import to_preset
            to_preset.extract_to_preset(
                pid,
                sources=sources,
                with_trial=bool(body.get("with_trial", False)),
            )
            with _PRESET_JOB_LOCK:
                _PRESET_JOBS[pid] = {"state": "done", "error": None}
        except Exception as e:
            with _PRESET_JOB_LOCK:
                _PRESET_JOBS[pid] = {"state": "failed", "error": str(e)}

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return {"ok": True, "preset_id": pid, "state": "running"}, 202


@app.get("/api/presets/<pid>/status")
def api_preset_status(pid: str):
    with _PRESET_JOB_LOCK:
        job = _PRESET_JOBS.get(pid)
    if job is None:
        # no job recorded — maybe already finished in previous process
        return {"state": "unknown"}
    return {**job, "preset_id": pid}
```

- [ ] **Step 4:** 改模板 `web/templates/presets/new-from-novel.html`：表单从 `/api/novels` 读取池子中的 txt，渲染 checkbox 列表，用户勾选后 POST 到 `/api/presets/new-from-novel`，然后跳到 progress 页轮询。

关键 HTML（简化）：

```html
{% extends "presets/_base.html" %}
{% block body %}
<h1>从原著拆出新 preset</h1>
<form id="form-new-preset">
  <label>Preset ID <input name="id" required pattern="[a-z0-9][a-z0-9_-]{0,62}"></label>
  <label>从大池子 /novels 勾选素材：</label>
  <div id="novel-checkboxes">加载中…</div>
  <label><input type="checkbox" name="with_trial"> 跑 3 章试验书（慢）</label>
  <button type="submit">▶ 启动拆解</button>
</form>
<script type="module" src="/static/presets.js"></script>
{% endblock %}
```

`presets.js` 里的 `loadNovelsPool()` 函数：fetch `/api/novels`，渲染 checkbox，submit 时把勾中的 name 作为 `sources`。

- [ ] **Step 5:** 跑测试 + commit

```bash
.venv/bin/python3 -m pytest tests/test_web_presets_api.py -v 2>&1 | tail -15
git add -A
git commit -m "feat(phase4): POST /api/presets/new-from-novel runs to_preset in background"
```

---

## Task 4.3 · `POST /api/projects/new` 4 步向导

**Files:**
- Modify: `web/app.py`（现存 `api_project_new`）
- Modify: `web/templates/index.html`（向导模板扩展第 2-4 步）
- Modify: `web/static/main.js`（向导 JS）
- Create: `tests/test_web_project_new_wizard.py`

- [ ] **Step 1:** 写 `tests/test_web_project_new_wizard.py`：

```python
"""POST /api/projects/new: 4-step wizard fields."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app_(tmp_path: Path, monkeypatch):
    from src import config
    (tmp_path / "presets" / "alpha").mkdir(parents=True)
    (tmp_path / "presets" / "alpha" / "genre.yaml").write_text("id: alpha\n", encoding="utf-8")
    for f in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        (tmp_path / "presets" / "alpha" / f).write_text("x\n", encoding="utf-8")
    (tmp_path / "presets" / "alpha" / "novels").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "novels").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")
    from web import app as web_app
    return web_app.app.test_client()


def test_wizard_blank_all(app_):
    r = app_.post("/api/projects/new", json={
        "id": "b1", "display_name": "B1", "protagonist_name": "H",
        "chapter_count_target": 10, "blank_genre": True,
        "blank_outline": True, "blank_characters": True,
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["project_id"] == "b1"


def test_wizard_from_preset(app_):
    r = app_.post("/api/projects/new", json={
        "id": "b2", "display_name": "B2", "protagonist_name": "H",
        "chapter_count_target": 5, "from_preset": "alpha",
        "blank_outline": True, "blank_characters": True,
    })
    assert r.status_code == 200


def test_wizard_with_synopsis_and_brief(app_, monkeypatch):
    monkeypatch.setattr(
        "src.agents.outline_drafter.OutlineDrafter.run",
        lambda self, *, synopsis, chapter_count_target, display_name: {
            "title": display_name,
            "chapters": [{"index": 1, "title": "c1", "beats": ["x"]}],
        },
    )
    monkeypatch.setattr(
        "src.agents.characters_drafter.CharactersDrafter.run",
        lambda self, *, brief, protagonist_name: {
            "protagonist": {"name": protagonist_name, "description": "d"},
            "supporting": [],
        },
    )
    r = app_.post("/api/projects/new", json={
        "id": "b3", "display_name": "B3", "protagonist_name": "H",
        "chapter_count_target": 3, "from_preset": "alpha",
        "outline_synopsis": "some story",
        "characters_brief": "some people",
    })
    assert r.status_code == 200


def test_wizard_with_extract_runs_in_background(app_, monkeypatch):
    called = {}
    def fake_extract(book_id, *, sources, with_trial):
        called.update(book_id=book_id, sources=list(sources))
    monkeypatch.setattr("src.genre_extractor.to_project.extract_to_project", fake_extract)

    (app_.application.config.get('_root') or Path.cwd())  # no-op; use fixture's pool
    from src import config
    (config.PROJECT_ROOT / "novels" / "seed.txt").write_text("x", encoding="utf-8")

    r = app_.post("/api/projects/new", json={
        "id": "b4", "display_name": "B4", "protagonist_name": "H",
        "chapter_count_target": 3,
        "from_extract": {"sources": ["seed.txt"], "with_trial": False},
        "blank_outline": True, "blank_characters": True,
    })
    assert r.status_code == 202  # async
    import time
    for _ in range(20):
        s = app_.get("/api/projects/b4/extract-genre/progress").get_json()
        if s.get("state") in ("done", "failed"):
            break
        time.sleep(0.05)
    assert called.get("book_id") == "b4"


def test_wizard_missing_required_fields(app_):
    r = app_.post("/api/projects/new", json={"id": "nodash"})
    assert r.status_code == 400


def test_wizard_mutually_exclusive_genre_flags(app_):
    r = app_.post("/api/projects/new", json={
        "id": "bad", "display_name": "d", "protagonist_name": "h",
        "chapter_count_target": 3,
        "from_preset": "alpha", "blank_genre": True,
        "blank_outline": True, "blank_characters": True,
    })
    assert r.status_code == 400
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_web_project_new_wizard.py -v 2>&1 | tail -15
```

- [ ] **Step 3:** 重写 `web/app.py` 的 `api_project_new`：

```python
# Track per-book extract-genre jobs
_PROJECT_JOBS: dict[str, dict] = {}
_PROJECT_JOB_LOCK = threading.Lock()


@app.post("/api/projects/new")
def api_project_new():
    body = request.get_json(silent=True) or {}
    required = ("id", "display_name", "protagonist_name", "chapter_count_target")
    for f in required:
        if not body.get(f):
            return {"ok": False, "reason": f"{f} required"}, 400
    try:
        from src.bootstrap import create_project, bootstrap_project
        # detect from_extract → go async
        from_extract = body.get("from_extract")
        if from_extract and from_extract.get("sources"):
            # Skeleton project first (blank_genre + blank_outline + blank_characters),
            # then kick extraction in background.
            create_project(
                body["id"],
                display_name=body["display_name"],
                protagonist_name=body["protagonist_name"],
                chapter_count_target=int(body["chapter_count_target"]),
                blank_genre=True,
                blank_outline=True,
                blank_characters=True,
            )
            with _PROJECT_JOB_LOCK:
                _PROJECT_JOBS[body["id"]] = {"state": "running", "error": None}

            def worker():
                try:
                    from src.genre_extractor import to_project as to_proj
                    to_proj.extract_to_project(
                        body["id"],
                        sources=from_extract["sources"],
                        with_trial=bool(from_extract.get("with_trial", False)),
                    )
                    with _PROJECT_JOB_LOCK:
                        _PROJECT_JOBS[body["id"]] = {"state": "done", "error": None}
                except Exception as e:
                    with _PROJECT_JOB_LOCK:
                        _PROJECT_JOBS[body["id"]] = {"state": "failed", "error": str(e)}

            t = threading.Thread(target=worker, daemon=True)
            t.start()
            return {"ok": True, "project_id": body["id"], "state": "extracting"}, 202

        # Synchronous path
        create_project(
            body["id"],
            display_name=body["display_name"],
            protagonist_name=body["protagonist_name"],
            chapter_count_target=int(body["chapter_count_target"]),
            from_preset=body.get("from_preset"),
            blank_genre=bool(body.get("blank_genre", False)),
            outline_synopsis=body.get("outline_synopsis"),
            blank_outline=bool(body.get("blank_outline", False)),
            characters_brief=body.get("characters_brief"),
            blank_characters=bool(body.get("blank_characters", False)),
        )
        bootstrap_project(body["id"])
    except ValueError as e:
        return {"ok": False, "reason": str(e)}, 400
    except FileNotFoundError as e:
        return {"ok": False, "reason": str(e)}, 404
    except FileExistsError as e:
        return {"ok": False, "reason": str(e)}, 409
    return {"ok": True, "project_id": body["id"]}
```

- [ ] **Step 4:** 跑测试 + commit

```bash
.venv/bin/python3 -m pytest tests/test_web_project_new_wizard.py -v 2>&1 | tail -15
git add web/app.py tests/test_web_project_new_wizard.py
git commit -m "feat(phase4): POST /api/projects/new accepts 4-step wizard fields + async extract"
```

---

## Task 4.4 · `POST /api/projects/<id>/extract-genre` 重覆

**Files:**
- Modify: `web/app.py`
- Create: `tests/test_web_project_extract_genre.py`

- [ ] **Step 1:** 写测试：

```python
"""Post-creation: overwrite a book's genre files from novels pool."""
from __future__ import annotations

from pathlib import Path
import time

import pytest


@pytest.fixture
def app_with_book(tmp_path: Path, monkeypatch):
    from src import config, bootstrap
    (tmp_path / "presets" / "alpha").mkdir(parents=True)
    for f in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        (tmp_path / "presets" / "alpha" / f).write_text("x\n", encoding="utf-8")
    (tmp_path / "presets" / "alpha" / "genre.yaml").write_text("id: alpha\n", encoding="utf-8")
    (tmp_path / "presets" / "alpha" / "novels").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "novels").mkdir()
    (tmp_path / "novels" / "seed.txt").write_text("x", encoding="utf-8")

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")

    bootstrap.create_project(
        "mybook", display_name="B", protagonist_name="H", chapter_count_target=3,
        from_preset="alpha", blank_outline=True, blank_characters=True,
    )

    from web import app as web_app
    return web_app.app.test_client()


def test_extract_genre_triggers_async(app_with_book, monkeypatch):
    captured = {}
    def fake_extract(book_id, *, sources, with_trial):
        captured.update(book_id=book_id, sources=sources)
    monkeypatch.setattr("src.genre_extractor.to_project.extract_to_project", fake_extract)

    r = app_with_book.post("/api/projects/mybook/extract-genre", json={
        "sources": ["seed.txt"],
    })
    assert r.status_code == 202

    for _ in range(20):
        s = app_with_book.get("/api/projects/mybook/extract-genre/progress").get_json()
        if s.get("state") == "done":
            break
        time.sleep(0.05)
    assert captured.get("book_id") == "mybook"


def test_extract_genre_404_for_missing_book(app_with_book):
    r = app_with_book.post("/api/projects/nope/extract-genre", json={"sources": ["x.txt"]})
    assert r.status_code == 404


def test_extract_genre_requires_sources(app_with_book):
    r = app_with_book.post("/api/projects/mybook/extract-genre", json={})
    assert r.status_code == 400
```

- [ ] **Step 2:** 跑失败 + 实现路由：

```python
@app.post("/api/projects/<pid>/extract-genre")
def api_project_extract_genre(pid: str):
    project_dir = config.PROJECTS_DIR / pid
    if not project_dir.exists():
        return {"ok": False, "reason": "project not found"}, 404
    body = request.get_json(silent=True) or {}
    sources = body.get("sources") or []
    if not sources:
        return {"ok": False, "reason": "sources required"}, 400

    with _PROJECT_JOB_LOCK:
        _PROJECT_JOBS[pid] = {"state": "running", "error": None}

    def worker():
        try:
            from src.genre_extractor import to_project
            to_project.extract_to_project(
                pid,
                sources=sources,
                with_trial=bool(body.get("with_trial", False)),
            )
            # re-bootstrap if currently active
            if config.get_active_project_id() == pid:
                from src.bootstrap import bootstrap_project
                bootstrap_project(pid, preserve_progress=True)
            with _PROJECT_JOB_LOCK:
                _PROJECT_JOBS[pid] = {"state": "done", "error": None}
        except Exception as e:
            with _PROJECT_JOB_LOCK:
                _PROJECT_JOBS[pid] = {"state": "failed", "error": str(e)}

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return {"ok": True, "state": "running"}, 202


@app.get("/api/projects/<pid>/extract-genre/progress")
def api_project_extract_progress(pid: str):
    with _PROJECT_JOB_LOCK:
        job = _PROJECT_JOBS.get(pid)
    return {"state": (job or {}).get("state", "unknown"),
            "error": (job or {}).get("error")}


@app.post("/api/projects/<pid>/extract-genre/abort")
def api_project_extract_abort(pid: str):
    # Soft abort: set a flag; extractor checks it between phases.
    # For now, just mark the job state so UI stops polling.
    with _PROJECT_JOB_LOCK:
        if pid in _PROJECT_JOBS:
            _PROJECT_JOBS[pid] = {"state": "aborted", "error": None}
    return {"ok": True}
```

- [ ] **Step 3:** 跑测试 + commit

```bash
.venv/bin/python3 -m pytest tests/test_web_project_extract_genre.py -v 2>&1 | tail -10
git add web/app.py tests/test_web_project_extract_genre.py
git commit -m "feat(phase4): POST /api/projects/<id>/extract-genre + progress + abort"
```

---

## Task 4.5 · `/draft-outline` + `/draft-characters` 端点

**Files:**
- Modify: `web/app.py`
- Create: `tests/test_web_draft_endpoints.py`

- [ ] **Step 1:** 写测试：

```python
"""/api/projects/<id>/draft-{outline,characters} endpoints."""
from __future__ import annotations

from pathlib import Path

import json
import pytest
import yaml


@pytest.fixture
def app_with_book(tmp_path: Path, monkeypatch):
    from src import config, bootstrap
    (tmp_path / "presets" / "alpha").mkdir(parents=True)
    for f in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        (tmp_path / "presets" / "alpha" / f).write_text("x\n", encoding="utf-8")
    (tmp_path / "presets" / "alpha" / "genre.yaml").write_text("id: alpha\n", encoding="utf-8")
    (tmp_path / "presets" / "alpha" / "novels").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "novels").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")
    bootstrap.create_project(
        "mybook", display_name="B", protagonist_name="H", chapter_count_target=3,
        from_preset="alpha", blank_outline=True, blank_characters=True,
    )
    from web import app as web_app
    return web_app.app.test_client()


def test_draft_outline(app_with_book, monkeypatch):
    monkeypatch.setattr(
        "src.agents.outline_drafter.OutlineDrafter.run",
        lambda self, *, synopsis, chapter_count_target, display_name: {
            "title": display_name,
            "chapters": [{"index": 1, "title": "c1", "beats": ["x"]}],
        },
    )
    r = app_with_book.post("/api/projects/mybook/draft-outline", json={
        "synopsis": "something",
    })
    assert r.status_code == 200
    assert r.get_json()["chapters"][0]["title"] == "c1"


def test_draft_characters(app_with_book, monkeypatch):
    monkeypatch.setattr(
        "src.agents.characters_drafter.CharactersDrafter.run",
        lambda self, *, brief, protagonist_name: {
            "protagonist": {"name": protagonist_name, "description": "d"},
            "supporting": [{"name": "A", "role": "r", "description": "d"}],
        },
    )
    r = app_with_book.post("/api/projects/mybook/draft-characters", json={
        "brief": "people",
    })
    assert r.status_code == 200
    assert len(r.get_json()["supporting"]) == 1


def test_draft_outline_404(app_with_book):
    r = app_with_book.post("/api/projects/nope/draft-outline", json={"synopsis": "x"})
    assert r.status_code == 404
```

- [ ] **Step 2:** 实现：

```python
@app.post("/api/projects/<pid>/draft-outline")
def api_project_draft_outline(pid: str):
    if not (config.PROJECTS_DIR / pid).exists():
        return {"ok": False, "reason": "project not found"}, 404
    body = request.get_json(silent=True) or {}
    synopsis = body.get("synopsis", "")
    from src.pipeline import run_draft_outline
    try:
        out = run_draft_outline(pid, synopsis=synopsis)
    except Exception as e:
        return {"ok": False, "reason": str(e)}, 500
    return out


@app.post("/api/projects/<pid>/draft-characters")
def api_project_draft_characters(pid: str):
    if not (config.PROJECTS_DIR / pid).exists():
        return {"ok": False, "reason": "project not found"}, 404
    body = request.get_json(silent=True) or {}
    brief = body.get("brief", "")
    from src.pipeline import run_draft_characters
    try:
        out = run_draft_characters(pid, brief=brief)
    except Exception as e:
        return {"ok": False, "reason": str(e)}, 500
    return out
```

- [ ] **Step 3:** 跑测试 + commit

```bash
.venv/bin/python3 -m pytest tests/test_web_draft_endpoints.py -v 2>&1 | tail -10
git add web/app.py tests/test_web_draft_endpoints.py
git commit -m "feat(phase4): /api/projects/<id>/draft-outline + draft-characters"
```

---

## Task 4.6 · `/api/novels` 新增 `used_by_presets` + 二次确认删除

**Files:**
- Modify: `web/app.py`（`api_novels_list` / `api_novels_delete`）
- Create: `tests/test_web_novels_usage.py`

- [ ] **Step 1:** 写测试：

```python
"""/api/novels: used_by_presets + confirm-before-delete."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app_(tmp_path: Path, monkeypatch):
    from src import config
    # preset alpha uses a.txt; beta uses nothing
    for gid in ("alpha", "beta"):
        pd = tmp_path / "presets" / gid
        pd.mkdir(parents=True)
        (pd / "genre.yaml").write_text(f"id: {gid}\n", encoding="utf-8")
        (pd / "era.md").write_text("x\n", encoding="utf-8")
        (pd / "novels").mkdir()
    # alpha has a.txt in its novels/
    (tmp_path / "presets" / "alpha" / "novels" / "a.txt").write_text("x", encoding="utf-8")
    # Pool
    (tmp_path / "novels").mkdir()
    (tmp_path / "novels" / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "novels" / "b.txt").write_text("x", encoding="utf-8")
    (tmp_path / "projects").mkdir()

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")
    from web import app as web_app
    return web_app.app.test_client()


def test_novels_list_has_used_by_presets(app_):
    data = app_.get("/api/novels").get_json()
    by_name = {n["name"]: n for n in data["novels"]}
    assert by_name["a.txt"]["used_by_presets"] == ["alpha"]
    assert by_name["b.txt"]["used_by_presets"] == []


def test_novels_delete_unused_straight(app_):
    r = app_.delete("/api/novels/b.txt")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_novels_delete_used_warns_then_force(app_):
    # first call: warning + refused
    r1 = app_.delete("/api/novels/a.txt")
    assert r1.status_code == 409
    data = r1.get_json()
    assert data["ok"] is False
    assert data["used_by_presets"] == ["alpha"]
    # Confirm with force
    r2 = app_.delete("/api/novels/a.txt?force=true")
    assert r2.status_code == 200
    assert r2.get_json()["ok"] is True
```

- [ ] **Step 2:** 改 `web/app.py`：

```python
def _novel_used_by_presets(name: str) -> list[str]:
    used = []
    if not config.PRESETS_DIR.exists():
        return used
    for p in sorted(config.PRESETS_DIR.iterdir()):
        if p.is_dir() and (p / "novels" / name).exists():
            used.append(p.name)
    return used


@app.get("/api/novels")
def api_novels_list():
    pool = config.PROJECT_ROOT / "novels"
    items = []
    if pool.exists():
        for f in sorted(pool.iterdir()):
            if not f.is_file() or f.suffix != ".txt":
                continue
            st = f.stat()
            items.append({
                "name": f.name,
                "size": st.st_size,
                "size_human": _human_size(st.st_size),
                "used_by_presets": _novel_used_by_presets(f.name),
            })
    return {"novels": items}


@app.delete("/api/novels/<path:name>")
def api_novels_delete(name: str):
    force = request.args.get("force") == "true"
    path = _resolve_novel_or_abort(name)  # existing helper
    used = _novel_used_by_presets(path.name)
    if used and not force:
        return {
            "ok": False,
            "reason": "novel is used by presets; pass ?force=true to confirm",
            "used_by_presets": used,
        }, 409
    path.unlink()
    return {"ok": True}
```

- [ ] **Step 3:** 跑测试 + commit

```bash
.venv/bin/python3 -m pytest tests/test_web_novels_usage.py -v 2>&1 | tail -10
git add web/app.py tests/test_web_novels_usage.py
git commit -m "feat(phase4): /api/novels exposes used_by_presets + confirm-on-delete"
```

---

## Task 4.7 · 作品首页 UI：向导 4 步 + 覆盖题材入口

**Files:**
- Modify: `web/templates/index.html`
- Modify: `web/static/main.js`

本 task 无法用 backend 测试完全覆盖；用**结构断言**保证模板含关键 DOM id，再配合 E2E 手测验。

- [ ] **Step 1:** 在 `tests/test_web_and_pages_sync.py` 追加结构断言：

```python
def test_index_html_has_wizard_4_steps():
    """New project wizard must have 4 steps with recognizable markers."""
    text = (config.PROJECT_ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'data-wizard-step="1"' in text
    assert 'data-wizard-step="2"' in text
    assert 'data-wizard-step="3"' in text
    assert 'data-wizard-step="4"' in text
    # Step 2: three options
    assert 'data-genre-starter="preset"' in text
    assert 'data-genre-starter="extract"' in text
    assert 'data-genre-starter="blank"' in text


def test_index_html_has_extract_genre_override_button():
    """The "覆盖当前题材配置" button must exist on the project main view."""
    text = (config.PROJECT_ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-extract-genre-override"' in text


def test_main_js_wires_wizard_and_extract_override():
    text = (config.PROJECT_ROOT / "web" / "static" / "main.js").read_text(encoding="utf-8")
    # Wizard submission helper
    assert "apiProjectNew" in text or "/api/projects/new" in text
    # Override extract-genre
    assert "/extract-genre" in text
```

- [ ] **Step 2:** 改模板 `web/templates/index.html`：
  - 把现有的"新建作品"dialog 扩展为 4 个 `data-wizard-step` 的 div（1 基本信息 / 2 题材起点 / 3 大纲 / 4 角色）
  - 第 2 步的 radio 组三选一，选"从 preset 拷贝"时 fetch `/api/presets` 渲染下拉；选"从原著拆"时 fetch `/api/novels` 渲染 checkbox；选"最小脚手架"时直接 disabled 其他
  - 新增 header 按钮 `<button id="btn-extract-genre-override" title="从原著覆盖当前题材配置">⎇ 覆盖题材</button>`，点击打开另一个 dialog：从 `/api/novels` 勾选 → POST `/api/projects/<id>/extract-genre` → 进度条轮询 `/extract-genre/progress`
  - 第 3 步 textarea：`<textarea name="outline_synopsis" placeholder="粘贴故事梗概…">` + 「跳过（空壳）」checkbox `<input type="checkbox" name="blank_outline">`
  - 第 4 步类似：`<textarea name="characters_brief">` + `<input type="checkbox" name="blank_characters">`

- [ ] **Step 3:** 改 `web/static/main.js`：
  - 实现 `runWizardSubmit(form)`：收集 4 步字段，组 payload，POST `/api/projects/new`
  - 如果返回 202（async extract），跳向导到「正在拆解…」的 panel，轮询 `/api/projects/<id>/extract-genre/progress`
  - 实现 `runExtractGenreOverride()`：打开 dialog，fetch `/api/novels` 渲染 checkbox，submit → POST `/api/projects/<id>/extract-genre` → 轮询进度 → done 时关闭 dialog 并提示

- [ ] **Step 4:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_web_and_pages_sync.py -v 2>&1 | tail -10
```

- [ ] **Step 5:** Commit

```bash
git add web/templates/index.html web/static/main.js tests/test_web_and_pages_sync.py
git commit -m "feat(phase4): project wizard 4 steps + override-genre button"
```

---

## Task 4.8 · Phase 4 Checkpoint + 修旧测试

最后一个任务：处理几个旧测试文件的最终状态。

**Files:**
- Modify: `tests/test_web_genre_files_api.py`
- Modify: `tests/test_web_and_pages_sync.py`

- [ ] **Step 1:** `tests/test_web_genre_files_api.py`：因为 `/api/genres/<id>/files/*` 路由永远不会实现（spec §11 明确不做 preset 编辑），把文件改为直接 skip 整个模块并加注释：

```python
import pytest
pytestmark = pytest.mark.skip(reason="preset editing is intentionally not supported — see docs/superpowers/specs/book-centric-workflow-design.md §11")
```

或直接 `git rm tests/test_web_genre_files_api.py`。推荐**删除**——代码里这路由已不存在，测试留着无意义。

- [ ] **Step 2:** `tests/test_web_and_pages_sync.py`：
  - `test_api_file_serves_new_info_priority_rule` 保留
  - `test_snapshot_has_bookkeeping_sample` 保留（docs demo snapshot 不变）
  - 如果有引用 `/api/genres` 的断言，改为 `/api/presets` 或移除
  - 如果有 `test_docs_main_js_declares_new_agents`，确保它还对 outline_drafter / characters_drafter 友好（若不重要可不管）

- [ ] **Step 3:** 跑整 phase checkpoint

```bash
set -e
.venv/bin/python3 -m pytest tests/test_web_presets_api.py tests/test_web_project_new_wizard.py tests/test_web_project_extract_genre.py tests/test_web_draft_endpoints.py tests/test_web_novels_usage.py -v
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py
```

**退出码 0 表示 Phase 4 通过，可进 Phase 5。**

- [ ] **Step 4:** Commit

```bash
git add -A
git commit -m "test(phase4): remove obsolete genre-files API tests, clean up sync tests"
```
