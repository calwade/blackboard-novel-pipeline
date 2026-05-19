"""Tests for from-novel job's full-pipeline contract.

Why: ora-1 environment-1 fix. The Web from-novel job worker (web/routes/jobs.py
~498-513) historically called _write_preset(...) without structured_tips,
silently skipping Stage 2.5 (`_structure_dna_tips`). The CLI entry point
(`python -m src.genre_extractor.miners.novel_dna ...`) always called Stage
2.5. The two entry points drifted and preset/2 ended up missing
dna_structured.yaml. These tests lock in:

 1. From-novel worker calls _structure_dna_tips between Stage 2 and write,
    producing presets/<id>/dna_structured.yaml.
 2. _write_preset raises ValueError when structured_tips is None (catches
    future regressions where a caller forgets Stage 2.5).
 3. _write_preset accepts allow_missing_structure=True for legitimate
    fixture / test contexts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.genre_extractor.miners.novel_dna import (
    BookDNA,
    _write_preset,
)


# ---------- 1. _write_preset guard contract ----------


def _make_dna_card(name: str = "mock") -> BookDNA:
    """Minimal BookDNA fixture (the field set _write_preset actually consumes:
    .title, .digest_markdown, .source_path)."""
    return BookDNA(
        source_path=Path(f"/tmp/{name}.txt"),
        title=name,
        total_chapters=42,
        digest_markdown=f"# DNA card for {name}\n\n(content)",
    )


def _minimal_synth() -> dict:
    """Mirror what _synthesize_preset returns (the keys _write_preset reads)."""
    return {
        "genre_yaml": {
            "id": "test-preset",
            "display_name": "测试 preset",
        },
        "era_md": "# era\n\n世界设定。\n",
        "writing_style_extra_md": "# 风格\n\n规范。\n",
        "iron_laws_extra_md": "# 题材铁律\n\n第 1 条 …\n",
    }


def test_write_preset_raises_when_structured_missing(tmp_path, monkeypatch):
    """Calling _write_preset without structured_tips must raise ValueError
    explaining the missing Stage 2.5. Defense against silent regressions."""
    # Redirect PRESETS_DIR to tmp so we don't touch the real presets/ tree
    monkeypatch.setattr("src.config.PRESETS_DIR", tmp_path)

    synth = _minimal_synth()
    cards = [_make_dna_card("alpha")]

    with pytest.raises(ValueError) as excinfo:
        _write_preset("test-preset-xyz", synth, [Path("/tmp/alpha.txt")], cards)

    msg = str(excinfo.value)
    assert "structured_tips" in msg or "dna_structured" in msg, (
        f"Error message must mention structured_tips / dna_structured.yaml, "
        f"got: {msg}"
    )


def test_write_preset_allows_missing_structure_when_explicit(tmp_path, monkeypatch):
    """Tests / fixtures legitimately need to write a preset without Stage
    2.5 (e.g. setup for a downstream test). The escape hatch must work."""
    monkeypatch.setattr("src.config.PRESETS_DIR", tmp_path)

    synth = _minimal_synth()
    cards = [_make_dna_card("alpha")]
    out_dir = _write_preset(
        "test-preset-allow", synth, [Path("/tmp/alpha.txt")], cards,
        structured_tips=None, allow_missing_structure=True,
    )
    # No dna_structured.yaml because we explicitly opted out
    assert not (out_dir / "dna_structured.yaml").exists()
    # But the rest of the preset is still there
    assert (out_dir / "era.md").exists()
    assert (out_dir / "genre.yaml").exists()


def test_write_preset_writes_dna_structured_when_provided(tmp_path, monkeypatch):
    """Happy path: structured_tips passed → dna_structured.yaml written."""
    monkeypatch.setattr("src.config.PRESETS_DIR", tmp_path)

    synth = _minimal_synth()
    cards = [_make_dna_card("alpha")]
    structured = {
        "schema_version": 1,
        "tips_by_chapter_type": {"战斗": ["手法 1"]},
    }
    out_dir = _write_preset(
        "test-preset-happy", synth, [Path("/tmp/alpha.txt")], cards,
        structured_tips=structured,
    )
    p = out_dir / "dna_structured.yaml"
    assert p.exists(), f"dna_structured.yaml not written to {p}"
    content = p.read_text(encoding="utf-8")
    assert "schema_version" in content
    assert "战斗" in content


# ---------- 2. from-novel worker integration ----------


def test_from_novel_worker_calls_stage_2_5(tmp_path, monkeypatch):
    """Drive the from-novel worker end-to-end with all 3 LLM-bound steps
    (mine_book_dna / _synthesize_preset / _structure_dna_tips) mocked.
    Assert dna_structured.yaml lands in presets/<id>/.

    This is a regression test for the bug where web/routes/jobs.py forgot
    to call _structure_dna_tips between Stage 2 and _write_preset.
    """
    # Redirect the presets dir
    monkeypatch.setattr("src.config.PRESETS_DIR", tmp_path)

    # Build a fake source novel file (mine_book_dna is mocked so content
    # doesn't matter, but the path must exist for the .exists() check in
    # _resolve_novel_path → list comprehension).
    novels_dir = tmp_path / "_novels"
    novels_dir.mkdir()
    fake_novel = novels_dir / "mock-source.txt"
    fake_novel.write_text("章 1\n…\n", encoding="utf-8")

    # Mock all 3 LLM-bound functions inside the novel_dna module so the
    # web job worker uses the mocks (it imports them at call time).
    fake_card = _make_dna_card("mock-source")
    fake_synth = _minimal_synth()
    structure_calls: list[tuple] = []

    def fake_mine(p, **_kw):
        return fake_card

    def fake_synthesize(_pid, _cards, hint=""):
        return fake_synth

    def fake_structure(cards, era_md):
        structure_calls.append((cards, era_md))
        return {
            "schema_version": 1,
            "tips_by_chapter_type": {"战斗": ["mock tip"]},
            "tips_by_scene_purpose": {},
            "hook_recipes": {"opening_hooks": [], "closing_hooks": []},
            "universal": {},
        }

    monkeypatch.setattr(
        "src.genre_extractor.miners.novel_dna.mine_book_dna", fake_mine
    )
    monkeypatch.setattr(
        "src.genre_extractor.miners.novel_dna._synthesize_preset", fake_synthesize
    )
    monkeypatch.setattr(
        "src.genre_extractor.miners.novel_dna._structure_dna_tips", fake_structure
    )

    # Now drive the worker. We can't easily stand up the full Flask app,
    # so we replicate the from-novel branch's *core sequence* (the 3-call
    # pipeline) here and assert behavior. If the production code drifts
    # away from this sequence, the read-string test below will catch it.
    from src.genre_extractor.miners.novel_dna import (
        mine_book_dna, _synthesize_preset, _structure_dna_tips, _write_preset,
    )
    dna_cards = [mine_book_dna(fake_novel)]
    synth = _synthesize_preset("test-from-novel", dna_cards, hint="")
    structured = _structure_dna_tips(dna_cards, synth.get("era_md", ""))
    out_dir = _write_preset(
        "test-from-novel", synth, [fake_novel], dna_cards,
        structured_tips=structured,
    )

    # Assertions
    assert len(structure_calls) == 1, (
        "Stage 2.5 (_structure_dna_tips) must be called exactly once between "
        "Stage 2 (_synthesize_preset) and _write_preset"
    )
    p = out_dir / "dna_structured.yaml"
    assert p.exists(), (
        f"dna_structured.yaml not written — Stage 2.5 output was lost. "
        f"Expected at {p}, found contents: {sorted(out_dir.iterdir())}"
    )


def test_jobs_py_invokes_structure_dna_tips_in_from_novel():
    """Anchor: web/routes/jobs.py from-novel branch must call
    _structure_dna_tips. If a future refactor drops that call, this test
    catches the regression even without spinning up the full Flask app
    (the integration test above relies on a hand-rolled simulation;
    this anchor guards the production source itself).
    """
    repo = Path(__file__).resolve().parent.parent
    src = (repo / "web" / "routes" / "jobs.py").read_text(encoding="utf-8")
    # The import must mention _structure_dna_tips
    assert "_structure_dna_tips" in src, (
        "web/routes/jobs.py must import + call _structure_dna_tips "
        "(Stage 2.5) for the from-novel job to produce a complete preset"
    )
    # And _write_preset must be called with structured_tips=
    assert "structured_tips=structured_tips" in src, (
        "web/routes/jobs.py must pass structured_tips=… to _write_preset "
        "in the from-novel branch"
    )
