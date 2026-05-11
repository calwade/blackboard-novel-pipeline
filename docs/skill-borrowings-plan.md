# 可跑 Skill → 系统借鉴计划

> **Source**：`docs/可跑的小说写作-skill.txt`（428 行，作者实战跑过的 skill）
> **Date**：2026-05-10
> **Last Update**：2026-05-11（C-22..C-32 全部落地完成后）
> **方法**：逐段对照 skill 内容 vs 现有系统 + `docs/gap-analysis-post-mvp.md` 清单，识别可借鉴项
> **与教程贴的根本差异**：教程贴是「思路/原则」级输入；这份 skill 是**可跑的 prompt 工程**，含大量可直接抄进现有 prompt 的语言表达、表格模板、判定规则

---

## 📊 落地状态速览（2026-05-11）

**新增 11 条（C-22..C-32）全部完成 ✅**：

| # | 条目 | 层级 | 完成状态 |
|---|---|---|---|
| C-22 | Intent Router | Should | ✅ pipeline.py 5 个 CLI 子命令 |
| C-23 | Current Status Card + StatusCardUpdater | **Must ⭐⭐** | ✅ 最高价值条目落地 |
| C-24 | Resource Ledger + schema | Should | ✅ 港综/仙侠有 schema，都市言情刻意不数值化 |
| C-25 | Pending Hooks + HookKeeper | Should | ✅ C-5 10 章跑验证伏笔真的在"回收" |
| C-26 | AISlopGuard 疲劳词黑名单 | Must | ✅ |
| C-27 | Fixer 4 档分级 | Must | ✅ |
| C-28 | Generator 动笔前 7 问 | Must | ✅ |
| C-29 | 章节类型分化 | Should | ✅ plan.json.chapter_type + scenes[].advances |
| C-30 | 设定场景化强制 | Must | ✅ Generator 第 8 条铁律 |
| C-31 | 黄金三章反馈 | Could | ✅ Planner ch3 特化分支 |
| C-32 | 风格锁定 prohibited_styles | Should | ✅ 3 个 setting 都声明 |

**升级修订 6 条全部完成**：
- A-1 Websearch（修订为 FactChecker 按 landmine_13 触发）✅
- A-5 writing_self_check（从 Planner 侧重开）✅
- A-9 补 4 条 iron_law（25-28）✅
- B-1 信息源优先级协议 ✅
- C-12 Summarizer 多级（按相关性读）✅
- C-8 质量仪表盘 ✅

**明确不采纳的 2 条维持不变**：无女主路线 / 二十二方起源真界彩蛋

**本 plan 的核心任务已全部完成。后续 skill 再次更新或新发现，可追加到本文档末尾的"第二轮借鉴"小节。**

---

## 总览统计

- skill 中识别的核心机制：**24 条**
- 🟢 直接借鉴（Must）：**8 条**
- 🟡 部分借鉴 / 改造（Should）：**9 条**
- 🟢 已在我们系统（确认对齐）：**5 条**
- 🔴 不取（冲突或不适用）：**2 条**

---

## 核心机制逐条（按 skill 原文顺序）

### 1. 任务判定（skill L13-25）

- **skill 原文**：开头就分 4 类 —— 正文创作 / 设定工作 / 质量审查 / 账本维护。讨论创意不套章节流程。
- **我们现状**：Pipeline 写死"plan→gen→eval→fix→sum→audit"单一流程。无 intent 分类。
- **借鉴价值**：🟡 中 —— 我们的入口是 `python -m src.pipeline --chapter N`，实际上已是"正文创作"固定模式；当前没有"讨论"入口。但**将来加 Web UI 对话式操作时会用到**。
- **落地方式**：暂缓；列入 `docs/gap-analysis-post-mvp.md` **新增条目 C-22 · Intent Router**（Should 层，8h）。
- **与 gap-analysis 关系**：**新增 C-22**。

### 2. 信息源优先级（skill L27-53）⭐ 高价值

- **skill 原文**：明确 6 级 fallback —
  1. 用户本轮明确要求
  2. 用户本轮贴的正文
  3. `99_当前状态卡.md`
  4. 最近正文章节
  5. `_小说设定.md` 总索引
  6. 知识库拆解资料
