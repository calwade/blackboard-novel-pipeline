# 🦞 Blackboard Novel Pipeline · 港务档案 1983

**多 Agent 港综同人小说写作流水线** — 把 Anthropic/Cognition/OpenAI 在长链路 Agent 上踩过的 5 个坑，当作架构约束来设计。

> 参赛作品：**2026 傅盛 AI 战队青少年黑客松**
> 截止：2026-05-10 23:59 北京

---

## 60 秒是什么项目

1983 年的香港，主角要白手起家。这本小说不是一个 AI 从头写到尾的 —— 它由 **5 个主 Agent + 2 个后台审计 Agent** 轮流工作，每一个都用独立的 LLM 调用、独立的 system prompt、独立的上下文窗口。所有状态存在文件里（`state/`），不在内存里。

核心卖点：**一个 Python 进程死了，换一个新进程，读 `state/progress.json` 就知道刚才到了哪一章——这就是 Cognition 说的 Context Reset**。

---

## 架构：三层嵌套

```
外层（宏观）： Pipeline — 章节线性推进
每章内部：    Blackboard — state/ 文件 = 唯一共享记忆
每章产后：    Fan-Out — 2 个 Auditor 并行扫
Evaluator:  半 Debate — 对抗人设 + 结构化 JSON rubric
```

| Agent | 读 | 写 | Temp |
|---|---|---|---|
| **Planner** | outline + 最近 2 摘要 | `chNNN.plan.json` | 0.4 |
| **Generator** | plan + characters + writing-style + era | `chNNN.md` (~3000字) | 0.85 |
| **Evaluator** | chNNN.md + 18-landmines + 24-iron-laws | `verdict.json` + issues.jsonl | 0.0 |
| **Fixer** | chNNN.md + verdict.top_3_fixes | 覆写 `chNNN.md` | 0.5 |
| **Summarizer** | **只读** `chNNN.md` | `summaries/chNNN.md` | 0.2 |
| **AISlopGuard** | chNNN.md | `fixes/chNNN.slop-patch.md` | 0.2 |
| **CharacterGuard** | chNNN.md + characters.yaml + 历史摘要 | `fixes/chNNN.char-patch.md` | 0.2 |

---

## 对应 5 大 Agent 搭建难题

| 难题 | 出处 | 本项目对策 |
|---|---|---|
| ① 反复失败、无反馈链路 | Anthropic | 所有 Agent 无状态，失败写入 `issues.jsonl` + `debt.jsonl`，下一轮 Fixer 从文件读重新进入干净会话 |
| ② 自评偏乐观 | Anthropic | 五个独立 Agent + Evaluator **对抗人设（默认拒稿）** + **结构化 JSON rubric**（18 个 landmine 逐条打分，必须给原文证据） |
| ③ Context Anxiety | Cognition | 每次调用都是 **fresh window** + 只读它需要的 1-2 个文件。Summarizer **独立会话**，只读最终章节正文，不读 plan/issues（防止 framing 后门泄漏） |
| ④ AI Slop | OpenAI Codex | `rules/*.md` 是黄金原则。每章跑完自动触发 2 个后台 Auditor，产出独立 `fixes/*.patch.md`。Evaluator 2 次 retry 仍不过 → `shipped_with_debt`，技术债进 `debt.jsonl`，每天还一点 |
| ⑤ 规则百科病 | OpenAI | `AGENTS.md` **只 70 行目录页**，详细拆到 `rules/` 5 个子文档。每个 Agent 只加载它需要的那 1-2 份 |

---

## 如何跑

```bash
# 1. 克隆 + 环境
git clone https://github.com/<your-user>/blackboard-novel-pipeline.git
cd blackboard-novel-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置 LLM
cp .env.example .env
# 打开 .env，填入 DEEPSEEK_API_KEY（EasyClaw 平台的 DeepSeek-V4-Pro 代理）

# 3. 初始化黑板（写入大纲、人物、时间线）
python -m src.bootstrap

# 4. 跑流水线
python -m src.pipeline --chapter 1     # 一章
python -m src.pipeline --range 1-3     # 三章
python -m src.pipeline --audit-only 1  # 只跑审计

# 5. 打开 Web 演示
flask --app web.app run --port 5055    # macOS 的 5000 被 AirPlay 占，用 5055
# 浏览器打开 http://localhost:5055/
```

---

## 项目结构

