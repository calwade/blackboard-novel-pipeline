"""GenreBookDistiller —— 把 N 个 arc-NN.yaml 蒸馏为 latest_merged.yaml。

属于题材 Pipeline 的第三级合并（arc → book）。

验证要点：
1. Agent 可实例化，name/response_format 正确
2. _build_prompts 读取所有 arcs/arc-*.yaml
3. _handle_output 写到 extraction_notes/latest_merged.yaml
4. 输出包含 distilled_from_arcs 字段（可选但推荐）
5. LLM 被 stub 时，整条 run 跑通
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.blackboard import Blackboard


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    return Blackboard(root=tmp_path)


def _write_stub_arc(bb: Blackboard, arc_id: int, covered_batches: list[int]) -> None:
    bb.write_yaml(f"extraction_notes/arcs/arc-{arc_id:03d}.yaml", {
        "arc_id": arc_id,
        "covered_batches": covered_batches,
        "batch_id": f"arc-{arc_id:03d}",
        "chapters_covered": [covered_batches[0] * 10 - 9, covered_batches[-1] * 10],
        "novel_source": "merged",
        "extracted_at": "2026-05-12",
        "era_observations": [
            {"summary": f"era-arc-{arc_id}", "evidence_chapters": [arc_id],
             "evidence_quotes": [], "confidence": "high", "recurrence_count": 4},
        ],
        "iron_law_candidates": [
            {"summary": f"rule-arc-{arc_id}", "evidence_chapters": [arc_id],
             "evidence_quotes": [], "confidence": "high", "recurrence_count": 4},
        ],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    })


def test_book_distiller_instantiates():
    from src.genre_extractor.agents.book_distiller import GenreBookDistiller
    a = GenreBookDistiller()
    assert a.name == "genre_book_distiller"
    assert a.response_format == "json"
    assert a.temperature == 0.2


def test_book_distiller_build_prompts_reads_all_arcs(bb):
    from src.genre_extractor.agents.book_distiller import GenreBookDistiller

    _write_stub_arc(bb, 1, [1, 2, 3, 4])
    _write_stub_arc(bb, 2, [5, 6, 7, 8])
    _write_stub_arc(bb, 3, [9, 10, 11, 12])

    a = GenreBookDistiller()
    system, user, inputs_read = a._build_prompts(bb)

    assert isinstance(system, str) and len(system) > 50
    # All 3 arc files should be referenced
    assert any("arc-001.yaml" in p for p in inputs_read)
    assert any("arc-002.yaml" in p for p in inputs_read)
    assert any("arc-003.yaml" in p for p in inputs_read)


def test_book_distiller_handle_output_writes_latest_merged(bb):
    from src.genre_extractor.agents.book_distiller import GenreBookDistiller

    a = GenreBookDistiller()
    stub_json = (
        '{"distilled_from_arcs": [1, 2, 3, 4], '
        '"batch_id": "book-distilled", "chapters_covered": [1, 160], '
        '"novel_source": "merged", "extracted_at": "2026-05-12", '
        '"era_observations": [], "iron_law_candidates": [], '
        '"style_markers": [], "resource_candidates": [], '
        '"open_questions": []}'
    )
    a._handle_output(bb, stub_json, arc_ids=[1, 2, 3, 4])

    assert bb.exists("extraction_notes/latest_merged.yaml")
    data = bb.read_yaml("extraction_notes/latest_merged.yaml")
    assert data["distilled_from_arcs"] == [1, 2, 3, 4]


def test_book_distiller_full_run_with_stub_llm(bb, monkeypatch):
    from src.genre_extractor.agents.book_distiller import GenreBookDistiller

    _write_stub_arc(bb, 1, [1, 2, 3, 4])
    _write_stub_arc(bb, 2, [5, 6, 7, 8])
    _write_stub_arc(bb, 3, [9, 10, 11, 12])
    _write_stub_arc(bb, 4, [13, 14, 15, 16])

    calls: list[dict] = []

    def fake_chat(*, system, user, agent_name, temperature, response_format, **_):
        calls.append({
            "agent_name": agent_name,
            "temperature": temperature,
            "response_format": response_format,
        })
        return (
            '{"distilled_from_arcs": [1,2,3,4], '
            '"batch_id": "book-distilled", "chapters_covered": [1, 160], '
            '"novel_source": "merged", "extracted_at": "2026-05-12", '
            '"era_observations": [], '
            '"iron_law_candidates": [{"summary": "ultra-merged", "evidence_chapters": [1], '
            '"evidence_quotes": [], "confidence": "high", "recurrence_count": 16}], '
            '"style_markers": [], "resource_candidates": [], '
            '"open_questions": []}'
        )

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    GenreBookDistiller().run(bb, arc_ids=[1, 2, 3, 4])

    assert len(calls) == 1
    assert calls[0]["agent_name"] == "genre_book_distiller"
    assert calls[0]["temperature"] == 0.2
    assert calls[0]["response_format"] == "json"
    assert bb.exists("extraction_notes/latest_merged.yaml")
    data = bb.read_yaml("extraction_notes/latest_merged.yaml")
    assert data["distilled_from_arcs"] == [1, 2, 3, 4]
    assert data["iron_law_candidates"][0]["recurrence_count"] == 16


def test_book_distiller_auto_discovers_arcs_when_no_arc_ids(bb, monkeypatch):
    """If arc_ids kwarg not provided, should auto-discover from arcs/ dir."""
    from src.genre_extractor.agents.book_distiller import GenreBookDistiller

    _write_stub_arc(bb, 1, [1, 2, 3, 4])
    _write_stub_arc(bb, 2, [5, 6, 7, 8])

    a = GenreBookDistiller()
    system, user, inputs_read = a._build_prompts(bb)

    # Both arcs must be referenced
    assert any("arc-001" in p for p in inputs_read)
    assert any("arc-002" in p for p in inputs_read)