- **我们现状**：Evaluator 读 characters.yaml + timeline.yaml + rules，未显式优先级；冲突时无仲裁策略。
- **借鉴价值**：🟢 高 —— 这是我们缺少的**冲突仲裁协议**。长链路跑到 30+ 章时，`summaries/ch029.md` 和 `characters.yaml` 可能冲突，没有优先级就是凭 Evaluator 运气判。
- **落地方式**：
  - 在 `rules/24-iron-laws.md` 之前新增 `rules/00-information-priority.md`，5 级优先级：
    ```
    1. state/chapters/chNNN.md (最新正文) > 任何摘要
    2. state/current_status_card.md (新加，见 #6) > 旧设定
    3. state/characters.yaml + timeline.yaml > 大纲
    4. state/outline.json > 题材拆解知识
    5. rules/*.md (通用规则) 最低
    ```
  - 在 Evaluator / Fixer 的 system prompt 顶部加一句："遇到冲突按 `rules/00-information-priority.md` 仲裁；最新章节正文覆盖过期设定。"
- **与 gap-analysis 关系**：**升级 B-1（交叉验证多源化）** → 从"多源验证"变成"多源**分级**验证"。工作量调到 4h。

### 3. 最小上下文原则（skill L55-63） ⭐ 高价值

- **skill 原文**：「不要机械地每次都读满 100 章」。按任务类型决定读什么，3-10 章为常规窗口，只有长线伏笔才扩窗。
- **我们现状**：Planner 固定读 "最近 2 份 summary"；Generator 固定读 "最近 1 份 summary"。看似符合，但**50+ 章时 50 份摘要叠加仍会爆炸**。
- **借鉴价值**：🟢 高 —— 完全对齐 gap-analysis **C-12 Summarizer 多级**，且比我们规划的更具体。
- **落地方式**：
  - 实现 C-12 时，额外吸收 skill 的原则："**3-10 章常规窗口，长线伏笔才扩窗**" —— 这变成 Planner 读摘要范围的可调参数。
  - 具体实现：Planner 读「本章 plan 所涉及的 key_characters 最后出现的那几章的摘要」而不是线性最后 2 章。
- **与 gap-analysis 关系**：**升级 C-12 Summarizer 多级** → 具体化为「按相关性读摘要 + 章 / 弧 / 全书三级」，工作量从 8h 细化分解。

### 4. 当前状态卡（skill L137-147）⭐⭐ 最高价值

- **skill 原文**：`99_当前状态卡.md` 是"**唯一的当前时间点状态覆盖文件**"，记录：当前章 / 当前境界 / 当前敌我 / 当前资源 / 当前已知真相 / 当前伏笔 / 本章任务。
- **我们现状**：有 `progress.json`（章节计数、in_flight）+ `characters.yaml`（静态档案）+ `debt.jsonl`（历史债）。但**没有"当前时间点的实时快照"**。
- **借鉴价值**：🟢🟢 极高 —— 这是 **Lesson 3（Context Reset）的终极实现**。进程死了起新的，读状态卡就知道"当前时间点的一切"。比我们现在的 summaries/ 更精确、更紧凑。
- **落地方式**：
  - 新文件 `state/current_status_card.md`（markdown 表格格式）
  - 新 Agent **`StatusCardUpdater`**（第 8 个 Agent，每章末尾跑，Summarizer 之后）：
    - 读：刚产出的 ch{N}.md + 上一版 current_status_card.md + characters.yaml
    - 写：新版 current_status_card.md（覆盖式）
    - 字段（来自 skill L143）：时间/位置锚点、主角当前状态、主角本章目标与限制、当前敌我关系、当前资源与收益账本、当前伏笔与回收状态、本章任务卡
  - Planner 在写 plan 前**必读** current_status_card.md
- **与 gap-analysis 关系**：**新增 C-23 · Current Status Card**，Must 级（10h）。这是 gap-analysis 漏掉的大条目。

### 5. 账本排版规范（skill L149-159）

- **skill 原文**：状态卡、粒度账本、伏笔池、【写作自检】、【章节结算】**统一用 Markdown 表格**。一行一对象，新增字段扩表不零散。
- **我们现状**：`debt.jsonl`（jsonl）、`issues.jsonl`（jsonl）、`prompts_log.jsonl`（jsonl）—— 机器友好，人眼难读。
- **借鉴价值**：🟡 中 —— jsonl 对 Inspector UI 渲染友好但对"读一眼了解状态"差。
- **落地方式**：保留 jsonl（UI 数据源），**额外**提供 `state/current_status_card.md`（#4）、`state/debt_table.md`（C-8 仪表盘生成）作为人眼读物。
- **与 gap-analysis 关系**：和 **C-8 质量仪表盘**合并 —— 仪表盘要产出 Markdown 表格（不是单纯数据），让人可直接打开 GitHub 查看。

### 6. 数值锚点与资源账本（skill L161-175）

