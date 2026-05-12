"""Structural assertions for the project-home HTML (wizard 4-step + override-genre button).

Phase 4 · Task 4.7 — verify the index page exposes:
  - 4 wizard-step sections (data-wizard-step="1..4")
  - three genre-starter radio options (preset / extract / blank)
  - the 覆盖题材 override button + its supporting form fields
  - main.js wires the new endpoints
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_index_html_has_wizard_4_steps():
    text = (REPO / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    for step in (1, 2, 3, 4):
        assert f'data-wizard-step="{step}"' in text, f"wizard step {step} marker missing"


def test_index_html_has_three_genre_starter_options():
    text = (REPO / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    for marker in ('data-genre-starter="preset"',
                   'data-genre-starter="extract"',
                   'data-genre-starter="blank"'):
        assert marker in text, f"genre-starter option {marker} missing"


def test_index_html_has_extract_genre_override_button():
    text = (REPO / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-extract-genre-override"' in text


def test_index_html_wizard_has_outline_and_characters_textareas():
    text = (REPO / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'name="outline_synopsis"' in text
    assert 'name="characters_brief"' in text
    assert 'name="blank_outline"' in text
    assert 'name="blank_characters"' in text


def test_main_js_wires_wizard_and_override():
    text = (REPO / "web" / "static" / "main.js").read_text(encoding="utf-8")
    # Wizard submission
    assert "/api/projects/new" in text
    # Override
    assert "/extract-genre" in text
    # Reads presets and novels list
    assert "/api/presets" in text
    assert "/api/novels" in text


def test_no_stale_genres_urls_in_web():
    """Web layer must fully use /presets routes after Phase 4."""
    import subprocess
    result = subprocess.run(
        ["git", "grep", "-l", "-E", r"/api/genres|href=\"/genres\""],
        capture_output=True, text=True, cwd=REPO,
    )
    hits = [ln for ln in result.stdout.splitlines() if ln and ln.startswith("web/")]
    assert hits == [], f"stale /genres URLs in web/: {hits}"
