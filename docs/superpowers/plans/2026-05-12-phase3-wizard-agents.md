# Phase 3 · 向导 Agents + `create_project` 完整签名

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Phase Goal:**
1. 新增 `OutlineDrafter` agent：吃梗概自由文本，产 `outline.json`
2. 新增 `CharactersDrafter` agent：吃人物简介自由文本，产 `characters.yaml`
3. 扩展 `create_project()` 支持 `outline_synopsis` / `characters_brief` / `from_extract` 参数
4. 在 `src/pipeline.py` 新增 `run_draft_outline(book_id, synopsis)` / `run_draft_characters(book_id, brief)`

**Phase Checkpoint 命令:**
```bash
.venv/bin/python3 -m pytest tests/test_outline_drafter.py tests/test_characters_drafter.py tests/test_bootstrap_book_centric.py tests/test_pipeline_draft.py -v
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py
```

---

## 文件结构

- Create: `src/agents/outline_drafter.py`
- Create: `src/agents/characters_drafter.py`
- Create: `tests/test_outline_drafter.py`
- Create: `tests/test_characters_drafter.py`
- Create: `tests/test_pipeline_draft.py`
- Modify: `src/bootstrap.py`（完善 `create_project` 的 `outline_synopsis` / `characters_brief` / `from_extract` 分支）
- Modify: `tests/test_bootstrap_book_centric.py`（新增 case）
- Modify: `src/pipeline.py`（新增 `run_draft_outline` / `run_draft_characters`）

---

## Task 3.1 · OutlineDrafter agent

**Files:**
- Create: `src/agents/outline_drafter.py`
- Create: `tests/test_outline_drafter.py`

- [ ] **Step 1:** 写 `tests/test_outline_drafter.py`：

```python
"""OutlineDrafter: synopsis (free text) → structured outline.json."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def stub_llm(monkeypatch):
    """Patch the shared LLM client to return a canned JSON string."""
    def fake_chat(messages, **kwargs):
        return {
            "content": json.dumps({
                "title": "Test Book",
                "chapters": [
                    {"index": 1, "title": "Arrival", "beats": ["开场", "建立冲突"]},
                    {"index": 2, "title": "Plot Thickens", "beats": ["反转"]},
                ]
            }, ensure_ascii=False),
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
    monkeypatch.setattr("src.llm.chat", fake_chat)
    return fake_chat


def test_outline_drafter_produces_structured_outline(stub_llm):
    from src.agents.outline_drafter import OutlineDrafter
    agent = OutlineDrafter()
    out = agent.run(
        synopsis="主角从福建来港，加入社团，一年内做大。",
        chapter_count_target=2,
        display_name="Test Book",
    )
    assert out["title"] == "Test Book"
    assert len(out["chapters"]) == 2
    assert out["chapters"][0]["index"] == 1
    assert "beats" in out["chapters"][0]


def test_outline_drafter_empty_synopsis_returns_blank_shell():
    from src.agents.outline_drafter import OutlineDrafter
    agent = OutlineDrafter()
    out = agent.run(synopsis="", chapter_count_target=10, display_name="Blank")
    assert out["title"] == "Blank"
    assert out["chapters"] == []


def test_outline_drafter_falls_back_to_shell_on_bad_json(monkeypatch):
    """If LLM returns non-JSON gibberish, return a blank shell instead of crashing."""
    def bad_chat(messages, **kwargs):
        return {"content": "not valid json at all", "usage": {}}
    monkeypatch.setattr("src.llm.chat", bad_chat)
    from src.agents.outline_drafter import OutlineDrafter
    agent = OutlineDrafter()
    out = agent.run(synopsis="something", chapter_count_target=5, display_name="X")
    assert out["title"] == "X"
    assert isinstance(out["chapters"], list)  # shell, not crash


def test_outline_drafter_enforces_max_chapters(stub_llm):
    """Even if LLM returns more chapters than requested, keep only the first N."""
    # already 2 in stub; request 1 → truncate
    from src.agents.outline_drafter import OutlineDrafter
    agent = OutlineDrafter()
    out = agent.run(synopsis="xxx", chapter_count_target=1, display_name="T")
    assert len(out["chapters"]) == 1
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_outline_drafter.py -v 2>&1 | tail -10
```

