"""Tests for the real `run_trial` implementation.

`run_trial(genre_id, bb)` spawns a throwaway project against the candidate
genre and runs 3 chapters through the novel pipeline. All LLM calls are
stubbed; we verify:

- scratch tmp is cleaned up (unless keep_scratch=True),
- config.PROJECTS_DIR / ACTIVE_POINTER / STATE_DIR are restored,
- prior active project pointer is preserved,
- genre_issues.jsonl receives a summary record (info on full-pass,
  warning when any chapter fails),
- unknown genre_id raises FileNotFoundError / ValueError.

The tests isolate config paths entirely under tmp_path so the real repo
never sees mutation. Follows the same pattern as tests/conftest.py's
isolated_project fixture.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src import config
from src.core.blackboard import Blackboard


# ------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------

def _stage_isolated_genre_and_build(tmp_path: Path, monkeypatch,
                                    *, genre_id: str = "gangster-hk-1983"
                                    ) -> tuple[Path, Blackboard]:
    """Copy the real gangster genre into a tmp sandbox; return (.build bb, tmp_genres).

    - tmp_genres/<genre_id>/               — full genre pack copy
    - tmp_projects/                        — empty; trial will mkdir trial-probe here
    - active pointer — tmp_projects/.active
    """
    tmp_genres = tmp_path / "genres"
    tmp_projects = tmp_path / "projects"
    tmp_genres.mkdir()
    tmp_projects.mkdir()

    real_genre = config.GENRES_DIR / genre_id
    if not real_genre.exists():
        pytest.skip(f"reference genre '{genre_id}' missing; cannot stage")
    shutil.copytree(real_genre, tmp_genres / genre_id)

    # Redirect all config paths. These are monkeypatched on the config
    # module so that bootstrap_project (which reads config.PROJECTS_DIR
    # etc. at call time) picks them up.
    monkeypatch.setattr(config, "GENRES_DIR", tmp_genres)
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_projects)
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_projects / ".active")

    build_root = tmp_genres / genre_id / ".build"
    build_root.mkdir(exist_ok=True)
    bb = Blackboard(root=build_root)
    return build_root, bb


def _patch_llm_always_ok(monkeypatch):
    """Stub src.agents._base.llm.chat so every agent returns passable output."""
    def fake_chat(*, system, user, agent_name, temperature, max_tokens,
                  response_format, inputs_read):
        if agent_name == "planner":
            return json.dumps({
                "ch": 1,
                "title": "trial",
                "chapter_type": "过渡",
                "opening_hook": "o",
                "scenes": [
                    {"scene_id": 1, "cast": ["主角"], "advances": ["地位"]}
                ],
                "closing_hook": "c",
                "landmines_to_avoid": [],
                "writing_self_check": {},
            })
        if agent_name == "evaluator":
            return json.dumps({
                "overall_pass": True,
                "landmines": {},
                "top_3_fixes": [],
            })
        if response_format == "json":
            return "{}"
        # everything else (generator/summarizer/status_card/hooks/auditors/...)
        # just returns a plausible markdown stub
        return "# 第一章 标题\n\n正文内容。\n"
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)


# ------------------------------------------------------------------------
# Task A — dry-run skeleton
# ------------------------------------------------------------------------

def test_trial_dry_run_creates_scratch_and_cleans_up(tmp_path, monkeypatch):
    """dry_run=True must not call the LLM yet still run bootstrap + cleanup."""
    from src.genre_extractor import trial

    _, bb = _stage_isolated_genre_and_build(tmp_path, monkeypatch)

    # Track scratch dirs that exist during run, verify they're gone after.
    seen_scratch: list[Path] = []
    orig_mkdtemp = trial.tempfile.mkdtemp  # type: ignore[attr-defined]

    def tracking_mkdtemp(*a, **kw):
        p = orig_mkdtemp(*a, **kw)
        seen_scratch.append(Path(p))
        return p

    monkeypatch.setattr(trial.tempfile, "mkdtemp", tracking_mkdtemp)

    # Hard guard: no LLM calls should happen in dry-run.
    def forbidden(*a, **kw):
        raise AssertionError("LLM called during dry-run")
    monkeypatch.setattr("src.agents._base.llm.chat", forbidden)

    trial.run_trial("gangster-hk-1983", bb, chapters=3, dry_run=True)

    # At least one scratch dir was created and cleaned.
    assert seen_scratch, "expected at least one scratch tmpdir"
    for p in seen_scratch:
        assert not p.exists(), f"scratch dir {p} should be cleaned up"

    # Config paths restored — active should be None (we started with no active).
    assert config.get_active_project_id() is None

    # An info record was written (dry-run signals success by convention).
    issues = bb.read_jsonl("genre_issues.jsonl")
    assert any(i.get("severity") == "info" for i in issues), (
        f"expected info record, got {issues}"
    )


# ------------------------------------------------------------------------
# Task B — full stub LLM run: 3 chapters pass
# ------------------------------------------------------------------------

def test_trial_with_stub_llm_runs_three_chapters(tmp_path, monkeypatch):
    """With stubbed LLM + evaluator passing, 3 chapters finish and info is logged."""
    from src.genre_extractor import trial

    _, bb = _stage_isolated_genre_and_build(tmp_path, monkeypatch)
    _patch_llm_always_ok(monkeypatch)

    trial.run_trial("gangster-hk-1983", bb, chapters=3)

    issues = bb.read_jsonl("genre_issues.jsonl")
    # Full-pass: severity=info with "3/3" message
    assert any(
        i.get("severity") == "info" and "3/3" in str(i.get("message", ""))
        for i in issues
    ), f"expected full-pass info record, got {issues}"


def test_trial_records_warning_when_chapter_fails(tmp_path, monkeypatch):
    """If evaluator returns overall_pass=False, a warning is recorded."""
    from src.genre_extractor import trial

    _, bb = _stage_isolated_genre_and_build(tmp_path, monkeypatch)

    def fake_chat(*, system, user, agent_name, temperature, max_tokens,
                  response_format, inputs_read):
        if agent_name == "planner":
            return json.dumps({
                "ch": 1, "title": "t", "chapter_type": "过渡",
                "opening_hook": "o",
                "scenes": [{"scene_id": 1, "cast": ["主角"], "advances": ["地位"]}],
                "closing_hook": "c", "landmines_to_avoid": [],
                "writing_self_check": {},
            })
        if agent_name == "evaluator":
            # ALL chapters fail — pipeline will ship_with_debt after retries
            return json.dumps({
                "overall_pass": False,
                "landmines": {
                    "landmine_01": {"hit": True, "severity": "high",
                                    "evidence": "stub", "fix_hint": "stub"}
                },
                "top_3_fixes": [{"where": "s", "what": "w", "how": "h"}],
            })
        if response_format == "json":
            return "{}"
        return "# t\n\n正文。\n"
    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)

    trial.run_trial("gangster-hk-1983", bb, chapters=3)

    issues = bb.read_jsonl("genre_issues.jsonl")
    assert any(i.get("severity") == "warning" for i in issues), (
        f"expected warning record, got {issues}"
    )


# ------------------------------------------------------------------------
# Task B — error handling & active-project preservation
# ------------------------------------------------------------------------

def test_trial_handles_genre_not_found(tmp_path, monkeypatch):
    """Unknown genre_id must raise, not silently write garbage."""
    from src.genre_extractor import trial

    tmp_genres = tmp_path / "genres"
    tmp_projects = tmp_path / "projects"
    tmp_genres.mkdir()
    tmp_projects.mkdir()
    monkeypatch.setattr(config, "GENRES_DIR", tmp_genres)
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_projects)
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_projects / ".active")

    bb = Blackboard(root=tmp_path / "build")

    with pytest.raises((FileNotFoundError, ValueError)):
        trial.run_trial("nonexistent-genre-xyz", bb, chapters=3, dry_run=True)


def test_trial_preserves_prior_active_project(tmp_path, monkeypatch):
    """If another project was active before trial, it must be restored after."""
    from src.genre_extractor import trial
    from src import bootstrap

    _, bb = _stage_isolated_genre_and_build(tmp_path, monkeypatch)

    # Create a prior project and mark it active.
    prior = config.PROJECTS_DIR / "prior-proj"
    real = config.PROJECTS_DIR  # already tmp
    # Copy a valid project in so bootstrap_project accepts it
    src_proj = Path(__file__).resolve().parent.parent / "projects" / "gangster-hk-1983-linjiayao"
    shutil.copytree(src_proj, prior)
    # Rewrite id inside project.yaml so the copy keeps consistency
    import yaml
    pyaml = yaml.safe_load((prior / "project.yaml").read_text(encoding="utf-8"))
    pyaml["id"] = "prior-proj"
    (prior / "project.yaml").write_text(
        yaml.safe_dump(pyaml, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    bootstrap.bootstrap_project("prior-proj")
    assert config.get_active_project_id() == "prior-proj"

    # run the trial with dry-run so no LLM
    trial.run_trial("gangster-hk-1983", bb, chapters=1, dry_run=True)

    assert config.get_active_project_id() == "prior-proj", (
        "prior active project should be restored after trial"
    )
