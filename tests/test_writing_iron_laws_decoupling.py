"""Tests for the writing-iron-laws.md decoupling (Oracle audit A4).

Background: Generator's system prompt used to embed a 7-question "动笔前自问 7 问"
section that was a paraphrased restatement of 7 iron laws (7/8/9/13/24/25/27).
Generator did not read iron-laws.md, so any change to iron-laws.md silently
drifted from Generator's prompt — a rule-drift source.

Fix: extract those 7 laws verbatim into rules/writing-iron-laws.md; both
Generator and Fixer read it; Evaluator continues reading the full iron-laws.md.

These tests lock in:
  1. The new file exists and lists exactly the expected 7 iron law IDs in order.
  2. Each entry's content matches iron-laws.md byte-for-byte (no semantic drift).
  3. Generator's system prompt loads + advertises the new file.
  4. The old "动笔前自问 7 问" section is gone (anti-regression).
  5. Fixer also loads + advertises the new file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src import config
from src.blackboard import Blackboard
from src.agents.generator import Generator
from src.agents.fixer import Fixer


EXPECTED_IDS = [7, 8, 9, 13, 24, 25, 27]


def _extract_iron_law(filepath: Path, n: int) -> str:
    """Return the full block for `## iron_law_<n>:` up to (but not including)
    the next `## ` heading or EOF. The returned text starts with the heading
    line and ends with the last non-blank line of the block (no trailing newlines).
    """
    text = filepath.read_text(encoding="utf-8")
    # Find heading
    pattern = re.compile(rf"^## iron_law_{n}:.*$", re.MULTILINE)
    m = pattern.search(text)
    if not m:
        raise AssertionError(f"iron_law_{n} heading not found in {filepath}")
    start = m.start()
    # Find next ## heading
    next_m = re.search(r"^## ", text[m.end():], re.MULTILINE)
    end = m.end() + next_m.start() if next_m else len(text)
    return text[start:end].rstrip()


# ---------- file existence + structure ----------

def test_writing_iron_laws_file_exists_and_has_7_laws():
    p = config.RULES_DIR / "writing-iron-laws.md"
    assert p.exists(), "rules/writing-iron-laws.md must exist as Generator/Fixer's iron-law subset"
    text = p.read_text(encoding="utf-8")
    ids = [int(x) for x in re.findall(r"^## iron_law_(\d+):", text, re.MULTILINE)]
    assert ids == EXPECTED_IDS, (
        f"writing-iron-laws.md iron_law IDs are {ids}, expected {EXPECTED_IDS} in order"
    )


def test_writing_iron_laws_content_matches_iron_laws_md():
    """Each of the 7 entries must match iron-laws.md byte-for-byte.
    This is the anti-drift guarantee: change one side, the other must follow."""
    src = config.RULES_DIR / "iron-laws.md"
    dst = config.RULES_DIR / "writing-iron-laws.md"
    for n in EXPECTED_IDS:
        src_block = _extract_iron_law(src, n)
        dst_block = _extract_iron_law(dst, n)
        assert src_block == dst_block, (
            f"iron_law_{n} block in writing-iron-laws.md drifted from iron-laws.md.\n"
            f"--- iron-laws.md ---\n{src_block}\n"
            f"--- writing-iron-laws.md ---\n{dst_block}\n"
            f"Re-copy the block from iron-laws.md to keep them in sync."
        )


# ---------- Generator integration ----------

@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "test", "era": "2026"})
    b.write_yaml(
        "characters.yaml",
        {"protagonist": {"name": "陈默"}, "supporting": []},
    )
    b.write_text("era.md", "test era facts")
    b.write_text("writing-style-extra.md", "test style extras")
    (tmp_path / "chapters").mkdir(exist_ok=True)
    b.write_json(
        "chapters/ch001.plan.json",
        {
            "ch": 1,
            "title": "t",
            "scenes": [{"scene_id": 1, "cast": ["陈默"]}],
            "chapter_type": "战斗",
        },
    )
    return b


def test_generator_system_prompt_includes_writing_iron_laws(bb):
    system, _, _ = Generator()._build_prompts(bb, chapter=1)
    assert "创作铁律" in system, "Generator system prompt missing '创作铁律' header"
    # Pick two distinctive landmarks from the iron laws subset
    assert "iron_law_8" in system, "Generator system prompt missing iron_law_8 marker"
    assert "反派不能降智" in system, "Generator system prompt missing iron_law_8 content"
    assert "iron_law_25" in system, "Generator system prompt missing iron_law_25 marker"
    assert "反派信息越界禁令" in system, "Generator system prompt missing iron_law_25 content"


def test_generator_no_longer_has_seven_questions(bb):
    """Anti-regression: the paraphrased '动笔前自问 7 问' section was the
    rule-drift source (it restated iron laws in different words). Now that
    we read writing-iron-laws.md verbatim, the old paraphrase must be gone."""
    system, _, _ = Generator()._build_prompts(bb, chapter=1)
    assert "动笔前自问 7 问" not in system, (
        "Generator still has the old '动笔前自问 7 问' paraphrase. "
        "It was replaced by reading rules/writing-iron-laws.md verbatim — "
        "delete the paraphrase to avoid two divergent copies of iron laws."
    )


def test_generator_inputs_read_includes_writing_iron_laws(bb):
    _, _, inputs = Generator()._build_prompts(bb, chapter=1)
    assert "rules/writing-iron-laws.md" in inputs, (
        "Generator must advertise reading rules/writing-iron-laws.md in inputs_read "
        "for Prompt Inspector transparency"
    )


# ---------- Fixer integration ----------

@pytest.fixture
def fixer_bb(tmp_path: Path) -> Blackboard:
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


def test_fixer_system_prompt_includes_writing_iron_laws(fixer_bb):
    system, _, _ = Fixer()._build_prompts(fixer_bb, chapter=1)
    assert "创作铁律" in system, "Fixer system prompt missing '创作铁律' header"
    assert "iron_law_8" in system or "反派不能降智" in system, (
        "Fixer system prompt missing iron_law_8 content"
    )
    assert "iron_law_25" in system or "反派信息越界禁令" in system, (
        "Fixer system prompt missing iron_law_25 content"
    )


def test_fixer_inputs_read_includes_writing_iron_laws(fixer_bb):
    _, _, inputs = Fixer()._build_prompts(fixer_bb, chapter=1)
    assert "rules/writing-iron-laws.md" in inputs, (
        "Fixer must advertise reading rules/writing-iron-laws.md in inputs_read"
    )
