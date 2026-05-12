# 题材流水线（Genre Pipeline）— 架构设计

> **📦 历史档案** · 本设计已由 `docs/superpowers/specs/book-centric-workflow-design.md` 取代。保留仅为历史脉络。


> **项目代号**：`genre-pipeline`
> **定位**：Novelforge 的第二条流水线——**建 / 补 / 审 / 拆**题材包
> **核心决策**：薄壳流水线，90% 复用小说流水线的工程机制，10% 是题材特有 Agent 和 schema
> **前置文档**：根目录 [`AGENTS.md`](../../../AGENTS.md) + [`genres/README.md`](../../../genres/README.md) + [`projects/README.md`](../../../projects/README.md)（小说流水线目录页与题材/作品两层结构）

---

## 0. 一句话说明

现有 Novelforge **只有写作品的流水线**。建题材（`genres/<id>/` 下的 4-5 份文件）目前靠人工手写 + `setting_lint` 结构校验。这意味着：

- 题材包质量没有 Agent 三角分工验收（违反 Anthropic 自评偏乐观教训）
- 题材构建多步骤没有状态外化（违反 Cognition Context Reset 教训）
- 从一本已有优秀小说逆向拆解题材的核心使用场景完全缺失
- `calibrate_evaluator` 的 scratch-bootstrap 骨架、`multi_level_summarizer` 的分级思想等现成资产未被题材层利用

本 spec 设计一条**与小说流水线对等的题材流水线**：支持**从零手建 / 补齐 / 审查 / 从已有小说拆解**四种入口，默认只跑快速的结构 + LLM 语义校验，`--with-trial` 显式开启"跑试验书 3 章"作为真实验收。

---

## 1. 用户决策记录（brainstorming 结果）

| 编号 | 问题 | 选定 | 备注 |
|---|---|---|---|
| Q1 | 流程主角是 Agent 自动还是人类主导 | **入口 C 优先**（从已有小说拆解） | 工程上最硬核，A/B 是其简化子集 |
| Q2 | `--with-trial` 试验书 3 章要不要默认开 | **B（默认关，显式开）** | 默认只跑快校验；冷启动成本低 |
| Q3 | 拆解长篇小说的窗口粒度 | **B'（25 章/批，三档自适应）** | ≤50 章：10/批；50-600：25/批；>600：40/批 |
| Q4 | Extractor 笔记的 schema 严格度 | **C（严格 schema，对齐最终产物）** | 字段对齐题材包 4 份文件；带 `evidence_chapters` / `confidence` |

---

## 2. 复用盘点（现有小说流水线里能剥离的机制）

### 2.1 架构层（可直接复用）

| 现有机制 | 题材流水线里的角色 | 剥离成本 |
|---|---|---|
| `Blackboard`（state/ 统一读写）| 题材构建工作目录 `genres/<id>/.build/` 的统一读写 | 改 `root` 参数即可 |
| `BaseAgent`（prompt_log + retry + json mode）| 题材四个 Agent 的基类 | 零成本，直接继承 |
| `pipeline.py` 的 `_stage()` + `_append_debt()` + `CANCEL_EVENT` + Intent Router | 题材流水线 `run_genre_build()` 照抄骨架 | 复制一份、换调度内容 |
| Fan-out 并行 Auditor 模式 | 题材包审查的多维度并行检查 | 同上 |
| `prompts_log.jsonl` + `inputs_read` 审计 | 题材构建全过程可审计 | 零成本 |
| `llm.chat()` 的 `_log_call` 机制 | 同上 | 零成本 |
| `multi_level_summarizer` 的 batch → arc → book 三级 | 拆解长篇的 batch (25 章) → arc (100 章合并) → book (全书 distill) | 复用调度代码，只换 prompt |

### 2.2 工具层（可直接复用）

| 现有工具 | 题材流水线里的角色 |
|---|---|
| `calibrate_evaluator.py` 的 scratch bootstrap + 注入章节 + 跑 Agent + 对比期望 | `--with-trial` 的 80% 骨架 |
| `setting_lint.py` 的结构校验 | 题材流水线 Validator 的 Stage 1 |
| `websearch.py`（Perplexity 缓存）| 拆解 / 合成阶段查证事实 |

### 2.3 不下沉、保持原位的

- `Planner / Generator / Evaluator / Fixer / Summarizer / StatusCardUpdater / HookKeeper / ResourceLedger`：**它们仍绑定小说流水线**，不动
- `src/pipeline.py`：继续是小说流水线入口
- `src/bootstrap.py`：继续做"激活 project、拷文件到 state/"

