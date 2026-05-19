"""Lock in: <dialog> elements stay display:none until [open], not stacked on the page.

Why: user reported "弹窗下方挤主页" — sources_editor / settings dialogs being
shown stacked at the bottom of the page, pushing main content up. Root cause:
dialog.css set `display: flex` directly on `.dlg`, overriding the user-agent
default `display: none` for closed <dialog>. All 4 dialogs (project picker,
new project, sources editor, settings) were always rendered visible.

Fix: move `display: flex` into `.dlg[open]` rule so closed dialogs use the
user-agent default `display: none`.

This test guards the contract that:
1. .dlg base rule must NOT contain display:flex/block/inline-block
2. .dlg[open] rule MUST contain display: flex
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DIALOG_CSS = REPO_ROOT / "web" / "static" / "css" / "components" / "dialog.css"


@pytest.fixture
def dialog_css() -> str:
    return DIALOG_CSS.read_text(encoding="utf-8")


def _extract_rule(css: str, selector: str) -> str:
    """Return the body of a CSS rule by exact selector match."""
    pattern = re.compile(
        r"(?:^|\n)\s*" + re.escape(selector) + r"\s*\{([^}]*)\}",
        re.MULTILINE,
    )
    m = pattern.search(css)
    return m.group(1) if m else ""


def test_dlg_base_rule_does_not_force_display(dialog_css: str):
    """.dlg base rule must not override user-agent display:none for closed <dialog>."""
    base_body = _extract_rule(dialog_css, ".dlg")
    assert base_body, "couldn't find .dlg rule in dialog.css"
    # display:flex/block 不该出现在裸 .dlg 里 — 否则关着的 dialog 也被强制显示
    forbidden = re.search(r"\bdisplay\s*:\s*(flex|block|inline-block|grid)\b", base_body)
    assert not forbidden, (
        f".dlg base rule contains forbidden display rule: {forbidden.group(0)}. "
        f"This causes closed <dialog> elements to stack on the page. "
        f"Move 'display: flex' into .dlg[open] only."
    )


def test_dlg_open_rule_has_display_flex(dialog_css: str):
    """.dlg[open] must declare display:flex so the dialog renders when open."""
    open_body = _extract_rule(dialog_css, ".dlg[open]")
    assert open_body, "couldn't find .dlg[open] rule in dialog.css"
    assert re.search(r"\bdisplay\s*:\s*flex\b", open_body), (
        ".dlg[open] missing 'display: flex' — dialogs won't show when opened. "
        f"Current body: {open_body!r}"
    )


def test_dlg_keeps_flex_direction_in_base(dialog_css: str):
    """flex-direction can stay in base since it's harmless when display is none."""
    base_body = _extract_rule(dialog_css, ".dlg")
    # flex-direction:column 留在 base 不影响 — 它仅在 display:flex 时生效
    # 这条只是说明保留是可以的，不是硬约束
    # (no assertion — purely documentation via test name)
    assert True
