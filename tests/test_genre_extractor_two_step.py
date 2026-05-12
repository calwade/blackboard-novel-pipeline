"""GenreExtractor 两步法：free-form notes (temp 0.3) → verbatim JSON (temp 0.0).

验证：
1. 一次 Extractor.run() 调用 llm.chat 恰好两次
2. 第一次 temperature ≈ 0.3, response_format='text'
3. 第二次 temperature == 0.0, response_format='json'
4. 第二次的 user prompt 中出现第一次的 assistant 输出（verbatim 提取）
5. 最终 YAML 产物 schema 合法 (有 batch_id / chapters_covered / evidence 等字段)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.blackboard import Blackboard


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    return Blackboard(root=tmp_path)


def test_extractor_calls_llm_exactly_twice(bb, monkeypatch):
    from src.genre_extractor.agents.extractor import GenreExtractor

    calls: list[dict] = []

    FREE_NOTES = (
        "<observations>\n"
        "- 观察 1: 街头话术密集\n"
        "</observations>\n"
        "<candidate_rules>\n"
        "- 铁律候选 A: 电话亭必须用粤语\n"
        "</candidate_rules>\n"
    )
    VERBATIM_JSON = (
        '{"batch_id": 1, "chapters_covered": [1,2,3], '
        '"novel_source": "mock", "extracted_at": "2026-05-12", '
        '"era_observations": [], "iron_law_candidates": [], '
        '"style_markers": [], "resource_candidates": [], '
        '"open_questions": []}'
    )

    def fake_chat(*, system, user, agent_name, temperature, response_format, **_):
        calls.append({
            "system": system,
            "user": user,
            "agent_name": agent_name,
            "temperature": temperature,
            "response_format": response_format,
        })
        if len(calls) == 1:
            return FREE_NOTES
        return VERBATIM_JSON

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    # Also patch the shim path used by some agents
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    GenreExtractor().run(bb, batch_id=1, batch_text="mock chapters content")

    assert len(calls) == 2, f"expected 2 LLM calls, got {len(calls)}"


def test_extractor_first_call_is_free_notes_text(bb, monkeypatch):
    from src.genre_extractor.agents.extractor import GenreExtractor

    calls: list[dict] = []

    def fake_chat(*, system, user, agent_name, temperature, response_format, **_):
        calls.append({
            "temperature": temperature,
            "response_format": response_format,
        })
        if len(calls) == 1:
            return "<observations>free notes</observations>"
        return '{"batch_id": 1, "chapters_covered": [], "novel_source": "m", "extracted_at": "t", "era_observations": [], "iron_law_candidates": [], "style_markers": [], "resource_candidates": [], "open_questions": []}'

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    GenreExtractor().run(bb, batch_id=1, batch_text="mock")

    first = calls[0]
    assert first["response_format"] == "text", \
        f"first call must be free-form text, got {first['response_format']}"
    # Free-notes temperature should be mildly creative (0.2 ~ 0.5)
    assert 0.15 <= first["temperature"] <= 0.5, \
        f"first call temp should be ~0.3, got {first['temperature']}"


def test_extractor_second_call_is_verbatim_json_zero_temp(bb, monkeypatch):
    from src.genre_extractor.agents.extractor import GenreExtractor

    FREE_NOTES_MARKER = "UNIQUE_NOTES_MARKER_12345"

    calls: list[dict] = []

    def fake_chat(*, system, user, agent_name, temperature, response_format, **_):
        calls.append({
            "user": user,
            "temperature": temperature,
            "response_format": response_format,
        })
        if len(calls) == 1:
            return f"<observations>\n- {FREE_NOTES_MARKER}\n</observations>"
        return '{"batch_id": 1, "chapters_covered": [], "novel_source": "m", "extracted_at": "t", "era_observations": [], "iron_law_candidates": [], "style_markers": [], "resource_candidates": [], "open_questions": []}'

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    GenreExtractor().run(bb, batch_id=1, batch_text="mock")

    second = calls[1]
    # Verbatim extraction must be deterministic
    assert second["temperature"] == 0.0, \
        f"second call temp must be 0.0, got {second['temperature']}"
    assert second["response_format"] == "json"
    # Step 2's user prompt MUST include step 1's free notes (verbatim extraction)
    assert FREE_NOTES_MARKER in second["user"], \
        "step 2 user prompt must quote step 1 free-notes verbatim"


def test_extractor_writes_yaml_file(bb, monkeypatch):
    from src.genre_extractor.agents.extractor import GenreExtractor

    def fake_chat(*, system, user, agent_name, temperature, response_format, **_):
        if response_format == "text":
            return "<observations>x</observations>"
        return '{"batch_id": 7, "chapters_covered": [70,71], "novel_source": "s", "extracted_at": "now", "era_observations": [], "iron_law_candidates": [], "style_markers": [], "resource_candidates": [], "open_questions": []}'

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    GenreExtractor().run(bb, batch_id=7, batch_text="mock")

    # File must exist with padding
    assert bb.exists("extraction_notes/batch-007.yaml")
    data = bb.read_yaml("extraction_notes/batch-007.yaml")
    assert data["batch_id"] == 7
    assert data["chapters_covered"] == [70, 71]
