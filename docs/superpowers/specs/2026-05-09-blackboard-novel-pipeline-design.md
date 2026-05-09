# Blackboard Novel Pipeline — 设计文档

> **项目代号**：`blackboard-novel-pipeline`
> **参赛赛事**：傅盛 AI 战队青少年黑客松（2026）
> **主题**：打造你的多 Agent AI 数字团队
> **截止**：2026-05-10 23:59 北京时间
> **应用场景**：港综同人小说长链路写作流水线

---

## 0. 一句话说明

把 Anthropic / Cognition / OpenAI 在长链路 Agent 上踩过的 5 个坑（自评偏乐观、Context Anxiety、AI Slop、AGENTS.md 百科病、缺反馈回路）**当作架构约束**，设计一个能稳定产出连贯港综小说章节的多 Agent 流水线，并把"怎么规避这些坑"变成可在 60 秒内演示出来的 UI 行为。

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
| **Generator** | ✓ | `chapters/chNNN.plan.json`, `characters.yaml`, `rules/writing-style.md`, 最近 1 份 summary | `chapters/chNNN.md`（~3000 字） | temp=0.85 |
| **Evaluator** | ✓ | `chapters/chNNN.md`, `characters.yaml`, `timeline.yaml`, `rules/18-landmines.md` | `chapters/chNNN.verdict.json`（rubric + 证据 + 硬伤列表）；issues → `issues.jsonl` | temp=0.0 + 对抗人设 |
| **Fixer** | ✓ | `chapters/chNNN.md`, 对应的 issues | 重写 `chapters/chNNN.md`（就地覆盖） | temp=0.5 |
| **Summarizer** | ✓ | **只**读最终的 `chapters/chNNN.md`（不读 plan/issues） | `summaries/chNNN.md`（≤300 字） | temp=0.2 |

### 后台 Auditor（2 个，Fan-Out 并行）

| Auditor | 检查内容 | 独立会话 | 产出 |
|---|---|---|---|
| **AISlopGuard** | AI 味、流水账、形容词堆砌、"了"字过多、机械排比 | ✓ | `fixes/chNNN.slop-patch.md`（diff 思路 + 重写建议段） |
| **CharacterGuard** | 人设前后一致性、双标、圣母心、降智、反派降智 | ✓ | `fixes/chNNN.char-patch.md` |

**奥卡姆剃刀**：原设计里有 TimelineGuard 和 FactGuard，被砍掉。原因：
- 3 章 MVP 上时间线/事实冲突的概率极低（预设好 `era-1983-hk.md` 就够）
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
blackboard-novel-pipeline/
├── AGENTS.md                      # 80 行索引（目录页，Lesson 5）
├── README.md                      # 项目介绍 + 如何跑
├── requirements.txt
├── .env.example                   # DeepSeek API key 占位
│
├── docs/
│   ├── Agent 搭建难题.md         # 原参考资料
│   ├── ai 小说流水线教程贴.txt    # 原参考资料
│   └── superpowers/specs/
│       └── 2026-05-09-blackboard-novel-pipeline-design.md   # 本文件
│
├── rules/                         # 黄金原则（Lesson 4 + Lesson 5）
│   ├── 24-iron-laws.md           # 24 条铁律
│   ├── 18-landmines.md           # 18 个雷点
│   ├── writing-style.md          # 六步人物分析 + 代入感六支柱 + Show-not-tell
│   ├── era-1983-hk.md            # 1983 香港背景事实包
│   └── characters-canon.md       # 人物设定
│
├── src/
│   ├── __init__.py
│   ├── llm.py                    # DeepSeek OpenAI 兼容客户端封装
│   ├── blackboard.py             # state/ 读写接口（原子写+jsonl 追加）
│   ├── agents/
│   │   ├── planner.py
│   │   ├── generator.py
│   │   ├── evaluator.py
│   │   ├── fixer.py
│   │   └── summarizer.py
│   ├── auditors/
│   │   ├── ai_slop_guard.py
│   │   └── character_guard.py
│   ├── pipeline.py               # 主循环：plan→gen→eval→fix→sum→fan-out-audit
│   └── bootstrap.py              # 预置 outline + characters + rules 初始化 state/
│
├── web/                          # Flask 演示页
│   ├── app.py
│   ├── templates/index.html
│   └── static/main.css, main.js
│
├── state/                        # 运行时产物（.gitignore）
│   ├── outline.json
│   ├── timeline.yaml
│   ├── characters.yaml
│   ├── progress.json
│   ├── chapters/chNNN.md
│   ├── summaries/chNNN.md
│   ├── fixes/chNNN.*-patch.md
│   ├── issues.jsonl
│   ├── debt.jsonl
│   └── prompts_log.jsonl        # 每次 LLM 调用的完整 prompt+output（Inspector 用）
│
└── tests/
    └── test_blackboard.py
