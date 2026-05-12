"""setting_lint: validate a preset or a project."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch):
    from src import config
    # valid preset
    preset = tmp_path / "presets" / "good"
    preset.mkdir(parents=True)
    (preset / "genre.yaml").write_text("id: good\ndisplay_name: Good\n", encoding="utf-8")
    (preset / "era.md").write_text("# era\n", encoding="utf-8")
    (preset / "writing-style-extra.md").write_text("# style\n", encoding="utf-8")
    (preset / "iron-laws-extra.md").write_text("# laws\n", encoding="utf-8")
    (preset / "novels").mkdir()

    # incomplete preset (missing iron-laws-extra.md)
    incomplete = tmp_path / "presets" / "incomplete"
    incomplete.mkdir(parents=True)
    (incomplete / "genre.yaml").write_text("id: incomplete\n", encoding="utf-8")
    (incomplete / "era.md").write_text("x\n", encoding="utf-8")
    (incomplete / "writing-style-extra.md").write_text("x\n", encoding="utf-8")
    # no iron-laws-extra.md
    (incomplete / "novels").mkdir()

    # valid project
    proj = tmp_path / "projects" / "mybook"
    proj.mkdir(parents=True)
    (proj / "project.yaml").write_text(
        "id: mybook\ndisplay_name: B\nprotagonist_name: H\nchapter_count_target: 10\nsource_preset: good\n",
        encoding="utf-8",
    )
    (proj / "outline.json").write_text('{"title":"B","chapters":[]}', encoding="utf-8")
    (proj / "characters.yaml").write_text("protagonist: {name: H}\nsupporting: []\n", encoding="utf-8")
    (proj / "timeline.yaml").write_text("events: []\n", encoding="utf-8")
    (proj / "era.md").write_text("# era\n", encoding="utf-8")
    (proj / "writing-style-extra.md").write_text("# style\n", encoding="utf-8")
    (proj / "iron-laws-extra.md").write_text("# laws\n", encoding="utf-8")

    # incomplete project
    bad = tmp_path / "projects" / "incomplete"
    bad.mkdir(parents=True)
    (bad / "project.yaml").write_text("id: incomplete\n", encoding="utf-8")

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path


def test_lint_valid_preset_is_clean(fake_repo):
    from src.tools.setting_lint import lint_preset
    report = lint_preset("good")
    assert report.n_errors == 0, [i.message for i in report.issues if i.level == "ERROR"]


def test_lint_incomplete_preset_reports_missing_files(fake_repo):
    from src.tools.setting_lint import lint_preset
    report = lint_preset("incomplete")
    errors = [i.message for i in report.issues if i.level == "ERROR"]
    assert any("iron-laws-extra.md" in m for m in errors)


def test_lint_missing_preset_raises(fake_repo):
    from src.tools.setting_lint import lint_preset
    with pytest.raises(FileNotFoundError):
        lint_preset("nonexistent")


def test_lint_valid_project_is_clean(fake_repo):
    from src.tools.setting_lint import lint_project
    report = lint_project("mybook")
    assert report.n_errors == 0, [i.message for i in report.issues if i.level == "ERROR"]


def test_lint_incomplete_project_reports_missing_files(fake_repo):
    from src.tools.setting_lint import lint_project
    report = lint_project("incomplete")
    errors = [i.message for i in report.issues if i.level == "ERROR"]
    assert any("outline.json" in m or "era.md" in m for m in errors)


def test_cli_preset_flag(fake_repo, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["prog", "--preset", "good"])
    from src.tools.setting_lint import main
    rc = main()
    assert rc == 0  # clean preset = exit 0


def test_cli_project_flag_reports_errors(fake_repo, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["prog", "--project", "incomplete"])
    from src.tools.setting_lint import main
    rc = main()
    assert rc != 0  # has errors → nonzero exit