- [ ] **Step 3:** 写 `src/agents/outline_drafter.py`：

```python
"""OutlineDrafter — turn a free-text synopsis into a structured outline.json.

Single LLM call. Returns a dict with schema:
  {
    "title": str,
    "chapters": [
      {"index": int, "title": str, "beats": [str, ...]},
      ...
    ]
  }

Fall back to a blank shell if the model misbehaves — the user can always
re-run later via POST /api/projects/<id>/draft-outline.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from src import llm

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一位资深中文小说责编。用户会给你一段"故事梗概"自由文本，请你输出严格的 JSON 章节大纲。

输出 JSON schema（必须严格遵守）：
{
  "title": "<小说标题>",
  "chapters": [
    {"index": 1, "title": "<章节标题>", "beats": ["<节拍 1>", "<节拍 2>"]},
    ...
  ]
}

规则：
1. 只输出 JSON，不要包含 markdown 代码块，不要额外注释。
2. chapters 数量 = 用户指定的 chapter_count_target。
3. 每章至少 2 个 beats，最多 5 个。
4. 若用户给的梗概信息太少，自行合理推演一个完整的章节弧。
"""


class OutlineDrafter:
    """Wraps a single LLM call."""

    def run(self, *, synopsis: str, chapter_count_target: int, display_name: str) -> dict:
        if not synopsis or not synopsis.strip():
            return {"title": display_name, "chapters": []}

        user = (
            f"小说标题：{display_name}\n"
            f"目标章数：{chapter_count_target}\n\n"
            f"故事梗概：\n{synopsis}\n"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        try:
            resp = llm.chat(messages, temperature=0.4)
            raw = resp.get("content") or ""
            # strip accidental markdown fences
            if raw.startswith("```"):
                raw = raw.strip("`").partition("\n")[2].rpartition("```")[0]
            data = json.loads(raw)
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("OutlineDrafter bad JSON, returning shell: %s", exc)
            return {"title": display_name, "chapters": []}

        if not isinstance(data, dict) or "chapters" not in data:
            return {"title": display_name, "chapters": []}

        # Truncate / pad to match target
        chapters = data.get("chapters", [])[:chapter_count_target]
        for i, ch in enumerate(chapters, start=1):
            ch["index"] = i
        return {"title": data.get("title") or display_name, "chapters": chapters}
```

- [ ] **Step 4:** 跑通过确认

```bash
.venv/bin/python3 -m pytest tests/test_outline_drafter.py -v 2>&1 | tail -10
```
Expected: 4 passed

- [ ] **Step 5:** Commit

```bash
git add src/agents/outline_drafter.py tests/test_outline_drafter.py
git commit -m "feat(phase3): OutlineDrafter agent with JSON schema + shell fallback"
```

---

## Task 3.2 · CharactersDrafter agent

**Files:**
- Create: `src/agents/characters_drafter.py`
- Create: `tests/test_characters_drafter.py`

- [ ] **Step 1:** 写 `tests/test_characters_drafter.py`：

```python
"""CharactersDrafter: free-text brief → structured characters.yaml dict."""
from __future__ import annotations

import yaml
import pytest


@pytest.fixture
def stub_llm(monkeypatch):
    canned = {
        "protagonist": {"name": "林家耀", "description": "24 岁, 福建人, 97 年穿越回 1983。"},
        "supporting": [
            {"name": "阿威", "role": "小弟", "description": "跟班。"},
            {"name": "苏婷", "role": "情报线", "description": "记者。"},
        ],
    }
    def fake_chat(messages, **kwargs):
        return {"content": yaml.safe_dump(canned, allow_unicode=True, sort_keys=False)}
    monkeypatch.setattr("src.llm.chat", fake_chat)
    return canned


