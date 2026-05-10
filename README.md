# 🔨 Novelforge

> *Production-grade multi-agent novel pipeline. Filesystem-as-memory, adversarial review, three-tier bookkeeping, hot-swappable genres.*

**小说锻造厂** — 把"一个 AI 一路写到黑"拆成 10 个独立 Agent 的长链路流水线。Anthropic / Cognition / OpenAI 在长链路 Agent 上踩过的 5 个坑，全部作为架构约束来设计：**状态沉在文件**、**对抗式审稿**、**三层账本**、**题材热插拔**、**渐进式披露**。

> **当前阶段**：Post-MVP Must+Should 扫清（gap-analysis C-22..C-32 全部落地 + bookkeeping layer）
> **下一阶段**：10+ 章长跑验证 + Evaluator 校准集 + CI，见 [`docs/gap-analysis-post-mvp.md`](docs/gap-analysis-post-mvp.md)
> **仓库主页**：[github.com/CalWade/novelforge](https://github.com/CalWade/novelforge)
> **演示**：[calwade.github.io/novelforge/](https://calwade.github.io/novelforge/)（静态只读）

---

## 一分钟讲清楚是什么

一本小说不是一个 AI 从头写到尾的 —— 它由 **5 个创作 Agent + 3 个 bookkeeping Agent + 2 个后台审计 Agent** 分工合作：

```
Planner 拆节拍 → Generator 写正文 → Evaluator 挑刺 → Fixer 改稿 → Summarizer 摘要
                                                                        │
                                       ┌────── Lesson-3 bookkeeping ───┤
                                       │                                │
                                 StatusCardUpdater            HookKeeper
                                 （当前状态卡）               （待回收伏笔池）
                                       │                                │
                                 ResourceLedger（可选，若 setting 有 resource_schema）
                                       │
                                       ├──────── Fan-Out 并行审计 ─────┤
                                       │                                │
                                 AISlopGuard                    CharacterGuard
```

每一个 Agent 都用独立的 LLM 调用、独立的 system prompt、独立的上下文窗口。**所有状态存在文件里**（`state/`），**不在内存里**。

核心性质：**一个 Python 进程死了，换一个新进程，读 `state/current_status_card.md` 就知道刚才到了哪一章、主角当前什么状态、哪些伏笔还没回收**——这是 Cognition 所说的 Context Reset 的工程化落地。

**题材 = 数据**：流水线本身（`src/`）对题材一无所知。题材通过 **Setting Pack**（`settings/<name>/`）注入，切题材只需重新 bootstrap，不用改代码。内置三个题材：**港综 1983**、**仙侠飞升**、**都市言情·深圳**。

---

## 架构：三层嵌套

```
外层（宏观）： Pipeline — 章节线性推进
每章内部：    Blackboard — state/ 文件 = 唯一共享记忆
每章产后：    Fan-Out — 2 个 Auditor 并行扫
Evaluator:  半 Debate — 对抗人设 + 结构化 JSON rubric + skeleton detector
```

| Agent | 读 | 写 | Temp |
|---|---|---|---|
| **Planner** | outline + 最近 2 摘要 + setting.yaml + **current_status_card.md** + **pending_hooks.md** | `chNNN.plan.json`（含 chapter_type / scene.advances / writing_self_check） | 0.4 |
| **Generator** | plan + characters + writing-style（core + extra）+ era + **setting.prohibited_styles** | `chNNN.md`（~3000 字） | 0.85 |
| **Evaluator** | chNNN.md + 18-landmines + 24-iron-laws（core + extra）+ **rules/00-information-priority.md** + chars + timeline | `verdict.json` + issues.jsonl | 0.0 |
| **Fixer** | chNNN.md + verdict.top_3_fixes + writing-style（core + extra）+ setting.prohibited_styles | 覆写 `chNNN.md` | 0.5 |
| **Summarizer** | **只读** `chNNN.md` | `summaries/chNNN.md` | 0.2 |
| **StatusCardUpdater** | chNNN.md + 上一版 status card + characters.yaml | `current_status_card.md`（覆盖式） | 0.2 |
| **HookKeeper** | chNNN.md + 上一版 pending_hooks + status card | `pending_hooks.md`（覆盖式） | 0.2 |
| **ResourceLedger**（可选） | resource_schema.yaml + chNNN.md + 上一版 ledger | `resource_ledger.md`（覆盖式） | 0.2 |
| **AISlopGuard** | chNNN.md | `fixes/chNNN.slop-patch.md` | 0.2 |
| **CharacterGuard** | chNNN.md + characters.yaml + 历史摘要 | `fixes/chNNN.char-patch.md` | 0.2 |
| **FactChecker**（A-1，按需） | chNNN.md + verdict.json + era.md | `fixes/chNNN.fact-patch.md` | 0.0 |

> FactChecker 只在 Evaluator 命中 `landmine_13`（世界观模糊/脱离现实）且 severity ∈ {medium, high} 时触发。调用 Perplexity Sonar 查 ≤3 个可查证断言，产出建议性补丁（不改 verdict）。未配置 `PERPLEXITY_API_KEY` 时优雅降级。

---

## 对应 5 大 Agent 搭建难题

| 难题 | 出处 | 本项目对策 |
|---|---|---|
| ① 反复失败、无反馈链路 | Anthropic | 所有 Agent 无状态，失败写入 `issues.jsonl` + `debt.jsonl`，下一轮 Fixer 从文件读重新进入干净会话 |
| ② 自评偏乐观 | Anthropic | 五个独立 Agent + Evaluator **对抗人设（默认拒稿）** + **结构化 JSON rubric**（18 个 landmine 逐条打分）+ **skeleton detector**（防模型复制 prompt 示例） |
| ③ Context Anxiety | Cognition | 每次调用都是 **fresh window** + 只读它需要的 1-2 个文件。Summarizer **独立会话**，只读最终章节正文，不读 plan/issues（防 framing 后门泄漏） |
| ④ AI Slop | OpenAI Codex | `rules/*.md` + `settings/<name>/iron-laws-extra.md` 是黄金原则。每章跑完自动触发 2 个后台 Auditor，产出独立 `fixes/*.patch.md`。Evaluator 2 次 retry 仍不过 → `shipped_with_debt`，技术债进 `debt.jsonl` |
| ⑤ 规则百科病 | OpenAI | `AGENTS.md` **只 70 行目录页**，详细拆到 `rules/` 通用 + `settings/<name>/` 题材。每个 Agent 只加载它需要的那 1-2 份 |

---

## Setting Pack — 题材即插即用

流水线对题材一无所知。题材通过 `settings/<name>/` 下的 7 + 1 个文件注入：

```
settings/<name>/
├── setting.yaml              # 元信息：题材名、基调、作者画像、prohibited_styles
├── outline.json              # 整本大纲 + 每章节拍
├── timeline.yaml             # 时代/世界观时间线
├── characters.yaml           # 人物档案
├── era.md                    # 时代/世界观事实包
├── writing-style-extra.md    # 题材特有风格
├── iron-laws-extra.md        # 题材特有铁律
└── resource_schema.yaml      # [可选] 题材的可追踪资源定义（仙侠 / 港综有；都市言情无）
```

切题材只需：

```bash
python -m src.bootstrap --setting urban-romance-contemporary
```

内置三个题材：

| Setting | 题材 | 状态 | 资源 schema | 产出 |
|---|---|---|---|---|
| `gangster-hk-1983` | 港综同人，1983 香港，福建新移民抵港白手起家 | ✅ 跑过 3 章 | ✅ 情报值/黑金/人情/仇家 | `demo_snapshot/` |
| `xianxia-ascension` | 仙侠修真，青龙历纪元，灵气 recovering 时代 | ✅ 跑过 3 章 | ✅ 灵石/灵草/境界/法器/因果 | `demo_snapshot_xianxia/` |
| `urban-romance-contemporary` | 都市言情·2024 深圳科技园，30 岁 PM 的克制成人叙事 | ⚠️ 结构完整，未跑 LLM | ❌ 非数值化（故意） | — |

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

# 3. 选择并激活一个 Setting
python -m src.bootstrap --list                       # 看可用题材
python -m src.bootstrap --setting gangster-hk-1983   # 或 xianxia-ascension

# 4. 跑流水线
python -m src.pipeline --chapter 1     # 一章（全流水线）
python -m src.pipeline --range 1-3     # 三章
python -m src.pipeline --audit-only 1  # 只跑两个 Auditor

# 4b. Intent Router — 按需重跑某个阶段（不烧全流水线的 LLM 预算）
python -m src.pipeline --plan-only 3        # 只重做 ch3 节拍表
python -m src.pipeline --write-only 3       # 只重写 ch3 正文（复用现有 plan.json）
python -m src.pipeline --evaluate-only 3    # 只重审 ch3
python -m src.pipeline --fix-only 3         # 只跑一次 Fixer（用现有 verdict）
python -m src.pipeline --bookkeeping-only 3 # 人工改过正文后，重刷所有账本

# 5. 打开 Web 演示（macOS 的 5000 被 AirPlay 占，用 5055）
flask --app web.app run --port 5055
# 浏览器打开 http://localhost:5055/
```

---

## 项目结构

```
novelforge/
├── AGENTS.md                        # 70 行运行时 ToC
├── README.md                        # 本文件
├── requirements.txt
├── .env.example
│
├── rules/                           # 通用规则（题材无关）
│   ├── 00-information-priority.md   # 信息源优先级（冲突仲裁协议，R1..R5）
│   ├── 24-iron-laws.md              # 28 条通用铁律（1-24 原版 + 25-28 skill 借鉴）
│   ├── 18-landmines.md              # 18 个通用雷点（含高疲劳词黑名单）
│   └── writing-style-core.md        # 通用写作风格（六步 + 代入感六支柱 + Show-Don't-Tell）
│
├── settings/                        # 题材包目录
│   ├── README.md                    # 怎么添加新题材
│   ├── gangster-hk-1983/            # 港综（7 + resource_schema = 8 文件）
│   ├── xianxia-ascension/           # 仙侠（7 + resource_schema = 8 文件）
│   └── urban-romance-contemporary/  # 都市言情（7 文件，无 resource_schema）
│
├── src/
│   ├── config.py                    # 环境变量 + 路径
│   ├── llm.py                       # OpenAI 兼容 chat() + 自动写 prompts_log.jsonl
│   ├── blackboard.py                # 原子写 / jsonl 追加 / yaml 读写
│   ├── bootstrap.py                 # 从 setting pack 初始化 state/（含可选 resource_schema）
│   ├── pipeline.py                  # 主循环 + Intent Router（按阶段重跑）
│   ├── agents/                      # 5 创作 + 3 bookkeeping 共 8 个 Agent
│   ├── auditors/                    # 2 个后台 Auditor
│   └── tools/                       # setting_lint / dashboard / calibrate_evaluator
│
├── web/                             # Flask 动态版 UI（本地运行）
│   ├── app.py                       # /api/state 返回 bookkeeping.* 等
│   ├── templates/index.html
│   └── static/{main.css, main.js}
│
├── docs/                            # 架构文档 + GitHub Pages 静态演示 + 演进路线
│   ├── superpowers/specs/2026-05-09-novelforge-design.md
│   ├── gap-analysis-post-mvp.md     # 后 MVP 补齐清单
│   ├── skill-borrowings-plan.md     # skill 借鉴计划（C-22..C-32 来源）
│   ├── tutorial-borrowings-audit.md # 教程贴 108 条 ↔ 系统落点逐条审计
│   ├── rules/                       # docs/rules 与 rules/ 同步（Pages 数据源）
│   └── index.html + main.*          # GitHub Pages 静态演示页
│
├── demo_snapshot/                   # 港综 setting 3 章产物 + bookkeeping 样本（Pages 数据源 1）
├── demo_snapshot_xianxia/           # 仙侠 setting 3 章产物 + bookkeeping 样本（Pages 数据源 2）
│
├── tests/                           # 244 个 pytest 用例（详见"测试"节）
│
└── state/                           # 运行时产物（.gitignore）
    ├── setting.yaml                 # 当前激活的 setting（由 bootstrap 拷入）
    ├── outline.json / timeline.yaml / characters.yaml
    ├── era.md / writing-style-extra.md / iron-laws-extra.md
    ├── resource_schema.yaml         # 可选；仅当 setting 提供时存在
    ├── progress.json
    ├── current_status_card.md       # StatusCardUpdater 覆盖式维护（Lesson-3 Reset 入口）
    ├── pending_hooks.md             # HookKeeper 覆盖式维护（待回收伏笔池）
    ├── resource_ledger.md           # ResourceLedger 覆盖式维护（仅当 schema 存在）
    ├── chapters/chNNN.{md,plan.json,verdict.json}
    ├── summaries/chNNN.md
    ├── fixes/chNNN.*-patch.md
    ├── issues.jsonl
    ├── debt.jsonl
    └── prompts_log.jsonl            # 每次 LLM 调用的完整记录（Inspector 数据源）
```

---

## Web UI 三面板

系统有两套 UI：

- **`web/` Flask 动态版**：读本地 `state/` 实时刷新，按钮真调 pipeline（本地跑）
- **`docs/` 静态只读版**：`demo_snapshot/` 冻结产物，评估用（GitHub Pages 托管）

两套都是三面板布局：

- **左**：`state/` 文件树。点任意文件 → 右侧显示。
- **中**：当前章节 Markdown / Debt 表格 / Rules 浏览。
- **右（tab）**：
  - **Prompt Inspector**：每次 LLM 调用的完整记录，按时间倒序。色彩标注 Agent 身份，展开看到 `inputs_read` / 完整 system+user+output / `Fresh context · N tokens` 标签。这是系统的"可观测性核心"。
  - **Lessons Map**：5 条 agent 搭建难题 ↔ 代码落点的可点击交叉引用。
  - **Log**：密集的时间线日志视图。
- **顶部**（静态版）：`[港综 · 1983] [仙侠 · 飞升]` 切换器，localStorage 持久化。

---

## 技术栈

- Python 3.11+
- `httpx` — LLM 客户端（无 SDK，OpenAI 兼容协议）
- `flask` — 动态版 UI
- `pyyaml` — 黑板存储
- `python-dotenv` — 配置
- **无 Agent 框架**（LangChain / CrewAI / AutoGen 一概不用）

**默认 LLM**：DeepSeek-V4-Pro（通过 EasyClaw 平台的 OpenAI 兼容代理）

---

## 测试

```bash
python -m pytest tests/ -v
```

**244 个 pytest 用例**，覆盖：

- `test_blackboard.py` — 原子写 / jsonl 顺序 / YAML 往返
- `test_verdict_schema.py` — Evaluator JSON rubric + skeleton detector
- `test_multi_level_summarizer.py` — L1/L2/L3 摘要边界与上下文组装
- `test_packaging.py` — 出版包装 Agent
- `test_setting_lint.py` + `test_bootstrap_and_settings.py` — 题材包验证 + 可选 resource_schema 注入/切换清理
- `test_status_card_updater.py` / `test_hook_keeper.py` / `test_resource_ledger.py` — 3 个 bookkeeping Agent 的 prompt 构造 + Lesson-3 边界
- `test_planner_extensions.py` / `test_generator_extensions.py` / `test_evaluator_fixer_extensions.py` — 新字段（chapter_type / advances / writing_self_check / prohibited_styles / info-priority）
- `test_pipeline_intent_router.py` — Intent Router 5 个子命令的 CLI 分发 + 全链路顺序验证（LLM 调用被 monkey-patch）
- `test_isolation_boundaries.py` — Lesson-3 回归保护（Generator/Evaluator/Summarizer 不得读 bookkeeping ledgers）
- `test_rules_and_docs.py` + `test_web_and_pages_sync.py` — 文档即代码（rules/00 存在性、AGENTS.md 完整性、docs/rules 与 rules/ drift 守卫）

**覆盖策略**：prompt 构造（inputs_read 清单、必读文件）通过单元测试；Agent 输出质量通过端到端运行验证（见 `demo_snapshot*/` 下三个题材的实测产出）。

后 MVP 阶段会加：Evaluator 校准集（`docs/gap-analysis-post-mvp.md` C-10）、CI（C-21）。

---

## 设计文档与演进路线

系统经过**三轮独立 Oracle 评审**，每轮都采纳了关键修改：

| 评审 | 发现 | 采纳 |
|---|---|---|
| 实施前 | 架构是否真的体现 5 大难题？ | 加独立 Summarizer、Auditor 砍 4→2、加 Prompt Inspector UI |
| 实施后 | Evaluator 在 2 章 false-pass（返回 prompt 骨架） | 加 skeleton detector、AISlop 改写质量收紧、UI 加 Lessons Map |
| 升级思考 | MVP → 通用系统需要补哪些？ | 9 Must / 18 Should 清单 + 5 周路线图 |

所有文档：

- **架构设计** · [`docs/superpowers/specs/2026-05-09-novelforge-design.md`](docs/superpowers/specs/2026-05-09-novelforge-design.md)
- **后 MVP Gap 分析与路线图** · [`docs/gap-analysis-post-mvp.md`](docs/gap-analysis-post-mvp.md)
- **教程贴借鉴审计** · [`docs/tutorial-borrowings-audit.md`](docs/tutorial-borrowings-audit.md)
- **运行时 ToC** · [`AGENTS.md`](AGENTS.md)
- **Setting 系统** · [`settings/README.md`](settings/README.md)

---

## 许可

MIT.

港综 setting 中「霍官泰」「李超人」「邵老板」「包船王」等是对真实历史人物的代指化处理。事件与时间线基于 1983-1985 真实香港公开史料。仙侠 setting 为完全虚构。都市言情 setting 中的公司（腾讯/字节/阿里/华为等）为时代背景提及，不作道德褒贬。
