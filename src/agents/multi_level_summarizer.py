"""Multi-level summarizers for long-chain context management.

Problem: a single-level summarizer (summaries/chNNN.md, ≤300 chars) scales
poorly: by ch50, Planner reading "last 2 summaries" has 50-chapter arc gaps;
reading all 50 summaries = 15K chars into Planner context = context overflow.

Solution: three-tier summaries.

  L1 章摘 (chapter summary) — ≤300 chars per chapter (existing Summarizer)
      file: state/summaries/ch{N:03d}.md
      owner: src/agents/summarizer.py (unchanged)

  L2 弧摘 (arc summary) — ≤600 chars covering 5 consecutive chapters
      file: state/summaries/arcs/arc-{A:02d}.md  where A = ceil(N/5)
      owner: ArcSummarizer (this file)
      triggered: after the last chapter of an arc completes (ch5 / ch10 / ch15 …)

  L3 卷摘 (volume/book summary) — ≤1200 chars covering 20 chapters
      file: state/summaries/volumes/vol-{V:02d}.md where V = ceil(N/20)
      owner: BookSummarizer (this file)
      triggered: after the last chapter of a volume completes (ch20 / ch40 …)

Reading strategy for downstream (Planner + others):
  - Always read last 2 × L1
  - If current_chapter > 5, also read the most recent completed L2
  - If current_chapter > 20, also read the most recent completed L3

This keeps the context window bounded regardless of how long the novel gets,
while still preserving long-arc continuity (Lesson 3 from Cognition's Devin
postmortem — Context Reset, not context compression).

Lesson 3 boundary (CRITICAL — identical to L1 Summarizer):
  ArcSummarizer reads ONLY the L1 summaries it's summarizing. It does
  NOT read plan.json, verdict.json, issues.jsonl, or any reasoning trace.
  BookSummarizer reads ONLY L2 summaries. This prevents Generator/
  Evaluator framing from leaking across summarization boundaries.
"""
from __future__ import annotations

from pathlib import Path

from ._base import BaseAgent
from ..blackboard import Blackboard


ARC_SIZE = 5        # L2 covers 5 chapters
VOLUME_SIZE = 20    # L3 covers 20 chapters


def arc_index_for_chapter(ch: int) -> int:
    """ch=1..5 → arc 1, ch=6..10 → arc 2, …"""
    return (ch - 1) // ARC_SIZE + 1


def volume_index_for_chapter(ch: int) -> int:
    return (ch - 1) // VOLUME_SIZE + 1


def is_arc_boundary(ch: int) -> bool:
    """True when ch is the LAST chapter of an arc (ch=5, 10, 15 ...)."""
    return ch % ARC_SIZE == 0


def is_volume_boundary(ch: int) -> bool:
    """True when ch is the LAST chapter of a volume (ch=20, 40, …)."""
    return ch % VOLUME_SIZE == 0


def arc_filename(arc: int) -> str:
    return f"summaries/arcs/arc-{arc:02d}.md"


def volume_filename(vol: int) -> str:
    return f"summaries/volumes/vol-{vol:02d}.md"


def most_recent_completed_arc(current_ch: int) -> int | None:
    """Return the arc index whose L2 summary should already exist, or None."""
    # Arc A is completed when all of its ARC_SIZE chapters have been produced.
    # If current_ch=7, we're writing ch7; arcs 1 (ch1-5) is complete.
    completed = (current_ch - 1) // ARC_SIZE
    return completed if completed >= 1 else None


def most_recent_completed_volume(current_ch: int) -> int | None:
    completed = (current_ch - 1) // VOLUME_SIZE
    return completed if completed >= 1 else None


# =========================================================================
# L2 — ArcSummarizer
# =========================================================================

