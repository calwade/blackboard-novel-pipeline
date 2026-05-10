"""Tests for websearch tool (A-1) + FactChecker auditor.

All network calls are monkey-patched. We verify:
- websearch.is_available() reads config correctly
- cache hits avoid network
- graceful degradation on missing API key / network error
- FactChecker.should_run gating logic (only moderate+ landmine_13 hits)
- FactChecker renders correct patch in each branch (no-claims, unavailable,
  parse-error, full-checked)
- Pipeline audit fan-out conditionally includes FactChecker
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src import config as cfg
from src.blackboard import Blackboard
from src.auditors.fact_checker import (
    FactChecker,
    should_run,
    _render_no_claims,
    _render_unavailable,
    _render_parse_error,
    _render_patch,
)
from src.tools import websearch


# ---------------- websearch tool ----------------

def test_is_available_respects_env(monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setattr(cfg, "PERPLEXITY_API_KEY", "", raising=False)
    assert websearch.is_available() is False

    monkeypatch.setenv("PERPLEXITY_API_KEY", "fake-key")
    assert websearch.is_available() is True


def test_search_raises_when_unconfigured(monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setattr(cfg, "PERPLEXITY_API_KEY", "", raising=False)
    with pytest.raises(websearch.WebSearchUnavailable):
        websearch.search("test query")


def test_search_cache_hits_avoid_network(monkeypatch, tmp_path):
    """Second identical call must hit the cache and not post()."""
    monkeypatch.setenv("PERPLEXITY_API_KEY", "fake-key")
    # Redirect cache + log to tmp so test is isolated
    monkeypatch.setattr(websearch, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(websearch, "WEBSEARCH_LOG_PATH", tmp_path / "ws.jsonl")

    call_count = {"n": 0}

    class FakeResp:
        status_code = 200
        def json(self):
            return {
                "choices": [{"message": {"content": "pretend answer"}}],
                "citations": ["https://example.com/1", "https://example.com/2"],
            }

    def fake_post(url, headers, json):
        call_count["n"] += 1
        return FakeResp()

    monkeypatch.setattr(websearch._client, "post", fake_post)

    r1 = websearch.search("what year was HK handover")
    assert r1.cached is False
    assert call_count["n"] == 1
    assert r1.content == "pretend answer"
    assert len(r1.citations) == 2

    r2 = websearch.search("what year was HK handover")
    assert r2.cached is True
    assert call_count["n"] == 1  # no new network call
    assert r2.content == "pretend answer"


def test_search_raises_on_http_error(monkeypatch, tmp_path):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "fake-key")
    monkeypatch.setattr(websearch, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(websearch, "WEBSEARCH_LOG_PATH", tmp_path / "ws.jsonl")

    class FakeResp:
        status_code = 500
        text = "Server on fire"
    monkeypatch.setattr(websearch._client, "post", lambda url, headers, json: FakeResp())

    with pytest.raises(RuntimeError, match="500"):
        websearch.search("flaky query")


def test_search_network_error_raises_unavailable(monkeypatch, tmp_path):
    import httpx
    monkeypatch.setenv("PERPLEXITY_API_KEY", "fake-key")
    monkeypatch.setattr(websearch, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(websearch, "WEBSEARCH_LOG_PATH", tmp_path / "ws.jsonl")

    def boom(*a, **kw):
        raise httpx.ConnectError("net down")
    monkeypatch.setattr(websearch._client, "post", boom)

    with pytest.raises(websearch.WebSearchUnavailable, match="network error"):
        websearch.search("q")


def test_search_result_as_markdown_includes_citations():
    r = websearch.SearchResult(
        query="Q",
        content="Some answer.",
        citations=["https://a.com", "https://b.com"],
        model="perplexity/sonar-pro",
        latency_ms=123,
    )
    md = r.as_markdown()
    assert "**查询**：Q" in md
    assert "Some answer." in md
    assert "https://a.com" in md
    assert "https://b.com" in md


# ---------------- FactChecker gating (should_run) ----------------

@pytest.fixture
def bb_with_verdict(tmp_path):
    b = Blackboard(root=tmp_path)
    (tmp_path / "chapters").mkdir()
    b.write_text("chapters/ch001.md", "# t\n正文")
    return b


def _set_verdict(bb, **l13):
    bb.write_json(
        "chapters/ch001.verdict.json",
        {
            "overall_pass": False,
            "landmines": {"landmine_13": l13},
            "top_3_fixes": [],
        },
    )


def test_should_run_false_when_no_verdict(tmp_path):
    b = Blackboard(root=tmp_path)
    assert should_run(b, 1) is False


def test_should_run_false_when_l13_not_hit(bb_with_verdict):
    _set_verdict(bb_with_verdict, hit=False, evidence=None, severity=None)
    assert should_run(bb_with_verdict, 1) is False


def test_should_run_false_when_l13_low_severity(bb_with_verdict):
    _set_verdict(bb_with_verdict, hit=True, evidence="x", severity="low")
    assert should_run(bb_with_verdict, 1) is False


def test_should_run_true_on_moderate(bb_with_verdict):
    _set_verdict(bb_with_verdict, hit=True, evidence="某事", severity="moderate")
    assert should_run(bb_with_verdict, 1) is True


def test_should_run_true_on_medium(bb_with_verdict):
    """Evaluator actually uses 'medium' (not 'moderate') per _verdict_schema.py;
    the gating must accept it."""
    _set_verdict(bb_with_verdict, hit=True, evidence="某事", severity="medium")
    assert should_run(bb_with_verdict, 1) is True


def test_should_run_true_on_high(bb_with_verdict):
    _set_verdict(bb_with_verdict, hit=True, evidence="某事", severity="high")
    assert should_run(bb_with_verdict, 1) is True


def test_should_run_handles_malformed_verdict(tmp_path):
    b = Blackboard(root=tmp_path)
    (tmp_path / "chapters").mkdir()
    b.write_text("chapters/ch001.verdict.json", "this is not json {")
    assert should_run(b, 1) is False


# ---------------- FactChecker prompt building ----------------

@pytest.fixture
def seeded_bb(tmp_path):
    b = Blackboard(root=tmp_path)
    (tmp_path / "chapters").mkdir()
    (tmp_path / "fixes").mkdir()
    b.write_text("chapters/ch001.md", "# 第一章\n林家耀在汇丰楼下。")
    b.write_text("era.md", "1983 年香港 era 事实。")
    b.write_json(
        "chapters/ch001.verdict.json",
        {
            "overall_pass": False,
            "landmines": {
                "landmine_13": {
                    "hit": True,
                    "severity": "moderate",
                    "evidence": "1982 年 9 月 24 日，港元对美元暴跌到 9.6:1。",
                }
            },
            "top_3_fixes": [],
        },
    )
    return b


def test_fact_checker_prompt_includes_evidence(seeded_bb):
    sys, user, inputs = FactChecker()._build_prompts(seeded_bb, chapter=1)
    assert "事实核查员" in sys
    assert "landmine_13" in sys
    assert "1982 年" in user
    assert "9.6:1" in user
    assert "state/chapters/ch001.verdict.json" in inputs
    assert "state/era.md" in inputs


def test_fact_checker_prompt_sans_era(tmp_path):
    b = Blackboard(root=tmp_path)
    (tmp_path / "chapters").mkdir()
    b.write_text("chapters/ch001.md", "正文")
    b.write_json(
        "chapters/ch001.verdict.json",
        {
            "overall_pass": False,
            "landmines": {
                "landmine_13": {"hit": True, "severity": "high", "evidence": "x"}
            },
            "top_3_fixes": [],
        },
    )
    sys, user, inputs = FactChecker()._build_prompts(b, chapter=1)
    assert "state/era.md" not in inputs
    assert "无 era.md" in sys


# ---------------- FactChecker output handling ----------------

def test_handle_output_writes_no_claims_patch(seeded_bb):
    FactChecker()._handle_output(seeded_bb, '{"claims": []}', chapter=1)
    p = seeded_bb.read_text("fixes/ch001.fact-patch.md")
    assert "无需外部事实核查" in p or "本章纯虚构" in p


def test_handle_output_writes_unavailable_patch_when_no_api_key(seeded_bb, monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setattr(cfg, "PERPLEXITY_API_KEY", "", raising=False)
    claims_json = json.dumps({
        "claims": [
            {"snippet": "1982 年 9 月...", "assertion": "暴跌到 9.6:1", "query": "1983 港元暴跌"},
        ]
    }, ensure_ascii=False)
    FactChecker()._handle_output(seeded_bb, claims_json, chapter=1)
    p = seeded_bb.read_text("fixes/ch001.fact-patch.md")
    assert "联网核查不可用" in p
    assert "PERPLEXITY_API_KEY" in p
    assert "1983 港元暴跌" in p


def test_handle_output_parses_fenced_json(seeded_bb):
    fenced = "```json\n{\"claims\": []}\n```"
    FactChecker()._handle_output(seeded_bb, fenced, chapter=1)
    p = seeded_bb.read_text("fixes/ch001.fact-patch.md")
    assert "FactChecker" in p


def test_handle_output_parse_error_branch(seeded_bb):
    FactChecker()._handle_output(seeded_bb, "{this is not json", chapter=1)
    p = seeded_bb.read_text("fixes/ch001.fact-patch.md")
    assert "Claims 抽取失败" in p or "非预期 JSON" in p
    assert "```" in p  # raw excerpt block


def test_handle_output_runs_websearch_when_available(seeded_bb, monkeypatch, tmp_path):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "fake-key")
    monkeypatch.setattr(websearch, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(websearch, "WEBSEARCH_LOG_PATH", tmp_path / "ws.jsonl")

    called_queries: list[str] = []

    def fake_search(query, **kwargs):
        called_queries.append(query)
        return websearch.SearchResult(
            query=query,
            content=f"Pretend fact answer for: {query}",
            citations=["https://src1.com", "https://src2.com"],
            model="perplexity/sonar-pro",
            latency_ms=42,
        )

    monkeypatch.setattr(websearch, "search", fake_search)
    # Make FactChecker use our fake search — it imports from the module
    from src.auditors import fact_checker as fc_module
    monkeypatch.setattr(fc_module.websearch, "search", fake_search)
    monkeypatch.setattr(fc_module.websearch, "is_available", lambda: True)

    claims_json = json.dumps({
        "claims": [
            {"snippet": "港元暴跌", "assertion": "9.6:1", "query": "1983 港元暴跌汇率"},
            {"snippet": "廉政公署", "assertion": "1974 成立", "query": "ICAC 成立时间"},
        ]
    }, ensure_ascii=False)
    FactChecker()._handle_output(seeded_bb, claims_json, chapter=1)

    assert called_queries == [
        "1983 港元暴跌汇率",
        "ICAC 成立时间",
    ]
    p = seeded_bb.read_text("fixes/ch001.fact-patch.md")
    assert "核查断言数**：2" in p
    assert "1983 港元暴跌汇率" in p
    assert "ICAC 成立时间" in p
    assert "https://src1.com" in p
    assert "Pretend fact answer" in p


def test_handle_output_caps_claims_at_3(seeded_bb, monkeypatch, tmp_path):
    """Skill #20: single-shot per chapter, max 3 claims."""
    monkeypatch.setenv("PERPLEXITY_API_KEY", "fake-key")
    monkeypatch.setattr(websearch, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(websearch, "WEBSEARCH_LOG_PATH", tmp_path / "ws.jsonl")

    called: list[str] = []
    def fake_search(query, **kw):
        called.append(query)
        return websearch.SearchResult(query=query, content="x", citations=[], model="m")

    from src.auditors import fact_checker as fc_module
    monkeypatch.setattr(fc_module.websearch, "search", fake_search)
    monkeypatch.setattr(fc_module.websearch, "is_available", lambda: True)

    many = json.dumps({
        "claims": [
            {"snippet": f"s{i}", "assertion": f"a{i}", "query": f"q{i}"}
            for i in range(5)
        ]
    })
    FactChecker()._handle_output(seeded_bb, many, chapter=1)
    # Only 3 queries should have fired
    assert called == ["q0", "q1", "q2"]


# ---------------- Render helpers (pure functions) ----------------

def test_render_no_claims_is_reassuring():
    out = _render_no_claims(7)
    assert "第 7 章" in out
    assert "无需外部事实核查" in out


def test_render_unavailable_preserves_claims_for_manual_check():
    out = _render_unavailable(3, [
        {"snippet": "港元", "assertion": "暴跌", "query": "1983 HK"}
    ])
    assert "联网核查不可用" in out
    assert "PERPLEXITY_API_KEY" in out
    assert "1983 HK" in out


def test_render_patch_marks_failed_items():
    out = _render_patch(2, [
        {"snippet": "a", "assertion": "b", "query": "q1",
         "search_content": "ok", "citations": [], "cached": False, "latency_ms": 100, "error": None},
        {"snippet": "c", "assertion": "d", "query": "q2",
         "search_content": "", "citations": [], "cached": False, "latency_ms": 0, "error": "timeout"},
    ])
    assert "断言 1" in out
    assert "断言 2" in out
    assert "❌ 核查失败" in out
    assert "timeout" in out


# ---------------- Pipeline integration ----------------

def test_pipeline_skips_fact_checker_when_no_l13(tmp_path, monkeypatch):
    """If the verdict has no landmine_13 hit, FactChecker MUST NOT run
    even if Perplexity is configured."""
    from src import pipeline
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {
        "genre": "g", "era": "e", "tone": "t",
        "prohibited_styles": ["x"], "author_persona_hints": ["h"],
    })
    b.write_yaml("characters.yaml", {"protagonist": {"name": "A"}, "supporting": []})
    b.write_text("timeline.yaml", "2024: []\n")
    b.write_text("era.md", "era")
    b.write_text("writing-style-extra.md", "style")
    b.write_text("iron-laws-extra.md", "## iron_law_extra_1\nfoo\n")
    b.write_json("outline.json", {
        "chapters": [{"ch": 1, "title": "t", "beats": ["b"]}]
    })
    b.write_json("progress.json", {"current_chapter": 0, "completed_chapters": []})
    (tmp_path / "chapters").mkdir()
    (tmp_path / "summaries").mkdir()
    (tmp_path / "fixes").mkdir()

    monkeypatch.setenv("PERPLEXITY_API_KEY", "fake-key")

    called: list[str] = []
    def fake_chat(*, agent_name, **_):
        called.append(agent_name)
        if agent_name == "planner":
            return json.dumps({
                "ch": 1, "title": "t", "chapter_type": "过渡",
                "opening_hook": "o",
                "scenes": [{"scene_id": 1, "cast": ["A"], "advances": ["地位"]}],
                "closing_hook": "c", "landmines_to_avoid": [], "writing_self_check": {},
            })
        if agent_name == "evaluator":
            # all-clean verdict: landmine_13.hit = false
            return json.dumps({
                "overall_pass": True,
                "landmines": {f"landmine_{i}": {"hit": False, "evidence": None, "severity": None}
                              for i in range(1, 19)},
                "top_3_fixes": [],
            })
        return "stub"
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)

    status = pipeline.run_chapter(b, 1)
    audit = status["stages"]["audit_fanout"]["results"]
    assert "ai_slop_guard" in audit
    assert "character_guard" in audit
    assert "fact_checker" not in audit


