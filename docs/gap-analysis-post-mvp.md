# 从 MVP 到通用系统 · Gap 分析

> 定位从"黑客松 3 章 MVP"升级到"大而全通用多 Agent 小说写作系统"之后，
> 针对教程贴借鉴审计（108 条）+ 现有系统形态做的 Gap 分析 + 补齐方案。
>
> 首次起草：2026-05-10（MVP 提交后）· Oracle 第三轮评审
> 最后更新：2026-05-11（Must+Should 主体落地、C-5 港综 10 章长跑 + C-10 Evaluator 校准完成后）
> 前两轮评审：docs/superpowers/specs/2026-05-09-novelforge-design.md § Oracle 事前/事后评审

---

## 当前进度速览（2026-05-11）

| 维度 | Must | Should | Could | Won't |
|---|---|---|---|---|
| **总条目** | 9 | 18 | 11 | 24 |
| **✅ 已落地** | **9 / 9** | **12 / 18** | 1 / 11 | — |
| **❌ 仍挂着** | 0 | 6 | 10 | — |

所有 Must 全部扫清。Should 层还剩 6 条（B-2 LogicGuard / B-4 细节扩写 / B-5 六步走强制 / B-6 全员在线 / B-7 节奏仪表 / C-11 Fixer 动态配额）。
详见下文每条的 ✅/❌ 标记和[优先级汇总](#优先级汇总moscow)。

---

## 前情回顾

### 过去两轮评审的约束

- **第一轮（事前）**：24 小时黑客松交付，单人开发，≤10MB zip。建议砍 Auditor（4→2）、砍 TimelineGuard/FactGuard、Summarizer 独立角色、加 Prompt Inspector UI。
- **第二轮（事后）**：Evaluator 对后修稿返回占位骨架（`"…"`）导致 ch1/ch3 false-pass。建议加 skeleton detector、修 README 谎言、加 Lesson→code crosswalk。

### 当前系统形态（2026-05-11）

- **11 个 Agent**（5 创作 + 3 记账 + 3 审计）+ Setting Pack 抽象层
  - 5 创作：Planner / Generator / Evaluator / Fixer / Summarizer
  - 3 记账：StatusCardUpdater / HookKeeper / ResourceLedger（可选）
  - 3 审计：AISlopGuard / CharacterGuard / FactChecker（按需触发）
  - 另有 PackagingAgent（一次性运行）+ ArcSummarizer / BookSummarizer（L2/L3 多级摘要）
- **3 个 Setting**：港综 1983（✅ 跑过 10 章）/ 仙侠飞升（✅ 跑过 3 章）/ 都市言情·深圳（⚠️ 结构完整未跑 LLM）
- **108 条教程借鉴**：已落地 90+ 条（tutorial-borrowings-audit.md 待更新到最新状态）
- **288 个 pytest 用例**（覆盖 blackboard I/O / 每个 Agent 的 prompt 构造 / pipeline 全链路 / 记账隔离 / 文档偏离守卫）
- **Evaluator 校准集**：10 case，3 轮迭代后达到 100% overall_pass 一致性 / 100% recall / 58.6% precision
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

**✅ 已落地（2026-05）**——`src/agents/packaging.py` 已存在并跑通。

**实际实现**：
- Agent：`src/agents/packaging.py`（`PackagingAgent`）
- 入口：`python -m src.pipeline --packaging`
- 产出：`state/packaging.json`（书名候选 + 简介 + 小剧场 + 封面提示 + 标签）
- 测试：`tests/test_packaging.py`

**与原设计的差异**：
- 没做单独的 `PackagingEvaluator`——`PackagingAgent` 内部做了一次自检，产出 `_validation_warnings` 字段供 UI 显示
- 没做 `rules/packaging-rubric.md` 独立规则——规则直接内嵌在 Agent system prompt
- 这两处简化没造成质量问题，保留

---

### A-5 · 创作自检 Checklist（教程贴 §二·12）

**当时砍的原因**：Evaluator 已做事后检查，"自己评自己乐观"是 Anthropic 踩过的坑。

**✅ 已落地（2026-05 · 重开方案）**——放在 **Planner** 侧实现，不是 Generator 自检。

**实际实现**：
- Planner 的 `plan.json` 新增 `writing_self_check` 字段（6 项风险扫描表：ooc / info_leak / setting_conflict / power_scaling / pacing / vocab_fatigue）
- 每项为 Planner 基于 outline + 状态卡 + 前情预判的 ≤30 字具体提示（或"无"）
- Generator 读 plan 时将此表渲染成 Markdown 表格拼进 system prompt，在产出时主动规避
- 详见 skill-borrowings-plan.md #14

**为什么重开**：skill 借鉴计划揭示了一个让这条能做的形态——"生成前自检"放在 **Planner**（不是 Generator）就不违反 Lesson 2，因为 Planner 本就是评估者而非执笔者。

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

**✅ 已落地（2026-05，skill 借鉴升级到 4 条新 iron_law）**——见 `rules/24-iron-laws.md`（实际 28 条）。

**实际新增**：
- `iron_law_25 · 信息越界禁令`：反派行动必须可追溯到其已知信息
- `iron_law_26 · 伏笔账本同步`：大剧情节点必须更新 pending_hooks.md
- `iron_law_27 · 资源结算禁模糊`：禁"暴涨/海量/难以估量"这类跳过结算的词
- `iron_law_28 · 风格锁定`：同一作品不得跑出题材基调

（比原计划的"严禁无脑后宫 / 严禁设定吃书"更通用，直接采纳 skill-borrowings-plan.md 的方案）

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

| # | 条目 | 新决议 | 工作量 | 进度 |
|---|---|---|---|---|
| A-1 | 联网搜索（受限 tool-call） | **Must** | 10h | **✅ 已落地** · FactChecker 按 landmine_13 触发 Perplexity Sonar，[c5-10ch-validation-report.md](c5-10ch-validation-report.md) |
| A-2 | Domain Knowledge 卡片机制 | **Should** | 6h | ❌ 仍挂着（C-5 10 章跑过没触发领域专家需求） |
| A-3 | 写作练习示例 | Won't | — | — |
| A-4 | 书名/简介/发布包装 Agent | **Must** | 10h | **✅ 已落地** · `src/agents/packaging.py` + `python -m src.pipeline --packaging` |
| A-5 | 创作自检 | **Should**（重开，Planner 侧） | 3h | **✅ 已落地** · Planner `writing_self_check` 字段 |
| A-6 | 梗提炼知识卡 | **Should** | 3h | ❌ 仍挂着 |
| A-7 | 5 个领域专家 Agent | Won't（并入 A-1） | — | — |
| A-8 | 影视剧知识 | Won't | — | — |
| A-9 | 补通用严禁为 iron_law_25/26 | **Should** | 1.5h → 3h | **✅ 已落地** · 扩到 4 条（iron_law_25-28） |
| A-10 | 其他 25 条 | Won't | — | — |

**维度 A 进度**：**4 Must / 5 Should 中 4 Must 全完成、2 Should 完成**。剩 A-2 / A-6 未做。

---

## 维度 B：🟡 部分借鉴项升级（26 项 → 审议 8 条关键）

以下 8 条是审计里标 🟡 但实际"一半都没做"或"做了但机制薄弱"的。

---

### B-1 · 交叉验证从"双源"升级到"多源"（审计 1.3）

**✅ 已落地（2026-05）**——skill-borrowings 升级为"**信息源优先级协议**"，比原"多源验证"方案更完整。

**实际实现**：
- 新文件：`rules/00-information-priority.md`（9 级优先级 + R1..R5 仲裁规则 + 4 个 worked examples）
- Evaluator system prompt 加载此规则（作为第 6 份参考规则）
- Fixer system prompt 引用此规则的 R1（正文是 ground truth 原则），指导冲突时反向修状态卡而非回改正文
- 测试：`tests/test_evaluator_fixer_extensions.py` + `tests/test_rules_and_docs.py` 双重回归守卫

**为什么比原计划好**：原来只想"多源验证 + external_checks 字段"。skill 揭示真正缺的不是"再加一个数据源"而是"冲突时按谁"——这是协议问题，不是数据源问题。

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

**🟡 部分落地（2026-05）**——数据层完成，可视化层未做。

**已完成部分**：
- Planner 的 plan.json 现在要求每个 scene 标注 `advances: [信息|地位|资源|伤亡|仇恨|境界]`（见 skill-borrowings C-29）
- 同时要求标注 `chapter_type: 战斗|布局|过渡|回收`
- Generator 根据 chapter_type 切换强调点（_chapter_type_emphasis()）

**待做**：
- 把 advances 字段汇总到 `state/pacing.json`
- Web UI 画热力图（章号 × 推进项）
- Planner 下一章决定时读这张表

**为什么还没做**：当前数据已经可供编辑人工审读，UI 可视化是锦上添花。等 10 章长跑证明编辑真会去查这个数据时再做。

**工作量**：剩余 2h（加汇总脚本 + UI）

---

### B-8 · 作品包装（审计 5.5 的书名/简介部分 + landmine_16）

**✅ 已在 A-4 覆盖**。

`PackagingAgent` 产出 `state/packaging.json` 时做了书名/简介/封面提示/标签的综合包装。

---

## 维度 B 小结

| # | 条目 | 新决议 | 工作量 | 进度 |
|---|---|---|---|---|
| B-1 | 交叉验证多源化 → 信息源优先级 | Should（升级） | 3h | **✅ 已落地** · `rules/00-information-priority.md`（9 级优先级 + R1..R5） |
| B-2 | 独立 LogicGuard | Should | 5h | ❌ 仍挂着 |
| B-3 | 历史考据动态化 | 并入 A-1 | — | **✅ 由 A-1 覆盖** |
| B-4 | DetailAmplifier | Should | 5h | ❌ 仍挂着 |
| B-5 | 六步走 → plan.json 结构化 | Should | 4h | 🟡 部分落地（Planner writing_self_check 已有，但"六步走"字段还没强制化） |
| B-6 | 人物 presence 跟踪 | Could | 3h | ❌ 仍挂着（但 status card + pending_hooks 部分覆盖） |
| B-7 | 节奏仪表 | Should | 4h → 2h | 🟡 数据层完成（advances + chapter_type），UI 未做 |
| B-8 | 作品包装 | 并入 A-4 | — | **✅ 由 A-4 覆盖** |

**维度 B 进度**：**3 Should 完成 / 2 Should 部分完成 / 2 Should 未做（B-2 LogicGuard + B-4 DetailAmplifier）+ 1 Could 未做**。

**维度 B 合计工作量：24h（含 Could）**

---

## 维度 C：通用系统新增需求

下面逐条判断用户给出的 16 个候选 + 我的补充。

---

### C-1 · 更多 Setting 示例（都市言情 / 赛博 / 科幻 / 历史 / 灵异）

**✅ 部分落地（2026-05）**——新增第三个 setting（都市言情·深圳）。

**已完成**：
- `settings/urban-romance-contemporary/` 完整 7 文件（7 必需，无 resource_schema 刻意不数值化）
- 人物 6 个（女主沈若微 / 男主林昭宇 / 闺蜜顾安安 / 同事赵恺 / VP 季凛 / 沈母）
- 10 章大纲 + 2024-10 到 2026 的 timeline
- 题材特有铁律 8 条（iron_law_25..32）
- 通过 `python -m src.tools.setting_lint --setting urban-romance-contemporary` 验证 0 errors

**未做**：
- 都市言情**没跑 LLM**（成年人的情感叙事审读成本高，仙侠跑过 3 章已足够证明题材无关性）
- 赛博朋克 / 科幻 / 历史 / 灵意骨架都没做

**为什么现在够**：C-5 10 章长跑（港综）已经证明"同一套架构能稳定跑"；`setting_lint` 能保证"任何用户自己写的 setting 都能被检出问题"。题材丰富度是**演示需求**而非**架构需求**，等用户真用起来再扩。

---

### C-2 · Setting Lint 工具（`python -m src.tools.setting_lint`）

**✅ 已落地（2026-05）**——`src/tools/setting_lint.py`（500 行）+ 18 个测试。

**实际检查项**：
1. 7 个必需文件 + 1 个可选文件（`resource_schema.yaml`）都存在 + 基本 schema 对 ✅
2. outline.json 章节的 key_characters 名字 ⊆ characters.yaml（不一致报 WARNING）✅
3. outline 跨度的 year_month ⊆ timeline.yaml 覆盖范围 ✅
4. characters.yaml 每个角色有 traits / redlines / motivation ✅
5. era.md ≥ 500 字 / writing-style-extra.md ≥ 300 字 / iron-laws-extra.md ≥ 3 条铁律 ✅
6. resource_schema.yaml（可选）结构合法：resources 列表 / 每个资源有 id/display_name/unit/description / validation 段 ✅
7. "黄金三章"检查（前 3 章 beats 齐全、有 opening/closing hook 等）✅
8. 禁词扫描（era.md 不得含"MVP/黑客松/hackathon"这种 meta 词）✅

**额外能力**：三个真实 setting 全部通过 `--all` 模式 0 errors（用 pytest 做回归守卫）

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

**✅ 已落地（2026-05-11）**——港综 10 章完整长跑成功。详见 [c5-10ch-validation-report.md](c5-10ch-validation-report.md)。

**实际数据**：
- 完成 10 / 10 章 ✅
- Evaluator 首过率 100%（0 hits）
- Fixer retry 0 次
- 总时长 68 分钟 / 92 次 LLM 调用 / 753k tokens
- 小说总长 45,113 字（均章 4,511 字，超出 3000 字目标 50%）

**关键架构验证通过**：
- Lesson-3 bookkeeping 三层账本在 ch10 仍能精确引用 ch1 的伏笔（`identity-1` 全程追踪）
- HookKeeper 真的在"回收"伏笔（首次 retire 在 ch5）
- Multi-level summarizer 在 ch5 / ch10 自动触发 arc summary
- FactChecker 正确未触发（landmine_13 全章未命中，印证 era.md 静态设定够用）
- 章节时长线性增长（297s → 495s），**未出现上下文爆炸**

**衍生产物**：
- `demo_snapshot_gangster_c5_10ch/`
- `docs/dashboards/gangster-c5-10ch.md`
- 未做的：`drift_analysis.py` 对比脚本——原因是 10 章数据已经人眼可读且仪表盘已覆盖指标对比

---

### C-6 · 导出成品小说（epub / pdf）

**❌ 未做**。用户在 2026-05-11 的对话中明确暂缓。

**当前仍建议**：Should 级。什么时候做看需求——如果项目走向"对外发布"阶段（GitHub Pages demo 变成可下载 EPUB 的演示），这是必须做的；如果只做架构研究，可以无限推迟。

**建议工作量**：5h（ebooklib 单次集成）

---

### C-7 · 协作编辑

**❌ 不做 / 维持 Won't**。

（原文理由不变）

---

### C-8 · 质量度量仪表盘（AI 味走势 / debt 累积 / landmine 频率）

**✅ 已落地（2026-05）**——`src/tools/dashboard.py` + `python -m src.tools.dashboard --dir demo_snapshot --out docs/dashboards/xxx.md`。

**实际产出**：
- **章节进展表**：字数 / 耗时 / retries / Eval.hits / AI 味 / OOC / 结果
- **Landmine 命中频率表**
- **Agent 调用统计**（次数 / 平均耗时 / 平均 tokens / 总 tokens / 错误数）
- **Bookkeeping 账本状态表**（C-23/C-24/C-25 落地后加的）
- **待偿技术债表**
- **Evaluator 校验警告汇总**

**已有仪表盘产出**（可直接查阅）：
- `docs/dashboards/gangster-3ch-mvp.md`
- `docs/dashboards/xianxia-3ch.md`
- `docs/dashboards/gangster-10ch-long-run.md`
- `docs/dashboards/gangster-c5-10ch.md`

**测试**：`tests/test_dashboard_bookkeeping.py`（5 个用例覆盖 bookkeeping 小节的各种状态）

**Web UI 仪表板 tab 未做**——因为命令行产出的 Markdown 已经能直接在 GitHub 上渲染查看，Web UI 再画一遍重复了。

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

**✅ 已落地（2026-05，三轮迭代）** — 详见 [`docs/c10-evaluator-calibration-report.md`](c10-evaluator-calibration-report.md)

**实际落点**：
- `evaluator_calibration/cases/*.yaml` — 10 个测试 case（2 clean + 8 各植入 1-2 个 landmine，正文 1400-1800 字贴近真实章节）
- `src/tools/calibrate_evaluator.py` — 批量跑 + 混淆矩阵计算
- `evaluator_calibration/reports/` — 每次跑自动产出 JSON + Markdown 报告
- `evaluator_calibration/cases-short-backup/` — T1 时的短 case，保留作历史对照
- CLI: `python -m src.tools.calibrate_evaluator --concurrency 5`（~85s 跑完 10 case）

**三轮数据进化**：
| 轮次 | 改动 | Pass 一致 | Recall | Precision |
|---|---|---|---|---|
| T1 baseline | 500 字短 case | 70% | 62.5% | 41.3% |
| T2 | case 扩到 1400-1800 字 | 80% | 75.0% | 37.8% |
| **T3** | 叙事层专项自查 + 命中稀疏化（Evaluator prompt） | **100%** ✅ | **100%** ✅ | **58.6%** ✅ |

**T1 时暴露的三大盲区**（T3 全部修复）：
- `landmine_13` 漏判（1983 年 iPhone）
- `landmine_4 + 9` 漏判（POV 跳换 + 无过渡切场）
- `landmine_8 + 15` 漏判（快速敌人撤退 / 无代价胜利）

**修复手段**（见 `src/agents/evaluator.py`）：
1. 在 Evaluator system prompt 加一段「叙事技术层专项自查」，强制扫描 landmine_4/8/9/15 这 4 条
2. 加「命中稀疏化原则」，防止 AI 见坏扩散命中 8+ 个 landmine

**价值**：
- **A-1 FactChecker 链路救活** —— landmine_13 现在能稳定命中，FactChecker 才会被触发
- **任何未来改 Evaluator prompt 的改动**都有定量回归基线可用
- C-5 10 章长跑的"10/10 0 hits 干净数据"**置信度提升**

**工作量**：总 6h（初版 2h + 扩 case 1.5h + prompt 调优 1h + 报告 1.5h）

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

**✅ 已落地（2026-05，commit `e4f0eef`）**——`src/agents/multi_level_summarizer.py`。

**实际实现**：
- **L1 章摘**（≤300 字，现有 Summarizer，每章生成）
- **L2 弧摘**（≤600 字，ArcSummarizer，每 5 章触发：ch5 / ch10 / ch15 ...）
- **L3 卷摘**（≤1200 字，BookSummarizer，每 20 章触发：ch20 / ch40 ...）
- **上下文组装助手**：`assemble_long_chain_context()`，Planner 按距离衰减读（最近 2 章 L1 + 最近 1 个 L2 + 最近 1 个 L3）

**与原计划差异**：弧窗口从 10 章缩到 5 章（更快见反馈），卷窗口从 50 章降到 20 章（更符合实际长度）。skill-borrowings 的"按相关性读摘要"进一步细化了 Planner 读法。

**C-5 长跑验证**：10 章跑完自动生成 arc-01.md（ch1-5）+ arc-02.md（ch6-10），各 2000 字左右，叙述连贯。

**测试**：`tests/test_multi_level_summarizer.py`（210 行，覆盖边界函数 + 上下文组装）

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

**✅ 已落地**——`src/agents/_verdict_schema.py`（256 行）+ `tests/test_verdict_schema.py`。

**实际实现**：
- `validate_verdict(raw) -> {clean_verdict, validation_warnings, skeleton_detected}`
- 检测 evidence / where 字段是否为占位符（`…` / `...` / 空串 / `<string>` 等 5 种形态）
- 服务端重算 overall_pass（不信 LLM 自评），规则：任何 high → fail；≥2 medium → fail
- 非法 severity 强制 coerce 到 `medium`
- 坏 JSON 输入合成一份"failed verdict"并标 `skeleton_detected=true`

**测试**：19 个用例覆盖所有 edge case（skeleton、缺字段、错类型、hit=truthy 非 bool、无占位符通过、等等）

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

| # | 候选 | 决议 | 工作量 | 进度 |
|---|---|---|---|---|
| C-1a | 都市言情 setting 跑通 | **Must** → 降为骨架 | 12h → 6h | **✅ 已落地** · setting 结构完整，lint 通过；未跑 LLM（3 题材足够证明题材无关） |
| C-1b | +1 骨架 setting（赛博/科幻） | Should | 4h | ❌ 不做（3 个题材已证明通用） |
| C-2 | Setting Lint | **Must** | 5h | **✅ 已落地** · `src/tools/setting_lint.py` + 18 测试 |
| C-3 | Setting Generator | Won't | — | — |
| C-4 | 章节编辑 UI | Should | 5h | ❌ 暂不做（Intent Router 的 `--write-only` `--bookkeeping-only` 已覆盖大部分场景） |
| C-5 | 10+ 章长链路验证 | **Must** | 9h | **✅ 已落地（港综）** · 68 分钟跑完 10 章 / 100% 首过 / 0 debt |
| C-6 | epub 导出 | Should | 5h | ❌ 用户暂缓 |
| C-7 | 协作编辑 | Won't | — | — |
| C-8 | 质量仪表盘 | **Must** | 6h | **✅ 已落地** · `src/tools/dashboard.py` + 4 份产出报告 |
| C-9 | 对比测试 | Could | 6h | ❌ 仍挂着 |
| C-10 | Evaluator 校准集 | **Must** | 4-10h | **✅ 已落地** · 10 case 三轮迭代到 100% pass 一致 / 100% recall |
| C-11 | Fixer 配额分级 | Should | 3h | ❌ 仍挂着（但 C-10 后发现当前 MAX_RETRIES=2 够用） |
| C-12 | Summarizer 多级 | **Must** | 8h | **✅ 已落地** · `multi_level_summarizer.py` L1/L2/L3 |
| C-13 | 人物关系图 | Could | 6h | ❌ 仍挂着 |
| C-14 | A/B setting diff | Could | 6h | ❌ 仍挂着 |
| C-15 | Agent 可插拔（轻量） | Should | 3h | ❌ 仍挂着 |
| C-16 | 调用 replay | Should | 3h | ❌ 仍挂着（对未来调试价值很大） |
| C-17 | Evaluator schema + skeleton detector | **Must** | 2h | **✅ 已落地** · `_verdict_schema.py` + 19 测试 |
| C-18 | LLM 统一重试层 | Should | 4h | ❌ 仍挂着 |
| C-19 | rules 覆写机制 | Should | 2h | ❌ 仍挂着 |
| C-20 | Cost 统计 | 合并 C-8 | — | **✅ dashboard 已含 Agent 调用统计 / 平均 tokens / 总 tokens** |
| C-21 | CI | Should | 2h | ❌ 仍挂着（268 测试本地手动跑） |

### 维度 C 扩展（skill 借鉴新增，2026-05）

| # | 候选 | 决议 | 工作量 | 进度 |
|---|---|---|---|---|
| C-22 | Intent Router（按阶段重跑） | Should | 8h | **✅ 已落地** · `--plan-only` / `--write-only` / `--evaluate-only` / `--fix-only` / `--bookkeeping-only` 5 个 CLI 子命令 |
| C-23 | Current Status Card + StatusCardUpdater | **Must** | 10h | **✅ 已落地** · 三层账本首层，Lesson-3 Context Reset 的入口 |
| C-24 | Resource Ledger + resource_schema.yaml（setting 可选） | Should | 8h | **✅ 已落地** · 港综 + 仙侠有 schema，都市言情刻意不数值化 |
| C-25 | Pending Hooks + HookKeeper | Should | 6h | **✅ 已落地** · 伏笔池真实"回收"（C-5 跑时 ch5 首次 retire） |
| C-26 | AISlopGuard 疲劳词黑名单 | **Must** | 1.5h | **✅ 已落地** · 6 类高识别词单章限 1 次 |
| C-27 | Fixer 4 档修改分级（润色/改写/重写/续写） | **Must** | 0.5h | **✅ 已落地** |
| C-28 | Generator 动笔前 7 问 | **Must** | 1h | **✅ 已落地** · Generator system prompt 铁律后新增 |
| C-29 | 章节类型分化（战斗/布局/过渡/回收） | Should | 4h | **✅ 已落地** · plan.json.chapter_type + scenes[].advances |
| C-30 | 设定场景化强制（禁百科复述） | **Must** | 0.5h | **✅ 已落地** · Generator 第 8 条铁律 |
| C-31 | 黄金三章反馈检 | Could | 2h | **✅ 已落地** · Planner ch3 特化分支 |
| C-32 | 风格锁定 prohibited_styles | Should | 2h | **✅ 已落地** · 3 个 setting 都声明禁止风格列表 |

**维度 C 进度**：
- **9 Must 全部完成**（C-2 / C-5 / C-8 / C-10 / C-12 / C-17 / C-23 / C-26 / C-27 / C-28 / C-30）
- **5 Should 完成**（C-22 / C-24 / C-25 / C-29 / C-32）
- **1 Could 完成**（C-31）
- **Won't 维持**：C-3 / C-7
- **剩余未做**：C-4 / C-6 / C-9 / C-11 / C-13 / C-14 / C-15 / C-16 / C-18 / C-19 / C-21

---

## 优先级汇总（MoSCoW）

### 🔴 Must — 系统称得上"通用完整"的硬条件

| # | 条目 | h | 状态 |
|---|---|---|---|
| A-1 | Websearch（Evaluator 按需触发） | 10 | ✅ 完成 |
| A-4 | PackagingAgent（书名/简介/封面提示） | 10 | ✅ 完成 |
| C-1a | 都市言情 setting（结构） | 12 | ✅ 完成（未跑 LLM） |
| C-2 | Setting Lint | 5 | ✅ 完成 |
| C-5 | 10+ 章长链路验证 | 9 | ✅ 完成（港综） |
| C-8 | 质量仪表盘 | 6 | ✅ 完成 |
| C-10 | Evaluator 校准集 | 4-10 | ✅ 完成 |
| C-12 | Summarizer 多级 | 8 | ✅ 完成 |
| C-17 | Evaluator schema + skeleton detector | 2 | ✅ 完成 |
| C-23 | Current Status Card + StatusCardUpdater | 10 | ✅ 完成（skill 新增） |
| C-26 | AISlopGuard 疲劳词黑名单 | 1.5 | ✅ 完成 |
| C-27 | Fixer 4 档分级 | 0.5 | ✅ 完成 |
| C-28 | Generator 动笔 7 问 | 1 | ✅ 完成 |
| C-30 | 设定场景化强制 | 0.5 | ✅ 完成 |

**Must 总计 14 条 · 全部完成 ✅** · 实际工时 ~85h

### 🟡 Should — 显著提升但非必须

| # | 条目 | h | 状态 |
|---|---|---|---|
| A-2 | 领域专家知识卡 | 6 | ❌ 未做 |
| A-5 | Planner writing_self_check | 3 | ✅ 完成（重开） |
| A-6 | 梗提炼知识卡 | 3 | ❌ 未做 |
| A-9 | 4 条新 iron_law | 3 | ✅ 完成 |
| B-1 | 信息源优先级协议 | 3 | ✅ 完成 |
| B-2 | 独立 LogicGuard | 5 | ❌ 未做 |
| B-4 | DetailAmplifier | 5 | ❌ 未做 |
| B-5 | 六步走 plan.json 结构化 | 4 | 🟡 部分（writing_self_check 覆盖一半） |
| B-7 | 节奏仪表 | 4 | 🟡 部分（数据层完成，UI 未做） |
| C-1b | +1 骨架 setting | 4 | ❌ 不做（3 题材够） |
| C-4 | 章节编辑 UI | 5 | ❌ 未做（Intent Router 部分覆盖） |
| C-6 | epub 导出 | 5 | ❌ 暂缓 |
| C-10+ | 校准集扩到 30 case | 6 | ❌ 不做（10 case 够用） |
| C-11 | Fixer 配额分级 | 3 | ❌ 未做 |
| C-15 | Agent 轻量可插拔 | 3 | ❌ 未做 |
| C-16 | 调用 replay | 3 | ❌ 未做（高价值） |
| C-18 | LLM 统一重试层 | 4 | ❌ 未做 |
| C-19 | rules 覆写机制 | 2 | ❌ 未做 |
| C-21 | CI | 2 | ❌ 未做 |
| C-22 | Intent Router | 8 | ✅ 完成 |
| C-24 | Resource Ledger（可选） | 8 | ✅ 完成 |
| C-25 | Pending Hooks + HookKeeper | 6 | ✅ 完成 |
| C-29 | 章节类型分化 | 4 | ✅ 完成 |
| C-32 | 风格锁定 prohibited_styles | 2 | ✅ 完成 |

**Should 总计 24 条 · 完成 12 / 部分 2 / 未做 10**

### 🟢 Could — 锦上添花

| # | 条目 | h | 状态 |
|---|---|---|---|
| B-6 | 人物 presence 跟踪 | 3 | ❌ 未做（但 status card 部分覆盖） |
| C-9 | 对比测试 | 6 | ❌ 未做 |
| C-13 | 人物关系图 | 6 | ❌ 未做 |
| C-14 | A/B setting diff | 6 | ❌ 未做 |
| C-31 | 黄金三章反馈检 | 2 | ✅ 完成 |

**Could 总计 5 条 · 完成 1 / 未做 4**

### ⚫ Won't — 明确不做

| # | 条目 | 理由 |
|---|---|---|
| A-3 | 教程贴写作练习示例 | 会污染 Generator 语气 |
| A-7 | 5 个领域专家 Agent | 已并入 A-1 |
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

## 工程量总估

### 已完成工时（2026-05-11 止）

| 层 | 条目数 | 工时 |
|---|---|---|
| Must | 14 / 14 | ~85h |
| Should | 12 / 24（含部分） | ~50h |
| Could | 1 / 5 | ~2h |
| **实际合计** | **27 / 43** | **~137h** |

### 剩余工作量

| 层 | 剩余 | 工时 |
|---|---|---|
| Should 未做 | 10 条 | ~40h |
| Could 未做 | 4 条 | ~21h |
| **剩余合计** | **14 条** | **~61h** |

完成所有 Should 后再做 Could，可以把系统推到"成熟的小众商用工具"水平。但**需要明确**：**Must 已全部完成，继续做的每一条都是在做"从好到更好"，ROI 会递减。**

---

## 下一阶段建议（2026-05-11 重写）

原"第一周 5 项"全部完成（C-17/C-10/C-2/C-5/C-8）。当前**真正有战略价值**的下一步不是继续砸 Should 清单，而是：

### 🥇 高价值 · 验证类

| # | 任务 | h | 为什么 |
|---|---|---|---|
| 1 | **xianxia 10 章长跑 + 对照报告** | 3-4h + $2 | 证明"题材无关"不是营销词。当前只有港综一个题材跑过 10 章 |
| 2 | **人眼审读 gangster 10 章** | 3-4h | 所有指标都是机器判官。一次真人深度审读能暴露机器永远看不到的盲区 |
| 3 | **Oracle 第四轮评审** | 4h | 三轮评审都在 MVP 完成前做的。现在应该让 Oracle 评"做完了该往哪走" |

### 🥈 中价值 · 基础设施类

| # | 任务 | h |
|---|---|---|
| C-16 | 调用 replay 系统 | 3h |
| C-21 | CI（GitHub Actions） | 2h |
| C-18 | LLM 统一重试层 | 4h |

### 🥉 低价值 · 锦上添花类

| # | 任务 | h |
|---|---|---|
| B-7 | 节奏可视化 UI | 2h（剩余） |
| C-6 | epub 导出 | 5h |
| C-9 | A/B 对比测试 | 6h |

**推荐组合**：先做验证类三条（~10h + $2），拿到真实反馈再决定是否继续向基础设施类推进。不建议直接砸剩余 Should 清单——那是典型的"过度工程"陷阱。

---

## 关键风险与红线

1. **不要同时做多个新机制 × 新题材**。每一条都会污染 prompts_log，堆起来无法 debug。串行做。
2. **维持"创作 + 记账 + 审计"三层上限**：当前 5 创作 + 3 记账 + 3 审计，不要继续加。新功能优先考虑**扩充现有 Agent 能力**（写进 system prompt），而非新增 Agent。
3. **prompts_log.jsonl 在长跑中会膨胀**：10 章 92 条 → 50 章 ~450 条 → 长篇满 1000 条。目前没分片，未来做 `logs/prompts_log-YYYY-MM.jsonl` 按月分片。已加入待做清单（非紧急）。
4. **Evaluator 是系统命门**。C-10 校准集已从 70% 做到 100% 一致性。**以后任何 Evaluator prompt 改动都必须先跑一次校准集**，保证指标不倒退。这已经是工作流硬要求。
5. **Setting Generator（C-3）仍是陷阱**。生成的骨架用户都要改 80%——不做，这条维持 Won't。

---

## 总评（2026-05-11 更新）

**已达成**：从 MVP 升级到"通用完整系统"的核心路径已跑通。

五格扩展的完成状态：
- ✅ 从 1 个 setting → 3 个（港综 / 仙侠 / 都市言情，第三个刻意不数值化证明架构不强制资源账本）
- ✅ 从 3 章 → 10+ 章（港综 10 章长跑 · 100% 首过 · 0 debt）
- ✅ 从"读 era.md"→"按需 websearch"（A-1 FactChecker 按 landmine_13 触发 Perplexity）
- ✅ 从"产章节"→"产章节 + 打包发布"（PackagingAgent 产出书名 / 简介 / 封面提示）
- ✅ 从"跑完就没数据"→"每章有指标、可回看"（dashboard + 4 份已生成仪表板报告）
- ✅ 从"相信 Evaluator"→"校准 Evaluator"（C-10 三轮迭代达 100% pass 一致性）

**超额完成**：
- bookkeeping 三层账本（C-23/C-24/C-25）—— 不在原 Must 清单，但由 skill 借鉴引入，提供了 Lesson-3 Context Reset 的真正工程化落地
- 88 → 288 个测试用例（增加 200 个）
- Intent Router（按阶段重跑）让 debug 成本降低一个数量级

**遗憾未做**：
- xianxia 没跑过 10 章（题材对照证据薄）
- 没有一次**人眼深度审读**（所有指标都是机器判官）
- 没有 CI（288 测试本地手动跑）
- Replay 系统（每次改 prompt 都要重花 LLM 预算）

**项目当前阶段定位**：**可对外展示的架构研究项目**。继续投入的 ROI 取决于定位目标：
- 若目标是**开源演示**：做 xianxia 10 章 + epub 导出 + Oracle 第四轮评审 + CI 即收官
- 若目标是**小众写作工具**：做章节编辑 UI + 多人可复现包 + Setting 模板改进
- 若目标是**商业产品**：以上都不够，需要重新走产品定义

---

— 首次起草：Oracle · 第三轮评审（2026-05-10）
— 最新更新：2026-05-11（Must+Should 主体落地、C-5 + C-10 完成后）
