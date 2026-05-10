# 从 MVP 到通用系统 · Gap 分析

> 定位从"黑客松 3 章 MVP"升级到"大而全通用多 Agent 小说写作系统"之后，
> 针对教程贴借鉴审计（108 条）+ 现有系统形态做的 Gap 分析 + 补齐方案。
>
> 审阅日期：2026-05-10（MVP 提交后）
> 审阅者：Oracle（第三轮评审）
> 前两轮评审：docs/superpowers/specs/2026-05-09-novelforge-design.md § Oracle 事前/事后评审

---

## 前情回顾

### 过去两轮评审的约束

- **第一轮（事前）**：24 小时黑客松交付，单人开发，≤10MB zip。建议砍 Auditor（4→2）、砍 TimelineGuard/FactGuard、Summarizer 独立角色、加 Prompt Inspector UI。
- **第二轮（事后）**：Evaluator 对后修稿返回占位骨架（`"…"`）导致 ch1/ch3 false-pass。建议加 skeleton detector、修 README 谎言、加 Lesson→code crosswalk。

### 当前系统形态

- 7 个 Agent（5 主 + 2 审计）+ Setting Pack 抽象层
- 2 个 Setting（港综 1983 跑过 3 章；仙侠已搭骨架未跑 LLM）
- 108 条教程借鉴中 🟢 43 / 🟡 26 / 🔴 39
- 6 个 pytest 测试全部覆盖 blackboard I/O
- 单进程 Python，Flask UI，无数据库

### 新前提

1. 定位升级：**通用多 Agent 小说写作系统**，不是一个港综 demo
2. 时间宽松，YAGNI 不再是首要原则
3. 首要目标是**完美效果 + 系统完整**

这意味着：凡是"MVP 够用就行 / 演示看不出来 / 单人扛不动"理由砍掉的东西，都要重新判断。但**过度设计**依然是敌人——"通用完整"不等于"什么都要有"。

### 评判标准

下文每条都用这三把尺子同时衡量：

1. **效果尺**：补上之后产出的小说质量是否显著变好？
2. **完整性尺**：不补的话"通用系统"的承诺是否缺一块？
3. **复杂度尺**：补上之后是否让系统从"简单 7 Agent 流水线"变成"28 个调度器无人能读"？

凡是三尺都过关才建议做。

---

## 维度 A：🔴 未借鉴项重审（39 项）

教程贴借鉴审计中 🔴 = 39 条。绝大多数是"§前言 12 条通用指令"（不适用）或"联网搜索类"（架构决策）。本节只审在新前提下**有复议价值**的 14 条。其余 25 条维持 🔴，原因见小节末。

---

### A-1 · 联网搜索能力（审计 1.1 / 1.2 / 1.12）

**当时砍的原因**：爬取不可靠、延迟高、海外访问香港资料困难、成本不可控。

**✅ 已落地（2026-05）** · 按 skill-borrowings-plan.md 的修订方案：

最终形态与原计划有两点不同：
1. **不是 Generator 主动触发**（Generator 仍无网），而是**独立的 FactChecker 审计员**
2. **每章至多 3 次搜索**（由 Planner 抽的可查证断言上限决定），不是 Generator 每段一次

**实际实现**（见 commits `ebf49dd+`）：

- `src/tools/websearch.py` — Perplexity Sonar OpenAI-compat 客户端
  - 端点 `https://work-api-srv.easyclaw.cn/api/v1/search/chat/completions`
  - 文件缓存（md5(query+model) → state/websearch_cache/\*.json）
  - state/websearch_log.jsonl 记录每次调用（Inspector 可见）
  - `WebSearchUnavailable` 异常：未配置 API key 或网络错误时抛出，调用方优雅降级

- `src/auditors/fact_checker.py` — 第三个 auditor（和 AISlopGuard/CharacterGuard 平行）
  - **触发条件**（`should_run()`）：Evaluator 写入的 verdict.json 中 `landmine_13.hit=true` 且 severity ∈ {medium, high}
  - **流程**：读 chNNN.md + verdict.json 的 landmine_13 evidence + era.md → LLM 抽 0-3 条可查证断言 → 每条 1 次 Perplexity 查询 → 合并为 `state/fixes/chNNN.fact-patch.md`
  - **Lesson-3 边界**：不读 plan/issues/summaries；不改 verdict；不作 pass/fail 门，纯建议性补丁

- `src/pipeline.py` — audit fan-out 条件加入 FactChecker
  - `--audit-only N` 也会按 should_run 自动包含

**配置**（`.env`）：
```
PERPLEXITY_API_KEY=dc-sk-...
PERPLEXITY_BASE_URL=https://work-api-srv.easyclaw.cn/api/v1/search
PERPLEXITY_MODEL=perplexity/sonar-pro
```
留空则 FactChecker 优雅降级（写一份"未配置"占位 patch，不影响其他 agent）。

**测试**：`tests/test_fact_checker.py` · 26 个 pytest 用例
- websearch 缓存 / 降级 / HTTP 错误 / 网络错误
- should_run 对各种 verdict 状态（未命中/low/medium/high/坏 JSON）
- FactChecker prompt 构建（含/不含 era.md）
- handle_output 5 个分支（无 claims / 无 API / 解析失败 / 正常 / ≤3 claims 封顶）
- pipeline 集成（landmine_13 未命中 → 跳过；medium 命中 → 加入 fan-out）

**为什么不做独立 FactGuard Agent**：独立 Agent 就要完整读一章 + 抽所有事实去查，80% 查到的都是已经对的。tool-call 模式只在"作者需要/评审怀疑"时触发，信噪比高得多。

**落点**：
- 新文件：`src/tools/websearch.py`（~80 行，httpx + 缓存）
- 新文件：`src/tools/__init__.py`
- 修改：`src/agents/generator.py`（加 post-process 扫描 `<<SEARCH:>>`）
- 修改：`src/agents/evaluator.py`（命中 landmine_13 且 evidence 含数据时触发）
- 新配置：`.env` 增加 `SEARCH_API_KEY`

**工作量**：10h（含外部 API key、缓存、失败回退、测试）

**判定**：**必做（Must）**。这是"通用系统"对真实世界开的唯一一个口，没有它就永远是"凭 era.md 静态事实的 LLM"。但限制范围（Generator 按需 + Evaluator 疑似触发），绝不做 "每章扫描全文去验证"。

---

