# 教程贴借鉴审计 (Tutorial → System Crosswalk)

> 对照 `docs/ai 小说流水线教程贴.txt`（1579 行）审查本仓库的实际借鉴情况。
> **首次起草**：2026-05-10（MVP 3 章完成时）
> **最后更新**：2026-05-11（C-5 10 章长跑 + C-10 校准 + 11 条 skill 借鉴全部落地后）
>
> 每条标注三种状态：
> - 🟢 **完整借鉴** — 落点明确，内容进入运行时，被 Agent 加载使用
> - 🟡 **部分借鉴/改造** — 核心思想采纳但实现方式调整
> - 🔴 **未借鉴** — 明确决定不用，给出原因

## 总览

- 教程贴总条目数：**约 108 条**（分解到可独立判断的粒度）
- 🟢 完整借鉴：**~55 条**（+12 条相比 2026-05-10 首版——联网搜索、书名简介、创作自检、节奏控制、信息源优先级等通过 skill 借鉴和 A-1/A-4 升级进了 🟢）
- 🟡 部分借鉴/改造：**~18 条**（从 26 减到 18，因为多条升级为 🟢）
- 🔴 未借鉴：**~35 条**（从 39 减到 35，因为 4 条升级为 🟢/🟡）

核心结论（2026-05-11 更新）：教程贴的**创作原则层**（§二 15 条创作原则 + 代入感六大支柱）几乎全部吸收；**雷点层**（18 landmines）完整借鉴 + AISlopGuard/FactChecker 专项审计；**小说设定层**（§三 16+ 条设定 + 24 个"严禁"）约一半进入通用铁律（28 条铁律 = 24 原版 + 4 新增）或 setting pack，另一半属于特定小说设定不通用；**前言通用指令层**（12 条）仍然绝大多数不适用（架构约束决定）；**角色层**（14 个）拆分重组到 11 个 Agent（5 创作 + 3 记账 + 3 审计）的职责中——记账层是教程贴未出现的、系统衍生的 Agent 形态。

---

## 分项对照

### §前言 · 12 条通用指令

#### 1.1 搜索启动（不确定即搜索）
**状态**：🔴 未借鉴
**原因**：本项目 Agent 不做联网搜索。题材事实通过 setting pack 的 `era.md` + `timeline.yaml` 静态注入。设计 spec 明确砍掉 TimelineGuard/FactGuard 的原因包括「活爬网费钱且易超时」。
**原文位置**：教程贴 L5
**相关架构决策**：`docs/superpowers/specs/2026-05-09-novelforge-design.md` L111-114

#### 1.2 搜索执行（专家级策略）
**状态**：🔴 未借鉴 — 同上，无联网搜索能力

#### 1.3 信息甄别（交叉验证）
**状态**：🟡 部分借鉴 — 交叉验证的思想在系统内转化为 Evaluator 对 characters.yaml + timeline.yaml 的双重交叉核查
**落点**：`src/agents/evaluator.py` L98-103：「如果稿件中主角的行为违背 characters.yaml 中的 redlines / traits…必须命中」+「如果稿件中的年份、事件、物价与 timeline.yaml 不符…必须命中」

#### 1.4 答案合成（禁止搬运）
**状态**：🔴 不适用 — 这是对 LLM 通用回答的要求，不是小说写作特有的

#### 1.5 语气规范（直言不讳、犀利幽默）
**状态**：🟡 部分借鉴 — Evaluator 的「以刁钻著称」「默认拒稿」性格吸收了这种犀利风格，但不是复制人设，而是工具化到 Evaluator 对抗 persona
**落点**：`src/agents/evaluator.py` L75-77

#### 1.6 深入解析
**状态**：🔴 不适用 — 纯 LLM 通用指令，与小说系统无关

#### 1.7 背景关联
**状态**：🔴 不适用 — 同上

#### 1.8 解释机制 / Markdown 表格 / LaTeX / Graphviz
**状态**：🔴 不适用 — 这是对知识问答类任务的格式约束

#### 1.9 专业影响力
**状态**：🔴 不适用 — 这是 LLM persona 指令，与 pipeline 结构无关

#### 1.10 就事论事 + 底层原理 + 思维链
**状态**：🔴 不适用 — 同上

#### 1.11 指令遵循 + 梳理归纳
**状态**：🔴 不适用 — 同上

#### 1.12 时刻联网搜索
**状态**：🔴 未借鉴 — 架构刻意不做联网搜索

---

### §一 · 14 个角色

