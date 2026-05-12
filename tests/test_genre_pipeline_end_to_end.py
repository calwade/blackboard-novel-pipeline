"""端到端 dry-run：验证所有 phase 能按顺序走完、build_status 正确演进。"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_end_to_end_dry_run(tmp_path, monkeypatch):
    """从 extract-from-novel 到 validate done，所有状态正确。"""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    novel = tmp_path / "mini.txt"
    novel.write_text(
        "\n".join(f"第{i}章\n场景...对白..." for i in range(1, 11)), encoding="utf-8"
    )

    from src.genre_pipeline import pipeline
    out = pipeline.extract_from_novel(
        "e2e-dry",
        sources=[str(novel)],
        with_trial=False,
        dry_run=True,
    )
    assert out["ok"]
    assert out["genre_id"] == "e2e-dry"

    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path / "e2e-dry" / ".build")
    status = bb.read_yaml("build_status.yaml")
    for phase in ("extract", "merge", "draft", "validate"):
        assert status["phases"][phase]["status"] == "done", f"phase {phase} not done"


def test_trial_rejects_unknown_genre(tmp_path):
    """Real run_trial validates genre up front — unknown id must raise.

    (The old placeholder silently wrote an info record; the real impl
    fails fast so upstream callers don't misinterpret a stub run as a
    successful trial.)
    """
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.trial import run_trial

    bb = Blackboard(root=tmp_path)
    with pytest.raises((FileNotFoundError, ValueError)):
        run_trial("demo-trial", bb, dry_run=True)


def test_audit_existing_genre_real(tmp_path, monkeypatch):
    """Audit a real seed genre to confirm Stage 1 (setting_lint) integration.

    Uses the real gangster-hk-1983 in-repo genre as target. Monkeypatches
    GENRES_DIR to a tmp location that symlinks/copies the real genre, so the
    audit leaves no trace in the real repo.
    """
    import shutil
    from src import config

    real_genres = config.GENRES_DIR
    if not (real_genres / "gangster-hk-1983").exists():
        pytest.skip("reference genre 'gangster-hk-1983' missing")

    shutil.copytree(real_genres / "gangster-hk-1983", tmp_path / "gangster-hk-1983")
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    from src.genre_pipeline import pipeline
    # audit triggers Stage 1 (structure lint).
    # Stage 2 (LLM) is best-effort — if it raises it's logged as a warning, not a failure.
    out = pipeline.audit_genre("gangster-hk-1983")

    # The audit summary must be structurally valid regardless of LLM availability.
    assert "error_count" in out
    assert "warning_count" in out
    assert out["genre_id"] == "gangster-hk-1983"
