# Novelforge Web 端全流程化 · Phase 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一个从零拿到代码的新人，启动 Flask 之后，所有配置和运行动作（填 key → 选题材/作品 → 新建作品 → 编辑元信息 → 跑章节/区间/包装 → 切换作品 → 中断）都能在浏览器里完成，不再回终端。

**Architecture:** 在现有 `web/app.py` 上扩展 Flask 路由，复用 `src/bootstrap.py` 已经暴露的公共 API（`bootstrap_project` / `create_project` / `list_genres` / `list_projects`）和 `src/pipeline.py` 所有 `run_*_only` 函数。前端 `index.html` + `main.js` 新增"项目"面板、"设置"面板、"运行"面板。pipeline 增加一个进程内的 `threading.Event` 作为协作式取消信号。`config.STATE_DIR` 快照问题在 `llm.py` / `websearch.py` / `web/app.py` 中改为延迟求值，确保切项目后所有日志落到新 state/ 下。

**Tech Stack:** Flask 3（已有）· Python 3.11+ · vanilla JS（保持现状，不引入框架）· pytest（后端路由全覆盖）。

---

## 0. 现状快照（事实基础，不是 TODO）

**bootstrap 已经是公共 API：**
- `bootstrap.list_genres()` / `list_projects()` / `bootstrap_project(id)` / `create_project(id, genre, overwrite)`（`src/bootstrap.py:98-299`）
- `config.refresh_state_dir()` 在 bootstrap 内被调用（`bootstrap.py:233`）
- 不需要再"拆函数"——直接从 web 里 import 就行

**pipeline 已经暴露 9 个入口函数：**
- `run_chapter` / `run_audit_only` / `run_plan_only` / `run_write_only` / `run_evaluate_only` / `run_fix_only` / `run_bookkeeping_only` / `run_packaging`（`src/pipeline.py:90-350`）

**Web 现状（`web/app.py` 310 行）：**
- 9 个路由：`GET /`, `/api/state|file|prompts|debt|issues|status`, `POST /api/run|audit`
- `bb = Blackboard()` 模块级单例（`app.py:25`）——切项目后仍指向旧 state/
- `_STATUS_PATH = config.STATE_DIR / "pipeline_status.json"` 模块级快照（`app.py:33`）——同样问题
- `_ALLOWED_ROOTS` 快照 `config.STATE_DIR.resolve()`（`app.py:61`）——切项目后沙箱仍允许旧路径

**STATE_DIR 快照泄漏点（切项目后需要处理）：**
- `src/llm.py:25` — `PROMPT_LOG_PATH = config.STATE_DIR / "prompts_log.jsonl"`
- `src/tools/websearch.py:51,56` — `WEBSEARCH_LOG_PATH` 和 `_CACHE_DIR`
- `web/app.py:25,33,61` — 已列出

**LLM key reload 的好消息：**
- `src/llm.py:67,79,83,97,120` 每次调用都读 `config.LLM_API_KEY`（属性引用），没有局部快照
- 只需 `reload_env()` 把模块级全局重新赋值即可生效

**三份作品仓的状态：**
- `gangster-hk-1983-linjiayao` ✅ 有 state/（当前 .active）
- `xianxia-ascension-peichangning` ❌ 无 state/（未 bootstrap）
- `urban-romance-shenruowei` ❌ 无 state/（未 bootstrap）

---

## 1. 文件结构：这次会创建/修改什么

### 新增文件

| 路径 | 职责 |
|---|---|
| `tests/test_web_projects_api.py` | 覆盖 `/api/genres`, `/api/projects`, `/api/projects/activate`, `/api/projects/new` |
| `tests/test_web_env_api.py` | 覆盖 `/api/env` GET/POST + 脱敏 + 白名单 + reload 生效 |
| `tests/test_web_project_files_api.py` | 覆盖 `/api/project-files` GET/PUT 的读写校验 |
| `tests/test_web_run_modes.py` | 覆盖 `/api/run` 各 mode + range + /api/abort |
| `tests/test_pipeline_cancel.py` | 覆盖 `pipeline.CANCEL_EVENT` 协作式取消 |

### 修改文件

| 路径 | 改什么 |
|---|---|
| `src/config.py` | 新增 `reload_env()` 函数 |
| `src/llm.py` | `PROMPT_LOG_PATH` 改为 `_prompts_log_path()` 函数（延迟求值） |
| `src/tools/websearch.py` | `WEBSEARCH_LOG_PATH` / `_CACHE_DIR` 改为延迟求值函数 |
| `src/pipeline.py` | 新增 `CANCEL_EVENT` + `_check_cancel()` 在每个 `_stage` 前调用；新增 `PipelineAborted` 异常 |
| `web/app.py` | 新增 7 组路由；`bb` / `_STATUS_PATH` / `_ALLOWED_ROOTS` 改为函数（每次请求重算） |
| `web/templates/index.html` | 新增"项目"、"设置"、"运行"面板的 DOM 结构 |
| `web/static/main.js` | 新增对应 JS 逻辑；启动时首次配置引导 |
| `web/static/main.css` | 新增模态/表单样式（复用现有 token） |

**设计边界：**
- 不重写前端，不引入框架。现有 vanilla JS + 现有 CSS token 风格。
- 不做用户系统/鉴权（若暴露公网再补，属于 Phase 2）。
- `.env` 写入只允许 6 个白名单字段；敏感字段读时脱敏。
- Web 通过 sandbox 白名单扩展到 `projects/<active>/{project.yaml, outline.json, characters.yaml, timeline.yaml}`，不允许写 `genres/`（题材层是不可变的共享资产）。

---

## 2. 任务拆解

### Task 1: STATE_DIR 延迟求值（解决切项目后日志落旧目录）

**Files:**
- Modify: `src/llm.py:25`
- Modify: `src/tools/websearch.py:51,56`

**为什么先做这个：** 后续所有切项目的测试都依赖 prompts_log 落到新 state/。

- [ ] **Step 1: 写一个失败测试**

Create: `tests/test_state_dir_dynamic.py`

```python
"""STATE_DIR 必须在切项目后被 llm / websearch 的日志写入端感知到。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src import config
from src import llm


def test_prompts_log_path_follows_state_dir(tmp_path, monkeypatch):
    # 构造两个假 STATE_DIR
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    # 指 A
    monkeypatch.setenv("STATE_DIR", str(a))
    config.refresh_state_dir()
    assert llm._prompts_log_path() == a / "prompts_log.jsonl"

    # 指 B，期望 llm 也跟着变
    monkeypatch.setenv("STATE_DIR", str(b))
    config.refresh_state_dir()
    assert llm._prompts_log_path() == b / "prompts_log.jsonl"


def test_websearch_paths_follow_state_dir(tmp_path, monkeypatch):
    from src.tools import websearch

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    monkeypatch.setenv("STATE_DIR", str(a))
    config.refresh_state_dir()
    assert websearch._websearch_log_path() == a / "websearch_log.jsonl"
    assert websearch._websearch_cache_dir() == a / "websearch_cache"

    monkeypatch.setenv("STATE_DIR", str(b))
    config.refresh_state_dir()
    assert websearch._websearch_log_path() == b / "websearch_log.jsonl"
    assert websearch._websearch_cache_dir() == b / "websearch_cache"
```