#### 2.1 历史考据官
**状态**：🟡 部分借鉴 — 没有独立 Agent，拆分为两个机制：
- `era.md`（时代事实包）供 Generator 在写场景时参考（`src/agents/generator.py` L39）
- `timeline.yaml` 供 Evaluator 交叉验证（`src/agents/evaluator.py` L53）
**为什么没有独立 Agent**：3 章 MVP 上时间线冲突概率低，setting pack 预载事实已足够（spec L112）
**原文位置**：教程贴 L37

#### 2.2 资深编辑
**状态**：🟢 完整借鉴 — Evaluator 的对抗人设就是「业内以刁钻著称的资深网文主编，做了 20 年」
**落点**：`src/agents/evaluator.py` L75-79；Agent 名册描述也为「对抗人设，默认拒稿」

#### 2.3 角色构建专家（六步走）
**状态**：🟢 完整借鉴 — 教程贴中「六步走人物心理分析」原文照搬进 `rules/writing-style-core.md`
**落点**：`rules/writing-style-core.md` L9-19，标题为「六步人物心理分析（六步走）」，六步原文逐一列出
**运行时加载**：Generator 和 Fixer 的 system prompt 都加载此文件（`src/agents/generator.py` L96，`src/agents/fixer.py` L64）

#### 2.4 写作优化专家
**状态**：🟢 完整借鉴 — 回避 AI 味的全部 10 条建议（句式多样化、词汇控制、反例/正例、修辞运用、逻辑结构、分段原则）全部进入 `rules/writing-style-core.md` 第四部分
**落点**：`rules/writing-style-core.md` L103-118，包含「少用『了』字」「避免转折词堆砌」「每段只有 1 个核心信息点」「严禁词藻堆砌/故意秀文笔」等
**原文位置**：教程贴 L55-89

#### 2.5 小说评论员
**状态**：🟡 部分借鉴 — 评论员的职能被拆到 Evaluator（判稿 + top_3_fixes）和 Fixer（改稿）两个 Agent。教程贴中「提供有见地的评论 + 讨论潜在解决方案」对应 Evaluator 的 landmine 评分 + evidence 机制
**落点**：`src/agents/evaluator.py` 全文（特别是 top_3_fixes 输出）
**差异**：系统是自动化的判稿→改稿循环，不是人机交互式评论

#### 2.6 电影电视剧爱好者
**状态**：🟡 部分借鉴 — 港综 setting 的 `era.md` 包含了 1983 年流行文化（电影、电视、音乐）参考，供 Generator 在场景描写中调用
**落点**：`settings/gangster-hk-1983/era.md` L88-95（列出《最佳拍档》《射雕英雄传》《神雕侠侣》、许冠杰、谭咏麟等）
**差异**：不是让 Agent 扮演影迷，而是把流行文化作为事实数据注入

#### 2.7 经济金融能源大师
**状态**：🔴 未借鉴 — MVP 中未实现经济金融子系统。但港综 setting 的 `era.md` 包含部分经济数据（恒指、GDP、港元汇率）
**落点**：`settings/gangster-hk-1983/era.md` L12-21 包含 1983 年经济数据
**原因**：3 章 MVP 中金融剧情占比低，经济事实通过 era.md 静态覆盖

#### 2.8 股票大师
**状态**：🔴 同上 — 但港综 setting 的 `era.md` 包含恒指数据和港元黑色星期六事件
**落点**：`settings/gangster-hk-1983/era.md` L15-21 + `settings/gangster-hk-1983/timeline.yaml` L1-10（黑色星期六）
**原因**：同上

#### 2.9 军火之王
**状态**：🔴 未借鉴 — 系统中有 `iron_law_10: 数据精准化` 在创作上有约束（要求精确数字），但没有领域专家 Agent
**相关**：教程贴 L1575「严禁不查证写军事」→ 在系统中对应 `iron_law_10` 的部分精神，但无独立军事/军火 Agent

#### 2.10 雇佣兵与杀手大师
**状态**：🔴 未借鉴 — MVP 章节未涉及此领域

#### 2.11 各国历史专家
**状态**：🟡 部分借鉴 — `era.md`（地域+时代）和 `timeline.yaml`（事件时间线）联合覆盖了固定时间窗口的历史事实
**落点**：`settings/gangster-hk-1983/era.md` + `settings/gangster-hk-1983/timeline.yaml`
**差异**：只覆盖香港 1983-2000，不是所有国家/时期

