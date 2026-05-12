"""四个题材 Agent 可实例化 + prompt 可构造。

不调真实 LLM；只验证骨架。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.blackboard import Blackboard
from src.genre_pipeline.schemas import make_initial_build_status, make_empty_blueprint


@pytest.fixture
def build_bb(tmp_path: Path) -> Blackboard:
    """A Blackboard with a minimal build_status ready for Agents."""
    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "novel.txt", "total_chapters": 50, "batch_size": 10}],
    )
    bb.write_yaml("build_status.yaml", status)
    return bb


def test_extractor_instantiates():
    from src.genre_pipeline.agents.extractor import GenreExtractor
    a = GenreExtractor()
    assert a.name == "genre_extractor"
    assert a.response_format == "json"


def test_extractor_build_prompts(build_bb):
    from src.genre_pipeline.agents.extractor import GenreExtractor
    a = GenreExtractor()
    system, user, inputs_read = a._build_prompts(
        build_bb, batch_id=1, batch_text="mock text"
    )
    assert isinstance(system, str) and len(system) > 50
    assert isinstance(user, str) and "mock text" in user
    assert isinstance(inputs_read, list)


def test_drafter_instantiates():
    from src.genre_pipeline.agents.drafter import GenreDrafter
    a = GenreDrafter()
    assert a.name.startswith("genre_drafter")


def test_drafter_build_prompts_with_blueprint(build_bb):
    from src.genre_pipeline.agents.drafter import GenreDrafter
    build_bb.write_yaml("genre_blueprint.yaml", make_empty_blueprint(genre_id="demo"))
    a = GenreDrafter()
    system, user, inputs_read = a._build_prompts(build_bb)
    assert "demo" in user or "blueprint" in user.lower()
    assert "genre_blueprint.yaml" in " ".join(inputs_read)


def test_validator_instantiates():
    from src.genre_pipeline.agents.validator import GenreValidator
    a = GenreValidator()
    assert a.name == "genre_validator"


def test_fixer_instantiates():
    from src.genre_pipeline.agents.fixer import GenreFixer
    a = GenreFixer()
    assert a.name == "genre_fixer"


def test_all_agents_subclass_base_agent():
    """All four genre agents must inherit from the shared BaseAgent."""
    from src.core.base_agent import BaseAgent
    from src.genre_pipeline.agents import (
        GenreExtractor, GenreDrafter, GenreValidator, GenreFixer,
    )
    for cls in (GenreExtractor, GenreDrafter, GenreValidator, GenreFixer):
        assert issubclass(cls, BaseAgent), f"{cls.__name__} not subclass of BaseAgent"