def test_characters_drafter_produces_protagonist_and_supporting(stub_llm):
    from src.agents.characters_drafter import CharactersDrafter
    out = CharactersDrafter().run(
        brief="主角林家耀 24 岁福建人。阿威是小弟。苏婷是记者。",
        protagonist_name="林家耀",
    )
    assert out["protagonist"]["name"] == "林家耀"
    assert len(out["supporting"]) == 2


def test_characters_drafter_empty_brief_returns_shell():
    from src.agents.characters_drafter import CharactersDrafter
    out = CharactersDrafter().run(brief="", protagonist_name="Hero")
    assert out["protagonist"]["name"] == "Hero"
    assert out["protagonist"]["description"] == ""
    assert out["supporting"] == []


def test_characters_drafter_bad_yaml_falls_back_to_shell(monkeypatch):
    def bad_chat(messages, **kwargs):
        return {"content": "::: not: [yaml"}
    monkeypatch.setattr("src.llm.chat", bad_chat)
    from src.agents.characters_drafter import CharactersDrafter
    out = CharactersDrafter().run(brief="blah", protagonist_name="H")
    assert out["protagonist"]["name"] == "H"
    assert isinstance(out["supporting"], list)


def test_characters_drafter_overrides_protagonist_name(stub_llm):
    """Regardless what LLM says, the protagonist.name must match what user typed in step 1."""
    from src.agents.characters_drafter import CharactersDrafter
    out = CharactersDrafter().run(brief="something", protagonist_name="不同名")
    assert out["protagonist"]["name"] == "不同名"
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_characters_drafter.py -v 2>&1 | tail -10
```

- [ ] **Step 3:** 写 `src/agents/characters_drafter.py`：

```python
"""CharactersDrafter — turn a free-text character brief into characters.yaml.

Single LLM call. Returns dict with schema:
  {
    "protagonist": {"name": str, "description": str, "arc": str (optional)},
    "supporting": [
      {"name": str, "role": str, "description": str},
      ...
    ]
  }

The protagonist.name is always overridden with what the user typed in step 1
of the wizard (authoritative source).
"""
from __future__ import annotations

import logging

import yaml

from src import llm

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是资深中文小说责编。用户给你一段自由文本描述主要人物，请输出严格的 YAML 人物档案。

YAML schema（必须严格遵守）：
protagonist:
  name: "<主角姓名>"
  description: "<两三句人物小传>"
  arc: "<(可选) 人物弧光一句话>"
supporting:
  - name: "<配角 1>"
    role: "<在故事中的功能, 如小弟/情敌/情报线>"
    description: "<两三句>"
  - name: "..."
    role: "..."
    description: "..."

