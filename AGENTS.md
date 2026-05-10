# AGENTS.md

> 目录页，不是百科全书。每个 Agent 只加载自己需要的那 1-2 份规则。
> — Lesson 5 from OpenAI Codex post-mortem

## 项目目标

**通用多 Agent 小说写作流水线**。外层 Pipeline + 内层 Blackboard + Auditor Fan-Out + Evaluator 半 Debate。

题材通过 **Setting Pack** 注入（见 `settings/`），流水线本身（`src/`）对题材一无所知。

## 如何运行

```bash
cp .env.example .env                                    # 填入 DEEPSEEK_API_KEY
pip install -r requirements.txt

python -m src.bootstrap --list                          # 看所有可用题材
python -m src.bootstrap --setting gangster-hk-1983      # 激活港综
python -m src.pipeline --range 1-3                      # 跑前三章
flask --app web.app run --port 5055                     # 启动演示页
```

切换题材只需重新 bootstrap，无需改代码：

```bash
python -m src.bootstrap --setting xianxia-ascension     # 切到仙侠
python -m src.pipeline --chapter 1
```

## 架构 1 行说明

每个 Agent = 一次独立 LLM 调用 + 独立 system prompt + 只读它需要的 state/ 文件。详见 [docs/superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md](docs/superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md)。

## Setting 系统

题材包放在 `settings/<name>/`，每个 7 个文件：`setting.yaml` + `outline.json` + `timeline.yaml` + `characters.yaml` + `era.md` + `writing-style-extra.md` + `iron-laws-extra.md`。详见 `settings/README.md`。

`bootstrap` 把选定 setting 的 7 份文件拷入 `state/`，Agent 只读 `state/`，与题材解耦。

内置两个 setting：
- `gangster-hk-1983` —— 港综同人，1983 香港（完整运行过 3 章，产出见 `demo_snapshot/`）
- `xianxia-ascension` —— 仙侠修真，青龙历纪元（结构完整，未跑 LLM 节省 demo token）

## State 目录地图

| 路径 | 内容 | 来源 |
|---|---|---|
| `state/setting.yaml` | 当前激活的 setting 元信息 | 由 bootstrap 从 setting pack 拷入 |
| `state/outline.json` | 整本小说大纲 + 每章节拍 | setting pack |
| `state/timeline.yaml` | 时代/世界观时间线 | setting pack |
| `state/characters.yaml` | 人物档案 | setting pack |
| `state/era.md` | 时代/世界观事实包 | setting pack |
| `state/writing-style-extra.md` | 题材特有风格补充 | setting pack |
| `state/iron-laws-extra.md` | 题材特有铁律 | setting pack |
| `state/progress.json` | 当前章节、已完成章节、运行中状态 | pipeline 运行时更新 |
| `state/current_status_card.md` | **当前时间点唯一的权威状态覆盖文件**（主角状态/敌我/资源/已知真相/活跃伏笔/下一章任务卡）。Context Reset 重建局势的入口 | StatusCardUpdater（每章末尾覆盖式更新） |
| `state/pending_hooks.md` | **待回收伏笔池**（活跃伏笔 + 本章刚回收的伏笔）。Planner 每章必读 | HookKeeper（每章末尾覆盖式更新） |
| `state/resource_schema.yaml` | 题材的**可追踪资源定义**（灵石/情报值/黑金/境界等）。**可选** —— 题材无需则不注入 | setting pack（bootstrap 注入） |
| `state/resource_ledger.md` | 按 schema 记录的资源账本（当前余额 + 本章变动）。仅当 schema 存在时生成 | ResourceLedger（每章末尾覆盖式更新） |
| `state/chapters/chNNN.md` | 第 N 章正文 | Generator / Fixer |
| `state/chapters/chNNN.plan.json` | 第 N 章节拍表 | Planner |
| `state/chapters/chNNN.verdict.json` | 第 N 章 Evaluator 判词 | Evaluator |
| `state/summaries/chNNN.md` | 第 N 章摘要 | Summarizer（独立会话） |
| `state/fixes/chNNN.slop-patch.md` | AI 味审计产物 | AISlopGuard |
| `state/fixes/chNNN.char-patch.md` | 人设审计产物 | CharacterGuard |
| `state/issues.jsonl` | 待修问题日志 | Evaluator 追加 |
| `state/debt.jsonl` | 带伤上线的技术债 | Pipeline（2 次 retry 仍不过） |
| `state/prompts_log.jsonl` | 每次 LLM 调用的完整记录 | llm.chat() 自动写入 |
| `state/packaging.json` | 出版包装产物（书名/简介/封面/标签） | PackagingAgent（独立运行 `--packaging`） |