- **skill 原文**：`particle_ledger.md` 记录微粒数值，必须可追溯。**同类型增量不得跨数量级无说明**（>3 倍要解释稀有性，>10 倍视为异常）。
- **我们现状**：港综的"情报值"、仙侠的"灵石"没被追踪。每章都在消耗但数字靠 Generator 临场编。
- **借鉴价值**：🟡 中 —— 对**玄幻/修仙/系统流题材必要**（资源是剧情核心），对**港综的金融操盘也必要**（8 月黑色星期六赢了多少每一次都该能对账），对都市文学/悬疑文学不必要。
- **落地方式**：
  - Setting Pack 扩展：`settings/<name>/resource_schema.yaml`（可选文件），声明该题材有哪些可追踪资源
  - `state/resource_ledger.md`（新，按 resource_schema 自动生成）
  - 新 Auditor **`ResourceGuard`**（第 3 个 auditor，可选）：检查章节内宣称的资源变化是否在合理范围
- **与 gap-analysis 关系**：**新增 C-24 · Resource Ledger**，Should 级（8h）。

### 7. 伏笔池维护（skill L177-187） ⭐

- **skill 原文**：`pending_hooks.md` 唯一待回收伏笔池，字段：hook_id / 起始章节 / 类型 / 当前状态 / 最近推进 / 预期回收窗口 / 备注。三类重点：逃敌 / 未拿到的宝物 / 未解释的耳语。
- **我们现状**：**完全没有**。Generator 埋的伏笔只在它当时的 `chNNN.plan.json` 有提 `closing_hook`，之后就无人追踪。长篇 10+ 章必然漏伏笔。
- **借鉴价值**：🟢 高 —— gap-analysis 完全没提这件事，这是**长链路写作的硬需求**。对应 iron_law_15（逻辑闭环/伏笔回收）的**数据层支撑**。
- **落地方式**：
  - 新文件 `state/pending_hooks.md`（表格）
  - 新 Agent **`HookKeeper`**（和 StatusCardUpdater 合并或独立，每章末尾跑）：从 chNNN.md 中抽取新埋 hook + 识别已回收的老 hook
  - 新通用铁律 `iron_law_25 · 伏笔必须入账`（补到 `rules/24-iron-laws.md`，实际变成 25 条）
- **与 gap-analysis 关系**：**新增 C-25 · Pending Hooks Ledger**，Should 级（6h）。

### 8. 语言去油与口号约束（skill L189-199）⭐ 可直接抄的 prompt

- **skill 原文**：
  - 优先**动作、器物反应、局部感官、具体判断**制造压迫感
  - 对「冷笑」「蝼蚁」「轰然炸裂」「倒吸一口凉气」「瞳孔骤缩」「满场死寂」等**高疲劳词保持克制**，单章同一高识别词最多 1 次
  - 群像反应不要一律"全场震惊/众人倒吸凉气"，改写成 1-2 个具体角色的身体反应、判断偏差或利益震荡
- **我们现状**：`rules/writing-style-core.md` 有 Show-Don't-Tell 但**没有具体禁用词黑名单**；AISlopGuard 查了句式结构但没查**高识别疲劳词**。
- **借鉴价值**：🟢 高 —— 直接扩充 AISlopGuard 的判据和 Generator 的铁律。
- **落地方式**：
  - 在 `rules/18-landmines.md` 的 `landmine_18`（AI 味）下**补"高疲劳词"清单**：冷笑 / 蝼蚁 / 轰然炸裂 / 倒吸一口凉气 / 瞳孔骤缩 / 满场死寂 / 全场震惊 / 众人瞠目结舌 / 内心翻江倒海 / 气势如虹
  - `src/auditors/ai_slop_guard.py` 增加**判据 11 号**：同章同识别词出现 ≥2 次
  - Generator system prompt 新增一句："群像反应**禁止**写成'全场震惊/众人倒吸凉气'；改写为 1-2 个**具体角色**的身体反应或利益震荡。"
- **与 gap-analysis 关系**：工作量小，直接插入下周 C-8 附近。**新增 C-26 · AISlopGuard 疲劳词黑名单**，Must 级（1.5h）。

### 9. 混合任务编排（skill L201-215）

- **skill 原文**：多任务时按顺序处理 —— 审查+改写先列问题；设定+试写先定设定；卷纲+正文先卷纲免正文反吃大纲。
- **我们现状**：Pipeline 一条线，不支持多任务混合。
- **借鉴价值**：🟡 低 —— 我们的 pipeline 就是串行"计划→生成→评估→修"，本身已经是"先卷纲再正文"的实现。
- **落地方式**：无需额外工作。
- **与 gap-analysis 关系**：**已在系统中**（隐式实现）。

