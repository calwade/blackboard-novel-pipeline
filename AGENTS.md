# AGENTS.md

> 目录页，不是百科全书。每个 Agent 只加载自己需要的那 1-2 份规则。
> — Lesson 5 from OpenAI Codex post-mortem

## 项目目标

**Novelforge · 小说锻造厂** — 通用多 Agent 小说写作流水线。外层 Pipeline + 内层 Blackboard + Auditor Fan-Out + Evaluator 半 Debate + Lesson-3 三层 Bookkeeping。

**一本书 = `projects/<book-id>/` 下的全部文件**。包括题材规范（`era.md` / `writing-style-extra.md` / `iron-laws-extra.md` / 可选 `resource_schema.yaml`）、作品本身（`outline.json` / `characters.yaml` / `timeline.yaml`）、以及元信息（`project.yaml`）。这本书自给自足，不依赖任何外部共享目录。

**preset（预设）只在新建作品时被使用**：`presets/<preset-id>/` 是一份可选的题材起点模板；新建一本书时可以从某个 preset 拷贝 4 份题材文件过来作为起点，之后作品目录里的文件就和 preset 解耦了。

流水线本身（`src/`）对这些都无感知；它只读运行时拷贝过来的 `state/` 目录。

## 如何运行

```bash
cp .env.example .env                                          # 填入 DEEPSEEK_API_KEY
pip install -r requirements.txt

python -m src.bootstrap --list-presets                        # 看所有题材预设
python -m src.bootstrap --list                                # 看所有作品
python -m src.bootstrap --project gangster-hk-1983-linjiayao  # 激活作品（含 state 初始化）
python -m src.pipeline --range 1-3                            # 跑前三章
flask --app web.app run --port 5055                           # 启动演示页
```

### 部署模式

- **开发**：`flask --app web.app run --port 5055`（单进程 + 调试）
- **生产**：`gunicorn --workers 1 --threads 8 "web.app:app"` — **必须 `--workers 1`**

> 内存里的 job 缓存（`_JOBS`）和 target 互斥锁（`_TARGET_LOCKS`）都是进程级的。
> 多 worker 会让同一个 job 只在其中一个 worker 上可见，UI 轮询其他 worker 时会拿到
> `unknown`。如要横向扩展，需要把 job cache 迁到共享存储（参见
> `docs/superpowers/specs/genre-jobs-rearch.md`）。

切换作品只需重新 bootstrap，无需改代码：

```bash
python -m src.bootstrap --project xianxia-ascension-peichangning   # 切到仙侠那本
python -m src.pipeline --chapter 1
```

新建一本书（最快路径：Web 向导 4 步走）：启动 `flask --app web.app` 后打开首页，按"题材起点 → 作品元信息 → 大纲 → 人物"四步填完即可。也可以用 CLI：

```bash
python -m src.bootstrap --new-project my-book \
    --preset gangster-hk-1983 --display-name "港岛新记" \
    --protagonist "陈阿强" --chapters 80
# 编辑 projects/my-book/outline.json / characters.yaml
python -m src.bootstrap --project my-book
```

## 题材提取流水线（Genre Extractor）

除了作品流水线（每章 Planner→Generator→Evaluator→Fixer→Summarizer），系统还有一条 **题材提取流水线**（`src/genre_extractor/`）：用于从已有小说拆解出题材规范，并写入两种目标之一——直接写入某个 **作品** 目录（`--extract-genre <book-id>`，替换该书的 4 份题材文件），或写入一个新的 **preset**（`--to-preset <preset-id>`，沉淀为可复用模板）。

```bash
# 从已有小说拆题材 → 直接写进一本作品
python -m src.pipeline --extract-genre my-book \
    --sources novels/a.txt,novels/b.txt [--with-trial]

# 从已有小说拆题材 → 沉淀成新 preset（供后续新作品勾选）
python -m src.genre_extractor --to-preset xianxia-dark-1 \
    --sources novels/a.txt,novels/b.txt

# 断点续跑单个 phase（Intent Router）
python -m src.genre_extractor --to-preset <id> --extract-only
python -m src.genre_extractor --to-preset <id> --merge-only
python -m src.genre_extractor --to-preset <id> --draft-only
python -m src.genre_extractor --to-preset <id> --validate-only
```

