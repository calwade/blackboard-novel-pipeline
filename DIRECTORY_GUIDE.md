# Novelforge · 目录结构导览

> 一页纸解释：哪些目录是**核心代码**、哪些是**运行时产物**、哪些**看起来可疑但其实合理**。
> 避免新人或未来的自己再困惑。对应的详细职责见 [`AGENTS.md`](AGENTS.md)。

## 一图看清

```
opencode/
├─ src/              ← Python 源码（唯一生产代码入口）
├─ web/              ← Flask 前端（app / routes / templates / static）
├─ tests/            ← pytest 测试（~520 个）
├─ rules/            ← 通用规则（Evaluator/Generator 读的 .md + deny phrases）
│
├─ projects/         ← **作品** 目录（每本书一份，state/ 运行时产物）
├─ presets/          ← **题材模板**（新建作品时拷贝 4 份题材文件）
├─ novels/           ← 原著素材（.gitignore 忽略）
│
├─ docs/             ← 文档 + GitHub Pages 静态 demo（见下）
├─ scripts/          ← 手工运维脚本（web-start.sh / web-stop.sh）
├─ evaluator_calibration/  ← Evaluator 校准测试集 + 报告（见下）
│
├─ AGENTS.md         ← 项目系统 prompt（agent 名册 + 目录地图）
├─ README.md         ← 项目介绍
├─ CHANGELOG.md      ← 发布变更日志
├─ Procfile          ← 生产部署启动命令（Heroku/Railway/Render 通用）
│
├─ package.json      ← npm 入口（只为 stylelint，不影响运行时）
├─ .stylelintrc.json ← CSS 风格守门配置
├─ .githooks/        ← pre-commit hook（CSS lint）
│
└─ .jobs/            ← 题材任务运行时产物（.gitignore 忽略）
```

## 核心代码（要看懂业务必读）

| 路径 | 说明 |
|---|---|
| `src/pipeline.py` | 每章流水线驱动（Planner → Generator → Evaluator → Fixer → Summarizer） |
| `src/agents/` | 14 个 agent（每个 = 一次独立 LLM 调用 + 独立 system prompt） |
| `src/auditors/` | 3 个 auditor（ai_slop / character / fact） |
| `src/core/` | BaseAgent + Blackboard（state/ 文件 I/O 抽象） |
| `src/genre_extractor/` | 新建 preset 的 3 条路径：blank / from_description / miners（NovelDNA + SensoryKit） |
| `src/jobs/` | 题材任务系统（.jobs/ 持久化 + cancel token） |
| `src/tools/` | CLI 工具（dashboard / calibrate_evaluator / setting_lint / websearch） |
| `src/bootstrap.py` | 激活作品 / 新建作品入口 |
| `src/config.py` | STATE_DIR 动态解析 + PROJECT_ROOT |
| `src/llm.py` | DeepSeek API 封装 + prompts_log 自动写入 |

## 作品与模板的关系

```
presets/<preset-id>/         作品模板（新建时被拷贝，之后与 preset 解耦）
  era.md
  writing-style-extra.md
  iron-laws-extra.md
  resource_schema.yaml (可选)
  genre.yaml
  dna_cards/ (仅 NovelDNA 产物)

     │  bootstrap 拷贝一次
     ▼

projects/<book-id>/          作品本身（生产端读的唯一真源）
  project.yaml
  outline.json
  characters.yaml
  timeline.yaml
  era.md                    ← 从 preset 拷来，之后作品自己维护
  writing-style-extra.md
  iron-laws-extra.md
  resource_schema.yaml (可选)
  state/                    ← 运行时产物，.gitignore 忽略
    chapters/
    summaries/
    fixes/
    prompts_log.jsonl
    progress.json
    ...
```

## "看起来可疑但其实合理"的目录

这些常被误以为是冗余或历史残骸，其实都在活跃使用：

### `evaluator_calibration/`

**用途**：Evaluator 校准测试集。包含 10 个 case（小说段落 + 预期 verdict）+ 历次 reports。

**谁在用**：
- `src/tools/calibrate_evaluator.py`（CLI）
- 手动验证 Evaluator 升级后是否回归

**运行**：`python -m src.tools.calibrate_evaluator`

### `docs/rules/` vs `rules/`

两份内容**必须完全一致**，由 `tests/test_web_and_pages_sync.py` 守护：
- `rules/` 是生产端读的（Evaluator/Generator）
- `docs/rules/` 是 GitHub Pages 静态演示页展示的副本

改 `rules/*.md` 后记得也改 `docs/rules/*.md`（或反之），否则测试会失败。

### `docs/demo_snapshot*/`

**3 份快照**：
- `docs/demo_snapshot/` — 港综 3 章
- `docs/demo_snapshot_xianxia/` — 仙侠 3 章
- `docs/demo_snapshot_gangster_c5_10ch/` — 港综 10 章

**用途**：GitHub Pages 静态 demo 的数据源。`src/tools/dashboard.py` 可以基于这些快照跑展示。

**.gitignore 特别注释**："故意不忽略——是 Pages 静态演示的证据链"。

### `docs/history/`

过期的设计文档和决策记录。`docs/history/README.md` 声明：

> 这些文档保留了项目的**决策脉络** ...**但不是当前系统状态的权威描述**。

读 AGENTS.md + 具体 specs 即可，history/ 只在"想知道为什么某个设计是这样"时才看。

### `docs/superpowers/{plans,specs}/`

- `specs/` — 正式设计文档（当前有效）
- `plans/` — 对应 spec 的实施 plan（执行时的 checklist）

### `scripts/`

只有 `web-start.sh` / `web-stop.sh`——手工部署用。代码不调用。

### `.easyclaw/`

第三方工具的凭证目录，权限 700，已 `.gitignore`。与 Novelforge 代码无关。

### `.jobs/`

题材任务（NovelDNA / SensoryKit 等 miner）的运行时产物：
- `active/<job_id>.json` — 未完成任务
- `archive/<job_id>.json` — 已结束任务
- `logs/<job_id>.log` — 运行日志

全部 `.gitignore` 忽略。详见 AGENTS.md "题材任务（Genre Jobs）" 段。

### `.husky/`

前端工具的 shell 存根目录。目前只有 `_/` 子目录（husky 内部文件）。实际 pre-commit hook 在 `.githooks/`，需 `git config core.hooksPath .githooks` 激活。

## "看起来多余但要保留"的测试

`tests/` 下几十个文件，有几个跟平常认知不太像：

- `test_web_and_pages_sync.py` — 守护 `rules/` ↔ `docs/rules/` 一致性
- `test_phase1_repo_state.py` — 检查仓库顶层结构 + `src.genre_extractor` import 正常
- `test_phase5_integration.py` — 端到端（bootstrap + CLI 辅助 + 没有老 pipeline 引用泄漏）

## 改任何东西前，先读

- **改 agent / 流水线** → `AGENTS.md` → 对应 `src/agents/*.py`
- **改 Web UI / CSS** → `docs/DESIGN-SYSTEM.md`（硬门禁），不读必踩坑
- **改题材 preset** → `docs/superpowers/specs/genre-mining-v2-step1-sensory-kit.md`
- **改流程/增加新 agent** → 照抄现有最相似的 agent（别凭空造风格）
