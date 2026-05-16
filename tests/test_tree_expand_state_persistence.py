"""Lock in: tree.js preserves expand state across polling rebuilds.

Why: pollState() runs every 2-4 seconds and calls renderTree() which does
`tree.innerHTML = ''` then rebuilds the entire DOM. Previously this lost
all is-open state — user manually expands a chapter group, polling fires,
group auto-collapses. Reported by user as "展开后过几秒缩回去".

Fix: each collapsible node carries data-tree-key (chapter:N / section:title).
renderTree snapshots open keys before innerHTML='', then restores is-open
on rebuild. This test guards the contract that:
  1. Every chapter group has a unique data-tree-key
  2. Every collapsible section header has a data-tree-key
  3. The render function reads data-tree-key from existing DOM before clearing
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TREE_JS = REPO_ROOT / "web" / "static" / "js" / "ui" / "tree.js"


@pytest.fixture
def tree_source() -> str:
    return TREE_JS.read_text(encoding="utf-8")


def test_tree_has_open_state_snapshot_before_innerhtml_clear(tree_source: str):
    """The snapshot-then-rebuild pattern must exist; otherwise polling
    silently re-collapses the tree every 2-4 seconds."""
    # Must collect openKeys from existing DOM before clearing
    assert "data-tree-key" in tree_source, (
        "tree.js missing data-tree-key attribute — needed to identify "
        "collapsible nodes across rebuilds"
    )
    assert "openKeys" in tree_source, (
        "tree.js missing openKeys snapshot — without it, polling rebuilds "
        "lose all user expand state every 2-4 seconds"
    )
    # Snapshot must happen BEFORE innerHTML clear (order matters)
    snapshot_idx = tree_source.find("openKeys")
    clear_idx = tree_source.find("innerHTML = ''")
    assert snapshot_idx > 0, "openKeys snapshot logic missing"
    assert clear_idx > 0, "innerHTML clear missing"
    assert snapshot_idx < clear_idx, (
        "openKeys must be collected BEFORE tree.innerHTML='' — "
        "otherwise the snapshot reads from an already-empty tree"
    )


def test_chapter_groups_have_data_tree_key(tree_source: str):
    """Each chapter group label must carry chapter:N key for state restoration."""
    # Look for the dataset assignment in the chapter group label creation
    assert re.search(r"groupKey\s*=\s*[`'\"]chapter:", tree_source), (
        "tree.js chapter group missing 'chapter:N' tree-key pattern. "
        "Without it, renderTree can't identify which chapter was expanded."
    )


def test_section_headers_have_data_tree_key(tree_source: str):
    """Section headers must use section:title keys (e.g. section:rules)."""
    # Multiple ways the key string can appear: inline opts {key: 'section:X'},
    # or via const rulesKey = 'section:rules'. Just check the string pattern.
    matches = re.findall(r"['\"]section:[a-z\-]+['\"]", tree_source)
    assert len(matches) >= 4, (
        f"tree.js section headers missing 'section:*' keys; found {matches}. "
        f"Expected at least 4 sections (chapters / bookkeeping / runtime / rules)."
    )


def test_section_header_signature_accepts_open_keys(tree_source: str):
    """sectionHeader function must take openKeys to restore user state."""
    # New signature: sectionHeader(title, opts, openKeys)
    sig = re.search(r"function\s+sectionHeader\s*\(([^)]+)\)", tree_source)
    assert sig, "sectionHeader function not found"
    params = sig.group(1)
    assert "openKeys" in params, (
        "sectionHeader must accept openKeys parameter to restore state — "
        f"current signature: {params}"
    )


def test_chapter_open_default_respects_user_expansion(tree_source: str):
    """A user-expanded chapter must stay open even if it's not the current chapter."""
    # The openDefault check should OR with userOpened
    assert re.search(r"userOpened\s*=\s*openKeys\.has", tree_source) or \
           re.search(r"openKeys\.has\(groupKey\)", tree_source), (
        "tree.js chapter group must check openKeys.has(groupKey) — "
        "otherwise only currentChapter stays open after rebuild"
    )