规则：
1. 只输出 YAML，不要 markdown 代码块，不要额外注释。
2. supporting 至少 2 个、最多 8 个。
3. 若简介信息不足，合理扩展。
"""


class CharactersDrafter:
    def run(self, *, brief: str, protagonist_name: str) -> dict:
        shell = {
            "protagonist": {"name": protagonist_name, "description": ""},
            "supporting": [],
        }
        if not brief or not brief.strip():
            return shell

        user = f"主角姓名（请在 protagonist.name 沿用此名）：{protagonist_name}\n\n人物简介：\n{brief}\n"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        try:
            resp = llm.chat(messages, temperature=0.4)
            raw = resp.get("content") or ""
            if raw.startswith("```"):
                raw = raw.strip("`").partition("\n")[2].rpartition("```")[0]
            data = yaml.safe_load(raw)
        except (yaml.YAMLError, KeyError) as exc:
            log.warning("CharactersDrafter bad YAML, returning shell: %s", exc)
            return shell

        if not isinstance(data, dict):
            return shell
        proto = data.get("protagonist") or {}
        # user-typed name wins
        proto["name"] = protagonist_name
        supp = data.get("supporting") or []
        if not isinstance(supp, list):
            supp = []
        return {"protagonist": proto, "supporting": supp}
```

- [ ] **Step 4:** 跑通过确认

```bash
.venv/bin/python3 -m pytest tests/test_characters_drafter.py -v 2>&1 | tail -10
```

- [ ] **Step 5:** Commit

```bash
git add src/agents/characters_drafter.py tests/test_characters_drafter.py
git commit -m "feat(phase3): CharactersDrafter agent with YAML schema + shell fallback"
```

---

## Task 3.3 · 扩展 `create_project` 接 drafter

**Files:**
- Modify: `src/bootstrap.py`
- Modify: `tests/test_bootstrap_book_centric.py`

- [ ] **Step 1:** 追加测试到 `tests/test_bootstrap_book_centric.py`：

```python
def test_create_project_with_outline_synopsis_uses_drafter(fake_repo, monkeypatch):
    from src import bootstrap
    called = {}
    def fake_run(synopsis, chapter_count_target, display_name):
        called.update(synopsis=synopsis, target=chapter_count_target, name=display_name)
        return {"title": display_name, "chapters": [{"index": 1, "title": "C1", "beats": ["a", "b"]}]}
    monkeypatch.setattr(
        "src.agents.outline_drafter.OutlineDrafter.run",
        lambda self, *, synopsis, chapter_count_target, display_name:
            fake_run(synopsis, chapter_count_target, display_name),
    )
    import json
    book_dir = bootstrap.create_project(
        "synopsis-book",
        display_name="By Synopsis",
        protagonist_name="H",
        chapter_count_target=5,
        from_preset="alpha",
        outline_synopsis="主角的故事。",
        blank_characters=True,
    )
    data = json.loads((book_dir / "outline.json").read_text(encoding="utf-8"))
    assert data["title"] == "By Synopsis"
    assert len(data["chapters"]) == 1
    assert called["target"] == 5


def test_create_project_with_characters_brief_uses_drafter(fake_repo, monkeypatch):
    from src import bootstrap
    import yaml
    monkeypatch.setattr(
        "src.agents.characters_drafter.CharactersDrafter.run",
        lambda self, *, brief, protagonist_name: {
            "protagonist": {"name": protagonist_name, "description": "from brief"},
            "supporting": [{"name": "A", "role": "friend", "description": "x"}],
        },
    )
    book_dir = bootstrap.create_project(
        "char-book",
        display_name="D",
        protagonist_name="H",
        chapter_count_target=3,
        from_preset="alpha",
        blank_outline=True,
        characters_brief="主角 H，配角 A。",
    )
    data = yaml.safe_load((book_dir / "characters.yaml").read_text(encoding="utf-8"))
    assert data["protagonist"]["name"] == "H"
    assert data["protagonist"]["description"] == "from brief"
    assert len(data["supporting"]) == 1


def test_create_project_outline_flags_mutually_exclusive(fake_repo):
    from src import bootstrap
    with pytest.raises(ValueError, match="mutually exclusive"):
        bootstrap.create_project(
            "bad1",
            display_name="d",
            protagonist_name="h",
            chapter_count_target=3,
            from_preset="alpha",
            outline_synopsis="x",
            blank_outline=True,
            blank_characters=True,
        )


def test_create_project_characters_flags_mutually_exclusive(fake_repo):
    from src import bootstrap
    with pytest.raises(ValueError, match="mutually exclusive"):
        bootstrap.create_project(
            "bad2",
            display_name="d",
            protagonist_name="h",
            chapter_count_target=3,
            from_preset="alpha",
            blank_outline=True,
            characters_brief="x",
            blank_characters=True,
        )
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_bootstrap_book_centric.py -v 2>&1 | tail -15
```

- [ ] **Step 3:** 修 `src/bootstrap.py` 的 `create_project`：

替换 Phase 2 "outline / characters — phase 2 covers only blank branches" 注释附近的逻辑：

```python
    # --- Outline starter ---
    outline_choices = [bool(outline_synopsis), blank_outline]
    if sum(outline_choices) != 1:
        raise ValueError("Outline starter flags are mutually exclusive; pick exactly one of "
                         "outline_synopsis / blank_outline")
    if outline_synopsis:
        from src.agents.outline_drafter import OutlineDrafter
        outline_data = OutlineDrafter().run(
            synopsis=outline_synopsis,
            chapter_count_target=chapter_count_target,
            display_name=display_name,
        )
        _write_json(project_dir / "outline.json", outline_data)
    else:
        _write_json(project_dir / "outline.json", {"title": display_name, "chapters": []})

    # --- Characters starter ---
    characters_choices = [bool(characters_brief), blank_characters]
    if sum(characters_choices) != 1:
        raise ValueError("Characters starter flags are mutually exclusive; pick exactly one of "
                         "characters_brief / blank_characters")
    if characters_brief:
        from src.agents.characters_drafter import CharactersDrafter
        chars_data = CharactersDrafter().run(
            brief=characters_brief,
            protagonist_name=protagonist_name,
        )
        _write_yaml(project_dir / "characters.yaml", chars_data)
    else:
        _write_yaml(project_dir / "characters.yaml", {
            "protagonist": {"name": protagonist_name, "description": ""},
            "supporting": [],
        })
```

- [ ] **Step 4:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_bootstrap_book_centric.py -v 2>&1 | tail -15
```

- [ ] **Step 5:** Commit

```bash
git add src/bootstrap.py tests/test_bootstrap_book_centric.py
git commit -m "feat(phase3): create_project wires OutlineDrafter/CharactersDrafter via synopsis/brief"
```

---

## Task 3.4 · `run_draft_outline` / `run_draft_characters` 接入 pipeline.py

这些 API 被 Phase 4 的 Web 路由 `POST /api/projects/<id>/draft-outline` 调用，用于**作品创建之后**重生 outline/characters。

**Files:**
- Modify: `src/pipeline.py`
- Create: `tests/test_pipeline_draft.py`

- [ ] **Step 1:** 写 `tests/test_pipeline_draft.py`：

```python
"""run_draft_outline / run_draft_characters: post-creation regeneration."""
from __future__ import annotations

from pathlib import Path

import json
import pytest
import yaml


@pytest.fixture
def prepared_book(tmp_path, monkeypatch):
    from src import config, bootstrap
    # Minimal preset
    preset = tmp_path / "presets" / "alpha"
    preset.mkdir(parents=True)
    for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        (preset / fname).write_text(f"# {fname}\n", encoding="utf-8")
    (preset / "genre.yaml").write_text("id: alpha\n", encoding="utf-8")
    (preset / "novels").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "novels").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")
    bootstrap.create_project(
        "mybook", display_name="B", protagonist_name="H", chapter_count_target=3,
        from_preset="alpha", blank_outline=True, blank_characters=True,
    )
    return tmp_path


def test_run_draft_outline_overwrites_outline_json(prepared_book, monkeypatch):
    monkeypatch.setattr(
        "src.agents.outline_drafter.OutlineDrafter.run",
        lambda self, *, synopsis, chapter_count_target, display_name: {
            "title": display_name,
            "chapters": [{"index": 1, "title": "C1", "beats": ["a"]}],
        },
    )
    from src import pipeline
    out = pipeline.run_draft_outline("mybook", synopsis="some story")
    assert out["chapters"][0]["title"] == "C1"

    book_dir = prepared_book / "projects" / "mybook"
    data = json.loads((book_dir / "outline.json").read_text(encoding="utf-8"))
    assert len(data["chapters"]) == 1


def test_run_draft_characters_overwrites_characters_yaml(prepared_book, monkeypatch):
    monkeypatch.setattr(
        "src.agents.characters_drafter.CharactersDrafter.run",
        lambda self, *, brief, protagonist_name: {
            "protagonist": {"name": protagonist_name, "description": "from brief"},
            "supporting": [{"name": "X", "role": "r", "description": "d"}],
        },
    )
    from src import pipeline
    out = pipeline.run_draft_characters("mybook", brief="people")
    assert len(out["supporting"]) == 1

    book_dir = prepared_book / "projects" / "mybook"
    data = yaml.safe_load((book_dir / "characters.yaml").read_text(encoding="utf-8"))
    assert data["protagonist"]["description"] == "from brief"


def test_run_draft_outline_missing_book_raises(prepared_book):
    from src import pipeline
    with pytest.raises(FileNotFoundError, match="not found"):
        pipeline.run_draft_outline("doesnotexist", synopsis="x")
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_pipeline_draft.py -v 2>&1 | tail -10
```

- [ ] **Step 3:** 在 `src/pipeline.py` 新增：

```python
def run_draft_outline(book_id: str, *, synopsis: str) -> dict:
    """Regenerate outline.json from a synopsis. Also re-bootstraps if active."""
    book_dir = config.PROJECTS_DIR / book_id
    if not book_dir.exists():
        raise FileNotFoundError(f"Project not found: {book_id}")

    with (book_dir / "project.yaml").open(encoding="utf-8") as f:
        import yaml
        pdata = yaml.safe_load(f) or {}
    display_name = pdata.get("display_name") or book_id
    target = int(pdata.get("chapter_count_target", 50))

    from src.agents.outline_drafter import OutlineDrafter
    out = OutlineDrafter().run(
        synopsis=synopsis,
        chapter_count_target=target,
        display_name=display_name,
    )
    import json
    (book_dir / "outline.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    if config.get_active_project_id() == book_id:
        bootstrap_project(book_id, preserve_progress=True)
    return out


def run_draft_characters(book_id: str, *, brief: str) -> dict:
    """Regenerate characters.yaml from a brief. Also re-bootstraps if active."""
    book_dir = config.PROJECTS_DIR / book_id
    if not book_dir.exists():
        raise FileNotFoundError(f"Project not found: {book_id}")

    import yaml
    with (book_dir / "project.yaml").open(encoding="utf-8") as f:
        pdata = yaml.safe_load(f) or {}
    protagonist = pdata.get("protagonist_name") or "TBD"

    from src.agents.characters_drafter import CharactersDrafter
    out = CharactersDrafter().run(brief=brief, protagonist_name=protagonist)
    (book_dir / "characters.yaml").write_text(
        yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    if config.get_active_project_id() == book_id:
        bootstrap_project(book_id, preserve_progress=True)
    return out
```

- [ ] **Step 4:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_pipeline_draft.py -v 2>&1 | tail -10
```
Expected: 3 passed

- [ ] **Step 5:** Commit

```bash
git add src/pipeline.py tests/test_pipeline_draft.py
git commit -m "feat(phase3): pipeline.run_draft_outline/characters regenerates from free text"
```

---

## Task 3.5 · `create_project(from_extract=...)` 分支

**Files:**
- Modify: `src/bootstrap.py`
- Modify: `tests/test_bootstrap_book_centric.py`

当 `from_extract={"sources": [...], "with_trial": bool}` 时：
1. 先 create project with `blank_genre=True`（预留 4 份空壳）
2. 同步（非异步）调 `extract_to_project(book_id, sources, with_trial)` 覆盖 4 份空壳

**重要**：本 task 保持**同步语义**——测试里用 mock。真实使用时 UI 端会在单独后台线程里调用 `create_project` 以避免阻塞（Phase 4 的 Web 路由负责）。

- [ ] **Step 1:** 追加测试：

```python
def test_create_project_from_extract_invokes_extractor(fake_repo, monkeypatch):
    """from_extract branch: blank_genre stubs first, then extract_to_project overwrites."""
    from src import bootstrap
    captured = {}
    def fake_extract(book_id, *, sources, with_trial):
        captured.update(book_id=book_id, sources=list(sources), with_trial=with_trial)
        # simulate extraction producing non-blank content
        book = fake_repo / "projects" / book_id
        (book / "era.md").write_text("# extracted era\n", encoding="utf-8")
        return {"book_id": book_id}
    monkeypatch.setattr("src.genre_extractor.to_project.extract_to_project", fake_extract)

    book_dir = bootstrap.create_project(
        "extract-book",
        display_name="E",
        protagonist_name="H",
        chapter_count_target=3,
        from_extract={"sources": ["novels/a.txt"], "with_trial": False},
        blank_outline=True,
        blank_characters=True,
    )
    assert captured["book_id"] == "extract-book"
    assert captured["sources"] == ["novels/a.txt"]
    assert (book_dir / "era.md").read_text(encoding="utf-8") == "# extracted era\n"


def test_create_project_genre_flags_three_way_exclusive(fake_repo):
    from src import bootstrap
    with pytest.raises(ValueError, match="mutually exclusive"):
        bootstrap.create_project(
            "x", display_name="d", protagonist_name="h", chapter_count_target=3,
            from_preset="alpha",
            from_extract={"sources": ["a.txt"], "with_trial": False},
            blank_outline=True, blank_characters=True,
        )
```

- [ ] **Step 2:** 跑失败

```bash
.venv/bin/python3 -m pytest tests/test_bootstrap_book_centric.py::test_create_project_from_extract_invokes_extractor tests/test_bootstrap_book_centric.py::test_create_project_genre_flags_three_way_exclusive -v 2>&1 | tail -10
```

- [ ] **Step 3:** 修 `src/bootstrap.py` 的 `create_project`：

```python
    # --- Genre starter: now 3-way exclusive ---
    genre_choices = [bool(from_preset), bool(from_extract), blank_genre]
    if sum(genre_choices) != 1:
        raise ValueError(
            "Genre starter flags are mutually exclusive; pick exactly one of "
            "from_preset / from_extract / blank_genre"
        )
    # ... existing from_preset / blank_genre branches ...

    if from_extract:
        # First lay down blanks so the project dir is valid when extractor
        # starts looking at it.
        (project_dir / "era.md").write_text("", encoding="utf-8")
        (project_dir / "writing-style-extra.md").write_text("", encoding="utf-8")
        (project_dir / "iron-laws-extra.md").write_text("", encoding="utf-8")
        # Then run extraction (sync here; Web caller offloads to background thread)
        from src.genre_extractor import to_project
        to_project.extract_to_project(
            project_id,
            sources=from_extract.get("sources", []),
            with_trial=from_extract.get("with_trial", False),
        )
```

**Signature update**（补到 `create_project` 形参）：

```python
def create_project(
    project_id: str,
    *,
    display_name: str,
    protagonist_name: str,
    chapter_count_target: int,
    from_preset: Optional[str] = None,
    from_extract: Optional[dict] = None,  # {"sources": [...], "with_trial": bool}
    blank_genre: bool = False,
    outline_synopsis: Optional[str] = None,
    blank_outline: bool = False,
    characters_brief: Optional[str] = None,
    blank_characters: bool = False,
    overwrite: bool = False,
) -> Path:
```

- [ ] **Step 4:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_bootstrap_book_centric.py -v 2>&1 | tail -15
```

必须全部 pass。

跑大套件：

```bash
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py 2>&1 | tail -15
```

- [ ] **Step 5:** Commit

```bash
git add src/bootstrap.py tests/test_bootstrap_book_centric.py
git commit -m "feat(phase3): create_project(from_extract=...) runs extract_to_project"
```

---

## Task 3.6 · Phase 3 Checkpoint

```bash
set -e
.venv/bin/python3 -m pytest tests/test_outline_drafter.py tests/test_characters_drafter.py tests/test_bootstrap_book_centric.py tests/test_pipeline_draft.py tests/test_extract_to_project.py tests/test_extract_to_preset.py -v
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py
```

**退出码 0 表示 Phase 3 通过，可进 Phase 4。**