#### 2.12 港综同人小说家
**状态**：🟢 完整借鉴 — 通过 setting pack 的 `setting.yaml` 注入，Generator 的 system prompt 第一行就声明「你是一名职业网文作家」，配合 `author_persona_hints`
**落点**：`settings/gangster-hk-1983/setting.yaml` L30-34（author_persona_hints：专精 1980s 港片、熟悉粤语俚语、克制冷笔等）；`src/agents/generator.py` L65-73（persona_block 被注入 system prompt）
**巧妙之处**：教程贴说「你知道怎么写港综同人小说」，系统通过 setting pack 的 author_persona_hints 让 Generator 扮演这个角色，而 Evaluator 反过来检查是否违题材特有铁律——形成对抗

#### 2.13 逻辑死磕官
**状态**：🟢 完整借鉴 — 「每写一个情节必须反问三次」被吸收进 Evaluator 的交叉核查机制 + `iron_law_1`（人设一致性）+ `iron_law_15`（逻辑闭环）
**落点**：
- `rules/24-iron-laws.md` L6-10（iron_law_1：角色行为由「过往经历 + 当前利益 + 性格底色」共同驱动）
- `rules/24-iron-laws.md` L90-94（iron_law_15：每个伏笔都要收回）
- `src/agents/evaluator.py` L98-103（交叉核查：characters.yaml redlines + timeline.yaml）
**原文**：教程贴 L107-109「每写一个情节，必须反问三次：他为什么要这么做？这符合他的利益吗？这符合他之前的人设吗？」

#### 2.14 细节堆砌师
**状态**：🟢 完整借鉴 — 转化为 `iron_law_20: 细节堆砌`
**落点**：`rules/24-iron-laws.md` L120-124：「重要剧情、关键伏笔必须用细节堆砌；不能一笔带过。谈判的艰难、对手的阴招、深夜的焦虑——都要写。」
**原文**：教程贴 L111「要有细节描写，而不是一笔带过对于很重要剧情和伏笔」

---

### §二 · 15 条创作原则

#### 3.1 Show, Don't Tell（展示，不要讲述）
**状态**：🟢 完整借鉴 — 系统中最核心、被加载最多次的「元规则」
**落点**：
- `rules/24-iron-laws.md` L12-16（iron_law_2，含正反例）
- `rules/writing-style-core.md` L67-99（第三部分：Show-Don't-Tell 铁律，6 个情绪维度各附正反例）
- Generator 的 system prompt 第一句引用此规则（`src/agents/generator.py` L86）
- Evaluator 通过 24-iron-laws 做合规检查

#### 3.2 盐溶于汤叙事
**状态**：🟢 完整借鉴 — 独立成 `iron_law_3`
**落点**：`rules/24-iron-laws.md` L18-22：「主角的野心和价值观不能通过口号喊出来，必须内化于行为与决策」

#### 3.3 梗的艺术与时代感
**状态**：🟢 完整借鉴 — 独立成 `iron_law_6`
**落点**：`rules/24-iron-laws.md` L36-40：「将后世梗提炼精神内核，用符合年代语境的方式说出；绝不出现穿越梗」
**原文位置**：教程贴 L121-124（原文 「用最正经的语气说最荒诞的话」的表述在港综 extra 中直接出现于 `settings/gangster-hk-1983/writing-style-extra.md` L29）

#### 3.4 全员在线
**状态**：🟡 部分借鉴 — 时间线把关由 Evaluator 对 `timeline.yaml` 交叉核查实现；人设不崩由 CharacterGuard 和 Evaluator 的 landmine_10 双重保障。但对「不能写着就遗漏了」的跟踪较弱
**落点**：`src/agents/evaluator.py` L98-103（交叉验证）；`src/auditors/character_guard.py`（人设一致性审计）

#### 3.5 配角 B 面
**状态**：🟢 完整借鉴 — 独立成 `iron_law_9` 和 `iron_law_21`
**落点**：
- `rules/24-iron-laws.md` L54-58（iron_law_9：配角必须有反击、有自己的算盘；小弟也有私心）
- `rules/24-iron-laws.md` L126-130（iron_law_21：配角必须有反击和算计）
- 人物档案中配角有独立 motivation 和 weakness（如 `characters.yaml` 中阿威「母亲病重，钱和孝是两条命」）

#### 3.6 节奏控制
**状态**：🟢 完整借鉴 — 独立成 `iron_law_16`
**落点**：`rules/24-iron-laws.md` L96-100：「不突然急促，不无故拖沓；每章都有推动，衔接自然，慢火炖高汤」

#### 3.7 拒绝流水账
**状态**：🟢 完整借鉴 — 独立成 `iron_law_4`
**落点**：`rules/24-iron-laws.md` L24-28：「不写『起床刷牙吃饭』；每一行字都要推动剧情或塑造人物，每一笔都有存在理由」

