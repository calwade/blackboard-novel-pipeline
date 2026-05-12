"""CharactersDrafter: free-text brief → structured characters.yaml dict."""
from __future__ import annotations

import yaml
import pytest


@pytest.fixture
def stub_llm(monkeypatch):
    canned = {
        "protagonist": {"name": "林家耀", "description": "24 岁, 福建人, 97 年穿越回 1983。"},
        "supporting": [
            {"name": "阿威", "role": "小弟", "description": "跟班。"},
            {"name": "苏婷", "role": "情报线", "description": "记者。"},
        ],
    }
    def fake_chat(messages, **kwargs):
        return {"content": yaml.safe_dump(canned, allow_unicode=True, sort_keys=False)}
    monkeypatch.setattr("src.llm.chat", fake_chat)
    return canned


def test_characters_drafter_produces_protagonist_and_supporting(stub_llm):
    from src.agents.characters_drafter import CharactersDrafter
    out = CharactersDrafter().run(
        brief="主角林家耀 24 岁福建人。阿威是小弟。苏婷是记者。",
        protagonist_name="林家耀",
    )
    assert out["protagonist"]["name"] == "林家耀"
    assert len(out["supporting"]) == 2


def test_characters_drafter_empty_brief_returns_shell():
    from src.agents.characters_drafter import CharactersDrafter
    out = CharactersDrafter().run(brief="", protagonist_name="Hero")
    assert out["protagonist"]["name"] == "Hero"
    assert out["protagonist"]["description"] == ""
    assert out["supporting"] == []


def test_characters_drafter_bad_yaml_falls_back_to_shell(monkeypatch):
    def bad_chat(messages, **kwargs):
        return {"content": "::: not: [yaml"}
    monkeypatch.setattr("src.llm.chat", bad_chat)
    from src.agents.characters_drafter import CharactersDrafter
    out = CharactersDrafter().run(brief="blah", protagonist_name="H")
    assert out["protagonist"]["name"] == "H"
    assert isinstance(out["supporting"], list)


def test_characters_drafter_overrides_protagonist_name(stub_llm):
    """Regardless what LLM says, the protagonist.name must match what user typed in step 1."""
    from src.agents.characters_drafter import CharactersDrafter
    out = CharactersDrafter().run(brief="something", protagonist_name="不同名")
    assert out["protagonist"]["name"] == "不同名"