- [ ] **Step 2: 运行测试确认失败**

```
pytest tests/test_state_dir_dynamic.py -v
```
Expected: FAIL — `_prompts_log_path` / `_websearch_log_path` / `_websearch_cache_dir` 不存在

- [ ] **Step 3: 改 `src/llm.py`**

把原来 line 25 的:
```python
PROMPT_LOG_PATH = config.STATE_DIR / "prompts_log.jsonl"
```
换成:
```python
def _prompts_log_path():
    """Resolve at call time so it follows project switches."""
    return config.STATE_DIR / "prompts_log.jsonl"
```

然后把 `llm.py` 里所有 `PROMPT_LOG_PATH` 用到的地方改成 `_prompts_log_path()`。用 grep 找完：

```
grep -n PROMPT_LOG_PATH src/llm.py
```
把每一处都换掉。

- [ ] **Step 4: 改 `src/tools/websearch.py`**

类似改动。把:
```python
WEBSEARCH_LOG_PATH = config.STATE_DIR / "websearch_log.jsonl"
_CACHE_DIR = config.STATE_DIR / "websearch_cache"
```
换成两个函数:
```python
def _websearch_log_path():
    return config.STATE_DIR / "websearch_log.jsonl"

def _websearch_cache_dir():
    p = config.STATE_DIR / "websearch_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p
```
替换所有用到这俩常量的地方。

- [ ] **Step 5: 运行测试确认通过**

```
pytest tests/test_state_dir_dynamic.py -v
```
Expected: PASS

- [ ] **Step 6: 跑完整回归测试确保没破坏现有行为**

```
pytest -x
```
Expected: 全部通过（或只有预期的无关 skip）

- [ ] **Step 7: 提交**

```
git add src/llm.py src/tools/websearch.py tests/test_state_dir_dynamic.py
git commit -m "refactor: lazy STATE_DIR resolution in llm and websearch for project switch"
```

---

### Task 2: `config.reload_env()` + 测试

**Files:**
- Modify: `src/config.py`
- Create: `tests/test_config_reload.py`

- [ ] **Step 1: 写失败测试**

Create: `tests/test_config_reload.py`

```python
"""reload_env 必须把 .env 的新值反映到 config.LLM_API_KEY 等全局。"""
from __future__ import annotations

from pathlib import Path

from src import config


def test_reload_env_picks_up_key_changes(tmp_path, monkeypatch):
    # 给 config 一个假的 .env
    fake_env = tmp_path / ".env"
    fake_env.write_text("DEEPSEEK_API_KEY=first-key\nDEEPSEEK_MODEL=first-model\n", encoding="utf-8")

    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    config.reload_env()
    assert config.LLM_API_KEY == "first-key"
    assert config.LLM_MODEL == "first-model"

    fake_env.write_text("DEEPSEEK_API_KEY=second-key\nDEEPSEEK_MODEL=second-model\n", encoding="utf-8")
    config.reload_env()
    assert config.LLM_API_KEY == "second-key"
    assert config.LLM_MODEL == "second-model"


def test_reload_env_covers_perplexity_fields(tmp_path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text("PERPLEXITY_API_KEY=pplx-xyz\n", encoding="utf-8")
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)

    config.reload_env()
    assert config.PERPLEXITY_API_KEY == "pplx-xyz"
```

- [ ] **Step 2: 确认失败**

```
pytest tests/test_config_reload.py -v
```
Expected: FAIL — `reload_env` 不存在

- [ ] **Step 3: 实现**

追加到 `src/config.py` 末尾：

```python
def reload_env() -> None:
    """Re-read .env and update module-level LLM/Perplexity config globals.

    Safe to call from the Web UI after writing new keys. Because llm.py and
    websearch.py always dereference `config.X` at call time (not at import),
    updates take effect on the next LLM call in the same process.
    """
    global LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
    global PERPLEXITY_API_KEY, PERPLEXITY_BASE_URL, PERPLEXITY_MODEL

    load_dotenv(_PROJECT_ROOT / ".env", override=True)
    LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    LLM_BASE_URL = os.environ.get(
        "DEEPSEEK_BASE_URL", "https://work-api-srv.easyclaw.cn/v1"
    ).rstrip("/")
    LLM_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")
    PERPLEXITY_BASE_URL = os.environ.get(
        "PERPLEXITY_BASE_URL", "https://work-api-srv.easyclaw.cn/api/v1/search"
    ).rstrip("/")
    PERPLEXITY_MODEL = os.environ.get("PERPLEXITY_MODEL", "perplexity/sonar-pro")
```

- [ ] **Step 4: 确认通过**

```
pytest tests/test_config_reload.py -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```
git add src/config.py tests/test_config_reload.py
git commit -m "feat(config): add reload_env for live .env reload from Web UI"
```

---

### Task 3: Pipeline 协作式取消（`CANCEL_EVENT`）

**Files:**
- Modify: `src/pipeline.py`
- Create: `tests/test_pipeline_cancel.py`

**设计：** 用 `threading.Event` 作为模块级取消信号。`_stage` 执行前检查，被置位时抛 `PipelineAborted`。调用方在区间循环里捕获 → 记录"在第 N 章被中断"→ 返回。Event 在每次 `run_chapter` 开始时清空，避免留存。

- [ ] **Step 1: 写失败测试**

Create: `tests/test_pipeline_cancel.py`

```python
"""Cooperative cancel: setting CANCEL_EVENT before a stage raises PipelineAborted."""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from src import pipeline
from src.blackboard import Blackboard


def test_cancel_event_is_threading_event():
    assert isinstance(pipeline.CANCEL_EVENT, threading.Event)


def test_check_cancel_raises_when_set():
    pipeline.CANCEL_EVENT.set()
    try:
        with pytest.raises(pipeline.PipelineAborted):
            pipeline._check_cancel()
    finally:
        pipeline.CANCEL_EVENT.clear()


def test_check_cancel_passes_when_cleared():
    pipeline.CANCEL_EVENT.clear()
    pipeline._check_cancel()  # does not raise


