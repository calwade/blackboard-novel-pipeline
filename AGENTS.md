# AGENTS.md

> 目录页，不是百科全书。每个 Agent 只加载自己需要的那 1-2 份规则。
> — Lesson 5 from OpenAI Codex post-mortem

## 项目目标

**Novelforge · 小说锻造厂** — 通用多 Agent 小说写作流水线。外层 Pipeline + 内层 Blackboard + Auditor Fan-Out + Evaluator 半 Debate + Lesson-3 三层 Bookkeeping。

**两层架构**：
- **题材层**（`genres/<genre-id>/`）：描述什么是港综 / 仙侠 / 言情。多本书共享。
- **作品层**（`projects/<project-id>/`）：描述一本具体的小说。每本书独立。

流水线本身（`src/`）对两层都无感知；它只读运行时拷贝过来的 `state/` 目录。

## 如何运行

```bash
cp .env.example .env                                          # 填入 DEEPSEEK_API_KEY
pip install -r requirements.txt

python -m src.bootstrap --list-genres                         # 看所有题材
python -m src.bootstrap --list                                # 看所有作品
python -m src.bootstrap --project gangster-hk-1983-linjiayao  # 激活作品（含 state 初始化）
python -m src.pipeline --range 1-3                            # 跑前三章
flask --app web.app run --port 5055                           # 启动演示页
```

切换作品只需重新 bootstrap，无需改代码：

```bash
python -m src.bootstrap --project xianxia-ascension-peichangning   # 切到仙侠那本
python -m src.pipeline --chapter 1
```

新建一本书（脚手架）：

```bash
python -m src.bootstrap --new-project my-new-book --genre gangster-hk-1983
# 编辑 projects/my-new-book/project.yaml / outline.json / characters.yaml
python -m src.bootstrap --project my-new-book
```

## 题材流水线（Genre Pipeline）

除了作品流水线（每章 Planner→Generator→Evaluator→Fixer→Summarizer），系统还有一条**题材流水线**：用于建 / 补 / 审 / 从已有小说拆解题材包。产物是 `genres/<id>/` 下的 4-5 份文件，跨作品复用。

```bash
# 从零手建（脚手架，不调 LLM）
python -m src.genre_extractor --new-genre <id> --name "..." --era "..."

# 补齐缺失文件（不调 LLM）
python -m src.genre_extractor --fill-genre <id>

# 审查已有题材（Stage 1 结构校验 + Stage 2 LLM 语义）
python -m src.genre_extractor --audit-genre <id>

# 从已有小说拆解题材规范（核心场景）
python -m src.genre_extractor --extract-from-novel <id> \
    --sources novels/a.txt,novels/b.txt [--with-trial]
```

机制要点：
- 复用 `Blackboard` / `BaseAgent`（位于 `src/core/`）
- 滑动窗口 25 章/批，三档自适应（≤50:10 / 51-600:25 / >600:40）
- `genres/<id>/.build/`（进 `.gitignore`）是构建期工作目录：`build_status.yaml` + `extraction_notes/batch-NNN.yaml` + `genre_blueprint.yaml` + `genre_issues.jsonl` + `extraction_tally.md`
- Extractor **两步法**（DSPy TwoStepAdapter 思路）：Step 1 自由笔记（temp 0.3）→ Step 2 verbatim 提取为严格 YAML（temp 0.0），字段对齐最终 4 份题材文件，带 `evidence_chapters` / `confidence`
- Drafter **Chain-of-Density 3-pass 迭代**（可选开启）
- **三级合并**：batch (25 章) → arc (每 4 批) → book distill（全量），大小说不吃满上下文
- Validator 扇出**并行 3 Auditor**（FactChecker / ConsistencyGuard / StyleGuard）+ Tier-1 正则 deny 短语扫描
- Validator→Fixer **≤2 次 retry loop** + ship_with_debt，对齐作品流水线
- ChapterStream 对 >5MB 大文件走流式索引 + 自动 GB18030/Big5/Shift-JIS 等编码检测转 UTF-8
- `--new-genre --interactive` 问卷式脚手架，产出富初稿
- `--with-trial` 真跑 3 章试验书（复用 bootstrap_project 的 scratch 隔离）
- Intent Router：`--extract-only` / `--merge-only` / `--draft-only` / `--validate-only` 可断点续跑单个 phase

规范文档：
- 设计：[`docs/superpowers/specs/genre-pipeline-design.md`](docs/superpowers/specs/genre-pipeline-design.md)

