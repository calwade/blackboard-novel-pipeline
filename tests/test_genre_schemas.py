"""schemas.py 测试：校验 Extractor 笔记、build_status、blueprint 的结构严格性。"""
from __future__ import annotations

import pytest


def test_extraction_note_minimal_valid():
    from src.genre_extractor.schemas import validate_extraction_note
    obj = {
        "batch_id": 1,
        "chapters_covered": [1, 25],
        "novel_source": "novels/a.txt",
        "extracted_at": "2026-05-11T14:30:00",
        "era_observations": [],
        "iron_law_candidates": [],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    }
    clean, warnings = validate_extraction_note(obj)
    assert clean["batch_id"] == 1
    assert warnings == []


def test_extraction_note_missing_required_key_raises():
    from src.genre_extractor.schemas import validate_extraction_note
    obj = {"batch_id": 1}  # missing almost everything
    with pytest.raises(ValueError, match="chapters_covered"):
        validate_extraction_note(obj)


def test_extraction_note_confidence_enum():
    from src.genre_extractor.schemas import validate_extraction_note
    obj = {
        "batch_id": 1,
        "chapters_covered": [1, 25],
        "novel_source": "x",
        "extracted_at": "2026-05-11T14:30:00",
        "era_observations": [
            {"fact": "f1", "evidence_chapters": [3], "confidence": "very-high", "cites_reality": True}
        ],
        "iron_law_candidates": [],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    }
    with pytest.raises(ValueError, match="confidence"):
        validate_extraction_note(obj)


def test_extraction_note_fuzzy_term_warning():
    """笔记里出现'暴涨/海量/大致/似乎'等禁词要 warn。"""
    from src.genre_extractor.schemas import validate_extraction_note
    obj = {
        "batch_id": 1,
        "chapters_covered": [1, 25],
        "novel_source": "x",
        "extracted_at": "2026-05-11T14:30:00",
        "era_observations": [
            {"fact": "主角实力大致暴涨", "evidence_chapters": [3], "confidence": "high", "cites_reality": False}
        ],
        "iron_law_candidates": [],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    }
    clean, warnings = validate_extraction_note(obj)
    assert any("模糊词" in w for w in warnings)


def test_build_status_initial():
    from src.genre_extractor.schemas import make_initial_build_status
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 300, "batch_size": 25}],
    )
    assert status["genre_id"] == "demo"
    assert status["phases"]["extract"]["status"] == "pending"
    assert status["phases"]["extract"]["batches_total"] == 12  # ceil(300/25)
    assert status["phases"]["merge"]["status"] == "pending"


def test_build_status_multiple_novels():
    from src.genre_extractor.schemas import make_initial_build_status
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[
            {"path": "a.txt", "total_chapters": 400, "batch_size": 25},
            {"path": "b.txt", "total_chapters": 180, "batch_size": 25},
        ],
    )
    # 400/25 = 16, 180/25 = 8 → total 24
    assert status["phases"]["extract"]["batches_total"] == 24


def test_blueprint_skeleton():
    from src.genre_extractor.schemas import make_empty_blueprint
    bp = make_empty_blueprint(genre_id="demo")
    assert bp["genre_id"] == "demo"
    assert "era_observations" in bp
    assert "iron_law_candidates" in bp
    assert "style_markers" in bp
    assert "resource_candidates" in bp
