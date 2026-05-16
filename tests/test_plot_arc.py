"""Tests for src/tools/plot_arc.py — 全书坐标系 (Oracle P0+P1 修复).

Pure-functional tests, no LLM calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.tools.plot_arc import (
    PlotAct,
    PlotArc,
    derive_planner_context,
    read_plot_arc,
)


# ---------------- 1. real example file is schema-valid ----------------

def test_plot_arc_schema_valid():
    """The committed example file projects/book-e3f4fc9b/plot_arc.yaml
    must round-trip through read_plot_arc successfully."""
    project_dir = Path(__file__).resolve().parent.parent / "projects" / "book-e3f4fc9b"
    if not (project_dir / "plot_arc.yaml").exists():
        pytest.skip("example plot_arc.yaml not present")

    arc = read_plot_arc(project_dir)
    assert arc is not None
    assert arc.schema_version == 1
    assert arc.total_chapters >= 1
    assert arc.acts, "must have at least one act"

    # Validate coverage 1..total_chapters with no gaps/overlaps
    sorted_acts = sorted(arc.acts, key=lambda a: a.range[0])
    expected = 1
    for a in sorted_acts:
        assert a.range[0] == expected, f"gap before {a.name}"
        expected = a.range[1] + 1
    assert expected - 1 == arc.total_chapters


# ---------------- 2. derive_planner_context at act_finale ----------------

def _make_50ch_arc() -> PlotArc:
    return PlotArc(
        schema_version=1,
        total_chapters=50,
        ultimate_goal="终极目标",
        acts=[
            PlotAct("卷一", (1, 15), "act1 goal", [], ["a", "b"]),
            PlotAct("卷二", (16, 30), "act2 goal", [], ["c"]),
            PlotAct("卷三", (31, 45), "act3 goal", [], ["d"]),
            PlotAct("终卷", (46, 50), "终卷 goal", [], ["e"]),
        ],
    )


def test_derive_planner_context_at_act_finale():
    arc = _make_50ch_arc()
    ctx = derive_planner_context(arc, 15)
    assert ctx["is_act_finale"] is True
    assert ctx["current_act"].name == "卷一"
    assert ctx["next_act"] is not None
    assert ctx["next_act"].name == "卷二"
    assert ctx["chapters_left_in_act"] == 1


# ---------------- 3. mid-act ----------------

def test_derive_planner_context_mid_act():
    arc = _make_50ch_arc()
    ctx = derive_planner_context(arc, 8)
    assert ctx["is_act_finale"] is False
    assert ctx["current_act"].name == "卷一"
    assert ctx["chapters_left_in_act"] == 8  # ch15 - 8 + 1


# ---------------- 4. progress_pct ----------------

def test_total_progress_pct():
    arc = _make_50ch_arc()
    ctx = derive_planner_context(arc, 30)
    assert ctx["total_progress_pct"] == 60


# ---------------- 5. chapters_left_total ----------------

def test_chapters_left_total():
    arc = _make_50ch_arc()
    ctx = derive_planner_context(arc, 30)
    assert ctx["chapters_left_total"] == 21  # 50 - 30 + 1


# ---------------- 6. invalid overlap raises ----------------

def test_invalid_act_overlap_raises(tmp_path: Path):
    bad = {
        "schema_version": 1,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [
            {"name": "A", "range": [1, 6], "goal": "", "must_close_by_end": []},
            {"name": "B", "range": [5, 10], "goal": "", "must_close_by_end": []},
        ],
    }
    (tmp_path / "plot_arc.yaml").write_text(
        yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"contiguously"):
        read_plot_arc(tmp_path)


def test_invalid_act_gap_raises(tmp_path: Path):
    bad = {
        "schema_version": 1,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [
            {"name": "A", "range": [1, 4], "goal": "", "must_close_by_end": []},
            {"name": "B", "range": [6, 10], "goal": "", "must_close_by_end": []},
        ],
    }
    (tmp_path / "plot_arc.yaml").write_text(
        yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"contiguously"):
        read_plot_arc(tmp_path)


def test_missing_file_returns_none(tmp_path: Path):
    assert read_plot_arc(tmp_path) is None


def test_wrong_schema_version_raises(tmp_path: Path):
    bad = {
        "schema_version": 2,
        "total_chapters": 10,
        "ultimate_goal": "x",
        "acts": [{"name": "A", "range": [1, 10], "goal": "", "must_close_by_end": []}],
    }
    (tmp_path / "plot_arc.yaml").write_text(
        yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"schema_version"):
        read_plot_arc(tmp_path)


def test_chapter_out_of_range_raises():
    arc = _make_50ch_arc()
    with pytest.raises(ValueError):
        derive_planner_context(arc, 0)
    with pytest.raises(ValueError):
        derive_planner_context(arc, 51)
