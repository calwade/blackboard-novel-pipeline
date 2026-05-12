"""--new-genre 交互问卷：让用户回答 8-10 个关键问题，产出比纯 stub 更丰富的初稿。"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_answers_to_survey_produces_genre_yaml(tmp_path, monkeypatch):
    """给定一组问卷答案，产出填满的 genre.yaml。"""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    from src.genre_extractor import interview

    answers = {
        "id": "demo-interview",
        "display_name": "赛博朋克 · 2077 夜之城",
        "genre": "赛博朋克 + 黑色侦探",
        "era": "2077 夜之城",
        "tone": "霓虹 + 雨夜 + 独白",
        "author_persona_hints": [
            "懂赛博朋克 2077 游戏术语",
            "熟悉 noir 侦探对白节奏",
        ],
        "genre_avoid": [
            "乌托邦式技术乐观",
            "动漫化少年英雄",
        ],
        "prohibited_styles": [
            "古风仙侠腔",
            "都市甜宠腔",
        ],
    }
    result = interview.build_genre_from_answers(answers)
    assert result["ok"]
    assert result["genre_id"] == "demo-interview"

    import yaml
    g = yaml.safe_load((tmp_path / "demo-interview" / "genre.yaml").read_text("utf-8"))
    assert g["id"] == "demo-interview"
    assert g["display_name"] == "赛博朋克 · 2077 夜之城"
    assert g["era"] == "2077 夜之城"
    assert "赛博朋克 2077 游戏术语" in "\n".join(g["author_persona_hints"])
    assert any("乌托邦" in x for x in g["genre_avoid"])
    assert any("仙侠" in x for x in g["prohibited_styles"])


def test_interview_validates_required_fields(tmp_path, monkeypatch):
    """缺必填字段就 raise。"""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    from src.genre_extractor import interview

    with pytest.raises(ValueError, match="id"):
        interview.build_genre_from_answers({})

    with pytest.raises(ValueError, match="display_name"):
        interview.build_genre_from_answers({"id": "x"})


def test_interview_refuses_existing(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    (tmp_path / "taken").mkdir()

    from src.genre_extractor import interview
    with pytest.raises(FileExistsError):
        interview.build_genre_from_answers({
            "id": "taken",
            "display_name": "x",
        })


def test_interview_produces_richer_than_stub(tmp_path, monkeypatch):
    """interview 产物的 4 份文件字符数应比 pure stub 更多（证明有实际填充）。"""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    from src.genre_extractor import pipeline, interview

    # 跑一份纯 stub
    pipeline.new_genre("pure-stub", display_name="PS", genre="g", era="e", tone="t")
    stub_era = (tmp_path / "pure-stub" / "era.md").read_text("utf-8")

    # 跑一份 interview
    interview.build_genre_from_answers({
        "id": "rich-interview",
        "display_name": "赛博朋克 · 2077 夜之城",
        "genre": "赛博朋克 + 黑色侦探",
        "era": "2077 夜之城",
        "tone": "霓虹 + 雨夜 + 独白",
        "author_persona_hints": ["熟悉 noir 侦探对白节奏"],
        "genre_avoid": ["乌托邦式技术乐观"],
        "prohibited_styles": ["古风仙侠腔"],
    })
    rich_era = (tmp_path / "rich-interview" / "era.md").read_text("utf-8")

    # interview 版必须有用户填的"era"内容
    assert "2077 夜之城" in rich_era
    # interview 版的 era.md 字符数应该 > stub 版
    assert len(rich_era) > len(stub_era)


def test_cli_interactive_flag_exists():
    """CLI 必须接受 --interactive 标志."""
    import subprocess, sys
    p = subprocess.run(
        [sys.executable, "-m", "src.genre_extractor", "--help"],
        capture_output=True, text=True, timeout=20,
    )
    assert p.returncode == 0
    assert "--interactive" in p.stdout
