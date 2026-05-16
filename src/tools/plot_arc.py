"""Plot Arc — 全书坐标系（P0+P1 Oracle 诊断的核心修复）.

Oracle 诊断 Planner 剧情停滞根因：架构缺"全书坐标系"模块——Planner 只看局部
上下文（最近 2 章 + 最新 arc + 状态卡），不知道自己在写 ch30/50（60% 进度），
不知道全书目标和阶段任务，所以退化为"局部贪心"——每章原地循环。

P0 续：milestones + anchor_quota 让 act 不再只是"区间+目标"，而是带强制爽点
节拍 + anchor 配比硬约束的节奏脊柱。Planner 在 milestone 章节会被强制兑现
beat / chapter_type / advances，避免 dna value_anchors 在长链中被过滤。

本模块提供：
  - PlotMilestone / PlotAct / PlotArc dataclass（schema_version=1）
  - read_plot_arc(project_dir): 读 yaml + 校验
  - derive_planner_context(arc, current_chapter): 派生 Planner 用的字段
    （含当前 milestone / 下一 milestone / 距离）

文件位置约定：
  - 作品源：projects/<id>/plot_arc.yaml
  - bootstrap 拷到：projects/<id>/state/plot_arc.yaml
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import yaml


SCHEMA_VERSION = 1

# DNA value anchors —— 4 种合法 anchor 值（来自 NovelDNA universal.value_anchors）
VALID_ANCHORS = ("爽感", "掌控感", "黑色幽默", "生存智慧")

# chapter_type 4 选一（与 Planner system prompt 一致）
VALID_CHAPTER_TYPES = ("战斗", "布局", "过渡", "回收")

# advances 类目（与 Planner system prompt 一致）
VALID_ADVANCES = ("信息", "地位", "资源", "伤亡", "仇恨", "境界")


@dataclass
class PlotMilestone:
    """卷内某一章的强制爽点节拍。

    chapter:              该 milestone 落在哪一章（必须在所属 act.range 内）
    type:                 描述性类型（如"能力升级 / 反派打脸 / 资源逆袭"）
    anchor:               必须 ∈ VALID_ANCHORS
    force_chapter_type:   可选，命中本章时 Planner 强制此 chapter_type
    force_advances:       可选，scenes[].advances 至少含其中之一
    beat:                 ≥1 句话描述本章必须兑现的奇观时刻（Evaluator 据此审核）
    payoff_recipe_ref:    可选，指向 dna_structured.yaml 的 recipe key。
                          形式：
                            - "<anchor>"                  → 仅锚 anchor，取通用配方
                            - "<anchor>.<pattern_name>"   → 精确指向 villain_defeat_patterns
                                                            里某条 pattern（如『爽感.信息差打脸』）
                          anchor 必须 ∈ VALID_ANCHORS。pattern_name 自由文本，
                          运行期 Planner 会去 dna_structured.yaml 查表，找不到则降级
                          为只用 payoff_recipes[anchor] 的配方。
    """

    chapter: int
    type: str
    anchor: str
    force_chapter_type: Optional[str] = None
    force_advances: list[str] = field(default_factory=list)
    beat: str = ""
    payoff_recipe_ref: Optional[str] = None


@dataclass
class PlotAct:
    name: str
    range: tuple[int, int]            # 章号区间（含两端）
    goal: str = ""
    must_open_by_ch: list[int] = field(default_factory=list)
    must_close_by_end: list[str] = field(default_factory=list)
    # P0 续：可选爽点节拍 + 全卷 anchor 配比硬约束
    milestones: list[PlotMilestone] = field(default_factory=list)
    # anchor_quota: dict[anchor_name -> int|str]，str 形如 ">=8"。
    # key 必须 ∈ VALID_ANCHORS。不写 → 该卷无强制 anchor 配比。
    anchor_quota: dict[str, Union[int, str]] = field(default_factory=dict)


@dataclass
class PlotArc:
    schema_version: int
    total_chapters: int
    ultimate_goal: str
    acts: list[PlotAct]


def _parse_anchor_quota_value(v) -> Union[int, str]:
    """Accept int or string (e.g. '>=8'). Return as-is after light validation."""
    if isinstance(v, int):
        if v < 0:
            raise ValueError(f"anchor_quota value must be non-negative, got {v}")
        return v
    if isinstance(v, str):
        s = v.strip()
        # Light syntactic check: must look like a comparator + integer.
        # We don't enforce strict parsing here; downstream Planner just shows
        # the string verbatim to the LLM ("配额: >=8").
        if not s:
            raise ValueError("anchor_quota value must be a non-empty string")
        return s
    raise ValueError(
        f"anchor_quota value must be int or string, got {type(v).__name__}: {v!r}"
    )


def read_plot_arc(project_or_state_dir: Path) -> Optional[PlotArc]:
    """读 plot_arc.yaml 并校验 schema。

    参数：
      project_or_state_dir: 包含 plot_arc.yaml 的目录（作品根目录或 state/）

    返回：
      PlotArc 实例；文件不存在 → None；schema 错误 → 抛 ValueError。
    """
    path = Path(project_or_state_dir) / "plot_arc.yaml"
    if not path.exists():
        return None

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"plot_arc.yaml: malformed YAML: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"plot_arc.yaml: top-level must be a mapping, got {type(data).__name__}")

    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"plot_arc.yaml: schema_version must be {SCHEMA_VERSION}, got {schema_version!r}"
        )

    total_chapters = data.get("total_chapters")
    if not isinstance(total_chapters, int) or total_chapters < 1:
        raise ValueError(
            f"plot_arc.yaml: total_chapters must be a positive int, got {total_chapters!r}"
        )

    ultimate_goal = data.get("ultimate_goal", "")
    if not isinstance(ultimate_goal, str):
        raise ValueError("plot_arc.yaml: ultimate_goal must be a string")

    raw_acts = data.get("acts")
    if not isinstance(raw_acts, list) or not raw_acts:
        raise ValueError("plot_arc.yaml: acts must be a non-empty list")

    acts: list[PlotAct] = []
    for i, raw in enumerate(raw_acts):
        if not isinstance(raw, dict):
            raise ValueError(f"plot_arc.yaml: acts[{i}] must be a mapping")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"plot_arc.yaml: acts[{i}].name must be a non-empty string")
        rng = raw.get("range")
        if (
            not isinstance(rng, list)
            or len(rng) != 2
            or not all(isinstance(x, int) for x in rng)
            or rng[0] > rng[1]
            or rng[0] < 1
        ):
            raise ValueError(
                f"plot_arc.yaml: acts[{i}].range must be [start, end] with 1 <= start <= end, got {rng!r}"
            )
        goal = raw.get("goal", "") or ""
        must_open = raw.get("must_open_by_ch", []) or []
        must_close = raw.get("must_close_by_end", []) or []
        if not isinstance(goal, str):
            raise ValueError(f"plot_arc.yaml: acts[{i}].goal must be a string")
        if not isinstance(must_open, list):
            raise ValueError(f"plot_arc.yaml: acts[{i}].must_open_by_ch must be a list")
        if not isinstance(must_close, list):
            raise ValueError(f"plot_arc.yaml: acts[{i}].must_close_by_end must be a list")

        # P0 续：milestones 校验
        raw_milestones = raw.get("milestones", []) or []
        if not isinstance(raw_milestones, list):
            raise ValueError(f"plot_arc.yaml: acts[{i}].milestones must be a list")
        milestones: list[PlotMilestone] = []
        for j, m in enumerate(raw_milestones):
            if not isinstance(m, dict):
                raise ValueError(
                    f"plot_arc.yaml: acts[{i}].milestones[{j}] must be a mapping"
                )
            ms_chapter = m.get("chapter")
            if not isinstance(ms_chapter, int):
                raise ValueError(
                    f"plot_arc.yaml: acts[{i}].milestones[{j}].chapter must be int, "
                    f"got {ms_chapter!r}"
                )
            if not (rng[0] <= ms_chapter <= rng[1]):
                raise ValueError(
                    f"plot_arc.yaml: acts[{i}] '{name}' milestone[{j}].chapter={ms_chapter} "
                    f"is outside act.range {rng}"
                )
            ms_anchor = m.get("anchor")
            if ms_anchor not in VALID_ANCHORS:
                raise ValueError(
                    f"plot_arc.yaml: acts[{i}].milestones[{j}].anchor must be one of "
                    f"{VALID_ANCHORS}, got {ms_anchor!r}"
                )
            ms_type = m.get("type", "")
            if not isinstance(ms_type, str):
                raise ValueError(
                    f"plot_arc.yaml: acts[{i}].milestones[{j}].type must be a string"
                )
            ms_beat = m.get("beat", "")
            if not isinstance(ms_beat, str):
                raise ValueError(
                    f"plot_arc.yaml: acts[{i}].milestones[{j}].beat must be a string"
                )
            ms_force_ct = m.get("force_chapter_type")
            if ms_force_ct is not None and ms_force_ct not in VALID_CHAPTER_TYPES:
                raise ValueError(
                    f"plot_arc.yaml: acts[{i}].milestones[{j}].force_chapter_type must be one of "
                    f"{VALID_CHAPTER_TYPES}, got {ms_force_ct!r}"
                )
            ms_force_adv = m.get("force_advances", []) or []
            if not isinstance(ms_force_adv, list):
                raise ValueError(
                    f"plot_arc.yaml: acts[{i}].milestones[{j}].force_advances must be a list"
                )
            for adv in ms_force_adv:
                if adv not in VALID_ADVANCES:
                    raise ValueError(
                        f"plot_arc.yaml: acts[{i}].milestones[{j}].force_advances element "
                        f"{adv!r} must be one of {VALID_ADVANCES}"
                    )
            # P3 续：payoff_recipe_ref 校验。格式必须是 "<anchor>" 或 "<anchor>.<pattern>"
            ms_recipe_ref = m.get("payoff_recipe_ref")
            if ms_recipe_ref is not None:
                if not isinstance(ms_recipe_ref, str) or not ms_recipe_ref.strip():
                    raise ValueError(
                        f"plot_arc.yaml: acts[{i}].milestones[{j}].payoff_recipe_ref "
                        f"must be a non-empty string, got {ms_recipe_ref!r}"
                    )
                # 至少一段，最多两段（anchor 或 anchor.pattern）
                parts = ms_recipe_ref.split(".", 1)
                if len(parts) == 0 or len(parts) > 2:
                    raise ValueError(
                        f"plot_arc.yaml: acts[{i}].milestones[{j}].payoff_recipe_ref "
                        f"format invalid; expected '<anchor>' or '<anchor>.<pattern>', "
                        f"got {ms_recipe_ref!r}"
                    )
                anchor_part = parts[0].strip()
                if anchor_part not in VALID_ANCHORS:
                    raise ValueError(
                        f"plot_arc.yaml: acts[{i}].milestones[{j}].payoff_recipe_ref "
                        f"anchor part {anchor_part!r} must be one of {VALID_ANCHORS}"
                    )
                # pattern part 可以是任意非空字符串（DNA tipsfile 里的具体 pattern key）
                if len(parts) == 2 and not parts[1].strip():
                    raise ValueError(
                        f"plot_arc.yaml: acts[{i}].milestones[{j}].payoff_recipe_ref "
                        f"pattern part is empty after dot in {ms_recipe_ref!r}"
                    )

            milestones.append(
                PlotMilestone(
                    chapter=ms_chapter,
                    type=ms_type,
                    anchor=ms_anchor,
                    force_chapter_type=ms_force_ct,
                    force_advances=list(ms_force_adv),
                    beat=ms_beat,
                    payoff_recipe_ref=ms_recipe_ref,
                )
            )

        # P0 续：anchor_quota 校验
        raw_quota = raw.get("anchor_quota", {}) or {}
        if not isinstance(raw_quota, dict):
            raise ValueError(
                f"plot_arc.yaml: acts[{i}].anchor_quota must be a mapping"
            )
        anchor_quota: dict[str, Union[int, str]] = {}
        for k, v in raw_quota.items():
            if k not in VALID_ANCHORS:
                raise ValueError(
                    f"plot_arc.yaml: acts[{i}].anchor_quota key {k!r} must be one of "
                    f"{VALID_ANCHORS}"
                )
            anchor_quota[k] = _parse_anchor_quota_value(v)

        acts.append(
            PlotAct(
                name=name,
                range=(rng[0], rng[1]),
                goal=goal,
                must_open_by_ch=[int(x) for x in must_open],
                must_close_by_end=[str(x) for x in must_close],
                milestones=milestones,
                anchor_quota=anchor_quota,
            )
        )

    # 校验 acts 覆盖完整 1..total_chapters，且无重叠
    sorted_acts = sorted(acts, key=lambda a: a.range[0])
    expected_start = 1
    for a in sorted_acts:
        if a.range[0] != expected_start:
            raise ValueError(
                f"plot_arc.yaml: acts must cover 1..{total_chapters} contiguously without gaps/overlaps; "
                f"act '{a.name}' starts at ch{a.range[0]} but expected ch{expected_start}"
            )
        expected_start = a.range[1] + 1
    if expected_start - 1 != total_chapters:
        raise ValueError(
            f"plot_arc.yaml: last act ends at ch{expected_start - 1} but total_chapters={total_chapters}"
        )

    return PlotArc(
        schema_version=schema_version,
        total_chapters=total_chapters,
        ultimate_goal=ultimate_goal.strip(),
        acts=acts,
    )


def derive_planner_context(arc: PlotArc, current_chapter: int) -> dict:
    """派生 Planner 用的全书坐标系字段。

    返回 dict 结构：
      - current_act:               当前章所在的 PlotAct
      - current_act_index:         0-based act index
      - current_act_progress:      "ch{N}/{act_total}" within act
      - next_act:                  下一 PlotAct 或 None
      - chapters_left_in_act:      含当前章在内还剩几章到 act 末尾
      - total_progress_pct:        0-100 整数
      - chapters_left_total:       含当前章在内还剩几章到全书末尾
      - must_close_in_current_act: list[str]
      - is_act_finale:             current_chapter == current_act.range[1]
      - current_milestone:         当前章命中的 PlotMilestone 或 None
      - next_milestone:            **整本书**下一个 milestone（不限于本 act）
                                   或 None
      - chapters_until_next_milestone: 距 next_milestone 还几章（含两端）
                                       即 next_milestone.chapter - current_chapter；
                                       None 当无下一 milestone
    """
    if current_chapter < 1 or current_chapter > arc.total_chapters:
        raise ValueError(
            f"current_chapter {current_chapter} out of range 1..{arc.total_chapters}"
        )

    sorted_acts = sorted(arc.acts, key=lambda a: a.range[0])
    current_act: Optional[PlotAct] = None
    current_idx = -1
    for i, a in enumerate(sorted_acts):
        if a.range[0] <= current_chapter <= a.range[1]:
            current_act = a
            current_idx = i
            break
    if current_act is None:
        # Should not happen post-validation, but guard.
        raise ValueError(f"no act covers chapter {current_chapter}")

    act_start, act_end = current_act.range
    act_total = act_end - act_start + 1
    pos_in_act = current_chapter - act_start + 1  # 1-based position within act

    next_act = sorted_acts[current_idx + 1] if current_idx + 1 < len(sorted_acts) else None
    chapters_left_in_act = act_end - current_chapter + 1  # incl. current
    chapters_left_total = arc.total_chapters - current_chapter + 1
    total_progress_pct = int(round(current_chapter * 100 / arc.total_chapters))
    is_act_finale = current_chapter == act_end

    # P0 续：milestone 派生
    # current_milestone: 任一 act 中 milestone.chapter == current_chapter（应只在 current_act 出现）
    current_milestone: Optional[PlotMilestone] = None
    for ms in current_act.milestones:
        if ms.chapter == current_chapter:
            current_milestone = ms
            break

    # next_milestone: 整本书所有 milestones 排序后第一个 chapter > current_chapter 的
    all_milestones: list[PlotMilestone] = []
    for a in sorted_acts:
        all_milestones.extend(a.milestones)
    all_milestones.sort(key=lambda m: m.chapter)
    next_milestone: Optional[PlotMilestone] = None
    for ms in all_milestones:
        if ms.chapter > current_chapter:
            next_milestone = ms
            break
    chapters_until_next_milestone = (
        next_milestone.chapter - current_chapter if next_milestone is not None else None
    )

    return {
        "current_act": current_act,
        "current_act_index": current_idx,
        "current_act_progress": f"ch{pos_in_act}/{act_total}",
        "next_act": next_act,
        "chapters_left_in_act": chapters_left_in_act,
        "total_progress_pct": total_progress_pct,
        "chapters_left_total": chapters_left_total,
        "must_close_in_current_act": list(current_act.must_close_by_end),
        "is_act_finale": is_act_finale,
        "current_milestone": current_milestone,
        "next_milestone": next_milestone,
        "chapters_until_next_milestone": chapters_until_next_milestone,
    }
