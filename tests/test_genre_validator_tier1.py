"""GenreValidator Tier-1 机械正则扫描 deny 短语。

验证：
1. 存在 `GenreValidator._tier1_deny_scan(genre_id)` 方法（或类似），返回 issue list。
2. 注入含 deny 短语的 era.md / writing-style-extra.md / iron-laws-extra.md
   能被命中，severity='warning'，file 指向出问题的文件。
3. 不含 deny 短语的文件返回空列表。
4. 整体 `_run_validate` 会把 Tier-1 结果也写入 genre_issues.jsonl。
5. Validator.run 在正常 LLM mock 下不会把 Tier-1 当成 Stage 2 的替代（两者叠加）。
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_stub_genre(tmp_path: Path, genre_id: str, era_content: str = "标准时代描述，无问题。\n"):
    """Seed a minimal valid genre dir with caller-controlled era.md."""
    from src.genre_extractor import pipeline
    pipeline.new_genre(genre_id, display_name="t", genre="x", era="y", tone="z")
    (tmp_path / genre_id / "era.md").write_text(era_content, encoding="utf-8")


def test_tier1_deny_scan_hits_chinese_phrase(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    # "总而言之" is in rules/deny-phrases-zh.txt
    _make_stub_genre(
        tmp_path,
        "g-zh-deny",
        era_content="这是一个时代背景。总而言之，这个年代很特别。\n",
    )

    from src.genre_extractor.agents.validator import GenreValidator
    v = GenreValidator()

    issues = v._tier1_deny_scan("g-zh-deny")

    assert isinstance(issues, list)
    assert len(issues) >= 1, "should flag '总而言之'"
    hit = issues[0]
    assert hit["file"] == "era.md"
    assert hit["severity"] == "warning"
    # message should reference the offending phrase
    assert "总而言之" in hit["message"]


def test_tier1_deny_scan_hits_english_phrase(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    _make_stub_genre(
        tmp_path,
        "g-en-deny",
        era_content="Background. In today's fast-paced world, things change.\n",
    )

    from src.genre_extractor.agents.validator import GenreValidator
    issues = GenreValidator()._tier1_deny_scan("g-en-deny")

    assert any("fast-paced world" in i["message"].lower() or "fast-paced" in i["message"] for i in issues), \
        f"expected English phrase hit, got {issues}"


def test_tier1_deny_scan_returns_empty_on_clean_files(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    _make_stub_genre(
        tmp_path,
        "g-clean",
        era_content="一九八三年香港，街头小贩用粤语叫卖着猪肉粥。\n",
    )

    from src.genre_extractor.agents.validator import GenreValidator
    issues = GenreValidator()._tier1_deny_scan("g-clean")

    assert issues == [], f"clean file should return no hits, got {issues}"


def test_tier1_runs_before_stage2_in_validator_run(tmp_path, monkeypatch):
    """A full Validator.run should include Tier-1 hits even when Stage 2 LLM returns no issues."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    _make_stub_genre(
        tmp_path,
        "g-combined",
        era_content="年代背景。毋庸置疑，这就是事实。\n",  # '毋庸置疑' is in deny list
    )

    # Mock Stage 2 to return no issues
    def fake_chat(*, system, user, agent_name, temperature, response_format, **_):
        return '{"issues": []}'

    monkeypatch.setattr("src.core.base_agent.llm.chat", fake_chat)
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat, raising=False)

    from src.core.blackboard import Blackboard
    from src.genre_extractor.agents.validator import GenreValidator

    bb = Blackboard(root=tmp_path / "g-combined" / ".build")
    GenreValidator().run(bb, genre_id="g-combined")

    # After run, Tier-1 issue must appear in genre_issues.jsonl
    issues = bb.read_jsonl("genre_issues.jsonl")
    tier1_hits = [i for i in issues if "毋庸置疑" in i.get("message", "")]
    assert len(tier1_hits) >= 1, \
        f"Tier-1 deny hit missing from issues; got {issues}"
