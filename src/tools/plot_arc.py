"""Plot Arc — 全书坐标系（P0+P1 Oracle 诊断的核心修复）.

Oracle 诊断 Planner 剧情停滞根因：架构缺"全书坐标系"模块——Planner 只看局部
上下文（最近 2 章 + 最新 arc + 状态卡），不知道自己在写 ch30/50（60% 进度），
不知道全书目标和阶段任务，所以退化为"局部贪心"——每章原地循环。

本模块提供：
  - PlotAct / PlotArc dataclass（schema_version=1）
  - read_plot_arc(project_dir): 读 yaml + 校验
  - derive_planner_context(arc, current_chapter): 派生 Planner 用的字段

文件位置约定：
  - 作品源：projects/<id>/plot_arc.yaml
  - bootstrap 拷到：projects/<id>/state/plot_arc.yaml
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


SCHEMA_VERSION = 1


@dataclass
class PlotAct:
    name: str
    range: tuple[int, int]            # 章号区间（含两端）
    goal: str = ""
    must_open_by_ch: list[int] = field(default_factory=list)
    must_close_by_end: list[str] = field(default_factory=list)


@dataclass
class PlotArc:
    schema_version: int
    total_chapters: int
    ultimate_goal: str
    acts: list[PlotAct]


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
        acts.append(
            PlotAct(
                name=name,
                range=(rng[0], rng[1]),
                goal=goal,
                must_open_by_ch=[int(x) for x in must_open],
                must_close_by_end=[str(x) for x in must_close],
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
      - chapters_left_in_act:      含当前章在内还剩几章到 act 末尾（=0 表示当前是 finale 后一章不可能；=1 表示当前是最后一章）
      - total_progress_pct:        0-100 整数
      - chapters_left_total:       含当前章在内还剩几章到全书末尾
      - must_close_in_current_act: list[str]
      - is_act_finale:             current_chapter == current_act.range[1]
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
    }
