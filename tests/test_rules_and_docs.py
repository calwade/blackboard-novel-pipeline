"""Tests for rules + AGENTS.md consistency (the "documentation is code" contract)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src import config


# -------- rules/00-information-priority.md (B-1) --------

def test_information_priority_rule_exists():
    p = config.RULES_DIR / "00-information-priority.md"
    assert p.exists(), f"missing {p}"


def test_information_priority_rule_has_key_sections():
    text = (config.RULES_DIR / "00-information-priority.md").read_text(encoding="utf-8")
    for needle in (
        "信息源优先级",
        "优先级",  # the priority table must be called out
        "state/current_status_card.md",
        "state/chapters/",
        "outline.json",
        "rules/24-iron-laws.md",
    ):
        assert needle in text, f"missing: {needle}"


def test_information_priority_has_arbitration_rules():
    text = (config.RULES_DIR / "00-information-priority.md").read_text(encoding="utf-8")
    # R1..R5 arbitration rules should all be present
    for rule_id in ("R1", "R2", "R3", "R4", "R5"):
        assert f"{rule_id} ·" in text or f"{rule_id}\n" in text or f"{rule_id} " in text


# -------- AGENTS.md inventory must be in sync with code --------

def test_agents_md_lists_all_new_agents():
    text = (config.PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    # All bookkeeping agents mentioned in state-map + agent-roster
    for agent_marker in (
        "StatusCardUpdater",
        "HookKeeper",
        "ResourceLedger",
    ):
        assert agent_marker in text, f"AGENTS.md missing {agent_marker}"


def test_agents_md_lists_all_new_state_files():
    text = (config.PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for filepath in (
        "state/current_status_card.md",
        "state/pending_hooks.md",
        "state/resource_schema.yaml",
        "state/resource_ledger.md",
    ):
        assert filepath in text, f"AGENTS.md missing {filepath}"


def test_agents_md_mentions_optional_resource_schema():
    """The state map should call out that resource_schema.yaml is optional."""
    text = (config.PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    # Look for optional/可选 near resource_schema
    idx = text.find("state/resource_schema.yaml")
    assert idx >= 0
    window = text[idx:idx + 300]
    assert "可选" in window or "optional" in window.lower()


# -------- setting lint still passes on all real settings --------

@pytest.mark.parametrize(
    "setting_name",
    ["gangster-hk-1983", "xianxia-ascension", "urban-romance-contemporary"],
)
def test_real_settings_pass_lint(setting_name):
    from src.tools.setting_lint import lint_setting
    r = lint_setting(config.PROJECT_ROOT / "settings" / setting_name)
    assert r.n_errors == 0, f"{setting_name} lint errors: {[i.message for i in r.issues if i.level == 'ERROR']}"