def test_pipeline_runs_fact_checker_on_l13_moderate(tmp_path, monkeypatch):
    """When verdict has landmine_13.moderate, FactChecker must join the fan-out."""
    from src import pipeline
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {
        "genre": "g", "era": "e", "tone": "t",
        "prohibited_styles": ["x"], "author_persona_hints": ["h"],
    })
    b.write_yaml("characters.yaml", {"protagonist": {"name": "A"}, "supporting": []})
    b.write_text("timeline.yaml", "2024: []\n")
    b.write_text("era.md", "era")
    b.write_text("writing-style-extra.md", "style")
    b.write_text("iron-laws-extra.md", "## iron_law_extra_1\nfoo\n")
    b.write_json("outline.json", {
        "chapters": [{"ch": 1, "title": "t", "beats": ["b"]}]
    })
    b.write_json("progress.json", {"current_chapter": 0, "completed_chapters": []})
    (tmp_path / "chapters").mkdir()
    (tmp_path / "summaries").mkdir()
    (tmp_path / "fixes").mkdir()

    monkeypatch.setenv("PERPLEXITY_API_KEY", "fake-key")

    # Stub websearch so FactChecker's network path doesn't actually fire
    from src.auditors import fact_checker as fc_module
    monkeypatch.setattr(
        fc_module.websearch, "search",
        lambda query, **kw: websearch.SearchResult(
            query=query, content="stub", citations=[], model="m",
        ),
    )
    monkeypatch.setattr(fc_module.websearch, "is_available", lambda: True)

    def fake_chat(*, agent_name, **_):
        if agent_name == "planner":
            return json.dumps({
                "ch": 1, "title": "t", "chapter_type": "过渡",
                "opening_hook": "o",
                "scenes": [{"scene_id": 1, "cast": ["A"], "advances": ["地位"]}],
                "closing_hook": "c", "landmines_to_avoid": [], "writing_self_check": {},
            })
        if agent_name == "evaluator":
            lm = {f"landmine_{i}": {"hit": False, "evidence": None, "severity": None}
                  for i in range(1, 19)}
            lm["landmine_13"] = {
                "hit": True, "severity": "medium",
                "evidence": "1982年9月 港元暴跌到 9.6:1，主角去汇丰楼下",
            }
            return json.dumps({
                "overall_pass": True,  # evaluator-level pass; FactChecker is advisory
                "landmines": lm,
                "top_3_fixes": [],
            })
        if agent_name == "fact_checker":
            return json.dumps({
                "claims": [
                    {"snippet": "1982年9月 港元暴跌", "assertion": "暴跌",
                     "query": "1982 年 9 月 港元暴跌"},
                ]
            })
        return "stub"
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)

    status = pipeline.run_chapter(b, 1)
    audit = status["stages"]["audit_fanout"]["results"]
    assert "fact_checker" in audit
    assert audit["fact_checker"] == "ok"
    assert b.exists("fixes/ch001.fact-patch.md")
    patch_text = b.read_text("fixes/ch001.fact-patch.md")
    assert "核查断言数" in patch_text