机制要点：
- 核心模块：`src/genre_extractor/core.py`（主编排器）、`to_preset.py`（写入 preset 目录）、`to_project.py`（写入作品目录）、`pipeline.py`（phase pipeline）、`adaptive.py`（自适应窗口）、`chapter_stream.py`（流式章节索引）
- 复用 `Blackboard` / `BaseAgent`（位于 `src/core/`）
- 滑动窗口 25 章/批，三档自适应（≤50:10 / 51-600:25 / >600:40）
- `.build/`（构建期工作目录，进 `.gitignore`）：`build_status.yaml` + `extraction_notes/batch-NNN.yaml` + `genre_blueprint.yaml` + `genre_issues.jsonl` + `extraction_tally.md`
- Extractor **两步法**（DSPy TwoStepAdapter 思路）：Step 1 自由笔记（temp 0.3）→ Step 2 verbatim 提取为严格 YAML（temp 0.0），字段对齐最终 4 份题材文件，带 `evidence_chapters` / `confidence`
- Drafter **Chain-of-Density 3-pass 迭代**（可选开启）
- **三级合并**：batch (25 章) → arc (每 4 批) → book distill（全量），大小说不吃满上下文
- Validator 扇出 **并行 3 Auditor**（FactChecker / ConsistencyGuard / StyleGuard）+ Tier-1 正则 deny 短语扫描
- Validator→Fixer **≤2 次 retry loop** + ship_with_debt，对齐作品流水线
- ChapterStream 对 >5MB 大文件走流式索引 + 自动 GB18030/Big5/Shift-JIS 等编码检测转 UTF-8
- `--with-trial` 真跑 3 章试验书（复用 bootstrap_project 的 scratch 隔离）

规范文档：
- 设计：[`docs/superpowers/specs/book-centric-workflow-design.md`](docs/superpowers/specs/book-centric-workflow-design.md)

## 架构 1 行说明

每个 Agent = 一次独立 LLM 调用 + 独立 system prompt + 只读它需要的 state/ 文件。

## 作品目录布局

一本书放在 `projects/<book-id>/`。每本书是自给自足的：

| 文件 | 必需？ | 内容 |
|---|---|---|
| `project.yaml` | ✅ | 作品元信息（`id` / `display_name` / `protagonist_name` / `opening_year_month` / `chapter_count_target` / `source_preset`） |
| `outline.json` | ✅ | 本书整本大纲 + 每章节拍 |
| `characters.yaml` | ✅ | 本书人物档案 |
| `timeline.yaml` | ✅ | 本书时间线 |
| `era.md` | ✅ | 时代/世界观事实包 |
| `writing-style-extra.md` | ✅ | 题材特有风格规范 |
| `iron-laws-extra.md` | ✅ | 题材特有铁律 |
| `resource_schema.yaml` | 可选 | 可追踪资源定义（仙侠/港综有；都市言情无） |
| `state/` | 运行时 | bootstrap 拷入 + Agent 产物（.gitignore） |

`project.yaml` 的 `source_preset` 字段仅作审计用：记录这本书的题材起点是从哪个 preset 拷来（或从什么样本拆出来）。它不参与运行时，作品目录里的 4 份题材文件才是权威。

详见 [`projects/README.md`](projects/README.md)。

### Bootstrap 在做什么

`python -m src.bootstrap --project <id>`：
1. 读 `projects/<id>/project.yaml`
2. 把 `projects/<id>/` 下的所有必需文件（outline / characters / timeline / era / writing-style-extra / iron-laws-extra / 可选 resource_schema）拷进 `projects/<id>/state/`
3. 合成 `state/setting.yaml` = `project.yaml` 的字段 + 运行时字段（`preset_id` 回填自 `source_preset`、`resource_ledger_enabled` 由 resource_schema 是否存在推出等）
4. 重置 `state/progress.json`，touch 空 jsonl
5. 写 `projects/.active` 记录当前激活作品
6. 刷新 `config.STATE_DIR` 指向 `projects/<id>/state/`

### 内置三本书

| 作品 id | source_preset | 主角 | 资源账本 |
|---|---|---|---|
| `gangster-hk-1983-linjiayao` | `gangster-hk-1983` | 林家耀 | ✅ 情报值/黑金/人情/仇家 |
| `xianxia-ascension-peichangning` | `xianxia-ascension` | 裴长宁 | ✅ 灵石/灵草/境界/法器/因果 |
| `urban-romance-shenruowei` | `urban-romance-contemporary` | 沈若微 | ❌（刻意不数值化） |

## State 目录地图

所有 Agent 只读写 state/ 下的文件。以下是 **激活某本书后** `projects/<id>/state/` 的布局：

