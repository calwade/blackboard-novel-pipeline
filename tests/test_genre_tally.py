"""Tests for src.genre_extractor.tally — extraction_tally.md generation.

The tally is a human-readable "health dashboard" produced at the end of
the merge phase. It's pure data aggregation (no LLM) from:
- build_status.yaml  -> coverage / batch count / progress
- extraction_notes/batch-*.yaml -> per-batch rollups + Top-N aggregations
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _make_bb(tmp_path: Path):
    from src.core.blackboard import Blackboard
    return Blackboard(root=tmp_path)


def _write_initial_status(bb, *, genre_id="demo", sources=None):
    from src.genre_extractor.schemas import make_initial_build_status
    bb.write_yaml(
        "build_status.yaml",
        make_initial_build_status(
            genre_id=genre_id,
            entry="extract-from-novel",
            novel_sources=sources or [],
        ),
    )


def _sample_batch(
    *,
    batch_id: int,
    chapters: tuple[int, int],
    source: str = "novel-a.txt",
    iron_laws: list[dict] | None = None,
    eras: list[dict] | None = None,
    styles: list[dict] | None = None,
    resources: list[dict] | None = None,
    questions: list[str] | None = None,
) -> dict:
    return {
        "batch_id": batch_id,
        "chapters_covered": list(chapters),
        "novel_source": source,
        "extracted_at": "2026-05-12T10:00:00",
        "era_observations": eras or [],
        "iron_law_candidates": iron_laws or [],
        "style_markers": styles or [],
        "resource_candidates": resources or [],
        "open_questions": questions or [],
    }


# ----------------------------------------------------------------------
# Task C tests
# ----------------------------------------------------------------------

def test_tally_on_empty_build(tmp_path: Path):
    """build_status exists but 0 batches -> Markdown still valid."""
    from src.genre_extractor.tally import generate_extraction_tally

    bb = _make_bb(tmp_path)
    _write_initial_status(bb, genre_id="empty-demo", sources=[])

    md = generate_extraction_tally(bb, "empty-demo")

    assert isinstance(md, str)
    assert md.startswith("# Extraction Tally")
    assert "empty-demo" in md
    # 0 batches readout
    assert "0" in md
    # The big sections should still be emitted (header-only is fine)
    assert "覆盖范围" in md


def test_tally_with_3_batches(tmp_path: Path):
    """3 hand-rolled batches -> coverage, Top-N, confidence buckets."""
    from src.genre_extractor.tally import generate_extraction_tally

    bb = _make_bb(tmp_path)
    _write_initial_status(
        bb,
        genre_id="threebatch",
        sources=[{"path": "novel-a.txt", "total_chapters": 75, "batch_size": 25}],
    )

    # Batch 1: three iron laws, some era (high/medium/low), two style markers
    bb.write_yaml(
        "extraction_notes/batch-001.yaml",
        _sample_batch(
            batch_id=1,
            chapters=(1, 25),
            iron_laws=[
                {"summary": "主角必须向上级汇报",
                 "evidence_chapters": [1, 5], "evidence_quotes": ["q"],
                 "confidence": "high", "recurrence_count": 4,
                 "cand_id": "cand_01"},
                {"summary": "帮派辈分不能越级",
                 "evidence_chapters": [3], "evidence_quotes": ["q"],
                 "confidence": "medium", "recurrence_count": 2,
                 "cand_id": "cand_02"},
            ],
            eras=[
                {"summary": "1983 香港", "confidence": "high",
                 "evidence_chapters": [1]},
                {"summary": "廉政公署成立", "confidence": "medium",
                 "evidence_chapters": [2]},
                {"summary": "主权谈判", "confidence": "low",
                 "evidence_chapters": [4]},
            ],
            styles=[
                {"marker": "粤语词融入", "measurement": "每千字 3-5 个",
                 "evidence_chapters": [1]},
                {"marker": "短句节奏", "measurement": "每段 2-3 句",
                 "evidence_chapters": [2]},
            ],
        ),
    )

    # Batch 2: reinforces cand_01; adds a new iron law; more eras
    bb.write_yaml(
        "extraction_notes/batch-002.yaml",
        _sample_batch(
            batch_id=2,
            chapters=(26, 50),
            iron_laws=[
                {"summary": "主角必须向上级汇报",
                 "evidence_chapters": [26], "evidence_quotes": ["q"],
                 "confidence": "high", "recurrence_count": 6,
                 "cand_id": "cand_01"},
                {"summary": "敌对势力必遭报应",
                 "evidence_chapters": [30], "evidence_quotes": ["q"],
                 "confidence": "medium", "recurrence_count": 3,
                 "cand_id": "cand_03"},
            ],
            eras=[
                {"summary": "英资银行主导", "confidence": "high",
                 "evidence_chapters": [26]},
                {"summary": "黑帮转型", "confidence": "low",
                 "evidence_chapters": [28]},
            ],
            styles=[
                {"marker": "粤语词融入", "measurement": "每千字 3-5 个",
                 "evidence_chapters": [26]},
            ],
        ),
    )

    # Batch 3: nothing new iron-law-wise, adds one style marker
    bb.write_yaml(
        "extraction_notes/batch-003.yaml",
        _sample_batch(
            batch_id=3,
            chapters=(51, 75),
            iron_laws=[],
            eras=[
                {"summary": "廉政公署成立", "confidence": "high",
                 "evidence_chapters": [55]},
            ],
            styles=[
                {"marker": "短句节奏", "measurement": "每段 2-3 句",
                 "evidence_chapters": [55]},
            ],
            questions=["主角对内地人的态度是演进还是题材规律？"],
        ),
    )

    md = generate_extraction_tally(bb, "threebatch")

    # Coverage
    assert "threebatch" in md
    assert "覆盖范围" in md
    # 3 batches
    assert "**3" in md or "3 批" in md
    # Batch table
    assert "batch-001" in md.replace(" ", "") or "001" in md
    # Top iron-law
    assert "主角必须向上级汇报" in md
    # Confidence distribution present
    assert "high" in md
    assert "medium" in md
    assert "low" in md
    # Style marker aggregate
    assert "粤语词融入" in md
    # Open question bubbled up
    assert "主角对内地人" in md


def test_tally_flags_fuzzy_terms(tmp_path: Path):
    """A forbidden fuzzy word in a batch -> tally warning indicator."""
    from src.genre_extractor.tally import generate_extraction_tally

    bb = _make_bb(tmp_path)
    _write_initial_status(
        bb,
        genre_id="fuzzy",
        sources=[{"path": "novel.txt", "total_chapters": 25, "batch_size": 25}],
    )
    bb.write_yaml(
        "extraction_notes/batch-001.yaml",
        _sample_batch(
            batch_id=1,
            chapters=(1, 25),
            eras=[
                # "暴涨" is in _FUZZY_TERMS
                {"summary": "房价暴涨的年代", "confidence": "medium",
                 "evidence_chapters": [1]},
            ],
        ),
    )

    md = generate_extraction_tally(bb, "fuzzy")

    assert "禁用模糊词" in md
    # Should flag failure — we accept any of ❌ / 失败 / 命中 >0 as the alarm
    assert ("❌" in md) or ("命中" in md and "0" not in md.split("禁用模糊词")[1].split("\n")[1:3][0])
    # The hit count must not be 0 here
    assert "0 次" not in md
    # The offending term should be surfaced (it's in _FUZZY_TERMS)
    assert "暴涨" in md


def test_tally_omits_empty_resource_section(tmp_path: Path):
    """If all resource_candidates empty, skip the whole section."""
    from src.genre_extractor.tally import generate_extraction_tally

    bb = _make_bb(tmp_path)
    _write_initial_status(
        bb,
        genre_id="noresource",
        sources=[{"path": "novel.txt", "total_chapters": 25, "batch_size": 25}],
    )
    bb.write_yaml(
        "extraction_notes/batch-001.yaml",
        _sample_batch(
            batch_id=1,
            chapters=(1, 25),
            iron_laws=[
                {"summary": "基本规律",
                 "evidence_chapters": [1], "evidence_quotes": ["q"],
                 "confidence": "high", "recurrence_count": 1,
                 "cand_id": "cand_01"},
            ],
            resources=[],
        ),
    )

    md = generate_extraction_tally(bb, "noresource")

    assert "Resource schema 候选" not in md


def test_run_merge_generates_tally(tmp_path: Path, monkeypatch):
    """End-to-end: _run_merge writes extraction_tally.md via the tally hook."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    from src.core.blackboard import Blackboard
    from src.genre_extractor import pipeline, schemas

    bb = Blackboard(root=tmp_path / "e2e-tally" / ".build")
    bb.write_yaml(
        "build_status.yaml",
        schemas.make_initial_build_status(
            genre_id="e2e-tally",
            entry="extract-from-novel",
            novel_sources=[{"path": "x.txt", "total_chapters": 25, "batch_size": 25}],
        ),
    )
    # Seed a single batch note so merge has something to work with
    bb.write_yaml(
        "extraction_notes/batch-001.yaml",
        _sample_batch(batch_id=1, chapters=(1, 25)),
    )

    pipeline._run_merge(bb)

    assert bb.exists("extraction_tally.md"), \
        "extraction_tally.md must be written by _run_merge"
    md = bb.read_text("extraction_tally.md")
    assert "e2e-tally" in md
    assert "覆盖范围" in md