### A-2 · 14 个角色中的 5 个领域专家（军火 / 股票 / 雇佣兵 / 金融 / 军事）

**当时砍的原因**：3 章 MVP 没写到这些场景；setting pack 的 era.md 已经覆盖了一部分经济数据。

**新前提下决议**：**拒绝做独立 Agent，但升级为"领域知识卡"机制**。

**为什么拒绝独立 Agent**：
- 5 个独立 Agent = 每章额外 5 次 LLM 调用 = 5 倍 token 和延迟，收益低（大部分章节不涉及这些领域）。
- 领域专家本质是"拿数据说话"，和 A-1 的 websearch tool 大量重叠。
- 通用系统应该让**用户**决定哪些领域在本 setting 里重要（军火在港综重要，但在言情不重要），而不是强行每个 setting 都跑 5 个领域审计。

**正确形态**：在 Setting Pack 里加**可选的**知识卡文件 `settings/<name>/domain-knowledge/*.md`，Generator 根据 plan 的 scene.domain_tags 按需加载（而不是全量读）。

**具体怎么补**：

1. Setting Pack 目录规约新增可选目录：
   ```
   settings/gangster-hk-1983/domain-knowledge/
   ├── firearms.md       # 港警制式手枪、黑市军火、价格
   ├── hk-stock.md       # 恒指、地产股、1987 崩盘
   └── triad-structure.md  # 十四 K / 和胜和组织架构
   ```
2. `outline.json` 里每个 chapter 加可选字段 `domain_tags: [firearms, hk-stock]`。
3. Planner 产出 plan 时继承 domain_tags 给 scenes。
4. Generator 扫描当前章 scenes 的 domain_tags，动态从 `state/domain-knowledge/*.md` 里 include 对应文件。
5. Bootstrap 同步拷贝 `domain-knowledge/` 目录到 `state/`。

**落点**：
- 修改：`src/bootstrap.py` SETTING_FILES 增加 `domain-knowledge/` 扫描
- 修改：`src/agents/generator.py` 加 `_load_domain_knowledge(plan)` 
- 修改：`src/agents/planner.py` 保留 domain_tags
- 新文档：`settings/README.md` 加 domain-knowledge 章节
- 每个 setting 按需写 2-3 份知识卡

**工作量**：6h（代码 3h + 港综 setting 写 3 份知识卡 3h）

**判定**：**应做（Should）**。这是"通用"和"专用"之间的正确抽象——系统提供机制，设置包选择用不用。不做独立 Agent 是对的，但"连 domain knowledge 这层都没有"不符合通用平台定位。

---

### A-3 · 教程贴的写作练习与教学示例（§五·2 避免流水账 2 方法 / §五·3 开篇 3 错误）

**当时砍的原因**：系统目标是产章节不是教 LLM，原理已进 iron_law 和 landmine。

**新前提下决议**：**保持 🔴，不采纳**。

**为什么**：
- 原理已完整进 `iron_law_4`（拒绝流水账）、`landmine_1`（开篇拖沓）。
- 教程贴里的教学示例（催债电话、下水道手机）是**中文写作教学语料**，硬塞进 Generator 的 system prompt 会污染语气——Generator 会试图模仿催债场景的风格。
- 真正需要的不是"教例子"而是"few-shot 展示优秀章节"，这个需求更干净地归到 A-6（Few-shot 高质量样本库）。

**判定**：**不做（Won't）**。这条之前砍得对，现在也不做。

---

### A-4 · 书名 / 简介 / 发布包装

**当时砍的原因**：MVP 是写章节，不是出版工作流。

**新前提下决议**：**应做（Should）**，但不是一个大 Agent，而是一个独立 `PackagingAgent` + 独立执行入口。

**为什么新前提下要做**：
- "通用完整系统"必须能从大纲 → 章节 → 完本包装走完一条龙。缺书名/简介等于少了一个章节产出之后的收尾动作。
- 教程贴 §16 对书名/简介的要求完整，拿来当 PackagingAgent 的 rubric 即可。

**具体形态**：
- 新 Agent：`src/agents/packaging.py`
- 入口：`python -m src.pipeline --package`（当完成全部章节，或随时手动触发）
- 读：`outline.json` + `characters.yaml` + 前 3 章正文 + 最新一章（体现风格稳定）
- 写：`state/package/book-title-candidates.md`（3-5 个候选 + 测试分数）+ `state/package/blurb.md`（300 字内简介 + 小剧场）+ `state/package/cover-prompt.md`（给画图工具的描述）
- Rubric：直接搬教程贴 §16（题材+核心爽点+主角行为）+ 番茄榜单观察到的书名模式
- 配套 `PackagingEvaluator`：用"书名与简介是否贴合 outline 和 chapter tone"做 JSON 评分

**落点**：
- 新文件：`src/agents/packaging.py`（~180 行）
- 新文件：`src/agents/packaging_evaluator.py`（~120 行）
- 新规则：`rules/packaging-rubric.md`（书名/简介的黄金法则，从教程贴 L1423-1463 提取）
- 修改：`src/pipeline.py` 增加 `run_packaging()` 入口
- UI：在 Web 加"查看发布包装"tab

**工作量**：10h（两个 Agent + 规则 + UI 对接）

**判定**：**必做（Must）**。通用小说系统的产物不应该是"3 个 .md"，而是"一本可发布的书"。缺这一环能感觉到断臂。

---

### A-5 · 创作自检 Checklist（教程贴 §二·12）

**当时砍的原因**：Evaluator 已做事后检查，"自己评自己乐观"是 Anthropic 踩过的坑。

**新前提下决议**：**不做（Won't）**。这条之前砍得对。

**为什么**：
- 教程贴原文是"生成前自检"（作者自己做一遍）。如果让 Generator 在产出前先自检，就等于把 Evaluator 的职责前移到 Generator——违反 Lesson 2（Planner/Generator/Evaluator 分离）。
- 真想要"生成前"的防线，应该让 Planner 的产出 JSON 多一个字段 `pre_generation_risks: [...]`，由 Planner（不是 Generator）基于 outline 预判本章可能踩哪些雷，Generator 读这个提示避雷。这本质是**增强 Planner**，不是新增自检 Agent。
- 这个增强很便宜（5 行 prompt），但不算"采纳教程贴原样"，归入 Must-do-small（见 B-5）。

**判定**：**不做原样，改为增强 Planner**（见 B-5）。

---

