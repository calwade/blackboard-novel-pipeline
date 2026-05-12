# 🔨 Novelforge

> *把一本小说拆给 10 个 Agent 分工生产的写作流水线。文件即记忆、对抗式审稿、三层账本、题材随书走。*

**小说锻造厂** — 把"一个 AI 一路写到黑"拆成 10 个独立 Agent 的长链路生产线。Anthropic / Cognition / OpenAI 在长链路 Agent 上总结出的 5 条经验，全部作为架构约束来设计：**状态全部沉到磁盘文件**、**对抗式审稿（默认拒稿）**、**三层账本（状态卡 / 伏笔池 / 资源账本）**、**题材随书走**、**规则按需披露（不塞大而全）**。

- **仓库主页**：[github.com/CalWade/novelforge](https://github.com/CalWade/novelforge)
- **在线演示**：[calwade.github.io/novelforge/](https://calwade.github.io/novelforge/)（GitHub Pages · 静态只读）

---

## 一分钟讲清楚是什么

一本小说**不是**一个 AI 从头写到尾的 —— 它由 **5 个创作 Agent + 3 个记账 Agent + 3 个后台审计 Agent** 分工合作：

```
Planner 拆节拍 → Generator 写正文 → Evaluator 挑刺 → Fixer 改稿 → Summarizer 摘要
                                                                        │
                                        ┌────── 记账层（三份账本）─────┤
                                        │                               │
                                 StatusCardUpdater               HookKeeper
                                 （当前状态卡）                  （待回收伏笔池）
                                        │                               │
                                 ResourceLedger
                                 （资源账本 · 可选：题材需声明 resource_schema 才启用）
                                        │
                                        ├──────── 扇出并行审计 ────────┤
                                        │                               │
                                  AISlopGuard                    CharacterGuard
                                  （AI 味审计）                  （人设漂移审计）
                                        │
                                  FactChecker（按需触发 · Perplexity 联网）
```

每个 Agent 都用**独立的 LLM 调用、独立的 system prompt、独立的上下文窗口**（每次调用都是全新会话，不累积）。**所有状态都存在文件里**（`state/` 目录），**不在内存里**。

核心性质：**一个 Python 进程死了，换一个新进程，只要读 `state/current_status_card.md` 就能立刻知道**—— 刚才写到哪一章、主角当前什么状态、哪些伏笔还没回收。这是 Cognition 团队提出的「把上下文整个丢掉重读文件」（他们叫 Context Reset，中文可理解为"上下文重置"）的工程化落地。

---

## 架构：三层嵌套

```
外层（宏观）： Pipeline 主循环 — 章节线性推进
每章内部：    Blackboard 黑板 — state/ 文件 = 所有 Agent 的唯一共享记忆
每章产后：    扇出并行 — 多个 Auditor 后台同时扫
Evaluator：   半对抗辩论 — 对抗人设 + 结构化 JSON 评分表 + 骨架检测器（防模型复制 prompt 示例）
```

| Agent | 读 | 写 | 采样温度 |
|---|---|---|---|
| **Planner**（责编） | 大纲 + 最近 2 份摘要 + 题材元信息 + **当前状态卡** + **伏笔池** | `chNNN.plan.json`（含章节类型 / 场景推进项 / 写作自检表） | 0.4 |
| **Generator**（执笔） | 节拍表 + 人物档案 + 写作风格（通用 + 题材特有）+ 时代事实包 + **题材禁用风格黑名单** | `chNNN.md`（~3000 字） | 0.85 |
| **Evaluator**（审稿） | 章节正文 + 18 条雷点 + 28 条铁律（通用 + 题材特有）+ **信息源优先级协议** + 人物档案 + 时间线 | `verdict.json` + 问题日志 | 0.0 |
| **Fixer**（改稿） | 章节正文 + 评审判决中的 top 3 待修 + 写作风格 + 题材禁用风格黑名单 | 覆写 `chNNN.md` | 0.5 |
| **Summarizer**（摘要员） | **只读**章节正文（不读 plan/verdict，防"立场后门"泄漏） | `summaries/chNNN.md` | 0.2 |
| **StatusCardUpdater**（状态卡员） | 本章正文 + 上一版状态卡 + 人物档案 | `current_status_card.md`（整份覆盖） | 0.2 |
| **HookKeeper**（伏笔登记员） | 本章正文 + 上一版伏笔池 + 当前状态卡 | `pending_hooks.md`（整份覆盖） | 0.2 |
| **ResourceLedger**（账房 · 可选） | 题材的资源定义 + 本章正文 + 上一版账本 | `resource_ledger.md`（整份覆盖） | 0.2 |
| **AISlopGuard**（AI 味审计） | 章节正文 | `fixes/chNNN.slop-patch.md`（补丁文件） | 0.2 |
| **CharacterGuard**（人设审计） | 章节正文 + 人物档案 + 历史摘要 | `fixes/chNNN.char-patch.md` | 0.2 |
| **FactChecker**（事实核查 · 按需触发） | 章节正文 + 判决文件 + 时代事实包 | `fixes/chNNN.fact-patch.md` | 0.0 |

> FactChecker 只在 Evaluator 命中 `landmine_13`（世界观模糊/脱离现实）且严重度为 medium 或 high 时才触发。调用 Perplexity Sonar 搜索 ≤3 条可查证断言，产出建议性补丁（不改判决）。未配置 `PERPLEXITY_API_KEY` 时自动跳过、不阻塞其他 Agent。

---

## 对应 5 大 Agent 搭建难题

| 难题 | 出处 | 本项目对策 |
|---|---|---|
| ① 反复失败、没有反馈链路 | Anthropic | 所有 Agent 无状态；失败写入 `issues.jsonl` + `debt.jsonl`；下一轮 Fixer 从文件读并开一个干净会话 |
| ② 自评过于乐观 | Anthropic | 五个独立 Agent + Evaluator **默认拒稿的"对抗人设"** + **结构化 JSON 评分表**（18 个雷点逐条打分）+ **骨架检测器**（防模型复制示例 prompt 里的 `…` 占位符） |
| ③ 上下文焦虑（越写越慌） | Cognition | 每次调用都是**全新会话**；只读它需要的 1-2 个文件；Summarizer **独立会话**，只读最终章节正文，不读 plan/issues（防"立场后门"泄漏） |
| ④ AI 味代码堆积 | OpenAI Codex | `rules/*.md` + `projects/<book-id>/iron-laws-extra.md` 就是黄金原则；每章跑完自动触发后台 Auditor，产出独立补丁文件；Evaluator 两轮重试仍不过 → **带病上线**（写入 `debt.jsonl`，避免死循环） |
| ⑤ 规则文件百科病 | OpenAI | `AGENTS.md` **只做目录页**；详细拆到 `rules/` 通用 + `projects/<book-id>/` 题材特有；每个 Agent 只加载它需要的那 1-2 份 |

---

## 一本书的生命周期

Novelforge 把"写一本小说"封装成单一工作流：

```
新建作品 (4 步向导)
    ↓
  第 1 步：基本信息（书名 / 主角 / 目标章数）
  第 2 步：题材起点（三选一）
           ├── 从 preset 拷贝：挑一个现成 preset 作为起点
           ├── 从原著拆：从 novels/ 大池子勾选 txt，LLM 生成题材规范
           └── 最小脚手架：产出 4 份空壳
  第 3 步：大纲起点（梗概 → LLM 生成 outline.json；或空壳）
  第 4 步：角色起点（人物简介 → LLM 生成 characters.yaml；或空壳）
    ↓
作品 ready → projects/<book-id>/ 下自带所有需要的文件
    ↓
bootstrap → projects/<book-id>/state/ 就绪
    ↓
pipeline --chapter N （Planner → Generator → Evaluator → Fixer → Summarizer + 记账 + 审计）
    ↓
作品完结 → pipeline --packaging（书名 / 简介 / 封面 / 标签）
```

题材不是独立概念。一本书 = `projects/<book-id>/` 目录下的全部文件：

```
projects/<book-id>/
├── project.yaml          # 书的元信息（含可选 source_preset 字段记录起点）
├── outline.json          # 大纲
├── characters.yaml       # 人物
├── timeline.yaml         # 时间线
├── era.md                # 题材文件：时代/世界观事实包
├── writing-style-extra.md   # 题材文件：特有写作风格
├── iron-laws-extra.md       # 题材文件：特有铁律
├── resource_schema.yaml  # 可选：可追踪资源定义
└── state/                # 运行时产物（.gitignore）
```

**preset 是新书的可选起点模板**，位于 `presets/<preset-id>/`。新建作品时可以从 preset 拷贝题材 4 份文件作为起点；拷完就和 preset 解耦——之后怎么改都不影响 preset，也不受 preset 更新影响。preset **不参与运行时**，只在新建作品的那一刻起作用。

### 从原著拆题材

新建作品或已有作品都可以「从原著拆题材」——读 N 本原著反推一份题材规范：

```bash
# 新建作品时：4 步向导的第 2 步选"从原著拆"
# 或：CLI 对已有作品操作（产物直接落到 projects/<book-id>/ 根目录）
python -m src.pipeline --extract-genre <book-id> --sources novels/a.txt,novels/b.txt [--with-trial]

# 造一个可复用的新 preset（供后续新作品从中拷贝起点）
python -m src.genre_extractor --to-preset <new-preset-id> --sources novels/a.txt,novels/b.txt
```

核心机制：滑动窗口 **25 章/批**（三档自适应：≤50 章 10/批、51-600 章 25/批、>600 章 40/批）+ **两步法 Extractor**（Step 1 自由笔记 temp 0.3 → Step 2 verbatim 提取为严格 YAML temp 0.0）+ **Drafter Chain-of-Density 3-pass 迭代** + **Validator 扇出 3 Auditor 并行**（FactChecker / ConsistencyGuard / StyleGuard）+ **≤2 次 Fixer retry loop** + **ChapterStream 流式索引**（>5MB 大文件不吃内存）+ **6 种章节格式自动识别** + **GB18030 / Big5 / Shift-JIS 等编码自动转 UTF-8**。

Web UI：作品首页 ⎇ 覆盖题材按钮 / `/presets/<id>` 从原著拆新 preset 入口。

### 内置三组

| preset（可选起点） | 内置作品 | 主角 | 资源账本 |
|---|---|---|---|
| `gangster-hk-1983` | `gangster-hk-1983-linjiayao` | 林家耀 | ✅ 情报值/黑金/人情/仇家 |
| `xianxia-ascension` | `xianxia-ascension-peichangning` | 裴长宁 | ✅ 灵石/灵草/境界/法器/因果 |
| `urban-romance-contemporary` | `urban-romance-shenruowei` | 沈若微 | ❌（刻意不数值化） |

详见 [`projects/README.md`](projects/README.md) 和 [`presets/README.md`](presets/README.md)。

---

## 如何跑

### 推荐路径：Web 端全流程

```bash
# 1. 克隆 + 环境
git clone https://github.com/CalWade/novelforge.git
cd novelforge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 启动 Web（不用先 cp .env / 先 bootstrap）
flask --app web.app run --port 5055
# 浏览器打开 http://localhost:5055/
```

首次打开会触发**启动向导**：

1. **填 API Key**：`DEEPSEEK_API_KEY`（必填，写入 `.env`），`PERPLEXITY_API_KEY`（可选，给 FactChecker 用）。
2. **选作品**：从 3 个内置作品里挑一本激活（港综·林家耀 / 仙侠·裴长宁 / 都市言情·沈若微），或点「+ 新建作品」走 **4 步向导**（基本信息 → 题材起点三选一 → 大纲梗概 → 人物简介）新建一本。
3. 主界面出来。顶部的 **▶ 开始 / ⏹ 中断** 控制面板支持 9 种运行模式（单章 / 批量 / 出版包装 / 只重排大纲 / 只重写 / 只重评 / 只跑修复 / 只重审计 / 只刷台账），点 ⚙ 可以随时改 API Key。

切换作品、编辑元信息（`project.yaml / outline.json / characters.yaml / timeline.yaml / era.md / ...`）、看每次 LLM 调用、查技术债——全部在浏览器里。详细页面说明见 [`docs/web-ui-guide.md`](docs/web-ui-guide.md)。

### CLI 路径（脚本化 / CI）

```bash
cp .env.example .env
# 在 .env 里填入 DEEPSEEK_API_KEY

python -m src.bootstrap --list-presets                        # 看所有可用起点模板
python -m src.bootstrap --list                                # 看所有作品
python -m src.bootstrap --project gangster-hk-1983-linjiayao  # 激活"林家耀的故事"

# 新建一本书（从 preset 拷贝题材起点）
python -m src.bootstrap --new-project my-book \
    --preset gangster-hk-1983 \
    --display-name "我的港综小说" \
    --protagonist "张三" \
    --chapters 50

# 跑流水线
python -m src.pipeline --chapter 1     # 跑一章（全流水线）
python -m src.pipeline --range 1-3     # 跑一到三章
python -m src.pipeline --audit-only 1  # 只重跑 3 个 Auditor
python -m src.pipeline --packaging     # 跑出版包装

# 按阶段重跑（不烧全流水线预算）
python -m src.pipeline --plan-only 3        # 只重做第 3 章节拍表
python -m src.pipeline --write-only 3       # 只重写第 3 章正文（复用现有 plan.json）
python -m src.pipeline --evaluate-only 3    # 只重审第 3 章
python -m src.pipeline --fix-only 3         # 只跑一次 Fixer（用现有 verdict.json）
python -m src.pipeline --bookkeeping-only 3 # 人工改过正文后，重刷所有账本

# 从原著拆题材（覆盖当前作品的 era.md / *-extra.md / resource_schema.yaml）
python -m src.pipeline --extract-genre my-book --sources novels/a.txt,novels/b.txt

# 造一个新的 preset（供后续新作品做起点）
python -m src.genre_extractor --to-preset my-new-preset --sources novels/a.txt,novels/b.txt
```

CLI 和 Web **调用同一套 Python 函数**（`src.bootstrap.bootstrap_project` / `src.pipeline.run_*`）——不是两套平行实现，不会漂移。

---

## 项目结构

```
novelforge/
├── AGENTS.md                        # 运行时目录页（state 地图 + Agent 名册）
├── README.md                        # 本文件
├── CHANGELOG.md                     # 发布变更日志
├── requirements.txt
├── .env.example
│
├── rules/                           # 通用规则（题材无关）
│   ├── 00-information-priority.md   # 信息源优先级（冲突仲裁协议 R1..R5）
│   ├── 24-iron-laws.md              # 28 条通用铁律
│   ├── 18-landmines.md              # 18 个通用雷点（含高疲劳词黑名单）
│   ├── writing-style-core.md        # 通用写作风格（六步分析 + 代入感六支柱 + Show-Don't-Tell）
│   └── deny-phrases-{zh,en}.txt     # Tier-1 deny-phrase 正则扫描清单
│
├── presets/                         # 新建作品的可选起点模板库（运行时不参与）
│   ├── README.md
│   ├── gangster-hk-1983/            # 港综起点（含 resource_schema）
│   ├── xianxia-ascension/           # 仙侠起点（含 resource_schema）
│   └── urban-romance-contemporary/  # 都市言情起点（无 resource_schema）
│
├── projects/                        # 作品层：一本书 = 这个目录下的一个子目录
│   ├── README.md
│   ├── .active                      # 单行文本，记录当前激活的作品 id
│   ├── gangster-hk-1983-linjiayao/  # 林家耀的故事
│   │   ├── project.yaml             # 可选字段 source_preset: gangster-hk-1983
│   │   ├── outline.json / characters.yaml / timeline.yaml
│   │   ├── era.md / writing-style-extra.md / iron-laws-extra.md  # 题材文件直接住这
│   │   ├── resource_schema.yaml     # 可选
│   │   └── state/                   # .gitignore；运行时拷入 + Agent 写入
│   ├── xianxia-ascension-peichangning/   # 裴长宁飞升记
│   └── urban-romance-shenruowei/    # 沈若微记事
│
├── novels/                          # 小说素材大池子（gitignore，只保留 README）
│                                    # "从原著拆题材"的默认输入路径
│
├── src/
│   ├── config.py                    # 环境变量 + 路径 · STATE_DIR 动态指向当前作品 state/
│   ├── llm.py                       # OpenAI 兼容的 chat 客户端 + 自动写 prompts_log.jsonl
│   ├── blackboard.py                # shim → src/core/blackboard.py（向后兼容）
│   ├── bootstrap.py                 # 把 projects/<id>/ 拷进 state/ + 合成 setting.yaml
│   ├── pipeline.py                  # 主循环 + 按阶段重跑 + --extract-genre 子命令
│   ├── core/                        # 通用抽象
│   │   ├── blackboard.py            # 原子写 / jsonl 追加 / yaml 读写
│   │   └── base_agent.py            # 所有 Agent 的基类
│   ├── agents/                      # 5 创作 + 3 记账 Agent + OutlineDrafter / CharactersDrafter
│   ├── auditors/                    # 3 后台审计 Agent（含 FactChecker）
│   ├── genre_extractor/             # 从原著拆题材（CLI：--to-preset；被 pipeline --extract-genre 复用）
│   │   ├── pipeline.py / __main__.py
│   │   ├── to_preset.py / to_project.py  # 两个产物出口
│   │   ├── schemas.py / adaptive.py / chapter_detector.py / chapter_stream.py
│   │   ├── tally.py / trial.py / interview.py
│   │   ├── agents/                  # Extractor/Drafter/Validator/Fixer + ArcMerger/BookDistiller
│   │   └── auditors/                # FactChecker/ConsistencyGuard/StyleGuard（Validator 扇出）
│   └── tools/                       # Lint / 质量仪表盘 / Evaluator 校准
│
├── web/                             # Flask 动态版 UI（本地运行）
│   ├── app.py                       # 路由：作品 / preset / 素材 / 运行 / 环境
│   ├── templates/
│   │   ├── index.html               # 作品首页（/）
│   │   ├── presets/                 # preset 子站：index / detail / extract / progress
│   │   └── novels/                  # 素材库子站：index
│   └── static/                      # 三套独立 CSS+JS：main / presets / novels
│
├── docs/                            # 架构文档 + GitHub Pages 静态演示
│   ├── web-ui-guide.md              # Web UI 页面与 API 手册
│   ├── Agent 搭建难题.md            # 5 条长链路 Agent 经验总结
│   ├── superpowers/specs/           # 设计规格
│   ├── history/                     # 历史/决策脉络档案（只读归档）
│   └── index.html + main.*          # GitHub Pages 静态演示页
│
├── tests/                           # pytest 测试套件
└── evaluator_calibration/           # Evaluator 校准集
```

---

## Web 演示页 · 三面板

系统有两套 UI：

- **`web/` Flask 动态版**：**默认入口**（见 [如何跑 · 推荐路径](#推荐路径web-端全流程)）。读本地 `state/` 实时刷新，按钮真的会调流水线；支持首次启动向导、9 种运行模式、作品切换、.env 在线编辑、源文件可视化修改（`PUT /api/project-files` 会 `preserve_progress` 地重新 seed 到 state/）、中断正在运行的 pipeline（协作式 `CANCEL_EVENT`）
- **`docs/` 静态只读版**：读冻结的快照目录，纯展示用（GitHub Pages 托管）

两套都是三面板布局：

- **左侧**：`state/` 文件树。点任意文件 → 右侧显示内容
- **中间**：当前章节正文（Markdown 渲染）/ 技术债表格 / 规则浏览
- **右侧**（三个切换页）：
  - **Prompt 检查器**：每次 LLM 调用的完整记录，按时间倒序。色彩标注是哪个 Agent 在说话，展开后能看到这次调用读了哪些文件、完整的 system + user + 模型输出、以及"全新会话 · N tokens"标签。这是系统的"可观测性核心"——每一次调用的来龙去脉都在这里。
  - **难题对照**：5 条 Agent 搭建难题 ↔ 代码落点的可点击交叉引用
  - **日志**：密集的时间线日志视图
- **顶部横幅**（静态版）：`[港综 · 1983]` `[仙侠 · 飞升]` 作品切换器，浏览器本地缓存会记住你的选择

---

## 技术栈

- Python 3.9+（本地 3.9.6 + CI 跑 3.9/3.11/3.12/3.13）
- `httpx` — LLM 客户端（不用官方 SDK，走 OpenAI 兼容协议）
- `flask` — 动态版 UI
- `pyyaml` — 黑板存储
- `python-dotenv` — 读取 `.env` 配置
- **不用任何 Agent 框架**（LangChain / CrewAI / AutoGen 一概不用）

**默认 LLM**：DeepSeek-V4-Pro（通过 EasyClaw 平台的 OpenAI 兼容代理访问）

---

## 测试

```bash
python -m pytest tests/ -v
```

pytest 套件覆盖：

- `test_blackboard.py` — 原子写 / jsonl 顺序保证 / YAML 往返
- `test_verdict_schema.py` — Evaluator JSON 评分表校验 + 骨架检测器
- `test_multi_level_summarizer.py` — 章摘 / 弧摘 / 卷摘的边界与上下文组装
- `test_packaging.py` — 出版包装 Agent
- `test_setting_lint.py` + `test_bootstrap_and_settings.py` — 作品文件校验 + 可选资源定义注入/切换清理
- `test_status_card_updater.py` / `test_hook_keeper.py` / `test_resource_ledger.py` — 3 个记账 Agent 的 prompt 构造 + 数据隔离边界
- `test_planner_extensions.py` / `test_generator_extensions.py` / `test_evaluator_fixer_extensions.py` — 章节类型 / 场景推进项 / 写作自检 / 风格锁定 / 信息源优先级字段
- `test_pipeline_intent_router.py` — CLI 子命令分发 + 全链路顺序验证（LLM 调用被 mock，不烧 token）
- `test_fact_checker.py` — FactChecker 的触发门控 + 联网核查 + 优雅降级
- `test_isolation_boundaries.py` — 数据隔离回归守卫（Generator/Evaluator/Summarizer 不得读账本文件）
- `test_outline_drafter.py` / `test_characters_drafter.py` — 4 步向导的两个轻量 Drafter Agent
- `test_new_project_wizard.py` — 4 步向导的端到端（stub LLM）
- `test_preset_api.py` — `/api/presets/*` 路由 + 新建 preset 从原著拆的进度机
- `test_rules_and_docs.py` + `test_web_and_pages_sync.py` — 文档即代码（`rules/00` 存在性、AGENTS.md 完整性、`docs/rules` 与 `rules/` 偏离守卫）
- `test_dashboard_bookkeeping.py` — 质量仪表盘的账本区块渲染
- `test_phase5_final_state.py` / `test_phase5_integration.py` — 重构后的文档 + 结构守卫 + 3 本内置作品的 bootstrap 冒烟

**覆盖策略**：prompt 构造（输入文件清单、必读文件）用单元测试；Agent 输出质量通过端到端运行验证（见 `docs/demo_snapshot*/` 下三个题材的实测产出，尤其 `docs/demo_snapshot_gangster_c5_10ch/` 的 10 章完整小说）。

---

## 设计文档

- **架构目录页** · [`AGENTS.md`](AGENTS.md)（运行时 state 地图 + Agent 名册）
- **Web UI 手册** · [`docs/web-ui-guide.md`](docs/web-ui-guide.md)
- **一本书的生命周期 · 整体设计** · [`docs/superpowers/specs/book-centric-workflow-design.md`](docs/superpowers/specs/book-centric-workflow-design.md)
- **5 条长链路 Agent 经验** · [`docs/Agent 搭建难题.md`](docs/Agent%20搭建难题.md)
- **作品层规范** · [`projects/README.md`](projects/README.md)
- **preset 起点模板规范** · [`presets/README.md`](presets/README.md)
- **发布变更日志** · [`CHANGELOG.md`](CHANGELOG.md)
- **历史决策档案** · [`docs/history/`](docs/history/)（gap analysis / 校准报告 / 借鉴审计等早期脉络文档，只读归档）

---

## 许可

MIT.

港综题材中「霍官泰」「李超人」「邵老板」「包船王」等是对真实历史人物的代指化处理，事件与时间线基于 1983-1985 年真实香港公开史料。仙侠题材为完全虚构。都市言情题材中的公司（腾讯 / 字节 / 阿里 / 华为等）仅作时代背景提及，不作道德褒贬。