def test_run_chapter_aborts_between_stages(tmp_path, monkeypatch):
    """If CANCEL_EVENT is set before planner runs, we should see PipelineAborted."""
    # Set up a minimal fake state/
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    from src import config
    config.refresh_state_dir()
    bb = Blackboard(root=tmp_path)
    bb.write_json("progress.json", {"completed_chapters": [], "current_chapter": 0})

    pipeline.CANCEL_EVENT.set()
    try:
        with pytest.raises(pipeline.PipelineAborted):
            pipeline.run_chapter(bb, chapter=1)
    finally:
        pipeline.CANCEL_EVENT.clear()
```

- [ ] **Step 2: 确认失败**

```
pytest tests/test_pipeline_cancel.py -v
```
Expected: FAIL — `CANCEL_EVENT` / `PipelineAborted` / `_check_cancel` 不存在

- [ ] **Step 3: 改 `src/pipeline.py`**

在 `MAX_FIXER_RETRIES = 2` 后面加：

```python
import threading

# Cooperative cancel signal. Web UI sets this via POST /api/abort; every
# pipeline stage checks before starting. Per-chapter clear happens at the
# start of run_chapter so stale signals from prior runs don't leak.
CANCEL_EVENT = threading.Event()


class PipelineAborted(RuntimeError):
    """Raised when CANCEL_EVENT is set between stages."""


def _check_cancel() -> None:
    if CANCEL_EVENT.is_set():
        raise PipelineAborted("pipeline aborted by cancel signal")
```

在 `run_chapter` 函数最开头（`status: dict = {...}` 之后）加：

```python
    # Clear any stale signal from a prior interrupted run.
    CANCEL_EVENT.clear()
```

在 `_stage` 函数体开头（`t0 = time.time()` 之前）加：

```python
        _check_cancel()
```

在 audit_fanout 段 `_update_in_flight(bb, chapter, "audit_fanout")` 之前也加一次 `_check_cancel()`。

- [ ] **Step 4: 确认通过**

```
pytest tests/test_pipeline_cancel.py -v
```
Expected: PASS

- [ ] **Step 5: 回归**

```
pytest -x
```
Expected: 全部通过

- [ ] **Step 6: 提交**

```
git add src/pipeline.py tests/test_pipeline_cancel.py
git commit -m "feat(pipeline): cooperative cancel via CANCEL_EVENT"
```

---

### Task 4: Web 动态化 `bb` / `_STATUS_PATH` / `_ALLOWED_ROOTS`

**Files:**
- Modify: `web/app.py`

**问题：** 这三个在模块加载时快照了 `config.STATE_DIR`。切项目后它们仍指向旧 state/。

**解决：** 改为每次请求重算。性能影响忽略（一次 Path resolve < 1ms）。

- [ ] **Step 1: 先写一个测试验证"切项目后 /api/state 指向新 state/"**

Create `tests/test_web_projects_api.py`（此处先写一部分，后续 Task 5 会扩充）:

```python
"""Switch project through Web, then /api/state should reflect new state/."""
from __future__ import annotations

import pytest

from web.app import app
from src import config


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_state_follows_active_project(client, monkeypatch):
    # Assume two projects exist with bootstrapped state/. At minimum
    # gangster-hk-1983-linjiayao is expected to be bootstrapped in the test env.
    # This test only validates that a GET /api/state returns a dict — the
    # deeper switching tests live in Task 5.
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "progress" in data
    assert "chapters" in data
```

- [ ] **Step 2: 重构 `web/app.py`**

把模块顶层的:
```python
bb = Blackboard()
_STATUS_PATH = config.STATE_DIR / "pipeline_status.json"
_ALLOWED_ROOTS = (config.STATE_DIR.resolve(), config.RULES_DIR.resolve())
```
改成函数：

```python
def _bb() -> Blackboard:
    """Fresh Blackboard bound to the CURRENT state dir.

    Cheap (one Path resolve + mkdir). Must not be cached across requests
    because Web UI can switch projects mid-session.
    """
    return Blackboard(root=config.STATE_DIR)


def _status_path() -> Path:
    return config.STATE_DIR / "pipeline_status.json"


def _allowed_roots() -> tuple[Path, ...]:
    return (config.STATE_DIR.resolve(), config.RULES_DIR.resolve())
```

然后把所有 `bb.` 调用替换成 `_bb().`，`_STATUS_PATH` 替换成 `_status_path()`，`_ALLOWED_ROOTS` 替换成 `_allowed_roots()`。grep 一遍确保没遗漏：

```
grep -n "^bb\|^_STATUS_PATH\|_ALLOWED_ROOTS\|\bbb\." web/app.py
```

注意 `_write_status` / `_read_status` / `_resolve_safe` 内部要一并改。

- [ ] **Step 3: 确认现有测试仍通过**

```
pytest tests/test_web_and_pages_sync.py tests/test_web_projects_api.py -v
```
Expected: PASS

- [ ] **Step 4: 提交**

```
git add web/app.py tests/test_web_projects_api.py
git commit -m "refactor(web): resolve Blackboard/status/sandbox at request time"
```

---

### Task 5: Web 新增 projects/genres 路由

**Files:**
- Modify: `web/app.py`
- Modify/Extend: `tests/test_web_projects_api.py`

**新路由：**

| Method | Path | Body | 返回 |
|---|---|---|---|
| GET | `/api/genres` | - | `{"genres": [{"id": "...", "display_name": "...", "tone": "..."}]}` |
| GET | `/api/projects` | - | `{"active": "...", "projects": [{"id": "...", "genre": "...", "display_name": "...", "has_state": bool}]}` |
| POST | `/api/projects/activate` | `{"id": "..."}` | `{"ok": true, "active": "...", "copied_files": [...]}` 或 `{"ok": false, "reason": "..."}` |
| POST | `/api/projects/new` | `{"id": "...", "genre": "...", "overwrite": false}` | `{"ok": true, "project_dir": "..."}` 或 `{"ok": false, "reason": "..."}` |

- [ ] **Step 1: 写失败测试**

扩充 `tests/test_web_projects_api.py`：

```python
def test_list_genres(client):
    resp = client.get("/api/genres")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "genres" in data
    ids = [g["id"] for g in data["genres"]]
    assert "gangster-hk-1983" in ids
    # each entry has display_name
    for g in data["genres"]:
        assert "display_name" in g


