"""Tests for web + docs Pages synchronization.

Ensures the Flask API surface and the static Pages tree both expose
the new bookkeeping artifacts and info-priority rule added in C-23..C-25
and B-1.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import config


# ---- Flask API: /api/state now reports bookkeeping presence ----

@pytest.fixture
def client():
    from web import app as web_app
    return web_app.app.test_client()


def test_api_state_returns_bookkeeping_key(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    data = r.get_json()
    assert "bookkeeping" in data
    bk = data["bookkeeping"]
    # All four keys must be present even when the files don't exist
    for key in ("has_status_card", "has_pending_hooks",
                "has_resource_schema", "has_resource_ledger"):
        assert key in bk
        assert isinstance(bk[key], bool)


def test_api_file_serves_new_info_priority_rule(client):
    r = client.get("/api/file?path=rules/00-information-priority.md")
    assert r.status_code == 200
    data = r.get_json()
    assert data["path"] == "rules/00-information-priority.md"
    assert "信息源优先级" in data["content"]
    assert data["size"] > 0


def test_api_file_rejects_path_traversal(client):
    r = client.get("/api/file?path=../etc/passwd")
    assert r.status_code == 403


def test_api_file_rejects_out_of_sandbox(client):
    r = client.get("/api/file?path=web/app.py")
    assert r.status_code == 403


# ---- GitHub Pages static site sync ----

def test_docs_rules_has_info_priority_copy():
    docs_rule = config.PROJECT_ROOT / "docs" / "rules" / "00-information-priority.md"
    root_rule = config.RULES_DIR / "00-information-priority.md"
    assert docs_rule.exists(), "docs/rules/ must include 00-information-priority.md for Pages"
    # Content must match repo's source of truth (prevents silent drift)
    assert docs_rule.read_text(encoding="utf-8") == root_rule.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "rule_name",
    ["24-iron-laws.md", "18-landmines.md", "writing-style-core.md", "00-information-priority.md"],
)
def test_docs_rules_in_sync_with_source(rule_name):
    """Every rule file shipped to Pages must match the source in rules/."""
    src = config.RULES_DIR / rule_name
    dst = config.PROJECT_ROOT / "docs" / "rules" / rule_name
    assert src.read_text(encoding="utf-8") == dst.read_text(encoding="utf-8"), (
        f"docs/rules/{rule_name} drifted from rules/{rule_name} — re-copy before committing"
    )


def test_docs_main_js_declares_new_agents():
    """Static pages UI must know about the 3 new bookkeeping agents
    so Prompt Inspector colors them correctly."""
    text = (config.PROJECT_ROOT / "docs" / "main.js").read_text(encoding="utf-8")
    for agent_name in ("status_card_updater", "hook_keeper", "resource_ledger"):
        assert agent_name in text, f"docs/main.js missing AGENT_LABEL entry for {agent_name}"


def test_docs_main_js_tree_references_bookkeeping_section():
    """Static pages tree must render the new 'bookkeeping/' section."""
    text = (config.PROJECT_ROOT / "docs" / "main.js").read_text(encoding="utf-8")
    assert "current_status_card.md" in text
    assert "pending_hooks.md" in text
    assert "resource_schema.yaml" in text
    assert "resource_ledger.md" in text
    assert "00-information-priority.md" in text


def test_web_main_js_declares_new_agents():
    text = (config.PROJECT_ROOT / "web" / "static" / "main.js").read_text(encoding="utf-8")
    for agent_name in ("status_card_updater", "hook_keeper", "resource_ledger"):
        assert agent_name in text, f"web/static/main.js missing AGENT_LABEL/COLOR for {agent_name}"


def test_web_main_js_tree_references_bookkeeping_section():
    text = (config.PROJECT_ROOT / "web" / "static" / "main.js").read_text(encoding="utf-8")
    assert "current_status_card.md" in text
    assert "pending_hooks.md" in text
    assert "resource_schema.yaml" in text
    assert "resource_ledger.md" in text
    assert "00-information-priority.md" in text


# ---- demo_snapshot sync: each of the two gangster/xianxia snapshots has
# representative bookkeeping files so Pages viewers see them rendered ----

@pytest.mark.parametrize(
    "snapshot_dir",
    [
        "docs/demo_snapshot",
        "docs/demo_snapshot_xianxia",
        "demo_snapshot",
        "demo_snapshot_xianxia",
    ],
)
def test_snapshot_has_bookkeeping_sample(snapshot_dir):
    root = config.PROJECT_ROOT / snapshot_dir
    for f in (
        "current_status_card.md",
        "pending_hooks.md",
        "resource_schema.yaml",
        "resource_ledger.md",
    ):
        p = root / f
        assert p.exists(), f"{snapshot_dir}/{f} missing — demo would render as 'not generated'"
        content = p.read_text(encoding="utf-8")
        assert len(content) > 100, f"{snapshot_dir}/{f} is suspiciously small ({len(content)} chars)"
