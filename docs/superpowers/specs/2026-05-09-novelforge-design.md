# Novelforge — 架构设计

> **项目代号**：`novelforge`
> **定位**：通用多 Agent 小说写作流水线
> **核心决策**：题材通过 Setting Pack 注入，`src/` 对题材无感知

---

## 0. 一句话说明

把 Anthropic / Cognition / OpenAI 在长链路 Agent 上踩过的 5 个坑（自评偏乐观、Context Anxiety、AI Slop、AGENTS.md 百科病、缺反馈回路）**当作架构约束**，设计一个能稳定产出连贯小说章节的多 Agent 流水线。

流水线本身对题材完全无知，具体题材（港综、仙侠、都市、赛博……）通过 **Setting Pack** 注入（见第 7 节）。

**当前阶段 / 演进路线**：本文档描述系统的**架构骨架**。骨架已落地（7 Agent + 2 题材各 3 章产出）。从 MVP 升级到"大而全通用系统"的 gap 分析、补齐清单与优先级路线图见 [`docs/gap-analysis-post-mvp.md`](../../gap-analysis-post-mvp.md)。

---

## 1. 架构：三层嵌套

### 模式选型决策树（复盘）

| 问题 | 答案 | 选定模式 |
|---|---|---|
| 任务能否分解成固定步骤？ | 一章内线性有序，整本书是章节串行 | **外层 Pipeline**（模式 6） |
| 质量 vs 成本？ | 质量第一 | **Evaluator 半 Debate**（模式 8） |
| Agent 数量 & 耦合度 | 5-7 个，松耦合 | **内层 Blackboard**（模式 7） |
| Auditor 是否并行？ | 2 个审计独立，可并行 | **Fan-Out**（模式 2） |
| 异构 Agent 池？ | 否，同模型不同 prompt/temp | 不用 Market / Pool |

### 架构示意

```
外层（宏观）：Pipeline — 章节线性推进
  chapter[i] ─→ chapter[i+1] ─→ chapter[i+2] ...

每章内部（微观）：Blackboard — state/ 是唯一共享媒介
  所有 Agent 无状态，仅通过读写文件通信

  ┌──── state/ （黑板） ────┐
  │ outline.json            │
  │ timeline.yaml           │
  │ characters.yaml         │
  │ chapters/chNNN.md       │
  │ chapters/chNNN.plan.json│
  │ summaries/chNNN.md      │
  │ issues.jsonl            │
  │ debt.jsonl              │
  │ fixes/chNNN.*-patch.md  │
  │ progress.json           │
  └────────────▲────────────┘
               │
       ┌───────┼───────┐
       ▼       ▼       ▼
   Planner  Generator  Evaluator (对抗人设 + JSON rubric)
                              │
                              ▼
                           Fixer (≤2 次 retry)
                              │
                     ┌────────┴────────┐
                     ▼                 ▼
                  通过             2 次仍不过
                     │                 │
                     ▼                 ▼
                Summarizer     debt.jsonl 记债
                     │          （Lesson 4 具身化）
                     ▼
        ┌─────── Fan-Out 并行 ────────┐
        ▼                             ▼
    AISlopGuard                  CharacterGuard
    (独立会话，只读 chNNN.md)    (同上)
        │                             │
        ▼                             ▼
    fixes/chNNN.slop-patch.md    fixes/chNNN.char-patch.md
    (可选应用)                    (可选应用)
```

---

## 2. 5 大难题 ↔ 架构落点（硬对应）

| 难题 | 《Agent 搭建难题.md》摘录 | 本项目落地 |
|---|---|---|
| ① Agent 反复失败 | "看环境里缺了什么能力然后补进去；重启胜过修补，状态沉到文件里" | 所有 Agent 无状态，全部通过 `state/` 通信。失败 → `issues.jsonl` + `debt.jsonl`，下一次 Fixer 读文件重新进入干净会话 |
| ② 自评偏乐观 | "让干活的和验收的必须是不同的人" | Planner / Generator / Evaluator / Fixer / Summarizer **五个独立会话**，各自有**不同 system prompt**。Evaluator 拿 **对抗人设** + **JSON 结构化 rubric**，看不到 Generator 的推理过程 |
| ③ Context Anxiety | "Context Reset：直接丢掉旧窗口，新窗口从文件读进度" | 每次调用都是 fresh window + 只读它需要的 1-2 个文件。生成第 N 章时，Planner 只读 outline 相关条目 + 最近 2 章的 **Summarizer 产物**（绝非全文）。**Summarizer 由独立 Agent 产出**（防止 Generator framing 从 summary 后门泄漏） |
| ④ AI Slop | "把工程师经验写成黄金原则沉进仓库，后台 Agent 按节奏扫描自动开修复 PR" | `rules/24-iron-laws.md` + `rules/18-landmines.md` 是黄金原则。每章生成后 AISlopGuard / CharacterGuard **并行独立扫描**，输出独立补丁文件 `fixes/chNNN.*-patch.md`（类 PR），用户/Fixer 决定是否应用 |
| ⑤ 规则百科病 | "AGENTS.md 从百科变目录页，详细拆到子文档" | 根目录 **`AGENTS.md` ≤ 100 行** 纯索引，指向 `rules/*.md`。每个 Agent 只在 system prompt 里加载自己需要的那 1-2 份规则文件 |