### A-6 · "梗的艺术"与时代感（原生梗提炼，教程 §二·3）

**当前状态**：审计列为 🟢（已进 iron_law_6），但审计时把它当"吸收完成"是过度乐观——规则文件里只写了原则，Generator 并不知道怎么**具体提炼**一个梗。

**实际差距**：iron_law_6 说"将后世梗提炼精神内核用年代语境说出来"，但没有任何示例。LLM 拿到"精神内核"四个字会编出什么谁都不知道。

**新前提下决议**：**应做（Should）**。需要做一个梗知识卡 + few-shot。

**具体怎么补**：

1. 新文件 `rules/meme-extraction.md`：10-20 个"后世梗 → 年代说法"对照例子（不是照搬教程，而是从网文 actual 港综里摘），每个例子标注"精神内核是什么"。
2. Generator 的 system prompt 加载它，作为"如果场景需要幽默元素参考这里"。
3. AISlopGuard 加一条检测："出现穿越后世梗"（如主角 1983 说"栓Q"）直接 high severity。

**落点**：
- 新文件：`rules/meme-extraction.md`
- 修改：`src/agents/generator.py` 加载
- 修改：`src/auditors/ai_slop_guard.py` AI_SLOP_CRITERIA 新增一条

**工作量**：3h（主要是挑选、写对照例子）

**判定**：**应做（Should）**。成本低收益高。

---

### A-7 · 经济金融 / 股票 / 军火 / 雇佣兵数据（审计 2.7-2.10）

**当时砍的原因**：3 章没写到 + era.md 覆盖了一部分。

**新前提下决议**：**不再按"每个领域一个 Agent"做**，并入 A-1（websearch tool）和 A-2（domain-knowledge 知识卡）两条解决。

**判定**：**已在 A-1/A-2 覆盖**，本条不单独立项。

---

### A-8 · 电影电视剧痴迷（审计 2.6）

**当时砍的原因**：已通过 era.md 注入流行文化事实。

**新前提下决议**：**维持 🔴，不采纳**。

**为什么**：这个角色本质是"影视知识供给者"，在 Setting Pack 形态下就是 era.md 的一部分。做独立 Agent 是冗余。真要增强，加一个可选文件 `settings/<name>/pop-culture.md`（电影/音乐/节目年表），并入 A-2 的 domain-knowledge 机制。

**判定**：**不做（Won't）**，有需要的 setting 自己加 pop-culture 知识卡。

---

### A-9 · 「严禁甚至无铺垫」等教程贴残留"严禁"条目中未独立化的部分

审计显示教程贴 24 条严禁中有 15 条独立、4 条部分覆盖、5 条因架构/题材差异未纳入。"严禁甚至无铺垫"→ iron_law_23（审计列为 🟢），但还有几条模糊：

| 教程严禁 | 当前状态 | 建议 |
|---|---|---|
| 严禁不查证写军事（L1575） | 仅 iron_law_10 部分覆盖 | A-1 websearch 解决 |
| 严禁无脑后宫（L1557） | 仅 🟡（港综 + 仙侠 extra 各自处理） | 在 rules/24-iron-laws.md 加 iron_law_25（通用） |
| 严禁设定吃书（L1565） | 🟡 部分覆盖 | 加 `iron_law_26`：已确立的设定/能力/空间大小等，后续变化必须有过程 |
| 严禁主角双标（L1555） | 🟡 | 已有 iron_law_1/7 覆盖，不单独加 |
| 严禁跪舔洋人（L1551） | 🟢 只在港综 extra | 维持题材特有 |

**新前提下决议**：**应做（Should）**，补全 iron_law_25 / iron_law_26 进通用铁律。

**工作量**：1.5h

**判定**：**应做（Should）**。

---

### A-10 · 其余不采纳的 🔴 条目

以下 25 条 🔴 在新前提下依然是 **不做（Won't）**：

| 条目 | 维持 🔴 的理由 |
|---|---|
| 前言 1.4-1.11（Markdown/LaTeX/Graphviz/语气规范/专业影响力等） | 非小说写作指令，是 LLM 通用回答格式规范，不适用 |
| 前言 1.5（直言不讳/犀利幽默） | 已在 Evaluator persona 吸收，不需要再普及到其他 Agent |
| §三·5 书名设定 / §三·6 简介设定 | A-4 已覆盖 |
| §三·4 章节设定中"800-1000 章"具体值 | 这是 setting 特有参数，已在 `setting.yaml.chapter_count_target` 里 |
| §三·7 写作依据 a（联网搜索） | A-1 已覆盖 |
| 教程开头"你是专家"类 persona 指令 | 和 Agent persona 不是一个层次 |

这些都是"教程贴适用的是作者-LLM 对话，系统用不上"类型。

---

## 维度 A 小结

| # | 条目 | 新决议 | 工作量 |
|---|---|---|---|
| A-1 | 联网搜索（受限 tool-call） | **Must** | 10h |
| A-2 | Domain Knowledge 卡片机制 | **Should** | 6h |
| A-3 | 写作练习示例 | Won't | — |
| A-4 | 书名/简介/发布包装 Agent | **Must** | 10h |
| A-5 | 创作自检（原样） | Won't（改为 B-5 增强 Planner） | — |
| A-6 | 梗提炼知识卡 | **Should** | 3h |
| A-7 | 5 个领域专家 Agent | Won't（并入 A-1/A-2） | — |
| A-8 | 影视剧知识 | Won't | — |
| A-9 | 补通用严禁为 iron_law_25/26 | **Should** | 1.5h |
| A-10 | 其他 25 条 | Won't | — |

**维度 A 合计工作量：30.5h**

---

## 维度 B：🟡 部分借鉴项升级（26 项 → 审议 8 条关键）

以下 8 条是审计里标 🟡 但实际"一半都没做"或"做了但机制薄弱"的。

---

### B-1 · 交叉验证从"双源"升级到"多源"（审计 1.3）

**当前形态**：Evaluator 交叉核查 characters.yaml + timeline.yaml。

**不足**：
- 两个文件都是 setting 自己提供的，本质是**自洽验证**而非真实世界验证。
- 没有版本漂移检测：如果 era.md 说 1983 茶餐厅菠萝包 $2，而 timeline.yaml 说 1983 物价指数 CPI=X，两者不一定互相核对。