```
blackboard-novel-pipeline/
├── AGENTS.md                 # 70 行目录页（Lesson 5）
├── README.md                 # 本文件
├── requirements.txt
├── .env.example
│
├── rules/                    # 黄金原则（Lesson 4）
│   ├── 24-iron-laws.md       #   Evaluator + Fixer 引用
│   ├── 18-landmines.md       #   Evaluator 全部 + AISlopGuard 子集
│   ├── writing-style.md      #   Generator + Fixer
│   ├── era-1983-hk.md        #   Generator 场景取样
│   └── characters-canon.md   #   所有 Agent 共读
│
├── src/
│   ├── config.py             # 环境变量 + 路径
│   ├── llm.py                # OpenAI 兼容 chat() + 自动写 prompts_log.jsonl
│   ├── blackboard.py         # 原子写 / jsonl 追加 / yaml 读写
│   ├── bootstrap.py          # 种大纲+人物+时间线
│   ├── pipeline.py           # 主循环：plan→gen→eval↔fix→sum→fan-out
│   ├── agents/               # 5 个主 Agent
│   └── auditors/             # 2 个后台 Auditor
│
├── web/
│   ├── app.py                # Flask 9 个路由
│   ├── templates/index.html
│   └── static/{main.css, main.js}
│
├── tests/test_blackboard.py
├── docs/                     # 参考资料 + 设计文档
│   └── superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md
│
└── state/                    # 运行时产物（.gitignore，演示用 demo_snapshot/ 另存）
    ├── outline.json
    ├── timeline.yaml
    ├── characters.yaml
    ├── progress.json
    ├── chapters/chNNN.md, .plan.json, .verdict.json
    ├── summaries/chNNN.md
    ├── fixes/chNNN.*-patch.md
    ├── issues.jsonl
    ├── debt.jsonl
    └── prompts_log.jsonl      # 每次 LLM 调用的完整记录（Inspector 数据源）
```

---

## Web UI 三面板

- **左**：`state/` 文件树实时刷新。点任意文件 → 右侧显示。
- **中**：当前章节 Markdown 渲染 / Debt 表格 / Rules 浏览。
- **右 · Prompt Inspector**（**pitch 武器**）：每次 LLM 调用的完整记录，按时间倒序。每条卡片色彩标注 Agent 身份，展开后看到：
  - `inputs_read` — 这次调用读了哪几个文件（可点击联动左侧）
  - 完整 `system` prompt
  - 完整 `user` prompt
  - 完整 `output`
  - `📋 Fresh context · N tokens — 这次调用没有任何继承上下文`
- **顶部按钮**：生成下一章 / 重审当前章 / 刷新（后两者演示：进程可重启，状态从文件恢复——reload 即 Context Reset 的隐喻；真正的进程级 reset 见 `python -m src.pipeline --chapter N` CLI）

---

## 技术栈

- Python 3.11+
- `httpx` — LLM 客户端（无 SDK，OpenAI 兼容）
- `flask` — 演示 Web
- `pyyaml` — 黑板存储
- `python-dotenv` — 配置
- 无 Agent 框架（LangChain/CrewAI/AutoGen 都不用）

**LLM**：DeepSeek-V4-Pro（EasyClaw 平台提供的 OpenAI 兼容代理）

---

## 测试

```bash
python -m pytest tests/ -v
```

当前测试：黑板的原子写、jsonl 顺序保证、YAML 往返（`tests/test_blackboard.py`，6 个用例）。**覆盖范围仅限 `src/blackboard.py`**——Agent 和 Pipeline 通过端到端运行验证，不另写单元测试。小说 Agent 的单元测试意义不大，输出质量必须人看（见 `demo_snapshot/` 下 3 章实测产出）。

---

## 设计文档

完整的架构分析、Agent 选型决策树、5 大难题硬对应表、60 秒 pitch 脚本：

**[docs/superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md](docs/superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md)**

架构经过 Oracle 子 Agent 独立审核，采纳了 3 条关键修改：
1. 加 Summarizer 独立角色（防 Lesson 3 summary 后门泄漏）
2. Auditor 从 4 砍到 2（聚焦 AI 味 + 人设，删掉 TimelineGuard + FactGuard）
3. 失败 2 次后 `shipped_with_debt`（本身就是 Lesson 4 的现身说法）

---

## 许可

MIT. 此项目为黑客松参赛作品，所有代码可自由使用。

人物档案中「霍官泰」「李超人」「邵老板」「包船王」等是对真实历史人物的代指化处理，避免名誉权问题。事件与时间线基于 1983-1985 真实香港公开史料。