#### 3.8 拒绝闭门造车
**状态**：🟢 完整借鉴 — 独立成 `iron_law_14`，且教程贴中 a-d 四个学习方向原文进入了港综 setting 的 writing-style-extra
**落点**：
- `rules/24-iron-laws.md` L84-88
- `settings/gangster-hk-1983/writing-style-extra.md` L78（人物弧光、剧情切入点、世界观深化、情感互动）

#### 3.9 精准时间线
**状态**：🟢 完整借鉴 — 独立成 `iron_law_12`，且港综 setting 有 `timeline.yaml` + `era.md` 两重时间事实
**落点**：`rules/24-iron-laws.md` L72-76；`settings/gangster-hk-1983/timeline.yaml`（真实事件日期精确到日）

#### 3.10 三七开日常
**状态**：🟢 完整借鉴 — 独立成 `iron_law_17`，港综 extra 也重复强调
**落点**：
- `rules/24-iron-laws.md` L102-106
- `settings/gangster-hk-1983/writing-style-extra.md` L54-56（「万物皆为饵」）

#### 3.11 人设防崩（人设一致性原则）
**状态**：🟢 完整借鉴 — 独立成 `iron_law_1`，且教程贴中「过往经历+当前利益+性格底色」的公式原文进入 iron_law_1
**落点**：`rules/24-iron-laws.md` L8：「角色行为由『过往经历 + 当前利益 + 性格底色』共同驱动」
**原文**：教程贴 L156-163 中这句话几乎逐字被 iron_law_1 纳入。禁忌案例「反派突然降智饶过主角」也直接化为 `iron_law_8` 的反例。

#### 3.12 创作自检 Checklist
**状态**：🟢 完整借鉴（2026-05 升级）— 教程贴的 4 条自检以两种形态同时落地：
- **Planner 侧**：`writing_self_check` 字段（6 维风险扫描表：ooc / info_leak / setting_conflict / power_scaling / pacing / vocab_fatigue）
  - 每项是 Planner 基于 outline + 状态卡 + 前情预判的 ≤30 字具体提示（或"无"）
  - Generator 读 plan 时将此表渲染成 Markdown 拼进 system prompt，主动规避
- **Evaluator 事后侧**（原设计不变）：
  - a（时间事件核对）→ Evaluator 的 timeline 交叉验证
  - b（逻辑闭环）→ `iron_law_1` + `iron_law_15` + Evaluator 的 landmine 机制
  - c（细节填充）→ `iron_law_20`（细节堆砌）
  - d（对照设定检查）→ Evaluator 对 characters.yaml 的交叉核对

**落点**：
- Planner 自检表：`src/agents/planner.py` system prompt 铁律 #10 + `_format_self_check()` 渲染
- 事后检查：`rules/24-iron-laws.md`、`src/agents/evaluator.py`

**差异**：原先把"生成前自检"判为违反分离原则而拒做；skill 借鉴揭示正确形态是放在 **Planner**（不是 Generator）自检，Planner 本就是评估者而非执笔者，不冲突。

#### 3.13 人物立体化原则
**状态**：🟢 完整借鉴 — 教程贴的「核心标签 + 反差细节 = 活人」公式直接进入系统
**落点**：
- `rules/18-landmines.md` L92：landmine_11 修正公式直接使用「核心标签 + 反差细节」
- `rules/writing-style-core.md` L61（人设与代入感：不要十全十美的人设，举例「总裁下班把衣服丢沙发」「漂亮女角真名叫牛翠花」）

#### 3.14 情感/动机逻辑链
**状态**：🟢 完整借鉴 — 独立成 `iron_law_19`
**落点**：`rules/24-iron-laws.md` L114-118：「任何关系的改变（结盟、背叛、从属），都必须有铺垫和事件驱动，严禁无理由的爱/恨」

#### 3.15 写作技巧六大核心（代入感六大支柱）
**状态**：🟢 完整借鉴 — 教程贴中「塑造代入感的六大支柱」被几乎全文吸收进 `rules/writing-style-core.md` 第二部分
**落点**：`rules/writing-style-core.md` L22-63：
- 支柱 1：基础信息交代与标签化（L24-28）
- 支柱 2：具体化、可视化的熟悉感（L30-34）
- 支柱 3：共鸣（情绪+认知）（L36-42）
- 支柱 4：欲望与好奇心（基础欲望 vs 主动欲望）（L44-47）
- 支柱 5：五感代入（L49-57）—— 同时被独立为 `iron_law_18`
- 支柱 6：人设与代入感（L59-63）

