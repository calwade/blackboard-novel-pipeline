# AGENTS.md

> 目录页，不是百科全书。每个 Agent 只加载自己需要的那一份规则。
> — Lesson 5 from OpenAI Codex post-mortem

## 项目目标

多 Agent 港综同人小说写作流水线。外层 Pipeline + 内层 Blackboard + Auditor Fan-Out + Evaluator 半 Debate。

## 如何运行

```
cp .env.example .env           # 填入 DEEPSEEK_API_KEY
pip install -r requirements.txt
python -m src.bootstrap         # 初始化 state/ 黑板
python -m src.pipeline --range 1-3   # 跑前三章
flask --app web.app run --port 5000  # 启动演示页
```

## 架构 1 行说明

每个 Agent = 一次独立 LLM 调用 + 独立 system prompt + 只读它需要的 state/ 文件。详见 [docs/superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md](docs/superpowers/specs/2026-05-09-blackboard-novel-pipeline-design.md)。

## State 目录地图

| 路径 | 内容 |
|---|---|
| `state/outline.json` | 整本小说大纲 + 每章节拍 |
| `state/timeline.yaml` | 1983-1984 历史时间线 |
| `state/characters.yaml` | 人物档案副本（来源 rules/characters-canon.md） |
| `state/progress.json` | 当前章节、已完成章节、运行中状态 |
| `state/chapters/chNNN.md` | 第 N 章正文（Generator/Fixer 写） |
| `state/chapters/chNNN.plan.json` | 第 N 章节拍表（Planner 写） |
| `state/chapters/chNNN.verdict.json` | 第 N 章 Evaluator 判词 |
| `state/summaries/chNNN.md` | 第 N 章摘要（Summarizer 独立会话产出） |
| `state/fixes/chNNN.slop-patch.md` | AI 味审计产物 |
| `state/fixes/chNNN.char-patch.md` | 人设审计产物 |
| `state/issues.jsonl` | 待修问题日志（Evaluator 追加） |
| `state/debt.jsonl` | 带伤上线的技术债（2 次 retry 仍不过的问题） |
| `state/prompts_log.jsonl` | 每次 LLM 调用的完整记录（Prompt Inspector 数据源） |

## Agent 名册

| Agent | 读 | 写 | Temp | 核心 Prompt 要点 |
|---|---|---|---|---|
| Planner | outline + progress + 最近 2 summary | chNNN.plan.json | 0.4 | 责编视角，输出严格 JSON |
| Generator | plan + characters + rules/writing-style | chNNN.md (~3000字) | 0.85 | Show-Don't-Tell，禁 AI 味 |
| Evaluator | chNNN.md + rules/18-landmines | verdict.json + issues.jsonl | 0.0 | 对抗人设，默认拒稿，JSON rubric |
| Fixer | chNNN.md + verdict.top_3_fixes | 覆写 chNNN.md | 0.5 | 只修不重写 |
| Summarizer | chNNN.md **（不读 plan/issues，防止 framing 泄漏）** | summaries/chNNN.md | 0.2 | 客观白描 |
| AISlopGuard | chNNN.md + 摘取 18-landmines 中 AI 味条目 | fixes/chNNN.slop-patch.md | 0.2 | 只报 AI 味相关问题 |
| CharacterGuard | chNNN.md + characters.yaml + 历史 summaries | fixes/chNNN.char-patch.md | 0.2 | 只报人设偏移 |

## 规则索引（Progressive Disclosure）

规则分散在 `rules/` 下。Agent 只加载它需要的那 1-2 份：

| 文件 | 谁用 |
|---|---|
| `rules/24-iron-laws.md` | Evaluator, Fixer |
| `rules/18-landmines.md` | Evaluator（全）, AISlopGuard（AI味子集） |
| `rules/writing-style.md` | Generator, Fixer |
| `rules/era-1983-hk.md` | Generator（场景取样） |
| `rules/characters-canon.md` | 所有 Agent |

## 故障排查

- **Agent 反复失败** → 不要在 prompt 上打补丁。读 `state/debt.jsonl` 和 `state/prompts_log.jsonl`，先定位能力缺口，再决定是"补工具/补规则/补语料"。**重启胜过修补**（Lesson 1）。
- **章节跑飞或越写越偏** → 检查 `summaries/*.md` 是否被 Generator 污染（本应只由 Summarizer 独立产出）。这是 Lesson 3 的典型泄漏点。
- **生成质量变差** → 打开 Web UI 的 Prompt Inspector，对比相邻两次 Generator 的 system prompt 和 inputs_read。任何两次调用的上下文必须各自独立、不应出现跨章累积。