**完整形态**：
- Evaluator 读 era.md 中的"数据表"段落（物价/事件/人名列表），与 timeline.yaml 互相交叉
- 涉及具体历史事实时触发 A-1 websearch 做第三源
- 产出 verdict.external_checks 字段记录"哪几条数据查了，一致/冲突"

**落点**：`src/agents/evaluator.py`，extend `_build_prompts`  约 40 行

**工作量**：3h（依赖 A-1 完成）

**判定**：**Should**，A-1 做完顺手做。

---

### B-2 · 独立 LogicGuard（审计 2.13 "逻辑死磕官"）

**当前形态**：Evaluator 的交叉核查 + iron_law_1 + iron_law_15 部分覆盖。

**不足**：教程贴的"逻辑死磕官"有一个很具体的动作——"每个情节反问三次"。Evaluator 检查的是**结果**（人设是否一致），不是**过程**（每一步动机是否站得住）。一章可能整体通过 Evaluator，但其中某段"主角为什么突然去找 X"是说不通的。

**完整形态**：独立 `LogicGuard` 审计 Agent，和 CharacterGuard 并列。
- 读：chNNN.md + plan.json（是，这个 Agent 是少数需要读 plan 的——它要对比"原计划动机"和"成稿表现"是否一致）
- 任务：对每一个 scene，反问"主角为什么这么做？利益算计是什么？和他的性格底色一致吗？"输出每个场景的 `motivation_score` + 问题列表
- 写：`state/fixes/chNNN.logic-patch.md`

**落点**：
- 新文件：`src/auditors/logic_guard.py`（~150 行，模板类似 CharacterGuard）
- 修改：`src/pipeline.py` Fan-Out 从 2 扩到 3

**工作量**：5h

**判定**：**Should**。这是从 🟡 升级到 🟢 的关键条目，而且收益明确——"动机不通"是 AI 小说最常见的扣分点。

---

### B-3 · 历史考据官（审计 2.1）从静态升级到动态

**当前形态**：timeline.yaml 静态注入。

**不足**：Timeline 覆盖不到边缘事实（"1984 年香港中学的校服是什么样？"），目前只能靠 Generator 编。

**完整形态**：不是做独立 Agent（那又回到被砍的 TimelineGuard 老路），而是 **让 Generator 在写具体年代细节时用 A-1 的 websearch tool 主动查**。

**落点**：A-1 完成后自然覆盖。

**判定**：**在 A-1 内实现**，不单独立项。

---

### B-4 · 细节堆砌（审计 2.14）从规则升级到独立扩写能力

**当前形态**：iron_law_20「重要剧情必须细节堆砌」写在规则里。

**不足**：Generator 写第一遍时为了赶字数容易略过细节，Evaluator 只能说"细节不够"，Fixer 只能在原文上小修。没有一个"专门挑出稀薄段落然后扩写"的能力。

**完整形态**：新 Agent `DetailAmplifier`，不是审计而是**半生成**：
- 读：chNNN.md + verdict 中 landmine_20（若命中） + iron_law_20
- 任务：找到被 Evaluator 标记为"一笔带过"的段落，就地扩写到 2-3 倍（但不改变情节走向）
- 写：覆盖 chNNN.md（像 Fixer 一样）

**触发条件**：只在 Evaluator 命中 landmine_20 且 severity=medium/high 时触发，不每章跑。

**为什么不是 Fixer 兼任**：Fixer 的定位是"只修不重写"（temp 0.5），扩写需要更强的创作能力（temp 0.7+）。两个角色职责重叠但强度不同。

**落点**：
- 新文件：`src/agents/detail_amplifier.py`（~130 行）
- 修改：`src/pipeline.py` retry loop 根据 verdict 决定调 Fixer 还是 DetailAmplifier

**工作量**：5h

**判定**：**Should**。对"细节不够"这类问题 Fixer 确实改不动，加一个针对性更强的 agent 值得。

---

### B-5 · 角色构建六步走从规则升级为 Planner 强制步骤

**当前形态**：六步走写在 `rules/writing-style-core.md`，但只有 Generator 读到它，且只是"参考"级别。

**不足**：没有强制证据表明 Planner 在出 plan 时做过六步走；也没有证据表明 Generator 的产出真的体现了六步走。

**完整形态**：
- Planner 的 plan.json schema 新增字段 `character_arc_checks`：对本章重要角色，每人按六步走打一个 JSON（每一步状态：已确立/本章新增/本章测试）。
- Generator 的 system prompt 读取这个字段，按章节"本章需要体现角色哪一步成长"来安排场景。
- 相当于把"隐式规则"变成 plan.json 里的"显式结构化 checklist"。

**顺便解决 A-5**：Planner 同时出 `pre_generation_risks`，给 Generator 避雷。

**落点**：
- 修改：`src/agents/planner.py` 约 50 行（schema + system prompt 扩展）
- 修改：`src/agents/generator.py` 读取新字段
- 小心不要让 plan.json 膨胀到人看不懂——这是主要风险

**工作量**：4h

**判定**：**Should**。从 🟡 升到 🟢 的关键。

---

### B-6 · "全员在线"（审计 3.4）人物跟踪升级

**当前形态**：CharacterGuard 检查 OOC，但不检查"哪些角色应该出现却没出现"（人物遗漏）。

**不足**：多线并行时（A 线主角去谈判，B 线配角被追杀），很容易写着写着"忘了 B 线配角这几章在干嘛"。当前没机制抓。

**完整形态**：
- Summarizer 产出时额外维护一份 `state/characters-presence.jsonl`：每章记录"哪些角色出场、简述其处境"。
- CharacterGuard 读这份文件 + 本章，检查"上一章说配角 X 在 Y 地有事，这一章他出场了却没提那事"之类的遗漏。

**落点**：
- 修改：`src/agents/summarizer.py`（加 presence 产出）
- 修改：`src/auditors/character_guard.py`（读 presence）

**工作量**：3h

**判定**：**Could**。长篇（10+ 章）才会显现价值，3 章 demo 看不出来。但通用系统承诺长链，必须有这个机制。

---

### B-7 · 节奏控制（审计 3.6）从规则升级到 pacing 仪表

**当前形态**：iron_law_16 规则化。

**不足**：无可视化的节奏数据。长篇小说读者感知的节奏是"多少章高潮 / 多少章日常 / 爽点间距"，这是可度量的。

