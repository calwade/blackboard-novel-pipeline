"""GenreArcMerger —— 把 N 个 batch-NNN.yaml 合并为一个 arc-NN.yaml。

属于题材 Pipeline 的第二级合并（batch → arc）。

验证要点：
1. Agent 可实例化，name/response_format 正确
2. _build_prompts 读取若干 batch YAML，引用 inputs_read
3. _handle_output 写到 extraction_notes/arcs/arc-NN.yaml
4. 输出保留 arc_id + covered_batches 字段
5. LLM 被 stub 时，整条 run 跑通
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.blackboard import Blackboard


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    return Blackboard(root=tmp_path)


def _write_stub_batch(bb: Blackboard, batch_id: int, iron_law_summary: str = "demo rule") -> None:
    bb.write_yaml(f"extraction_notes/batch-{batch_id:03d}.yaml", {
        "batch_id": batch_id,
        "chapters_covered": [batch_id * 10 - 9, batch_id * 10],
        "novel_source": "stub",
        "extracted_at": "2026-05-12",
        "era_observations": [
            {"summary": f"era-obs-{batch_id}", "evidence_chapters": [batch_id * 10],
             "evidence_quotes": ["q"], "confidence": "high", "recurrence_count": 1},
        ],
        "iron_law_candidates": [
            {"summary": iron_law_summary, "evidence_chapters": [batch_id * 10],
             "evidence_quotes": ["q"], "confidence": "high", "recurrence_count": 1},
        ],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    })


def test_arc_merger_instantiates():
    from src.genre_extractor.agents.arc_merger import GenreArcMerger
    a = GenreArcMerger()
    assert a.name == "genre_arc_merger"
    assert a.response_format == "json"
    assert a.temperature == 0.2


def test_arc_merger_build_prompts_reads_batches(bb):
    from src.genre_extractor.agents.arc_merger import GenreArcMerger

    _write_stub_batch(bb, 1)
    _write_stub_batch(bb, 2)
    _write_stub_batch(bb, 3)
    _write_stub_batch(bb, 4)

    a = GenreArcMerger()
    system, user, inputs_read = a._build_prompts(
        bb, arc_id=1, batch_ids=[1, 2, 3, 4]
    )

    assert isinstance(system, str) and len(system) > 50
    # User prompt should contain content from the batches
    assert "batch-001.yaml" in user or "batch_id" in user
    # inputs_read should list all 4 batch paths
    assert any("batch-001.yaml" in p for p in inputs_read)
    assert any("batch-004.yaml" in p for p in inputs_read)


def test_arc_merger_handle_output_writes_arc_yaml(bb):
    from src.genre_extractor.agents.arc_merger import GenreArcMerger

    a = GenreArcMerger()
    stub_json = (
        '{"arc_id": 3, "covered_batches": [9, 10, 11, 12], '
        '"batch_id": "arc-003", "chapters_covered": [81, 120], '
        '"novel_source": "merged", "extracted_at": "2026-05-12", '
        '"era_observations": [], "iron_law_candidates": [], '
        '"style_markers": [], "resource_candidates": [], '
        '"open_questions": []}'
    )
    a._handle_output(bb, stub_json, arc_id=3, batch_ids=[9, 10, 11, 12])

    assert bb.exists("extraction_notes/arcs/arc-003.yaml")
    data = bb.read_yaml("extraction_notes/arcs/arc-003.yaml")
    assert data["arc_id"] == 3
    assert data["covered_batches"] == [9, 10, 11, 12]


def test_arc_merger_full_run_with_stub_llm(bb, monkeypatch):
    from src.genre_extractor.agents.arc_merger import GenreArcMerger

    _write_stub_batch(bb, 1)
    _write_stub_batch(bb, 2)
    _write_stub_batch(bb, 3)
    _write_stub_batch(bb, 4)

    calls: list[dict] = []

    def fake_chat(*, system, user, agent_name, temperature, response_format, **_):
        calls.append({
            "agent_name": agent_name,
            "temperature": temperature,
            "response_format": response_format,
        })
        return (
            '{"arc_id": 1, "covered_batches": [1,2,3,4], '
            '"batch_id": "arc-001", "chapters_covered": [1, 40], '
            '"novel_source": "merged", "extracted_at": "2026-05-12", '
            '"era_observations": [{"summary": "merged era", "evidence_chapters": [1], '
            '"evidence_quotes": [], "confidence": "high", "recurrence_count": 4}], '
            '"iron_law_candidates": [{"summary": "merged rule", "evidence_chapters": [1], '
            '"evidence_quotes": [], "confidence": "high", "recurrence_count": 4}], '
            '"style_markers": [], "resource_candidates": [], '
            '"open_questions": []}'
        )

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    GenreArcMerger().run(bb, arc_id=1, batch_ids=[1, 2, 3, 4])

    assert len(calls) == 1
    assert calls[0]["agent_name"] == "genre_arc_merger"
    assert calls[0]["temperature"] == 0.2
    assert calls[0]["response_format"] == "json"
    assert bb.exists("extraction_notes/arcs/arc-001.yaml")
    data = bb.read_yaml("extraction_notes/arcs/arc-001.yaml")
    assert data["arc_id"] == 1
    assert data["covered_batches"] == [1, 2, 3, 4]


def test_arc_merger_includes_previous_arc_if_exists(bb, monkeypatch):
    """When running a later arc, if earlier arc file exists, should be available as reference."""
    from src.genre_extractor.agents.arc_merger import GenreArcMerger

    # Earlier arc already produced
    bb.write_yaml("extraction_notes/arcs/arc-001.yaml", {
        "arc_id": 1, "covered_batches": [1, 2, 3, 4],
        "batch_id": "arc-001", "chapters_covered": [1, 40],
        "novel_source": "merged", "extracted_at": "t",
        "era_observations": [], "iron_law_candidates": [
            {"summary": "existing-rule", "evidence_chapters": [1],
             "evidence_quotes": [], "confidence": "high", "recurrence_count": 4},
        ],
        "style_markers": [], "resource_candidates": [], "open_questions": [],
    })
    # New batches being merged
    _write_stub_batch(bb, 5)
    _write_stub_batch(bb, 6)
    _write_stub_batch(bb, 7)
    _write_stub_batch(bb, 8)

    a = GenreArcMerger()
    system, user, inputs_read = a._build_prompts(
        bb, arc_id=2, batch_ids=[5, 6, 7, 8]
    )
    # Previous arc should appear in user prompt or be referenced
    assert "existing-rule" in user or "arc-001" in user or "previous" in user.lower()
