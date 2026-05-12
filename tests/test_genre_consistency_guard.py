"""GenreConsistencyGuard — iron-laws / era / resource_schema consistency.

Tests:
1. Instantiation.
2. _build_prompts reads iron-laws-extra.md + era.md (+ resource_schema.yaml if present).
3. _handle_output tags issues source="consistency_guard".
4. Full run via stub LLM writes correctly-sourced issues.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _seed_genre(tmp_path: Path, genre_id: str, *, with_resources: bool = False) -> Path:
    from src.genre_pipeline import pipeline
    pipeline.new_genre(genre_id, display_name="t", genre="x", era="y", tone="z")
    if with_resources:
        (tmp_path / genre_id / "resource_schema.yaml").write_text(
            "resources:\n  - id: qi\n    baseline_scale: 100\n",
            encoding="utf-8",
        )
    return tmp_path / genre_id


def test_consistency_guard_instantiates():
    from src.genre_pipeline.auditors.genre_consistency_guard import (
        GenreConsistencyGuard,
    )
    a = GenreConsistencyGuard()
    assert a.name == "genre_consistency_guard"
    assert a.temperature == 0.0
    assert a.response_format == "json"


def test_consistency_guard_build_prompts_reads_iron_laws_and_era(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(tmp_path, "g-cg-1")

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.auditors.genre_consistency_guard import (
        GenreConsistencyGuard,
    )

    bb = Blackboard(root=tmp_path / "g-cg-1" / ".build")
    system, user, inputs_read = GenreConsistencyGuard()._build_prompts(
        bb, genre_id="g-cg-1"
    )
    joined = " ".join(inputs_read)
    assert "iron-laws-extra.md" in joined
    assert "era.md" in joined
    # resource schema not present → should NOT appear
    assert "resource_schema.yaml" not in joined


def test_consistency_guard_reads_resource_schema_when_present(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(tmp_path, "g-cg-rs", with_resources=True)

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.auditors.genre_consistency_guard import (
        GenreConsistencyGuard,
    )

    bb = Blackboard(root=tmp_path / "g-cg-rs" / ".build")
    _, user, inputs_read = GenreConsistencyGuard()._build_prompts(
        bb, genre_id="g-cg-rs"
    )
    joined = " ".join(inputs_read)
    assert "resource_schema.yaml" in joined
    assert "baseline_scale" in user


def test_consistency_guard_handle_output_tags_source(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(tmp_path, "g-cg-2")

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.auditors.genre_consistency_guard import (
        GenreConsistencyGuard,
    )

    bb = Blackboard(root=tmp_path / "g-cg-2" / ".build")
    raw = (
        '{"issues": ['
        '{"severity": "error", "file": "iron-laws-extra.md", '
        '"quote": "主角绝不杀人", "message": "与 era.md 帮派文化矛盾", '
        '"suggestion": "放宽杀人禁令"}]}'
    )
    GenreConsistencyGuard()._handle_output(bb, raw, genre_id="g-cg-2")

    issues = bb.read_jsonl("genre_issues.jsonl")
    assert len(issues) == 1
    assert issues[0]["source"] == "consistency_guard"
    assert issues[0]["genre_id"] == "g-cg-2"


def test_consistency_guard_full_run_with_stub_llm(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    _seed_genre(tmp_path, "g-cg-3")

    def fake_chat(*, system, user, agent_name, **_):
        assert agent_name == "genre_consistency_guard"
        return (
            '{"issues": [{"severity": "warning", "file": "iron-laws-extra.md", '
            '"quote": "主角绝不杀人", '
            '"message": "与 era.md「帮派月月械斗」矛盾", '
            '"suggestion": "细化为：不主动以个人名义杀人"}]}'
        )

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)

    from src.core.blackboard import Blackboard
    from src.genre_pipeline.auditors.genre_consistency_guard import (
        GenreConsistencyGuard,
    )

    bb = Blackboard(root=tmp_path / "g-cg-3" / ".build")
    GenreConsistencyGuard().run(bb, genre_id="g-cg-3")

    issues = bb.read_jsonl("genre_issues.jsonl")
    assert len(issues) == 1
    assert issues[0]["source"] == "consistency_guard"
    assert issues[0]["severity"] == "warning"