class ArcSummarizer(BaseAgent):
    """Summarize a 5-chapter arc from its 5 L1 summaries only.

    Runs at arc boundaries (after ch5, ch10, ch15, ...).
    """
    name = "arc_summarizer"
    temperature = 0.2
    response_format = "text"
    max_tokens = 1000

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        """chapter is the LAST chapter of the arc (e.g., 5 / 10 / 15)."""
        if not is_arc_boundary(chapter):
            raise ValueError(
                f"ArcSummarizer called at ch{chapter} which is not an arc boundary"
            )
        arc = arc_index_for_chapter(chapter)
        start = (arc - 1) * ARC_SIZE + 1
        end = arc * ARC_SIZE  # == chapter

        # Load the 5 L1 summaries for this arc — and ONLY those
        summaries: list[str] = []
        inputs_read: list[str] = []
        for ch in range(start, end + 1):
            path = f"summaries/ch{ch:03d}.md"
            if bb.exists(path):
                summaries.append(f"### 第 {ch} 章摘要\n" + bb.read_text(path))
                inputs_read.append(f"state/{path}")
        joined = "\n\n".join(summaries) if summaries else "（本弧未找到章摘）"

        system = (
            "你是一个客观的弧段摘要员。任务：把一组连续章节的单章摘要（L1）\n"
            "再次浓缩为一段 ≤600 字的弧段摘要（L2），记录这 5 章累计发生的事实。\n"
            "\n"
            "硬规则：\n"
            "1. 只读传入的章摘，不读正文、不读 plan/issues/verdict。\n"
            "2. 摘要必须是**事实**：谁、在哪、做了什么、结果如何、谁死了、谁变强了、谁和谁结盟了、什么宝物被得到、什么伏笔被埋下或回收。\n"
            "3. 不写评价、感受、预测、修辞。\n"
            "4. 严格 ≤600 字。\n"
            "5. 使用简体中文。\n"
            "6. 直接用人名，不用『主角』『他』等代称。\n"
            "7. 不要加任何标题、引言或 Markdown 结构。\n"
            "8. 把这 5 章视作一个**有内在弧线**的整体——开端、推进、转折、结局——\n"
            "   用一段连贯的叙述串起来，不是 5 条独立流水账。\n"
            "9. **在事实流水之后，必须单独追加一段 ≤200 字的『节奏报表』**——\n"
            "   这是 P2 防 dna value_anchor 在长链摘要中被过滤的关键段，\n"
            "   Planner 读到这段会触发主动节奏设计。格式如下（标题必须就用 `## 节奏报表（用于 Planner 决策）`）：\n"
            "\n"
            "   ## 节奏报表（用于 Planner 决策）\n"
            "   - chapter_type 分布：战斗×N / 布局×N / 过渡×N / 回收×N\n"
            "   - 主动 vs 被动场景比：主动设局 N 次（ch{X}, ch{Y}）；被动求生 N 次\n"
            "   - dna anchor 兑现：爽感×N / 掌控感×N / 黑色幽默×N / 生存智慧×N\n"
            "   - 新增未回收伏笔数：N\n"
            "   - 节奏判断：[1 句话总结，例：『本弧节奏偏被动，5 章 0 爽感 0 掌控感』 / 『节奏均衡』]\n"
            "\n"
            "   节奏报表只能依据 L1 章摘里出现的事实推断——L1 没显示的不要硬塞 anchor。\n"
        )
        user = (
            f"# 第 {arc} 弧（第 {start}-{end} 章）的 L1 章摘\n\n"
            f"{joined}\n\n"
            f"# 任务\n\n"
            f"请输出第 {arc} 弧的弧段摘要（≤600 字，一段，连贯叙述）。"
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        arc = arc_index_for_chapter(chapter)
        # Ensure dir exists
        (bb.root / "summaries" / "arcs").mkdir(parents=True, exist_ok=True)
        bb.write_text(arc_filename(arc), raw.strip() + "\n")


# =========================================================================
# L3 — BookSummarizer (volume scope: 4 arcs = 20 chapters)
# =========================================================================

class BookSummarizer(BaseAgent):
    """Summarize a 20-chapter volume from its 4 L2 arc summaries only.

    Runs at volume boundaries (after ch20, ch40, ...).
    """
    name = "book_summarizer"
    temperature = 0.2
    response_format = "text"
    max_tokens = 1500

    def _build_prompts(self, bb: Blackboard, *, chapter: int, **_):
        if not is_volume_boundary(chapter):
            raise ValueError(
                f"BookSummarizer called at ch{chapter} which is not a volume boundary"
            )
        vol = volume_index_for_chapter(chapter)
        start_arc = (vol - 1) * (VOLUME_SIZE // ARC_SIZE) + 1
        end_arc = vol * (VOLUME_SIZE // ARC_SIZE)

        # Load the 4 L2 arc summaries for this volume — and ONLY those
        arcs: list[str] = []
        inputs_read: list[str] = []
        for a in range(start_arc, end_arc + 1):
            path = arc_filename(a)
            if bb.exists(path):
                arcs.append(f"### 第 {a} 弧摘要\n" + bb.read_text(path))
                inputs_read.append(f"state/{path}")
        joined = "\n\n".join(arcs) if arcs else "（本卷未找到弧摘）"

        system = (
            "你是一个客观的卷摘摘要员。任务：把一组连续弧段的摘要（L2）\n"
            "进一步浓缩为一段 ≤1200 字的卷摘（L3），记录这 20 章累计发生的事实。\n"
            "\n"
            "硬规则：\n"
            "1. 只读传入的弧摘，不读章摘、不读正文、不读任何 reasoning trace。\n"
            "2. 摘要必须是**事实**：阶段性转折、主要角色的命运变化、资源与地位的演变、主要伏笔的设置与回收、世界观的推进。\n"
            "3. 不写评价、感受、预测、修辞。\n"
            "4. 严格 ≤1200 字。\n"
            "5. 使用简体中文。\n"
            "6. 直接用人名，不用代称。\n"
            "7. 不要加任何标题、引言或 Markdown 结构。\n"
            "8. 把这 20 章视作一个**卷**——开端、上升、高潮、收束——用 2-4 段文字串起来。\n"
            "9. 强调**长线元素**：跨弧的伏笔、长期敌我关系、累计资源/境界变化。\n"
            "10. **在事实流水之后，必须单独追加一段 ≤300 字的『节奏报表』**——\n"
            "    这是 P2 防 dna value_anchor 在长链摘要中被过滤的关键段。\n"
            "    把 4 个 L2 弧摘各自的『节奏报表』汇总到本卷尺度。格式：\n"
            "\n"
            "    ## 节奏报表（用于 Planner 决策）\n"
            "    - chapter_type 分布：战斗×N / 布局×N / 过渡×N / 回收×N（全卷 20 章合计）\n"
            "    - 主动 vs 被动场景比：主动设局 N 次（ch{X1}, ch{X2}, ...）；被动求生 N 次\n"
            "    - dna anchor 兑现：爽感×N / 掌控感×N / 黑色幽默×N / 生存智慧×N\n"
            "    - 卷末未回收伏笔数：N\n"
            "    - 节奏判断：[1-2 句话总结全卷的节奏强弱，例：『本卷前 10 章爽感缺失，后 10 章靠 ch{N} 反转补回来；整体节奏偏后置』]\n"
            "\n"
            "    节奏报表的数字应**汇总自 L2 节奏报表**，不要再去推断单章。\n"
        )
        user = (
            f"# 第 {vol} 卷（弧 {start_arc}-{end_arc}）的 L2 弧摘\n\n"
            f"{joined}\n\n"
            f"# 任务\n\n"
            f"请输出第 {vol} 卷的卷摘（≤1200 字）。"
        )
        return system, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, chapter: int, **_):
        vol = volume_index_for_chapter(chapter)
        (bb.root / "summaries" / "volumes").mkdir(parents=True, exist_ok=True)
        bb.write_text(volume_filename(vol), raw.strip() + "\n")


# =========================================================================
# Context assembly helper — used by Planner to read the right mix of levels
# =========================================================================

def assemble_long_chain_context(bb: Blackboard, current_chapter: int) -> tuple[str, list[str]]:
    """Return (context_text, inputs_read_paths) for use in Planner/Generator.

    Strategy:
        - Always: last 2 × L1 chapter summaries
        - If current_chapter > ARC_SIZE: plus the most recent completed L2 arc summary
        - If current_chapter > VOLUME_SIZE: plus the most recent completed L3 volume summary

    Returns empty string and empty list for ch=1 (no prior context).
    """
    parts: list[str] = []
    inputs_read: list[str] = []

    # L1: last 2 chapter summaries
    l1_taken = []
    for n in (current_chapter - 2, current_chapter - 1):
        if n >= 1:
            path = f"summaries/ch{n:03d}.md"
            if bb.exists(path):
                parts.append(f"### 第 {n} 章摘要（L1）\n" + bb.read_text(path))
                inputs_read.append(f"state/{path}")
                l1_taken.append(n)

    # L2: most recent completed arc summary (if any)
    arc = most_recent_completed_arc(current_chapter)
    if arc is not None and current_chapter > ARC_SIZE:
        path = arc_filename(arc)
        if bb.exists(path):
            parts.append(f"### 第 {arc} 弧摘要（L2，覆盖 ch{(arc-1)*ARC_SIZE+1}-ch{arc*ARC_SIZE}）\n" + bb.read_text(path))
            inputs_read.append(f"state/{path}")

    # L3: most recent completed volume summary (if any)
    vol = most_recent_completed_volume(current_chapter)
    if vol is not None and current_chapter > VOLUME_SIZE:
        path = volume_filename(vol)
        if bb.exists(path):
            parts.append(
                f"### 第 {vol} 卷摘要（L3，覆盖 ch{(vol-1)*VOLUME_SIZE+1}-ch{vol*VOLUME_SIZE}）\n"
                + bb.read_text(path)
            )
            inputs_read.append(f"state/{path}")

    if not parts:
        return "（这是首章或紧邻首章，无前情摘要）", inputs_read

    return "\n\n".join(parts), inputs_read