**完整形态**：在 Summarizer 产出时标记本章类型 `chapter_tag: setup / conflict / climax / breather`，pipeline 汇总到 `state/pacing.json`，Web UI 画一个节奏分布图。Planner 下一章决定时读这张表，避免连续 5 章都是 setup。

**落点**：
- 修改：`src/agents/summarizer.py`（加 chapter_tag 输出）
- 新文件：`web/static/pacing-panel.js`（或者直接在现有 panel 加）
- 修改：`src/agents/planner.py`（读 pacing.json 决定是否插高潮）

**工作量**：4h

**判定**：**Should**。节奏控制是长篇通用系统的定义性能力。

---

### B-8 · 作品包装（审计 5.5 的书名/简介部分 + landmine_16）

**当前形态**：landmine_16「作品包装」部分借鉴（只检查不生成）。

**不足**：只能骂"包装不好"，不能产出包装。

**完整形态**：合并到 A-4（PackagingAgent），landmine_16 由 PackagingEvaluator 作为专项评分。

**判定**：**已在 A-4 覆盖**。

---

## 维度 B 小结

| # | 条目 | 新决议 | 工作量 |
|---|---|---|---|
| B-1 | 交叉验证多源化 | Should（依赖 A-1） | 3h |
| B-2 | 独立 LogicGuard | Should | 5h |
| B-3 | 历史考据动态化 | 并入 A-1 | — |
| B-4 | DetailAmplifier | Should | 5h |
| B-5 | 六步走 → plan.json 结构化 | Should | 4h |
| B-6 | 人物 presence 跟踪 | Could | 3h |
| B-7 | 节奏仪表 | Should | 4h |
| B-8 | 作品包装 | 并入 A-4 | — |

**维度 B 合计工作量：24h（含 Could）**

---

## 维度 C：通用系统新增需求

下面逐条判断用户给出的 16 个候选 + 我的补充。

---

### C-1 · 更多 Setting 示例（都市言情 / 赛博 / 科幻 / 历史 / 灵异）

**判定**：**Should 做 1-2 个 + Could 做其余**。

**理由**：
- 当前只有港综 + 仙侠 = 2，且仙侠还没跑过 LLM，"通用"的承诺很虚。
- 至少需要**一个完全不同的类别**真跑 LLM 做出 3 章，才能证明系统没题材偏见。推荐：**都市言情**（跟港综/仙侠三角互补 + 读者群最大）。
- 赛博朋克/科幻/历史/灵异属于锦上添花，做成"骨架完整、未跑"即可（和仙侠现状一样）。

**工作量**：
- 都市言情完整 setting + 跑 3 章：12h（含写 7 个 setting 文件 6h + LLM 跑 + 调 4h + demo snapshot 2h）
- 其他 2 个骨架：每个 4h

**推荐范围**：都市言情（Must）+ 1 个骨架（如赛博朋克，Should）。

---

### C-2 · Setting Lint 工具（`python -m src.setting_lint`）

**判定**：**Must**。

**理由**：
- 通用系统必须有"设置包质量门卫"。当前 bootstrap 只检查 7 个文件存在，但不检查"characters.yaml 里的角色名是否都出现在 outline 里"、"timeline.yaml 时间跨度是否覆盖 outline 章节"等一致性。
- 没有 lint，用户自己写的 setting 跑起来会炸得莫名其妙。

**具体检查项**：
1. 7 个文件都存在 + 基本 schema 对
2. outline.json 章节的 cast 名字 ⊆ characters.yaml 里的名字
3. outline 跨度的时间窗口 ⊆ timeline.yaml 覆盖范围
4. characters.yaml 里每个角色都有 traits / redlines / motivation
5. writing-style-extra.md 至少 20 行（避免空文件）
6. iron-laws-extra.md 里的 iron_law_extra_N 编号不和通用 iron_law_N 冲突
7. era.md 至少有"物价"、"地理"、"文化"三个主题（通过 heading 检测）

**落点**：
- 新文件：`src/setting_lint.py`（~200 行）
- 集成：bootstrap 默认跑 lint，失败阻止激活（加 `--force` 开关）

**工作量**：5h

---

### C-3 · Setting 生成器（关键词 → 骨架）

**判定**：**Could**，优先级低。

**理由**：
- 听起来好用，但实际上"一键生成 7 个文件"的成品基本不可用，用户还是要改 80%。
- 真正需要的是**模板**（复制 xianxia 改），不是**生成**。
- 做出来会让系统看起来华丽，但是陷阱——模板驱动的 setting 容易出现"东西都对但都浅"，对系统输出质量有反效果。

**如果要做**：限制为"**生成 setting.yaml + outline.json 前 3 章骨架**"，其余 5 个文件留空给用户填。即便如此也要 8h。

**判定**：**Won't（第一轮），Could（做完 Must+Should 后再考虑）**。

---

### C-4 · 章节编辑 UI（手工编辑 chapter 后触发重审）

**判定**：**Should**。

**理由**：
- 当前 Web UI 只读。但通用系统的用户是作者，作者写完/改完要能触发"重新审"。
- 实际形态：chapter 视图加"编辑"按钮 → 触发 `/api/chapter/edit` → 保存 → 触发 `run_audit_only(n)`（已有）。

**落点**：
- 修改：`web/app.py`（加 POST 路由 + 简单的编辑授权——至少密码保护）
- 修改：`web/static/main.js`（textarea + 保存按钮）
- 修改：`src/pipeline.py` 已有 run_audit_only，直接复用

**工作量**：5h

---

### C-5 · 长链路验证（10+ 章证明稳定）

**判定**：**Must**。

**理由**：
- Lesson 3（Context Reset）的承诺是"跨章不漂移"，当前只有 3 章 demo 根本没验证。
- 10 章是通用系统的最低验证门槛。跑 10 章要：7 个 Agent × 10 章 ≈ 70 次 LLM 调用（按最低估算）+ 2 次 retry × 50% ≈ 20 次 + 2 auditor × 10 = 20 次 = **约 110 次 LLM 调用**，按 DeepSeek 定价 < $5，时间 ~4h 一次跑完。
- 必须检查：ch10 的 characters.yaml 遵从度 vs ch1，Generator 对 era.md 的引用频率是否衰减，Summarizer 累积误差（读 ch10 要不要动一下之前的 summary）。

**落点**：
- 运行：跑港综 setting 到 10 章
- 新脚本：`tools/drift_analysis.py`（对比 ch1 和 ch10 的 landmine 命中分布、AI 味分数走势）
- 产出：`docs/long-run-report.md`