## Agent 名册

| Agent | 读 | 写 | Temp | 核心 Prompt 要点 |
|---|---|---|---|---|---|
| Planner | outline + 最近 2 summary + setting.yaml + **current_status_card.md** + **pending_hooks.md** | chNNN.plan.json | 0.4 | 责编视角，输出严格 JSON；必读状态卡+伏笔池作为当前权威 |
| Generator | plan + characters + setting.yaml + era + writing-style（core + extra） | chNNN.md (~3000字) | 0.85 | Show-Don't-Tell，禁 AI 味 |
| Evaluator | chNNN.md + 18-landmines + 24-iron-laws（core + extra）+ characters + timeline | verdict.json + issues.jsonl | 0.0 | 对抗人设，默认拒稿，JSON rubric + skeleton detector |
| Fixer | chNNN.md + verdict.top_3_fixes + writing-style（core + extra） | 覆写 chNNN.md | 0.5 | 只修不重写 |
| Summarizer | chNNN.md **（不读 plan/issues，防 framing 泄漏）** | summaries/chNNN.md | 0.2 | 客观白描 |
| **StatusCardUpdater** | chNNN.md + 上一版 current_status_card.md + characters.yaml + setting.yaml | **current_status_card.md**（覆盖式） | 0.2 | Lesson 3：当前时间点唯一快照；读正文，不读 plan/verdict/issues |
| **HookKeeper** | chNNN.md + 上一版 pending_hooks.md + current_status_card.md | **pending_hooks.md**（覆盖式） | 0.2 | 维护活跃伏笔池，回收/新增/推进三操作；只从正文抽取 |
| **ResourceLedger**（可选） | resource_schema.yaml + chNNN.md + 上一版 resource_ledger.md | **resource_ledger.md**（覆盖式） | 0.2 | 仅在 setting 提供 resource_schema.yaml 时运行；监控资源跳数量级 |
| AISlopGuard | chNNN.md + 摘取 AI 味条目 | fixes/chNNN.slop-patch.md | 0.2 | 只报 AI 味相关（moderate/severe） |
| CharacterGuard | chNNN.md + characters.yaml + 历史 summaries | fixes/chNNN.char-patch.md | 0.2 | 只报人设偏移 |
| PackagingAgent | setting.yaml + outline.json + characters.yaml + era.md + ch001.md + 最后章节 | packaging.json | 0.6 | 书名/简介/封面/标签包装，独立运行 `--packaging` |

## 规则索引（Progressive Disclosure）

规则分两层：通用（`rules/`）+ 题材特有（`settings/<name>/` 经 bootstrap 拷入 `state/`）。每个 Agent 只加载它需要的那 1-2 份。

| 文件 | 类型 | 谁用 |
|---|---|---|
| `rules/24-iron-laws.md` | 通用 | Evaluator |
| `rules/18-landmines.md` | 通用 | Evaluator（全）、AISlopGuard（AI 味子集） |
| `rules/writing-style-core.md` | 通用 | Generator、Fixer |
| `state/iron-laws-extra.md` | 题材（setting） | Evaluator |
| `state/writing-style-extra.md` | 题材（setting） | Generator、Fixer |
| `state/era.md` | 题材（setting） | Generator |
| `state/characters.yaml` | 题材（setting） | 所有 Agent |

## 故障排查

- **Agent 反复失败** → 不要在 prompt 上打补丁。读 `state/debt.jsonl` 和 `state/prompts_log.jsonl`，先定位能力缺口，再决定是"补工具/补规则/补语料"。**重启胜过修补**（Lesson 1）。
- **章节跑飞或越写越偏** → 检查 `summaries/*.md` 是否被 Generator 污染（本应只由 Summarizer 独立产出）。这是 Lesson 3 的典型泄漏点。
- **Evaluator 看似通过但 verdict 全空** → 检查 `_skeleton_detected` 字段。Evaluator 返回 JSON 示例骨架时会被 detector 识别并触发 retry，不会静默通过。
- **生成质量变差** → 打开 Web UI 的 Prompt Inspector，对比相邻两次 Generator 的 system prompt 和 inputs_read。任何两次调用的上下文必须各自独立、不应出现跨章累积。
- **切换题材但 Agent 仍然用老题材口吻** → 重新 `python -m src.bootstrap --setting <name>`。检查 `state/setting.yaml` 中 `id` 字段是否为期望的 setting。
