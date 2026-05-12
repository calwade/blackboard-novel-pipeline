"""CLI 冒烟测试：四个入口都能出合法输出。

不调真实 LLM（使用 --dry-run 或不触发 LLM 的入口）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(*args) -> tuple[int, str, str]:
    """Run the CLI with args; capture stdout/stderr."""
    cmd = [sys.executable, "-m", "src.genre_extractor", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout, p.stderr


def test_cli_help():
    rc, out, err = _run_cli("--help")
    assert rc == 0
    assert "--new-genre" in out
    assert "--extract-from-novel" in out


def test_new_genre_creates_scaffold(tmp_path, monkeypatch):
    """--new-genre in a tmp GENRES_DIR."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    from src.genre_extractor import pipeline
    out = pipeline.new_genre(
        "demo-cli", display_name="Demo", genre="demo", era="2020", tone="neutral"
    )
    assert out["ok"]
    d = tmp_path / "demo-cli"
    assert (d / "genre.yaml").exists()
    assert (d / "era.md").exists()
    assert (d / "writing-style-extra.md").exists()
    assert (d / "iron-laws-extra.md").exists()
    assert (d / ".build" / "build_status.yaml").exists()


def test_new_genre_refuses_existing(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    (tmp_path / "occupied").mkdir()

    from src.genre_extractor import pipeline
    with pytest.raises(FileExistsError):
        pipeline.new_genre("occupied")


def test_extract_from_novel_dry_run(tmp_path, monkeypatch):
    """Full plumbing walk-through without any LLM call."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    novel = tmp_path / "novel.txt"
    novel.write_text(
        "\n".join([f"第{i}章 章节{i}\n内容..." for i in range(1, 31)]),
        encoding="utf-8",
    )

    from src.genre_extractor import pipeline
    out = pipeline.extract_from_novel(
        "demo-extract",
        sources=[str(novel)],
        with_trial=False,
        dry_run=True,
    )
    assert out["ok"]
    assert out["mode"] == "dry_run"

    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path / "demo-extract" / ".build")
    s = bb.read_yaml("build_status.yaml")
    for phase in ("extract", "merge", "draft", "validate"):
        assert s["phases"][phase]["status"] == "done"


def test_extract_from_novel_missing_source_raises(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    from src.genre_extractor import pipeline
    with pytest.raises(FileNotFoundError):
        pipeline.extract_from_novel(
            "demo-missing",
            sources=[str(tmp_path / "nonexistent.txt")],
            dry_run=True,
        )


def test_fill_genre_adds_missing(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    d = tmp_path / "half-baked"
    d.mkdir()
    (d / "genre.yaml").write_text("id: half-baked\n", encoding="utf-8")

    from src.genre_extractor import pipeline
    out = pipeline.fill_genre("half-baked")
    assert out["ok"]
    assert set(out["filled"]) == {"era.md", "writing-style-extra.md", "iron-laws-extra.md"}
    assert (d / "era.md").exists()


def test_fill_genre_nonexistent_raises(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    from src.genre_extractor import pipeline
    with pytest.raises(FileNotFoundError):
        pipeline.fill_genre("nobody")


def test_run_phase_requires_build_status(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    from src.genre_extractor import pipeline
    # Genre exists but no .build/build_status.yaml
    (tmp_path / "no-build").mkdir()
    with pytest.raises(FileNotFoundError, match="build_status"):
        pipeline.run_phase("no-build", phase="extract")
