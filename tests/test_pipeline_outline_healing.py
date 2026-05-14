"""Regression: `run_chapter` self-heals legacy outlines on entry.

Historical projects created before the blank-outline prefill fix
(commit a1c7034) have `state/outline.json == {"chapters": []}`. Planner has
an in-prompt fallback for missing entries, but the file itself never gets
patched — so every run quietly pays the cost and downstream agents never see
structural chapter placeholders.

`pipeline._heal_outline_if_needed(bb)` runs once at the top of every
`run_chapter` and fills any gap up to `setting.yaml::chapter_count_target`,
preserving any existing non-empty entries verbatim.

Two cases:
  1. Fully empty outline → filled with N shells.
  2. Sparse outline (ch1/ch2 populated, ch3..N missing) → existing entries
     are preserved, missing ones are added.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import pipeline
from src.blackboard import Blackboard


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _seed_bb(tmp_path: Path, *, outline: dict, chapter_count_target: int) -> Blackboard:
    """Create a minimal blackboard with the given outline + target."""
    b = Blackboard(root=tmp_path)
    b.write_yaml(
        "setting.yaml",
        {
            "genre": "g",
            "era": "e",
            "tone": "t",
            "prohibited_styles": [],
            "author_persona_hints": [],
            "chapter_count_target": chapter_count_target,
        },
    )
    b.write_yaml(
        "characters.yaml",
        {"protagonist": {"name": "主角"}, "supporting": []},
    )
    b.write_text("timeline.yaml", "2024: []\n")
    b.write_text("era.md", "era facts")
    b.write_text("writing-style-extra.md", "style extra")
    b.write_text("iron-laws-extra.md", "## iron_law_extra_1\nfoo\n")
    b.write_json("outline.json", outline)
    b.write_json("progress.json", {"current_chapter": 0, "completed_chapters": []})
    (tmp_path / "chapters").mkdir(exist_ok=True)
    (tmp_path / "summaries").mkdir(exist_ok=True)
    (tmp_path / "fixes").mkdir(exist_ok=True)
    return b


def _stub_llm():
    """Fake llm.chat that returns shape-appropriate stubs for every agent."""
    def _fake(*, system, user, agent_name, temperature, max_tokens,
              response_format, inputs_read):
        if agent_name == "planner":
            return json.dumps(
                {
                    "ch": 1,
                    "title": "t",
                    "chapter_type": "过渡",
                    "opening_hook": "o",
                    "scenes": [{"scene_id": 1, "cast": ["主角"], "advances": ["地位"]}],
                    "closing_hook": "c",
                    "landmines_to_avoid": [],
                    "writing_self_check": {},
                }
            )
        if agent_name == "evaluator":
            return '{"overall_pass": true, "landmines": {}, "top_3_fixes": []}'
        if response_format == "json":
            return '{"overall_pass": true, "landmines": {}, "top_3_fixes": []}'
        return "# t\n\n正文。"
    return _fake


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_chapter_heals_empty_outline(tmp_path, monkeypatch):
    """Legacy `chapters: []` outline must be back-filled by run_chapter."""
    bb = _seed_bb(
        tmp_path,
        outline={"title": "T", "chapters": []},
        chapter_count_target=5,
    )
    monkeypatch.setattr("src.agents._base.llm.chat", _stub_llm())

    status = pipeline.run_chapter(bb, chapter=1)
    assert status["evaluation"]["passed"] is True

    healed = bb.read_json("outline.json")
    assert len(healed["chapters"]) == 5, "empty outline should be filled to target"
    for i, ch in enumerate(healed["chapters"], start=1):
        assert ch["ch"] == i
        assert ch["title"] == f"第 {i} 章"
        assert ch["beats"] == []


def test_run_chapter_preserves_existing_outline_entries(tmp_path, monkeypatch):
    """Sparse outline: existing ch1/ch2 kept verbatim; ch3..ch5 added as shells."""
    existing_ch1 = {"ch": 1, "title": "开场", "beats": ["a", "b"]}
    existing_ch2 = {"ch": 2, "title": "发展", "beats": ["c"]}
    bb = _seed_bb(
        tmp_path,
        outline={"title": "T", "chapters": [existing_ch1, existing_ch2]},
        chapter_count_target=5,
    )
    monkeypatch.setattr("src.agents._base.llm.chat", _stub_llm())

    pipeline.run_chapter(bb, chapter=3)

    healed = bb.read_json("outline.json")
    assert len(healed["chapters"]) == 5
    # Existing entries preserved exactly
    assert healed["chapters"][0] == existing_ch1
    assert healed["chapters"][1] == existing_ch2
    # New entries are blank shells in ch3..ch5
    for i in (3, 4, 5):
        ch = healed["chapters"][i - 1]
        assert ch["ch"] == i
        assert ch["title"] == f"第 {i} 章"
        assert ch["beats"] == []