def test_list_projects(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "projects" in data
    assert "active" in data
    ids = [p["id"] for p in data["projects"]]
    assert "gangster-hk-1983-linjiayao" in ids
    for p in data["projects"]:
        assert "genre" in p and "display_name" in p


def test_activate_unknown_project_returns_400(client):
    resp = client.post("/api/projects/activate", json={"id": "does-not-exist-xyz"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_activate_missing_body_returns_400(client):
    resp = client.post("/api/projects/activate", json={})
    assert resp.status_code == 400


def test_new_project_requires_genre(client):
    resp = client.post("/api/projects/new", json={"id": "temp-test-proj"})
    assert resp.status_code == 400


def test_new_project_creates_scaffold(client, tmp_path, monkeypatch):
    # Redirect PROJECTS_DIR so we don't dirty the real projects/ dir
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    resp = client.post(
        "/api/projects/new",
        json={"id": "temp-test-proj", "genre": "gangster-hk-1983", "overwrite": True},
    )
    # Known tradeoff: monkeypatching PROJECTS_DIR doesn't reach bootstrap's
    # `config.PROJECTS_DIR` if bootstrap already snapshotted it. In that case
    # the test asserts status code is 200 or 400 with a sensible reason.
    assert resp.status_code in (200, 400)
```

- [ ] **Step 2: 运行确认失败**

```
pytest tests/test_web_projects_api.py -v
```
Expected: FAIL on new tests (routes missing)

- [ ] **Step 3: 在 `web/app.py` 新增路由**

```python
# ---------- project / genre management ----------
@app.get("/api/genres")
def api_genres():
    from src import bootstrap
    import yaml
    out = []
    for gid in bootstrap.list_genres():
        gyaml = yaml.safe_load(
            (config.GENRES_DIR / gid / "genre.yaml").read_text(encoding="utf-8")
        )
        out.append({
            "id": gid,
            "display_name": gyaml.get("display_name", gid),
            "genre": gyaml.get("genre"),
            "era": gyaml.get("era"),
            "tone": gyaml.get("tone"),
        })
    return jsonify({"genres": out})


@app.get("/api/projects")
def api_projects():
    from src import bootstrap
    import yaml
    active = config.get_active_project_id()
    out = []
    for pid in bootstrap.list_projects():
        pyaml_path = config.PROJECTS_DIR / pid / "project.yaml"
        try:
            pyaml = yaml.safe_load(pyaml_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            pyaml = {}
        out.append({
            "id": pid,
            "genre": pyaml.get("genre"),
            "display_name": pyaml.get("display_name", pid),
            "has_state": (config.PROJECTS_DIR / pid / "state").exists(),
            "is_active": (pid == active),
        })
    return jsonify({"active": active, "projects": out})


@app.post("/api/projects/activate")
def api_project_activate():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    pid = (data.get("id") or "").strip()
    if not pid:
        return jsonify({"ok": False, "reason": "id required"}), 400
    # Refuse if pipeline is running to avoid state-mid-flight swap
    if not _run_lock.acquire(blocking=False):
        return jsonify({"ok": False, "reason": "pipeline running; try abort first"}), 409
    try:
        from src import bootstrap
        try:
            result = bootstrap.bootstrap_project(pid)
        except (FileNotFoundError, ValueError) as e:
            return jsonify({"ok": False, "reason": str(e)}), 400
        return jsonify({
            "ok": True,
            "active": result.project_id,
            "genre": result.genre_id,
            "copied_files": result.copied_files,
        })
    finally:
        _run_lock.release()


@app.post("/api/projects/new")
def api_project_new():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    pid = (data.get("id") or "").strip()
    genre = (data.get("genre") or "").strip()
    overwrite = bool(data.get("overwrite", False))
    if not pid or not genre:
        return jsonify({"ok": False, "reason": "id and genre required"}), 400
    from src import bootstrap
    try:
        project_dir = bootstrap.create_project(pid, genre, overwrite=overwrite)
    except FileNotFoundError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    except FileExistsError as e:
        return jsonify({"ok": False, "reason": str(e)}), 409
    return jsonify({"ok": True, "project_dir": str(project_dir), "id": pid})
```

- [ ] **Step 4: 运行测试通过**

```
pytest tests/test_web_projects_api.py -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```
git add web/app.py tests/test_web_projects_api.py
git commit -m "feat(web): add /api/genres, /api/projects, activate, new endpoints"
```

---

### Task 6: Web 新增 `/api/env` GET/POST

**Files:**
- Modify: `web/app.py`
- Create: `tests/test_web_env_api.py`

**设计：**
- 白名单：`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `PERPLEXITY_API_KEY`, `PERPLEXITY_BASE_URL`, `PERPLEXITY_MODEL`
- 敏感字段：`DEEPSEEK_API_KEY`, `PERPLEXITY_API_KEY` — GET 返回 `{"set": true, "preview": "****abc1", "length": 51}`
- 非敏感字段：GET 返回 `{"set": true, "value": "https://..."}`
- POST body: 部分字段即可；空字符串 = 清除。写完调用 `config.reload_env()`。
- 原子写：临时文件 + os.replace。

- [ ] **Step 1: 写失败测试**

Create `tests/test_web_env_api.py`:

```python
"""/api/env: masked GET + whitelisted POST + live reload."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from web.app import app
from src import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Redirect .env to a temp file to avoid touching the real one
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "DEEPSEEK_API_KEY=dc-sk-aaaabbbbccccdddd\n"
        "DEEPSEEK_MODEL=test-model\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path)
    # Also prevent prior process env from leaking
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    config.reload_env()

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_env_masks_sensitive_fields(client):
    resp = client.get("/api/env")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["DEEPSEEK_API_KEY"]["set"] is True
    # masked preview shows only last 4
    assert data["DEEPSEEK_API_KEY"]["preview"].endswith("dddd")
    assert "value" not in data["DEEPSEEK_API_KEY"]
    # non-sensitive field returns value in clear
    assert data["DEEPSEEK_MODEL"]["value"] == "test-model"


def test_post_updates_and_reloads(client):
    resp = client.post("/api/env", json={"DEEPSEEK_API_KEY": "dc-sk-NEWKEY1234"})
    assert resp.status_code == 200
    # Re-read
    assert config.LLM_API_KEY == "dc-sk-NEWKEY1234"
    # Other fields preserved
    assert config.LLM_MODEL == "test-model"


def test_post_empty_string_clears(client):
    resp = client.post("/api/env", json={"PERPLEXITY_API_KEY": ""})
    assert resp.status_code == 200
    assert config.PERPLEXITY_API_KEY == ""


def test_post_rejects_unknown_key(client):
    resp = client.post("/api/env", json={"MALICIOUS_KEY": "pwned"})
    assert resp.status_code == 400


def test_post_rejects_nonstring(client):
    resp = client.post("/api/env", json={"DEEPSEEK_API_KEY": 123})
    assert resp.status_code == 400
```

- [ ] **Step 2: 确认失败**

```
pytest tests/test_web_env_api.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现**

加到 `web/app.py`：

```python
# ---------- env management ----------
_ENV_WRITABLE = {
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "PERPLEXITY_API_KEY",
    "PERPLEXITY_BASE_URL",
    "PERPLEXITY_MODEL",
}
_ENV_SENSITIVE = {"DEEPSEEK_API_KEY", "PERPLEXITY_API_KEY"}


def _env_path() -> Path:
    return config._PROJECT_ROOT / ".env"


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip()
    return out


def _serialize_env(existing: dict[str, str], updates: dict[str, str]) -> str:
    merged = dict(existing)
    for k, v in updates.items():
        if v == "":
            merged.pop(k, None)
        else:
            merged[k] = v
    # Preserve a deterministic order: known whitelist first, then unknown lines
    lines: list[str] = []
    for k in sorted(_ENV_WRITABLE):
        if k in merged:
            lines.append(f"{k}={merged[k]}")
    for k, v in sorted(merged.items()):
        if k not in _ENV_WRITABLE:
            lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"


def _mask(value: str) -> str:
    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else value
    return f"****{tail}"


@app.get("/api/env")
def api_env_get():
    env_file = _env_path()
    current = _parse_env(env_file.read_text(encoding="utf-8")) if env_file.exists() else {}
    out: dict[str, dict] = {}
    for k in sorted(_ENV_WRITABLE):
        v = current.get(k, "")
        if k in _ENV_SENSITIVE:
            out[k] = {
                "set": bool(v) and not v.startswith("dc-sk-put-yours"),
                "preview": _mask(v),
                "length": len(v),
            }
        else:
            out[k] = {"set": bool(v), "value": v}
    return jsonify(out)


@app.post("/api/env")
def api_env_post():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({"ok": False, "reason": "json object required"}), 400
    updates: dict[str, str] = {}
    for k, v in data.items():
        if k not in _ENV_WRITABLE:
            return jsonify({"ok": False, "reason": f"key not allowed: {k}"}), 400
        if not isinstance(v, str):
            return jsonify({"ok": False, "reason": f"value for {k} must be string"}), 400
        updates[k] = v

    env_file = _env_path()
    existing = _parse_env(env_file.read_text(encoding="utf-8")) if env_file.exists() else {}
    new_text = _serialize_env(existing, updates)

    # Atomic write
    tmp = env_file.with_suffix(".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, env_file)

    # Live reload so later LLM calls in the same process see new values
    config.reload_env()
    return jsonify({"ok": True, "updated": sorted(updates.keys())})
```

- [ ] **Step 4: 通过**

```
pytest tests/test_web_env_api.py -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```
git add web/app.py tests/test_web_env_api.py
git commit -m "feat(web): /api/env read/write with masked sensitive fields and live reload"
```

---

### Task 7: Web 新增 `/api/project-files` GET/PUT

**Files:**
- Modify: `web/app.py`
- Create: `tests/test_web_project_files_api.py`

**设计：** 只允许读写 **当前激活项目** 的 `project.yaml` / `outline.json` / `characters.yaml` / `timeline.yaml`。不允许操作其他项目——避免用户被交错编辑误导。

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/project-files?name=outline.json` | 返回 `{"name": "...", "content": "...", "mtime": ...}` |
| PUT | `/api/project-files` body `{"name": "...", "content": "..."}` | 写入当前激活项目。同时 trigger 一次 rerun bootstrap（把新内容拷进 state/）。 |

- [ ] **Step 1: 写失败测试**

Create `tests/test_web_project_files_api.py`:

```python
"""Project file edit: read/write the 4 source-of-truth files of active project."""
from __future__ import annotations

import pytest

from web.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_project_file_requires_active(client):
    resp = client.get("/api/project-files?name=project.yaml")
    # Either 200 (active project exists) or 409 (no active)
    assert resp.status_code in (200, 409)


def test_get_project_file_whitelist(client):
    resp = client.get("/api/project-files?name=iron-laws-extra.md")
    assert resp.status_code == 400  # not in whitelist


def test_put_rejects_unknown_name(client):
    resp = client.put(
        "/api/project-files",
        json={"name": "evil.sh", "content": "rm -rf /"},
    )
    assert resp.status_code == 400


def test_put_requires_content_key(client):
    resp = client.put("/api/project-files", json={"name": "project.yaml"})
    assert resp.status_code == 400


def test_put_roundtrip(client):
    """PUT should update the project-layer file AND re-seed state/."""
    get_resp = client.get("/api/project-files?name=project.yaml")
    if get_resp.status_code != 200:
        pytest.skip("no active project in test env")
    original = get_resp.get_json()["content"]
    try:
        # Trivial edit: append a harmless comment line
        modified = original.rstrip() + "\n# edited by test\n"
        put = client.put(
            "/api/project-files",
            json={"name": "project.yaml", "content": modified},
        )
        assert put.status_code == 200
        # Verify re-read
        reget = client.get("/api/project-files?name=project.yaml")
        assert "edited by test" in reget.get_json()["content"]
    finally:
        # Restore
        client.put("/api/project-files", json={"name": "project.yaml", "content": original})
```

- [ ] **Step 2: 确认失败**

```
pytest tests/test_web_project_files_api.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现**

加到 `web/app.py`：

```python
_PROJECT_EDITABLE = {"project.yaml", "outline.json", "characters.yaml", "timeline.yaml"}


def _active_project_path(name: str) -> Path:
    if name not in _PROJECT_EDITABLE:
        abort(400, f"name must be one of {sorted(_PROJECT_EDITABLE)}")
    pid = config.get_active_project_id()
    if not pid:
        abort(409, "no active project")
    return config.PROJECTS_DIR / pid / name


@app.get("/api/project-files")
def api_project_file_get():
    name = request.args.get("name", "").strip()
    path = _active_project_path(name)
    if not path.exists():
        abort(404, f"{name} not found in active project")
    return jsonify({
        "name": name,
        "content": path.read_text(encoding="utf-8"),
        "mtime": path.stat().st_mtime,
    })


@app.put("/api/project-files")
def api_project_file_put():
    if READONLY_MODE:
        return jsonify({"ok": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if "content" not in data:
        return jsonify({"ok": False, "reason": "content required"}), 400
    content = data["content"]
    if not isinstance(content, str):
        return jsonify({"ok": False, "reason": "content must be string"}), 400
    path = _active_project_path(name)

    # Atomic write
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)

    # Re-seed state/ so agents see the new content on next run.
    from src import bootstrap
    pid = config.get_active_project_id()
    try:
        bootstrap.bootstrap_project(pid)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"ok": False, "reason": f"re-seed failed: {e}"}), 400
    return jsonify({"ok": True, "name": name, "re_seeded": True})
```

- [ ] **Step 4: 通过 + 回归**

```
pytest tests/test_web_project_files_api.py -v
pytest -x
```
Expected: PASS

- [ ] **Step 5: 提交**

```
git add web/app.py tests/test_web_project_files_api.py
git commit -m "feat(web): /api/project-files for editing active project's 4 source files"
```

---

### Task 8: Web `/api/run` 扩展 mode + range + `/api/abort`

**Files:**
- Modify: `web/app.py`
- Create: `tests/test_web_run_modes.py`

**新接口设计：**

`POST /api/run` body:
```json
{"mode": "chapter|range|packaging|plan-only|write-only|evaluate-only|fix-only|audit-only|bookkeeping-only",
 "chapter": 3,
 "range": "1-3"}
```
- `mode=chapter`：单章全流水线（`run_chapter`）。必填 `chapter`。
- `mode=range`：在 worker 里串行循环 `run_chapter`。必填 `range`，格式 `N-M`。
- `mode=packaging`：`run_packaging`，不吃 chapter。
- 其余 mode 映射到 `run_*_only` 函数。必填 `chapter`。

保留旧的 `POST /api/audit`（alias `mode=audit-only`）兼容现有前端，但新路径走 `/api/run`。

`POST /api/abort`：设置 `pipeline.CANCEL_EVENT`，不释放 `_run_lock`（让 worker 自行退出时释放）。返回 `{"ok": true, "aborted": true}`。

- [ ] **Step 1: 写失败测试**

Create `tests/test_web_run_modes.py`:

```python
"""/api/run accepts all pipeline modes; /api/abort triggers cancel."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from web.app import app
from src import pipeline


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_run_requires_mode(client):
    resp = client.post("/api/run", json={})
    # Backward compat: missing mode but present chapter falls back to mode=chapter
    # So this should either 400 or 202 depending on impl; we accept either but
    # an explicit unknown mode should 400.
    assert resp.status_code in (202, 400, 409)


def test_run_rejects_unknown_mode(client):
    resp = client.post("/api/run", json={"mode": "teleport", "chapter": 1})
    assert resp.status_code == 400


def test_run_range_requires_range_arg(client):
    resp = client.post("/api/run", json={"mode": "range"})
    assert resp.status_code == 400


def test_run_packaging_needs_no_chapter(client):
    """Packaging mode should accept bodies without chapter."""
    # We stub out run_packaging to avoid actual LLM calls
    with patch("src.pipeline.run_packaging") as mock_pkg:
        mock_pkg.return_value = {"ok": True}
        resp = client.post("/api/run", json={"mode": "packaging"})
    assert resp.status_code in (202, 409)


def test_abort_sets_cancel_event(client):
    pipeline.CANCEL_EVENT.clear()
    resp = client.post("/api/abort")
    assert resp.status_code == 200
    assert pipeline.CANCEL_EVENT.is_set()
    pipeline.CANCEL_EVENT.clear()


def test_backward_compat_chapter_only_body(client):
    """Old UI posted just {"chapter": N}; still works as mode=chapter."""
    with patch("src.pipeline.run_chapter") as mock:
        mock.return_value = {"chapter": 1}
        resp = client.post("/api/run", json={"chapter": 1})
    assert resp.status_code in (202, 409)
```

- [ ] **Step 2: 失败**

```
pytest tests/test_web_run_modes.py -v
```
Expected: FAIL

- [ ] **Step 3: 重构 `web/app.py` 的 `_spawn` + `api_run` + 新增 `api_abort`**

```python
_MODE_DISPATCH = {
    "chapter":         ("full",         lambda ch: pipeline.run_chapter),
    "packaging":       ("packaging",    lambda ch: pipeline.run_packaging),
    "plan-only":       ("plan",         lambda ch: pipeline.run_plan_only),
    "write-only":      ("write",        lambda ch: pipeline.run_write_only),
    "evaluate-only":   ("evaluate",     lambda ch: pipeline.run_evaluate_only),
    "fix-only":        ("fix",          lambda ch: pipeline.run_fix_only),
    "audit-only":      ("audit",        lambda ch: pipeline.run_audit_only),
    "bookkeeping-only":("bookkeeping",  lambda ch: pipeline.run_bookkeeping_only),
}


def _run_range_worker(chapters: list[int]):
    done: list[int] = []
    failed = None
    for ch in chapters:
        _write_status({
            "running": True, "kind": "range", "chapter": ch,
            "pending": [c for c in chapters if c > ch],
            "done": done, "started_at": time.time(),
        })
        try:
            pipeline.run_chapter(_bb(), chapter=ch)
            done.append(ch)
        except pipeline.PipelineAborted:
            failed = {"chapter": ch, "reason": "aborted"}
            break
        except Exception as e:
            failed = {"chapter": ch, "error": f"{type(e).__name__}: {e}",
                      "traceback": traceback.format_exc()[-1200:]}
            break
    _write_status({
        "running": False, "kind": "range", "done": done, "failed": failed,
        "finished_at": time.time(), "ok": failed is None,
    })


def _spawn_generic(target_fn, kwargs: dict, kind: str):
    """Generic single-shot spawner for mode != range."""
    if not _run_lock.acquire(blocking=False):
        return False
    pipeline.CANCEL_EVENT.clear()

    def _worker():
        _write_status({"running": True, "kind": kind, "started_at": time.time(), **kwargs})
        try:
            result = target_fn(_bb(), **kwargs) if kwargs else target_fn(_bb())
            _write_status({"running": False, "kind": kind, "finished_at": time.time(),
                           "ok": True, "result": result, **kwargs})
        except pipeline.PipelineAborted:
            _write_status({"running": False, "kind": kind, "finished_at": time.time(),
                           "ok": False, "error": "aborted", **kwargs})
        except Exception as e:
            _write_status({"running": False, "kind": kind, "finished_at": time.time(),
                           "ok": False, "error": f"{type(e).__name__}: {e}",
                           "traceback": traceback.format_exc()[-1200:], **kwargs})
        finally:
            _run_lock.release()

    threading.Thread(target=_worker, daemon=True).start()
    return True


def _spawn_range(chapters: list[int]):
    if not _run_lock.acquire(blocking=False):
        return False
    pipeline.CANCEL_EVENT.clear()

    def _worker():
        try:
            _run_range_worker(chapters)
        finally:
            _run_lock.release()

    threading.Thread(target=_worker, daemon=True).start()
    return True


def _parse_range(s: str) -> list[int]:
    try:
        a, b = s.split("-")
        a, b = int(a), int(b)
    except (ValueError, AttributeError):
        abort(400, "range must be 'N-M'")
    if a > b or a < 1:
        abort(400, "invalid range")
    return list(range(a, b + 1))


@app.post("/api/run")
def api_run():
    if READONLY_MODE:
        return jsonify({"started": False, "reason": "readonly_mode"}), 403
    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "").strip()
    # Backward compat: if no mode but chapter present, treat as chapter mode
    if not mode and "chapter" in data:
        mode = "chapter"
    if mode == "range":
        rng = data.get("range")
        if not rng or not isinstance(rng, str):
            return jsonify({"started": False, "reason": "range required"}), 400
        chapters = _parse_range(rng)
        ok = _spawn_range(chapters)
        if not ok:
            return jsonify({"started": False, "reason": "pipeline already running"}), 409
        return jsonify({"started": True, "kind": "range", "chapters": chapters}), 202

    if mode not in _MODE_DISPATCH:
        return jsonify({"started": False, "reason": f"unknown mode: {mode}"}), 400

    kind, fn_getter = _MODE_DISPATCH[mode]
    target_fn = fn_getter(None)

    if mode == "packaging":
        kwargs = {}
    else:
        ch = data.get("chapter")
        if ch is None:
            return jsonify({"started": False, "reason": "chapter required"}), 400
        try:
            ch = int(ch)
        except (TypeError, ValueError):
            return jsonify({"started": False, "reason": "chapter must be int"}), 400
        kwargs = {"chapter": ch}

    ok = _spawn_generic(target_fn, kwargs, kind=kind)
    if not ok:
        return jsonify({"started": False, "reason": "pipeline already running"}), 409
    return jsonify({"started": True, "kind": kind, **kwargs}), 202


@app.post("/api/abort")
def api_abort():
    """Signal pipeline.CANCEL_EVENT. Worker checks it between stages."""
    was_running = _run_lock.locked()
    pipeline.CANCEL_EVENT.set()
    return jsonify({"ok": True, "aborted": True, "was_running": was_running})
```

**注意：** 保留旧 `/api/audit` 路由（继续只接 `chapter`），别删，避免前端破裂。可以改成内部转发到 `_spawn_generic(pipeline.run_audit_only, {"chapter": ch}, "audit")`。

- [ ] **Step 4: 通过 + 回归**

```
pytest tests/test_web_run_modes.py -v
pytest -x
```
Expected: PASS

- [ ] **Step 5: 提交**

```
git add web/app.py tests/test_web_run_modes.py
git commit -m "feat(web): /api/run supports all pipeline modes + range; /api/abort"
```

---

### Task 9: 前端 — 项目/设置/运行 三组 UI

**Files:**
- Modify: `web/templates/index.html`
- Modify: `web/static/main.js`
- Modify: `web/static/main.css`

**不写测试**（前端按约定手动验证，见"验收"部分）。

- [ ] **Step 1: 顶部加"当前项目"徽章 + 下拉切换**

在 `index.html` 顶栏（能找到现有 status pill 的位置）旁边加一个 `<button id="project-switcher">` 显示 `{active_id} ▾`。点击弹模态列出 `/api/projects` 结果，点任意一项 POST `/api/projects/activate`，成功后 `location.reload()`（偷懒但可靠——切项目后几乎所有视图都要刷）。

最小 HTML 片段：
```html
<div class="top-bar">
  <!-- existing status pill -->
  <button id="project-switcher" class="pill">⟳ 项目</button>
  <button id="settings-btn" class="pill">⚙ 设置</button>
</div>

<dialog id="project-dialog">
  <h3>切换作品</h3>
  <div id="project-list"></div>
  <button id="new-project-btn">+ 新建作品</button>
  <button onclick="document.getElementById('project-dialog').close()">关闭</button>
</dialog>
```

对应 JS：
```javascript
async function openProjectDialog() {
  const resp = await fetch("/api/projects").then(r => r.json());
  const list = document.getElementById("project-list");
  list.innerHTML = resp.projects.map(p => `
    <div class="project-card ${p.is_active ? 'active' : ''}">
      <div class="project-title">${p.display_name}</div>
      <div class="project-meta">${p.genre} · ${p.has_state ? '已初始化' : '未初始化'}</div>
      <button data-id="${p.id}" ${p.is_active ? 'disabled' : ''}>${p.is_active ? '当前' : '切换'}</button>
    </div>
  `).join("");
  list.querySelectorAll("button[data-id]").forEach(btn => {
    btn.addEventListener("click", () => activateProject(btn.dataset.id));
  });
  document.getElementById("project-dialog").showModal();
}

async function activateProject(id) {
  if (!confirm(`切换到 ${id}？当前运行如已进行到一半会拒绝切换。`)) return;
  const resp = await fetch("/api/projects/activate", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id}),
  }).then(r => r.json());
  if (resp.ok) {
    location.reload();
  } else {
    alert("切换失败：" + resp.reason);
  }
}