## 架构 1 行说明

每个 Agent = 一次独立 LLM 调用 + 独立 system prompt + 只读它需要的 state/ 文件。

## 题材 + 作品 两层

### genres/ — 题材层

题材包放在 `genres/<genre-id>/`。**所有基于该题材的作品共享**这些文件。

| 文件 | 必需？ | 内容 |
|---|---|---|
| `genre.yaml` | ✅ | 题材元信息（id / display_name / genre / era / tone / author_persona_hints / prohibited_styles / genre_avoid） |
| `era.md` | ✅ | 时代/世界观事实包 |
| `writing-style-extra.md` | ✅ | 题材特有风格规范 |
| `iron-laws-extra.md` | ✅ | 题材特有铁律 |
| `resource_schema.yaml` | 可选 | 可追踪资源定义（仙侠/港综有；都市言情无） |

详见 `genres/README.md`。

### projects/ — 作品层

一本书放在 `projects/<project-id>/`，每本独立：

| 文件 | 必需？ | 内容 |
|---|---|---|
| `project.yaml` | ✅ | 作品元信息（关键字段：`genre = <genre-id>`，声明基于哪个题材） + protagonist_name / opening_year_month / chapter_count_target |
| `outline.json` | ✅ | 本书整本大纲 + 每章节拍 |
| `characters.yaml` | ✅ | 本书人物档案 |
| `timeline.yaml` | ✅ | 本书时间线 |
| `state/` | 运行时 | bootstrap 拷入题材+作品文件 + Agent 产物（.gitignore） |

详见 `projects/README.md`。

### Bootstrap 在做什么

`python -m src.bootstrap --project <id>`：
1. 读 `projects/<id>/project.yaml`，找到它声明的 `genre`
2. 把 `genres/<genre>/` 的题材层文件拷进 `projects/<id>/state/`
3. 把 `projects/<id>/` 的作品层文件拷进 `projects/<id>/state/`
4. 合成 `state/setting.yaml`（题材元信息 + 作品元信息合并）
5. 重置 `state/progress.json`，touch 空 jsonl
6. 写 `projects/.active` 记录当前激活作品
7. 刷新 `config.STATE_DIR` 指向 `projects/<id>/state/`

### 内置三组（题材 × 作品）

| 题材 id | 作品 id | 主角 | 资源账本 |
|---|---|---|---|
| `gangster-hk-1983` | `gangster-hk-1983-linjiayao` | 林家耀 | ✅ 情报值/黑金/人情/仇家 |
| `xianxia-ascension` | `xianxia-ascension-peichangning` | 裴长宁 | ✅ 灵石/灵草/境界/法器/因果 |
| `urban-romance-contemporary` | `urban-romance-shenruowei` | 沈若微 | ❌（刻意不数值化） |

## State 目录地图

所有 Agent 只读写 state/ 下的文件。以下是**激活某个项目后** `projects/<id>/state/` 的布局：

