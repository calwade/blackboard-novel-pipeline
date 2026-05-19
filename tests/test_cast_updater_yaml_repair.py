"""Tests for CastUpdater YAML repair + tolerance.

LLM 经常输出形如 ``- "规矩"挂在嘴边`` 这样的中文标注，把裸双引号当语义引号；
yaml 把 ``"规矩"`` 当 quoted scalar 边界，整章 pipeline 卡住。

CastUpdater 现在做两件事：
1. 第一次 ``yaml.safe_load`` 失败 → 跑 ``_repair_yaml_chinese_quotes`` 把
   行内成对的裸双引号替换为「」，再 parse 一次。
2. 再失败 → 警告 + silent return，让旧 cast 保留，pipeline 继续。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.agents.cast_updater import (
    CastUpdater,
    _repair_yaml_chinese_quotes,
)
from src.blackboard import Blackboard


# ---------- _repair_yaml_chinese_quotes pure-function tests ----------


def test_repair_chinese_quotes_pair():
    """Single pair of bare double quotes inside a list-item value → 「」."""
    src = '      - "规矩"挂在嘴边\n'
    out = _repair_yaml_chinese_quotes(src)
    assert out == "      - 「规矩」挂在嘴边"
    # And the result is now valid yaml as a list of one item:
    assert yaml.safe_load("voice_tags:\n" + out)["voice_tags"] == ["「规矩」挂在嘴边"]


def test_repair_two_quoted_phrases():
    """Two pairs in one line → 「」 「」 in order."""
    src = '  - A: "规矩" B: "节律"'
    out = _repair_yaml_chinese_quotes(src)
    assert out == "  - A: 「规矩」 B: 「节律」"


def test_repair_does_not_touch_pure_quoted_string():
    """A value that is exactly "..." with no other content is a legal yaml
    quoted scalar — leave it alone."""
    src = '    - "regular"'
    assert _repair_yaml_chinese_quotes(src) == src
    # And it parses correctly as a string list item.
    assert yaml.safe_load("xs:\n" + src)["xs"] == ["regular"]


def test_repair_does_not_touch_keys_with_clean_string_value():
    """``key: "value"`` where value is a clean quoted scalar — keep as-is."""
    src = '  one_line: "纯字符串"'
    assert _repair_yaml_chinese_quotes(src) == src


def test_repair_handles_mapping_value_with_inline_quotes():
    """LLM 真实失败 case：``one_line: 系统炉底"挂着"，残留……``"""
    src = '    one_line: 前任第七掮客，其编号仍在系统炉底"挂着"，残留担保链与语法裂隙'
    out = _repair_yaml_chinese_quotes(src)
    assert out == '    one_line: 前任第七掮客，其编号仍在系统炉底「挂着」，残留担保链与语法裂隙'
    parsed = yaml.safe_load(out)
    assert parsed["one_line"].endswith("语法裂隙")


def test_repair_leaves_lines_without_quotes():
    src = "schema_version: 1\nlast_updated_chapter: 1\ncast:\n  - name: 苏烬\n    role: 主角"
    assert _repair_yaml_chinese_quotes(src) == src


def test_repair_skips_unmatched_odd_quote_count():
    """3 个双引号无法成对配 → 保持原样（不胡乱替换）。"""
    src = '  - 这里有 "一" 和 "二 三个引号'
    # 3 个 " — odd; should be left as-is to avoid corrupting data
    assert _repair_yaml_chinese_quotes(src) == src


def test_repair_full_failing_block_from_real_log():
    """完整还原 17:07 真实失败：含 list-item 内引号 + mapping value 内引号。"""
    src = (
        "cast:\n"
        "  - name: 纸鹞\n"
        '    one_line: 其编号仍在系统炉底"挂着"，残留担保链与语法裂隙\n'
        "    voice_tags:\n"
        '      - "规矩"挂在嘴边\n'
        '      - 不会无偿提供"完整版"数据\n'
    )
    repaired = _repair_yaml_chinese_quotes(src)
    parsed = yaml.safe_load(repaired)
    entry = parsed["cast"][0]
    assert entry["name"] == "纸鹞"
    assert "「挂着」" in entry["one_line"]
    tags = entry["voice_tags"]
    assert "「规矩」挂在嘴边" in tags
    assert "不会无偿提供「完整版」数据" in tags


# ---------- _handle_output integration tests ----------


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "test"})
    b.write_yaml("characters.yaml", {"protagonist": {"name": "苏烬"}})
    (tmp_path / "chapters").mkdir(exist_ok=True)
    return b


def test_handle_output_uses_repair_on_yaml_failure(bb):
    """yaml 第一次 parse 失败 → 修复后能 parse → 文件被写入。"""
    # 注意 voice_tags 行有裸双引号会让第一次 safe_load 报错
    raw = (
        "schema_version: 1\n"
        "last_updated_chapter: 1\n"
        "cast:\n"
        "  - name: 苏烬\n"
        "    role: 主角\n"
        "    first_appeared_ch: 1\n"
        "    last_appeared_ch: 1\n"
        "    status: active\n"
        "    in_baseline: true\n"
        "    voice_tags:\n"
        '      - "规矩"挂在嘴边\n'
        '      - 不会无偿提供"完整版"数据\n'
    )
    # First parse must indeed fail — this guards the test premise.
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(raw)

    # _handle_output should not raise — it repairs and writes.
    CastUpdater()._handle_output(bb, raw, chapter=1)
    obj = bb.read_yaml("characters-cast.yaml")
    assert obj["last_updated_chapter"] == 1
    tags = obj["cast"][0]["voice_tags"]
    assert "「规矩」挂在嘴边" in tags
    assert "不会无偿提供「完整版」数据" in tags


def test_handle_output_returns_silently_on_unrecoverable(bb):
    """完全坏掉的 yaml（即便修复后仍坏）→ warning + silent return，
    旧 cast 文件保留，pipeline 不被阻断。"""
    bb.write_yaml(
        "characters-cast.yaml",
        {
            "schema_version": 1,
            "last_updated_chapter": 0,
            "cast": [{"name": "old-entry"}],
        },
    )
    # 这一段 yaml 即便经过引号修复也不可能合法
    raw = "this:: is :: completely : broken : :\n  - - - x\n: : :"
    # Must not raise.
    CastUpdater()._handle_output(bb, raw, chapter=1)
    # Prior cast file still intact.
    obj = bb.read_yaml("characters-cast.yaml")
    assert obj["last_updated_chapter"] == 0
    assert obj["cast"][0]["name"] == "old-entry"


def test_handle_output_returns_silently_when_no_prior_cast(bb):
    """同上，但没有旧 cast → 仅是不创建文件，不抛错。"""
    raw = ":::not yaml at all:::"
    CastUpdater()._handle_output(bb, raw, chapter=1)
    assert not bb.exists("characters-cast.yaml")


# ---------- system prompt safety rules ----------


def test_cast_updater_prompt_has_yaml_safety_rules(bb):
    bb.write_text("chapters/ch001.md", "苏烬走入巷口。")
    system, _, _ = CastUpdater()._build_prompts(bb, chapter=1)
    # 关键提示词应该都在 system prompt 里
    assert "不要用裸双引号" in system or "绝对不要用裸双引号" in system
    assert "「" in system
    assert "」" in system
    # 用例对照（错与对）
    assert "「规矩」" in system
