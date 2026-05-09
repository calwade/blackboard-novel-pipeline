"""Tests for setting_lint — verify it catches real errors and passes clean settings."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.tools.setting_lint import lint_setting, LintReport


@pytest.fixture
def clean_setting(tmp_path: Path) -> Path:
    """A minimal valid setting pack."""
    d = tmp_path / "test-setting"
    d.mkdir()

    (d / "setting.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "test-setting",
                "display_name": "Test",
                "locale": "zh-Hans",
                "genre": "都市",
                "era": "2024",
                "tone": "冷峻",
                "protagonist_name": "张三",
                "chapter_count_target": 100,
                "chapters_in_outline": 3,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    outline = {
        "title": "Test Novel",
        "protagonist": "张三",
        "chapter_count_target": 100,
        "chapters_in_outline": 3,
        "chapters": [
            {
                "ch": i,
                "title": f"第{i}章",
                "year_month": f"2024-0{i}",
                "key_location": "北京",
                "key_characters": ["张三", "李四"],
                "beats": [f"beat{i}-1", f"beat{i}-2", f"beat{i}-3"],
                "opening_hook": "开场",
                "closing_hook": "收场",
                "tension": "张力",
                "word_target": 3000,
            }
            for i in (1, 2, 3)
        ],
    }
    (d / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    (d / "timeline.yaml").write_text(
        yaml.safe_dump(
            {
                "2024": [
                    {"date": "2024-01", "event": "e1"},
                    {"date": "2024-02", "event": "e2"},
                    {"date": "2024-03", "event": "e3"},
                ]
            }
        ),
        encoding="utf-8",
    )

    (d / "characters.yaml").write_text(
        yaml.safe_dump(
            {
                "protagonist": {"name": "张三", "age": 30},
                "supporting": [
                    {"name": "李四", "role": "朋友"},
                    {"name": "王五", "role": "对手"},
                    {"name": "赵六", "role": "导师"},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    (d / "era.md").write_text("x" * 600, encoding="utf-8")  # > 500
    (d / "writing-style-extra.md").write_text("y" * 400, encoding="utf-8")  # > 300
    (d / "iron-laws-extra.md").write_text(
        "iron_law_extra_1 foo\niron_law_extra_2 bar\niron_law_extra_3 baz\n",
        encoding="utf-8",
    )
    return d


def test_clean_setting_has_no_errors(clean_setting):
    r = lint_setting(clean_setting)
    # Supporting character 王五 never appears in outline — so 1 INFO
    # and 赵六 too — so 2 INFOs total
    assert r.n_errors == 0
    # INFO about unused supporting chars is expected + allowed
    assert r.n_warnings == 0


def test_missing_file_is_error(clean_setting):
    (clean_setting / "era.md").unlink()
    r = lint_setting(clean_setting)
    assert r.n_errors >= 1
    assert any("era.md" in i.file and i.level == "ERROR" for i in r.issues)


def test_protagonist_mismatch_is_error(clean_setting):
    # Change characters.yaml to a different name
    chars = yaml.safe_load((clean_setting / "characters.yaml").read_text(encoding="utf-8"))
    chars["protagonist"]["name"] = "不同的名字"
    (clean_setting / "characters.yaml").write_text(
        yaml.safe_dump(chars, allow_unicode=True), encoding="utf-8"
    )
    r = lint_setting(clean_setting)
    assert any(
        i.level == "ERROR" and "protagonist_name mismatch" in i.message
        for i in r.issues
    )


def test_thin_era_is_warning(clean_setting):
    (clean_setting / "era.md").write_text("只有一句话。", encoding="utf-8")
    r = lint_setting(clean_setting)
    assert any(i.level == "WARNING" and "era.md" in i.file for i in r.issues)


def test_missing_iron_laws_extra_is_warning(clean_setting):
    (clean_setting / "iron-laws-extra.md").write_text("# Empty header", encoding="utf-8")
    r = lint_setting(clean_setting)
    assert any(
        i.level == "WARNING" and "iron-laws-extra.md" in i.file for i in r.issues
    )


def test_unknown_character_ref_is_warning(clean_setting):
    # Change outline to reference a character not in characters.yaml
    outline = json.loads((clean_setting / "outline.json").read_text(encoding="utf-8"))
    outline["chapters"][0]["key_characters"] = ["张三", "完全不在档案里的某人"]
    (clean_setting / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False), encoding="utf-8"
    )
    r = lint_setting(clean_setting)
    assert any(
        i.level == "WARNING" and "unknown character" in i.message for i in r.issues
    )


def test_malformed_yaml_is_error(clean_setting):
    (clean_setting / "setting.yaml").write_text("this: is: bad:yaml:[", encoding="utf-8")
    r = lint_setting(clean_setting)
    assert any(i.level == "ERROR" and "parse failed" in i.message for i in r.issues)


def test_malformed_json_is_error(clean_setting):
    (clean_setting / "outline.json").write_text("{ not valid json }", encoding="utf-8")
    r = lint_setting(clean_setting)
    assert any(
        i.level == "ERROR" and "outline.json" in i.file and "parse failed" in i.message
        for i in r.issues
    )


def test_meta_words_in_setting_md_is_info(clean_setting):
    (clean_setting / "era.md").write_text(
        "x" * 600 + "\n本项目为黑客松 MVP。", encoding="utf-8"
    )
    r = lint_setting(clean_setting)
    assert any(i.level == "INFO" and "MVP" in i.message for i in r.issues)
    assert any(i.level == "INFO" and "黑客松" in i.message for i in r.issues)


def test_thin_golden_3_chapters_is_warning(clean_setting):
    outline = json.loads((clean_setting / "outline.json").read_text(encoding="utf-8"))
    # Strip beats from ch1 to only 1 beat
    outline["chapters"][0]["beats"] = ["only one beat"]
    (clean_setting / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False), encoding="utf-8"
    )
    r = lint_setting(clean_setting)
    # Should trigger either "黄金三章" warning (missing fields) or the
    # "first 3 chapters should have ≥3 each" warning (beat count)
    assert any(
        i.level == "WARNING" and ("黄金三章" in i.message or "≥3 each" in i.message)
        for i in r.issues
    )


def test_real_gangster_setting_has_no_errors():
    """Integration: real gangster-hk-1983 must have 0 errors."""
    from src import config
    gangster = config.PROJECT_ROOT / "settings" / "gangster-hk-1983"
    r = lint_setting(gangster)
    assert r.n_errors == 0, f"gangster setting has errors: {[i.message for i in r.issues if i.level == 'ERROR']}"


def test_real_xianxia_setting_has_no_errors():
    """Integration: real xianxia-ascension must have 0 errors."""
    from src import config
    xianxia = config.PROJECT_ROOT / "settings" / "xianxia-ascension"
    r = lint_setting(xianxia)
    assert r.n_errors == 0, f"xianxia setting has errors: {[i.message for i in r.issues if i.level == 'ERROR']}"
