"""StatusCardUpdater — maintain state/current_status_card.md.

Lesson 3 from Cognition's Devin postmortem: Context Reset.
The status card is the ONE authoritative snapshot of "current time point":
- which chapter we're at
- protagonist's current state / stage / resources
- current adversarial landscape
- current known truths (what everyone knows vs. what only the reader knows)
- currently active (unresolved) hooks
- current chapter's task card

Purpose:
- When a new process takes over (Context Reset), reading this one file
  is enough to rebuild situational awareness.
- Planner reads this BEFORE building the next chapter's plan, so the plan
  reflects the actual current state (not a linear-summary approximation).

This agent runs AFTER Summarizer, at the end of each chapter.

Reads:
  - state/chapters/ch{N:03d}.md           — the fresh chapter prose
  - state/current_status_card.md          — the PREVIOUS version (or empty)
  - state/characters.yaml                  — persona anchors
  - state/setting.yaml                     — era label & genre

Writes:
  - state/current_status_card.md   (Markdown table format, overwritten each time)

Lesson 3 boundary:
  StatusCardUpdater reads the CHAPTER PROSE (not plan / verdict / issues).
  This keeps the card a factual snapshot, not a planning trace. Any
  mismatch between card and prose is resolved by the prose (prose is ground
  truth; card is derived).

Temperature 0.2 — this is a bookkeeping task, not creative writing.
"""
from __future__ import annotations

from ._base import BaseAgent
from ..blackboard import Blackboard


# The canonical skeleton Markdown structure.
# We show this to the LLM as the authoritative format to preserve.
STATUS_CARD_SKELETON = """\
# 当前状态卡

> 唯一的"当前时间点"状态覆盖文件。任何冲突以最新章节正文为准，此卡过期则先修卡再继续。
> 由 StatusCardUpdater 在每章结束后覆盖更新。

## 时间与位置锚点

| 字段 | 值 | 备注 |
|---|---|---|
| 当前章 | ch{N} | |
| 故事内时间 | (YYYY-MM 或题材内纪年) | |
| 当前位置 | (主角当前所在地) | |

## 主角当前状态

| 字段 | 值 | 备注 |
|---|---|---|
| 姓名 | | |
| 境界/职级/阶段 | | 随题材（修仙境界 / 职业层级 / 社团辈分） |
| 身体状态 | | 伤势 / 疲惫 / 中毒 / 健康 |
| 心理状态 | | 当前核心情绪、当前最大焦虑 |
| 当前身份 | | 公开身份 + 隐藏身份（如有） |

## 主角本章目标与限制

| 字段 | 值 |
|---|---|
| 上章遗留目标 | |
| 本章已完成 | |
| 本章未竟 | |
| 当前硬限制 | 时间 / 金钱 / 信息 / 体力 / 人脉的具体约束 |

## 当前敌我关系

| 对象 | 立场 | 关系强度 | 最近动作 | 备注 |
|---|---|---|---|---|
| | 盟友/敌人/中立/暧昧 | 强/中/弱 | | |

## 主角主动账本（Agency Ledger）

> Lesson 3 的"被动求生 → 主动设局"防呆段。每个『距上次 N 章』必须基于历史正文计算，禁止编造。

| 字段 | 值 | 备注 |
|---|---|---|
| 当前最强的牌 | (主角当前最有威慑/影响力的能力或道具，1 句) | 距上次使用：ch{N}（已 {M} 章未亮） |
| 上次主动设局 | ch{N}（1 句描述）| 已 {M} 章 |
| 上次黑色幽默时刻 | ch{N}（1 句）| 已 {M} 章 |
| 上次爽感兑现 | ch{N}（1 句）| 已 {M} 章 |
| 当前 anchor 缺口 | (从 4 种 dna anchor 看哪几种缺失：爽感 / 掌控感 / 黑色幽默 / 生存智慧) | 下章必须补 |

## 当前资源与收益账本

| 资源类型 | 当前量 | 本章增减 | 折算/来源 |
|---|---|---|---|
| | | | |

## 当前已知真相（谁知道什么）

| 信息项 | 主角知否 | 反派知否 | 读者知否 | 其他关键人知否 |
|---|---|---|---|---|
| | 是/否 | 是/否 | 是/否 | |

## 当前活跃伏笔（未回收）

> 当前活跃伏笔详见 `pending_hooks.md`（HookKeeper 维护，权威）。本卡不再
> 重复登记伏笔池——避免与 HookKeeper 输出双源不一致。

## 下一章任务卡（给 Planner 的输入）

| 字段 | 建议 |
|---|---|
| 建议主冲突 | |
| 建议推进的伏笔 | (hook_id 列表) |
| 建议回收的伏笔 | (hook_id 列表) |
| 建议出场人物 | |
| 建议规避的重复 | (本卡中最近章节已写过的场景/桥段) |
"""