| 路径 | 内容 | 来源 |
|---|---|---|
| `state/setting.yaml` | 运行时合成的设定元信息（题材 + 作品合并） | bootstrap |
| `state/outline.json` | 本书大纲 + 每章节拍 | 作品层（由 bootstrap 拷入） |
| `state/timeline.yaml` | 本书时间线 | 作品层 |
| `state/characters.yaml` | 本书人物档案 | 作品层 |
| `state/era.md` | 题材事实包 | 题材层 |
| `state/writing-style-extra.md` | 题材特有风格 | 题材层 |
| `state/iron-laws-extra.md` | 题材特有铁律 | 题材层 |
| `state/progress.json` | 当前章节、已完成章节、运行中状态 | pipeline 运行时更新 |
| `state/current_status_card.md` | **当前时间点唯一的权威状态覆盖文件**（主角状态/敌我/资源/已知真相/活跃伏笔/下一章任务卡）。Context Reset 重建局势的入口 | StatusCardUpdater（每章末尾覆盖式更新） |
| `state/pending_hooks.md` | **待回收伏笔池**（活跃伏笔 + 本章刚回收的伏笔）。Planner 每章必读 | HookKeeper（每章末尾覆盖式更新） |
| `state/resource_schema.yaml` | 题材的**可追踪资源定义**。**可选** —— 题材无需则不注入 | 题材层（bootstrap 注入） |
| `state/resource_ledger.md` | 按 schema 记录的资源账本（当前余额 + 本章变动）。仅当 schema 存在时生成 | ResourceLedger（每章末尾覆盖式更新） |
| `state/chapters/chNNN.md` | 第 N 章正文 | Generator / Fixer |
| `state/chapters/chNNN.plan.json` | 第 N 章节拍表 | Planner |
| `state/chapters/chNNN.verdict.json` | 第 N 章 Evaluator 判词 | Evaluator |
| `state/summaries/chNNN.md` | 第 N 章摘要 | Summarizer（独立会话） |
| `state/fixes/chNNN.slop-patch.md` | AI 味审计产物 | AISlopGuard |
| `state/fixes/chNNN.char-patch.md` | 人设审计产物 | CharacterGuard |
| `state/fixes/chNNN.fact-patch.md` | 事实核查补丁（**仅当** Evaluator 命中 landmine_13·medium+ 且配置了 Perplexity） | FactChecker（A-1，按需触发） |
| `state/issues.jsonl` | 待修问题日志 | Evaluator 追加 |
| `state/debt.jsonl` | 带伤上线的技术债 | Pipeline（2 次 retry 仍不过） |
| `state/prompts_log.jsonl` | 每次 LLM 调用的完整记录 | llm.chat() 自动写入 |
| `state/websearch_log.jsonl` | 每次 Perplexity 查询的完整记录（query + latency + 引用数） | websearch.search() 自动写入 |
| `state/websearch_cache/*.json` | Perplexity 查询结果缓存（md5 键） | websearch.search() 自动写入 |
| `state/packaging.json` | 出版包装产物（书名/简介/封面/标签） | PackagingAgent（独立运行 `--packaging`） |

**另外**：`projects/.active` 是一个单行文本文件，记录当前激活的 project id。这让工具（web / lint / calibrate）能自动找到"当前这本书"。

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
| **FactChecker**（A-1，按需） | chNNN.md + verdict.json（读 landmine_13 evidence）+ era.md | fixes/chNNN.fact-patch.md | 0.0 | 独立事实核查；调 Perplexity Sonar ≤3 次/章；仅在 landmine_13·medium+ 时触发 |
| PackagingAgent | setting.yaml + outline.json + characters.yaml + era.md + ch001.md + 最后章节 | packaging.json | 0.6 | 书名/简介/封面/标签包装，独立运行 `--packaging` |

## 规则索引（Progressive Disclosure）

规则分两层：通用（`rules/`）+ 题材特有（`genres/<id>/` 经 bootstrap 拷入 `state/`）。每个 Agent 只加载它需要的那 1-2 份。

| 文件 | 类型 | 谁用 |
|---|---|---|
| `rules/00-information-priority.md` | 通用 | Evaluator、Fixer（引用） |
| `rules/24-iron-laws.md` | 通用 | Evaluator |
| `rules/18-landmines.md` | 通用 | Evaluator（全）、AISlopGuard（AI 味子集） |
| `rules/writing-style-core.md` | 通用 | Generator、Fixer |
| `state/iron-laws-extra.md` | 题材（genre） | Evaluator |
| `state/writing-style-extra.md` | 题材（genre） | Generator、Fixer |
| `state/era.md` | 题材（genre） | Generator |
| `state/characters.yaml` | 作品（project） | 所有 Agent |

## 故障排查

- **Agent 反复失败** → 不要在 prompt 上打补丁。读 `state/debt.jsonl` 和 `state/prompts_log.jsonl`，先定位能力缺口，再决定是"补工具/补规则/补语料"。**重启胜过修补**（Lesson 1）。
- **章节跑飞或越写越偏** → 检查 `summaries/*.md` 是否被 Generator 污染（本应只由 Summarizer 独立产出）。这是 Lesson 3 的典型泄漏点。
- **Evaluator 看似通过但 verdict 全空** → 检查 `_skeleton_detected` 字段。Evaluator 返回 JSON 示例骨架时会被 detector 识别并触发 retry，不会静默通过。
- **生成质量变差** → 打开 Web UI 的 Prompt Inspector，对比相邻两次 Generator 的 system prompt 和 inputs_read。任何两次调用的上下文必须各自独立、不应出现跨章累积。
- **切换作品但 Agent 仍然用老题材口吻** → 重新 `python -m src.bootstrap --project <id>`。检查 `projects/.active` 文件的内容 + `state/setting.yaml` 中 `id` 字段是否为期望的作品。
