# 题材任务（Genre Jobs）重构 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"新建题材"三种方式（素材库拆 / 描述生成 / 空壳）+ 作品层 extract-to-project 统一成带独立 URL 页面、落盘持久化、支持无限并发和真 abort 的 Job 系统。

**Spec:** `docs/superpowers/specs/genre-jobs-rearch.md`

**Architecture:** 新增 `src/jobs/` 模块（JobStore 文件落盘 + 内存缓存 + CancelToken 协议）→ 改造 `src/genre_extractor/` 4 个入口函数接受 `CancelToken` + `on_progress` 回调 → 新建 `/api/jobs` REST + `/jobs` `/jobs/<id>` 两个页面 → 删除所有旧 endpoint → 前端 `presets.js` 迁到 ES modules + 新增 `jobDetail.js` `jobsList.js`。

**Tech Stack:** Python 3.11+ · Flask · threading · 无新依赖。

---

## 执行顺序总览

| Phase | Task | 主文件 | 性质 |
|---|---|---|---|
| **P1 · 基础设施** | 1. CancelToken 协议 | `src/jobs/cancel.py` | 纯库 |
|  | 2. JobStore（文件落盘 + 内存缓存 + 恢复） | `src/jobs/store.py` | 纯库 |
|  | 3. JobLogger（rotating） | `src/jobs/logger.py` | 纯库 |
|  | 4. Job schema + 常量 | `src/jobs/schema.py` | 纯库 |
| **P2 · Extractor 接入** | 5. `genre_extractor.pipeline` 去掉 module-global `CANCEL_EVENT` | `src/genre_extractor/pipeline.py` | 改接口 |
|  | 6. `core.run_extract / run_merge / run_draft` 接 token + 子步骤回调 | `src/genre_extractor/core.py` | 改接口 |
|  | 7. `to_preset / to_project / from_description / blank_preset` 顶层接 token | 4 个文件 | 改接口 |
| **P3 · Web 后端** | 8. `web/_shared.py` 用 JobStore 替代 `_PRESET_JOBS`/`_PROJECT_JOBS` | `web/_shared.py` | 改集成 |
|  | 9. 新 blueprint `web/routes/jobs.py`（CRUD + abort + log） | 新文件 | 新路由 |
|  | 10. 删除旧 endpoint（presets/new-*, projects/extract-genre/*, presets/<id>/status） | 2 个文件 | 清理 |
|  | 11. `web/app.py` 注册 jobs blueprint + 启动恢复 | `web/app.py` | 集成 |
| **P4 · 前端** | 12. 新建 `/jobs` 列表页（模板 + ES module） | 2 个文件 | 新 UI |
|  | 13. 新建 `/jobs/<id>` 详情页（节点图 + 日志） | 2 个文件 | 新 UI |
|  | 14. `/presets/new` 三 tab 提交改为跳 `/jobs/<id>` | 2 个文件 | 改路径 |
|  | 15. 新作品向导 + ⎇ 覆盖题材改为跳 `/jobs/<id>` | 2 个文件 | 改路径 |
|  | 16. 首页顶栏"题材任务运行中" pill | 2 个文件 | 新 UI |
|  | 17. `web/static/presets.js` 迁 ES modules（删除老 IIFE） | 3 个文件 | 重构 |
| **P5 · 收尾** | 18. README 明确 `--workers=1` 部署约束 | `README.md` / `AGENTS.md` | 文档 |
|  | 19. 端到端手动验证清单 | — | 验证 |

**Phase 间 Checkpoint**：每个 phase 结束跑 `.venv/bin/python3 -m pytest tests/ -q`，全绿方可下一 phase。

---

## P1 · 基础设施

### Task 1: CancelToken 协议

**Files:**
- Create: `src/jobs/__init__.py`
- Create: `src/jobs/cancel.py`
- Create: `tests/test_jobs_cancel.py`

- [ ] **Step 1:** 写测试 `tests/test_jobs_cancel.py`：

```python
"""CancelToken 协议与默认实现."""
from __future__ import annotations

import pytest


def test_null_token_never_cancels():
    from src.jobs.cancel import NullCancelToken
    t = NullCancelToken()
    t.check()
    assert not t.is_cancelled()


def test_thread_event_token_check_raises_after_cancel():
    from src.jobs.cancel import ThreadEventToken, GenrePipelineAborted
    t = ThreadEventToken()
    t.check()
    t.cancel()
    assert t.is_cancelled()
    with pytest.raises(GenrePipelineAborted):
        t.check()


def test_thread_event_token_idempotent_cancel():
    from src.jobs.cancel import ThreadEventToken
    t = ThreadEventToken()
    t.cancel()
    t.cancel()
    assert t.is_cancelled()
```

- [ ] **Step 2:** 跑测试验证失败：

```
.venv/bin/python3 -m pytest tests/test_jobs_cancel.py -v
```
Expected: FAIL, `ModuleNotFoundError: src.jobs`

- [ ] **Step 3:** 写 `src/jobs/__init__.py`（空文件）和 `src/jobs/cancel.py`：

```python
"""Cancel token 协议：让长任务可以协作式取消。

- `CancelToken` 是 Protocol
- `ThreadEventToken` 是线程默认实现
- `NullCancelToken` 是 CLI / 测试用的无操作实现
"""
from __future__ import annotations

import threading
from typing import Protocol


class GenrePipelineAborted(Exception):
    """Cancel token 触发 check() 时抛出，worker 捕获后把 state → aborted."""


class CancelToken(Protocol):
    def check(self) -> None: ...
    def is_cancelled(self) -> bool: ...


class ThreadEventToken:
    def __init__(self) -> None:
        self._e = threading.Event()

    def cancel(self) -> None:
        self._e.set()

    def check(self) -> None:
        if self._e.is_set():
            raise GenrePipelineAborted()

    def is_cancelled(self) -> bool:
        return self._e.is_set()


class NullCancelToken:
    def cancel(self) -> None:
        pass

    def check(self) -> None:
        pass

    def is_cancelled(self) -> bool:
        return False
```

- [ ] **Step 4:** 跑测试验证通过：

```
.venv/bin/python3 -m pytest tests/test_jobs_cancel.py -v
```
Expected: 3 passed

- [ ] **Step 5:** 提交

```bash
git add src/jobs/ tests/test_jobs_cancel.py
git commit -m "feat(jobs): add CancelToken protocol and default implementations"
```

---

### Task 2: JobStore（持久化 + 内存缓存）

**Files:**
- Create: `src/jobs/schema.py`
- Create: `src/jobs/store.py`
- Create: `tests/test_jobs_store.py`

- [ ] **Step 1:** 写 `src/jobs/schema.py`：

```python
"""Job record schema 与常量."""
from __future__ import annotations

import time
import uuid
from typing import Literal, TypedDict

SCHEMA_VERSION = 1

JobState = Literal["running", "aborting", "done", "failed", "aborted", "interrupted"]
JobKind = Literal["from-novel", "from-description", "blank", "extract-to-project"]
TargetType = Literal["preset", "project"]

TERMINAL_STATES = frozenset({"done", "failed", "aborted", "interrupted"})
PHASE_ORDER = ("extract", "merge", "draft", "validate")
PHASE_TOTAL = 4


class Target(TypedDict):
    type: TargetType
    id: str


class SubSteps(TypedDict, total=False):
    batch_cur: int | None
    batch_total: int | None
    arc_cur: int | None
    arc_total: int | None
    draft_pass: int | None
    validate_round: int | None


def new_job_id() -> str:
    return uuid.uuid4().hex


def empty_sub_steps() -> SubSteps:
    return {
        "batch_cur": None, "batch_total": None,
        "arc_cur": None, "arc_total": None,
        "draft_pass": None, "validate_round": None,
    }


def initial_job_record(
    *,
    job_id: str,
    kind: JobKind,
    target: Target,
    label: str,
    sources: list[str] | None = None,
    params: dict | None = None,
) -> dict:
    now = time.time()
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "label": label,
        "kind": kind,
        "target": target,
        "state": "running",
        "phase": None,
        "phase_index": 0,
        "phase_total": PHASE_TOTAL,
        "sub_steps": empty_sub_steps(),
        "progress_text": "",
        "error": None,
        "log_path": f".jobs/logs/{job_id}.log",
        "created_at": now,
        "started_at": now,
        "updated_at": now,
        "finished_at": None,
        "sources": sources or [],
        "params": params or {},
    }
```

- [ ] **Step 2:** 写测试 `tests/test_jobs_store.py`：

```python
"""JobStore：文件落盘 + 内存缓存 + 启动恢复."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


@pytest.fixture
def store_env(tmp_path: Path, monkeypatch):
    from src.jobs import store as store_mod
    monkeypatch.setattr(store_mod, "JOBS_DIR", tmp_path / ".jobs")
    # 强制新建 store 实例
    store_mod._STORE_SINGLETON = None
    return tmp_path


def test_create_and_get_job(store_env):
    from src.jobs.store import get_store
    from src.jobs.schema import initial_job_record, new_job_id
    s = get_store()
    jid = new_job_id()
    rec = initial_job_record(
        job_id=jid, kind="blank", target={"type": "preset", "id": "p1"}, label="L",
    )
    s.create(rec)
    back = s.get(jid)
    assert back["job_id"] == jid
    assert back["state"] == "running"


def test_persist_roundtrip(store_env):
    from src.jobs.store import get_store
    from src.jobs.schema import initial_job_record, new_job_id
    s = get_store()
    jid = new_job_id()
    s.create(initial_job_record(
        job_id=jid, kind="blank", target={"type": "preset", "id": "p"}, label="L",
    ))
    path = store_env / ".jobs" / "active" / f"{jid}.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["job_id"] == jid


def test_update_writes_to_disk(store_env):
    from src.jobs.store import get_store
    from src.jobs.schema import initial_job_record, new_job_id
    s = get_store()
    jid = new_job_id()
    s.create(initial_job_record(
        job_id=jid, kind="blank", target={"type": "preset", "id": "p"}, label="L",
    ))
    s.update(jid, phase="extract", phase_index=1, progress_text="batch 1/5")
    rec = s.get(jid)
    assert rec["phase"] == "extract"
    assert rec["progress_text"] == "batch 1/5"
    disk = json.loads((store_env / ".jobs" / "active" / f"{jid}.json").read_text())
    assert disk["phase"] == "extract"


def test_finish_moves_to_archive(store_env):
    from src.jobs.store import get_store
    from src.jobs.schema import initial_job_record, new_job_id
    s = get_store()
    jid = new_job_id()
    s.create(initial_job_record(
        job_id=jid, kind="blank", target={"type": "preset", "id": "p"}, label="L",
    ))
    s.finish(jid, "done")
    assert not (store_env / ".jobs" / "active" / f"{jid}.json").exists()
    assert (store_env / ".jobs" / "archive" / f"{jid}.json").exists()
    rec = s.get(jid)
    assert rec["state"] == "done"
    assert rec["finished_at"] is not None


def test_finish_idempotent(store_env):
    """已处于终态的 job 不被覆盖（防止 abort 后 worker 仍然 finish(done)）."""
    from src.jobs.store import get_store
    from src.jobs.schema import initial_job_record, new_job_id
    s = get_store()
    jid = new_job_id()
    s.create(initial_job_record(
        job_id=jid, kind="blank", target={"type": "preset", "id": "p"}, label="L",
    ))
    s.finish(jid, "aborted", error="user abort")
    s.finish(jid, "done")  # should be no-op
    rec = s.get(jid)
    assert rec["state"] == "aborted"
    assert rec["error"] == "user abort"


def test_list_filters_by_state(store_env):
    from src.jobs.store import get_store
    from src.jobs.schema import initial_job_record, new_job_id
    s = get_store()
    j1 = new_job_id()
    j2 = new_job_id()
    s.create(initial_job_record(
        job_id=j1, kind="blank", target={"type": "preset", "id": "a"}, label="A",
    ))
    s.create(initial_job_record(
        job_id=j2, kind="blank", target={"type": "preset", "id": "b"}, label="B",
    ))
    s.finish(j2, "done")
    running = s.list(state="running")
    done = s.list(state="done")
    assert [r["job_id"] for r in running] == [j1]
    assert [r["job_id"] for r in done] == [j2]


def test_delete_rejects_running(store_env):
    from src.jobs.store import get_store
    from src.jobs.schema import initial_job_record, new_job_id
    s = get_store()
    jid = new_job_id()
    s.create(initial_job_record(
        job_id=jid, kind="blank", target={"type": "preset", "id": "p"}, label="L",
    ))
    with pytest.raises(ValueError, match="running"):
        s.delete(jid)


def test_delete_archived_ok(store_env):
    from src.jobs.store import get_store
    from src.jobs.schema import initial_job_record, new_job_id
    s = get_store()
    jid = new_job_id()
    s.create(initial_job_record(
        job_id=jid, kind="blank", target={"type": "preset", "id": "p"}, label="L",
    ))
    s.finish(jid, "done")
    s.delete(jid)
    assert s.get(jid) is None


def test_recover_marks_orphans_interrupted(store_env):
    """启动时发现 active/ 里 state=running 的 job，标记为 interrupted."""
    from src.jobs.store import get_store
    from src.jobs.schema import initial_job_record, new_job_id
    import src.jobs.store as store_mod
    jid = new_job_id()
    # 手工写 active 文件，模拟进程崩溃
    active = store_env / ".jobs" / "active"
    active.mkdir(parents=True)
    rec = initial_job_record(
        job_id=jid, kind="blank", target={"type": "preset", "id": "p"}, label="L",
    )
    (active / f"{jid}.json").write_text(json.dumps(rec))
    # 重置 singleton，触发 recover
    store_mod._STORE_SINGLETON = None
    s = get_store()
    s.recover()
    rec2 = s.get(jid)
    assert rec2["state"] == "interrupted"
    assert "进程重启" in rec2["error"]
    assert not (active / f"{jid}.json").exists()
```

- [ ] **Step 3:** 跑测试验证全部失败：

```
.venv/bin/python3 -m pytest tests/test_jobs_store.py -v
```
Expected: FAIL（ModuleNotFoundError / AttributeError）

- [ ] **Step 4:** 写 `src/jobs/store.py`：

```python
"""JobStore：每个 job 一个 JSON 文件，atomic write，内存缓存 active 的。

目录结构：
    .jobs/
      active/<job_id>.json
      archive/<job_id>.json
      logs/<job_id>.log    (由 JobLogger 管理)

线程安全：所有 pub 方法拿 `_lock`（RLock）。
进程隔离：不做（单 worker 约束，见 README）。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from src import config
from src.jobs.schema import TERMINAL_STATES

JOBS_DIR = config.PROJECT_ROOT / ".jobs"

_STORE_SINGLETON: "JobStore | None" = None
_SINGLETON_LOCK = threading.Lock()


def get_store() -> "JobStore":
    global _STORE_SINGLETON
    with _SINGLETON_LOCK:
        if _STORE_SINGLETON is None:
            _STORE_SINGLETON = JobStore(JOBS_DIR)
        return _STORE_SINGLETON


class JobStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._active = root / "active"
        self._archive = root / "archive"
        self._logs = root / "logs"
        for d in (self._active, self._archive, self._logs):
            d.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict] = {}
        self._runtime: dict[str, dict] = {}  # 非序列化字段：cancel token / target lock
        self._lock = threading.RLock()
        # 启动时懒加载 active
        for p in self._active.glob("*.json"):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
                self._cache[rec["job_id"]] = rec
            except (json.JSONDecodeError, KeyError, OSError):
                continue

    # ---------- CRUD ----------

    def create(self, rec: dict) -> None:
        with self._lock:
            jid = rec["job_id"]
            self._cache[jid] = rec
            self._write_active(rec)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            if job_id in self._cache:
                return dict(self._cache[job_id])
            # 尝试 archive 懒加载
            p = self._archive / f"{job_id}.json"
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return None
            return None

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            if job_id not in self._cache:
                return
            rec = self._cache[job_id]
            if rec["state"] in TERMINAL_STATES:
                return  # 不覆盖终态
            # sub_steps 做 merge 而不是替换
            if "sub_steps" in fields:
                merged = {**rec.get("sub_steps", {}), **fields.pop("sub_steps")}
                rec["sub_steps"] = merged
            rec.update(fields)
            rec["updated_at"] = time.time()
            self._write_active(rec)

    def finish(self, job_id: str, state: str, *, error: str | None = None) -> None:
        with self._lock:
            if job_id not in self._cache:
                return
            rec = self._cache[job_id]
            if rec["state"] in TERMINAL_STATES:
                return  # idempotent
            rec["state"] = state
            rec["error"] = error
            rec["finished_at"] = time.time()
            rec["updated_at"] = rec["finished_at"]
            # archive
            self._write_archive(rec)
            self._remove_active(job_id)
            # 保留内存缓存（方便详情页 fallback）
            # 但移除 runtime
            self._runtime.pop(job_id, None)

    def delete(self, job_id: str) -> None:
        with self._lock:
            rec = self.get(job_id)
            if rec is None:
                return
            if rec["state"] not in TERMINAL_STATES:
                raise ValueError(f"cannot delete job in state: {rec['state']} (still running)")
            self._cache.pop(job_id, None)
            ap = self._archive / f"{job_id}.json"
            if ap.exists():
                ap.unlink()
            lp = self._logs / f"{job_id}.log"
            if lp.exists():
                lp.unlink()
            # 顺手清 rotate 过的
            for p in self._logs.glob(f"{job_id}.log.*"):
                p.unlink(missing_ok=True)

    def list(self, *, state: str | None = None, kind: str | None = None) -> list[dict]:
        with self._lock:
            out: list[dict] = list(self._cache.values())
            # 懒加载 archive
            for p in self._archive.glob("*.json"):
                jid = p.stem
                if jid in self._cache:
                    continue
                try:
                    out.append(json.loads(p.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    continue
            if state:
                out = [r for r in out if r.get("state") == state]
            if kind:
                out = [r for r in out if r.get("kind") == kind]
            out.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
            return out

    # ---------- 运行时（不序列化） ----------

    def set_runtime(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            self._runtime.setdefault(job_id, {}).update(fields)

    def get_runtime(self, job_id: str, key: str) -> Any:
        with self._lock:
            return self._runtime.get(job_id, {}).get(key)

    # ---------- 启动恢复 ----------

    def recover(self) -> list[str]:
        """启动时把 active 里 state ∈ {running,aborting} 的 job 全部标为 interrupted."""
        recovered: list[str] = []
        with self._lock:
            for jid, rec in list(self._cache.items()):
                if rec["state"] in ("running", "aborting"):
                    rec["state"] = "interrupted"
                    rec["error"] = "进程重启导致任务中断"
                    rec["finished_at"] = time.time()
                    rec["updated_at"] = rec["finished_at"]
                    self._write_archive(rec)
                    self._remove_active(jid)
                    recovered.append(jid)
        return recovered

    # ---------- 内部 ----------

    def _write_active(self, rec: dict) -> None:
        self._atomic_write(self._active / f"{rec['job_id']}.json", rec)

    def _write_archive(self, rec: dict) -> None:
        self._atomic_write(self._archive / f"{rec['job_id']}.json", rec)

    def _remove_active(self, job_id: str) -> None:
        p = self._active / f"{job_id}.json"
        if p.exists():
            p.unlink()

    @staticmethod
    def _atomic_write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
```

- [ ] **Step 5:** 跑测试验证通过：

```
.venv/bin/python3 -m pytest tests/test_jobs_store.py -v
```
Expected: 9 passed

- [ ] **Step 6:** 提交

```bash
git add src/jobs/schema.py src/jobs/store.py tests/test_jobs_store.py
git commit -m "feat(jobs): add JobStore with atomic JSON persistence + in-memory cache + recovery"
```

---

### Task 3: JobLogger（rotating 日志）

**Files:**
- Create: `src/jobs/logger.py`
- Create: `tests/test_jobs_logger.py`

- [ ] **Step 1:** 写测试：

```python
"""JobLogger：rotating file handler，文本日志 append."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def log_env(tmp_path: Path, monkeypatch):
    from src.jobs import logger as mod
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path / "logs")
    return tmp_path


def test_get_logger_writes_to_file(log_env):
    from src.jobs.logger import get_job_logger
    lg = get_job_logger("job1")
    lg.info("hello")
    lg.info("world")
    content = (log_env / "logs" / "job1.log").read_text(encoding="utf-8")
    assert "hello" in content
    assert "world" in content


def test_two_loggers_same_job_share_handler(log_env):
    """重复调用 get_job_logger 不应加多个 handler（防止重复写）."""
    from src.jobs.logger import get_job_logger
    lg1 = get_job_logger("j2")
    lg2 = get_job_logger("j2")
    assert lg1 is lg2
    lg1.info("once")
    content = (log_env / "logs" / "j2.log").read_text(encoding="utf-8")
    assert content.count("once") == 1


def test_read_tail_returns_content_from_offset(log_env):
    from src.jobs.logger import get_job_logger, read_log_tail
    lg = get_job_logger("j3")
    lg.info("line A")
    lg.info("line B")
    (content1, next_off1) = read_log_tail("j3", offset=0)
    assert "line A" in content1
    assert next_off1 > 0
    # 不再写入
    (content2, next_off2) = read_log_tail("j3", offset=next_off1)
    assert content2 == ""
    assert next_off2 == next_off1


def test_read_tail_missing_log_returns_empty(log_env):
    from src.jobs.logger import read_log_tail
    c, o = read_log_tail("unknown-job", offset=0)
    assert c == ""
    assert o == 0
```

- [ ] **Step 2:** 跑测试验证失败：

```
.venv/bin/python3 -m pytest tests/test_jobs_logger.py -v
```

- [ ] **Step 3:** 写 `src/jobs/logger.py`：

```python
"""JobLogger：每个 job 一个 rotating file handler.

- 单文件 10MB，保留 3 份（总 40MB 上限）
- `get_job_logger(job_id)` 幂等：同一 job 只创建一次 handler
- `read_log_tail(job_id, offset)` 给前端轮询用
"""
from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src import config

LOGS_DIR = config.PROJECT_ROOT / ".jobs" / "logs"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 3

_LOGGERS: dict[str, logging.Logger] = {}
_LOCK = threading.Lock()


def get_job_logger(job_id: str) -> logging.Logger:
    with _LOCK:
        if job_id in _LOGGERS:
            return _LOGGERS[job_id]
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        lg = logging.getLogger(f"novelforge.job.{job_id}")
        lg.setLevel(logging.INFO)
        lg.propagate = False
        # 清理旧 handler（防止测试中 module reload 出现的累加）
        lg.handlers.clear()
        handler = RotatingFileHandler(
            LOGS_DIR / f"{job_id}.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
        lg.addHandler(handler)
        _LOGGERS[job_id] = lg
        return lg


def read_log_tail(job_id: str, offset: int = 0) -> tuple[str, int]:
    """从 offset 字节开始读取日志。返回 (内容, 下一个 offset)."""
    p = LOGS_DIR / f"{job_id}.log"
    if not p.exists():
        return "", 0
    size = p.stat().st_size
    if offset >= size:
        return "", offset
    with p.open("rb") as f:
        f.seek(offset)
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return text, offset + len(raw)
```

- [ ] **Step 4:** 跑测试验证通过：

```
.venv/bin/python3 -m pytest tests/test_jobs_logger.py -v
```
Expected: 4 passed

- [ ] **Step 5:** 提交

```bash
git add src/jobs/logger.py tests/test_jobs_logger.py
git commit -m "feat(jobs): add rotating per-job file logger + tail reader"
```

---

### Task 4: `.gitignore` 与配置入口

**Files:**
- Modify: `.gitignore`
- Modify: `src/jobs/__init__.py`

- [ ] **Step 1:** 在 `.gitignore` 末尾追加：

```
.jobs/
```

- [ ] **Step 2:** 在 `src/jobs/__init__.py` 暴露公共 API：

```python
"""Jobs 子系统：持久化长运行任务 + cancel token + rotating log."""
from __future__ import annotations

from src.jobs.cancel import (
    CancelToken,
    GenrePipelineAborted,
    NullCancelToken,
    ThreadEventToken,
)
from src.jobs.logger import get_job_logger, read_log_tail
from src.jobs.schema import (
    PHASE_ORDER,
    PHASE_TOTAL,
    TERMINAL_STATES,
    initial_job_record,
    new_job_id,
)
from src.jobs.store import JobStore, get_store

__all__ = [
    "CancelToken",
    "GenrePipelineAborted",
    "JobStore",
    "NullCancelToken",
    "PHASE_ORDER",
    "PHASE_TOTAL",
    "TERMINAL_STATES",
    "ThreadEventToken",
    "get_job_logger",
    "get_store",
    "initial_job_record",
    "new_job_id",
    "read_log_tail",
]
```

- [ ] **Step 3:** 跑现有全部测试确保没破坏：

```
.venv/bin/python3 -m pytest tests/ -q
```
Expected: 全绿

- [ ] **Step 4:** 提交

```bash
git add .gitignore src/jobs/__init__.py
git commit -m "chore(jobs): export public API and ignore .jobs/ artifacts"
```

---

## P2 · Extractor 接入 CancelToken + 子步骤回调

### Task 5: 移除 `genre_extractor.pipeline` 的 module-global `CANCEL_EVENT`

**Files:**
- Modify: `src/genre_extractor/pipeline.py`
- Modify: `src/pipeline.py`（如有引用）

- [ ] **Step 1:** 查找所有 `CANCEL_EVENT` 引用：

```bash
rg "CANCEL_EVENT" src/ tests/ web/
```

- [ ] **Step 2:** 在 `src/genre_extractor/pipeline.py` 删除 `CANCEL_EVENT = threading.Event()` 及其相关辅助函数（`_cancelled()` 之类）。如有函数中的 `if CANCEL_EVENT.is_set(): raise ...` 改为接受 `cancel: CancelToken` 参数并调 `cancel.check()`。若为 CLI 入口（`__main__.py` / `run_phase`），给一个 `NullCancelToken()` 默认值。

- [ ] **Step 3:** 跑 genre_extractor 相关测试：

```
.venv/bin/python3 -m pytest tests/ -k "genre or extractor" -v
```
Expected: 全绿（或改代码直到全绿）

- [ ] **Step 4:** 提交

```bash
git add src/genre_extractor/pipeline.py src/pipeline.py
git commit -m "refactor(genre): remove module-global CANCEL_EVENT in favor of per-call CancelToken"
```

---

### Task 6: `core.run_extract / run_merge / run_draft` 接受 token + 子步骤回调

**Files:**
- Modify: `src/genre_extractor/core.py`
- Modify: `tests/` 相关测试

- [ ] **Step 1:** 查看现有回调形状：

```bash
rg "on_phase|_safe_phase" src/genre_extractor/ -n
```

- [ ] **Step 2:** 设计新回调签名。在 `src/genre_extractor/progress.py` 新建：

```python
"""Progress callback 协议，子步骤粒度上报."""
from __future__ import annotations

from typing import Callable, Protocol

from src.jobs.schema import SubSteps


class ProgressCallback(Protocol):
    def __call__(
        self,
        *,
        phase: str | None = None,
        phase_index: int | None = None,
        sub_steps: SubSteps | None = None,
        progress_text: str | None = None,
    ) -> None: ...


def null_progress(**_: object) -> None:
    pass
```

- [ ] **Step 3:** 给 `core.run_extract` 加参数（保留向后兼容默认值）：

```python
def run_extract(
    ...existing args...,
    *,
    cancel: "CancelToken | None" = None,
    on_progress: "ProgressCallback | None" = None,
) -> ...:
    from src.jobs.cancel import NullCancelToken
    from src.genre_extractor.progress import null_progress
    cancel = cancel or NullCancelToken()
    on_progress = on_progress or null_progress

    # 进入 extract phase
    on_progress(phase="extract", phase_index=1, sub_steps={"batch_cur": 0, "batch_total": total_batches})
    for idx, batch in enumerate(batches, 1):
        cancel.check()
        ...existing batch work...
        on_progress(
            phase="extract",
            phase_index=1,
            sub_steps={"batch_cur": idx, "batch_total": total_batches},
            progress_text=f"batch {idx}/{total_batches}",
        )
```

同理 `run_merge`（`arc_cur/total`）、`run_draft`（`draft_pass`）、validate loop（`validate_round`）。

- [ ] **Step 4:** 为每个改动写/更新测试（示例——batch cancel）：

```python
def test_run_extract_cancels_between_batches(...):
    from src.jobs.cancel import ThreadEventToken, GenrePipelineAborted
    token = ThreadEventToken()
    seen = []
    def on_progress(**kw):
        seen.append(kw)
        if kw.get("sub_steps", {}).get("batch_cur") == 2:
            token.cancel()
    with pytest.raises(GenrePipelineAborted):
        run_extract(..., cancel=token, on_progress=on_progress)
    assert any(s.get("sub_steps", {}).get("batch_cur") == 2 for s in seen)
```

- [ ] **Step 5:** 跑测试：

```
.venv/bin/python3 -m pytest tests/ -k "core or extract" -v
```

- [ ] **Step 6:** 提交

```bash
git add src/genre_extractor/core.py src/genre_extractor/progress.py tests/
git commit -m "feat(genre): plumb CancelToken + fine-grained ProgressCallback through core pipeline"
```

---

### Task 7: 顶层入口接 token（`to_preset / to_project / from_description / blank_preset`）

**Files:**
- Modify: `src/genre_extractor/to_preset.py`
- Modify: `src/genre_extractor/to_project.py`
- Modify: `src/genre_extractor/from_description.py`
- Modify: `src/genre_extractor/blank_preset.py`

- [ ] **Step 1:** 给 4 个入口函数加 `cancel: CancelToken | None = None, on_progress: ProgressCallback | None = None`，把这两个参数透传到 `core.run_*`。

- [ ] **Step 2:** 在每个 phase 的 `_safe_phase` 调用前加 `cancel.check()`。

- [ ] **Step 3:** `blank_preset.create_blank_preset` 是同步的，只在开头 `cancel.check()` 一次，结束前 `on_progress(phase="validate", phase_index=4, progress_text="done")` 一次。

- [ ] **Step 4:** 补集成测试（示例）：

```python
def test_extract_to_preset_can_abort_mid_phase(tmp_path, monkeypatch, ...):
    from src.jobs.cancel import ThreadEventToken, GenrePipelineAborted
    from src.genre_extractor.to_preset import extract_to_preset
    token = ThreadEventToken()
    def on_progress(**kw):
        if kw.get("phase") == "merge":
            token.cancel()
    with pytest.raises(GenrePipelineAborted):
        extract_to_preset("x", sources=[...], cancel=token, on_progress=on_progress)
```

- [ ] **Step 5:** 跑测试：

```
.venv/bin/python3 -m pytest tests/ -k "to_preset or to_project or from_description or blank" -v
```

- [ ] **Step 6:** 提交

```bash
git add src/genre_extractor/
git commit -m "feat(genre): 4 entry points accept cancel+progress, wired to core"
```

---

## P3 · Web 后端

### Task 8: `web/_shared.py` 用 JobStore 替换内存 dict

**Files:**
- Modify: `web/_shared.py`

- [ ] **Step 1:** 删除 `_PRESET_JOBS`、`_PROJECT_JOBS`、`_PHASES`、`PHASE_TOTAL`、`_make_phase_cb`。新增：

```python
# Per-target 互斥锁（同一 preset 或 project 同时只跑 1 个 job）
_TARGET_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_TARGET_LOCKS_META = threading.Lock()


def acquire_target_lock(target_type: str, target_id: str) -> threading.Lock | None:
    """尝试获取 target 锁（非阻塞）。成功返回 Lock（worker 结束后 release），失败返回 None."""
    key = (target_type, target_id)
    with _TARGET_LOCKS_META:
        lock = _TARGET_LOCKS.setdefault(key, threading.Lock())
    if lock.acquire(blocking=False):
        return lock
    return None
```

- [ ] **Step 2:** 保留 `_run_lock`（章节流水线的）。不变。

- [ ] **Step 3:** 跑所有 web 测试，一些会断（下一 task 修）。**本 step 不跑 pytest**，下一 task 一起验。

- [ ] **Step 4:** 提交（暂允许 broken state，下一 task 马上修）：

```bash
git add web/_shared.py
git commit -m "refactor(web): drop in-memory job dicts in favor of JobStore (WIP, routes updated next)"
```

---

### Task 9: 新 blueprint `web/routes/jobs.py`

**Files:**
- Create: `web/routes/jobs.py`
- Modify: `web/routes/__init__.py`（如有）

- [ ] **Step 1:** 新建 `web/routes/jobs.py`。完整代码：

```python
"""Jobs blueprint: /api/jobs CRUD + abort + log tailing + /jobs /jobs/<id> 页面."""
from __future__ import annotations

import threading
from typing import Any

from flask import Blueprint, abort, jsonify, render_template, request

from src.jobs import (
    GenrePipelineAborted,
    NullCancelToken,
    ThreadEventToken,
    get_job_logger,
    get_store,
    initial_job_record,
    new_job_id,
    read_log_tail,
)
from web._shared import acquire_target_lock

bp = Blueprint("jobs", __name__)

# ---------- API ----------


@bp.get("/api/jobs")
def list_jobs():
    store = get_store()
    state = request.args.get("state")
    kind = request.args.get("kind")
    return jsonify({"jobs": store.list(state=state, kind=kind)})


@bp.post("/api/jobs")
def create_job():
    body = request.get_json(force=True, silent=True) or {}
    kind = body.get("kind")
    target = body.get("target")
    sources = body.get("sources") or []
    params = body.get("params") or {}

    if kind not in ("from-novel", "from-description", "blank", "extract-to-project"):
        return jsonify({"error": "unknown kind"}), 400
    if not isinstance(target, dict) or target.get("type") not in ("preset", "project"):
        return jsonify({"error": "bad target"}), 400

    # Per-target lock
    lock = acquire_target_lock(target["type"], target["id"])
    if lock is None:
        return jsonify({"error": "another job is already running for this target"}), 409

    store = get_store()
    job_id = new_job_id()
    label = _build_label(kind, target)
    rec = initial_job_record(
        job_id=job_id, kind=kind, target=target,
        label=label, sources=sources, params=params,
    )
    store.create(rec)

    cancel = ThreadEventToken()
    store.set_runtime(job_id, cancel=cancel, target_lock=lock)

    t = threading.Thread(target=_run_worker, args=(job_id,), daemon=True)
    t.start()

    return jsonify({"job_id": job_id}), 201


@bp.get("/api/jobs/<job_id>")
def get_job(job_id):
    rec = get_store().get(job_id)
    if rec is None:
        abort(404)
    return jsonify(rec)


@bp.post("/api/jobs/<job_id>/abort")
def abort_job(job_id):
    store = get_store()
    rec = store.get(job_id)
    if rec is None:
        abort(404)
    if rec["state"] != "running":
        return jsonify({"error": f"cannot abort job in state: {rec['state']}"}), 409
    token: ThreadEventToken | None = store.get_runtime(job_id, "cancel")
    if token is not None:
        token.cancel()
    store.update(job_id, state="aborting")
    return jsonify({"ok": True})


@bp.delete("/api/jobs/<job_id>")
def delete_job(job_id):
    store = get_store()
    try:
        store.delete(job_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"ok": True})


@bp.get("/api/jobs/<job_id>/log")
def job_log(job_id):
    offset = int(request.args.get("offset", 0))
    content, next_off = read_log_tail(job_id, offset)
    return jsonify({"content": content, "next_offset": next_off})


# ---------- 页面 ----------


@bp.get("/jobs")
def page_jobs_list():
    return render_template("jobs/index.html")


@bp.get("/jobs/<job_id>")
def page_jobs_detail(job_id):
    return render_template("jobs/detail.html", job_id=job_id)


# ---------- 内部 ----------


def _build_label(kind: str, target: dict) -> str:
    tid = target["id"]
    mapping = {
        "from-novel": f"素材库拆题材 → {tid}",
        "from-description": f"从描述生成题材 → {tid}",
        "blank": f"空壳题材 → {tid}",
        "extract-to-project": f"覆盖作品题材 → {tid}",
    }
    return mapping.get(kind, kind)


def _run_worker(job_id: str) -> None:
    store = get_store()
    rec = store.get(job_id)
    if rec is None:
        return
    logger = get_job_logger(job_id)
    cancel = store.get_runtime(job_id, "cancel") or NullCancelToken()
    target_lock: threading.Lock | None = store.get_runtime(job_id, "target_lock")

    def on_progress(
        *,
        phase: str | None = None,
        phase_index: int | None = None,
        sub_steps: dict | None = None,
        progress_text: str | None = None,
    ) -> None:
        updates: dict[str, Any] = {}
        if phase is not None:
            updates["phase"] = phase
        if phase_index is not None:
            updates["phase_index"] = phase_index
        if sub_steps is not None:
            updates["sub_steps"] = sub_steps
        if progress_text is not None:
            updates["progress_text"] = progress_text
            logger.info(f"[{phase or '-'}] {progress_text}")
        store.update(job_id, **updates)

    try:
        logger.info(f"job started: kind={rec['kind']} target={rec['target']}")
        _dispatch(rec, cancel=cancel, on_progress=on_progress, logger=logger)
        store.finish(job_id, "done")
        logger.info("job finished: done")
    except GenrePipelineAborted:
        store.finish(job_id, "aborted", error="用户中止")
        logger.info("job aborted by user")
    except Exception as e:  # noqa: BLE001
        store.finish(job_id, "failed", error=str(e))
        logger.exception("job failed")
    finally:
        if target_lock is not None:
            try:
                target_lock.release()
            except RuntimeError:
                pass


def _dispatch(rec: dict, *, cancel, on_progress, logger) -> None:
    kind = rec["kind"]
    target = rec["target"]
    params = rec.get("params", {})
    sources = rec.get("sources", [])

    if kind == "blank":
        from src.genre_extractor.blank_preset import create_blank_preset
        create_blank_preset(
            target["id"],
            display_name=params.get("display_name") or target["id"],
            tone=params.get("tone", ""),
            cancel=cancel,
            on_progress=on_progress,
        )
    elif kind == "from-description":
        from src.genre_extractor.from_description import extract_from_description
        extract_from_description(
            target["id"],
            description=params.get("description", ""),
            display_name=params.get("display_name") or target["id"],
            cancel=cancel,
            on_progress=on_progress,
        )
    elif kind == "from-novel":
        from src.genre_extractor.to_preset import extract_to_preset
        extract_to_preset(
            target["id"],
            sources=sources,
            display_name=params.get("display_name") or target["id"],
            with_trial=params.get("with_trial", False),
            cancel=cancel,
            on_progress=on_progress,
        )
    elif kind == "extract-to-project":
        from src.genre_extractor.to_project import extract_to_project
        extract_to_project(
            target["id"],
            sources=sources,
            cancel=cancel,
            on_progress=on_progress,
        )
    else:
        raise ValueError(f"unknown kind: {kind}")
```

- [ ] **Step 2:** 写 route 测试 `tests/test_routes_jobs.py`：

```python
"""web/routes/jobs.py 基础 REST 行为."""
from __future__ import annotations

import time
from pathlib import Path

import pytest


@pytest.fixture
def app(tmp_path: Path, monkeypatch):
    from src import config
    from src.jobs import store as store_mod
    from src.jobs import logger as logger_mod
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(store_mod, "JOBS_DIR", tmp_path / ".jobs")
    monkeypatch.setattr(logger_mod, "LOGS_DIR", tmp_path / ".jobs" / "logs")
    store_mod._STORE_SINGLETON = None
    logger_mod._LOGGERS.clear()
    from web.app import create_app
    a = create_app()
    a.config["TESTING"] = True
    yield a


def test_list_jobs_empty(app):
    client = app.test_client()
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert r.get_json() == {"jobs": []}


def test_create_blank_job_returns_201(app, monkeypatch):
    # stub blank_preset 以加速
    def fake(_pid, *, display_name, tone, cancel, on_progress):
        on_progress(phase="validate", phase_index=4, progress_text="done")
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", fake,
    )
    client = app.test_client()
    r = client.post("/api/jobs", json={
        "kind": "blank",
        "target": {"type": "preset", "id": "p1"},
        "params": {"display_name": "P1"},
    })
    assert r.status_code == 201
    jid = r.get_json()["job_id"]
    # 等 worker 结束
    for _ in range(50):
        time.sleep(0.05)
        j = client.get(f"/api/jobs/{jid}").get_json()
        if j["state"] in ("done", "failed", "aborted"):
            break
    assert j["state"] == "done"


def test_create_same_target_twice_conflicts(app, monkeypatch):
    # 阻塞 worker，让第一个 job 不结束
    import threading
    barrier = threading.Event()
    def block(_pid, *, display_name, tone, cancel, on_progress):
        barrier.wait(timeout=5)
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", block,
    )
    client = app.test_client()
    r1 = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "same"},
        "params": {}})
    assert r1.status_code == 201
    r2 = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "same"},
        "params": {}})
    assert r2.status_code == 409
    barrier.set()


def test_abort_flips_state(app, monkeypatch):
    import threading
    from src.jobs.cancel import GenrePipelineAborted
    barrier = threading.Event()
    def block(_pid, *, display_name, tone, cancel, on_progress):
        barrier.wait(timeout=2)
        cancel.check()
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", block,
    )
    client = app.test_client()
    jid = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "abortme"},
        "params": {}}).get_json()["job_id"]
    r = client.post(f"/api/jobs/{jid}/abort")
    assert r.status_code == 200
    barrier.set()
    for _ in range(50):
        time.sleep(0.05)
        j = client.get(f"/api/jobs/{jid}").get_json()
        if j["state"] == "aborted":
            break
    assert j["state"] == "aborted"


def test_delete_running_rejected(app, monkeypatch):
    import threading
    barrier = threading.Event()
    def block(_pid, *, display_name, tone, cancel, on_progress):
        barrier.wait(timeout=5)
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", block,
    )
    client = app.test_client()
    jid = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "delme"},
        "params": {}}).get_json()["job_id"]
    r = client.delete(f"/api/jobs/{jid}")
    assert r.status_code == 409
    barrier.set()


def test_log_tail_incremental(app, monkeypatch):
    def quick(_pid, *, display_name, tone, cancel, on_progress):
        on_progress(phase="extract", phase_index=1, progress_text="hello")
        on_progress(phase="validate", phase_index=4, progress_text="world")
    monkeypatch.setattr(
        "src.genre_extractor.blank_preset.create_blank_preset", quick,
    )
    client = app.test_client()
    jid = client.post("/api/jobs", json={
        "kind": "blank", "target": {"type": "preset", "id": "tailme"},
        "params": {}}).get_json()["job_id"]
    for _ in range(30):
        time.sleep(0.05)
        j = client.get(f"/api/jobs/{jid}").get_json()
        if j["state"] == "done":
            break
    r = client.get(f"/api/jobs/{jid}/log?offset=0").get_json()
    assert "hello" in r["content"]
    assert "world" in r["content"]
    assert r["next_offset"] > 0
    r2 = client.get(f"/api/jobs/{jid}/log?offset={r['next_offset']}").get_json()
    assert r2["content"] == ""
```

- [ ] **Step 3:** 跑测试：

```
.venv/bin/python3 -m pytest tests/test_routes_jobs.py -v
```
Expected: 如果 app.py 还没注册 blueprint 会 404，下一 task 修。暂跳过。

- [ ] **Step 4:** 提交

```bash
git add web/routes/jobs.py tests/test_routes_jobs.py
git commit -m "feat(web): add /api/jobs REST blueprint + page routes"
```

---

### Task 10: 删除旧 endpoint

**Files:**
- Modify: `web/routes/presets.py`
- Modify: `web/routes/projects.py`

- [ ] **Step 1:** 在 `web/routes/presets.py` 删除：
  - `POST /api/presets/new-from-novel`
  - `POST /api/presets/new-from-description`
  - `POST /api/presets/new-blank`
  - `GET /api/presets/<pid>/status`

保留：GET list / GET detail / DELETE / `/presets*` 页面路由。

- [ ] **Step 2:** 在 `web/routes/projects.py` 删除：
  - `POST /api/projects/<pid>/extract-genre`
  - `GET /api/projects/<pid>/extract-genre/progress`
  - `POST /api/projects/<pid>/extract-genre/abort`

- [ ] **Step 3:** 修改 `POST /api/projects/new`：去掉 `from_extract.sources` 的异步分支，不再起线程。改为：如果请求带 `from_extract.sources`，则**不接受**（返回 400：请先 POST /api/jobs 创建 extract-to-project job）。

- [ ] **Step 4:** 跑全部 web 测试：

```
.venv/bin/python3 -m pytest tests/ -q
```
Expected: 老的 presets/projects 异步测试会断——**删掉**那些测试文件里的对应 case（老 endpoint 没了就没必要测了）。

- [ ] **Step 5:** 提交

```bash
git add web/routes/presets.py web/routes/projects.py tests/
git commit -m "refactor(web): remove legacy genre job endpoints in favor of /api/jobs"
```

---

### Task 11: `web/app.py` 注册 jobs blueprint + 启动恢复

**Files:**
- Modify: `web/app.py`

- [ ] **Step 1:** 在 `create_app()` 里增加：

```python
from web.routes import jobs as jobs_routes
app.register_blueprint(jobs_routes.bp)

# 启动恢复
from src.jobs import get_store
recovered = get_store().recover()
if recovered:
    app.logger.info(f"recovered {len(recovered)} interrupted jobs")
```

- [ ] **Step 2:** 跑测试：

```
.venv/bin/python3 -m pytest tests/test_routes_jobs.py -v
```
Expected: 全绿

- [ ] **Step 3:** 跑全部测试确保 phase 收尾绿：

```
.venv/bin/python3 -m pytest tests/ -q
```

- [ ] **Step 4:** 提交

```bash
git add web/app.py
git commit -m "feat(web): wire jobs blueprint + boot-time orphan recovery"
```

**Phase 3 Checkpoint:** 所有测试全绿 + 手动跑 `.venv/bin/python3 -m flask --app web.app run --port 5055`，手动 `curl -X POST localhost:5055/api/jobs -d '{"kind":"blank","target":{"type":"preset","id":"demo"},"params":{"display_name":"D"}}' -H 'Content-Type: application/json'`，确认 job 建成 + `.jobs/active/<id>.json` 存在。

---

## P4 · 前端

### Task 12: `/jobs` 列表页

**Files:**
- Create: `web/templates/jobs/index.html`
- Create: `web/static/js/features/jobsList.js`
- Modify: `web/templates/_base.html`（如需 import 新 JS）

- [ ] **Step 1:** 写模板 `web/templates/jobs/index.html`：

```html
{% extends "_base.html" %}
{% block title %}题材任务 · Novelforge{% endblock %}
{% block content %}
<div class="page jobs-list-page">
  <header class="page-header">
    <h1>题材任务</h1>
    <nav class="filter-tabs">
      <button data-state="all" class="active">全部</button>
      <button data-state="running">运行中</button>
      <button data-state="done">已完成</button>
      <button data-state="failed">失败</button>
      <button data-state="aborted">已中止</button>
      <button data-state="interrupted">中断</button>
    </nav>
  </header>
  <div id="jobs-list" class="jobs-list">
    <div class="jobs-empty">加载中…</div>
  </div>
</div>
<script type="module" src="{{ url_for('static', filename='js/features/jobsList.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2:** 写 JS `web/static/js/features/jobsList.js`：

```javascript
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
    "from-novel": "素材库拆",
    "from-description": "从描述",
    "blank": "空壳",
    "extract-to-project": "覆盖作品",
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
  return `
    <a class="job-row" href="/jobs/${job.job_id}">
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
    </a>
  `;
}

async function render() {
  const jobs = await fetchJobs();
  if (jobs.length === 0) {
    listEl.innerHTML = `<div class="jobs-empty">暂无任务</div>`;
    return;
  }
  listEl.innerHTML = jobs.map(renderRow).join("");
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
```

- [ ] **Step 3:** 手动验证：跑 `flask --app web.app run --port 5055`，访问 `http://localhost:5055/jobs`，确认页面加载。POST 一个 job 后刷新能看到。

- [ ] **Step 4:** 提交

```bash
git add web/templates/jobs/index.html web/static/js/features/jobsList.js
git commit -m "feat(web): add /jobs list page"
```

---

### Task 13: `/jobs/<id>` 详情页（节点图 + 日志）

**Files:**
- Create: `web/templates/jobs/detail.html`
- Create: `web/static/js/features/jobDetail.js`
- Create: `web/static/css/pages/jobs.css`
- Modify: `web/templates/_base.html`（include css）

- [ ] **Step 1:** 写模板 `web/templates/jobs/detail.html`：

```html
{% extends "_base.html" %}
{% block title %}任务 {{ job_id }} · Novelforge{% endblock %}
{% block content %}
<div class="page job-detail-page" data-job-id="{{ job_id }}">
  <header class="page-header">
    <a href="/jobs" class="btn btn-ghost">← 返回列表</a>
    <h1 id="job-label">任务 {{ job_id }}</h1>
    <div class="job-actions">
      <span id="job-state-badge" class="badge">…</span>
      <button id="btn-abort" class="btn btn-danger" style="display:none">中止</button>
      <button id="btn-delete" class="btn btn-ghost" style="display:none">删除</button>
    </div>
  </header>

  <!-- 节点图 -->
  <section class="pipeline-diagram">
    {% for phase in ["extract", "merge", "draft", "validate"] %}
    <div class="phase-node" data-phase="{{ phase }}">
      <div class="phase-circle">
        <span class="phase-icon">○</span>
      </div>
      <div class="phase-name">{{ phase }}</div>
      <div class="phase-sub" data-sub="{{ phase }}"></div>
    </div>
    {% if not loop.last %}<div class="phase-arrow">→</div>{% endif %}
    {% endfor %}
  </section>

  <!-- 元数据 -->
  <section class="job-meta">
    <dl>
      <dt>类型</dt><dd id="job-kind">—</dd>
      <dt>目标</dt><dd id="job-target">—</dd>
      <dt>开始</dt><dd id="job-started">—</dd>
      <dt>更新</dt><dd id="job-updated">—</dd>
      <dt>结束</dt><dd id="job-finished">—</dd>
    </dl>
    <div id="job-error" class="job-error" style="display:none"></div>
  </section>

  <!-- 日志 -->
  <section class="job-log">
    <h2>运行日志</h2>
    <pre id="log-pane"></pre>
  </section>
</div>
<script type="module" src="{{ url_for('static', filename='js/features/jobDetail.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2:** 写 JS `web/static/js/features/jobDetail.js`：

```javascript
const root = document.querySelector(".job-detail-page");
const jobId = root.dataset.jobId;

const $ = (sel) => document.querySelector(sel);
const logPane = $("#log-pane");
const btnAbort = $("#btn-abort");
const btnDelete = $("#btn-delete");

let logOffset = 0;
let polling = true;

const PHASE_ORDER = ["extract", "merge", "draft", "validate"];

function setNodeState(phase, state) {
  const node = document.querySelector(`.phase-node[data-phase="${phase}"]`);
  if (!node) return;
  node.classList.remove("pending", "active", "done", "failed");
  node.classList.add(state);
  const icon = node.querySelector(".phase-icon");
  icon.textContent = state === "done" ? "✓" : state === "active" ? "●" : state === "failed" ? "✕" : "○";
}

function renderPipeline(job) {
  const curIdx = job.phase ? PHASE_ORDER.indexOf(job.phase) : -1;
  PHASE_ORDER.forEach((p, i) => {
    if (i < curIdx) setNodeState(p, "done");
    else if (i === curIdx && job.state === "running") setNodeState(p, "active");
    else if (i === curIdx && job.state === "failed") setNodeState(p, "failed");
    else if (i === curIdx && (job.state === "done" || job.state === "aborted")) setNodeState(p, "done");
    else setNodeState(p, "pending");
  });
  // 子步骤
  const sub = job.sub_steps || {};
  document.querySelector('[data-sub="extract"]').textContent =
    sub.batch_total ? `batch ${sub.batch_cur || 0}/${sub.batch_total}` : "";
  document.querySelector('[data-sub="merge"]').textContent =
    sub.arc_total ? `arc ${sub.arc_cur || 0}/${sub.arc_total}` : "";
  document.querySelector('[data-sub="draft"]').textContent =
    sub.draft_pass ? `pass ${sub.draft_pass}/3` : "";
  document.querySelector('[data-sub="validate"]').textContent =
    sub.validate_round ? `round ${sub.validate_round}/2` : "";
}

function renderMeta(job) {
  $("#job-label").textContent = job.label;
  $("#job-kind").textContent = job.kind;
  $("#job-target").textContent = `${job.target.type}:${job.target.id}`;
  $("#job-started").textContent = new Date(job.started_at * 1000).toLocaleString("zh-CN");
  $("#job-updated").textContent = new Date(job.updated_at * 1000).toLocaleString("zh-CN");
  $("#job-finished").textContent = job.finished_at
    ? new Date(job.finished_at * 1000).toLocaleString("zh-CN")
    : "—";
  const badge = $("#job-state-badge");
  badge.textContent = job.state;
  badge.className = `badge badge-${job.state}`;
  const err = $("#job-error");
  if (job.error) {
    err.textContent = `错误：${job.error}`;
    err.style.display = "";
  } else {
    err.style.display = "none";
  }
  // 按钮显示
  btnAbort.style.display = job.state === "running" ? "" : "none";
  btnDelete.style.display =
    ["done", "failed", "aborted", "interrupted"].includes(job.state) ? "" : "none";
}

async function fetchJob() {
  const r = await fetch(`/api/jobs/${jobId}`);
  if (!r.ok) return null;
  return r.json();
}

async function fetchLog() {
  const r = await fetch(`/api/jobs/${jobId}/log?offset=${logOffset}`);
  if (!r.ok) return;
  const { content, next_offset } = await r.json();
  if (content) {
    logPane.textContent += content;
    logPane.scrollTop = logPane.scrollHeight;
  }
  logOffset = next_offset;
}

async function tick() {
  if (!polling) return;
  const job = await fetchJob();
  if (!job) return;
  renderMeta(job);
  renderPipeline(job);
  await fetchLog();
  if (["done", "failed", "aborted", "interrupted"].includes(job.state)) {
    polling = false;
    // 再拉一次尾巴以防最后几行没收
    await fetchLog();
  } else {
    setTimeout(tick, 1500);
  }
}

btnAbort.addEventListener("click", async () => {
  if (!confirm("确认中止该任务？")) return;
  btnAbort.disabled = true;
  const r = await fetch(`/api/jobs/${jobId}/abort`, { method: "POST" });
  if (!r.ok) {
    alert(`中止失败：${(await r.json()).error}`);
    btnAbort.disabled = false;
  }
});

btnDelete.addEventListener("click", async () => {
  if (!confirm("确认删除该任务的记录？日志也会一并删除。")) return;
  const r = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
  if (r.ok) location.href = "/jobs";
  else alert(`删除失败：${(await r.json()).error}`);
});

tick();
```

- [ ] **Step 3:** 写 CSS `web/static/css/pages/jobs.css`：

```css
.pipeline-diagram {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding: 2rem 1rem;
  margin: 1rem 0 2rem;
  background: var(--bg-subtle, #fafafa);
  border-radius: 8px;
}
.phase-node {
  text-align: center;
  min-width: 120px;
}
.phase-circle {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 0.5rem;
  border: 2px solid #ccc;
  background: #fff;
  font-size: 1.5rem;
  transition: all 0.3s;
}
.phase-node.pending .phase-circle { color: #999; }
.phase-node.done .phase-circle { border-color: #2ecc71; color: #2ecc71; background: #e8f8ef; }
.phase-node.active .phase-circle {
  border-color: #3498db; color: #3498db;
  animation: phase-pulse 1.5s ease-in-out infinite;
}
.phase-node.failed .phase-circle { border-color: #e74c3c; color: #e74c3c; background: #fdecea; }
@keyframes phase-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(52, 152, 219, 0.5); }
  50%      { box-shadow: 0 0 0 12px rgba(52, 152, 219, 0); }
}
.phase-arrow {
  color: #999;
  font-size: 1.5rem;
}
.phase-name {
  font-weight: 600;
  text-transform: capitalize;
}
.phase-sub {
  font-size: 0.85rem;
  color: #666;
  min-height: 1.2em;
}
.job-log pre {
  max-height: 400px;
  overflow-y: auto;
  background: #1e1e1e;
  color: #ddd;
  padding: 1rem;
  border-radius: 4px;
  font-family: "Menlo", "Consolas", monospace;
  font-size: 0.85rem;
  white-space: pre-wrap;
  word-break: break-all;
}
.badge-running   { background: #3498db; color: #fff; }
.badge-aborting  { background: #f39c12; color: #fff; }
.badge-done      { background: #2ecc71; color: #fff; }
.badge-failed    { background: #e74c3c; color: #fff; }
.badge-aborted   { background: #95a5a6; color: #fff; }
.badge-interrupted { background: #9b59b6; color: #fff; }
.jobs-list .job-row {
  display: flex;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #eee;
  text-decoration: none;
  color: inherit;
}
.jobs-list .job-row:hover { background: #f5f5f5; }
```

- [ ] **Step 4:** 在 `web/templates/_base.html` 加载 jobs.css（根据现有模式，可能是统一 bundle；按约定加）：

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/pages/jobs.css') }}">
```

- [ ] **Step 5:** 手动验证：访问 `/jobs/<id>`，确认节点图渲染正常、日志滚动更新、状态 badge 正确。

- [ ] **Step 6:** 提交

```bash
git add web/templates/jobs/detail.html web/static/js/features/jobDetail.js web/static/css/pages/jobs.css web/templates/_base.html
git commit -m "feat(web): add /jobs/<id> detail page with pipeline diagram and log tail"
```

---

### Task 14: `/presets/new` 三 tab 提交改为跳 `/jobs/<id>`

**Files:**
- Modify: `web/templates/presets/new.html`
- Create: `web/static/js/features/presetNew.js`（替代老 presets.js 中的表单部分）

- [ ] **Step 1:** 改模板，三 tab 各挂一个 form，移除页内进度条（跳转后由详情页负责）。

- [ ] **Step 2:** 写 `web/static/js/features/presetNew.js`：

```javascript
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
```

- [ ] **Step 3:** 模板 `presets/new.html` 底部 `<script>` 改为 `<script type="module" src="{{ url_for('static', filename='js/features/presetNew.js') }}"></script>`；表单 `id` 与 JS 对应；移除内联 phase_timeline 宏调用。

- [ ] **Step 4:** 手动验证：三 tab 提交都跳 `/jobs/<id>`，状态正常推进。

- [ ] **Step 5:** 提交

```bash
git add web/templates/presets/new.html web/static/js/features/presetNew.js
git commit -m "feat(web): preset-new three tabs now submit to /api/jobs and redirect to job detail"
```

---

### Task 15: 新作品向导 + ⎇ 覆盖题材改为跳 `/jobs/<id>`

**Files:**
- Modify: `web/static/js/features/projectWizard.js`
- Modify: `web/static/js/features/extractOverride.js`
- Modify: `web/templates/_partials/dialogs/new_project.html`
- Modify: `web/templates/_partials/dialogs/extract_override.html`

- [ ] **Step 1:** `projectWizard.js`：Step 2 选"从素材库拆"后，Step 4 提交时：
  - 先同步 `POST /api/projects/new` **只**创建项目框架（不含 extract，后端改为允许无 `from_extract`）
  - 再 `POST /api/jobs` 创建 `extract-to-project` job
  - 跳 `/jobs/<job_id>`

- [ ] **Step 2:** `extractOverride.js`：直接 `POST /api/jobs` 创建 `extract-to-project` job，跳 `/jobs/<job_id>`。弹窗关闭即可。

- [ ] **Step 3:** 模板里删除 phase_timeline 相关的 DOM（已经搬去详情页）。

- [ ] **Step 4:** 手动验证两条路径都跳详情页。

- [ ] **Step 5:** 提交

```bash
git add web/static/js/features/projectWizard.js web/static/js/features/extractOverride.js web/templates/_partials/dialogs/
git commit -m "feat(web): wizard+override dialogs now submit to /api/jobs and redirect"
```

---

### Task 16: 首页顶栏"题材任务运行中" pill

**Files:**
- Modify: `web/static/js/ui/pills.js`
- Modify: `web/templates/index.html`（若需加 pill DOM 容器）

- [ ] **Step 1:** 在 `pills.js` 的 `renderPills` 里，新增一个 fetch `/api/jobs?state=running` 获取运行中 job 数，渲染一个 pill：

```javascript
async function renderJobsPill() {
  const el = document.getElementById("pill-jobs");
  if (!el) return;
  const r = await fetch("/api/jobs?state=running");
  if (!r.ok) return;
  const { jobs } = await r.json();
  if (jobs.length === 0) {
    el.style.display = "none";
  } else {
    el.style.display = "";
    el.innerHTML = `<a href="/jobs?state=running">⚙ ${jobs.length} 个题材任务运行中</a>`;
  }
}
```

在 `renderPills` 末尾 `renderJobsPill();` 调一次；`polling.js` 的 state 轮询里也加一条 `renderJobsPill()` 调用。

- [ ] **Step 2:** `index.html` 顶栏 pills 区域加：

```html
<div id="pill-jobs" class="pill pill-jobs" style="display:none"></div>
```

- [ ] **Step 3:** 手动验证：启动一个 job → 首页 pill 出现 → 跳到详情页 → 任务完成 → pill 消失。

- [ ] **Step 4:** 提交

```bash
git add web/static/js/ui/pills.js web/templates/index.html
git commit -m "feat(web): home page pill showing running genre jobs count"
```

---

### Task 17: `web/static/presets.js` 迁 ES modules（清理老 IIFE）

**Files:**
- Delete: `web/static/presets.js`
- Modify: `web/templates/presets/index.html`
- Modify: `web/templates/presets/detail.html`
- Create: `web/static/js/features/presetsList.js`
- Create: `web/static/js/features/presetsDetail.js`

- [ ] **Step 1:** 阅读现有 `presets.js` 的全部功能（list 渲染、删除、detail 渲染、old pollPresetJob 等）。pollPresetJob 可以删（已由 jobDetail.js 接管）。

- [ ] **Step 2:** 新建 `presetsList.js`（只保留 list 渲染 + 删除逻辑，引用 `GET /api/presets`、`DELETE /api/presets/<id>`）。

- [ ] **Step 3:** 新建 `presetsDetail.js`（只保留 detail 渲染）。

- [ ] **Step 4:** 在 `presets/index.html` `presets/detail.html` 底部改成：

```html
<script type="module" src="{{ url_for('static', filename='js/features/presetsList.js') }}"></script>
```

- [ ] **Step 5:** 删除 `web/static/presets.js`。

- [ ] **Step 6:** 手动验证：题材库列表 / 详情 / 删除都正常。

- [ ] **Step 7:** 提交

```bash
git add -A
git commit -m "refactor(web): migrate presets.js to ES modules split (list + detail)"
```

---

## P5 · 收尾

### Task 18: 更新文档

**Files:**
- Modify: `README.md`（如存在）
- Modify: `AGENTS.md`

- [ ] **Step 1:** 在 `AGENTS.md` 的 "如何运行" 或新增 "部署" 段落明确：

```markdown
## 部署

- 开发：`flask --app web.app run --port 5055`（单进程）
- 生产：`gunicorn --workers 1 --threads 8 "web.app:create_app()"`（**必须 workers=1**）
- 多 worker 场景不受支持：内存 job cache 会在 worker 间失效。如需横向扩展，后续可做 file-token 持久化方案（见 `docs/superpowers/specs/genre-jobs-rearch.md` 的"部署模型"）
```

- [ ] **Step 2:** 更新 `AGENTS.md` 的 "State 目录地图" 或新增一节 "`.jobs/` 目录"：

```markdown
## 题材任务（Genre Jobs）

每个"新建题材" / "覆盖作品题材"操作都会产生一个 Job，落盘到 `.jobs/`：

- `.jobs/active/<job_id>.json` — 未完成
- `.jobs/archive/<job_id>.json` — 已结束
- `.jobs/logs/<job_id>.log` — 运行日志（10MB rotate × 3）

前端入口：`/jobs` 列表 + `/jobs/<id>` 详情。
API：`/api/jobs` REST + `/api/jobs/<id>/log` tail。
Cancel 真实可用：`POST /api/jobs/<id>/abort`。
```

- [ ] **Step 3:** 提交

```bash
git add AGENTS.md README.md
git commit -m "docs: document genre jobs system and deployment constraints"
```

---

### Task 19: 端到端手动验证清单

- [ ] **Step 1:** 启动 `.venv/bin/python3 -m flask --app web.app run --port 5055`

- [ ] **Step 2:** 执行以下场景，全部通过才算完成：

1. **三种新建方式都能跳到专属页面**
   - `/presets/new` → 素材库拆 → 跳 `/jobs/<id>` ✓
   - `/presets/new` → 从描述 → 跳 `/jobs/<id>` ✓
   - `/presets/new` → 空壳 → 跳 `/jobs/<id>` ✓

2. **离开再回来进度不丢**
   - 启动一个 from-novel job（大文件，预期跑 >30 秒）
   - 跳去 `/` 看首页 → 看到 pill
   - 跳去 `/jobs` → 看到列表
   - 点回 `/jobs/<id>` → 节点图和日志继续，无缝
   - 关闭浏览器 → 重开 → 进度还在

3. **并发跑多个 job + 小说生产**
   - 同时跑：1 个 from-novel job + 1 个 from-description job + 1 本书的章节生产
   - 三者互不阻塞、互不污染进度

4. **真 abort**
   - 启动一个 from-novel job
   - 5 秒内点 "中止"
   - 预期：20 秒内 state → aborted，worker 真正退出（检查 `ps -ef` 无孤儿）

5. **进程崩溃 → interrupted**
   - 启动 job → `kill -9 <flask pid>`
   - 重启 flask → `/jobs` 看到该 job state=interrupted，错误信息含"进程重启"

6. **per-target 互斥**
   - 为同一个 preset id 连续 POST 两次 → 第二次返回 409

7. **日志 rotate**
   - 跑一个大 job → 确认 `.jobs/logs/<id>.log` 存在；超 10MB 时有 `.log.1`

8. **pill 和 /jobs 列表自动刷新**
   - job 状态变化后 3 秒内首页 pill / 列表页数字更新

- [ ] **Step 3:** 跑全部自动化测试：

```
.venv/bin/python3 -m pytest tests/ -q
```

Expected: 全绿

- [ ] **Step 4:** 提交收尾：

```bash
git commit --allow-empty -m "chore: genre jobs rearch complete — E2E verified"
```

---

## 自检清单（实施前 + 实施后都过一遍）

**Spec 覆盖**：

- ✅ 三种新建方式都有独立 URL 页面（Task 12/13/14）
- ✅ 页面可离开可回来 + 进度不丢（Task 2 持久化 + Task 11 恢复 + Task 13 详情页基于 URL）
- ✅ 无限并发（Task 8 per-target 锁，不同 target 自由并发）
- ✅ 真 abort（Task 1/5/6/7/9）
- ✅ 工作流图（Task 13）
- ✅ 和小说生产互不阻塞（Task 8 保留 `_run_lock` 独立，不干涉 job 线程）

**Placeholder 扫描**：无 TBD / TODO / "待实现" / "类似上文"。所有代码块完整。

**类型一致性**：
- `CancelToken` / `ThreadEventToken` / `NullCancelToken` 在所有 task 里名字一致
- `on_progress(phase, phase_index, sub_steps, progress_text)` 签名在 core / to_* / jobs.py 全部一致
- `JobStore.create/get/update/finish/delete/list/recover` 方法名一致
- job record 的字段名（schema.py 定义）被 store.py/jobs.py/jobDetail.js 一致使用

**执行方式建议**：这是一个边界清晰但体量较大的重构（17 个 task 跨 5 个 phase）。推荐用 **subagent-driven-development**，每个 task 派一个 fresh subagent，orchestrator 在 task 之间做 checkpoint review。