**工作量**：运行 4h + 分析脚本 3h + 报告 2h = 9h

---

### C-6 · 导出成品小说（epub / pdf）

**判定**：**Should**。

**理由**：
- 通用小说系统的产物如果只是 `state/chapters/ch*.md` 是残废的。epub 是网文标配。
- 技术成熟：`ebooklib` 库 + markdown → epub 直接 one-shot。
- pdf 可选（LaTeX 依赖重）；MVP 只做 epub + 简单 html bundle。

**落点**：
- 新文件：`src/export/epub.py`（~100 行，ebooklib）
- 入口：`python -m src.export --format epub --setting gangster-hk-1983`
- 整合：Web UI 加下载按钮

**工作量**：5h

---

### C-7 · 协作编辑

**判定**：**Won't**。

**理由**：
- 单机工具 + 多人协作差 2 个数量级复杂度（冲突解决、权限、锁）。
- 没有明显需求。作者和 AI 协作就够了，多人介入意味着要重新审定"谁是权威"——这是个产品问题不是工程问题。

---

### C-8 · 质量度量仪表盘（AI 味走势 / debt 累积 / landmine 频率）

**判定**：**Must**。

**理由**：
- 这是**通用系统的 observability**，和单元测试同等地位。
- 当前每次跑完只有一堆 .md 和 .json，没有"综合视图"。长跑场景下必须能一眼看到"AI 味分数在 ch5 之后飙升"。

**落点**：
- 新文件：`web/static/dashboard.js`（加一个 Dashboard tab）
- 数据源：已有的 `issues.jsonl` + `debt.jsonl` + auditor fixes 里的 score
- 图表：小函数画 svg 即可，不上 d3

**工作量**：6h

---

### C-9 · 对比测试（不同 temperature / 不同 Agent 版本）

**判定**：**Could**。

**理由**：
- 对"系统开发者"有用，对"普通用户"没用。
- 实现本身便宜（pipeline 多跑一次把输出放到 variant_a/ vs variant_b/），但做个比较 UI 要 4h。
- 优先级在 Must/Should 后。

**工作量**：6h

---

### C-10 · Evaluator 校准（Evaluator 自测集）

**判定**：**Must**。

**✅ 已落地（2026-05，初版 10 case）** — 详见 [`docs/c10-evaluator-calibration-report.md`](c10-evaluator-calibration-report.md)

**实际落点**：
- `evaluator_calibration/cases/*.yaml` — 10 个测试 case（2 clean + 8 各植入 1-2 个 landmine）
- `src/tools/calibrate_evaluator.py` — 批量跑 + 混淆矩阵计算
- `evaluator_calibration/reports/` — 每次跑自动产出 JSON + Markdown 报告
- CLI: `python -m src.tools.calibrate_evaluator --concurrency 5`（90s 跑完 10 case）

**首轮基线数据（commit `c061b95` 时的 Evaluator 状态）**：
- **overall_pass 一致性 70%**（目标 ≥80% · 不及格）
- **召回 62.5%**（37.5% 植入雷被漏判）
- **精度 41.3%**（命中扩散问题）

**关键发现**：
- ✅ 干净稿 100% 放行（Evaluator 不冤枉好稿）
- 🔴 **3 类问题漏判严重**：timeline_drift（landmine_13）/ rushed-pacing（landmine_8+15）/ POV-jumping（landmine_4+9）
- ⚠️ **命中扩散偏差**：见坏稿会连锁命中更多不相关 landmine（精度偏低的主因）
- **推论**：C-5 的 "10/10 0 hits" 数据可能混有 1-2 个漏判的真问题

**下一轮升级方向**（未来 C-10+）：
- 扩 case 到 2000+ 字（更贴近真实章节长度）
- 靶向强化 landmine_4/8/9/13/15 判据
- 考虑 Evaluator 二次采样（两次 0-temp 投票降低漏判）

**工作量**：初版 10 case **已完成**（实际 3h）；完整版 30 case 暂不做（见 report 结论）

---

### C-11 · Fixer 配额控制（MAX_FIXER_RETRIES=2 升级）

**判定**：**Should**。

**理由**：
- MVP 下 2 次硬编码，通用系统应该按问题严重度分级。
- 具体：配置化 `MAX_FIXER_RETRIES` 按 severity 不同：all-low = 1 次，any-medium = 2 次，any-high = 3 次，且最后一次失败后路由到 DetailAmplifier（见 B-4）或标记 debt。

**落点**：
- 修改：`src/pipeline.py`（重写 retry loop）
- 新文件：`src/config.py` 增加 retry policy 配置

**工作量**：3h

---

### C-12 · Summarizer 多级（章节 / 弧 / 全书）

**判定**：**Must**。

**理由**：
- Lesson 3 的承诺在长篇（50+ 章）会失效——单章 300 字摘要 × 50 章 = 15000 字 context，Planner 依然被淹没。
- 真正的 Context Reset 需要分层：
  - `summaries/chNNN.md`（章级，≤300 字，现有）
  - `summaries/arc-NNN.md`（弧级，每 10 章一篇，≤600 字，新增）
  - `summaries/novel.md`（全书级，≤1500 字，每 50 章刷新一次，新增）
- Planner 按距离衰减读：最近 3 章章级 + 相关弧级 + 全书级。

**落点**：
- 新文件：`src/agents/arc_summarizer.py`（~80 行）
- 新文件：`src/agents/novel_summarizer.py`（~80 行）
- 修改：`src/pipeline.py` 每 10 章触发 arc_summarizer，每 50 章触发 novel_summarizer
- 修改：`src/agents/planner.py` 读取多级摘要

**工作量**：8h

---

### C-13 · 人物关系图（自动提取）

**判定**：**Could**。

**理由**：
- 好看，UI 上 viz 能直接抓眼球。
- 但对产出质量影响间接——关系图是"用户看"的，不是 Agent 读的。
- 如果要做，让一个 RelationMapper Agent 从 summaries 里提取（人物 A → 人物 B + 关系演变），输出 dot 文件给 UI 画。

**工作量**：6h

---

### C-14 · A/B Setting Pack diff

**判定**：**Could**。

**理由**：
- "同一 outline 两个 setting 的产出对比"——listed idea 很聪明，适合做 demo。但日常不用。
- 实现：新入口 `python -m src.compare --outline shared.json --settings A,B --chapter 1`，跑两次 Pipeline 写到 `state_A/` `state_B/`，UI 加 diff 视图。

