"""Tests for `python -m src.genre_extractor.miners.novel_dna --backfill-structured`.

Why: ora-1 environment-1 fix. preset/2 (and any future Web-generated preset
prior to the from-novel-Stage-2.5 fix) is missing dna_structured.yaml. The
backfill command reads the already-archived dna_cards/*.md + era.md and
runs Stage 2.5 in isolation — no re-mining of windows, no re-synthesis.

Tests:
 1. Backfill --use-mock writes a schema-compliant dna_structured.yaml
    without invoking the LLM.
 2. Backfill fails fast when the preset / dna_cards/ directory is missing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


def test_backfill_use_mock_writes_schema_compliant_yaml(tmp_path, monkeypatch, capsys):
    """Set up a preset with dna_cards/ + era.md, run --backfill-structured
    --use-mock, assert dna_structured.yaml is written + contains all 4
    chapter_type buckets."""
    # Redirect PRESETS_DIR to tmp
    monkeypatch.setattr("src.config.PRESETS_DIR", tmp_path)

    preset_dir = tmp_path / "test-preset-bf"
    preset_dir.mkdir()
    cards_dir = preset_dir / "dna_cards"
    cards_dir.mkdir()
    (cards_dir / "alpha.md").write_text("# alpha\n\nDNA content alpha\n", encoding="utf-8")
    (cards_dir / "beta.md").write_text("# beta\n\nDNA content beta\n", encoding="utf-8")
    (preset_dir / "era.md").write_text("# era\n\n世界设定\n", encoding="utf-8")

    from src.genre_extractor.miners.novel_dna import main
    rc = main(["--backfill-structured", "test-preset-bf", "--use-mock"])
    assert rc == 0, "backfill --use-mock should exit 0 on happy path"

    out = preset_dir / "dna_structured.yaml"
    assert out.exists(), f"dna_structured.yaml not written to {out}"

    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    # 4 chapter_type buckets
    assert set(data["tips_by_chapter_type"].keys()) == {"战斗", "布局", "过渡", "回收"}
    # 3 scene_purpose buckets
    assert set(data["tips_by_scene_purpose"].keys()) == {"推进主线", "塑造人物", "埋伏笔"}
    # 4 payoff_recipes anchors
    assert set(data["payoff_recipes"].keys()) == {"爽感", "掌控感", "黑色幽默", "生存智慧"}
    # _backfill_mock marker so users / future debuggers can tell this came
    # from --use-mock and isn't a real LLM-grounded structured tip set
    assert data.get("_backfill_mock") is True


def test_backfill_fails_when_preset_missing(tmp_path, monkeypatch):
    """Backfilling a non-existent preset must exit nonzero (not crash silently)."""
    monkeypatch.setattr("src.config.PRESETS_DIR", tmp_path)

    from src.genre_extractor.miners.novel_dna import main
    rc = main(["--backfill-structured", "does-not-exist", "--use-mock"])
    assert rc == 1, "backfill on missing preset must return exit code 1"


def test_backfill_fails_when_dna_cards_missing(tmp_path, monkeypatch):
    """Preset exists but dna_cards/ is missing → fail fast."""
    monkeypatch.setattr("src.config.PRESETS_DIR", tmp_path)
    preset_dir = tmp_path / "no-cards-preset"
    preset_dir.mkdir()
    (preset_dir / "era.md").write_text("# era\n", encoding="utf-8")

    from src.genre_extractor.miners.novel_dna import main
    rc = main(["--backfill-structured", "no-cards-preset", "--use-mock"])
    assert rc == 1
