"""Lock in landmine_19 (因果颠倒归因／记错功劳) is wired end-to-end in Evaluator's
system prompt + rules/landmines.md is up to date.

Why: landmine_19 guards against a specific kind of narrative bug found in ch002 of
user project book-e3f4fc9b (老刘 送情报救了陈默，但陈默反过来说"我救了你一命"——
方向性归因错误)。If evaluator.py 或 rules/landmines.md 被人改回 "18"，
the LLM 会按 18 条的 schema 输出 JSON、跳过第 19 条，这条 landmine 就失效了。
"""
from __future__ import annotations

import re
from pathlib import Path

from src.blackboard import Blackboard
from src.agents.evaluator import Evaluator


REPO_ROOT = Path(__file__).resolve().parent.parent
LANDMINES_PATH = REPO_ROOT / "rules" / "landmines.md"


def _seed_minimum(tmp_path: Path) -> Blackboard:
    """Seed a Blackboard with the minimum files Evaluator._build_prompts requires.

    Mirrors tests/test_evaluator_reads_bookkeeping.py::_seed_minimum so that if
    the Evaluator's reader contract changes, both test suites move in lockstep.
    """
    b = Blackboard(root=tmp_path)
    b.write_yaml(
        "setting.yaml",
        {"genre": "港综同人", "era": "1983"},
    )
    b.write_yaml(
        "characters.yaml",
        {"protagonist": {"name": "林家耀"}, "supporting": []},
    )
    b.write_text("timeline.yaml", "1983: []\n")
    b.write_text("iron-laws-extra.md", "## iron_law_extra_1 洋人不跪舔\n")
    (tmp_path / "chapters").mkdir(exist_ok=True)
    b.write_text(
        "chapters/ch001.md",
        "# 第一章\n林家耀走出茶餐厅，心里想着那笔黑金交易。\n",
    )
    return b


# ---------------- Case 1: rules/landmines.md declares 19 items ----------------


def test_landmines_file_declares_19_items():
    """The header line + per-section headings must both reflect 19 landmines.

    A stale header ("18 个写作雷点") combined with 19 section bodies would mean
    the file silently contradicts itself — the LLM reads the header first and
    anchors its schema to the smaller number.
    """
    text = LANDMINES_PATH.read_text(encoding="utf-8")

    # Header must advertise 19
    assert "19 个" in text or "19 Landmines" in text, (
        "rules/landmines.md header still claims 18 landmines — update the "
        "'# N 个写作雷点 (The N Landmines)' line to 19."
    )

    # Count each '## landmine_N: ...' heading; must be exactly [1..19].
    ids = [int(m) for m in re.findall(r"## landmine_(\d+):", text)]
    assert ids == list(range(1, 20)), (
        f"Expected landmine sections 1..19 in order, got {ids}. "
        "Check for missing, duplicated, or renumbered landmines."
    )


# ---------------- Case 2: landmine_19 definition is substantive ----------------


def test_landmine_19_definition_present():
    """Not just the heading — the section must carry the title keyword so
    Evaluator/Fixer readers can distinguish it from the other 18 mines.
    """
    text = LANDMINES_PATH.read_text(encoding="utf-8")

    assert "landmine_19" in text
    # Either of the canonical title phrases is acceptable (Chinese titles vary
    # by author style; both map to the same concept):
    assert ("因果颠倒归因" in text) or ("记错功劳" in text), (
        "landmine_19 section should carry either '因果颠倒归因' or '记错功劳' "
        "as its title keyword — otherwise downstream agents have no anchor to "
        "reference this specific mine."
    )


# ---------------- Case 3: Evaluator prompt embeds landmine_19 end-to-end -------


def test_evaluator_prompt_embeds_landmine_19(tmp_path):
    """End-to-end: the Evaluator prompt must (a) carry the full
    landmine_19 definition from the rules file (now in the user prompt's
    『19 个雷点完整定义』 block) and (b) instruct the LLM to include
    landmine_19 in its JSON output (in the system prompt's format directive
    and the user prompt's schema).

    Regression guard: if evaluator.py's hardcoded count reverts to 18, or if
    the rules file loses landmine_19, the LLM will omit landmine_19 in its
    output and _verdict_schema will silently default it to hit=false.
    """
    b = _seed_minimum(tmp_path)

    system, user, _inputs = Evaluator()._build_prompts(b, chapter=1)

    # Full landmine_19 definition is stitched into the user prompt via the
    # '# 19 个雷点完整定义' block (system prompt was slimmed in 2026-05-15
    # decoupling pass; the bulky rules text now lives in user prompt).
    assert "landmine_19" in user, (
        "Evaluator prompt does not contain 'landmine_19' — either the "
        "rules file wasn't read or landmine_19 has been deleted from it."
    )

    # JSON-schema directive: total count must be 19, not 18. The system
    # prompt's format section keeps a brief "19 个 landmine_N" mention; the
    # user prompt's schema explicitly enumerates landmine_1..landmine_19.
    assert "19 个 landmine_N" in system, (
        "Evaluator system prompt's JSON-schema directive still says a count "
        "other than '19 个 landmine_N' — update the hardcoded count in "
        "evaluator.py's system-prompt string."
    )
    assert "landmine_19" in user, (
        "Evaluator user prompt's JSON schema must enumerate up to landmine_19."
    )

    # Anti-regression: no lingering '18 个 landmine_N' in either prompt.
    assert "18 个 landmine_N" not in system
    assert "18 个 landmine_N" not in user

    # Title keyword from the rules file must survive the rule-text concat
    # (now embedded in user prompt).
    assert ("因果颠倒归因" in user) or ("记错功劳" in user), (
        "landmine_19's title keyword is missing from the assembled "
        "prompt — confirm _read_rule('landmines.md') returns the updated "
        "file contents."
    )
