# 信息源优先级（冲突仲裁协议）

> 本文件是**所有 Agent 遇到信息冲突时的仲裁规则**。Evaluator、Fixer、Planner、Generator 在 system prompt 中必须引用它。
> 灵感来自 skill #2「信息源优先级」——长链路（30+ 章）写作时，摘要与设定必然冲突，必须有明确协议才能仲裁。

## 默认优先级（高到低）

当两份资料对同一事实有不同描述时，按以下顺序采信：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | 用户**本轮**明确要求 | 最高，直接覆盖所有其他来源（但仍受铁律约束） |
| 2 | 用户**本轮**贴的正文片段 | 次高，视为本次上下文的权威事实 |
| 3 | `state/current_status_card.md` | **当前时间点**权威快照，覆盖过期设定 |
| 4 | `state/chapters/ch{N}.md`（最近 2-3 章正文） | 最新正文 > 任何摘要；是 ground truth |
| 5 | `state/summaries/ch{N}.md`（章摘） / `arcs/arc-{A}.md`（弧摘） / `volumes/vol-{V}.md`（卷摘） | 二手事实；与正文冲突时**丢弃摘要** |
| 6 | `state/characters.yaml` + `state/timeline.yaml` | 静态档案；如主角发生境界变化/失去资源，以最新正文为准 |
| 7 | `state/outline.json` | 大纲是路线图，**不是合约**；最新正文可改写大纲 |
| 8 | `state/era.md` | 时代/世界观事实包，仅供**场景融入**，不得成为正文（见 iron_law 禁百科） |
| 9 | `rules/*.md`（通用铁律与 landmines） | 最低优先级但**硬约束**，不得违反 |

## 仲裁规则

### R1 · 正文永远是 ground truth

如果 `current_status_card.md` 或 `summaries/*` 与 `chapters/ch{N}.md` 冲突：
- 以**最新正文**为准
- 在状态卡上记录『根据 ch{N} 正文修正』，并推进更新
- 不得反向修改已完成章节的正文来迎合过期状态卡

### R2 · 状态卡优于静态档案

如果 `current_status_card.md` 说主角"已失去情报系统"，但 `characters.yaml` 说主角"有金手指情报系统"：
- 以**状态卡**为准
- `characters.yaml` 是**出场时的初始档案**，不是当前状态

### R3 · 大纲可被正文改写

如果 `outline.json` 计划让某角色在 ch10 回归，但 ch9 正文让他死了：
- 以**正文**为准
- Planner 在写 ch10 plan 时**必须检测到这个冲突**，改写或请求 Fixer 调整 ch9（而不是让角色复活）
- 永远不允许"机械照大纲走"

### R4 · 铁律是硬下限

优先级再高的来源，也不得突破 `rules/24-iron-laws.md` 与 `rules/18-landmines.md`：
- 用户说"让主角突然爆杀反派"→ 仍受 iron_law（动机链、反派信息边界）约束
- 大纲说"主角跳级突破"→ 仍受 iron_law（收益具体化、不跳数量级）约束

### R5 · 冲突必须显式标记，不得静默协调

Agent 检测到两份来源冲突时：
- 不得凭"创作直觉"在两者之间折中
- 必须在对应 Agent 的输出中**显式说明**采信了哪份、丢弃了哪份（写在 plan.json 的 `conflicts_resolved` 字段、verdict.json 的 `evidence` 字段、状态卡的备注列）

## 示例冲突与处理

**冲突 A**：`summaries/ch005.md` 说"沈若微去了北京"，但 `chapters/ch006.md` 正文描述她在深圳上班。
→ **采信 ch006 正文**（R1）。`ch005.md` 摘要可能有误，但不动它（历史摘要仅供参考，不回改）；在下一次 `current_status_card.md` 中明确『当前位置=深圳』。

**冲突 B**：`characters.yaml` 说林昭宇是"CTO"，但 ch7 正文让他被迫辞职回家乡。
→ **采信正文 + 状态卡**（R2）。`current_status_card.md` 的"主角当前状态"反映最新职业。`characters.yaml` 不动（那是初始档案）。

**冲突 C**：`outline.json` ch12 让顾安安介绍投行 offer，但 ch11 状态卡显示两人因一场矛盾三个月没联系。
→ **采信状态卡**（R3）。Planner 必须在 ch12 plan 中**先处理关系修复**或**换别的介绍人**，不得让顾安安若无其事地打电话。

**冲突 D**：用户说"让沈若微辞职"。`outline.json` 规划 ch15 才离职，现在是 ch8。
→ 用户本轮要求 > 大纲（R1）。但**仍受铁律约束**——ch8 辞职需要"心理成本"描写（iron_law_extra_1 for urban-romance），不能突然。Planner 应在 ch7-ch8 插入铺垫 beat。

## 在各 Agent 中如何引用

- **Planner**：开场读 `current_status_card.md`（优先级 3），对照 `outline.json`（7），若冲突按 R3 处理。
- **Generator**：读 plan.json + era.md，不直接读摘要；写作时按 R4 遵守铁律。
- **Evaluator**：审正文（4）与 landmines/iron-laws（9）一致性；若 evidence 冲突，按本文件仲裁。
- **Fixer**：按 Evaluator 的 top_3_fixes 修；若修改方向与状态卡冲突，**不修正文，改状态卡**（R1 反向）——此时由 StatusCardUpdater 下一轮覆盖。

---

> 核心原则：**正文是 ground truth；状态卡是最新权威快照；大纲是路线图不是合约；规则是不可逾越的下限。**