### 10. 改写边界（skill L217-229）⭐ 可直接抄

- **skill 原文**：按任务词精确控制修改幅度 —
  - **润色**：只改表达、节奏、段落呼吸，不改事实与剧情结论
  - **改写**：可改叙述顺序、画面、力度，但保留核心事实与人物动机
  - **重写**：可重构场景推进和冲突组织，但不改主设定和大事件结果
  - **续写**：只在现有文本之后向前推进，不反改前文
- **我们现状**：Fixer system prompt 写的是"**只修，不重写**"和"**±15% 字数相差**"。略粗糙，且"不添加新情节"的边界模糊。
- **借鉴价值**：🟢 高 —— 直接可抄进 Fixer prompt，明确化修改边界。
- **落地方式**：Fixer system prompt 重写开头段落，加入 4 档分级（目前只用"改写"档）：
  ```
  你的默认修改档是「改写」：可改叙述顺序、画面、力度，但必须保留核心事实
  与人物动机。绝不使用「重写」档（不改主设定和大事件结果）。
  ```
- **与 gap-analysis 关系**：0.5h 小改动，立即可做。**新增 C-27 · Fixer 修改档明确化**，Must 级（0.5h）。

### 11. 动笔前自问（skill L265-281）⭐⭐ 可直接抄

- **skill 原文**：Generator 动笔前必须自问 7 个问题：
  1. 此刻利益最大化的选择是什么？
  2. 这场冲突是谁先动手，为什么非打不可？
  3. 配角/反派是否有明确诉求、恐惧和反制？
  4. 反派当前已知信息、误判、盲区？哪些只有读者知道？
  5. 反派每一步关键动作能追溯到其已知信息？
  6. 本段靠前文已铺垫的能力/底牌解决，还是凭空掉设定？
  7. 本章收益是否能落到具体资源/微粒增量/地位变化/已回收伏笔，而不是抽象"更强了"？
- **我们现状**：Generator system prompt 有"人物动机必须利益化"但**没列出这 7 个自问**。
- **借鉴价值**：🟢🟢 极高 —— 这是可以直接搬进 Generator prompt 的「内心独白检查表」，比我们现有的抽象铁律具体得多。
- **落地方式**：
  - 把这 7 问翻译成 Generator 的「动笔前自检」section，加在 system prompt 的「铁律」之后
  - 另外把第 7 问（收益落具体）单独提出为 **iron_law_25 · 收益具体化**，避免 Generator 写"主角感到力量涌动"这种抽象描述
- **与 gap-analysis 关系**：**新增 C-28 · Generator 动笔 7 问**，Must 级（1h）。

### 12. 章节类型识别（skill L283-295）

- **skill 原文**：4 类 —— 战斗章 / 布局章 / 过渡章 / 回收章。不同类型不同写法。
- **我们现状**：Planner 没在 plan.json 标注章节类型。Generator 按同一套铁律写所有章节，可能把过渡章写成战斗章的"血腥重拳模板"。
- **借鉴价值**：🟢 高 —— 这是 landmine_9（节奏失控）的根本解法。
- **落地方式**：
  - Planner 的 plan.json schema 增加字段 `chapter_type` (战斗 / 布局 / 过渡 / 回收)
  - Generator system prompt 根据 chapter_type 调整指令权重：战斗章强调画面/受力/收益；布局章强调试探/交易/威慑；过渡章强调状态变化/钩子；回收章优先回应伏笔
- **与 gap-analysis 关系**：**新增 C-29 · 章节类型分化**，Should 级（4h）。

### 13. 场景压力（skill L297-309）⭐

- **skill 原文**：
  - 用动作、伤势、声音、重量、冲击、温度、血腥味落地，少用空泛判断
  - **每个场景至少推进一项**：信息 / 地位 / 资源 / 伤亡 / 仇恨 / 境界
  - 小冲突尽快兑现，**不要把爽点无限后置**
  - 核心对手必须有脑子；边缘敌人不必人人演满但也不能让路
  - 留人/钓鱼/示弱/借刀可以，**前提只能是利益更大，绝不是心软**
- **我们现状**：rules/writing-style-core.md 有"五感代入"，但**"每场景至少推进一项"的硬约束没有**。
- **借鉴价值**：🟢 高 —— "场景必推进一项"这一条可直接变成 Planner 强制字段。
- **落地方式**：
  - Planner 的 scene schema 增加字段 `advances` (信息 / 地位 / 资源 / 伤亡 / 仇恨 / 境界 中至少选一)
  - 对应新 landmine 判据：scene_advances 为空或笼统 → Evaluator hit landmine_5（主线模糊）