**工作量**：6h

---

### C-15 · Agent 可插拔（换掉某个 Agent 或加新 Agent）

**判定**：**Should（但限制范围）**。

**理由**：
- 对"通用系统"是本质需求——用户可能想换一个更好的 Evaluator 或加一个 GenreAgent。
- 但**完全插件化**是深渊（类加载 / 版本管理 / 接口稳定）。
- 合理的范围：
  - 用 `src/agents/registry.py` 注册 Agent 名字 → 类映射
  - `pipeline.py` 从 registry 取 Agent 而非硬 import
  - 新增 Agent 只需在 registry 里加一行
- 这距离"可插拔"只差一个 entry_points 机制，而我们**故意不做**那一步——保持一个仓库，不做插件市场。

**落点**：
- 新文件：`src/agents/registry.py`（~40 行）
- 修改：`src/pipeline.py` 从 registry 读

**工作量**：3h

---

### C-16 · Agent 调用可复现包（给定 seed + prompts_log 重放）

**判定**：**Should**。

**理由**：
- Debug 神器。`prompts_log.jsonl` 已经记录了所有 call，加一个 replay 入口就能"用同样的 system+user 重新跑一次某个 call"——用来验证 prompt 改动有效。
- LLM 不完全确定，但 seed + temp=0 的 call 高度可复现。

**落点**：
- 新文件：`tools/replay.py`（~60 行）
- 输入：prompts_log 中某条 id
- 行为：重放该 call，diff 新旧 output

**工作量**：3h

---

### C-额外 · 我补充的候选

#### C-17 · Evaluator 结构化 JSON schema 校验 + skeleton detector 固化

**判定**：**Must**。

**理由**：事后评审中发现的 false-pass 问题还没在代码里修（只在 AGENTS.md 故障排查提了一句）。应该把"检测 `where == '…'` 或 zero hits after fixer"做成 schema 校验，不过就重试。

**落点**：`src/agents/evaluator.py` 的 `_handle_output`

**工作量**：2h

#### C-18 · 统一的 "LLM 调用容错" 层

**判定**：**Should**。

**理由**：当前 `src/llm.py` 对非 2xx 直接 raise，对 JSON 解析错误（Planner/Evaluator/Auditors 都有 `_parse_json`）各自 try/except。通用系统应该有一层统一的 retry（指数退避 + JSON schema 校验 + 占位检测）。

**落点**：`src/llm.py` 加 `chat_with_retry()`；各 Agent 改用它

**工作量**：4h

#### C-19 · 用户可编辑的 `rules/` 覆写机制

**判定**：**Should**。

**理由**：当前用户想改 iron_law_1 的措辞必须改仓库文件。通用系统应该支持用户在 `state/rules-overrides/` 里放自己的覆写，Agent 优先读 state 再回落 rules/。

**落点**：`src/agents/_base.py` 的 `_read_rule()` 加 override 查找

**工作量**：2h

#### C-20 · Cost & Token 统计

**判定**：**Should**。

**理由**：通用系统的用户会关心"一章花多少钱"。`prompts_log.jsonl` 已经有 usage，加一个汇总面板即可。

**落点**：Web UI Dashboard 加 cost tab（和 C-8 合并）

**工作量**：并入 C-8

#### C-21 · CI / GitHub Actions 跑基本测试

**判定**：**Should**。

**理由**：通用系统最低要求。当前 tests 只有 blackboard，加一个 CI 跑所有测试 + lint。

**工作量**：2h

---

## 维度 C 小结

| # | 候选 | 决议 | 工作量 |
|---|---|---|---|
| C-1a | 都市言情 setting 跑通 | **Must** | 12h |
| C-1b | +1 骨架 setting（赛博/科幻） | Should | 4h |
| C-2 | Setting Lint | **Must** | 5h |
| C-3 | Setting Generator | Won't（或延后） | — |
| C-4 | 章节编辑 UI | Should | 5h |
| C-5 | 10+ 章长链路验证 | **Must** | 9h |
| C-6 | epub 导出 | Should | 5h |
| C-7 | 协作编辑 | Won't | — |
| C-8 | 质量仪表盘 | **Must** | 6h（含 C-20） |
| C-9 | 对比测试 | Could | 6h |
| C-10 | Evaluator 校准集 | **Must** | 4-10h |
| C-11 | Fixer 配额分级 | Should | 3h |
| C-12 | Summarizer 多级 | **Must** | 8h |
| C-13 | 人物关系图 | Could | 6h |
| C-14 | A/B setting diff | Could | 6h |
| C-15 | Agent 可插拔（轻量） | Should | 3h |
| C-16 | 调用 replay | Should | 3h |
| C-17 | Evaluator schema + skeleton detector | **Must** | 2h |
| C-18 | LLM 统一重试层 | Should | 4h |
| C-19 | rules 覆写机制 | Should | 2h |
| C-20 | Cost 统计 | 合并 C-8 | — |
| C-21 | CI | Should | 2h |

**维度 C 合计工作量：~95h（含 Could）**

---

## 优先级汇总（MoSCoW）

### 🔴 Must — 系统称得上"通用完整"的硬条件

| # | 条目 | h |
|---|---|---|
| A-1 | Websearch tool-call 能力 | 10 |
| A-4 | PackagingAgent（书名/简介/封面提示） | 10 |
| C-1a | 都市言情 setting 跑通 | 12 |
| C-2 | Setting Lint | 5 |
| C-5 | 10+ 章长链路验证 | 9 |
| C-8 | 质量仪表盘（+ Cost） | 6 |
| C-10 | Evaluator 校准集（初版） | 4 |
| C-12 | Summarizer 多级 | 8 |
| C-17 | Evaluator schema + skeleton detector | 2 |

**Must 小计：66h**

### 🟡 Should — 显著提升但非必须

