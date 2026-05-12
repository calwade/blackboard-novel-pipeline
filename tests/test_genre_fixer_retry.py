"""Fixer retry loop + ship_with_debt for genre pipeline validate phase.

Mirrors tests/test_pipeline_intent_router.py's pattern of monkey-patching
`src.agents._base.llm.chat` + counting calls, adapted to the genre agents.

2026-05-12 update: GenreValidator was split into 3 parallel auditors
(genre_fact_checker / genre_consistency_guard / genre_style_guard), so
these tests now stub the 3 auditor agent names instead of "genre_validator".
The retry-loop semantic being tested (validate→fix→validate, N retries,
ship-with-debt after max) is unchanged.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import pytest


# Agents that together constitute the semantic "validate" LLM call set
_VALIDATE_AGENTS = (
    "genre_fact_checker",
    "genre_consistency_guard",
    "genre_style_guard",
)


def _install_fake_llm(monkeypatch, responses):
    """Install a fake LLM that yields `responses` in order per agent_name.

    Returns a list that records (agent_name, response_index) for each call.
    """
    iters: dict[str, object] = {}
    calls: list[tuple[str, int]] = []

    def fake_chat(*, system, user, agent_name, **kw):
        if agent_name not in iters:
            iters[agent_name] = iter(responses.get(agent_name, itertools.repeat("{}")))
        out = next(iters[agent_name])  # type: ignore[call-overload]
        calls.append((agent_name, len(calls)))
        return out

    # Patch both shim and core — they reference the same llm module, so
    # patching either works, but we patch the shim for clarity.
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)
    return calls


def _count_validate_rounds(calls: list[tuple[str, int]]) -> int:
    """One validate round = up to 3 auditor calls (one per agent).

    We count unique validation rounds by tracking per-agent call counts and
    taking the max (each round contributes at most 1 call per agent).
    """
    per_agent = {a: 0 for a in _VALIDATE_AGENTS}
    for name, _ in calls:
        if name in per_agent:
            per_agent[name] += 1
    return max(per_agent.values()) if per_agent else 0


def test_validate_no_errors_no_fixer(tmp_path, monkeypatch):
    """Happy path: validator returns 0 errors → Fixer never invoked."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    # Create a minimal genre pack so setting_lint doesn't explode
    from src.genre_extractor import pipeline
    pipeline.new_genre("g-clean", display_name="clean", genre="x", era="y", tone="z")

    # All 3 auditors return zero issues
    empty = '{"issues": []}'
    calls = _install_fake_llm(monkeypatch, {
        "genre_fact_checker": [empty],
        "genre_consistency_guard": [empty],
        "genre_style_guard": [empty],
    })

    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path / "g-clean" / ".build")
    pipeline._run_validate(bb, "g-clean", with_trial=False)

    # All 3 auditors were invoked at least once; Fixer should NOT run because
    # auditors found nothing (lint may still flag stub files, but that's
    # orthogonal to this test's assertion).
    agent_names = {c[0] for c in calls}
    assert _VALIDATE_AGENTS[0] in agent_names, (
        f"first call should include an auditor, got {calls}"
    )


