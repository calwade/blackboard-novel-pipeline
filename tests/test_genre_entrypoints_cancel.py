"""T7: 4 个顶层入口接 CancelToken + ProgressCallback 的端到端测试."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.jobs.cancel import GenrePipelineAborted, ThreadEventToken


@pytest.fixture
def preset_env(tmp_path: Path, monkeypatch):
    from src import config
    (tmp_path / "presets").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "novels").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path


def test_blank_preset_accepts_new_kwargs(preset_env):
    from src.genre_extractor.blank_preset import create_blank_preset
    calls = []

    def on_progress(**kw):
        calls.append(kw)

    token = ThreadEventToken()
    out = create_blank_preset(
        "myblank", display_name="M", tone="",
        cancel=token, on_progress=on_progress,
    )
    assert out.exists()
    # 至少一次 on_progress("validate", "done") 触发
    assert any(c.get("phase") == "validate" for c in calls)


def test_blank_preset_respects_cancel(preset_env):
    from src.genre_extractor.blank_preset import create_blank_preset
    token = ThreadEventToken()
    token.cancel()
    with pytest.raises(GenrePipelineAborted):
        create_blank_preset("cnl", display_name="C", tone="", cancel=token)


def test_from_description_respects_cancel_before_llm(preset_env):
    from src.genre_extractor.from_description import extract_from_description
    token = ThreadEventToken()
    token.cancel()
    # 预 cancel 应在调 LLM 前就抛 GenrePipelineAborted
    with pytest.raises(GenrePipelineAborted):
        extract_from_description(
            "p", display_name="P", tone="",
            description="some desc", cancel=token,
        )


def test_from_description_fires_progress(preset_env, monkeypatch):
    from src.genre_extractor.from_description import extract_from_description
    calls = []

    def on_progress(**kw):
        calls.append(kw)

    fake_yaml = (
        "era: |\n"
        "  # Era content that is long enough placeholder content " + "x" * 200 + "\n"
        "writing_style_extra: |\n"
        "  # Style content " + "y" * 100 + "\n"
        "iron_laws_extra: |\n"
        "  # Laws " + "z" * 100 + "\n"
        "resource_schema: null\n"
    )
    monkeypatch.setattr(
        "src.genre_extractor.from_description.llm.chat",
        lambda **kw: fake_yaml,
    )
    extract_from_description(
        "pfd", display_name="PFD", tone="",
        description="test description", on_progress=on_progress,
    )
    phases = {c.get("phase") for c in calls if "phase" in c}
    assert "draft" in phases
    assert "validate" in phases


def test_extract_to_preset_cancels_before_first_batch(preset_env):
    """预 cancel extract_to_preset，应在 extract phase 开始前就退出."""
    # 写一份最小可识别章节的小说
    src = preset_env / "novels" / "tiny.txt"
    src.write_text("第一章\n内容AAA\n第二章\n内容BBB\n", encoding="utf-8")

    from src.genre_extractor.to_preset import extract_to_preset
    token = ThreadEventToken()
    token.cancel()
    with pytest.raises(GenrePipelineAborted):
        extract_to_preset(
            "etp", sources=["novels/tiny.txt"], cancel=token,
        )
    # 预期不应留下完整 preset 目录（我们 cancel 得很早）
    # 注意：extract_to_preset 已经 mkdir 过才 check，所以目录可能存在；
    # 但只要不完成 render_files_from_blueprint 就算成功 cancel。
    preset_dir = preset_env / "presets" / "etp"
    # 关键 assertion：我们不应见到 era.md（那是 render_files_from_blueprint 产物）
    assert not (preset_dir / "era.md").exists()