| # | 条目 | h |
|---|---|---|
| A-2 | Domain Knowledge 卡片机制 | 6 |
| A-6 | 梗提炼知识卡 | 3 |
| A-9 | 补通用 iron_law_25/26 | 1.5 |
| B-1 | 交叉验证多源化（并 A-1） | 3 |
| B-2 | 独立 LogicGuard | 5 |
| B-4 | DetailAmplifier | 5 |
| B-5 | 六步走 → plan.json 结构化 | 4 |
| B-7 | 节奏仪表 | 4 |
| C-1b | +1 骨架 setting | 4 |
| C-4 | 章节编辑 UI | 5 |
| C-6 | epub 导出 | 5 |
| C-10+ | Evaluator 校准升级到 30 case | 6 |
| C-11 | Fixer 配额分级 | 3 |
| C-15 | Agent 轻量可插拔 | 3 |
| C-16 | 调用 replay | 3 |
| C-18 | LLM 统一重试层 | 4 |
| C-19 | rules 覆写机制 | 2 |
| C-21 | CI | 2 |

**Should 小计：68.5h**

### 🟢 Could — 锦上添花

| # | 条目 | h |
|---|---|---|
| B-6 | 人物 presence 跟踪 | 3 |
| C-9 | 对比测试 | 6 |
| C-13 | 人物关系图 | 6 |
| C-14 | A/B setting diff | 6 |

**Could 小计：21h**

### ⚫ Won't — 明确不做

| # | 条目 | 理由 |
|---|---|---|
| A-3 | 教程贴写作练习示例 | 会污染 Generator 语气 |
| A-5 | 创作自检（原样） | 违反 Planner/Generator/Evaluator 分离（改为 B-5） |
| A-7 | 5 个领域专家 Agent | 已并入 A-1/A-2 |
| A-8 | 影视剧角色 Agent | 已进 era.md |
| A-10 | LLM 通用 persona/格式指令 25 条 | 不适用于 Agent 系统 |
| C-3 | Setting Generator | 生成的骨架用户都要改 80%，陷阱 |
| C-7 | 多人协作编辑 | 产品问题不是工程问题，跨数量级复杂 |

---

## 工程量总估

| 层 | 工时 | 天数（8h/d） |
|---|---|---|
| Must | 66h | 8.25 天 |
| Must + Should | 134.5h | 17 天 |
| Must + Should + Could | 155.5h | 19.5 天 |

### 分阶段建议

**阶段 1（2 周冲刺）**：Must 全部 → 66h
- 产出：真正"通用"的系统（支持联网 + 另一个题材跑通 + 长链路验证 + 可观测性 + Evaluator 有校准）

**阶段 2（2 周提升）**：Should 前 12 条 → 50h
- 产出：小说质量从"3 章可读"到"10 章稳定好看"

**阶段 3（1 周）**：剩余 Should + 选 1-2 个 Could → 30h
- 产出：系统成熟度接近商业工具

**总计**：约 5 周单人全职（~160h）能做到"大而全通用系统"。

这个数字是乐观估计。现实中需要加 ~30% buffer 处理 LLM 不稳定（A-1 的搜索 tool 尤其容易拖延）和调试时间。真实估算 **6-7 周**。

---

## 建议的下一步（第一周 · 5 项）

按优先级排序。每项可以独立开发，相互依赖已在"依赖"列标出。

| # | 任务 | h | 依赖 | 为什么先做 |
|---|---|---|---|---|
| 1 | **C-17 Evaluator schema + skeleton detector** | 2 | 无 | 先修已知 bug，防止所有后续长跑带病运行 |
| 2 | **C-10 Evaluator 校准集初版（10 case）** | 4 | C-17 | 没有金标准就没有办法判断后续所有改动是改好还是改坏 |
| 3 | **C-2 Setting Lint** | 5 | 无 | 基础设施，后续 C-1a 做新 setting 会频繁碰到 |
| 4 | **C-5 10 章长链路验证（跑港综）** | 9 | C-17, C-10 | 用现有系统跑 10 章，看 drift 在哪儿——这份 drift 数据**直接决定** C-12 Summarizer 多级的具体设计 |
| 5 | **C-8 质量仪表盘初版** | 6 | C-5（要有数据） | 长跑后第一件事是看数据分布，没有仪表盘就全凭手工 grep |

**第一周 26h + buffer = 30h**，中等强度单人可做完。

第一周结束时的系统状态：
- Evaluator 不会再 false-pass
- 有一份 10-case 的客观质量标尺
- 有 10 章的长跑数据 + 可视化
- 所有后续改动都能用这套基础设施衡量是否改好

**再下一步（第二周开始）**才是真正的扩展工作：A-1 websearch、C-12 多级 summarizer、A-4 Packaging、C-1a 新题材。

---

## 关键风险与红线

1. **不要同时做 A-1 + A-2 + A-4 + C-1a**。每一条都是"新机制 × 新领域"，堆在一起会把 prompts_log 搅乱到无法 debug。串行做。
2. **维持"5 主 Agent + N 审计"的上限**。加新 Agent 时认真问：它能被合并到现有 Agent 吗？目前增加到 5 主 + 3 审计（+LogicGuard + DetailAmplifier）是上限。再加就意味着架构要重新审视。
3. **prompts_log.jsonl 会爆炸**。10 章 × 多 Agent × 可能触发 retry/searche 一轮 ≈ 200+ 条；50 章就是 1000+ 条。需要做分片 + 压缩（加 C-append：`logs/prompts_log-YYYY-MM.jsonl` 按月分片）。没归入 Must 因为不紧急，但总体规划里不能忘。
4. **Evaluator 是系统的命门**。任何一个改动导致 Evaluator 召回率下降，所有下游都会出错。C-10 校准集必须先有，再改 Evaluator prompt。
5. **别做 Setting Generator**。C-3 是典型的"看起来很酷但会反噬质量"的陷阱，我在维度 C 已经拒了它，这里再强调一次——如果未来有人提出来，让他先读这份文档。

---

## 总评

现有系统的骨架**已经对**。从 MVP 升级到通用系统不需要推倒重来，只需要**把每个抽象向外扩展一格**：
- 从 1 个 setting（港综完整）→ 2-3 个（多题材覆盖）
- 从 3 章 → 10+ 章（证明长链稳定）
- 从"读 era.md"→"按需 websearch"（开一个小窗口到真实世界）
- 从"产章节"→"产章节 + 打包发布"（完整产品线）
- 从"跑完就没数据"→"每章有指标、可回看"（observability）
- 从"相信 Evaluator"→"校准 Evaluator"（可量化质量）

这五格扩展 = Must 层 = 66h。做完就是个**合格的通用系统**。再往上做到**优秀**还要 60-90h。

但这一切的前提是**C-17 Evaluator skeleton bug 先修**——现在还带着这个 bug 跑任何长链路都是在放大错误。

— Oracle · 第三轮评审
