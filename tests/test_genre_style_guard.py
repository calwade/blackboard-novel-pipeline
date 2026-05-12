"""GenreStyleGuard — writing-style internal & cross-rule consistency + AI 味.

Tests:
1. Instantiation.
2. _build_prompts reads writing-style-extra.md + rules/writing-style-core.md.
3. _handle_output tags source="style_guard".
4. Full run via stub LLM writes issues.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _seed_genre(tmp_path: Path, genre_id: str, *, style: str | None = None) -> Path:
    from src.genre_extractor import pipeline
    pipeline.new_genre(genre_id, display_name="t", genre="x", era="y", tone="z")
    if style is not None:
        (tmp_path / genre_id / "writing-style-extra.md").write_text(
            style, encoding="utf-8"
        )
    return tmp_path / genre_id


def test_style_guard_instantiates():
    from src.genre_extractor.auditors.genre_style_guard import GenreStyleGuard
    a = GenreStyleGuard()
    assert a.name == "genre_style_guard"
    assert a.temperature == 0.2
    assert a.response_format == "json"


def test_style_guard_build_prompts_reads_style_files(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(tmp_path, "g-sg-1", style="# Style\n要简洁。\n")

    from src.core.blackboard import Blackboard
    from src.genre_extractor.auditors.genre_style_guard import GenreStyleGuard

    bb = Blackboard(root=tmp_path / "g-sg-1" / ".build")
    system, user, inputs_read = GenreStyleGuard()._build_prompts(
        bb, genre_id="g-sg-1"
    )
    joined = " ".join(inputs_read)
    assert "writing-style-extra.md" in joined
    # Also reads rules/writing-style-core.md
    assert any("writing-style-core" in p for p in inputs_read)
    assert "要简洁" in user


def test_style_guard_handle_output_tags_source(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(tmp_path, "g-sg-2")

    from src.core.blackboard import Blackboard
    from src.genre_extractor.auditors.genre_style_guard import GenreStyleGuard

    bb = Blackboard(root=tmp_path / "g-sg-2" / ".build")
    raw = (
        '{"issues": ['
        '{"severity": "warning", "file": "writing-style-extra.md", '
        '"quote": "总而言之要写得好", "message": "AI 味套话", '
        '"suggestion": "删除这句"}]}'
    )
    GenreStyleGuard()._handle_output(bb, raw, genre_id="g-sg-2")

    issues = bb.read_jsonl("genre_issues.jsonl")
    assert len(issues) == 1
    assert issues[0]["source"] == "style_guard"
    assert issues[0]["genre_id"] == "g-sg-2"


def test_style_guard_full_run_with_stub_llm(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(
        tmp_path,
        "g-sg-3",
        style="# Style\n总而言之，要写得生动活泼。\n",
    )

    def fake_chat(*, system, user, agent_name, **_):
        assert agent_name == "genre_style_guard"
        return (
            '{"issues": [{"severity": "warning", "file": "writing-style-extra.md", '
            '"quote": "总而言之", "message": "AI 式过渡套语", '
            '"suggestion": "直接给出具体要求"}]}'
        )

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)

    from src.core.blackboard import Blackboard
    from src.genre_extractor.auditors.genre_style_guard import GenreStyleGuard

    bb = Blackboard(root=tmp_path / "g-sg-3" / ".build")
    GenreStyleGuard().run(bb, genre_id="g-sg-3")

    issues = bb.read_jsonl("genre_issues.jsonl")
    assert len(issues) == 1
    assert issues[0]["source"] == "style_guard"
