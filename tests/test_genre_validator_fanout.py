"""GenreValidator fan-out into 3 parallel auditors.

Tests:
1. Validator.run() calls all 3 auditors (GenreFactChecker, GenreConsistencyGuard,
   GenreStyleGuard) and their issues each appear in genre_issues.jsonl with
   the correct `source` tag.
2. If ONE auditor raises an exception, the other two still complete, and the
   failure is captured as a `warning` issue (not propagated).
3. Tier-1 deterministic deny-scan still runs (and its hits still appear with
   source="tier1-deny-scan"), coexisting with the fan-out.
4. Public interface unchanged: `run(bb, genre_id=...)` takes same args, returns
   without raising when all auditors succeed.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _seed_genre(tmp_path: Path, genre_id: str, *, era: str = "年代背景。\n"):
    from src.genre_pipeline import pipeline
    pipeline.new_genre(genre_id, display_name="t", genre="x", era="y", tone="z")
    (tmp_path / genre_id / "era.md").write_text(era, encoding="utf-8")


def test_validator_runs_three_auditors_each_writes_issue(tmp_path, monkeypatch):
    """Happy path: all 3 auditors return issues; each lands in genre_issues.jsonl."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(tmp_path, "g-fanout-1")

    call_log: list[str] = []

    def fake_chat(*, system, user, agent_name, **_):
        call_log.append(agent_name)
        # Return a distinct issue per agent, identifiable by message text
        return (
            '{"issues": [{"severity": "warning", "file": "era.md", '
            f'"quote": "q", "message": "issue-from-{agent_name}", '
            '"suggestion": "s"}]}'
        )

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.agents.validator import GenreValidator

    bb = Blackboard(root=tmp_path / "g-fanout-1" / ".build")
    GenreValidator().run(bb, genre_id="g-fanout-1")

    issues = bb.read_jsonl("genre_issues.jsonl")
    sources = {i.get("source") for i in issues}

    # All 3 auditors must have contributed
    assert "fact_checker" in sources, f"missing fact_checker in {sources}"
    assert "consistency_guard" in sources, f"missing consistency_guard in {sources}"
    assert "style_guard" in sources, f"missing style_guard in {sources}"

    # All 3 agents were invoked (order may vary due to parallel exec)
    assert set(call_log) == {
        "genre_fact_checker",
        "genre_consistency_guard",
        "genre_style_guard",
    }, f"unexpected agent call set: {call_log}"


def test_validator_isolates_auditor_failure(tmp_path, monkeypatch):
    """One auditor crashes; the other two still finish, and crash is recorded."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(tmp_path, "g-fanout-2")

    def fake_chat(*, system, user, agent_name, **_):
        if agent_name == "genre_fact_checker":
            raise RuntimeError("boom: fact checker exploded")
        return (
            '{"issues": [{"severity": "warning", "file": "era.md", '
            f'"quote": "q", "message": "ok-from-{agent_name}", '
            '"suggestion": "s"}]}'
        )

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.agents.validator import GenreValidator

    bb = Blackboard(root=tmp_path / "g-fanout-2" / ".build")
    # Public interface: run() must NOT raise when one auditor dies
    GenreValidator().run(bb, genre_id="g-fanout-2")

    issues = bb.read_jsonl("genre_issues.jsonl")
    sources = {i.get("source") for i in issues}

    # The two survivors contributed
    assert "consistency_guard" in sources
    assert "style_guard" in sources

    # Failure was captured as a warning
    failure_issues = [
        i for i in issues
        if "genre_fact_checker" in i.get("message", "")
        or "fact_checker" in i.get("message", "").lower()
    ]
    assert failure_issues, f"expected failure-capture issue, got {issues}"
    assert failure_issues[0]["severity"] == "warning"
    assert failure_issues[0]["file"] == "(validator)"


def test_validator_keeps_tier1_deny_scan(tmp_path, monkeypatch):
    """Tier-1 deny-scan MUST still run; its issues coexist with fan-out results."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    # era.md contains a known zh deny phrase
    _seed_genre(tmp_path, "g-fanout-3", era="年代说明。总而言之，就这样。\n")

    def fake_chat(*, system, user, agent_name, **_):
        return '{"issues": []}'  # All auditors find nothing via LLM

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.agents.validator import GenreValidator

    bb = Blackboard(root=tmp_path / "g-fanout-3" / ".build")
    GenreValidator().run(bb, genre_id="g-fanout-3")

    issues = bb.read_jsonl("genre_issues.jsonl")
    tier1 = [i for i in issues if i.get("source") == "tier1-deny-scan"]
    assert tier1, f"Tier-1 deny scan did not run or not tagged; issues={issues}"
    assert any("总而言之" in i["message"] for i in tier1)


def test_validator_public_run_signature_unchanged(tmp_path, monkeypatch):
    """Upstream (_run_validate, retry loop) calls `.run(bb, genre_id=...)`.
    This contract must survive the refactor."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(tmp_path, "g-fanout-4")

    monkeypatch.setattr(
        "src.agents._base.llm.chat",
        lambda **_: '{"issues": []}',
    )

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.agents.validator import GenreValidator

    bb = Blackboard(root=tmp_path / "g-fanout-4" / ".build")
    # This call shape is what _run_validate uses — must not raise.
    GenreValidator().run(bb, genre_id="g-fanout-4")
