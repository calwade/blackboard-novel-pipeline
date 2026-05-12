"""Deny-phrase lists for AI-slop scanning.

Two plain-text files (one per language) that the Drafter inlines and
the Validator Tier-1 scans as regex. Minimal schema:
- One phrase per line, blank lines + `# ...` comments ignored.
- Each non-comment line must be non-empty after strip.
- Chinese list: at least 30 entries. English list: at least 8 entries.
"""
from __future__ import annotations

from pathlib import Path


RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


def _load(path: Path) -> list[str]:
    phrases: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        phrases.append(line)
    return phrases


def test_deny_phrases_zh_exists_and_nonempty():
    p = RULES_DIR / "deny-phrases-zh.txt"
    assert p.exists(), f"{p} must exist"
    phrases = _load(p)
    # At least 30 concrete Chinese deny phrases.
    assert len(phrases) >= 30, f"need >=30 phrases, got {len(phrases)}"
    # Every phrase non-empty after strip (re-checked for safety).
    for ph in phrases:
        assert ph.strip() == ph
        assert len(ph) >= 1


def test_deny_phrases_en_exists_and_nonempty():
    p = RULES_DIR / "deny-phrases-en.txt"
    assert p.exists(), f"{p} must exist"
    phrases = _load(p)
    assert len(phrases) >= 8, f"need >=8 phrases, got {len(phrases)}"
    for ph in phrases:
        assert ph.strip() == ph
        assert len(ph) >= 1


def test_deny_phrases_zh_no_duplicates():
    phrases = _load(RULES_DIR / "deny-phrases-zh.txt")
    assert len(set(phrases)) == len(phrases), "duplicate phrases in zh list"


def test_deny_phrases_en_no_duplicates():
    phrases = _load(RULES_DIR / "deny-phrases-en.txt")
    assert len(set(phrases)) == len(phrases), "duplicate phrases in en list"