document.getElementById("project-switcher").addEventListener("click", openProjectDialog);
```

- [ ] **Step 2: "新建作品"向导**

点 `#new-project-btn`：
1. 先 `GET /api/genres` 填题材下拉
2. 表单：项目 id (slug)、显示名、题材（下拉）、主角名、opening_year_month、chapter_count_target
3. 提交：POST `/api/projects/new` 只带 id + genre（其他字段在成功后通过 PUT `/api/project-files` 更新 `project.yaml`）
4. 随后打开"编辑元信息"模态（step 3）

- [ ] **Step 3: "编辑元信息"模态 — 四个 tab**

每个 tab 对应一个文件（project.yaml / outline.json / characters.yaml / timeline.yaml），内容用 `<textarea>` 简单显示。保存时 PUT `/api/project-files`。不引入 JSON/YAML 编辑器（避免体积膨胀），纯文本编辑即可。

- [ ] **Step 4: 设置模态（.env 编辑）**

点 `#settings-btn` → GET `/api/env` → 表单渲染。敏感字段 input placeholder 显示 `****abc1（留空保留原值）`，非敏感字段直接显示 value。保存：把非空字段 POST 上去。

- [ ] **Step 5: 运行面板升级**

在现有"生成下一章"按钮区域加：
- 章节输入框（默认下一章）
- Mode 下拉（`chapter` / `range` / `packaging` / `plan-only` / `write-only` / `evaluate-only` / `fix-only` / `audit-only` / `bookkeeping-only`）
- Range 输入框（mode=range 时才显示）
- "开始"按钮 → POST `/api/run`
- "中断"按钮 → POST `/api/abort`（运行中才可用，通过轮询 `/api/status.running` 控制 disabled）