| 路径 | 内容 | 来源 |
|---|---|---|
| `state/setting.yaml` | 运行时合成的设定元信息 | bootstrap（合成自 project.yaml） |
| `state/outline.json` | 本书大纲 + 每章节拍 | 作品目录（bootstrap 拷入） |
| `state/timeline.yaml` | 本书时间线 | 作品目录（bootstrap 拷入） |
| `state/characters.yaml` | 本书人物档案 | 作品目录（bootstrap 拷入） |
| `state/era.md` | 题材事实包 | 作品目录（bootstrap 拷入） |
| `state/writing-style-extra.md` | 题材特有风格 | 作品目录（bootstrap 拷入） |
| `state/iron-laws-extra.md` | 题材特有铁律 | 作品目录（bootstrap 拷入） |
| `state/resource_schema.yaml` | 可追踪资源定义（**可选**，书无需则不拷入） | 作品目录（bootstrap 拷入） |
| `state/progress.json` | 当前章节、已完成章节、运行中状态 | pipeline 运行时更新 |
| `state/current_status_card.md` | **当前时间点唯一的权威状态覆盖文件**（主角状态/敌我/资源/已知真相/活跃伏笔/下一章任务卡）。Context Reset 重建局势的入口 | StatusCardUpdater（每章末尾覆盖式更新） |
| `state/pending_hooks.md` | **待回收伏笔池**（活跃伏笔 + 本章刚回收的伏笔）。Planner 每章必读 | HookKeeper（每章末尾覆盖式更新） |
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

## 题材任务（Genre Jobs）

每个"新建题材" / "覆盖作品题材"操作（原著拆 / 描述生成 / 空壳 / 作品覆盖）都会产生一个 **Job**，落盘到仓库根的 `.jobs/` 目录（已在 `.gitignore`）：

| 路径 | 内容 |
|---|---|
| `.jobs/active/<job_id>.json` | 未完成的 job（state ∈ running / aborting） |
| `.jobs/archive/<job_id>.json` | 已结束（state ∈ done / failed / aborted / interrupted） |
| `.jobs/logs/<job_id>.log` | 运行日志（rotating 10MB × 3 份） |

**Web 入口**：`/jobs` 列表 + `/jobs/<id>` 详情页（节点图 + 日志 tail）。首页顶栏 pill `⚙ N 个题材任务运行中` 可一键跳转。

**API**：`/api/jobs` REST（POST 创建 / GET 列表 / GET 详情 / DELETE / POST abort）+ `/api/jobs/<id>/log?offset=N` 日志尾随。

**关键特性**：
- **不限并发**：每个 job 独立线程 + 按 target（preset id / project id）互斥。同一 target 不允许两个 job 并跑；不同 target 完全并行（且与章节流水线互不阻塞）。
- **真 abort**：`CancelToken` 协议（`src.jobs.cancel`）贯穿 4 个 phase 边界和 extract batch 循环，`POST /api/jobs/<id>/abort` 在 30 秒内让 worker 真正退出。
- **进程崩溃恢复**：启动时 `JobStore.recover()` 把 `active/` 里 state=running/aborting 的孤儿 job 翻成 `interrupted`。
- **不污染 git**：`.jobs/` 目录整体 `.gitignore`。

## Agent 名册