教程贴中「小爷我乃镇南府世子林峰」的例子也被保留在支柱 1 的示例中（L28）。

---

### 增强代入感的 4 种方式

#### 4.1 熟悉感
**状态**：🟢 已借 — 进入 `rules/writing-style-core.md` L30-34（支柱 2）

#### 4.2 标签
**状态**：🟢 已借 — 进入 `rules/writing-style-core.md` L24-28（支柱 1）+ L35-63（人设标签与小缺点）

#### 4.3 冲突的紧迫性
**状态**：🟢 已借 — 进入 `rules/18-landmines.md` landmine_8（冲突乏力与爽点缺失）的整套改进办法

#### 4.4 接地气
**状态**：🟢 已借 — 进入 `rules/writing-style-core.md` L61-63（角色接地气缺点示例）

#### 4.5 减少「了」字和转折词
**状态**：🟢 完整借鉴 — 进入 `rules/writing-style-core.md` L106-107（少用「了」字）+ L107（避免转折词堆砌）。AISlopGuard 的判据中也专门有「了字泛滥」和「转折词滥用」两条。

---

### 五方面写作雷区

#### 5.1 写作人称
**状态**：🟢 完整借鉴 — 进入 `rules/writing-style-core.md` L118：「叙事人称统一：确定第三人称『他/她』或第一人称『我』后全书一致，不可混用」
**原文位置**：教程贴 L569-595

#### 5.2 避免流水账（2 种办法）
**状态**：🟡 部分借鉴 — 增加冲突和加入强情绪的方法被吸收进 `iron_law_4`（拒绝流水账）和 landmine_7（主线模糊与偏离）。但教程贴的具体练习示例（催债电话、手机掉水沟）未被直接搬运，因为系统是写港综而非做教学。
**原文位置**：教程贴 L597-678

#### 5.3 开篇不吸引人（3 种常见错误）
**状态**：🟢 完整借鉴 — 教程贴「开篇太寡淡」「开篇太复杂」的分析完全进入 landmine_1（开篇拖沓/平淡/信息轰炸）
**落点**：`rules/18-landmines.md` L6-13，包括「开篇堆砌背景、世界观设定」「核心冲突迟迟不出现」「出场人物不超过 3 个」等
**原文位置**：教程贴 L685-737

#### 5.4 人设有问题（扁平化 + 前后不统一）
**状态**：🟢 完整借鉴 — 全部进入 landmine_10（人设前后矛盾）+ landmine_11（人物形象单薄）
**落点**：`rules/18-landmines.md` L78-92

#### 5.5 其他问题（秀文笔、钩子、书名简介）
**状态**：
- **秀文笔**：🟢 进入 `rules/writing-style-core.md` L116「严禁词藻堆砌/故意秀文笔」+ landmine_6（描写无效/文笔华丽）
- **钩子**：🟢 Evaluator 的 top_3_fixes 会检查章末钩子；landmine_1 会检查开篇钩子；Planner 要求输出 opening_hook + closing_hook
- **书名简介**：🟢 完整借鉴（2026-05 升级）— `PackagingAgent` 落地，产出 `state/packaging.json` 含书名候选 + 简介 + 小剧场 + 封面提示 + 标签。入口：`python -m src.pipeline --packaging`。

---

### 18 个写作雷点

| # | 教程贴雷点 | 系统 landmine 编号 | 状态 |
|---|---|---|---|
| 1 | 开篇拖沓/平淡/信息轰炸 | landmine_1 | 🟢 完整 |
| 2 | 世界观设定模糊/强行灌输 | landmine_2 + landmine_13 | 🟢 完整 |
| 3 | 人设矛盾/节奏混乱/配角工具人 | landmine_3 | 🟢 完整 |
| 4 | 视角杂乱/叙事方式不当 | landmine_4 | 🟢 完整 |
| 5 | 剧情主线模糊/平淡/混乱 | landmine_5 | 🟢 完整 |
| 6 | 描写无效/排版不规范/文笔华丽/欠佳 | landmine_6 | 🟢 完整 |
| 7 | 主线模糊与偏离 | landmine_7 | 🟢 完整 |
| 8 | 冲突乏力与爽点缺失 | landmine_8 + landmine_15 | 🟢 完整（拆为 2 条） |
| 9 | 节奏失控与过渡生硬 | landmine_9 | 🟢 完整 |
| 10 | 人设前后矛盾 | landmine_10 | 🟢 完整 |
| 11 | 人物形象单薄 | landmine_11 | 🟢 完整 |
| 12 | 情感表达生硬 | landmine_12 | 🟢 完整 |
| 13 | 世界观模糊/脱离现实 | landmine_13 | 🟢 完整 |
| 14 | 金手指失衡 | landmine_14 | 🟢 完整 |
| 15 | 爽点不足与冲突乏力 | landmine_15 | 🟢 完整 |
| 16 | 作品包装缺乏吸引力 | landmine_16 | 🟢 完整（2026-05 升级，PackagingAgent 落地） |
| 17 | 文笔不佳与排版不规范 | landmine_17 | 🟢 完整 |
| 18 | AI 味 | landmine_18 | 🟢 完整 + AISlopGuard 专项审计 |