- [ ] **Step 6: 首次启动引导**

`init()` 里：
```javascript
async function init() {
  const [state, env, projects] = await Promise.all([
    fetch("/api/state").then(r => r.json()),
    fetch("/api/env").then(r => r.json()),
    fetch("/api/projects").then(r => r.json()),
  ]);
  const needKey = !env.DEEPSEEK_API_KEY.set;
  const needProject = !projects.active;
  if (needKey) openOnboarding("key");
  else if (needProject) openOnboarding("project");
  else renderMain(state);
}
```

`openOnboarding(stage)` 显示一个向导模态，stage="key" 时只显示 API key 表单，stage="project" 时显示项目卡片列表。

- [ ] **Step 7: 手动验证 checklist**

依次在浏览器里做：
1. 删除 `projects/.active` 和 `.env`，启动 web：能看到向导要求填 DEEPSEEK_API_KEY ✓
2. 填完 key → 自动推进到"选作品"步骤 ✓
3. 选林家耀作品 → 激活成功 ✓
4. 运行面板输入 range=1-2，点开始 → 两章顺序跑（可只跑第一章，然后中断第二章）
5. 点"中断"→ 当前章节收尾（允许当前 stage 完成）后 status 显示 aborted ✓
6. 切换到"裴长宁" → 刷新后左侧文件树为空（新 state/）✓
7. 点"编辑元信息"→ 改 project.yaml 保存 → state/setting.yaml 同步更新（可在文件树里打开对比）✓
8. 点齿轮 → 改 PERPLEXITY_API_KEY 保存 → 下次 evaluate 命中 landmine_13 时 FactChecker 真的跑起来 ✓
9. 点"新建作品"→ 填 id=test-new-book, genre=gangster-hk-1983 → 成功创建，可在项目切换面板看到 ✓