---

## 3. 顶层架构

```
                           题材流水线（本 spec 新增）
                           ────────────────────────
                                                                  
 ┌──── 入口 ────────────────────────────────────────────────┐
 │ --new-genre <id>          从零脚手架（问卷→Drafter）      │
 │ --fill-genre <id>         补齐缺失文件（读现有 + 补全）   │
 │ --audit-genre <id>        审查已有题材一致性              │
 │ --extract-from-novel <id> 从已有小说拆解（核心入口 C）    │
 │   --sources a.txt,b.txt   输入 1-N 本同题材小说正文       │
 │   --with-trial            开启试验书 3 章真实验收         │
 └────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
       ┌───── genres/<id>/.build/ （题材层黑板）──────┐
       │ build_status.yaml       ←─ 当前构建阶段     │
       │ extraction_notes/       ←─ 每批笔记独立落盘 │
       │   batch-NNN.yaml        ←─ 严格 schema(C)   │
       │ extraction_tally.md     ←─ 量化统计账本     │
       │ pending_questions.md    ←─ 开放问题池       │
       │ genre_blueprint.yaml    ←─ 合成中间产物     │
       │ genre_issues.jsonl      ←─ 审查问题流水     │
       │ genre_debt.jsonl        ←─ 带伤上线记录     │
       │ prompts_log.jsonl       ←─ LLM 审计日志     │
       └──────────────────▲────────────────────────────┘
                          │
       ┌──────────────────┼──────────────────┐
       │                  │                  │
       ▼                  ▼                  ▼
  GenreExtractor    GenreDrafter      GenreValidator
  (滑动窗口拆解)    (合成 4 份文件)   (结构+语义+可选试验书)
                          │
                          ▼
                    GenreFixer (≤2 retry)
                          │
                  ┌───────┴───────┐
                  ▼               ▼
                通过         2 次仍不过
                  │               │
                  ▼               ▼
      genres/<id>/*.md        genre_debt.jsonl
      （正式输出落盘）         （Lesson 4 带伤上线）
```

**关键设计原则：**

1. **`.build/` 是构建期临时目录，输出落盘后可安全删除**（默认保留，便于复跑）
2. **`.build/` 进 `.gitignore`，只有正式的 4 份题材文件才 commit**
3. **所有 Agent 都读 `build_status.yaml` 先确认"当前在哪一步"**（Context Reset 的具身化）
4. **每批 Extractor 跑完就更新 `build_status.yaml`**，任何一批失败都能从 `build_status.yaml` 续跑

---

## 4. 四个题材 Agent 的职责

### 4.1 `GenreExtractor`（入口 C 专用）

**场景：**拆解用户提供的 N 本同题材小说。

**每次调用读：**
- 当前批次的 M 章原文（M 由自适应档位决定）
- 上一版 `extraction_notes/latest_merged.yaml`（增量合并基准）
- `build_status.yaml`（定位当前批次 id）
- 已有 3 个题材包作为 few-shot（仅读 `genre.yaml` 头部元信息，不读正文，省 token）

**每次调用写：**
- `extraction_notes/batch-NNN.yaml`（本批笔记，独立落盘，Lesson 3 隔离）

**温度：**0.3（需要结构识别，不要太发散）

**response_format：**json

**严格 schema（Q4 决策 C）：**见第 5 节。

---

### 4.2 `GenreDrafter`

**场景：**三种入口都会用。

**分两步跑，两次 LLM 调用：**

1. **Step A — 产 blueprint**：读 merged notes → 写 `genre_blueprint.yaml`（合成中间产物，结构化 + 带 evidence）
2. **Step B — 拆文件**：读 blueprint → 渲染出 5 份正式文件（确定性模板填充为主，少量 LLM 润色 era.md 散文部分）

这样做的好处：blueprint 可复用、可人工审查、可重跑 Step B 而不重跑昂贵的 Step A。

**Step A 读：**
- `extraction_notes/latest_merged.yaml`（入口 C）或用户问卷答案（入口 A）
- 已有 3 个题材包的**格式样板**（仅作 few-shot）
- `rules/` 下的通用规则文件（避免重复通用内容）

**Step A 写：**
- `genre_blueprint.yaml`

**Step B 读：**
- `genre_blueprint.yaml`
- 已有题材包的文件级模板