---

## 3. Agent 清单

### 主流水线 Agent（5 个）

| Agent | 独立会话？ | 读取文件 | 产出文件 | 模型参数 |
|---|---|---|---|---|
| **Planner** | ✓ | `outline.json`, `progress.json`, 最近 2 份 `summaries/chNNN.md` | `chapters/chNNN.plan.json`（本章节拍表） | temp=0.4 |
| **Generator** | ✓ | `chapters/chNNN.plan.json`, `characters.yaml`, `setting.yaml`, `era.md`, `writing-style-extra.md`, `rules/writing-style-core.md`, 最近 1 份 summary | `chapters/chNNN.md`（~3000 字） | temp=0.85 |
| **Evaluator** | ✓ | `chapters/chNNN.md`, `characters.yaml`, `timeline.yaml`, `rules/18-landmines.md` | `chapters/chNNN.verdict.json`（rubric + 证据 + 硬伤列表）；issues → `issues.jsonl` | temp=0.0 + 对抗人设 |
| **Fixer** | ✓ | `chapters/chNNN.md`, 对应的 issues | 重写 `chapters/chNNN.md`（就地覆盖） | temp=0.5 |
| **Summarizer** | ✓ | **只**读最终的 `chapters/chNNN.md`（不读 plan/issues） | `summaries/chNNN.md`（≤300 字） | temp=0.2 |

### 后台 Auditor（2 个，Fan-Out 并行）

| Auditor | 检查内容 | 独立会话 | 产出 |
|---|---|---|---|
| **AISlopGuard** | AI 味、流水账、形容词堆砌、"了"字过多、机械排比 | ✓ | `fixes/chNNN.slop-patch.md`（diff 思路 + 重写建议段） |
| **CharacterGuard** | 人设前后一致性、双标、圣母心、降智、反派降智 | ✓ | `fixes/chNNN.char-patch.md` |

**奥卡姆剃刀**：原设计里有 TimelineGuard 和 FactGuard，被砍掉。原因：
- 3 章 MVP 上时间线/事实冲突的概率极低（setting pack 里的 `era.md` 预设好就够）
- 活爬网费钱且易超时
- Oracle 建议聚焦最能打动评委的 2 个

---

## 4. 关键细节设计

### 4.1 Evaluator 去乐观化（半 Debate）

**对抗人设**（system prompt 核心片段）：

> 你是一个以刁钻著称的资深网文主编，以拒稿为默认选项。读稿件时要求你找出至少 3 处硬伤——哪怕文字再好，如果你找不出 3 处问题就是你失职。你只看稿件本身，不信任任何"作者本意"。

**结构化 rubric**（输出 JSON 格式，无自由发挥空间）：

```json
{
  "overall_pass": false,
  "landmines": {
    "ai_flavor":     {"hit": true,  "evidence": "第3段连续4个四字成语堆砌", "severity": "medium"},
    "character_ooc": {"hit": false, "evidence": null, "severity": null},
    "timeline":      {"hit": false, "evidence": null, "severity": null},
    "weak_hook":     {"hit": true,  "evidence": "章末没有悬念，直接收尾", "severity": "high"},
    ...共 18 条雷点
  },
  "top_3_fixes": [
    {"where": "第3段", "what": "改写四字成语堆砌为动词+具体细节"},
    {"where": "章末", "what": "补一个钩子，可用 XX 角色的突然出现"}
  ]
}
```

这种结构化输出是**对抗乐观偏差最便宜也最有效**的手段。

### 4.2 Fixer 失败兜底

```python
for attempt in range(2):
    fixer.run(chapter, issues)
    verdict = evaluator.run(chapter)
    if verdict.overall_pass:
        break
else:
    # 2 次仍不过：带债上线，不死循环
    progress["chapters"][N]["status"] = "shipped_with_debt"
    with open("state/debt.jsonl", "a") as f:
        f.write(json.dumps(verdict.landmines) + "\n")
```