- **与 gap-analysis 关系**：和 **B-7 节奏仪表**合并，细化为具体的 scene 推进项审计。

### 14. 【写作自检】 + 【章节结算】表格（skill L315-337）⭐⭐ 结构可直接抄

- **skill 原文**：每次生成正文前输出 Markdown 表格的【写作自检】，涉及吞噬/突破/卷末时追加【章节结算】。
  ```
  【写作自检】
  | 检查项 | 本章记录 | 备注 |
  | 上下文范围 | ... | |
  | 当前锚点 | ... | |
  | 当前微粒开启数 | X/840000000 | |
  | 本章预计增量 | +X | |
  | 待回收伏笔 | Hook-A/Hook-B | |
  | 本章冲突 | 一句话 | |
  | 风险扫描 | OOC/敌方信息越界/设定冲突/战力崩坏/节奏拖沓/词汇疲劳 | |
  ```
- **我们现状**：Planner 产出 plan.json 不含"风险扫描"，Generator 产出直接是 chNNN.md 无自检。
- **借鉴价值**：🟢 高 —— 这个表格实际上是**教程贴创作自检 Checklist 的实现形态**。我们之前在 gap-analysis A-5 拒掉了（理由：违反 Planner/Generator/Evaluator 分离）；但 skill 把它放在 Planner 层**是可行的**，因为它产出的是 plan 附录，不是 Generator 的自评。
- **落地方式**：
  - Planner 的 plan.json 增加 `writing_self_check` 字段（表格结构）
  - Generator 读到 plan.json 的 writing_self_check，必须按"风险扫描"提到的风险避写
- **与 gap-analysis 关系**：**重开 A-5**（原本 Won't）→ 改造为 Planner 侧的 writing_self_check，不是 Generator 自查。Should 级（3h）。

### 15. 句子与段落节奏（skill L353）

- **skill 原文**："保持简体中文，句子长短交替，段落适合手机阅读。"
- **我们现状**：`rules/writing-style-core.md` 说"每段 3-5 行"。对齐。
- **借鉴价值**：已在系统中。
- **与 gap-analysis 关系**：**已对齐**。

### 16. 无女主路线 / 女性角色立场（skill L359-361）

- **skill 原文**：skill 对应的是无女主小说；但"无女主不等于无女性角色"。
- **我们现状**：是 setting 级别的决策，gangster-hk-1983 里苏婷就是"第二方视角，非恋爱对象"。
- **借鉴价值**：🔴 不通用 —— 这是 skill 特定题材的约束，不同题材不同做法。
- **与 gap-analysis 关系**：已隐式在 setting.yaml 和 characters.yaml 里实现。

### 17. 数值追溯要求（skill L367）

- **skill 原文**："保持数值、收益、已知信息与伏笔状态**可追溯**，不用模糊词掩盖跳变与降智。"
- **我们现状**：current_status_card.md + resource_ledger.md + pending_hooks.md 三件套落地后，这条自动满足。
- **与 gap-analysis 关系**：与 #4 #6 #7 合并实现。

### 18. 设定在场景里落地（skill L371）⭐ 可抄

- **skill 原文**："保持设定在场景里落地，不要整段讲百科。"
- **我们现状**：Generator prompt 加载 era.md 时有风险被 Generator 当百科复述。当前的 writing-style-core 第四部分**没有明确禁止百科复制**。
- **借鉴价值**：🟢 高
- **落地方式**：
  - Generator system prompt 加："**禁止百科式堆砌设定**。era.md 是参考资料，它的事实必须**融入场景的感官/动作**，不得以解说性段落形式复述。"
  - 新 landmine_2（世界观强行灌输）的 AISlopGuard 判据补充：整段说明性世界观文字 → hit
- **与 gap-analysis 关系**：**新增 C-30 · 设定场景化强制**，Must 级（0.5h）。

### 19. 三章内明确反馈（skill L377）

- **skill 原文**："三章内应有明确反馈，但反馈可以是**打脸/收益兑现/信息反转/地位变化**，不限于杀人。"
- **我们现状**：我们写 3 章 demo 都有反馈，但**没规则**。Planner 没被要求检查「前 3 章有没有具体反馈」。
- **借鉴价值**：🟡 中 —— 可以进入 Planner 的"黄金三章自检"。
- **落地方式**：Planner 在做 ch3 的 plan 时，回读 ch1+ch2 的 closing_hook，检查"三章内有没有至少一个反馈兑现"。没有则要求 Planner 在 ch3 加入一个。
- **与 gap-analysis 关系**：**新增 C-31 · 黄金三章反馈检**，Could 级（2h）。

### 20. 联网规则（skill L391-397）

