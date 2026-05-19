"""pytest tests for CastUpdater (running演员表 维护员)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.blackboard import Blackboard
from src.agents.cast_updater import CastUpdater, read_characters_cast


@pytest.fixture
def bb(tmp_path: Path) -> Blackboard:
    b = Blackboard(root=tmp_path)
    b.write_yaml("setting.yaml", {"genre": "港综", "era": "1983"})
    b.write_yaml(
        "characters.yaml",
        {"protagonist": {"name": "陈默", "traits": ["冷静", "心狠"]}, "supporting": []},
    )
    (tmp_path / "chapters").mkdir(exist_ok=True)
    return b


# ---------- prompt construction ----------

def test_prompt_first_run_no_prior_cast(bb):
    bb.write_text(
        "chapters/ch001.md",
        "陈默走进巷子。老刘从拐角探出头：『阿默，赵铁城的人来过。』",
    )
    system, user, inputs = CastUpdater()._build_prompts(bb, chapter=1)
    assert "cast 维护员" in system
    assert "in_baseline" in system
    assert "永不删除条目" in system
    assert "state/chapters/ch001.md" in inputs
    assert "state/characters.yaml" in inputs
    # First run: no prior cast file
    assert "state/characters-cast.yaml" not in inputs
    assert "首次" in user or "首次运行" in user


def test_prompt_includes_baseline_yaml(bb):
    bb.write_text("chapters/ch001.md", "正文")
    _, user, _ = CastUpdater()._build_prompts(bb, chapter=1)
    # baseline yaml passed into user prompt
    assert "陈默" in user
    assert "极致" not in user  # we set traits 冷静/心狠 — sanity check our fixture is present


def test_prompt_with_prior_cast(bb):
    bb.write_yaml(
        "characters-cast.yaml",
        {
            "schema_version": 1,
            "last_updated_chapter": 1,
            "cast": [
                {
                    "name": "老刘",
                    "in_baseline": False,
                    "first_appeared_ch": 1,
                    "last_appeared_ch": 1,
                }
            ],
        },
    )
    bb.write_text("chapters/ch002.md", "老刘又来了。")
    _, user, inputs = CastUpdater()._build_prompts(bb, chapter=2)
    assert "state/characters-cast.yaml" in inputs
    assert "老刘" in user


# ---------- output handling ----------

def test_handle_output_writes_valid_yaml(bb):
    raw = (
        "schema_version: 1\n"
        "last_updated_chapter: 1\n"
        "cast:\n"
        "  - name: 陈默\n"
        "    role: 主角\n"
        "    first_appeared_ch: 1\n"
        "    last_appeared_ch: 1\n"
        "    status: active\n"
        "    in_baseline: true\n"
        "  - name: 老刘\n"
        "    role: 配角\n"
        "    first_appeared_ch: 1\n"
        "    last_appeared_ch: 1\n"
        "    status: active\n"
        "    in_baseline: false\n"
        "notes:\n"
        "  pruning_policy: never delete\n"
    )
    CastUpdater()._handle_output(bb, raw, chapter=1)
    obj = bb.read_yaml("characters-cast.yaml")
    assert obj["schema_version"] == 1
    assert obj["last_updated_chapter"] == 1
    names = [c["name"] for c in obj["cast"]]
    assert "陈默" in names
    assert "老刘" in names
    chen = next(c for c in obj["cast"] if c["name"] == "陈默")
    laoliu = next(c for c in obj["cast"] if c["name"] == "老刘")
    assert chen["in_baseline"] is True
    assert laoliu["in_baseline"] is False


def test_handle_output_strips_yaml_fences(bb):
    raw = (
        "```yaml\n"
        "schema_version: 1\n"
        "last_updated_chapter: 2\n"
        "cast: []\n"
        "```\n"
    )
    CastUpdater()._handle_output(bb, raw, chapter=2)
    obj = bb.read_yaml("characters-cast.yaml")
    assert obj["last_updated_chapter"] == 2
    assert obj["cast"] == []


def test_handle_output_invalid_yaml_does_not_raise(bb):
    """Unrecoverable YAML must NOT raise — it should warn + return so the
    main pipeline can continue (cast updates are bookkeeping, not blocking)."""
    # No prior cast file → file simply isn't created.
    CastUpdater()._handle_output(bb, "this: is: not: valid: yaml: : :", chapter=1)
    assert not bb.exists("characters-cast.yaml")


def test_handle_output_invalid_yaml_keeps_prior_cast(bb):
    """When repair fails, the prior cast file must be left untouched."""
    bb.write_yaml(
        "characters-cast.yaml",
        {"schema_version": 1, "last_updated_chapter": 0, "cast": []},
    )
    CastUpdater()._handle_output(bb, "this: is: not: valid: yaml: : :", chapter=1)
    obj = bb.read_yaml("characters-cast.yaml")
    assert obj["last_updated_chapter"] == 0  # unchanged


def test_handle_output_missing_schema_version_skips(bb):
    raw = "last_updated_chapter: 1\ncast: []\n"
    CastUpdater()._handle_output(bb, raw, chapter=1)
    assert not bb.exists("characters-cast.yaml")


def test_handle_output_missing_cast_skips(bb):
    raw = "schema_version: 1\nlast_updated_chapter: 1\n"
    CastUpdater()._handle_output(bb, raw, chapter=1)
    assert not bb.exists("characters-cast.yaml")


# ---------- end-to-end with mocked LLM ----------

def test_first_run_creates_cast(bb, monkeypatch):
    """ch1 with two new characters → cast file created with 2 entries."""
    bb.write_text(
        "chapters/ch001.md",
        "陈默走进巷子。老刘从拐角探出头说话。后来赵铁城出现。",
    )

    fake_llm_output = """schema_version: 1
