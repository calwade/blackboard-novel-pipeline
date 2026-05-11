# 🔨 Novelforge

> *把一本小说拆给 10 个 Agent 分工生产的写作流水线。文件即记忆、对抗式审稿、三层账本、题材热插拔。*

**小说锻造厂** — 把"一个 AI 一路写到黑"拆成 10 个独立 Agent 的长链路生产线。Anthropic / Cognition / OpenAI 在长链路 Agent 上踩过的 5 个坑，全部作为架构约束来设计：**状态全部沉到磁盘文件**、**对抗式审稿（默认拒稿）**、**三层账本（状态卡 / 伏笔池 / 资源账本）**、**题材随拔随换**、**规则按需披露（不塞大而全）**。

> **当前阶段**：MVP 之后必做项 + 应做项全部扫清（见 [`docs/gap-analysis-post-mvp.md`](docs/gap-analysis-post-mvp.md)，C-22..C-32 落地 + 三层账本层完工）
> **下一阶段**：10 章以上长跑验证（✅ 港综已完成）+ Evaluator 校准集（✅ 已到 100% 一致）+ 持续集成
> **仓库主页**：[github.com/CalWade/novelforge](https://github.com/CalWade/novelforge)
> **在线演示**：[calwade.github.io/novelforge/](https://calwade.github.io/novelforge/)（静态只读）

---

## 一分钟讲清楚是什么

一本小说**不是**一个 AI 从头写到尾的 —— 它由 **5 个创作 Agent + 3 个记账 Agent + 2 个后台审计 Agent** 分工合作：

```
Planner 拆节拍 → Generator 写正文 → Evaluator 挑刺 → Fixer 改稿 → Summarizer 摘要
                                                                        │
                                       ┌─────── 记账层（三份账本）─────┤
                                       │                                │
                                 StatusCardUpdater               HookKeeper
                                 （当前状态卡）                  （待回收伏笔池）
                                       │                                │
                                 ResourceLedger
                                 （资源账本 · 可选：题材需声明 resource_schema 才启用）
                                       │
                                       ├──────── 扇出并行审计 ─────────┤
                                       │                                │
                                 AISlopGuard                    CharacterGuard
                                 （AI 味审计）                  （人设漂移审计）
```

每个 Agent 都用**独立的 LLM 调用、独立的 system prompt、独立的上下文窗口**（每次调用都是全新会话，不累积）。**所有状态都存在文件里**（`state/` 目录），**不在内存里**。

核心性质：**一个 Python 进程死了，换一个新进程，只要读 `state/current_status_card.md` 就能立刻知道**—— 刚才写到哪一章、主角当前什么状态、哪些伏笔还没回收。这是 Cognition 团队提出的「把上下文整个丢掉重读文件」（他们叫 Context Reset，中文可理解为"上下文重置"）的工程化落地。

**题材 = 数据**：流水线本身（`src/`）对题材一无所知。

新架构（2026-05-11 重构）把"题材"和"作品"分两层：

- **`genres/<id>/`** 是"什么是港综 / 仙侠 / 言情"的描述——多本书共享
- **`projects/<id>/`** 是"这本书的主角叫林家耀、大纲是这样安排"的数据——每本独立

切换作品只需要一行 `bootstrap` 命令，不用改任何代码。内置三组（题材 × 作品）：
**港综 · 林家耀**、**仙侠 · 裴长宁**、**都市言情 · 沈若微**。

---

## 架构：三层嵌套

```
外层（宏观）： Pipeline 主循环 — 章节线性推进
每章内部：    Blackboard 黑板 — state/ 文件 = 所有 Agent 的唯一共享记忆
每章产后：    扇出并行 — 2 个 Auditor 后台同时扫
Evaluator：   半对抗辩论 — 对抗人设 + 结构化 JSON 评分表 + 骨架检测器（防模型复制 prompt 示例）
```

| Agent | 读 | 写 | 采样温度 |
|---|---|---|---|
| **Planner**（责编） | 大纲 + 最近 2 份摘要 + 题材元信息 + **当前状态卡** + **伏笔池** | `chNNN.plan.json`（含章节类型 / 场景推进项 / 写作自检表） | 0.4 |
| **Generator**（执笔） | 节拍表 + 人物档案 + 写作风格（通用 + 题材特有）+ 时代事实包 + **题材禁用风格黑名单** | `chNNN.md`（~3000 字） | 0.85 |
| **Evaluator**（审稿） | 章节正文 + 18 条雷点 + 28 条铁律（通用 + 题材特有）+ **信息源优先级协议** + 人物档案 + 时间线 | `verdict.json` + 问题日志 | 0.0 |
| **Fixer**（改稿） | 章节正文 + 评审判决中的 top 3 待修 + 写作风格 + 题材禁用风格黑名单 | 覆写 `chNNN.md` | 0.5 |
| **Summarizer**（摘要员） | **只读**章节正文（不读 plan/verdict，防"立场后门"泄漏） | `summaries/chNNN.md` | 0.2 |
| **StatusCardUpdater**（状态卡员） | 本章正文 + 上一版状态卡 + 人物档案 | `current_status_card.md`（整份覆盖） | 0.2 |
| **HookKeeper**（伏笔登记员） | 本章正文 + 上一版伏笔池 + 当前状态卡 | `pending_hooks.md`（整份覆盖） | 0.2 |
| **ResourceLedger**（账房 · 可选） | 题材的资源定义 + 本章正文 + 上一版账本 | `resource_ledger.md`（整份覆盖） | 0.2 |
| **AISlopGuard**（AI 味审计） | 章节正文 | `fixes/chNNN.slop-patch.md`（补丁文件） | 0.2 |
| **CharacterGuard**（人设审计） | 章节正文 + 人物档案 + 历史摘要 | `fixes/chNNN.char-patch.md` | 0.2 |
| **FactChecker**（事实核查 · 按需触发） | 章节正文 + 判决文件 + 时代事实包 | `fixes/chNNN.fact-patch.md` | 0.0 |

> FactChecker 只在 Evaluator 命中 `landmine_13`（世界观模糊/脱离现实）且严重度为 medium 或 high 时才触发。调用 Perplexity Sonar 搜索 ≤3 条可查证断言，产出建议性补丁（不改判决）。未配置 `PERPLEXITY_API_KEY` 时自动跳过、不阻塞其他 Agent。

---

## 对应 5 大 Agent 搭建难题

| 难题 | 出处 | 本项目对策 |
|---|---|---|
| ① 反复失败、没有反馈链路 | Anthropic | 所有 Agent 无状态；失败写入 `issues.jsonl` + `debt.jsonl`；下一轮 Fixer 从文件读重新开一个干净会话 |
| ② 自评过于乐观 | Anthropic | 五个独立 Agent + Evaluator **默认拒稿的"对抗人设"** + **结构化 JSON 评分表**（18 个雷点逐条打分）+ **骨架检测器**（防模型复制示例 prompt 里的 `…` 占位符） |
| ③ 上下文焦虑（越写越慌） | Cognition | 每次调用都是**全新会话**；只读它需要的 1-2 个文件；Summarizer **独立会话**，只读最终章节正文，不读 plan/issues（防"立场后门"泄漏） |
| ④ AI 味代码堆积 | OpenAI Codex | `rules/*.md` + `genres/<id>/iron-laws-extra.md` 就是黄金原则；每章跑完自动触发 2 个后台 Auditor，产出独立补丁文件；Evaluator 两轮重试仍不过 → **带病上线**（写入 `debt.jsonl`，避免死循环） |
| ⑤ 规则文件百科病 | OpenAI | `AGENTS.md` **只 100 行目录页**；详细拆到 `rules/` 通用 + `genres/<id>/` 题材特有；每个 Agent 只加载它需要的那 1-2 份 |

---

## Genre + Project 两层架构（2026-05-11 重构）

历史原因，"题材包"之前是单层 `settings/<name>/`，同时承载**题材定义**和**单一作品数据**——
单本书场景下没问题，但架构逻辑混乱。重构为两层：

### `genres/<id>/` · 题材层（共享）

```
genres/<id>/
├── genre.yaml              # 必需 · 题材元信息 + author_persona_hints + prohibited_styles
├── era.md                  # 必需 · 时代/世界观事实包
├── writing-style-extra.md  # 必需 · 题材特有写作风格
├── iron-laws-extra.md      # 必需 · 题材特有铁律
└── resource_schema.yaml    # 可选 · 可追踪资源定义（仙侠/港综有；都市言情无）
```

### `projects/<id>/` · 作品层（每本独立）

```
projects/<id>/
├── project.yaml            # 必需 · 声明基于哪个 genre + 本书主角/章数等
├── outline.json            # 必需 · 本书大纲 + 每章节拍
├── characters.yaml         # 必需 · 本书人物档案
├── timeline.yaml           # 必需 · 本书时间线
└── state/                  # 运行时产物（.gitignore）
```

### 切题材 / 新建一本书

```bash
# 查看所有可用题材和作品
python -m src.bootstrap --list-genres
python -m src.bootstrap --list

# 激活某本书（把题材层 + 作品层文件合并到 projects/<id>/state/，供 Agent 读取）
python -m src.bootstrap --project gangster-hk-1983-linjiayao

# 新建一本基于现有题材的书（脚手架）
python -m src.bootstrap --new-project my-book --genre gangster-hk-1983
# 然后编辑 projects/my-book/project.yaml / outline.json / characters.yaml ...
python -m src.bootstrap --project my-book
```

### 内置三组

| 题材 | 作品 | 主角 | 状态 |
|---|---|---|---|
| `gangster-hk-1983` | `gangster-hk-1983-linjiayao` | 林家耀 | ✅ 跑过 10 章 |
| `xianxia-ascension` | `xianxia-ascension-peichangning` | 裴长宁 | ✅ 跑过 3 章 |
| `urban-romance-contemporary` | `urban-romance-shenruowei` | 沈若微 | ⚠️ 未跑 LLM |

详见 [`genres/README.md`](genres/README.md) 和 [`projects/README.md`](projects/README.md)。

---

## 如何跑

### 推荐路径：Web 端全流程（2026-05-11 起）

```bash
# 1. 克隆 + 环境
git clone https://github.com/CalWade/novelforge.git
cd novelforge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 启动 Web（即可，不用先 cp .env / 先 bootstrap）
flask --app web.app run --port 5055
# 浏览器打开 http://localhost:5055/
```

首次打开会触发**启动向导**：

1. **填 API Key**：`DEEPSEEK_API_KEY`（必填，写入 `.env`），`PERPLEXITY_API_KEY`（可选，给 FactChecker 用）。
2. **选作品**：从 3 个内置作品里挑一本激活（港综·林家耀 / 仙侠·裴长宁 / 都市言情·沈若微），或点「+ 新建作品」选题材脚手架一本新的。
3. 主界面出来。顶部的 **▶ 开始 / ⏹ 中断** 控制面板支持 9 种运行模式（单章 / 批量 / 出版包装 / 只重排大纲 / 只重写 / 只重评 / 只跑修复 / 只重审计 / 只刷台账），点 ⚙ 可以随时改 API Key。

切换作品、编辑元信息（`project.yaml / outline.json / characters.yaml / timeline.yaml`）、看每次 LLM 调用、查技术债——全部在浏览器里。

### CLI 路径（脚本化 / CI / 老用户）

```bash
cp .env.example .env
# 在 .env 里填入 DEEPSEEK_API_KEY

python -m src.bootstrap --list-genres                         # 看所有可用题材
python -m src.bootstrap --list                                # 看所有可用作品
python -m src.bootstrap --project gangster-hk-1983-linjiayao  # 激活"林家耀的故事"

# 新建一本基于现有题材的书
# python -m src.bootstrap --new-project my-book --genre gangster-hk-1983

# 跑流水线
python -m src.pipeline --chapter 1     # 跑一章（全流水线）
python -m src.pipeline --range 1-3     # 跑一到三章
python -m src.pipeline --audit-only 1  # 只重跑 3 个 Auditor
python -m src.pipeline --packaging     # 跑出版包装

# 按阶段重跑（不烧全流水线预算）
python -m src.pipeline --plan-only 3        # 只重做第 3 章节拍表
python -m src.pipeline --write-only 3       # 只重写第 3 章正文（复用现有 plan.json）
python -m src.pipeline --evaluate-only 3    # 只重审第 3 章
python -m src.pipeline --fix-only 3         # 只跑一次 Fixer（用现有 verdict.json）
python -m src.pipeline --bookkeeping-only 3 # 人工改过正文后，重刷所有账本
```

CLI 和 Web **调用同一套 Python 函数**（`src.bootstrap.bootstrap_project` / `src.pipeline.run_*`）——不是两套平行实现，不会漂移。

---

## 项目结构

```
novelforge/
├── AGENTS.md                        # 70 行运行时目录页
├── README.md                        # 本文件
├── requirements.txt
├── .env.example
│
├── rules/                           # 通用规则（题材无关）
│   ├── 00-information-priority.md   # 信息源优先级（冲突仲裁协议 R1..R5）
│   ├── 24-iron-laws.md              # 28 条通用铁律（1-24 原版 + 25-28 新增）
│   ├── 18-landmines.md              # 18 个通用雷点（含高疲劳词黑名单）
│   └── writing-style-core.md        # 通用写作风格（六步分析 + 代入感六支柱 + Show-Don't-Tell）
│
├── genres/                          # 题材层：描述某一类题材（多本书共享）
│   ├── README.md                    # 怎么新增题材
│   ├── gangster-hk-1983/            # 港综（含 resource_schema）
│   ├── xianxia-ascension/           # 仙侠（含 resource_schema）
│   └── urban-romance-contemporary/  # 都市言情（无 resource_schema）
│
├── projects/                        # 作品层：一本具体的小说
│   ├── README.md                    # 怎么新增作品
│   ├── .active                      # 单行文本，记录当前激活的项目 id
│   ├── gangster-hk-1983-linjiayao/  # 林家耀的故事（基于 gangster-hk-1983）
│   │   ├── project.yaml             # 关键字段：genre = gangster-hk-1983
│   │   ├── outline.json / characters.yaml / timeline.yaml
│   │   └── state/                   # .gitignore 以下这部分；运行时拷入 + Agent 写入
│   ├── xianxia-ascension-peichangning/   # 裴长宁飞升记
│   └── urban-romance-shenruowei/    # 沈若微记事
│
├── src/
│   ├── config.py                    # 环境变量 + 路径 · STATE_DIR 动态指向当前项目 state/
│   ├── llm.py                       # OpenAI 兼容的 chat 客户端 + 自动写 prompts_log.jsonl
│   ├── blackboard.py                # 原子写 / jsonl 追加 / yaml 读写
│   ├── bootstrap.py                 # genre + project 两层注入 state/
│   ├── pipeline.py                  # 主循环 + 按阶段重跑的多个子命令
│   ├── agents/                      # 5 个创作 Agent + 3 个记账 Agent
│   ├── auditors/                    # 3 个后台审计 Agent（含按需触发的 FactChecker）
│   └── tools/                       # 题材 Lint / 质量仪表盘 / Evaluator 校准
│
├── web/                             # Flask 动态版 UI（本地运行）
│   ├── app.py                       # /api/state 返回账本状态等
│   ├── templates/index.html
│   └── static/{main.css, main.js}
│
├── docs/                            # 架构文档 + GitHub Pages 静态演示 + 演进路线
│   ├── superpowers/specs/2026-05-09-novelforge-design.md
│   ├── gap-analysis-post-mvp.md     # 后 MVP 补齐清单
│   ├── skill-borrowings-plan.md     # skill 借鉴计划（C-22..C-32 的来源）
│   ├── tutorial-borrowings-audit.md # 教程贴 108 条 ↔ 系统落点逐条审计
│   ├── c5-10ch-validation-report.md # 港综 10 章长跑验证报告
│   ├── c10-evaluator-calibration-report.md # Evaluator 三轮校准报告
│   ├── rules/                       # 和根目录 rules/ 同步（Pages 数据源）
│   ├── demo_snapshot/               # 港综 3 章产物（Pages 数据源 1）
│   ├── demo_snapshot_xianxia/       # 仙侠 3 章产物（Pages 数据源 2）
│   ├── demo_snapshot_gangster_c5_10ch/ # 港综 10 章完整长跑（Pages 数据源 3）
│   │                                # 三份 snapshot 的 schema 说明见 demo-snapshots.md
│   └── index.html + main.*          # GitHub Pages 静态演示页
│
├── tests/                           # 288 个测试用例
├── evaluator_calibration/           # Evaluator 校准集（10 case + 3 轮报告）
│
└── projects/<id>/state/             # 运行时产物（.gitignore，不进仓库）
    ├── setting.yaml                 # 运行时合成（genre.yaml + project.yaml 合并）
    ├── outline.json / timeline.yaml / characters.yaml
    ├── era.md / writing-style-extra.md / iron-laws-extra.md
    ├── resource_schema.yaml         # 可选，仅当题材提供时存在
    ├── progress.json
    ├── current_status_card.md       # StatusCardUpdater 整份覆盖（"上下文重置"的入口文件）
    ├── pending_hooks.md             # HookKeeper 整份覆盖（待回收伏笔池）
    ├── resource_ledger.md           # ResourceLedger 整份覆盖（仅当资源定义存在）
    ├── chapters/chNNN.{md,plan.json,verdict.json}
    ├── summaries/chNNN.md
    ├── fixes/chNNN.*-patch.md       # 审计 Agent 产出的建议性补丁
    ├── issues.jsonl
    ├── debt.jsonl
    └── prompts_log.jsonl            # 每次 LLM 调用的完整记录（Web UI 的数据源）
```

---

## Web 演示页 · 三面板

系统有两套 UI：

- **`web/` Flask 动态版**：**默认入口**（见 [如何跑 · 推荐路径](#推荐路径web-端全流程2026-05-11-起)）。读本地 `state/` 实时刷新，按钮真的会调流水线；支持首次启动向导、9 种运行模式、项目切换、.env 在线编辑、源文件可视化修改（`PUT /api/project-files` 会 `preserve_progress` 地重新 seed 到 state/）、中断正在运行的 pipeline（协作式 `CANCEL_EVENT`）
- **`docs/` 静态只读版**：读冻结的快照目录，纯展示用（GitHub Pages 托管）

两套都是三面板布局：

- **左侧**：`state/` 文件树。点任意文件 → 右侧显示内容
- **中间**：当前章节正文（Markdown 渲染）/ 技术债表格 / 规则浏览
- **右侧**（三个切换页）：
  - **Prompt 检查器**：每次 LLM 调用的完整记录，按时间倒序。色彩标注是哪个 Agent 在说话，展开后能看到这次调用读了哪些文件、完整的 system + user + 模型输出、以及"全新会话 · N tokens"标签。这是系统的"可观测性核心"——每一次调用的来龙去脉都在这里。
  - **难题对照**：5 条 Agent 搭建难题 ↔ 代码落点的可点击交叉引用
  - **日志**：密集的时间线日志视图
- **顶部横幅**（静态版）：`[港综 · 1983]` `[仙侠 · 飞升]` 题材切换器，浏览器本地缓存会记住你的选择

---

## 技术栈

- Python 3.9+（本地 3.9.6 + CI 跑 3.9/3.11/3.12/3.13）
- `httpx` — LLM 客户端（不用官方 SDK，走 OpenAI 兼容协议）
- `flask` — 动态版 UI
- `pyyaml` — 黑板存储
- `python-dotenv` — 读取 `.env` 配置
- **不用任何 Agent 框架**（LangChain / CrewAI / AutoGen 一概不用）

**默认 LLM**：DeepSeek-V4-Pro（通过 EasyClaw 平台的 OpenAI 兼容代理访问）

---

## 测试

```bash
python -m pytest tests/ -v
```

**288 个测试用例**，覆盖：

- `test_blackboard.py` — 原子写 / jsonl 顺序保证 / YAML 往返
- `test_verdict_schema.py` — Evaluator JSON 评分表校验 + 骨架检测器
- `test_multi_level_summarizer.py` — 章摘 / 弧摘 / 卷摘的边界与上下文组装
- `test_packaging.py` — 出版包装 Agent
- `test_setting_lint.py` + `test_bootstrap_and_settings.py` — 题材包校验 + 可选资源定义注入/切换清理
- `test_status_card_updater.py` / `test_hook_keeper.py` / `test_resource_ledger.py` — 3 个记账 Agent 的 prompt 构造 + 数据隔离边界
- `test_planner_extensions.py` / `test_generator_extensions.py` / `test_evaluator_fixer_extensions.py` — 新字段（章节类型 / 场景推进项 / 写作自检 / 风格锁定 / 信息源优先级）
- `test_pipeline_intent_router.py` — 5 个子命令的 CLI 分发 + 全链路顺序验证（LLM 调用被 mock 掉，不烧 token）
- `test_fact_checker.py` — FactChecker 的触发门控 + 联网核查 + 优雅降级
- `test_isolation_boundaries.py` — 数据隔离回归守卫（Generator/Evaluator/Summarizer 不得读账本文件）
- `test_rules_and_docs.py` + `test_web_and_pages_sync.py` — 文档即代码（`rules/00` 存在性、AGENTS.md 完整性、`docs/rules` 与 `rules/` 偏离守卫）
- `test_dashboard_bookkeeping.py` — 质量仪表盘的账本区块渲染

**覆盖策略**：prompt 构造（输入文件清单、必读文件）用单元测试；Agent 输出质量通过端到端运行验证（见 `docs/demo_snapshot*/` 下三个题材的实测产出，尤其 `docs/demo_snapshot_gangster_c5_10ch/` 的 10 章完整小说）。

---

## 设计文档与演进路线

系统经过**三轮独立 Oracle（架构顾问）评审**，每轮都采纳了关键修改：

| 评审 | 发现 | 采纳 |
|---|---|---|
| 实施前 | 架构真的体现了 5 大难题吗？ | 独立 Summarizer、Auditor 从 4 砍到 2、加 Prompt 检查器 UI |
| 实施后 | Evaluator 有 2 章假过（返回了 prompt 骨架） | 加骨架检测器、AISlopGuard 改写质量收紧、UI 加难题对照页 |
| 升级思考 | MVP → 通用系统还差什么？ | 9 个必做项 / 18 个应做项清单 + 5 周路线图 |

所有文档：

- **架构设计** · [`docs/superpowers/specs/2026-05-09-novelforge-design.md`](docs/superpowers/specs/2026-05-09-novelforge-design.md)
- **后 MVP 差距分析 + 路线图** · [`docs/gap-analysis-post-mvp.md`](docs/gap-analysis-post-mvp.md)
- **教程贴借鉴审计** · [`docs/tutorial-borrowings-audit.md`](docs/tutorial-borrowings-audit.md)
- **港综 10 章长跑验证报告** · [`docs/c5-10ch-validation-report.md`](docs/c5-10ch-validation-report.md)
- **Evaluator 三轮校准报告** · [`docs/c10-evaluator-calibration-report.md`](docs/c10-evaluator-calibration-report.md)
- **运行时目录页** · [`AGENTS.md`](AGENTS.md)
- **题材包系统** · [`genres/README.md`](genres/README.md)  +  [`projects/README.md`](projects/README.md)

---

## 许可

MIT.

港综题材中「霍官泰」「李超人」「邵老板」「包船王」等是对真实历史人物的代指化处理，事件与时间线基于 1983-1985 年真实香港公开史料。仙侠题材为完全虚构。都市言情题材中的公司（腾讯 / 字节 / 阿里 / 华为等）仅作时代背景提及，不作道德褒贬。