**Step B 写：**
- `genres/<id>/genre.yaml`
- `genres/<id>/era.md`
- `genres/<id>/writing-style-extra.md`
- `genres/<id>/iron-laws-extra.md`
- `genres/<id>/resource_schema.yaml`（可选，仅当 extraction 阶段识别出可追踪资源时）

**温度：**Step A 0.4 / Step B 0.2

**response_format：**Step A json / Step B 模板填充 + text（仅 era.md 的散文段落调 LLM）

---

### 4.3 `GenreValidator`

**场景：**三种入口末端都会跑；`--audit-genre` 单独运行。

**分三个 Stage：**

| Stage | 名称 | 耗时 | 默认开 | 做什么 |
|---|---|---|---|---|
| 1 | `StructureCheck` | 秒级 | ✅ | 直接调用 `setting_lint.lint_pack()`，复用现有实现 |
| 2 | `SemanticCheck`（LLM）| 1-2 分钟 | ✅ | 扫 iron-laws 之间、iron-laws 与 era、iron-laws 与 writing-style 的矛盾 + AI 味 + 模糊词 |
| 3 | `TrialCheck`（试验书 3 章）| 15-30 分钟 | ❌ `--with-trial` 开 | 在 tempfile scratch 里起一本 trial 书，跑 `--range 1-3`，Evaluator 连审，对比现有 3 个题材的 baseline 分数 |

**Stage 3 复用 `calibrate_evaluator.py` 的 scratch-bootstrap 骨架。**

**写：**
- `genre_issues.jsonl`（issue 级记录）
- 如果 Stage 3 跑，追加 trial 章节路径到报告

---

### 4.4 `GenreFixer`

**场景：**`GenreValidator` 报问题后，Fixer 读 issues 修对应文件。

**Retry 机制：**和小说流水线完全一致——最多 2 次，2 次仍有 ERROR 级问题则 ship_with_debt 到 `genre_debt.jsonl`。

**温度：**0.3

---

## 5. 严格 Schema（Q4 决策 C 的具身化）

### 5.1 `extraction_notes/batch-NNN.yaml`

```yaml
batch_id: 1
chapters_covered: [1, 25]
novel_source: "path/to/novel-a.txt"
extracted_at: "2026-05-11T14:30:00"

# === 对应最终 era.md 的素材 ===
era_observations:
  - fact: "1983-09 港币信心危机，政府 10 月 17 日推出联系汇率"
    evidence_chapters: [3, 4]
    confidence: high     # high / medium / low
    cites_reality: true  # 是否源自真实历史，需要 websearch 二次核对

# === 对应最终 iron-laws-extra.md 的素材 ===
iron_law_candidates:
  - id: "cand_01"
    statement: "主角对英籍督察默认态度是利用+压榨，不跪舔不仇恨"
    evidence_chapters: [5, 12, 18]
    bad_example: "<原文里作者刻意避免的反面例子>"  # 可空
    good_example: "<原文里的正面例子原文片段 ≤200 字>"
    recurrence_count: 3  # 本批出现几次，跨批累加

# === 对应最终 writing-style-extra.md 的素材 ===
style_markers:
  - marker: "粤语词融入度"
    measurement: "每千字约 3-5 个俚语词"
    forbidden_pattern: "整段纯粤语对白"
    example: "<原文片段>"

# === 对应最终 resource_schema.yaml 的素材（可选）===
resource_candidates:
  - id: "intel_value"
    display_name: "情报值"
    tracked_in_chapters: [2, 8, 15]
    increment_events:
      - "扳倒贪官 +100"
      - "搞一条情报线 +20"

# === 开放问题（给 Drafter 或人类裁决）===
open_questions:
  - question: "主角对内地人的态度，前 10 章回避、20 章后拉拢，是人设演进还是题材规律？"
    needs: "后续批次观察"
```

### 5.2 `build_status.yaml`

```yaml
genre_id: "gangster-tw-1990"
entry: "extract-from-novel"  # new / fill / audit / extract
created_at: "2026-05-11T14:00:00"
last_update: "2026-05-11T15:30:00"

novel_sources:
  - path: "novels/a.txt"
    total_chapters: 400
    batch_size: 25
  - path: "novels/b.txt"
    total_chapters: 180
    batch_size: 25

phases:
  extract:
    status: "in_progress"   # pending / in_progress / done / failed
    batches_total: 23        # 400/25 + 180/25 = 16+8 = 24; 四舍五入
    batches_done: 12
    last_batch_id: 12
  merge:
    status: "pending"
  draft:
    status: "pending"
  validate:
    status: "pending"

in_flight:
  agent: "genre_extractor"
  batch_id: 13
  started_at: "2026-05-11T15:29:00"
```