Oracle 点评："带伤上线"恰好 **现身说法 Lesson 4**（技术债不攒着等，每天还一点）—— 写进 debt.jsonl，后续 Auditor 下一轮可以重开。

### 4.3 Context Reset 具身化

每个 Agent 调用都用独立 Python 函数 + 独立 httpx client + 独立 `messages` 数组。没有跨调用的 memory。这个"无状态"通过 **Web UI 的 Prompt Inspector** 可直接可视化：

> 点任意 Agent 调用 → 看到完整发送的 prompt（约 1-3k token，不是几十 k 累积历史）+ 读了哪几个文件 + 完整 output。

这是把"架构上有" **变成** "60 秒内演得出"的核心手段。

---

## 5. 文件结构

```
novelforge/
├── AGENTS.md                      # 80 行索引（目录页，Lesson 5）
├── README.md                      # 项目介绍 + 如何跑
├── requirements.txt
├── .env.example                   # DeepSeek API key 占位
│
├── docs/
│   ├── Agent 搭建难题.md         # 原参考资料
│   ├── ai 小说流水线教程贴.txt    # 原参考资料
│   └── superpowers/specs/
│       └── 2026-05-09-novelforge-design.md   # 本文件
│
├── rules/                         # 通用黄金原则（题材无关, Lesson 4 + Lesson 5）
│   ├── 24-iron-laws.md            # 24 条通用铁律
│   ├── 18-landmines.md            # 18 个通用雷点
│   └── writing-style-core.md      # 通用写作风格（六步人物分析 + 代入感六支柱 + Show-Don't-Tell）
│
├── settings/                      # 题材包（Setting Pack）—— 流水线对题材解耦
│   ├── README.md                  # 怎么新增一个题材
│   ├── gangster-hk-1983/          # 示例：港综 1983（7 文件）
│   │   ├── setting.yaml
│   │   ├── outline.json
│   │   ├── timeline.yaml
│   │   ├── characters.yaml
│   │   ├── era.md
│   │   ├── writing-style-extra.md
│   │   └── iron-laws-extra.md
│   └── xianxia-ascension/         # 示例：仙侠飞升（同样 7 文件，证明架构通用）
│
├── src/
│   ├── __init__.py
│   ├── config.py                 # 环境变量 + 路径
│   ├── llm.py                    # DeepSeek OpenAI 兼容客户端封装
│   ├── blackboard.py             # state/ 读写接口（原子写+jsonl 追加）
│   ├── agents/
│   │   ├── _base.py
│   │   ├── planner.py
│   │   ├── generator.py
│   │   ├── evaluator.py
│   │   ├── fixer.py
│   │   └── summarizer.py
│   ├── auditors/
│   │   ├── ai_slop_guard.py
│   │   └── character_guard.py
│   ├── pipeline.py               # 主循环：plan→gen→eval→fix→sum→fan-out-audit
│   └── bootstrap.py              # --setting <name> 把 setting pack 拷入 state/
│
├── web/                          # Flask 演示页
│   ├── app.py
│   ├── templates/index.html
│   └── static/main.css, main.js
│
├── docs/                         # GitHub Pages 静态演示 + 设计文档
│   ├── index.html + main.js + main.css   # 静态只读版
│   └── superpowers/specs/
│       └── 2026-05-09-novelforge-design.md   # 本文件
│
├── docs/demo_snapshot/           # 港综 setting 3 章完整跑出的产物（Pages 数据源）
│                                  # 注：2026-05-11 前此目录位于根目录，已移至 docs/
│
├── state/                        # 运行时产物（.gitignore）
│   ├── setting.yaml              # 当前激活的 setting（bootstrap 从 setting pack 拷入）
│   ├── outline.json              # 来自 setting
│   ├── timeline.yaml             # 来自 setting
│   ├── characters.yaml           # 来自 setting
│   ├── era.md                    # 来自 setting
│   ├── writing-style-extra.md    # 来自 setting
│   ├── iron-laws-extra.md        # 来自 setting
│   ├── progress.json
│   ├── chapters/chNNN.{md,plan.json,verdict.json}
│   ├── summaries/chNNN.md
│   ├── fixes/chNNN.*-patch.md
│   ├── issues.jsonl
│   ├── debt.jsonl
│   └── prompts_log.jsonl         # 每次 LLM 调用的完整记录（Inspector 用）
│
└── tests/
    └── test_blackboard.py
```

---

## 6. Setting System

原本的设计把"港综 1983"硬编码到 `rules/`、`src/agents/*.py` 与文档中。
架构审查阶段识别到这违反了"通用多 Agent 团队"的初衷：架构与具体题材未分离。