**18 条雷点全部被系统吸收**，且每一条在 `rules/18-landmines.md` 中都保留了教程贴原文的结构：常见错误 → 危害 → 反例/正例 → 修正。

---

### §三 · 小说设定 1-16

#### 6.1 主角性格设定（极致利己 + 有底线）
**状态**：🟢 完整借鉴 — 进入港综 setting 的 `characters.yaml`
**落点**：`settings/gangster-hk-1983/characters.yaml` L9-14：
```
traits:
  - 极致利己
  - 有底线
  - 算计>胆大
redlines:
  - 不碰毒品生意
  - 不动未成年人
  - 不杀无辜老人小孩
```
**原文**：教程贴 L1520-1521 的「极致利己 + 有底线」「禁止圣母心、禁止无脑莽、禁止降智」「每一个举动背后必须有利益算计」全部进入人设档案，并通过 Evaluator 的交叉核查强制执行。

#### 6.2 系统设定（名称、商城、空间功能）
**状态**：🟢 完整借鉴 — 进入 `characters.yaml` 的 system 块
**落点**：`settings/gangster-hk-1983/characters.yaml` L23-32：
- 系统名称「港务档案」对应教程贴 L1526
- 能力「查询 1983-2000 公开事件」对应教程贴 L1527
- hard_limits 对应教程贴 L1529-1531（但系统商城和空间功能不适用——此系统是查询系统，不能输出）
- 情报值经济系统是系统独创的（教程贴未设计）
**差异**：教程贴的系统更接近传统签到/商城系统，本项目的「港务档案」是纯情报查询系统（`iron_law_extra_5` 明确禁止物理输出），这是题材适配后的改造。

#### 6.3 小说风格（暴力美学 + 爽点）
**状态**：🟢 完整借鉴 — 进入 `setting.yaml` 的 tone 字段：「暴力美学 + 克制算计 + 市井温度」
**落点**：`settings/gangster-hk-1983/setting.yaml` L11

#### 6.4 章节设定（3000 字、800-1000 章）
**状态**：🟡 部分借鉴 — 3000 字被吸收（Generator prompt 中明确「约 3000 字」），但 800-1000 章只作为 outline 的 target 标记
**落点**：`settings/gangster-hk-1983/setting.yaml` L17（`chapter_count_target: 800`）；`src/agents/generator.py` L77「约 3000 字」
**差异**：当前 MVP 只跑 3 章，不融纸嫁衣/灵魂摆渡的要求属于题材特定设定

#### 6.5 书名设定
**状态**：🔴 未借鉴 — 系统不生成书名

#### 6.6 简介设定
**状态**：🔴 未借鉴 — 系统不生成简介

#### 6.7 写作依据（24 个严禁 → 24 条铁律）

这是教程贴中被吸收比例最高的部分。教程贴的 24 个「严禁」或相关表述，与系统的 24 条 iron_laws 形成近乎一一对应的关系：