### 5.3 `genre_blueprint.yaml`（合成中间产物）

这是合并完所有 batch notes 后的**全局拆解报告**，`GenreDrafter` 基于它产出 4 份正式文件。结构就是 5.1 去掉 `batch_id` / `chapters_covered` 维度，把所有 batch 的同字段合并 + 去重 + 统计。

### 5.4 `extraction_tally.md`

人类可读的量化账本：

```markdown
# Extraction Tally — gangster-tw-1990

## 覆盖范围
- 已读 2 本小说，共 580 章，分 24 批
- 当前进度：12/24 (50%)

## iron_law_candidates 出现频次 Top 10
| # | cand_id | statement（节选）| total_recurrence |
|---|---|---|---|
| 1 | cand_01 | 主角对英籍督察利用+压榨… | 12 |
| 2 | cand_03 | 社团辈分越级会被教训… | 8 |
...

## era_observations confidence 分布
- high: 23 条
- medium: 15 条
- low: 6 条 (需要 Drafter 降权或丢弃)

## 禁用的模糊词扫描（防 LLM 废话）
- 已出现 0 次："似乎" / "大致" / "整体而言" / "某种程度上"
```

---

## 6. 自适应窗口档位（Q3 决策 B' 的实现）

```python
def adaptive_batch_size(total_chapters: int) -> int:
    if total_chapters <= 50:
        return 10
    elif total_chapters <= 600:
        return 25
    else:
        return 40
```

档位由每本源小说的章节数独立决定。一个 400 章 + 一个 80 章一起跑，前者用 25/批，后者用 25/批（都落在同档）。

---

## 7. 目录布局

```
src/
├── core/                        # ← 新增，通用抽象下沉
│   ├── __init__.py
│   ├── blackboard.py            # 从 src/blackboard.py 移过来（薄包装，保持向后兼容）
│   ├── base_agent.py            # 从 src/agents/_base.py 移过来（同上）
│   └── debt_ledger.py           # 从 pipeline.py 抽出的 _append_debt 通用化
├── blackboard.py                # 保留 re-export shim，`from src.core.blackboard import ...`
├── agents/_base.py              # 保留 re-export shim
├── pipeline.py                  # 小说流水线，不动
├── bootstrap.py                 # 不动
├── genre_pipeline/              # ← 新增
│   ├── __init__.py
│   ├── __main__.py              # CLI entry
│   ├── pipeline.py              # run_genre_build() 主调度
│   ├── schemas.py               # batch-NNN / build_status / blueprint 的 dataclass + 校验
│   ├── adaptive.py              # adaptive_batch_size + 章节切分
│   ├── trial.py                 # Stage 3 scratch bootstrap（复用 calibrate 骨架）
│   └── agents/
│       ├── __init__.py
│       ├── extractor.py
│       ├── drafter.py
│       ├── validator.py
│       └── fixer.py

tests/
├── test_genre_schemas.py              # schema 校验
├── test_genre_adaptive.py             # 档位 + 切分
├── test_genre_pipeline_cli.py         # CLI 冒烟
├── test_genre_pipeline_stages.py      # 各 Agent 可实例化、prompt 可生成
├── test_genre_build_status.py         # 状态卡中断续跑
└── test_core_shims.py                 # 向后兼容（from src.blackboard import X 仍然可用）

genres/<id>/
├── genre.yaml                   # 最终产物（git 跟踪）
├── era.md                       # 同上
├── writing-style-extra.md       # 同上
├── iron-laws-extra.md           # 同上
├── resource_schema.yaml         # 同上（可选）
└── .build/                      # .gitignore；构建期临时，可删
    ├── build_status.yaml
    ├── extraction_notes/
    │   ├── batch-001.yaml
    │   ├── batch-002.yaml
    │   └── latest_merged.yaml
    ├── extraction_tally.md
    ├── pending_questions.md
    ├── genre_blueprint.yaml
    ├── genre_issues.jsonl
    ├── genre_debt.jsonl
    └── prompts_log.jsonl
```

---

## 8. 向后兼容策略

**硬约束：**不破坏任何现有代码。

1. **`src/blackboard.py` / `src/agents/_base.py` 变成 re-export shim**
   ```python
   # src/blackboard.py
   from .core.blackboard import *  # noqa: F401,F403
   from .core.blackboard import Blackboard, bb  # explicit
   ```
   现有的 `from src.blackboard import Blackboard` 语句全部继续工作。