### 6.1 分层

```
通用层（题材无关）             题材层（setting pack）
──────────────────             ────────────────────
rules/24-iron-laws.md          settings/<name>/
rules/18-landmines.md            setting.yaml
rules/writing-style-core.md      outline.json
                                 timeline.yaml
src/agents/*.py                  characters.yaml
src/auditors/*.py                era.md
src/pipeline.py                  writing-style-extra.md
src/blackboard.py                iron-laws-extra.md
src/llm.py
AGENTS.md
```

### 6.2 激活流程

```
python -m src.bootstrap --setting <name>
```

把 `settings/<name>/` 的 7 个文件拷贝到 `state/`。Agent 只读 `state/`，跟题材解耦。

### 6.3 Agent 如何读题材内容

| Agent | 通用读 | 题材读 |
|---|---|---|
| Planner | outline.json + setting.yaml（genre/era 元信息） | — |
| Generator | rules/writing-style-core.md | state/setting.yaml + state/era.md + state/writing-style-extra.md + state/characters.yaml |
| Evaluator | rules/24-iron-laws.md + rules/18-landmines.md | state/iron-laws-extra.md + state/characters.yaml + state/timeline.yaml |
| Fixer | rules/writing-style-core.md | state/writing-style-extra.md |
| Summarizer | — | state/chapters/chNNN.md（仅正文） |
| AISlopGuard | (AI-slop 子集内嵌在 auditor 的 prompt 里，通用) | — |
| CharacterGuard | — | state/characters.yaml + 历史摘要 |

### 6.4 切题材零代码修改

```bash
python -m src.bootstrap --setting gangster-hk-1983
python -m src.pipeline --chapter 1
# ...
python -m src.bootstrap --setting xianxia-ascension
python -m src.pipeline --chapter 1
```

### 6.5 内置示例

| Setting | 状态 |
|---|---|
| `gangster-hk-1983` | 完整运行过 3 章，产出在 `docs/demo_snapshot/` |
| `xianxia-ascension` | 完整运行过 3 章，产出在 `docs/demo_snapshot_xianxia/` |

---

## 7. Web UI（`web/` + `docs/`）

系统提供两套 UI，共享大部分组件：

- **`web/` · Flask 动态版**：读本地实时 `state/`，轮询刷新。按钮触发 `POST /api/run` 调用 pipeline，LLM 实时跑。需要本地 Python 环境 + API Key。
- **`docs/` · 静态只读版**：纯 HTML/CSS/JS，GitHub Pages 托管。数据从 `docs/demo_snapshot*/` 加载（2026-05-11 起三份 snapshot 全部接入）。操作按钮永久 disabled。供公网评估查阅。

两套 UI 的**三面板结构一致**：

- **左**：`state/` 文件树，点击跳到中间面板
- **中**：章节 Markdown / Debt 表格 / Rules 浏览
- **右**：`Prompt Inspector`（LLM 调用时间线，关键）/ `Log`（密集流水日志）/ `Lessons`（5 大难题 ↔ 代码指针 crosswalk）

关键 UI 功能由架构诉求反推：Prompt Inspector 是"每次调用 fresh context"的可视证据；文件树 + 状态 pill 是"状态外化到文件"的可视证据；Debt Tab 是 Lesson 4 "带债上线"的可视产物。

---

## 演进状态与路线图

本文档描述**架构骨架**。从 3 章 MVP 到"大而全通用系统"的 gap 清单、优先级、工时估算与第一周行动项，见：

- [`docs/gap-analysis-post-mvp.md`](../../gap-analysis-post-mvp.md) —— 第三轮 Oracle 评审。MoSCoW 清单：9 Must / 18 Should / 4 Could / 7 Won't，总工时约 155h。
- [`docs/tutorial-borrowings-audit.md`](../../tutorial-borrowings-audit.md) —— 教程贴 108 条 ↔ 系统落点的逐条审计。

---

**文档版本历史**：
- 初版（2026-05-09）—— 架构评审 by Oracle subagent。采纳 3 条修改：独立 Summarizer、Auditor 从 4 砍到 2、加 Prompt Inspector UI。
- 重构（2026-05-09）—— Oracle 后评审发现架构与题材未分离。抽 `settings/` 系统，加 `xianxia-ascension` 作为第二示例；Evaluator 加 skeleton detector；AISlopGuard 改写质量收紧；UI 加 Lessons Map 面板。
- 精简（2026-05-10）—— 清理 MVP 交付话术与黑客松 pitch 章节，以符合"通用系统"定位。演进路线外移到 `docs/gap-analysis-post-mvp.md`。