- **skill 原文**："创作已有世界观下的正文时，**以本地设定和已有章节为主，不主动联网**。用户明确要求或核对真实世界概念时才联网。"
- **我们现状**：完全无联网。
- **借鉴价值**：🟢 完全一致 —— 这支持我们砍掉联网的决策。
- **关键启发**：gap-analysis 的 **A-1 websearch tool-call** 要改思路 —— 不是"默认开搜索"，而是"**仅在 Evaluator 检测到真实世界事实风险时才搜索**"。例如 Evaluator 对 timeline_drift 类 landmine_13 高度怀疑但 evidence 不足时，**一次性**调用 search tool 核查。
- **与 gap-analysis 关系**：**修订 A-1 · Websearch 按需触发**（不是 Generator 主动而是 Evaluator 按需），工作量从 10h 压缩到 6h。

### 21. 禁止的失败模式（skill L399-419）⭐⭐ 可直接抄成 iron_laws

- **skill 原文**：12 条明确禁令 —
  - 已退场角色无铺垫回归
  - 为推剧情突然仁慈、犯蠢、讲武德
  - 反派木桩排队送死
  - 反派基于不可能知道的信息行动
  - 大段设定说明替代战斗/压迫
  - 无铺垫塞新体系/新地图/新外挂
  - 用"暴涨/海量/难以估量"跳过结算
  - 完成大剧情后忘记更新伏笔池
  - 拆解知识库反向污染正文
  - 输出跑偏题材文风
- **我们现状**：部分已在 `rules/24-iron-laws.md`（拒绝机械降神、反派不降智），部分**完全没有**（"反派基于不可能知道的信息行动"、"完成大剧情后忘更新伏笔池"）。
- **借鉴价值**：🟢 极高 —— 这是 12 条 iron_law 候选，可直接扩展我们 24 → 30+ 条。
- **落地方式**：
  - 审阅 12 条 vs 现有 24 iron_laws，去重后**至少 4 条新增**，编号 iron_law_25-30：
    - iron_law_25 · 信息越界禁令：反派行动必须可追溯到其已知信息
    - iron_law_26 · 伏笔池同步：大剧情节点必须更新 pending_hooks.md
    - iron_law_27 · 资源结算禁模糊："暴涨/海量/难以估量"直接 fail
    - iron_law_28 · 风格锁定：同一作品不得跑出题材基调
- **与 gap-analysis 关系**：**升级 A-9（补通用 iron_law_25/26）** → 具体化为 4 条新增，工作量 3h。

### 22. 审稿问题分类（skill L423）⭐

- **skill 原文**："先判定问题属于：设定冲突 / 人物 OOC / 爽点缺失 / 节奏拖沓 / 配角降智 / 敌方信息越界 / 战力崩坏 / 微粒数值跳变 / 伏笔失管 / 语言机械 / 词汇疲劳。"
- **我们现状**：我们有 18 个 landmine，覆盖很广。但**没有"配角降智"单独条目**、"敌方信息越界"也没有。
- **借鉴价值**：🟡 中 —— 可审查现有 18 landmine 是否遗漏。
- **落地方式**：扩充 landmine_11（人物形象单薄）判据，明确包含"配角降智"和"敌方信息越界"两个子项。
- **与 gap-analysis 关系**：**补强 landmine_11 判据**，0.5h。

### 23. 修根因不做表面润色（skill L427）

- **skill 原文**："优先修根因，不做表面润色。"
- **我们现状**：Fixer prompt 有"**只修不重写**"，但没明确"**根因优先**"。
- **借鉴价值**：🟡 中 —— 可补进 Fixer prompt。
- **落地方式**：Fixer system prompt 加一句："**定位 evidence 的根因修**，不要做纯语言润色把症状盖住。"
- **与 gap-analysis 关系**：0.5h 小改动。

### 24. 全局风格锁定（skill L11, L419）⭐

- **skill 原文**：开头和结尾都强调"**输出风格必须稳定保持玄幻小说质感**... 不得混入都市/科幻/游戏文/轻小说/影视剧本/悬疑刑侦/历史演义/散文议论/玩梗吐槽等其他风格"。
- **我们现状**：Generator 的 setting.yaml.author_persona_hints 提到风格基调，但**没有明确禁止的风格清单**。
- **借鉴价值**：🟢 高 —— 对长链路写作极重要（易飘）。
- **落地方式**：
  - setting.yaml 增加字段 `prohibited_styles`（数组），默认包含通用禁止（影视剧本腔 / 游戏系统播报腔 / 轻小说吐槽腔 / 散文抒情腔）+ 题材特定禁止
  - Generator / Fixer system prompt 在开头顶级位置加载这个字段作为"不可跨越的风格锁"