| # | 教程贴严禁/要求 | 系统 iron_law | 状态 |
|---|---|---|---|
| 1 | 联网搜索现实世界 | — | 🔴 不适用（架构约束） |
| 2 | 拒绝机械降神 | iron_law_13 | 🟢 |
| 3 | 拒绝反派降智 | iron_law_8 | 🟢 |
| 4 | 拒绝流水账 | iron_law_4 | 🟢 |
| 5 | 严禁跪舔洋人 | iron_law_extra_1（港综特供） | 🟢 |
| 6 | 严禁时间线错乱 | iron_law_12 | 🟢 |
| 7 | 严禁主角双标 | iron_law_7（主角动机利益化）+ iron_law_1（人设一致性） | 🟡 |
| 8 | 严禁无脑后宫 | iron_law_extra_6（仙侠，道侣关系严肃化）+ 港综设定女主不作花瓶 | 🟡 |
| 9 | 严禁数据模糊 | iron_law_10 | 🟢 |
| 10 | 严禁配角工具人 | iron_law_9 + iron_law_21 | 🟢 |
| 11 | 严禁文青病 | iron_law_22 | 🟢 |
| 12 | 严禁设定吃书 | iron_law_1（人设一致性）+ iron_law_extra_5（系统边界不可变） | 🟡 |
| 13 | 严禁无铺垫高潮 | iron_law_23 | 🟢 |
| 14 | 严禁照搬百科 | iron_law_14（拒绝闭门造车）的框架覆盖 | 🟡 |
| 15 | 严禁无理由的爱/恨 | iron_law_19 | 🟢 |
| 16 | 严禁烂尾逻辑 | iron_law_15 | 🟢 |
| 17 | 严禁不查证写军事 | iron_law_10（数据精准）部分覆盖 | 🟡 |
| 18 | 严禁不懂装懂金融 | iron_law_10（数据精准）部分覆盖 | 🟡 |
| 19 | 严禁 AI 式说教 | iron_law_24 | 🟢 |
| 20 | 现实世界时间线（已发资料） | era.md + timeline.yaml | 🟡（静态设定替代） |
| 21 | Show-Don't-Tell | iron_law_2 | 🟢 |
| 22 | 盐溶于汤 | iron_law_3 | 🟢 |
| 23 | 主角动机利益化 | iron_law_7 | 🟢 |
| 24 | 细节堆砌 | iron_law_20 | 🟢 |

**核心发现**：教程贴 §三·写作依据中的 24 条严禁/要求，有 15 条完整进入 24-iron-laws 成为独立条目，4 条部分覆盖，5 条因架构/题材差异未直接纳入。

---

## 架构层面的借鉴与改造

### 🟢 直接继承的结构

1. **责编 + 写手 + 改稿 三角**（教程贴角色 2/4/5 + 设定 6.7 的审核流程）→ Planner（责编视角）+ Generator（写手）+ Evaluator + Fixer（审核+改稿）的四角闭环
2. **Show-Don't-Tell 作为最高优先级的元规则** — 教程贴排创作原则第一条，系统排 iron_law_2
3. **「严禁」→「铁律」的转化** — 教程贴的语气（严禁xxx）被转化为系统 Agent 可以执行的 Yes/No 检查项
4. **人设档案制度** — 教程贴多次强调人物小传、人设档案的重要性，系统将其具象化为 characters.yaml

### 🟡 改造性吸收

1. **「逻辑死磕官」→ Evaluator 交叉核查**：教程贴是角色内省（自己反问自己），系统改为独立 Evaluator 的反问（避免自评乐观）
2. **「角色构建六步走」→ 通用规则文件**：教程贴是角色扮演的一部分，系统将其写入 Generator/Fixer 共用的 style 文件
3. **「联网搜索」→ 静态 Setting Pack**：教程贴反复强调联网，系统改为 `era.md` + `timeline.yaml` 预载——这是对延迟和可靠性的主动妥协

### 🔴 刻意不借鉴

| 类别 | 代表条目 | 原因 |
|---|---|---|
| LLM 通用指令 | 语气规范/深入解析/Markdown 格式等 | 不适用于小说写作 Agent 的 prompt 系统 |
| 领域专家角色 | 股票/军火/雇佣兵大师 | 3 个 setting 10 章长跑无此类专业剧情需求；架构选择通用 Agent + 题材注入而非专用专家（A-2 仍挂着） |
| 写作教学示例 | 流水账修改练习/开篇错误示例 | 系统目标是产出章节，不是教学 |

**曾经不借鉴但已升级**：
- 联网搜索：2026-05 由 A-1 FactChecker 按 `landmine_13` 触发 Perplexity Sonar 覆盖（见 gap-analysis A-1 小节）
- 作品包装 / 书名简介：2026-05 由 `PackagingAgent` 覆盖（`python -m src.pipeline --packaging`）

---

## 最重要的 5 个借鉴（对系统定义性影响）

1. **Show-Don't-Tell** → 系统的元规则。从 iron_law_2 到 writing-style-core 到 Generator 的 system prompt 第一句，无处不在。

2. **人设一致性原则（「过往经历+当前利益+性格底色」）** → 直接成为 iron_law_1 的公式，通过 Evaluator 对抗人设强制执行。

3. **18 个雷点 → 18 个 Landmines** → 教程贴的 18 个雷点被完整搬进 `rules/18-landmines.md`，成为 Evaluator 的评分 rubric，支撑了系统「结构化判稿」的核心能力。

4. **24 个「严禁」→ 24 条 Iron Laws** → 教程贴末尾的 24 条写作依据（严禁xxx），几乎一一对应转化为 `rules/24-iron-laws.md` 的 24 条条目。这是从「人说的指令」到「机器能执行的规则」的工程化翻译。

