# 题材任务（Genre Jobs）重构 · 设计

## 背景

当前"新建题材"功能存在三个问题：

1. **进度只在内存**：`web/_shared.py` 的 `_PRESET_JOBS` / `_PROJECT_JOBS` 内存 dict 进程重启即丢。
2. **进度只在弹窗里看**：4 phase timeline 只在新作品向导 / ⎇ 覆盖题材对话框里；关掉对话框就丢视图。
3. **abort 是假的**：`/api/projects/<pid>/extract-genre/abort` 只翻 dict 字段，后台线程继续跑。

用户诉求：

- 点击"新建题材"选三种方式之一后 → 进入**独立 URL 页面**展示工作流
- 页面可离开可回来，**进度不丢**
- 支持**无限并发**（多个题材 job + 章节生产并行）
- 真正的 abort

## 架构决策

### 部署模型

**gunicorn `--workers=1 --threads=N`** 或开发模式 flask run。原因：
- Python GIL 对 LLM I/O 等待类负载不阻塞真实并发
- 多 worker 场景下内存 dict 必然失效；单 worker 多线程是最低复杂度方案
- README 需明确此约束

### Job 存储：文件落盘 + 内存缓存

```
.jobs/
  active/<job_id>.json       # 未完成的 job
  archive/<job_id>.json      # 已结束的 job
  logs/<job_id>.log          # 滚动日志（单文件软上限 10MB，保留 3 份）
```

- 进 `.gitignore`
- 内存层 `_JOBS: dict[str, dict]` 在 `web/_shared.py`，作为 active 的快速读取缓存
- 每次状态变动 → 更新内存 + atomic write 磁盘（temp file + rename）

### Job Schema

```python
{
  "schema_version": 1,
  "job_id": "<uuid4.hex>",
  "label": "素材库拆题材 → xianxia-dark-1",
  "kind": "from-novel" | "from-description" | "blank" | "extract-to-project",
  "target": {"type": "preset" | "project", "id": "xianxia-dark-1"},
  "state": "running" | "aborting" | "done" | "failed" | "aborted" | "interrupted",
  "phase": "extract" | "merge" | "draft" | "validate" | null,
  "phase_index": 1,
  "phase_total": 4,
  "sub_steps": {
    "batch_cur": 3, "batch_total": 12,
    "arc_cur": null, "arc_total": null,
    "draft_pass": null, "validate_round": null
  },
  "progress_text": "batch 3/12",
  "error": null,
  "log_path": ".jobs/logs/<job_id>.log",
  "created_at": 1234.0,
  "started_at": 1234.0,
  "updated_at": 1234.5,
  "finished_at": null,
  "sources": ["novels/a.txt", ...],
  "params": {"with_trial": false, "display_name": "..."}
}
```

**状态机**：

```
                    ┌─────────> done
queued → running ───┼─────────> failed
          ↑         └─> aborting → aborted
          └─ process-crash → interrupted
```

- `queued` 仅保留字段但不启用（YAGNI，现在直接 running）
- `aborting` 表示 cancel token 已触发但 worker 尚未退出
- `interrupted` 表示启动时发现 `active/` 里 state=running 但没对应线程（进程死了）

### Cancel 机制：CancelToken 协议

```python
# src/genre_extractor/cancel.py
class CancelToken(Protocol):
    def check(self) -> None: ...         # 已 cancel 则抛 GenrePipelineAborted
    def is_cancelled(self) -> bool: ...

class ThreadEventToken(CancelToken):
    def __init__(self): self._e = threading.Event()
    def cancel(self): self._e.set()
    def check(self):
        if self._e.is_set(): raise GenrePipelineAborted()
    def is_cancelled(self): return self._e.is_set()

class NullCancelToken(CancelToken):      # CLI / 测试用
    def check(self): pass
    def is_cancelled(self): return False
```

**Plumbing**：
- `to_preset.extract_to_preset(..., cancel: CancelToken = NullCancelToken())`
- `to_project.extract_to_project(..., cancel=...)`
- `core.run_extract / run_merge / run_draft(..., cancel=...)`
- 每个 `_safe_phase` 前 `cancel.check()`
- `_run_extract` 的 batch for-loop 里 per-batch `cancel.check()`
- auditor fan-out 内不传 token（phase 粒度够用）

module-global `CANCEL_EVENT` 彻底移除。

### 并发互斥：per-target 排他锁

```python
_TARGET_LOCKS: dict[tuple[str, str], threading.Lock] = {}  # (type, id) -> Lock
_TARGET_LOCKS_META = threading.Lock()
```

- 同一 target（preset:x 或 project:x）同时只允许 1 个 job
- 不同 target 完全并发
- 提交时 `lock.acquire(blocking=False)` 失败 → 返回 409 Conflict

### API 设计（全新 `/api/jobs`）

```
POST   /api/jobs                    # 创建 job，body: {kind, target, params, sources}，返回 {job_id}
GET    /api/jobs                    # 列表，支持 ?state=running&kind=from-novel
GET    /api/jobs/<job_id>           # 详情（不含 log）
POST   /api/jobs/<job_id>/abort     # 真 abort（cancel token + state → aborting）
DELETE /api/jobs/<job_id>           # 仅非 running 可删
GET    /api/jobs/<job_id>/log?offset=N  # tail log 文本，返回 {content, next_offset}
```