2. **`src/pipeline.py` 不动**。小说流水线的 `_append_debt` 先保留原位；如果后续 `GenreFixer` 想共用，再把它也 re-export 到 `src/core/debt_ledger.py`。YAGNI 原则：第一版先只做真正需要下沉的。

3. **测试基线：**现有 `tests/` 全部必须继续通过。新增测试不能偶发地污染现有 fixture。

---

## 9. CLI 详细设计

```bash
# 入口 A：从零手建（最小实现，本 spec 第一版可以不做交互问卷，只生成 stub）
python3 -m src.genre_extractor --new-genre <genre-id> \
    --name "港综-台湾-1990" \
    --era "1990-2000 台北高雄"

# 入口 B：补齐
python3 -m src.genre_extractor --fill-genre <genre-id>
# 读现有 genres/<id>/，识别缺失文件，调 Drafter 补齐

# 入口 C：拆解（核心）
python3 -m src.genre_extractor --extract-from-novel <genre-id> \
    --sources novels/a.txt,novels/b.txt \
    [--with-trial]
# 流程：Extract (滑窗) → Merge → Draft → Validate (+Trial 可选)

# 入口 D：纯审查（不产出新文件）
python3 -m src.genre_extractor --audit-genre <genre-id>

# Intent Router（中断续跑，对应小说流水线的 --plan-only 等）
python3 -m src.genre_extractor --extract-only <genre-id> --batch 7
python3 -m src.genre_extractor --merge-only <genre-id>
python3 -m src.genre_extractor --draft-only <genre-id>
python3 -m src.genre_extractor --validate-only <genre-id> [--with-trial]
```

---

## 10. 实现范围与进度

> **✅ 2026-05-12 更新**：本 spec 的第一版 + 第二版功能**已全部 ship**。以下清单按时间轴整理。

### 10.1 第一版（已交付）

- ✅ `src/core/` 下沉（`Blackboard` + `BaseAgent`，shim 保留向后兼容）
- ✅ `src/genre_extractor/` 完整骨架 + 4 个 Agent
- ✅ CLI 全部 subcommand 接入 + Intent Router（`--extract-only` / `--merge-only` / `--draft-only` / `--validate-only`）
- ✅ `--new-genre` stub 脚手架
- ✅ `--extract-from-novel` 全流程打通
- ✅ `--with-trial` 标志接入
- ✅ `pytest` 测试套件（schema 校验 / 档位切分 / CLI 冒烟 / build_status 续跑 / core shim 向后兼容）
- ✅ `AGENTS.md` 增加题材流水线索引段

### 10.2 第二版（已交付，超出原 YAGNI 范围）

原"不交付"清单已全部补齐并超越：

- ✅ **生产级 prompt**：Extractor 两步法（temp 0.3 自由笔记 → temp 0.0 verbatim 提取）+ Drafter CoD 3-pass 迭代 + Validator 对抗性 reject-by-default + deny-phrases 中英文清单（commits `32f6b21` / `fc34057` / `3d9cefd` / `203939a`）
- ✅ **`--new-genre --interactive` 问卷式脚手架**：8 字段 + 3 多行列表问卷，产出富初稿（commit `6fc9aea`）
- ✅ **Web UI 完整集成**：`/genres` 题材库 / `/genres/new` 新建 / `/genres/<id>` 详情 / `/genres/<id>/extract` 拆解 / `/genres/<id>/extract/progress` 进度页 + 8 个 API 路由（commit `cde3f3e`）
- ✅ **trial 真跑 3 章试验书**：复用 `bootstrap_project` 的 scratch 隔离模式（commit `7ae51d6`）
- ✅ **Validator → Fixer retry loop**：≤2 次 retry + ship_with_debt，对齐小说流水线（commit `a80a754`）
- ✅ **3-tier merge**（batch → arc → book）：`GenreArcMerger` + `GenreBookDistiller`（commits `cbb997c` / `47b4224` / `8004eaf`）
- ✅ **Validator 扇出并行 3 Auditor**：`GenreFactChecker` / `GenreConsistencyGuard` / `GenreStyleGuard`（commit `678bc66`）
- ✅ **ChapterStream 流式 + 编码兜底**：>5MB 走流式索引；自动识别 UTF-8 / GB18030 / Big5 / Shift-JIS 等并转 UTF-8（commits `a6f1441` / `4a053fb` / `0b59b20`）
- ✅ **多格式章节识别**：6 种（zh-standard / en-standard / zh-ordinal / roman / numeric / separator）+ 自适应档位（commits `37e2c67` / `c9f3dbd`）
- ✅ **`extraction_tally.md` 健康报告**（commits `a52250d` / `a4217b4`）
- ✅ **Web 素材库 `/novels`**：批量上传 + 编码检测 + 路径安全双层防御（commits `42b3a1f` / `29d5c7b` / `76cc639`）

