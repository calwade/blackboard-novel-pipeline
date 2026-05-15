"""Tests for agent ↔ rules alignment (Oracle audit follow-up to D5+).

Background: After commit 156ee99 split rules/ into 6 single-responsibility
files, an audit checked each agent's `_read_rule()` calls against what each
rule file actually authorises. 13/15 agent-rule pairs were correct; 3 issues
remained:

  1. Fixer didn't read rules/ai-rhythm-taboos.md, so when fixing landmine_18
     hits (e.g., "破折号 42 次") it had no target threshold (≤8) to aim at.
     Generator already reads it; Fixer must be symmetric.
  2. Fixer's system prompt mentions rules/00-information-priority.md but
     inputs_read didn't list it — Prompt Inspector couldn't show the link.
     Fix is observability-only (don't actually load file into prompt; would
     waste tokens for a one-line citation).
  3. AISlopGuard's inline AI_SLOP_CRITERIA partly overlaps with landmine_18
     and iron_law_24. This is intentional (different detail levels for
     different consumers) but unlabeled. Add an architecture-decision comment
     above AI_SLOP_CRITERIA + reverse pointer in landmines.md → ai_slop_guard.py.

These tests lock in those three fixes against future regression.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import config
from src.blackboard import Blackboard
from src.agents.fixer import Fixer


@pytest.fixture
def fixer_bb(tmp_path: Path) -> Blackboard:
    """Minimal Blackboard for Fixer._build_prompts.
    Mirrors tests/test_writing_iron_laws_decoupling.py::fixer_bb."""
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "test"})
    b.write_text("writing-style-extra.md", "test style extras")
    (tmp_path / "chapters").mkdir(exist_ok=True)
    b.write_text("chapters/ch001.md", "# 第一章\n\n正文。")
    b.write_json(
        "chapters/ch001.verdict.json",
        {"top_3_fixes": [], "landmines": {}},
    )
    return b


# ---------- Fix 1: Fixer reads ai-rhythm-taboos.md ----------

def test_fixer_reads_ai_rhythm_taboos(fixer_bb):
    """Fixer's system prompt must include the AI-rhythm 4-threshold table.
    When Evaluator hands Fixer a landmine_18 hit (e.g., '破折号 42 次'),
    Fixer needs to know the target value (≤8) to aim at — without this,
    Fixer is guessing."""
    system, _, inputs_read = Fixer()._build_prompts(fixer_bb, chapter=1)

    # 1. Section header announcing the threshold table is present
    assert "AI 节奏阈值" in system, (
        "Fixer system prompt missing 'AI 节奏阈值' header — Fixer cannot fix "
        "landmine_18 hits surgically without knowing target thresholds"
    )
    # 2. Content from ai-rhythm-taboos.md is actually inlined.
    #    Verify with a hard cap value that's unique to the taboos file.
    assert "≤ 8" in system, (
        "Fixer system prompt missing '≤ 8' (emdash hard cap) — "
        "ai-rhythm-taboos.md content not actually loaded"
    )
    assert "破折号" in system, (
        "Fixer system prompt missing '破折号' — ai-rhythm-taboos.md content "
        "not actually loaded"
    )
    # 3. inputs_read advertises the dependency
    assert "rules/ai-rhythm-taboos.md" in inputs_read, (
        "Fixer must advertise reading rules/ai-rhythm-taboos.md in inputs_read "
        "for Prompt Inspector transparency"
    )


def test_fixer_ai_rhythm_taboos_at_tail_of_system_prompt(fixer_bb):
    """Mirror Generator's tail-placement strategy (commit 1cf7338): the AI
    rhythm thresholds are 'final conflict arbitration' content and must sit
    after style_extra (which ends the writing-style stack) so recency bias
    favors them. We don't require >75% like Generator — Fixer prompt is
    shorter overall — but the taboos must come AFTER the style stack."""
    system, _, _ = Fixer()._build_prompts(fixer_bb, chapter=1)
    pos_style_extra = system.find("题材特有风格")
    pos_taboo_header = system.find("AI 节奏阈值")
    assert 0 < pos_style_extra < pos_taboo_header, (
        f"AI 节奏阈值 must come AFTER 题材特有风格 in Fixer system prompt "
        f"(positions: style_extra={pos_style_extra}, taboo={pos_taboo_header}). "
        f"Mirror Generator's tail-placement: thresholds beat style by recency."
    )


# ---------- Fix 2: Fixer inputs_read declares 00-information-priority.md ----------

def test_fixer_inputs_read_includes_information_priority(fixer_bb):
    """Fixer's system prompt cites `rules/00-information-priority.md R1` in
    its conflict-arbitration clause (when top_3_fixes conflicts with
    current_status_card.md). The file is intentionally NOT loaded into the
    prompt (waste of tokens for a one-line citation) but inputs_read must
    declare the dependency so Prompt Inspector shows the link."""
    system, _, inputs_read = Fixer()._build_prompts(fixer_bb, chapter=1)

    # System prompt must still cite the rule (citation is the whole point)
    assert "00-information-priority.md" in system, (
        "Fixer system prompt should cite rules/00-information-priority.md "
        "in the conflict-arbitration clause"
    )
    # inputs_read must declare it for Inspector observability
    assert "rules/00-information-priority.md" in inputs_read, (
        "Fixer cites rules/00-information-priority.md in system prompt but "
        "doesn't declare it in inputs_read — Prompt Inspector shows broken link"
    )


# ---------- Fix 3a: landmine_18 has reverse pointer to AISlopGuard ----------

def test_landmine_18_has_aislopguard_pointer():
    """landmines.md landmine_18 (AI 味) must point readers to
    src/auditors/ai_slop_guard.py's AI_SLOP_CRITERIA — that's where the
    detailed criteria set with thresholds + high-fatigue-word blacklist
    lives. Without this pointer, future maintainers won't know about the
    intentional dual-layer architecture (rules = short reference for
    Evaluator; AI_SLOP_CRITERIA = detailed audit checklist for AISlopGuard)."""
    text = (config.RULES_DIR / "landmines.md").read_text(encoding="utf-8")
    # Locate the landmine_18 block (between '## landmine_18:' and '## landmine_19:')
    start = text.find("## landmine_18:")
    end = text.find("## landmine_19:")
    assert 0 < start < end, "landmine_18 / landmine_19 block markers not found"
    block = text[start:end]
    assert "AISlopGuard" in block, (
        "landmines.md landmine_18 missing 'AISlopGuard' reference — "
        "readers won't find the detailed AI-slop criteria in src/auditors/"
    )
    assert "AI_SLOP_CRITERIA" in block, (
        "landmines.md landmine_18 missing 'AI_SLOP_CRITERIA' symbol name — "
        "readers can't grep to the actual code"
    )


# ---------- Fix 3b: AISlopGuard has architecture-decision comment ----------

def test_aislopguard_has_inline_criteria_with_explanation_comment():
    """ai_slop_guard.py's AI_SLOP_CRITERIA constant must have an
    architecture-decision comment immediately above it explaining why it
    duplicates parts of landmines.md / iron-laws.md (intentional dual-layer
    architecture). Without this comment, future reviewers will likely try
    to 'deduplicate' by replacing AI_SLOP_CRITERIA with a `_read_rule()`
    call — breaking the Lesson-4 independent-auditor design.

    Anti-regression: if any reviewer deletes the comment, this test fails
    and forces them to read the rationale before stripping it."""
    src_path = config.PROJECT_ROOT / "src" / "auditors" / "ai_slop_guard.py"
    text = src_path.read_text(encoding="utf-8")

    # Locate AI_SLOP_CRITERIA assignment
    idx = text.find("AI_SLOP_CRITERIA = ")
    assert idx > 0, "AI_SLOP_CRITERIA constant not found in ai_slop_guard.py"

    # Look at the ~20 lines preceding the assignment for the rationale comment
    preceding = text[:idx]
    last_lines = "\n".join(preceding.splitlines()[-20:])

    # The comment must explain the dual-layer / intentional choice with at
    # least one of these key phrases (allowing future wording tweaks but
    # forcing reviewer to keep the architectural rationale intact).
    rationale_phrases = ["故意为之", "双层架构", "独立审计员"]
    matches = [p for p in rationale_phrases if p in last_lines]
    assert matches, (
        f"AI_SLOP_CRITERIA missing architecture-decision comment immediately above. "
        f"Expected at least one of {rationale_phrases} in the preceding 20 lines. "
        f"Got:\n{last_lines}\n\n"
        f"This comment exists to prevent future 'deduplication' refactors — do not delete."
    )