| Agent | 读 | 写 | Temp | 核心 Prompt 要点 |
|---|---|---|---|---|
| Planner | outline + 最近 2 summary + setting.yaml + **current_status_card.md** + **pending_hooks.md** | chNNN.plan.json | 0.4 | 责编视角，输出严格 JSON；必读状态卡+伏笔池作为当前权威 |
| Generator | plan + characters + setting.yaml + era + writing-style（core + extra） | chNNN.md (~3000字) | 0.85 | Show-Don't-Tell，禁 AI 味 |
| Evaluator | chNNN.md + 18-landmines + 24-iron-laws（core + extra）+ characters + timeline + **current_status_card.md** + **pending_hooks.md**（两者可选，缺失时跳过） | verdict.json + issues.jsonl | 0.0 | 对抗人设，默认拒稿，JSON rubric + skeleton detector；交叉验证"反派信息越界"与伏笔回收一致性 |
| Fixer | chNNN.md + verdict.top_3_fixes + writing-style（core + extra） | 覆写 chNNN.md | 0.5 | 只修不重写 |
| Summarizer | chNNN.md **（不读 plan/issues，防 framing 泄漏）** | summaries/chNNN.md | 0.2 | 客观白描 |
| **StatusCardUpdater** | chNNN.md + 上一版 current_status_card.md + characters.yaml + setting.yaml | **current_status_card.md**（覆盖式） | 0.2 | Lesson 3：当前时间点唯一快照；读正文，不读 plan/verdict/issues |
| **HookKeeper** | chNNN.md + 上一版 pending_hooks.md + current_status_card.md | **pending_hooks.md**（覆盖式） | 0.2 | 维护活跃伏笔池，回收/新增/推进三操作；只从正文抽取 |
| **ResourceLedger**（可选） | resource_schema.yaml + chNNN.md + 上一版 resource_ledger.md | **resource_ledger.md**（覆盖式） | 0.2 | 仅在书提供 resource_schema.yaml 时运行；监控资源跳数量级 |
| AISlopGuard | chNNN.md + 摘取 AI 味条目 | fixes/chNNN.slop-patch.md | 0.2 | 只报 AI 味相关（moderate/severe） |
| CharacterGuard | chNNN.md + characters.yaml + 历史 summaries | fixes/chNNN.char-patch.md | 0.2 | 只报人设偏移 |
| **FactChecker**（A-1，按需） | chNNN.md + verdict.json（读 landmine_13 evidence）+ era.md | fixes/chNNN.fact-patch.md | 0.0 | 独立事实核查；调 Perplexity Sonar ≤3 次/章；仅在 landmine_13·medium+ 时触发 |
| PackagingAgent | setting.yaml + outline.json + characters.yaml + era.md + ch001.md + 最后章节 | packaging.json | 0.6 | 书名/简介/封面/标签包装，独立运行 `--packaging` |
| **OutlineDrafter**（向导用） | 用户填写的 synopsis（自由文本）+ chapter_count_target | 临时 outline.json 初稿 | 0.4 | 新建作品向导 Step 3：把一段 synopsis 转成结构化 outline.json 初稿 |
| **CharactersDrafter**（向导用） | 用户填写的 character brief（自由文本）+ protagonist_name | 临时 characters.yaml 初稿 | 0.4 | 新建作品向导 Step 4：把人物简述转成结构化 characters.yaml 初稿 |

OutlineDrafter / CharactersDrafter 是新建作品向导使用的轻量 agent：它们只在"从一段自由文本起草初稿"时被触发，之后作者可以在 Web UI 或直接编辑文件进一步打磨。它们不参与每章循环。

## 规则索引（Progressive Disclosure）

规则分两层：通用（`rules/`）+ 作品目录内的题材特有文件（经 bootstrap 拷入 `state/`）。每个 Agent 只加载它需要的那 1-2 份。

| 文件 | 类型 | 谁用 |
|---|---|---|
| `rules/00-information-priority.md` | 通用 | Evaluator、Fixer（引用） |
| `rules/24-iron-laws.md` | 通用 | Evaluator |
| `rules/18-landmines.md` | 通用 | Evaluator（全）、AISlopGuard（AI 味子集） |
| `rules/writing-style-core.md` | 通用 | Generator、Fixer |
| `state/iron-laws-extra.md` | 题材（本书专属） | Evaluator |
| `state/writing-style-extra.md` | 题材（本书专属） | Generator、Fixer |
| `state/era.md` | 题材（本书专属） | Generator |
| `state/characters.yaml` | 作品（本书专属） | 所有 Agent |

## 故障排查

- **Agent 反复失败** → 不要在 prompt 上打补丁。读 `state/debt.jsonl` 和 `state/prompts_log.jsonl`，先定位能力缺口，再决定是"补工具/补规则/补语料"。**重启胜过修补**（Lesson 1）。
- **章节跑飞或越写越偏** → 检查 `summaries/*.md` 是否被 Generator 污染（本应只由 Summarizer 独立产出）。这是 Lesson 3 的典型泄漏点。
- **Evaluator 看似通过但 verdict 全空** → 检查 `_skeleton_detected` 字段。Evaluator 返回 JSON 示例骨架时会被 detector 识别并触发 retry，不会静默通过。
- **生成质量变差** → 打开 Web UI 的 Prompt Inspector，对比相邻两次 Generator 的 system prompt 和 inputs_read。任何两次调用的上下文必须各自独立、不应出现跨章累积。
- **切换作品但 Agent 仍然用老题材口吻** → 重新 `python -m src.bootstrap --project <id>`。检查 `projects/.active` 文件的内容 + `state/setting.yaml` 中 `id` 字段是否为期望的作品。
- **想换题材起点** → preset 拷贝一次就解耦了；要替换某本书的题材，直接改 `projects/<id>/` 目录下的 4 份题材文件（或跑 `--extract-genre` 从新样本重新拆），不需要动 preset。
