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

**题材 = 数据**：流水线本身（`src/`）对题材一无所知。题材通过 **Setting Pack（题材包）**（放在 `settings/<题材名>/`）注入——切换题材只需要重新跑一次初始化命令，不用改一行代码。内置三个题材：**港综 1983**、**仙侠飞升**、**都市言情·深圳**。

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
| ④ AI 味代码堆积 | OpenAI Codex | `rules/*.md` + `settings/<题材>/iron-laws-extra.md` 就是黄金原则；每章跑完自动触发 2 个后台 Auditor，产出独立补丁文件；Evaluator 两轮重试仍不过 → **带病上线**（写入 `debt.jsonl`，避免死循环） |
| ⑤ 规则文件百科病 | OpenAI | `AGENTS.md` **只 70 行目录页**；详细拆到 `rules/` 通用 + `settings/<题材>/` 题材特有；每个 Agent 只加载它需要的那 1-2 份 |

---

## Setting Pack — 题材即插即用

流水线对题材一无所知。题材通过 `settings/<题材名>/` 下的 7 + 1 个文件注入：

```
settings/<题材名>/
├── setting.yaml              # 元信息：题材名、基调、作者画像、禁用风格黑名单
├── outline.json              # 整本大纲 + 每章节拍
├── timeline.yaml             # 时代/世界观时间线
├── characters.yaml           # 人物档案
├── era.md                    # 时代/世界观事实包
├── writing-style-extra.md    # 题材特有的写作风格
├── iron-laws-extra.md        # 题材特有的铁律
└── resource_schema.yaml      # [可选] 题材的可追踪资源定义（仙侠 / 港综有；都市言情无）
```

切换题材只需：

```bash
python -m src.bootstrap --setting urban-romance-contemporary
```

内置三个题材：

| 题材包 ID | 题材描述 | 状态 | 资源定义 | 产出目录 |
|---|---|---|---|---|
| `gangster-hk-1983` | 港综同人，1983 香港，福建新移民抵港白手起家 | ✅ 跑过 10 章 | ✅ 情报值 / 黑金 / 人情 / 仇家 | `demo_snapshot_gangster_c5_10ch/` |
| `xianxia-ascension` | 仙侠修真，青龙历纪元，灵气复苏时代 | ✅ 跑过 3 章 | ✅ 灵石 / 灵草 / 境界 / 法器 / 因果 | `demo_snapshot_xianxia/` |
| `urban-romance-contemporary` | 都市言情·2024 深圳科技园，30 岁产品经理的克制成人叙事 | ⚠️ 结构完整，未跑 LLM | ❌ 不做数值化（有意为之） | — |

详见 [`settings/README.md`](settings/README.md)。

---

## 如何跑

```bash
# 1. 克隆 + 环境
git clone https://github.com/CalWade/novelforge.git
cd novelforge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置 LLM
cp .env.example .env
# 在 .env 里填入 DEEPSEEK_API_KEY

# 3. 选择并激活一个题材
python -m src.bootstrap --list                       # 看所有可用题材
python -m src.bootstrap --setting gangster-hk-1983   # 激活港综（或 xianxia-ascension）

# 4. 跑流水线
python -m src.pipeline --chapter 1     # 跑一章（全流水线）
python -m src.pipeline --range 1-3     # 跑一到三章
python -m src.pipeline --audit-only 1  # 只重跑 2 个 Auditor

# 4b. 按阶段重跑（不烧全流水线预算）
python -m src.pipeline --plan-only 3        # 只重做第 3 章节拍表
python -m src.pipeline --write-only 3       # 只重写第 3 章正文（复用现有 plan.json）
python -m src.pipeline --evaluate-only 3    # 只重审第 3 章
python -m src.pipeline --fix-only 3         # 只跑一次 Fixer（用现有 verdict.json）
python -m src.pipeline --bookkeeping-only 3 # 人工改过正文后，重刷所有账本

# 5. 打开 Web 演示（macOS 的 5000 被 AirPlay 占，所以用 5055）
flask --app web.app run --port 5055
# 浏览器打开 http://localhost:5055/
```

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
├── settings/                        # 题材包目录
│   ├── README.md                    # 怎么添加新题材
│   ├── gangster-hk-1983/            # 港综（7 + 可选资源定义 = 8 文件）
│   ├── xianxia-ascension/           # 仙侠（7 + 可选资源定义 = 8 文件）
│   └── urban-romance-contemporary/  # 都市言情（7 文件，无资源定义）
│
├── src/
│   ├── config.py                    # 环境变量 + 路径
│   ├── llm.py                       # OpenAI 兼容的 chat 客户端 + 自动写 prompts_log.jsonl
│   ├── blackboard.py                # 原子写 / jsonl 追加 / yaml 读写
│   ├── bootstrap.py                 # 从题材包初始化 state/（含可选的资源定义）
│   ├── pipeline.py                  # 主循环 + 按阶段重跑的多个子命令
│   ├── agents/                      # 5 个创作 Agent + 3 个记账 Agent，共 8 个
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
│   └── index.html + main.*          # GitHub Pages 静态演示页
│
├── demo_snapshot/                   # 港综 3 章产物 + 账本样本（Pages 数据源 1）
├── demo_snapshot_xianxia/           # 仙侠 3 章产物 + 账本样本（Pages 数据源 2）
├── demo_snapshot_gangster_c5_10ch/  # 港综 10 章完整长跑产物
│
├── tests/                           # 288 个测试用例
├── evaluator_calibration/           # Evaluator 校准集（10 case + 3 轮报告）
│
└── state/                           # 运行时产物（.gitignore，不进仓库）
    ├── setting.yaml                 # 当前激活的题材（bootstrap 拷入）
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

- **`web/` Flask 动态版**：读本地 `state/` 实时刷新，按钮真的会调流水线（本地跑）
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

- Python 3.11+
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

**覆盖策略**：prompt 构造（输入文件清单、必读文件）用单元测试；Agent 输出质量通过端到端运行验证（见 `demo_snapshot*/` 下三个题材的实测产出，尤其 `demo_snapshot_gangster_c5_10ch/` 的 10 章完整小说）。

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
- **题材包系统** · [`settings/README.md`](settings/README.md)

---

## 许可

MIT.

港综题材中「霍官泰」「李超人」「邵老板」「包船王」等是对真实历史人物的代指化处理，事件与时间线基于 1983-1985 年真实香港公开史料。仙侠题材为完全虚构。都市言情题材中的公司（腾讯 / 字节 / 阿里 / 华为等）仅作时代背景提及，不作道德褒贬。