last_updated_chapter: 1
cast:
  - name: 陈默
    role: 主角
    first_appeared_ch: 1
    last_appeared_ch: 1
    status: active
    one_line: 主角，冷静心狠
    traits: [冷静, 心狠]
    redlines: []
    relations: []
    voice_tags: []
    aliases: []
    in_baseline: true
  - name: 老刘
    role: 配角
    first_appeared_ch: 1
    last_appeared_ch: 1
    status: active
    one_line: 巷口情报商
    traits: []
    redlines: []
    relations: []
    voice_tags: []
    aliases: []
    in_baseline: false
  - name: 赵铁城
    role: 反派
    first_appeared_ch: 1
    last_appeared_ch: 1
    status: active
    one_line: 对手帮派话事人
    traits: []
    redlines: []
    relations: []
    voice_tags: []
    aliases: []
    in_baseline: false
notes:
  pruning_policy: never delete
"""

    def fake_chat(*, agent_name, **_):
        assert agent_name == "cast_updater"
        return fake_llm_output

    monkeypatch.setattr("src.agents._base.llm.chat", fake_chat)
    CastUpdater().run(bb, chapter=1)

    obj = bb.read_yaml("characters-cast.yaml")
    assert obj["last_updated_chapter"] == 1
    names = sorted(c["name"] for c in obj["cast"])
    assert names == ["老刘", "赵铁城", "陈默"]
    chen = next(c for c in obj["cast"] if c["name"] == "陈默")
    assert chen["in_baseline"] is True
    laoliu = next(c for c in obj["cast"] if c["name"] == "老刘")
    assert laoliu["in_baseline"] is False


def test_subsequent_run_updates_last_appeared(bb, monkeypatch):
    """ch2 with 老刘 returning → first_appeared_ch=1 preserved, last_appeared_ch=2."""
    # Seed prior cast (after ch1)
    bb.write_yaml(
        "characters-cast.yaml",
        {
            "schema_version": 1,
            "last_updated_chapter": 1,
            "cast": [
                {
                    "name": "老刘",
                    "role": "配角",
                    "first_appeared_ch": 1,
                    "last_appeared_ch": 1,
                    "status": "active",
                    "in_baseline": False,
                    "traits": [],
                }
            ],
        },
    )
    bb.write_text("chapters/ch002.md", "老刘再次出现。")

    # LLM returns updated cast where 老刘.last_appeared_ch=2 but first_appeared_ch=1
    fake_output = """schema_version: 1
last_updated_chapter: 2
cast:
  - name: 老刘
    role: 配角
    first_appeared_ch: 1
    last_appeared_ch: 2
    status: active
    in_baseline: false
    traits: []
    redlines: []
    relations: []
    voice_tags: []
    aliases: []
"""
    monkeypatch.setattr("src.agents._base.llm.chat", lambda **_: fake_output)
    CastUpdater().run(bb, chapter=2)

    obj = bb.read_yaml("characters-cast.yaml")
    laoliu = next(c for c in obj["cast"] if c["name"] == "老刘")
    assert laoliu["first_appeared_ch"] == 1  # preserved
    assert laoliu["last_appeared_ch"] == 2  # updated
    assert obj["last_updated_chapter"] == 2


def test_baseline_character_marked_in_baseline_true(bb, monkeypatch):
    """Character in characters.yaml should be flagged in_baseline=true."""
    bb.write_text("chapters/ch001.md", "陈默和老刘对话。")
    fake_output = """schema_version: 1
last_updated_chapter: 1
cast:
  - name: 陈默
    in_baseline: true
    first_appeared_ch: 1
    last_appeared_ch: 1
    status: active
    role: 主角
    traits: [冷静, 心狠]
    redlines: []
    relations: []
    voice_tags: []
    aliases: []
  - name: 老刘
    in_baseline: false
    first_appeared_ch: 1
    last_appeared_ch: 1
    status: active
    role: 配角
    traits: []
    redlines: []
    relations: []
    voice_tags: []
    aliases: []
"""
    monkeypatch.setattr("src.agents._base.llm.chat", lambda **_: fake_output)
    CastUpdater().run(bb, chapter=1)
    obj = bb.read_yaml("characters-cast.yaml")
    flags = {c["name"]: c["in_baseline"] for c in obj["cast"]}
    assert flags["陈默"] is True
    assert flags["老刘"] is False


# ---------- read helper ----------

def test_read_helper_when_present(bb):
    bb.write_text("characters-cast.yaml", "schema_version: 1\ncast: []\n")
    text, inputs = read_characters_cast(bb)
    assert "schema_version" in text
    assert inputs == ["state/characters-cast.yaml"]


def test_read_helper_when_missing(bb):
    text, inputs = read_characters_cast(bb)
    assert "尚无演员表" in text
    assert inputs == []