class StatusCardUpdater(BaseAgent):
    name = "status_card_updater"
    temperature = 0.2
    response_format = "text"
    max_tokens = 4000

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        chapter_path = f"chapters/ch{chapter:03d}.md"
        chapter_text = bb.read_text(chapter_path)

        # Previous status card (may not exist for ch1)
        if bb.exists("current_status_card.md"):
            prior_card = bb.read_text("current_status_card.md")
            prior_note = "（下方是上一版状态卡，作为 diff 基准，请在本次更新中**覆盖过期字段**）"
        else:
            prior_card = STATUS_CARD_SKELETON.replace("{N}", str(chapter))
            prior_note = "（本章是首章或首次生成状态卡，下方是空白骨架，请**填满所有字段**）"

        characters = bb.read_text("characters.yaml")

        try:
            setting = bb.read_yaml("setting.yaml")
        except (OSError, Exception):
            setting = {}
        genre = setting.get("genre", "通用小说")
        era_label = setting.get("era", "")

        inputs_read = [
            f"state/{chapter_path}",
            "state/characters.yaml",
            "state/setting.yaml",
        ]
        if bb.exists("current_status_card.md"):
            inputs_read.append("state/current_status_card.md")

        system = (
            f"你是一个客观的状态卡维护员。题材：{genre}；时代/世界观：{era_label}。\n"
            f"\n"
            f"你的任务：基于刚产出的第 {chapter} 章正文，更新 `current_status_card.md`。\n"
            f"这张卡是『**当前时间点**』唯一的权威状态覆盖文件——当 Agent 进程重启或\n"
            f"Context Reset 时，读这一张卡就要能重建局势。\n"
            f"\n"
            f"# 硬规则\n"
            f"1. 只读传入的章节正文、人物档案、setting 元数据、上一版状态卡。**不读** plan / issues / verdict。\n"
            f"2. 输出是**一份完整的 Markdown 表格文档**，严格遵守骨架的标题层级与表头。\n"
            f"3. 每一处字段必须是**事实**：谁、在哪、做了什么、当前是什么状态。\n"
            f"   不写评价、感受、预测、修辞。\n"
            f"4. 时间锚点、主角状态、敌我关系、资源、已知真相——**过期字段必须覆盖**，\n"
            f"   新出现的人物/资源**必须新增行**。\n"
            f"5. 伏笔池由 HookKeeper 维护到 `pending_hooks.md`，本卡**不再登记**伏笔，\n"
            f"   只在『当前活跃伏笔』段保留指向 `pending_hooks.md` 的指针。\n"
            f"6. 『已知真相』表必须明确区分 4 列：主角知否 / 反派知否 / 读者知否 / 其他关键人知否。\n"
            f"   这张表是 Evaluator 审『反派信息越界』的主要依据。\n"
            f"6b. **必须输出『主角主动账本（Agency Ledger）』段**——这是 P1 防『被动求生』退化的关键。\n"
            f"   格式：与骨架表格一致，包含以下五行（每行『距上次 N 章』必须基于历史正文计算，**不允许编造**）：\n"
            f"   - 『当前最强的牌』：主角当前最有威慑 / 影响力的能力或道具，1 句话；备注列写『距上次使用：ch{{N}}（已 {{M}} 章未亮）』\n"
            f"   - 『上次主动设局』：『主动设局』指主角不是被动反应而是**主动操控、布局、欺骗、利用规则**的场景\n"
            f"   - 『上次黑色幽默时刻』：『黑色幽默』指主角面对死亡 / 绝境的吐槽性内心独白或荒诞行为\n"
            f"   - 『上次爽感兑现』：『爽感兑现』指反派被打脸 / 资源逆袭 / 能力首秀这种读者期待的兑现时刻\n"
            f"   - 『当前 anchor 缺口』：从 4 种 dna anchor（爽感 / 掌控感 / 黑色幽默 / 生存智慧）看哪几种最近 5 章缺失，下章必须补\n"
            f"   如果某项至今从未出现，写『从未』+章数（如『已 {chapter} 章』），而不是编造一个虚假章号。\n"
            f"7. 『下一章任务卡』必须给出具体可执行的建议（不是『继续发展剧情』这种空话），\n"
            f"   给 Planner 读本卡时可直接作为 ch{chapter+1} 的 plan 种子。\n"
            f"8. 如果上一版卡与本章正文冲突，以**正文为准**，在对应行备注写『(根据 ch{chapter} 正文修正)』。\n"
            f"9. 使用简体中文。直接用人名，不用『主角』『他』等代称。\n"
            f"10. 不要加任何段首 meta 注释、不要解释『我做了什么』，直接输出 Markdown。\n"
            f"\n"
            f"# 不允许的输出\n"
            f"- 整段散文叙述（必须用表格）\n"
            f"- 『此处待补充』『暂无』这种占位（写『-』或删掉该行）\n"
            f"- 超出表格骨架的自创章节\n"
            f"- 重复原骨架的『(主角当前所在地)』这种括号占位——必须填具体值\n"
        )

        user = (
            f"# 上一版状态卡 {prior_note}\n\n"
            f"```markdown\n{prior_card}\n```\n\n"
            f"# 第 {chapter} 章正文（基准事实）\n\n"
            f"{chapter_text}\n\n"
            f"# 人物档案（身份锚点）\n\n"
            f"```yaml\n{characters}\n```\n\n"
            f"# 任务\n\n"
            f"输出更新后的完整 `current_status_card.md`。Markdown 格式，遵守骨架表头。"
            f"第一行是 `# 当前状态卡` 标题，之后严格按骨架填表。"
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        # Strip any ```markdown fences the LLM might wrap output in
        text = raw.strip()
        if text.startswith("```"):
            # Drop first fence line
            lines = text.split("\n")
            lines = lines[1:]
            # Drop closing fence if present
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        bb.write_text("current_status_card.md", text + "\n")


def read_current_status_card(bb: Blackboard) -> tuple[str, list[str]]:
    """Helper for downstream agents (Planner, Generator).

    Returns (card_text, inputs_read). Returns ("(尚无状态卡——本章是首章或首次运行)", [])
    if the card does not yet exist.
    """
    if bb.exists("current_status_card.md"):
        return bb.read_text("current_status_card.md"), ["state/current_status_card.md"]
    return "（尚无状态卡——本章是首章或状态卡尚未产出）", []
