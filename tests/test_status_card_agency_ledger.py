"""Tests for StatusCardUpdater Agency Ledger section (P1 修复).

LLM-free — only exercises StatusCardUpdater._build_prompts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.blackboard import Blackboard
from src.agents.status_card_updater import StatusCardUpdater


def _seed(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "末世契约", "era": "X"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "陈牧"}})
    (tmp_path / "chapters").mkdir(exist_ok=True)
    b.write_text("chapters/ch005.md", "# 第五章\n\n陈牧在便利店。\n" * 10)
    return b


# ---------------- 1. system prompt demands Agency Ledger ----------------

def test_status_card_prompt_demands_agency_ledger(tmp_path):
    b = _seed(tmp_path)
    system, user, _ = StatusCardUpdater()._build_prompts(b, chapter=5)

    # Rule 6b in system
    assert "主角主动账本" in system
    assert "Agency Ledger" in system
    # The 5 mandatory rows must be enumerated
    assert "当前最强的牌" in system
    assert "上次主动设局" in system
    assert "上次黑色幽默时刻" in system
    assert "上次爽感兑现" in system
    assert "当前 anchor 缺口" in system
    # Definitions for the four anchor types
    assert "主动设局" in system
    assert "爽感兑现" in system
    assert "黑色幽默" in system

    # The skeleton in user prompt also has the section
    assert "主角主动账本" in user


# ---------------- 2. system prompt warns against fabrication ----------------

def test_status_card_prompt_warns_against_fabrication(tmp_path):
    b = _seed(tmp_path)
    system, _, _ = StatusCardUpdater()._build_prompts(b, chapter=5)
    assert "基于历史正文计算" in system
    assert "不允许编造" in system