```

---

## 6. Web 演示页（60 秒 pitch 的核心武器）

**三面板布局**：

- **左**：`state/` 文件树浏览器。实时刷新。点文件 → 右侧主区展示内容。演示"状态外化到文件"。
- **中**：当前章节全文 + 下方 `debt.jsonl` 表格（每行一个未解决问题，带章节号和严重度）。演示"带债上线"=Lesson 4。
- **右（可切换 tab）**：
  - **Prompt Inspector**：`prompts_log.jsonl` 的时间线视图。每条记录包含：调用时间、agent 名、输入文件列表、完整 system prompt、完整 user prompt、output、用时、token 数。这是演示"Context Reset + 独立会话"的决定性证据。
  - **Agent Log**：简洁的 role 色彩流水日志。

**顶部按钮**：
- `生成下一章` — 触发一次完整流水线
- `全量审计` — 对所有已生成章节跑一遍 Auditor
- `重置并续写` — 删除内存进程，重新起 Python 进程，从 `state/progress.json` 恢复（**现场演示 Context Reset**）

---

## 7. MVP 范围（≤24h 可交付）

### ✅ 必做

- [ ] 5 个 Agent + 2 个 Auditor 全部实现
- [ ] 预置港综大纲（1983 年香港起步，主角背景 + 金手指 + 前 5 章节拍表）
- [ ] `AGENTS.md` + 5 份 `rules/*.md`
- [ ] **真实产出前 3 章**（每章 ~3000 字，总计 ~9000 字，完整走过 plan→gen→eval→fix→sum→audit）
- [ ] Flask Web 三面板（文件树 / 当前章节+debt / Prompt Inspector）
- [ ] `README.md` 说明怎么跑
- [ ] 部署到公网（Vercel 或 Railway，黑客松要求公网演示）

### ❌ 不做（YAGNI）

- 真写 800 章
- 用户登录/多用户
- 数据库（全文件）
- TimelineGuard + FactGuard（砍）
- 流式 UI / WebSocket（polling 即可）
- 真 Git PR 集成（用 `.patch.md` 文件模拟）

### 风险 & 兜底

| 风险 | 兜底 |
|---|---|
| DeepSeek API 波动 | `.env` 里保留 fallback OpenAI key（若用户提供） |
| 一次跑 3 章 >10 分钟 | 提前跑一遍，成品章节 checked-in 到 `state/` 里；Web 页上的"生成"按钮只演示流水线，不阻塞 |
| 部署不通过 | 本地 `python -m web.app` + ngrok/cloudflared 隧道 |
| ZIP > 10MB | 删 `state/prompts_log.jsonl` 历史，只保留最近 1 章 |

---

## 8. 评委 60 秒 pitch 脚本

> "**1983 年的香港，主角要白手起家。** 但这本小说不是一个 AI 从头写到尾的——它是五个 Agent 轮流工作，加两个后台审计员。
>
> **（切到 Prompt Inspector）** 看这里。每个 Agent 调用都是 fresh context，只读几个它要的文件，**不继承前一个 Agent 的思考**。这是 Anthropic 的 "Planner/Generator/Evaluator 三角" 的工程化落地。
>
> **（切到 state/ 文件树）** 所有状态都沉在文件里。**（点'重置并续写'按钮）** 看——Python 进程死了，新进程起来，从 `progress.json` 读到第几章，继续。这就是 Cognition 说的 Context Reset，不是 context compression。
>
> **（切到 debt.jsonl）** 这是技术债。有些问题 Fixer 两次没改好，就带伤上线，写到 debt 里。后台审计员每天扫一次，找个轻的时候再修。OpenAI 在 Codex 项目里就是这么干的。
>
> 代码 2000 行出头，没用任何 Agent 框架。"

---

## 9. 交付清单

- [ ] 本设计文档（已提交 git）
- [ ] GitHub 公开仓库
- [ ] Flask 可部署到公网的 demo 站
- [ ] 演示视频（≤2 分钟）或运行截图，作为第 1、2 个补充链接
- [ ] 代码 ZIP ≤ 10MB
- [ ] EasyClaw 平台报名表提交

---

**文档版本**：v1.0（2026-05-09 完成架构评审 by Oracle subagent）