### 10.3 未来迭代（待做）

- ⏳ 对现有 3 个题材包跑 `--audit-genre` 批量 CI 集成
- ⏳ 题材文件 Web 编辑器（33 个测试已 ready，实现 pending —— 见 `tests/test_web_genre_files_api.py`）
- ⏳ Web 端布局重构（详见根目录审计报告）

---

## 11. 风险与回退

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| `src/core/` 下沉破坏现有 import | 中 | 高（测试炸） | re-export shim + 先跑现有测试基线、改完再跑 |
| `calibrate_evaluator` 骨架复用时环境变量污染 | 低 | 中 | 用 monkeypatch 隔离，比照 `conftest.py` 的 `isolated_project` fixture |
| Extractor 在真实 LLM 下不遵守 schema | 高 | 高 | schema 带 pydantic 或手写 validator + retry；第一版占位 prompt 不触发 |
| 400 章小说跑 Extract 超时 | 中 | 中 | 每批独立落盘 + CANCEL_EVENT + Intent Router 续跑，失败可断点 |
| 题材层的 `prompts_log.jsonl` 与作品层撞库 | 低 | 低 | 题材层写 `genres/<id>/.build/prompts_log.jsonl`，独立目录 |

**回退方案：**第一版完全不改 `src/pipeline.py` / `src/bootstrap.py` / 现有 Agent 实现。如果 `src/core/` 下沉出问题，回退步骤：删除 `src/genre_extractor/` + `src/core/`，**并把 `src/blackboard.py` 和 `src/agents/_base.py` 的 re-export shim 恢复为下沉前的完整实现**（git 历史可查）即可。由于 shim 方案的 API 面和原实现完全一致，大概率无需回退。

---

## 12. 成功判据

第一版实现完成后应满足：

1. `python3 -m pytest tests/` 全绿（包括所有新增测试）
2. 现有 `python3 -m src.bootstrap --project gangster-hk-1983-linjiayao` 仍然正常
3. `python3 -m src.genre_extractor --new-genre demo-genre --name "demo"` 能生成 4 份 stub 文件
4. `python3 -m src.genre_extractor --extract-from-novel demo-genre --sources <mock-novel>` 能走完 extract → merge → draft → validate，最后在 `genres/demo-genre/.build/build_status.yaml` 里看到全部 phase = done
5. `python3 -m src.tools.setting_lint --genre demo-genre` 对 extract 产物结果不报 ERROR（WARNING 可接受）
6. `AGENTS.md` 增加了题材流水线索引段

---

## 13. 与三份原始参考文档的映射

| 参考文档 | 在本设计里的落点 |
|---|---|
| Agent 搭建难题.md · Lesson 1 重启胜过修补 | Intent Router + build_status 续跑 + Fix retry ≤2 次 |
| Agent 搭建难题.md · Lesson 2 生产/验收分离 | Extractor/Drafter 和 Validator 是不同 Agent；`--with-trial` 让验收摸到真实世界 |
| Agent 搭建难题.md · Lesson 3 Context Reset | `.build/build_status.yaml` + 每批独立 `batch-NNN.yaml` + 分级合并 |
| Agent 搭建难题.md · Lesson 4 技术债日还 | `genre_debt.jsonl` + ship_with_debt |
| Agent 搭建难题.md · Lesson 5 AGENTS.md 目录页 | 4 份题材文件职责分离、不塞百科 |
| ai 小说流水线教程贴.txt · 18 雷点 | Validator Stage 2 的语义检查 rubric 基础 |
| ai 小说流水线教程贴.txt · 代入感六支柱 | Drafter 合成 writing-style-extra.md 的 checklist |
| 可跑的小说写作-skill.txt · 四分类任务判定 | CLI 四种入口（new / fill / audit / extract） |
| 可跑的小说写作-skill.txt · 当前状态卡 | `build_status.yaml` |
| 可跑的小说写作-skill.txt · 表格化账本 | `extraction_tally.md` |
| 可跑的小说写作-skill.txt · 最小上下文原则 | Extractor 每次只读本批 + 上轮 merged + few-shot 头部 |

---