5. **港综题材数据（时代/物价/俚语/人物代指）** → 教程贴中对港综的详细素材（物价、俚语、人物代指、历史事件）被拆解进入 `era.md`、`timeline.yaml`、`setting.yaml`、`writing-style-extra.md`、`iron-laws-extra.md` 等 setting pack 文件。这是从「对话里的知识」到「可切换的数据文件」的转化。

---

## 最重要的 5 个刻意不借鉴（及原因）

> 注：原 5 条中有 2 条已在 2026-05 后被重新吸收（联网搜索 / 书名简介）。保留下面 3 条原样，另外加 2 条仍然不做的。

1. **LLM 通用回答格式指令**：教程贴前言 12 条中的 Markdown/LaTeX/Graphviz/专业语气等，是对 LLM 通用问答任务的要求。系统是小说写作 pipeline，不适用。

2. **多种领域专家角色（军火/股票/雇佣兵）**：教程贴拟定了 14 个角色，其中 5 个是领域专家（L95-103）。系统用 11 个 Agent（5 创作 + 3 记账 + 3 审计），不设领域专家——因为 setting pack 的 era.md 预载了足够的事实，且 C-5 港综 10 章长跑中 landmine_13 零命中，证明静态设定够用。A-2 条目仍挂着未做。

3. **写作练习与教学示例**：教程贴大量内容（如避免流水账的练习、开篇错误分析）本质是教学材料。系统是对手，不是老师——不需要教 LLM 怎么写，而是强行让写入规则的文字被遵守。

4. **「照搬百科」禁令**：教程贴说「严禁照搬百科」，但在系统中，setting pack 的 era.md 实际上就是「百科全书」——区别在于它被设计成供 Generator 在写作时内化吸收。系统通过 iron_law_18（五感代入）+ Generator 第 8 条铁律（C-30 禁百科复述）+ writing-style-core（Show-Don't-Tell）三道防线间接实现了这个约束。

5. **多人协作编辑（C-7）**：产品问题不是工程问题，跨数量级复杂（冲突解决、权限、锁）。一直维持 Won't。

### 曾经不借鉴但已升级的 2 条

- **联网搜索**：2026-05 由 A-1 FactChecker 按 `landmine_13` 触发 Perplexity Sonar 覆盖。不是让 Generator 主动联网，而是作为独立审计员按需触发，保留了"创作管线不依赖外网"的原则。
- **书名/简介/发布包装**：2026-05 由 `PackagingAgent` 覆盖，产出 `state/packaging.json`。不做番茄平台发布，但书名 + 简介 + 封面提示的完本包装已完整。

---

## 反思：教程贴到工程系统的转化规律

1. **角色 → 检查规则**：教程贴的角色（「逻辑死磕官」「人设防崩」）→ 系统中成为可运行的检查规则
2. **原则 → 可评分的条目**：教程贴的创作原则（Show-Don't-Tell、盐溶于汤）→ 系统中成为 Evaluator 能打 hit/severity 的 landmine 或 iron_law
3. **领域知识 → 数据文件**：教程贴中分散在各处的港综知识 → 系统中被结构化到 era.md、timeline.yaml、characters.yaml
4. **严禁列表 → 铁律表格**：教程贴末尾的 24 条「严禁xxx」→ 28 条编号化的 iron_law（原 24 + 2026-05 新增 4 条）
5. **生成前自检 → 双阶段自检**（2026-05 升级）：
   - **Planner 侧**：`writing_self_check` 6 维风险扫描表，作为 Generator 下笔前的告警清单
   - **事后侧**：Evaluator + AISlopGuard + CharacterGuard + FactChecker 四重独立审计
   - 两阶段一前一后夹击，比教程贴原设计的"作者一人自检"覆盖率更高

核心洞察：教程贴是一个作者与 AI 对话的工作流；系统是把这段对话中的**规则内容**提炼出来，变成多个独立 Agent 之间通过文件通信的**执行系统**。教程贴的「角色」和系统的「Agent」之间不是一一对应关系——大部分角色被拆解为检查规则注入到 Evaluator/Guard 中，少数（写手、责编）保留了独立 Agent 形态；还有一部分衍生出了**记账类 Agent**（StatusCardUpdater / HookKeeper / ResourceLedger），是教程贴未出现的形态——它们解决了教程贴作者靠"人脑记忆"处理的那部分工作。

---

*审计日期：2026-05-09 | 审计者：Fixer Agent 按 Auditor 框架执行*