- **与 gap-analysis 关系**：**新增 C-32 · 风格锁定机制**，Should 级（2h）。

---

## 对照 gap-analysis 的清单修订建议

| gap-analysis 原条目 | skill 带来的新信息 | 修订建议 |
|---|---|---|
| A-1 Websearch | skill L393-397 明确"不主动联网，按需核查" | 修订为 Evaluator 按 landmine_13 怀疑触发一次性搜索，工作量 10h → 6h |
| A-9 补通用 iron_law_25/26 | skill L399-419 提供 12 条候选 | 升级：扩充 4 条新 iron_law（原 1.5h → 3h） |
| B-1 交叉验证多源 | skill L27-53 提供显式优先级协议 | 升级：加 `rules/00-information-priority.md`，工作量 3h |
| B-7 节奏仪表 | skill L297-309 "每场景推进一项" | 细化：scene.advances 字段 + 对应 landmine 判据 |
| C-12 Summarizer 多级 | skill L55-63 提供"按需窗口"策略 | 细化：按相关性读摘要 + 章/弧/全书三级（原 8h 不变） |
| **A-5 创作自检 Checklist** | skill L315 放在 Planner 层可行 | **重开**：原 Won't → 改造到 Planner 的 writing_self_check（3h） |

## 新增条目（gap-analysis 漏掉的）

| # | 条目 | 层级 | 工时 | 来源 | 状态 |
|---|---|---|---|---|---|
| **C-22** | Intent Router（任务类型判别） | Should | 8h | skill #1 | ✅ |
| **C-23** | Current Status Card（当前状态卡 + StatusCardUpdater Agent） | **Must** | 10h | skill #4 ⭐⭐ | ✅ |
| **C-24** | Resource Ledger（资源账本，setting 可选） | Should | 8h | skill #6 | ✅ |
| **C-25** | Pending Hooks（伏笔池 + HookKeeper Agent） | Should | 6h | skill #7 | ✅ |
| **C-26** | AISlopGuard 疲劳词黑名单 | **Must** | 1.5h | skill #8 | ✅ |
| **C-27** | Fixer 修改档分级（润色/改写/重写/续写） | **Must** | 0.5h | skill #10 | ✅ |
| **C-28** | Generator 动笔前 7 问 | **Must** | 1h | skill #11 ⭐⭐ | ✅ |
| **C-29** | 章节类型分化（战斗/布局/过渡/回收） | Should | 4h | skill #12 | ✅ |
| **C-30** | 设定场景化强制（禁百科复述） | **Must** | 0.5h | skill #18 | ✅ |
| **C-31** | 黄金三章反馈自检 | Could | 2h | skill #19 | ✅ |
| **C-32** | 风格锁定机制（prohibited_styles） | Should | 2h | skill #24 | ✅ |

**合计新增**：11 条 · Must 5 条（13.5h） · Should 4 条（20h）· Could 1 条（2h）· 其他升级 1 条