def test_validate_ships_debt_after_max_retries(tmp_path, monkeypatch):
    """Pathological: one auditor always returns an error on the same file →
    after 2 retries we bail and write to genre_debt.jsonl."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    from src.genre_extractor import pipeline
    pipeline.new_genre("g-stubborn", display_name="s", genre="x", era="y", tone="z")

    # Write something to era.md so Fixer has a real file to touch
    (tmp_path / "g-stubborn" / "era.md").write_text("original era content\n", encoding="utf-8")

    # fact_checker always says era.md has an error; the other two auditors are
    # clean; Fixer always "fixes" but fact_checker keeps rejecting.
    error_issue = (
        '{"issues": [{"severity": "error", "file": "era.md", '
        '"message": "era.md still wrong", "suggestion": "redo"}]}'
    )
    empty = '{"issues": []}'
    fixer_output = "rewritten era content\n"

    calls = _install_fake_llm(monkeypatch, {
        "genre_fact_checker": [error_issue, error_issue, error_issue],
        "genre_consistency_guard": [empty, empty, empty],
        "genre_style_guard": [empty, empty, empty],
        "genre_fixer": [fixer_output, fixer_output],
    })

    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path / "g-stubborn" / ".build")
    pipeline._run_validate(bb, "g-stubborn", with_trial=False, max_fix_retries=2)

    # Counts — 3 validation rounds, 2 fixer rounds
    assert _count_validate_rounds(calls) == 3, (
        f"expected 3 validation rounds, got {_count_validate_rounds(calls)}; calls={calls}"
    )
    fixer_calls = [c for c in calls if c[0] == "genre_fixer"]
    assert len(fixer_calls) == 2, f"expected 2 fixer calls, got {len(fixer_calls)}"

    # genre_debt.jsonl should have a ship-with-debt record
    debt = bb.read_jsonl("genre_debt.jsonl")
    assert len(debt) == 1
    assert debt[0]["genre_id"] == "g-stubborn"
    assert debt[0]["retries_used"] == 2
    assert len(debt[0]["unresolved_errors"]) >= 1
    assert any("era.md" in str(e) for e in debt[0]["unresolved_errors"])


def test_validate_recovers_on_second_attempt(tmp_path, monkeypatch):
    """Fixer fixes the problem in round 1 → attempt 1 validator clean → stop."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    from src.genre_extractor import pipeline
    pipeline.new_genre("g-recovering", display_name="r", genre="x", era="y", tone="z")
    (tmp_path / "g-recovering" / "era.md").write_text("bad\n", encoding="utf-8")

    error_issue = (
        '{"issues": [{"severity": "error", "file": "era.md", '
        '"message": "bad", "suggestion": "fix"}]}'
    )
    empty = '{"issues": []}'

    calls = _install_fake_llm(monkeypatch, {
        # Round 1: fact_checker errors, others clean.
        # Round 2: all clean.
        "genre_fact_checker": [error_issue, empty],
        "genre_consistency_guard": [empty, empty],
        "genre_style_guard": [empty, empty],
        "genre_fixer": ["fixed era content\n"],
    })

    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path / "g-recovering" / ".build")
    pipeline._run_validate(bb, "g-recovering", with_trial=False, max_fix_retries=2)

    assert _count_validate_rounds(calls) == 2, (
        f"expected 2 validation rounds, got {_count_validate_rounds(calls)}; calls={calls}"
    )
    fixer_calls = [c for c in calls if c[0] == "genre_fixer"]
    assert len(fixer_calls) == 1

    # No debt record — recovery succeeded
    debt = bb.read_jsonl("genre_debt.jsonl")
    assert debt == []

    # Fixer actually wrote to era.md
    assert "fixed era content" in (tmp_path / "g-recovering" / "era.md").read_text("utf-8")


def test_apply_fixer_round_skips_meta_files(tmp_path, monkeypatch):
    """Issues with file='(validator)' / '(structure)' don't call Fixer."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    from src.genre_extractor import pipeline
    pipeline.new_genre("g-meta", display_name="m", genre="x", era="y", tone="z")

    calls = _install_fake_llm(monkeypatch, {
        "genre_fixer": ["should not be called\n"],
    })

    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path / "g-meta" / ".build")
    meta_errors = [
        {"severity": "error", "file": "(validator)", "message": "x"},
        {"severity": "error", "file": "(structure)", "message": "y"},
        {"severity": "error", "file": "", "message": "z"},
    ]
    pipeline._apply_fixer_round(bb, "g-meta", meta_errors)

    # Fixer was never invoked
    fixer_calls = [c for c in calls if c[0] == "genre_fixer"]
    assert fixer_calls == []