**旧 endpoint 全删**（用户确认无外部脚本依赖）：
- `POST /api/presets/new-from-novel`
- `POST /api/presets/new-from-description`
- `POST /api/presets/new-blank`
- `GET  /api/presets/<pid>/status`
- `POST /api/projects/<pid>/extract-genre`
- `GET  /api/projects/<pid>/extract-genre/progress`
- `POST /api/projects/<pid>/extract-genre/abort`
- `POST /api/projects/new` 的 `from_extract.sources` 异步分支改为：同步同步创建项目框架 + 返回 `job_id` 让前端跳 `/jobs/<id>`

### 页面路由

```
GET /jobs                # 列表页（filter: all/running/failed/done/aborted/interrupted）
GET /jobs/<job_id>       # 详情页（节点图 + 日志）
GET /presets/new         # 保留；表单提交后跳 /jobs/<new_job_id>
```

**首页集成**：
- 顶栏多一个 pill：`⚙ N 个题材任务运行中` → 点击跳 `/jobs?state=running`
- 不做 mini-widget

### 前端渲染（详情页）

**节点图**（4 个大圆 + 连线）：

```
[extract] ──→ [merge] ──→ [draft] ──→ [validate]
  ✓ 完成       ● 进行中    ○ 未开始   ○ 未开始
  batch 12/12  arc 2/3
```

- 当前节点高亮脉冲
- 节点下方子步骤小字：`batch 3/12` / `arc 2/3` / `pass 1/3` / `round 1/2`
- 完成节点打勾、失败节点标红

**日志面板**：`<pre>` 定时 `GET /api/jobs/<id>/log?offset=<seen_bytes>` → append。

**轮询策略**：job running 时 1500ms，结束后停止。

**JS 风格**：ES modules（`web/static/js/features/jobDetail.js` / `jobsList.js`）。顺手把 `web/static/presets.js` 的表单迁到 ES modules。

### 子步骤数据怎么来

| 子步骤 | 来源 | 改动 |
|---|---|---|
| `batch X/N` | `_run_extract` 的 for-loop | 每次 iteration 调 `on_progress(batch_cur=i, batch_total=n)` |
| `arc X/N` | `core._run_merge_multitier` 的 arc loop | 同上 |
| `pass 1/3` | draft 的 Chain-of-Density 循环 | 同上 |
| `round 1/2` | validate retry loop | 同上 |

现有 `on_phase(phase, progress_text)` 回调升级为 `on_progress(phase, sub_steps_delta, progress_text)`，phase 转换也通过它触发（phase 变时 sub_steps 自动重置）。

### 启动恢复

```python
def _recover_jobs_on_boot():
    for p in (JOBS_DIR / "active").glob("*.json"):
        job = _read_job_file(p)
        if job["state"] in ("running", "aborting"):
            job["state"] = "interrupted"
            job["error"] = "进程重启导致任务中断"
            job["finished_at"] = time.time()
            _persist(job)
            _move_to_archive(job["job_id"])
        else:
            _JOBS[job["job_id"]] = job
```

`web/app.py` 的 factory 里调用一次。

### 日志 rotate

`src/genre_extractor/` 内每次需要写日志 → 统一走 `_job_logger(job_id)`（logging.handlers.RotatingFileHandler，`maxBytes=10*1024*1024, backupCount=3`）。`on_progress` 文本也 append 进 log。

## Non-goals

- 不引入数据库
- 不引入 Celery/RQ/Redis
- 不做 SSE/WebSocket（轮询够用，且和 threading + gunicorn 兼容性最好）
- 不做多 worker 支持（README 明确约束）
- 不做 job 重试 UI（interrupted 状态的 job 用户自己决定手动重启，当前版本只显示状态）
- 不改章节流水线（`src/pipeline.py`）的 cancel 机制（另起 plan）

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 多线程下 `_JOBS` dict race | 所有读写加 `_JOBS_LOCK`（RLock） |
| 磁盘 JSON 损坏 | atomic write（temp + rename）；读失败时跳过并日志 |
| 日志文件膨胀 | RotatingFileHandler 10MB × 3 份 |
| 旧 endpoint 删除后现有前端失效 | 同一次 PR 同步改前端；无外部脚本依赖 |
| `_run_lock` 与 extract job 的交互（extract 激活作品时需重 bootstrap） | `extract-to-project` kind 的 job 提交前显式 acquire `_run_lock`；章节流水线运行期间不允许提交此类 job |

## 验证

- 全部现有测试绿
- 新增测试覆盖：job CRUD、持久化、恢复、cancel token、per-target 锁、旧 endpoint 已删
- 手动验证：
  - 从素材库拆题材 → 跳 `/jobs/<id>` → 关闭标签页 → 重开 → 进度还在
  - 同时跑 2 个题材 job + 1 个章节流水线 → 三者互不阻塞
  - 运行中进程 kill → 重启 → job 状态变 interrupted
  - abort 按钮 → 5 秒内 worker 真正退出
