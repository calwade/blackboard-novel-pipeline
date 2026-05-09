# 🦞 Blackboard Novel Pipeline

**通用多 Agent 小说写作流水线** — 把 Anthropic / Cognition / OpenAI 在长链路 Agent 上踩过的 5 个坑，当作架构约束来设计。

> **当前阶段**：MVP+（已跑通 2 个题材 × 各 3 章完整产物）
> **下一阶段**：向"大而全通用系统"演进，见 [`docs/gap-analysis-post-mvp.md`](docs/gap-analysis-post-mvp.md)
> **仓库主页**：[github.com/CalWade/blackboard-novel-pipeline](https://github.com/CalWade/blackboard-novel-pipeline)
> **演示**：[calwade.github.io/blackboard-novel-pipeline/](https://calwade.github.io/blackboard-novel-pipeline/)（静态只读）

---

## 一分钟讲清楚是什么

一本小说不是一个 AI 从头写到尾的 —— 它由 **5 个主 Agent + 2 个后台审计 Agent** 轮流工作：

```
Planner 拆节拍 → Generator 写正文 → Evaluator 挑刺 → Fixer 改稿 → Summarizer 摘要
                                                                       │
                                            ┌──── Fan-Out 并行审计 ───┤
                                            │                          │
                                      AISlopGuard              CharacterGuard
```

每一个 Agent 都用独立的 LLM 调用、独立的 system prompt、独立的上下文窗口。**所有状态存在文件里**（`state/`），**不在内存里**。

核心性质：**一个 Python 进程死了，换一个新进程，读 `state/progress.json` 就知道刚才到了哪一章**——这是 Cognition 所说的 Context Reset 的工程化落地。

**题材 = 数据**：流水线本身（`src/`）对题材一无所知。题材通过 **Setting Pack**（`settings/<name>/`）注入，切题材只需重新 bootstrap，不用改代码。内置两个示例：**港综 1983** 和 **仙侠飞升**。

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
| **Planner** | outline + 最近 2 摘要 + setting.yaml | `chNNN.plan.json` | 0.4 |
| **Generator** | plan + characters + writing-style（core + extra）+ era | `chNNN.md`（~3000 字） | 0.85 |
| **Evaluator** | chNNN.md + 18-landmines + 24-iron-laws（core + extra）+ chars + timeline | `verdict.json` + issues.jsonl | 0.0 |
| **Fixer** | chNNN.md + verdict.top_3_fixes + writing-style（core + extra） | 覆写 `chNNN.md` | 0.5 |
| **Summarizer** | **只读** `chNNN.md` | `summaries/chNNN.md` | 0.2 |
| **AISlopGuard** | chNNN.md | `fixes/chNNN.slop-patch.md` | 0.2 |
| **CharacterGuard** | chNNN.md + characters.yaml + 历史摘要 | `fixes/chNNN.char-patch.md` | 0.2 |

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

流水线对题材一无所知。题材通过 `settings/<name>/` 下的 7 个文件注入：

```
settings/<name>/
├── setting.yaml              # 元信息：题材名、基调、作者画像
├── outline.json              # 整本大纲 + 每章节拍
├── timeline.yaml             # 时代/世界观时间线
├── characters.yaml           # 人物档案
├── era.md                    # 时代/世界观事实包
├── writing-style-extra.md    # 题材特有风格
└── iron-laws-extra.md        # 题材特有铁律
```

切题材只需：

```bash
python -m src.bootstrap --setting xianxia-ascension
```

内置两个示例（均完整跑过 3 章）：

| Setting | 题材 | 产出 |
|---|---|---|
| `gangster-hk-1983` | 港综同人，1983 香港，福建新移民抵港白手起家 | `demo_snapshot/` |
| `xianxia-ascension` | 仙侠修真，青龙历纪元，灵气 recovering 时代 | `demo_snapshot_xianxia/` |

详见 [`settings/README.md`](settings/README.md)。

---

## 如何跑

```bash
# 1. 克隆 + 环境
git clone https://github.com/CalWade/blackboard-novel-pipeline.git
cd blackboard-novel-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置 LLM
cp .env.example .env
# 在 .env 里填入 DEEPSEEK_API_KEY

# 3. 选择并激活一个 Setting
python -m src.bootstrap --list                       # 看可用题材
python -m src.bootstrap --setting gangster-hk-1983   # 或 xianxia-ascension

# 4. 跑流水线
python -m src.pipeline --chapter 1     # 一章
python -m src.pipeline --range 1-3     # 三章
python -m src.pipeline --audit-only 1  # 只跑审计

# 5. 打开 Web 演示（macOS 的 5000 被 AirPlay 占，用 5055）
flask --app web.app run --port 5055
# 浏览器打开 http://localhost:5055/
```

---

## 项目结构

```
blackboard-novel-pipeline/
├── AGENTS.md                        # 70 行运行时 ToC
├── README.md                        # 本文件
├── requirements.txt
├── .env.example
│
├── rules/                           # 通用规则（题材无关）
│   ├── 24-iron-laws.md              # 24 条通用铁律
│   ├── 18-landmines.md              # 18 个通用雷点
│   └── writing-style-core.md        # 通用写作风格（六步 + 代入感六支柱 + Show-Don't-Tell）
│
├── settings/                        # 题材包目录
│   ├── README.md                    # 怎么添加新题材
│   ├── gangster-hk-1983/            # 港综（7 文件）
│   └── xianxia-ascension/           # 仙侠（7 文件）
│
├── src/
│   ├── config.py                    # 环境变量 + 路径
│   ├── llm.py                       # OpenAI 兼容 chat() + 自动写 prompts_log.jsonl
│   ├── blackboard.py                # 原子写 / jsonl 追加 / yaml 读写
│   ├── bootstrap.py                 # 从 setting pack 初始化 state/
│   ├── pipeline.py                  # 主循环：plan → gen → eval↔fix → sum → fan-out
│   ├── agents/                      # 5 个主 Agent
│   └── auditors/                    # 2 个后台 Auditor
│
├── web/                             # Flask 动态版 UI（本地运行）
│   ├── app.py                       # 10 个 API 路由
│   ├── templates/index.html
│   └── static/{main.css, main.js}
│
├── docs/                            # 架构文档 + GitHub Pages 静态演示 + 演进路线
│   ├── superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md
│   │                                  # 架构设计（三层嵌套 / 5 大难题对应 / Setting System）
│   ├── gap-analysis-post-mvp.md     # 后 MVP · 9 Must / 18 Should 补齐清单
│   ├── tutorial-borrowings-audit.md # 教程贴 108 条 ↔ 系统落点逐条审计
│   ├── Agent 搭建难题.md            # 原始输入（5 大难题资料）
│   ├── ai 小说流水线教程贴.txt      # 原始输入（教程贴）
│   └── index.html + main.*          # GitHub Pages 静态演示页
│
├── demo_snapshot/                   # 港综 setting 3 章完整产物（Pages 数据源 1）
├── demo_snapshot_xianxia/           # 仙侠 setting 3 章完整产物（Pages 数据源 2）
│
├── tests/test_blackboard.py         # 6 个黑板 I/O 测试
│
└── state/                           # 运行时产物（.gitignore）
    ├── setting.yaml                 # 当前激活的 setting（由 bootstrap 拷入）
    ├── outline.json / timeline.yaml / characters.yaml
    ├── era.md / writing-style-extra.md / iron-laws-extra.md
    ├── progress.json
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

现役测试：黑板的原子写 / jsonl 顺序保证 / YAML 往返（`tests/test_blackboard.py`，6 个用例）。**覆盖范围仅限 `src/blackboard.py`**——Agent 和 Pipeline 通过端到端运行验证。小说 Agent 的单元测试意义不大，输出质量必须人看（见 `demo_snapshot*/` 下两个题材各 3 章实测产出）。

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

- **架构设计** · [`docs/superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md`](docs/superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md)
- **后 MVP Gap 分析与路线图** · [`docs/gap-analysis-post-mvp.md`](docs/gap-analysis-post-mvp.md)
- **教程贴借鉴审计** · [`docs/tutorial-borrowings-audit.md`](docs/tutorial-borrowings-audit.md)
- **运行时 ToC** · [`AGENTS.md`](AGENTS.md)
- **Setting 系统** · [`settings/README.md`](settings/README.md)

---

## 许可

MIT.

港综 setting 中「霍官泰」「李超人」「邵老板」「包船王」等是对真实历史人物的代指化处理。事件与时间线基于 1983-1985 真实香港公开史料。仙侠 setting 为完全虚构。