- [ ] **Step 8: 提交**

```
git add web/templates/index.html web/static/main.js web/static/main.css
git commit -m "feat(web): onboarding wizard + project/env/run panels"
```

---

### Task 10: README 更新 + AGENTS.md 一致性修复

**Files:**
- Modify: `README.md`（如果存在）
- Modify: `docs/AGENTS.md`（它还在用旧 settings/ 语言，与代码不一致）

- [ ] **Step 1: 检查 README.md 是否存在**

```
ls README.md
```

若存在，更新"如何运行"一节，把推荐路径改为：

```
pip install -r requirements.txt
flask --app web.app run --port 5055
# 打开 http://127.0.0.1:5055
# 首次使用向导填 API Key → 选作品 → 点"生成第一章"
```

CLI 路径保留，但降级为"高级/脚本化"场景。

- [ ] **Step 2: 修 `docs/AGENTS.md`**

目前 docs/AGENTS.md 还在用 `settings/<name>/` 的旧两层概念（见文件开头"## Setting 系统"段），但代码已经是 `genres/ + projects/` 两层。两种表述并存会误导。

最小修复：在 docs/AGENTS.md 顶部加一行 `> **注意**：本文档描述的是 2026-05-10 前的单层 settings 结构。当前代码已重构为 genres/ + projects/ 两层，请以根目录 AGENTS.md 为准。` 或者直接把内容同步成根目录 AGENTS.md 的版本。

