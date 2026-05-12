"""End-to-end test: 3-tier merge behavior of src.genre_extractor.pipeline._run_merge.

Three regimes:
  ≤ ARC_BATCH_COUNT (4) batches   → pure concat, 0 LLM calls
  5 – 4*ARC_BATCH_COUNT batches   → arc tier only (≥2 arc merger calls, 0 book distill)
  > 4*ARC_BATCH_COUNT batches     → arc tier + book distill (≥4 arc + 1 distill)

This anchors the implementation plan described in the 2026-05-12 spec:
  - short book: 2 batches      → 0 LLM
  - mid book: 8 batches         → 2 arc_merger calls, no book distill
  - long book: 16 batches       → 4 arc_merger calls + 1 book distill
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.blackboard import Blackboard


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    return Blackboard(root=tmp_path)


def _seed_batch(bb: Blackboard, batch_id: int) -> None:
    """Write a minimal valid batch-NNN.yaml that _run_merge can consume."""
    bb.write_yaml(f"extraction_notes/batch-{batch_id:03d}.yaml", {
        "batch_id": batch_id,
        "chapters_covered": [batch_id * 10 - 9, batch_id * 10],
        "novel_source": "stub",
        "extracted_at": "2026-05-12",
        "era_observations": [
            {"summary": f"era-{batch_id}", "evidence_chapters": [batch_id],
             "evidence_quotes": [], "confidence": "high", "recurrence_count": 1},
        ],
        "iron_law_candidates": [
            {"summary": f"rule-{batch_id}", "evidence_chapters": [batch_id],
             "evidence_quotes": [], "confidence": "high", "recurrence_count": 1},
        ],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    })


def _seed_status(bb: Blackboard) -> None:
    """Minimal build_status for _run_merge to update phase info."""
    from src.genre_extractor.schemas import make_initial_build_status
    bb.write_yaml(
        "build_status.yaml",
        make_initial_build_status(
            genre_id="merge-tiers-demo",
            entry="extract-from-novel",
            novel_sources=[{"path": "x.txt", "total_chapters": 100, "batch_size": 25}],
        ),
    )


def _stub_arc_merger_output(arc_id: int, batch_ids: list[int]) -> str:
    return (
        f'{{"arc_id": {arc_id}, "covered_batches": {batch_ids}, '
        f'"batch_id": "arc-{arc_id:03d}", "chapters_covered": [1, 999], '
        f'"novel_source": "merged", "extracted_at": "2026-05-12", '
        f'"era_observations": [], '
        f'"iron_law_candidates": [{{"summary": "merged-rule-{arc_id}", '
        f'"evidence_chapters": [{arc_id}], "evidence_quotes": [], '
        f'"confidence": "high", "recurrence_count": 4}}], '
        f'"style_markers": [], "resource_candidates": [], '
        f'"open_questions": []}}'
    )


def _stub_book_distiller_output(arc_ids: list[int]) -> str:
    return (
        f'{{"distilled_from_arcs": {arc_ids}, '
        f'"batch_id": "book-distilled", "chapters_covered": [1, 9999], '
        f'"novel_source": "merged", "extracted_at": "2026-05-12", '
        f'"era_observations": [], '
        f'"iron_law_candidates": [{{"summary": "ultra-merged", '
        f'"evidence_chapters": [1], "evidence_quotes": [], '
        f'"confidence": "high", "recurrence_count": 99}}], '
        f'"style_markers": [], "resource_candidates": [], '
        f'"open_questions": []}}'
    )


# =========================================================================
# Regime 1: ≤ ARC_BATCH_COUNT batches → pure concat, 0 LLM calls
# =========================================================================

def test_merge_with_2_batches_uses_pure_concat_no_llm(bb, monkeypatch):
    """Short novel: 2 batches → fall back to simple concat, no LLM calls."""
    from src.genre_extractor import pipeline

    _seed_status(bb)
    _seed_batch(bb, 1)
    _seed_batch(bb, 2)

    call_count = {"n": 0}

    def fake_chat(**_):
        call_count["n"] += 1
        raise RuntimeError("should not be called for ≤4 batches")

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    pipeline._run_merge(bb)

    assert call_count["n"] == 0, "≤4 batches must not invoke LLM"
    assert bb.exists("extraction_notes/latest_merged.yaml")
    merged = bb.read_yaml("extraction_notes/latest_merged.yaml")
    # Concat mode: all 2 iron_laws present (not deduplicated by LLM)
    summaries = [i["summary"] for i in merged.get("iron_law_candidates", [])]
    assert "rule-1" in summaries
    assert "rule-2" in summaries


def test_merge_with_4_batches_still_uses_pure_concat(bb, monkeypatch):
    """Boundary: exactly ARC_BATCH_COUNT batches → pure concat (single arc would equal merged)."""
    from src.genre_extractor import pipeline

    _seed_status(bb)
    for i in range(1, 5):
        _seed_batch(bb, i)

    call_count = {"n": 0}

    def fake_chat(**_):
        call_count["n"] += 1
        raise RuntimeError("should not be called for ≤ARC_BATCH_COUNT batches")

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    pipeline._run_merge(bb)

    assert call_count["n"] == 0, "exactly 4 batches must not invoke LLM"
    assert bb.exists("extraction_notes/latest_merged.yaml")


# =========================================================================
# Regime 2: 5 – 16 batches → arc tier only (≥2 arc calls, 0 book distill)
# =========================================================================

def test_merge_with_8_batches_runs_arc_tier_only(bb, monkeypatch):
    """Mid novel: 8 batches → 2 arc_merger calls, 0 book_distiller calls."""
    from src.genre_extractor import pipeline

    _seed_status(bb)
    for i in range(1, 9):
        _seed_batch(bb, i)

    agent_calls: list[str] = []

    def fake_chat(*, agent_name, **_):
        agent_calls.append(agent_name)
        if agent_name == "genre_arc_merger":
            # Derive arc_id from how many arc calls so far
            arc_id = sum(1 for n in agent_calls if n == "genre_arc_merger")
            start_b = (arc_id - 1) * 4 + 1
            return _stub_arc_merger_output(arc_id, list(range(start_b, start_b + 4)))
        if agent_name == "genre_book_distiller":
            return _stub_book_distiller_output([1, 2])
        raise RuntimeError(f"unexpected agent {agent_name}")

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    pipeline._run_merge(bb)

    arc_calls = [a for a in agent_calls if a == "genre_arc_merger"]
    book_calls = [a for a in agent_calls if a == "genre_book_distiller"]

    assert len(arc_calls) == 2, f"expected 2 arc merger calls, got {len(arc_calls)}"
    assert len(book_calls) == 0, (
        f"8 batches → 2 arcs → book distill should NOT run "
        f"(threshold is >=2 arcs, but with exactly 2 arcs one of them is "
        f"promoted to latest_merged directly). Got {len(book_calls)} distill calls."
    )

    # Arc files must exist
    assert bb.exists("extraction_notes/arcs/arc-001.yaml")
    assert bb.exists("extraction_notes/arcs/arc-002.yaml")
    # Final latest_merged must exist
    assert bb.exists("extraction_notes/latest_merged.yaml")


def test_merge_with_5_batches_produces_2_arcs(bb, monkeypatch):
    """Odd number: 5 batches → arc 1 covers batches 1-4, arc 2 covers batch 5."""
    from src.genre_extractor import pipeline

    _seed_status(bb)
    for i in range(1, 6):
        _seed_batch(bb, i)

    agent_calls: list[str] = []

    def fake_chat(*, agent_name, **_):
        agent_calls.append(agent_name)
        if agent_name == "genre_arc_merger":
            arc_id = sum(1 for n in agent_calls if n == "genre_arc_merger")
            return _stub_arc_merger_output(arc_id, [arc_id])  # trivial covered_batches
        return _stub_book_distiller_output([1, 2])

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    pipeline._run_merge(bb)

    arc_calls = [a for a in agent_calls if a == "genre_arc_merger"]
    assert len(arc_calls) == 2
    assert bb.exists("extraction_notes/latest_merged.yaml")


# =========================================================================
# Regime 3: > 16 batches → arc tier + book distill
# =========================================================================

def test_merge_with_16_batches_runs_book_distill(bb, monkeypatch):
    """Long novel: 16 batches → 4 arc_merger calls + 1 book_distiller call."""
    from src.genre_extractor import pipeline

    _seed_status(bb)
    for i in range(1, 17):
        _seed_batch(bb, i)

    agent_calls: list[str] = []

    def fake_chat(*, agent_name, **_):
        agent_calls.append(agent_name)
        if agent_name == "genre_arc_merger":
            arc_id = sum(1 for n in agent_calls if n == "genre_arc_merger")
            start_b = (arc_id - 1) * 4 + 1
            return _stub_arc_merger_output(arc_id, list(range(start_b, start_b + 4)))
        if agent_name == "genre_book_distiller":
            return _stub_book_distiller_output([1, 2, 3, 4])
        raise RuntimeError(f"unexpected agent {agent_name}")

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    pipeline._run_merge(bb)

    arc_calls = [a for a in agent_calls if a == "genre_arc_merger"]
    book_calls = [a for a in agent_calls if a == "genre_book_distiller"]

    assert len(arc_calls) == 4, f"expected 4 arc merger calls, got {len(arc_calls)}"
    assert len(book_calls) == 1, (
        f"16 batches → 4 arcs → exactly 1 book distill call, got {len(book_calls)}"
    )

    # All 4 arc files must exist
    for aid in range(1, 5):
        assert bb.exists(f"extraction_notes/arcs/arc-{aid:03d}.yaml")
    # Final merged must exist
    assert bb.exists("extraction_notes/latest_merged.yaml")
    data = bb.read_yaml("extraction_notes/latest_merged.yaml")
    # latest_merged should be the distilled output (has distilled_from_arcs field)
    assert "distilled_from_arcs" in data


# =========================================================================
# Regime metadata: phase status + idempotency
# =========================================================================

def test_merge_updates_phase_status_to_done(bb, monkeypatch):
    """_run_merge must still mark the merge phase done regardless of tier."""
    from src.genre_extractor import pipeline

    _seed_status(bb)
    _seed_batch(bb, 1)
    _seed_batch(bb, 2)

    monkeypatch.setattr(
        "src.core.base_agent.llm.chat",
        lambda **_: (_ for _ in ()).throw(RuntimeError("no LLM for 2 batches"))
    )

    pipeline._run_merge(bb)

    status = bb.read_yaml("build_status.yaml")
    assert status["phases"]["merge"]["status"] == "done"
