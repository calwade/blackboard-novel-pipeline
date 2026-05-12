"""GenreFactChecker — era-fact-focused auditor (part of Validator fan-out).

Tests:
1. Can be instantiated; has expected name/temperature/response_format.
2. `_build_prompts` reads era.md and lists it in inputs_read.
3. `_handle_output` parses stub LLM JSON and appends each issue to
   genre_issues.jsonl with source="fact_checker" + genre_id.
4. End-to-end: run() via a stubbed LLM produces the expected issues on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _seed_genre(tmp_path: Path, genre_id: str, *, era: str = "年代说明。\n") -> Path:
    """Create a minimal genre dir under tmp_path with the 4 required files."""
    from src.genre_pipeline import pipeline
    pipeline.new_genre(genre_id, display_name="t", genre="x", era="y", tone="z")
    (tmp_path / genre_id / "era.md").write_text(era, encoding="utf-8")
    return tmp_path / genre_id


def test_fact_checker_instantiates():
    from src.genre_pipeline.auditors.genre_fact_checker import GenreFactChecker
    a = GenreFactChecker()
    assert a.name == "genre_fact_checker"
    assert a.temperature == 0.0
    assert a.response_format == "json"


def test_fact_checker_build_prompts_reads_era(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    _seed_genre(tmp_path, "g-fc-1", era="一九八三年的油麻地。\n")

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.auditors.genre_fact_checker import GenreFactChecker

    bb = Blackboard(root=tmp_path / "g-fc-1" / ".build")
    system, user, inputs_read = GenreFactChecker()._build_prompts(
        bb, genre_id="g-fc-1"
    )
    assert isinstance(system, str) and len(system) > 50
    assert isinstance(user, str) and "一九八三年的油麻地" in user
    assert any("era.md" in p for p in inputs_read)


def test_fact_checker_handle_output_writes_issues_with_source(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    _seed_genre(tmp_path, "g-fc-2")

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.auditors.genre_fact_checker import GenreFactChecker

    bb = Blackboard(root=tmp_path / "g-fc-2" / ".build")
    raw = (
        '{"issues": ['
        '{"severity": "error", "file": "era.md", "quote": "一九八三年美国回归香港", '
        '"message": "事实错误：香港回归时间是 1997", "suggestion": "改为 1997"}]}'
    )
    GenreFactChecker()._handle_output(bb, raw, genre_id="g-fc-2")

    issues = bb.read_jsonl("genre_issues.jsonl")
    assert len(issues) == 1
    issue = issues[0]
    assert issue["source"] == "fact_checker"
    assert issue["genre_id"] == "g-fc-2"
    assert issue["severity"] == "error"
    assert "事实错误" in issue["message"]


def test_fact_checker_full_run_with_stub_llm(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    _seed_genre(tmp_path, "g-fc-3", era="一九八三年美国回归香港。\n")

    def fake_chat(*, system, user, agent_name, **_):
        assert agent_name == "genre_fact_checker"
        return (
            '{"issues": [{"severity": "error", "file": "era.md", '
            '"quote": "一九八三年美国回归香港", '
            '"message": "史实错误：1997 年英国交还香港", '
            '"suggestion": "改为 一九九七年英国交还香港"}]}'
        )

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.auditors.genre_fact_checker import GenreFactChecker

    bb = Blackboard(root=tmp_path / "g-fc-3" / ".build")
    GenreFactChecker().run(bb, genre_id="g-fc-3")

    issues = bb.read_jsonl("genre_issues.jsonl")
    assert len(issues) == 1
    assert issues[0]["source"] == "fact_checker"
    assert issues[0]["genre_id"] == "g-fc-3"
    assert "史实" in issues[0]["message"]