**🎉 2026-05-11：11 条全部落地 ✅ · 见 [gap-analysis-post-mvp.md 维度 C 扩展表](gap-analysis-post-mvp.md#维度-c-扩展skill-借鉴新增2026-05)**

---

## 推荐借鉴清单（按优先级）

### 🟢 立即借鉴（本周 / 下周融入）· ✅ 全部完成

1. **C-26 · AISlopGuard 疲劳词黑名单**（1.5h）✅
2. **C-27 · Fixer 修改档分级**（0.5h）✅
3. **C-28 · Generator 动笔前 7 问**（1h）✅
4. **C-30 · 设定场景化强制**（0.5h）✅
5. **A-9 升级 · 4 条新 iron_law**（3h）✅

**子合计**：6.5h · 实际落地 commit `9512db0`。

### 🟡 下周融入（配合 C-5 10 章长跑）· ✅ 全部完成

6. **C-23 · Current Status Card + StatusCardUpdater Agent**（10h）✅ —— 长链路稳定的决定性基础设施
7. **B-1 升级 · 信息源优先级协议**（3h）✅
8. **C-12 细化 · 按相关性读摘要 + 章/弧/全书**（C-23 落地后实现）✅
9. **A-5 重开 · Planner 侧 writing_self_check**（3h）✅

**子合计**：16h · 实际落地 commit `1b86923` 等。

### 🔵 第三周及以后 · ✅ 全部完成

10. C-29 章节类型分化（4h）✅
11. C-24 Resource Ledger（8h，玄幻/系统流题材需要）✅
12. C-25 Pending Hooks（6h）✅
13. C-32 风格锁定（2h）✅
14. A-1 修订 · Evaluator 按需搜索（6h）✅ —— commit `bad8eea` FactChecker
15. C-22 Intent Router（8h）✅
16. C-31 黄金三章反馈检（2h）✅

**全部完成。剩余可能的二轮借鉴机会见文档末尾（留空备用）。**

---

## 明确不采纳

| 条目 | 原因 |
|---|---|
| **无女主路线** | Setting 级决策，不通用 |
| **二十二方起源真界彩蛋** | 具体作品 IP，不可抄 |

---

## 可直接抄的 prompt 语言库

下面的句子，以后重写 Generator / Evaluator / Fixer prompt 时可以直接引用：

### 通用
- "不吃设定、不降智、不机械的前提下"（skill L11）
- "保持数值、收益、已知信息与伏笔状态可追溯，不用模糊词掩盖跳变与降智"（L367）
- "优先修根因，不做表面润色"（L427）

### 对 Generator
- "动作、伤势、声音、重量、冲击、温度、血腥味来落地强，少用空泛判断"（L299）
- "每个场景至少推进一项：信息、地位、资源、伤亡、仇恨、境界"（L301）
- "留人、钓鱼、示弱、借刀杀人，但前提只能是利益更大，绝不能是心软"（L307）
- "保持设定在场景里落地，不要整段讲百科"（L371）
- "群像反应不要一律写成'全场震惊'或'众人倒吸凉气'；改写成 1-2 个具体角色的身体反应、判断偏差或利益震荡"（L195）

### 对 Evaluator / Auditor
- "反派当前掌握了哪些已知信息、误判与盲区？哪些信息只有读者知道、反派不知道？"（L273）
- "反派的每一步关键动作，是否都能追溯到其已知信息、资源约束、性格习惯或上一轮误判？"（L275）
- "本章收益是否能落到具体资源、微粒增量、地位变化或已回收伏笔，而不是抽象'更强了'？"（L279）
- "对'冷笑''蝼蚁''轰然炸裂''倒吸一口凉气''瞳孔骤缩''满场死寂'等高疲劳词保持克制。单章中同一高识别词默认只允许出现 1 次"（L193）

### 对 Fixer
- "润色：只改表达、节奏、段落呼吸，不改事实与剧情结论"
- "改写：可改叙述顺序、画面、力度，但保留核心事实与人物动机"
- "重写：可重构场景推进和冲突组织，但除非用户允许，否则不改主设定和大事件结果"
- "续写：只在现有文本之后向前推进，不反改前文"

---

## Top 3 最值得立即借鉴

1. **skill L315-337 写作自检表格 → C-23 Current Status Card + #14 writing_self_check**
   进 `state/current_status_card.md` + Planner 的 plan.json.writing_self_check 字段
   **最大的架构补强** —— 解决了 gap-analysis 漏掉的"长链路实时状态追踪"

2. **skill L265-281 动笔 7 问 → C-28 Generator 动笔前 7 问**
   直接抄进 `src/agents/generator.py` system prompt 的铁律之后
   1 小时改动，质量直接上台阶

3. **skill L399-419 禁止失败模式 → A-9 扩充 4 条 iron_law**
   进 `rules/24-iron-laws.md`（变成 28 条）
   可抄性最高，直接从 skill 翻译过来

## Top 3 与我们架构冲突（不建议照搬）

1. **skill 的 "主动读所有 .md 设定文件" 策略**（L65-102）
   我们是 Agent 按需读，不是主动全读。skill 靠 Claude Code 级别的 agentic loop，我们是线性 pipeline。**保留我们的按需读**。

2. **skill 的微粒数值硬锚点 `840000000`**（L163）
   是玄幻特定数值。我们改为 setting.yaml 声明题材需要的资源 schema。

3. **skill 的 Intent Router**（L13-25）
   我们 pipeline 是单一入口，暂不需要 intent 分类。**仅在加 Web 对话 UI 时再做**（C-22 Should 层）。

---

## 本文档的预期用法

- 本周完成第一周 5 项（C-17 / C-10 / C-2 / C-5 / C-8）时，**穿插做借鉴清单里的 🟢 立即借鉴 5 条**（共 6.5h）
- 第二周开始 C-12 多级摘要 + C-5 长跑时，同时做 C-23 当前状态卡（两者共生）
- 把这份清单当作 gap-analysis 的**补丁**文档：gap-analysis 有的保留，这份补充它漏掉的 + 修订它的估算

---

*维护者：Calvin · 可随 skill 理解深入迭代 · 鼓励未来的 Oracle 评审再过一遍*