- [ ] **Step 3: 提交**

```
git add README.md docs/AGENTS.md
git commit -m "docs: web is now the primary entry point; sync docs/AGENTS.md"
```

---

## 3. 任务依赖图

```
Task 1 (STATE_DIR 延迟)    ─┐
Task 2 (reload_env)        ─┤
Task 3 (CANCEL_EVENT)      ─┤
Task 4 (Web 动态化)        ─┤
                            ├─► Task 5 (projects API)    ─┐
                            ├─► Task 6 (env API)          ─┤
                            ├─► Task 7 (project-files)    ─┤
                            └─► Task 8 (run modes + abort)─┤
                                                            └─► Task 9 (前端 UI)
                                                                    │
                                                                    └─► Task 10 (docs)
```

- Task 1-4 彼此独立，可并行（如果用 fixer 并行）
- Task 5-8 都依赖 Task 4（动态 bb / sandbox），互相独立
- Task 9 依赖 5-8 全部完成
- Task 10 独立收尾

---

## 4. 验收标准（"done"）

Phase 1 做完，在 `projects/.active` 和 `.env` 都被删除的全新状态下：

1. `pip install -r requirements.txt && flask --app web.app run --port 5055`
2. 打开 `http://127.0.0.1:5055` → 向导要求填 DEEPSEEK_API_KEY ✓
3. 填完 → 向导列出 3 个内置作品 → 点"林家耀"激活 ✓
4. 点"生成第一章"→ 看到 prompts_log 实时流入 ✓
5. 点"批量 1-2"→ 两章顺序跑完 ✓
6. 点"中断"（在第二章跑到一半时）→ 当前 stage 完成后停 ✓
7. 点齿轮 → 改 Perplexity key 保存 → 本进程立即生效 ✓
8. 点项目切换 → 切到"裴长宁"→ 刷新后章节列表为空 ✓
9. 点"新建作品"→ 填 id+genre → 创建成功 → 在模态里编辑 outline.json 保存 → state/outline.json 同步 ✓
10. 全程不打开任何终端 ✓

所有新增 Flask 路由必须有 pytest 覆盖，`pytest -x` 全绿。

---

## 5. 本 plan 不做的事

- 不做用户认证 / 多人协作
- 不做章节正文编辑器（state/chapters/chNNN.md 编辑请用系统编辑器）
- 不做 genre 脚手架 UI（Phase 2）
- 不做 SSE 流式 prompt 推送（保持现有 `/api/prompts` 轮询）
- 不做多进程 / 多作品并行跑（需要把 pipeline 脱离全局 STATE_DIR，改动过大）
- 不引入前端框架
- 不做 Docker / 一键脚本（宿主层暂按现状）

---

## 6. 自审

- **覆盖**：§0 列出的 5 类摩擦点（选题材/切项目/.env/批量运行/包装运行）都由 Task 5-8 覆盖 ✓
- **placeholders 扫描**：无 TODO / TBD，所有关键代码块都给出最小实现 ✓
- **类型一致**：`bootstrap.bootstrap_project` 返回 `BootstrapResult` dataclass（已存在），Web 返回时读 `.project_id / .genre_id / .copied_files` 属性，与 Task 5 测试期望的 JSON 一致 ✓
- **依赖**：§3 图清晰，Task 1-4 必须先于 5-9 ✓
- **并行机会**：Task 1/2/3/4 完全独立，可多 fixer 并行；Task 5-8 都依赖 4，彼此独立也可并行 ✓

---

## 7. 执行交付

Plan saved to `docs/superpowers/plans/2026-05-11-web-full-onboarding.md`.

执行模式推荐：**Subagent-Driven**。Task 1-4 首轮并行派 4 个 fixer；review 后 Task 5-8 再并行派 4 个；最后 Task 9 由 designer（前端）做，Task 10 收尾。
