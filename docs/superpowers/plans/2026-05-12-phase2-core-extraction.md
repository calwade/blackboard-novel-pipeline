# Phase 2 · Core 抽取 + to_project / to_preset + Bootstrap 简化

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Phase Goal:**
1. 把 `src/genre_extractor/pipeline.py` 里与"产物落点"解耦的逻辑抽成 `core.py`（纯函数）
2. 新增 `src/genre_extractor/to_project.py`（提取结果写入 `projects/<book-id>/` 根目录）
3. 新增 `src/genre_extractor/to_preset.py`（提取结果写入 `presets/<preset-id>/` 并拷贝勾选的 novel）
4. 简化 `src/bootstrap.py`：单层（无 genre merge），`create_project` 支持 `from_preset`
5. `src/config.py`：`GENRES_DIR` 改为 `PRESETS_DIR`
6. `src/pipeline.py` 新增 `--extract-genre <book-id>` 子命令
7. `src/genre_extractor/__main__.py` CLI 重构为 `--to-preset <id> --sources ...`

**Phase Checkpoint 命令:**
```bash
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py
```

---

## 文件结构

- Create: `src/genre_extractor/core.py`（提取 run_extract / run_merge / run_draft 的解耦版本）
- Create: `src/genre_extractor/to_project.py`
- Create: `src/genre_extractor/to_preset.py`
- Modify: `src/genre_extractor/pipeline.py`（保留 preset 场景的旧入口 `new_genre/fill_genre/audit_genre/extract_from_novel/run_phase`，改为读写 `presets/`；新增内部共享函数委托给 `core.py`）
- Rewrite: `src/genre_extractor/__main__.py`（新 CLI：`--to-preset` / `--fill-preset` / `--audit-preset` / 分阶段 `--*-only`）
- Modify: `src/config.py`（`GENRES_DIR` → `PRESETS_DIR`）
- Rewrite: `src/bootstrap.py`（单层 bootstrap + `create_project(from_preset=...)`）
- Modify: `src/pipeline.py`（新增 `--extract-genre` + `run_extract_genre()`）
- Create: `tests/test_extract_core.py`
- Create: `tests/test_extract_to_project.py`
- Create: `tests/test_extract_to_preset.py`
- Create: `tests/test_bootstrap_book_centric.py`
- Create: `tests/test_pipeline_extract_genre.py`
- Modify: `tests/test_bootstrap_and_settings.py`（解除 Phase 1 的 skip，按新签名改写）
- Modify: `tests/test_setting_lint.py`（若有 `--genre` 分支则去除，新增 `--preset`）
- Modify: `src/tools/setting_lint.py`（同上）
- Modify: `tests/test_genre_pipeline_cli.py`（改名为 `test_genre_extractor_cli.py` 或保留；按新 CLI 断言）

---

## Task 2.1 · 抽 core.py（解耦提取流程）

**Files:**
- Create: `src/genre_extractor/core.py`
- Create: `tests/test_extract_core.py`

- [ ] **Step 1:** 读旧 `src/genre_extractor/pipeline.py` 定位以下函数（它们操作 Blackboard 对象，本身不知道 bb 绑哪个目录）：
  - `_count_chapters_in_text`
  - `_split_text_into_batches`
  - `_run_extract(bb, source_streams)`
  - `_run_merge(bb)` / `_run_merge_concat` / `_run_merge_multitier` / `_parse_batch_id`
  - `_run_draft(bb, build_key)`
  - `_render_files_from_blueprint(bb, build_key, out_dir)` — **改签名**：从原先根据 `build_key` 推出 `presets/<id>/`，改为显式接受 `out_dir` 参数
  - `_run_validate(bb, build_key, *, with_trial, out_dir)` — 同上显式传 out_dir
  - `_apply_fixer_round(bb, build_key, errors)` — 保持
  - `_run_setting_lint(bb, out_dir)` — 改为接受 out_dir

- [ ] **Step 2:** 写 `tests/test_extract_core.py`：

```python
"""Tests for the decoupled extraction core. Exercises functions that operate
purely on a Blackboard, without caring whether the artifacts land in a project
or in a preset.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_count_chapters_in_text_simple():
    from src.genre_extractor.core import count_chapters_in_text
    text = "第一章 abc\n第二章 def\n第三章 ghi\n"
    assert count_chapters_in_text(text) == 3


def test_split_text_into_batches_respects_adaptive(tmp_path: Path):
    from src.genre_extractor.core import split_text_into_batches
    text = "\n".join(f"第{i}章 content" for i in range(1, 31))
    batches = split_text_into_batches(text, batch_size=10)
    assert len(batches) == 3


def test_render_files_from_blueprint_writes_to_custom_dir(tmp_path: Path):
    """render_files_from_blueprint must use the out_dir we pass, not a hard-coded path."""
    from src.genre_extractor.core import render_files_from_blueprint

    blueprint = {
        "era": {"content": "# Era\nyear 1983"},
        "writing_style_extra": {"content": "# Style\nshort sentences"},
        "iron_laws_extra": {"content": "# Laws\n- obey"},
        "resource_schema": None,
    }
    out_dir = tmp_path / "target"
    out_dir.mkdir()
    render_files_from_blueprint(blueprint, out_dir=out_dir)

    assert (out_dir / "era.md").read_text(encoding="utf-8").startswith("# Era")
    assert (out_dir / "writing-style-extra.md").exists()
    assert (out_dir / "iron-laws-extra.md").exists()
    assert not (out_dir / "resource_schema.yaml").exists()


def test_render_files_writes_resource_schema_when_present(tmp_path: Path):
    from src.genre_extractor.core import render_files_from_blueprint
    blueprint = {
        "era": {"content": "# E"},
        "writing_style_extra": {"content": "# S"},
        "iron_laws_extra": {"content": "# L"},
        "resource_schema": {"resources": [{"name": "gold", "unit": "coin"}]},
    }
    render_files_from_blueprint(blueprint, out_dir=tmp_path)
    schema_text = (tmp_path / "resource_schema.yaml").read_text(encoding="utf-8")
    assert "gold" in schema_text
```

- [ ] **Step 3:** 跑失败确认（`core.py` 不存在）

```bash
.venv/bin/python3 -m pytest tests/test_extract_core.py -v 2>&1 | tail -10
```

- [ ] **Step 4:** 写 `src/genre_extractor/core.py`：

把旧 `pipeline.py` 里可复用的纯函数移到 `core.py`，签名改为接受显式 `out_dir`。保留关键函数：

```python
"""Genre extraction core — pure functions that produce extraction artifacts.

These functions are oblivious to whether artifacts end up in a project or a
preset. Callers (to_project.py / to_preset.py / pipeline.py legacy preset
entry points) pass an out_dir explicitly.
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Iterable

from src.blackboard import Blackboard
# Import agents / auditors — unchanged from the old module layout.
from src.genre_extractor.agents.extractor import GenreExtractor
from src.genre_extractor.agents.drafter import GenreDrafter
from src.genre_extractor.agents.validator import GenreValidator
from src.genre_extractor.agents.fixer import GenreFixer
from src.genre_extractor.agents.arc_merger import GenreArcMerger
from src.genre_extractor.agents.book_distiller import GenreBookDistiller
from src.genre_extractor.adaptive import choose_batch_size
from src.genre_extractor.chapter_detector import detect_chapter_format
from src.genre_extractor.chapter_stream import ChapterStream
from src.genre_extractor.tally import write_tally


# --- Plumbing helpers extracted verbatim from the old pipeline.py ---

def count_chapters_in_text(text: str) -> int:
    # copy from old _count_chapters_in_text
    ...


def split_text_into_batches(text: str, *, batch_size: int = 25) -> list[str]:
    # copy from old _split_text_into_batches (remove leading underscore)
    ...


def run_extract(bb: Blackboard, source_streams: Iterable) -> None:
    # copy from old _run_extract
    ...


def run_merge(bb: Blackboard) -> dict:
    # copy from old _run_merge and its callees (_parse_batch_id, _run_merge_concat,
    # _run_merge_multitier) — keep internal helpers module-private
    ...


def run_draft(bb: Blackboard, build_key: str) -> dict:
    # copy from old _run_draft — `build_key` is only used for logging/build dir
    ...


def render_files_from_blueprint(blueprint: dict, *, out_dir: Path) -> list[Path]:
    """Write era.md / writing-style-extra.md / iron-laws-extra.md + optional
    resource_schema.yaml to out_dir. Creates out_dir if missing.

    Returns a list of paths written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    mapping = {
        "era": "era.md",
        "writing_style_extra": "writing-style-extra.md",
        "iron_laws_extra": "iron-laws-extra.md",
    }
    for key, fname in mapping.items():
        node = blueprint.get(key) or {}
        content = node.get("content", "")
        path = out_dir / fname
        path.write_text(content, encoding="utf-8")
        written.append(path)

    schema = blueprint.get("resource_schema")
    if schema:
        path = out_dir / "resource_schema.yaml"
        path.write_text(yaml.safe_dump(schema, allow_unicode=True, sort_keys=False), encoding="utf-8")
        written.append(path)
    else:
        # purge stale schema file if out_dir had one from a prior run
        stale = out_dir / "resource_schema.yaml"
        if stale.exists():
            stale.unlink()

    return written


def run_validate(bb: Blackboard, build_key: str, *, out_dir: Path, with_trial: bool = False) -> dict:
    # copy from old _run_validate, pass out_dir into _run_setting_lint's caller
    ...


def apply_fixer_round(bb: Blackboard, build_key: str, errors: list) -> None:
    # copy from old _apply_fixer_round verbatim
    ...


def run_setting_lint(bb: Blackboard, *, out_dir: Path) -> list[dict]:
    """Run the setting-lint audit against a rendered preset/project dir."""
    # copy from old _run_setting_lint with path mutated to use out_dir
    ...


def build_dir_for(base: Path) -> Path:
    """Return the `.build` / `.extract_build` working dir under an arbitrary base.

    Caller decides base — presets/<id>/ or projects/<id>/state/.
    """
    build = base / ".build"
    if not build.exists():
        build = base / ".extract_build"
    return build
```

**对老 `pipeline.py` 的改造**：在 `pipeline.py` 中保留旧函数名作为 thin wrappers（内部 `from src.genre_extractor import core` 并 delegate），**直到 Task 2.5 的 pipeline.py 重写**才移除这些 wrapper。

核心逻辑迁移后，旧 `pipeline.py` 的"写 `presets/<id>/` 的 3 个 md 文件"逻辑改用 `core.render_files_from_blueprint(blueprint, out_dir=presets_dir)`。

- [ ] **Step 5:** 跑通过确认

```bash
.venv/bin/python3 -m pytest tests/test_extract_core.py -v 2>&1 | tail -10
```
Expected: `4 passed`

跑既存的题材提取测试确认没破坏旧行为：

```bash
.venv/bin/python3 -m pytest tests/ -x -q -k "genre_extractor or extract" 2>&1 | tail -15
```

- [ ] **Step 6:** Commit

```bash
git add src/genre_extractor/core.py src/genre_extractor/pipeline.py tests/test_extract_core.py
git commit -m "refactor(phase2): extract genre_extractor/core with out_dir-explicit helpers"
```

---

## Task 2.2 · 写 `to_preset.py`

**Files:**
- Create: `src/genre_extractor/to_preset.py`
- Create: `tests/test_extract_to_preset.py`

- [ ] **Step 1:** 写 `tests/test_extract_to_preset.py`：

```python
"""Extract a genre pack into presets/<preset-id>/."""
from __future__ import annotations

from pathlib import Path
import shutil

import pytest


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch):
    from src import config
    (tmp_path / "presets").mkdir()
    (tmp_path / "novels").mkdir()
    (tmp_path / "novels" / "a.txt").write_text("第一章 open\n", encoding="utf-8")
    (tmp_path / "novels" / "b.txt").write_text("第一章 inner\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    return tmp_path


def test_extract_to_preset_creates_preset_dir(fake_repo, monkeypatch):
    from src.genre_extractor import to_preset
    # Patch the core pipeline to produce a canned blueprint without calling LLMs.
    monkeypatch.setattr(
        to_preset, "_run_full_extraction_to_blueprint",
        lambda bb, sources: {
            "era": {"content": "# Era stub"},
            "writing_style_extra": {"content": "# Style stub"},
            "iron_laws_extra": {"content": "# Laws stub"},
            "resource_schema": None,
        },
    )

    result = to_preset.extract_to_preset(
        preset_id="myp",
        sources=["a.txt", "b.txt"],
    )

    preset = fake_repo / "presets" / "myp"
    assert (preset / "genre.yaml").exists()
    assert (preset / "era.md").read_text(encoding="utf-8") == "# Era stub"
    assert (preset / "novels" / "a.txt").read_text(encoding="utf-8") == "第一章 open\n"
    assert (preset / "novels" / "b.txt").exists()
    assert result["preset_id"] == "myp"


def test_extract_to_preset_refuses_existing_preset(fake_repo):
    from src.genre_extractor import to_preset
    # Pre-create preset directory
    (fake_repo / "presets" / "exists").mkdir()
    (fake_repo / "presets" / "exists" / "genre.yaml").write_text("id: exists\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        to_preset.extract_to_preset(preset_id="exists", sources=["a.txt"])


def test_extract_to_preset_resolves_source_paths_via_pool(fake_repo, monkeypatch):
    """Both 'a.txt' and 'novels/a.txt' and absolute paths must resolve."""
    from src.genre_extractor import to_preset
    captured = {}
    monkeypatch.setattr(
        to_preset, "_run_full_extraction_to_blueprint",
        lambda bb, sources: (captured.setdefault("sources", sources) or {
            "era": {"content": "e"}, "writing_style_extra": {"content": "s"},
            "iron_laws_extra": {"content": "l"}, "resource_schema": None,
        }),
    )
    to_preset.extract_to_preset(
        preset_id="p2",
        sources=["a.txt", "novels/b.txt"],
    )
    sources = captured["sources"]
    assert all(str(p).endswith((".txt",)) and Path(p).exists() for p in sources)
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_extract_to_preset.py -v 2>&1 | tail -15
```

- [ ] **Step 3:** 写 `src/genre_extractor/to_preset.py`：

```python
"""Extract a genre pack into presets/<preset-id>/.

Sources come from the global novels/ pool (or absolute paths). Selected
sources are copied into presets/<preset-id>/novels/ so the preset is
self-describing.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from src import config
from src.blackboard import Blackboard
from src.genre_extractor import core


def _resolve_source(path_str: str) -> Path:
    """Resolve source path: absolute → as-is; relative → tried under novels/ first,
    then under project root."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    # prefix with novels/ if not already prefixed
    if p.parts and p.parts[0] == "novels":
        return config.PROJECT_ROOT / p
    cand = config.PROJECT_ROOT / "novels" / p
    if cand.exists():
        return cand
    return config.PROJECT_ROOT / p  # fallback


def _run_full_extraction_to_blueprint(bb: Blackboard, sources: list[Path]) -> dict:
    """Drive the core pipeline end-to-end; return the final blueprint dict.

    Extracted into its own function so tests can monkeypatch to avoid LLMs.
    """
    streams = [open(p, "r", encoding="utf-8") for p in sources]
    try:
        core.run_extract(bb, streams)
    finally:
        for s in streams:
            s.close()
    core.run_merge(bb)
    return core.run_draft(bb, build_key=str(bb.root))


def extract_to_preset(
    preset_id: str,
    *,
    sources: list[str],
    with_trial: bool = False,
) -> dict:
    """Run the extraction pipeline; write preset artifacts.

    Refuses to overwrite an existing preset — presets are append-only in this
    system. Use a new preset_id or delete the old one first.
    """
    preset_dir = config.PRESETS_DIR / preset_id
    if preset_dir.exists():
        raise FileExistsError(f"Preset already exists: {preset_id}")

    resolved_sources = [_resolve_source(s) for s in sources]
    for p in resolved_sources:
        if not p.exists():
            raise FileNotFoundError(f"Source not found: {p}")

    preset_dir.mkdir(parents=True)
    (preset_dir / "novels").mkdir()
    build_dir = preset_dir / ".build"
    build_dir.mkdir()

    bb = Blackboard(root=build_dir)
    blueprint = _run_full_extraction_to_blueprint(bb, resolved_sources)
    core.render_files_from_blueprint(blueprint, out_dir=preset_dir)

    # seed genre.yaml with minimum metadata
    (preset_dir / "genre.yaml").write_text(
        yaml.safe_dump(
            {"id": preset_id, "display_name": preset_id, "extracted_from": [p.name for p in resolved_sources]},
            allow_unicode=True, sort_keys=False,
        ),
        encoding="utf-8",
    )

    # copy sources into preset's novels/
    for p in resolved_sources:
        shutil.copy2(p, preset_dir / "novels" / p.name)

    result = {"preset_id": preset_id, "sources": [str(p) for p in resolved_sources]}
    if with_trial:
        from src.genre_extractor import trial
        result["trial"] = trial.run_trial_against_preset(preset_id)
    return result
```

**同步改 config.py**：追加 `PRESETS_DIR`。若 `GENRES_DIR` 还在，改为指向 `presets/`（别名），但新代码全部用 `PRESETS_DIR`。

- [ ] **Step 4:** 改 `src/config.py`：

把原来
```python
GENRES_DIR: Path = _PROJECT_ROOT / "genres"
```
改为
```python
PRESETS_DIR: Path = _PROJECT_ROOT / "presets"
GENRES_DIR: Path = PRESETS_DIR  # Deprecated alias, kept only to avoid breaking imports in this phase
```

同时更新顶部 docstring 去掉"Layering model (refactored 2026-05-11)"这类段落；改为描述 book-centric 单层模型。

- [ ] **Step 5:** 跑通过确认

```bash
.venv/bin/python3 -m pytest tests/test_extract_to_preset.py -v 2>&1 | tail -10
```
Expected: 3 passed

- [ ] **Step 6:** Commit

```bash
git add src/genre_extractor/to_preset.py src/config.py tests/test_extract_to_preset.py
git commit -m "feat(phase2): extract_to_preset + config.PRESETS_DIR"
```

---

## Task 2.3 · 写 `to_project.py`

**Files:**
- Create: `src/genre_extractor/to_project.py`
- Create: `tests/test_extract_to_project.py`

- [ ] **Step 1:** 写 `tests/test_extract_to_project.py`：

```python
"""Extract a genre pack into projects/<book-id>/ (overwriting that book's 4 genre files)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch):
    from src import config
    # Set up a book
    book = tmp_path / "projects" / "mybook"
    book.mkdir(parents=True)
    (book / "project.yaml").write_text("id: mybook\nprotagonist_name: hero\n", encoding="utf-8")
    (book / "outline.json").write_text("{}", encoding="utf-8")
    (book / "characters.yaml").write_text("{}", encoding="utf-8")
    (book / "timeline.yaml").write_text("{}", encoding="utf-8")
    (book / "era.md").write_text("old era\n", encoding="utf-8")
    (book / "writing-style-extra.md").write_text("old style\n", encoding="utf-8")
    (book / "iron-laws-extra.md").write_text("old laws\n", encoding="utf-8")
    (book / "state").mkdir()

    (tmp_path / "novels").mkdir()
    (tmp_path / "novels" / "a.txt").write_text("第一章 a\n", encoding="utf-8")

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path


def test_extract_to_project_overwrites_genre_files(fake_repo, monkeypatch):
    from src.genre_extractor import to_project
    monkeypatch.setattr(
        to_project, "_run_full_extraction_to_blueprint",
        lambda bb, sources: {
            "era": {"content": "# new era"},
            "writing_style_extra": {"content": "# new style"},
            "iron_laws_extra": {"content": "# new laws"},
            "resource_schema": None,
        },
    )
    result = to_project.extract_to_project(
        book_id="mybook",
        sources=["a.txt"],
    )
    book = fake_repo / "projects" / "mybook"
    assert (book / "era.md").read_text(encoding="utf-8") == "# new era"
    assert (book / "writing-style-extra.md").read_text(encoding="utf-8") == "# new style"
    assert result["book_id"] == "mybook"


def test_extract_to_project_backs_up_previous_files(fake_repo, monkeypatch):
    from src.genre_extractor import to_project
    monkeypatch.setattr(
        to_project, "_run_full_extraction_to_blueprint",
        lambda bb, sources: {
            "era": {"content": "# new"}, "writing_style_extra": {"content": "s"},
            "iron_laws_extra": {"content": "l"}, "resource_schema": None,
        },
    )
    to_project.extract_to_project(book_id="mybook", sources=["a.txt"])
    backup_dir = fake_repo / "projects" / "mybook" / "state" / ".backup"
    # era.md was "old era\n" before — must be preserved
    backups = list(backup_dir.glob("era*.md"))
    assert backups, "no backup file for era.md created"
    assert any("old era" in p.read_text(encoding="utf-8") for p in backups)


def test_extract_to_project_missing_book_raises(fake_repo):
    from src.genre_extractor import to_project
    with pytest.raises(FileNotFoundError, match="Project not found"):
        to_project.extract_to_project(book_id="does-not-exist", sources=["a.txt"])
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_extract_to_project.py -v 2>&1 | tail -10
```

- [ ] **Step 3:** 写 `src/genre_extractor/to_project.py`：

```python
"""Extract a genre pack into projects/<book-id>/ (overwriting that book's
4 genre files, with backup of the previous versions).

Sources resolve via the same rules as to_preset (pool-first, absolute ok).
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from src import config
from src.blackboard import Blackboard
from src.genre_extractor import core
from src.genre_extractor.to_preset import _resolve_source

GENRE_FILES = ("era.md", "writing-style-extra.md", "iron-laws-extra.md", "resource_schema.yaml")


def _run_full_extraction_to_blueprint(bb: Blackboard, sources: list[Path]) -> dict:
    """Drive the core pipeline end-to-end; return the final blueprint dict."""
    streams = [open(p, "r", encoding="utf-8") for p in sources]
    try:
        core.run_extract(bb, streams)
    finally:
        for s in streams:
            s.close()
    core.run_merge(bb)
    return core.run_draft(bb, build_key=str(bb.root))


def extract_to_project(
    book_id: str,
    *,
    sources: list[str],
    with_trial: bool = False,
) -> dict:
    """Run the extraction pipeline; overwrite this book's 4 genre files in
    place. Prior file contents are backed up under state/.backup/.
    """
    book_dir = config.PROJECTS_DIR / book_id
    if not book_dir.exists():
        raise FileNotFoundError(f"Project not found: {book_id}")

    resolved = [_resolve_source(s) for s in sources]
    for p in resolved:
        if not p.exists():
            raise FileNotFoundError(f"Source not found: {p}")

    state_dir = book_dir / "state"
    state_dir.mkdir(exist_ok=True)
    backup_dir = state_dir / ".backup"
    backup_dir.mkdir(exist_ok=True)
    build_dir = state_dir / ".extract_build"
    build_dir.mkdir(exist_ok=True)

    # Backup existing genre files
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    for fname in GENRE_FILES:
        src = book_dir / fname
        if src.exists():
            stem, sep, ext = fname.partition(".")
            shutil.copy2(src, backup_dir / f"{stem}.{ts}.{ext}")

    # Run extraction
    bb = Blackboard(root=build_dir)
    blueprint = _run_full_extraction_to_blueprint(bb, resolved)
    core.render_files_from_blueprint(blueprint, out_dir=book_dir)

    result = {"book_id": book_id, "sources": [str(p) for p in resolved]}
    if with_trial:
        from src.genre_extractor import trial
        result["trial"] = trial.run_trial_against_project(book_id)
    return result
```

- [ ] **Step 4:** 跑通过确认

```bash
.venv/bin/python3 -m pytest tests/test_extract_to_project.py -v 2>&1 | tail -10
```
Expected: 3 passed

- [ ] **Step 5:** Commit

```bash
git add src/genre_extractor/to_project.py tests/test_extract_to_project.py
git commit -m "feat(phase2): extract_to_project with backup of prior genre files"
```

---

## Task 2.4 · 简化 bootstrap.py

**Files:**
- Rewrite: `src/bootstrap.py`（主要函数）
- Create: `tests/test_bootstrap_book_centric.py`
- Modify: `tests/test_bootstrap_and_settings.py`（解除 Phase 1 的 skip，改写按新签名）

- [ ] **Step 1:** 写 `tests/test_bootstrap_book_centric.py`：

```python
"""Single-layer bootstrap + create_project(from_preset=...)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch):
    from src import config
    # Set up a preset
    preset = tmp_path / "presets" / "alpha"
    preset.mkdir(parents=True)
    (preset / "genre.yaml").write_text("id: alpha\ndisplay_name: Alpha\ntone: dark\n", encoding="utf-8")
    (preset / "era.md").write_text("# alpha era\n", encoding="utf-8")
    (preset / "writing-style-extra.md").write_text("# alpha style\n", encoding="utf-8")
    (preset / "iron-laws-extra.md").write_text("# alpha laws\n", encoding="utf-8")
    (preset / "resource_schema.yaml").write_text("resources: []\n", encoding="utf-8")
    (preset / "novels").mkdir()

    (tmp_path / "projects").mkdir()
    (tmp_path / "novels").mkdir()

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PRESETS_DIR", tmp_path / "presets")
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "ACTIVE_POINTER", tmp_path / "projects" / ".active")
    return tmp_path


def test_create_project_from_preset_copies_4_genre_files(fake_repo):
    from src.bootstrap import create_project
    book_dir = create_project(
        "mybook",
        display_name="My Book",
        protagonist_name="Hero",
        chapter_count_target=50,
        from_preset="alpha",
    )
    for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md", "resource_schema.yaml"):
        assert (book_dir / fname).exists()
    data = yaml.safe_load((book_dir / "project.yaml").read_text(encoding="utf-8"))
    assert data["source_preset"] == "alpha"
    assert data["protagonist_name"] == "Hero"


def test_create_project_blank_genre(fake_repo):
    from src.bootstrap import create_project
    book_dir = create_project(
        "blankbook",
        display_name="Blank",
        protagonist_name="H",
        chapter_count_target=10,
        blank_genre=True,
    )
    for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        p = book_dir / fname
        assert p.exists()
        # Blank stub — empty or one-liner placeholder
        assert len(p.read_text(encoding="utf-8")) < 200
    assert not (book_dir / "resource_schema.yaml").exists()


def test_bootstrap_project_single_layer(fake_repo):
    """Bootstrap must NOT look at any genres/ dir — just copy projects/<id>/
    files into state/ and synthesize setting.yaml."""
    from src.bootstrap import create_project, bootstrap_project
    create_project(
        "mybook",
        display_name="My Book",
        protagonist_name="Hero",
        chapter_count_target=50,
        from_preset="alpha",
        blank_outline=True,
        blank_characters=True,
    )
    result = bootstrap_project("mybook")

    state = fake_repo / "projects" / "mybook" / "state"
    for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md", "setting.yaml",
                  "outline.json", "characters.yaml", "timeline.yaml"):
        assert (state / fname).exists(), f"{fname} missing"

    setting = yaml.safe_load((state / "setting.yaml").read_text(encoding="utf-8"))
    assert setting["id"] == "mybook"
    assert setting["active_project"] == "mybook"
    # No leftover "active_genre" field from the old layering
    assert "active_genre" not in setting


def test_bootstrap_refuses_missing_preset(fake_repo):
    from src.bootstrap import create_project
    with pytest.raises(FileNotFoundError, match="preset"):
        create_project(
            "x",
            display_name="X",
            protagonist_name="H",
            chapter_count_target=10,
            from_preset="nonexistent",
        )


def test_create_project_rejects_duplicate_preset_and_blank(fake_repo):
    """Flags must be mutually exclusive."""
    from src.bootstrap import create_project
    with pytest.raises(ValueError, match="mutually exclusive"):
        create_project(
            "dup",
            display_name="D",
            protagonist_name="H",
            chapter_count_target=10,
            from_preset="alpha",
            blank_genre=True,
        )
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_bootstrap_book_centric.py -v 2>&1 | tail -15
```

- [ ] **Step 3:** 重写 `src/bootstrap.py`。主要变化：
  - 移除 `GENRE_REQUIRED_FILES` / `GENRE_OPTIONAL_FILES` / `validate_genre`
  - `bootstrap_project` 不再读 `genres/`；只拷 `projects/<id>/` 自己根目录下的所有（`era.md` / `writing-style-extra.md` / `iron-laws-extra.md` / `resource_schema.yaml`(可选) / `outline.json` / `characters.yaml` / `timeline.yaml`）到 `state/`
  - `setting.yaml` 的合成只基于 `project.yaml`
  - `create_project` 签名按 spec §5.2 扩展为 4 步向导落地函数；本 task **只实现 from_preset / blank_genre / blank_outline / blank_characters 4 个分支**；`from_extract` / `outline_synopsis` / `characters_brief` 留给 Phase 3
  - 新增 `list_presets()` 替代 `list_genres()`

```python
"""Single-layer bootstrap.

Each project owns its own genre files (era.md, writing-style-extra.md,
iron-laws-extra.md, optional resource_schema.yaml) directly under its project
directory. Bootstrap just copies that tree into projects/<id>/state/ and
synthesizes setting.yaml from project.yaml.

Presets (presets/<id>/) are **only** consumed by create_project(from_preset=...)
as a seed template. Runtime code never reads presets/.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from src import config


# Required files that must live directly under projects/<id>/
REQUIRED_PROJECT_FILES = (
    "project.yaml",
    "outline.json",
    "characters.yaml",
    "timeline.yaml",
    "era.md",
    "writing-style-extra.md",
    "iron-laws-extra.md",
)
OPTIONAL_PROJECT_FILES = ("resource_schema.yaml",)


def _validate_id(kind: str, value: str) -> None:
    import re
    if not re.match(r"^[a-z0-9][a-z0-9_-]{0,62}$", value):
        raise ValueError(f"Invalid {kind} id: {value!r}")


@dataclass
class BootstrapResult:
    project_id: str
    source_preset: Optional[str]
    state_dir: Path
    project_dir: Path
    copied_files: list[str] = field(default_factory=list)


def list_presets() -> list[str]:
    if not config.PRESETS_DIR.exists():
        return []
    return sorted(p.name for p in config.PRESETS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def list_projects() -> list[str]:
    if not config.PROJECTS_DIR.exists():
        return []
    return sorted(
        p.name for p in config.PROJECTS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".") and (p / "project.yaml").exists()
    )


def validate_project(project_dir: Path) -> list[str]:
    return [f for f in REQUIRED_PROJECT_FILES if not (project_dir / f).exists()]


def empty_progress() -> dict:
    return {
        "current_chapter": 0,
        "completed_chapters": [],
        "in_flight": None,
        "last_update": None,
        "total_llm_calls": 0,
    }


def bootstrap_project(project_id: str, *, preserve_progress: bool = False) -> BootstrapResult:
    _validate_id("project", project_id)
    project_dir = config.PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise FileNotFoundError(
            f"Project not found: {project_dir}. "
            f"Known projects: {', '.join(list_projects()) or '(none)'}"
        )
    missing = validate_project(project_dir)
    if missing:
        raise ValueError(
            f"Project '{project_id}' is incomplete. Missing files:\n  - " + "\n  - ".join(missing)
        )

    project_yaml = yaml.safe_load((project_dir / "project.yaml").read_text(encoding="utf-8"))
    source_preset = project_yaml.get("source_preset")  # may be None for hand-built projects

    state_dir = project_dir / "state"
    state_dir.mkdir(exist_ok=True)
    for sub in ("chapters", "summaries", "fixes"):
        (state_dir / sub).mkdir(exist_ok=True)

    copied: list[str] = []
    for fname in REQUIRED_PROJECT_FILES:
        if fname == "project.yaml":
            continue  # merged into setting.yaml below
        shutil.copy2(project_dir / fname, state_dir / fname)
        copied.append(fname)
    for fname in OPTIONAL_PROJECT_FILES:
        src = project_dir / fname
        dst = state_dir / fname
        if src.exists():
            shutil.copy2(src, dst)
            copied.append(fname)
        elif dst.exists():
            dst.unlink()

    # Synthesize setting.yaml — just project metadata + runtime tags.
    merged = dict(project_yaml)
    merged["active_project"] = project_id
    merged["bootstrapped_at"] = datetime.now().isoformat(timespec="seconds")
    _write_yaml(state_dir / "setting.yaml", merged)
    copied.append("setting.yaml (synthesized)")

    # Progress
    progress_path = state_dir / "progress.json"
    if preserve_progress and progress_path.exists():
        try:
            existing = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        base = {
            "current_chapter": existing.get("current_chapter", 0),
            "completed_chapters": existing.get("completed_chapters", []),
            "in_flight": existing.get("in_flight"),
            "last_update": existing.get("last_update"),
            "total_llm_calls": existing.get("total_llm_calls", 0),
        }
    else:
        base = empty_progress()
    _write_json(progress_path, {**base, "active_project": project_id,
                                "bootstrapped_at": merged["bootstrapped_at"]})

    for f in ("issues.jsonl", "debt.jsonl"):
        p = state_dir / f
        if not p.exists():
            p.touch()

    config.set_active_project_id(project_id)
    config.refresh_state_dir()

    return BootstrapResult(
        project_id=project_id,
        source_preset=source_preset,
        state_dir=state_dir,
        project_dir=project_dir,
        copied_files=copied,
    )


def create_project(
    project_id: str,
    *,
    display_name: str,
    protagonist_name: str,
    chapter_count_target: int,
    from_preset: Optional[str] = None,
    blank_genre: bool = False,
    outline_synopsis: Optional[str] = None,
    blank_outline: bool = False,
    characters_brief: Optional[str] = None,
    blank_characters: bool = False,
    overwrite: bool = False,
) -> Path:
    _validate_id("project", project_id)

    # Genre starter: mutually exclusive
    genre_choices = [bool(from_preset), blank_genre]
    if sum(genre_choices) != 1:
        raise ValueError("Genre starter flags are mutually exclusive; pick exactly one of "
                         "from_preset / blank_genre (from_extract deferred to phase 3)")

    project_dir = config.PROJECTS_DIR / project_id
    if project_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Project already exists: {project_dir}")
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True)

    # project.yaml
    _write_yaml(project_dir / "project.yaml", {
        "id": project_id,
        "display_name": display_name,
        "protagonist_name": protagonist_name,
        "chapter_count_target": chapter_count_target,
        "source_preset": from_preset,  # may be None
    })

    # Genre files
    if from_preset:
        preset_dir = config.PRESETS_DIR / from_preset
        if not preset_dir.exists():
            shutil.rmtree(project_dir)
            raise FileNotFoundError(f"preset not found: {from_preset}")
        for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
            shutil.copy2(preset_dir / fname, project_dir / fname)
        if (preset_dir / "resource_schema.yaml").exists():
            shutil.copy2(preset_dir / "resource_schema.yaml", project_dir / "resource_schema.yaml")
    elif blank_genre:
        (project_dir / "era.md").write_text(f"# Era for {display_name}\n\n(TODO: fill in the era pack.)\n", encoding="utf-8")
        (project_dir / "writing-style-extra.md").write_text("# Writing style\n\n(TODO.)\n", encoding="utf-8")
        (project_dir / "iron-laws-extra.md").write_text("# Iron laws\n\n(TODO.)\n", encoding="utf-8")

    # Outline / characters — phase 2 covers only the "blank" branches
    if blank_outline or outline_synopsis is None:
        _write_json(project_dir / "outline.json", {
            "title": display_name,
            "chapters": [],
        })
    # If outline_synopsis provided, phase 3's OutlineDrafter will be wired in later.

    if blank_characters or characters_brief is None:
        _write_yaml(project_dir / "characters.yaml", {
            "protagonist": {"name": protagonist_name, "description": ""},
            "supporting": [],
        })

    _write_yaml(project_dir / "timeline.yaml", {"events": []})

    return project_dir


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Novelforge bootstrap (book-centric)")
    p.add_argument("--list", action="store_true")
    p.add_argument("--list-presets", action="store_true")
    p.add_argument("--project", metavar="ID")
    p.add_argument("--new-project", metavar="ID")
    p.add_argument("--preset", metavar="ID", help="(with --new-project) the preset to seed from")
    p.add_argument("--blank-genre", action="store_true")
    p.add_argument("--display-name", default=None)
    p.add_argument("--protagonist", default="TBD")
    p.add_argument("--chapters", type=int, default=50)
    args = p.parse_args()

    if args.list_presets:
        for pid in list_presets():
            print(pid)
        return
    if args.list:
        for pid in list_projects():
            print(pid)
        return
    if args.new_project:
        if not (args.preset or args.blank_genre):
            p.error("--new-project requires --preset <id> OR --blank-genre")
        path = create_project(
            args.new_project,
            display_name=args.display_name or args.new_project,
            protagonist_name=args.protagonist,
            chapter_count_target=args.chapters,
            from_preset=args.preset if not args.blank_genre else None,
            blank_genre=args.blank_genre,
            blank_outline=True,
            blank_characters=True,
        )
        print(str(path))
        return
    if args.project:
        result = bootstrap_project(args.project)
        print(f"active: {result.project_id}")
        return
    p.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_bootstrap_book_centric.py -v 2>&1 | tail -15
```
Expected: 5 passed

- [ ] **Step 5:** 修 `tests/test_bootstrap_and_settings.py`（Phase 1 标了 skip 的那些）

打开文件，找到每个有 `@pytest.mark.skip(reason="awaiting phase 2 bootstrap rewrite")` 的测试。对每个：
  - 如果测试逻辑是验证旧的 genres/ 层，**删除整个测试**（新架构没这个概念）
  - 如果测试验证 bootstrap 的 state/ 产物，改签名：改用 `create_project(from_preset=..., blank_outline=True, blank_characters=True)` 准备环境，再调 `bootstrap_project`

关键：跑完 `.venv/bin/python3 -m pytest tests/test_bootstrap_and_settings.py -v`，所有 case 必须 PASS（无 skip）。

- [ ] **Step 6:** 跑既存大套件

```bash
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py 2>&1 | tail -20
```

必须通过。若有其他测试因 bootstrap 签名变化失败，本任务内修好（例如 `test_config_reload.py` 若用到旧签名）。

- [ ] **Step 7:** Commit

```bash
git add src/bootstrap.py tests/test_bootstrap_book_centric.py tests/test_bootstrap_and_settings.py tests/
git commit -m "refactor(phase2): single-layer bootstrap + create_project(from_preset|blank_genre)"
```

---

## Task 2.5 · 重写 `src/pipeline.py` 的 CLI + 新增 `--extract-genre`

**Files:**
- Modify: `src/pipeline.py`
- Create: `tests/test_pipeline_extract_genre.py`

- [ ] **Step 1:** 写 `tests/test_pipeline_extract_genre.py`：

```python
"""--extract-genre CLI: extract a genre pack into an existing book."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_pipeline_extract_genre_invokes_to_project(monkeypatch):
    """Test the function layer (CLI tested separately)."""
    from src import pipeline
    captured = {}
    def fake_extract_to_project(**kwargs):
        captured.update(kwargs)
        return {"book_id": kwargs["book_id"]}
    monkeypatch.setattr("src.genre_extractor.to_project.extract_to_project", fake_extract_to_project)
    # Also avoid bootstrap after extraction
    monkeypatch.setattr(pipeline, "bootstrap_project", lambda *a, **kw: None)

    result = pipeline.run_extract_genre("mybook", sources=["a.txt"], with_trial=False)
    assert captured["book_id"] == "mybook"
    assert captured["sources"] == ["a.txt"]
    assert result["book_id"] == "mybook"


def test_pipeline_cli_extract_genre_flag_parsed(tmp_path, monkeypatch):
    """--extract-genre <book-id> --sources a.txt must route to run_extract_genre."""
    # Smoke: import pipeline.main and inspect argparse options
    from src import pipeline
    import argparse
    parser = pipeline._build_parser()  # internal helper added by this task
    args = parser.parse_args(["--extract-genre", "mybook", "--sources", "a.txt,b.txt"])
    assert args.extract_genre == "mybook"
    assert args.sources == "a.txt,b.txt"
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_pipeline_extract_genre.py -v 2>&1 | tail -10
```

- [ ] **Step 3:** 改 `src/pipeline.py`：
  - 抽出 `_build_parser()` 便于测试
  - 新增 `--extract-genre <book-id>` + `--sources <comma>` + `--with-trial` 子命令
  - 新增 `run_extract_genre(book_id, sources, with_trial)` 函数：调 `extract_to_project`，然后如果书当前已激活则 `bootstrap_project(book_id, preserve_progress=True)` 把新题材文件推到 state/

实现里关键部分：

```python
# near the top
from src.bootstrap import bootstrap_project
from src import config

def run_extract_genre(book_id: str, *, sources: list[str], with_trial: bool = False) -> dict:
    from src.genre_extractor import to_project
    result = to_project.extract_to_project(book_id, sources=sources, with_trial=with_trial)
    # Re-bootstrap if this is the active book, so state/ picks up new genre files
    if config.get_active_project_id() == book_id:
        bootstrap_project(book_id, preserve_progress=True)
    return result


def _build_parser():
    import argparse
    p = argparse.ArgumentParser(description="Novelforge project pipeline")
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument("--chapter", type=int)
    g.add_argument("--range", dest="chapter_range")
    g.add_argument("--plan-only", dest="plan_only", type=int)
    g.add_argument("--write-only", dest="write_only", type=int)
    g.add_argument("--evaluate-only", dest="evaluate_only", type=int)
    g.add_argument("--fix-only", dest="fix_only", type=int)
    g.add_argument("--audit-only", dest="audit_only", type=int)
    g.add_argument("--bookkeeping-only", dest="bookkeeping_only", type=int)
    g.add_argument("--packaging", action="store_true")
    g.add_argument("--extract-genre", dest="extract_genre", metavar="BOOK_ID")
    p.add_argument("--sources", default="")
    p.add_argument("--with-trial", action="store_true")
    return p


def main():
    parser = _build_parser()
    args = parser.parse_args()
    # ... existing branches unchanged ...
    if args.extract_genre:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        if not sources:
            parser.error("--extract-genre requires --sources a.txt,b.txt")
        import json
        out = run_extract_genre(args.extract_genre, sources=sources, with_trial=args.with_trial)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
```

- [ ] **Step 4:** 跑通过确认

```bash
.venv/bin/python3 -m pytest tests/test_pipeline_extract_genre.py -v 2>&1 | tail -10
```

- [ ] **Step 5:** 跑 CLI 烟测

```bash
.venv/bin/python3 -m src.pipeline --help 2>&1 | grep "extract-genre"
```
Expected: 输出包含 `--extract-genre BOOK_ID`

- [ ] **Step 6:** Commit

```bash
git add src/pipeline.py tests/test_pipeline_extract_genre.py
git commit -m "feat(phase2): pipeline --extract-genre routes to extract_to_project + re-bootstrap"
```

---

## Task 2.6 · 重写 `src/genre_extractor/__main__.py` 的 CLI

**Files:**
- Modify: `src/genre_extractor/__main__.py`
- Modify: `tests/test_genre_pipeline_cli.py`（或新增 `tests/test_genre_extractor_cli.py`）

- [ ] **Step 1:** 新 CLI 契约：

```
python3 -m src.genre_extractor --to-preset <id> --sources a.txt,b.txt [--with-trial]
python3 -m src.genre_extractor --fill-preset <id>
python3 -m src.genre_extractor --audit-preset <id>
python3 -m src.genre_extractor --extract-only <id>
python3 -m src.genre_extractor --merge-only <id>
python3 -m src.genre_extractor --draft-only <id>
python3 -m src.genre_extractor --validate-only <id> [--with-trial]
```

保留分阶段 `--*-only`，语义不变（针对 preset `.build/` 断点续跑）。

- [ ] **Step 2:** 改 `tests/test_genre_pipeline_cli.py` 中的断言：
  - 把所有 `--new-genre` → `--new-preset`？**或者**：删除 `--new-genre` 分支（preset 只能从原著拆，没有"裸建"入口——这和 spec §3 一致）
  - `--extract-from-novel` → `--to-preset`
  - `--fill-genre` → `--fill-preset`
  - `--audit-genre` → `--audit-preset`

每条 CLI 测试必须保证调用新旧的子函数是 `pipeline.extract_to_preset` 等（而不是旧的 `extract_from_novel`）。

- [ ] **Step 3:** 重写 `src/genre_extractor/__main__.py`：

```python
"""CLI entry for the genre extractor.

Usage:
  python3 -m src.genre_extractor --to-preset <id> --sources a.txt,b.txt [--with-trial]
  python3 -m src.genre_extractor --fill-preset <id>
  python3 -m src.genre_extractor --audit-preset <id>
  python3 -m src.genre_extractor --extract-only <id>
  python3 -m src.genre_extractor --merge-only <id>
  python3 -m src.genre_extractor --draft-only <id>
  python3 -m src.genre_extractor --validate-only <id> [--with-trial]
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Novelforge Genre Extractor")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--to-preset", metavar="ID", help="extract a new preset from source novels")
    grp.add_argument("--fill-preset", metavar="ID", help="fill missing files in an existing preset")
    grp.add_argument("--audit-preset", metavar="ID", help="run validator stages on an existing preset")
    grp.add_argument("--extract-only", metavar="ID")
    grp.add_argument("--merge-only", metavar="ID")
    grp.add_argument("--draft-only", metavar="ID")
    grp.add_argument("--validate-only", metavar="ID")

    parser.add_argument("--sources", default="", help="comma-separated novel paths")
    parser.add_argument("--with-trial", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    from src.genre_extractor import to_preset as to_preset_mod
    from src.genre_extractor import pipeline

    if args.to_preset:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        if not sources:
            print("error: --to-preset requires --sources a.txt,b.txt", file=sys.stderr)
            return 2
        out = to_preset_mod.extract_to_preset(
            args.to_preset, sources=sources, with_trial=args.with_trial,
        )
    elif args.fill_preset:
        out = pipeline.fill_preset(args.fill_preset)
    elif args.audit_preset:
        out = pipeline.audit_preset(args.audit_preset)
    elif args.extract_only:
        out = pipeline.run_phase(args.extract_only, phase="extract")
    elif args.merge_only:
        out = pipeline.run_phase(args.merge_only, phase="merge")
    elif args.draft_only:
        out = pipeline.run_phase(args.draft_only, phase="draft")
    elif args.validate_only:
        out = pipeline.run_phase(args.validate_only, phase="validate", with_trial=args.with_trial)
    else:
        parser.print_help()
        return 2

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4:** 改 `src/genre_extractor/pipeline.py`：
  - 重命名函数 `fill_genre` → `fill_preset`，`audit_genre` → `audit_preset`
  - `run_phase` 内部把 `genre_id` 语义改为 `preset_id`（变量改名）
  - 工作目录从 `config.GENRES_DIR / id` 改为 `config.PRESETS_DIR / id`
  - 旧的 `new_genre` 函数**删除**（spec §7.1：不再提供裸建 preset 的入口）
  - `extract_from_novel` 删除（替代为 `to_preset.extract_to_preset`）

- [ ] **Step 5:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_genre_pipeline_cli.py tests/test_extract_to_preset.py -v 2>&1 | tail -20
```

所有测试必须 PASS。

再跑大套件：

```bash
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py 2>&1 | tail -20
```

若因 `genre_id` → `preset_id` 变量改名导致其他测试失败（特别是 `test_genre_*.py` 系列），在本 task 内修好。

- [ ] **Step 6:** Commit

```bash
git add src/genre_extractor/__main__.py src/genre_extractor/pipeline.py tests/
git commit -m "refactor(phase2): genre_extractor CLI uses --to-preset/--fill-preset/--audit-preset"
```

---

## Task 2.7 · `src/tools/setting_lint.py` 改名 `--genre` → `--preset`

**Files:**
- Modify: `src/tools/setting_lint.py`
- Modify: `tests/test_setting_lint.py`

- [ ] **Step 1:** 读 `src/tools/setting_lint.py`、找到 `--genre` 分支

- [ ] **Step 2:** 改测试：把所有 `--genre` 断言改为 `--preset`，并保留 `--project`（作品层校验）

- [ ] **Step 3:** 改实现：
  - argparse：`--genre` → `--preset`
  - 校验目录：`config.GENRES_DIR` → `config.PRESETS_DIR`
  - 错误消息中 "genre" → "preset"
  - 保留对 `resource_schema.yaml` 可选的处理

- [ ] **Step 4:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_setting_lint.py -v 2>&1 | tail -10
```

- [ ] **Step 5:** Commit

```bash
git add src/tools/setting_lint.py tests/test_setting_lint.py
git commit -m "refactor(phase2): setting_lint uses --preset/--project flags"
```

---

## Task 2.8 · 清理 `config.GENRES_DIR` deprecated alias

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1:** 全仓搜索 `GENRES_DIR`

```bash
git grep "GENRES_DIR" -- ':!CHANGELOG.md' ':!docs/history'
```

- [ ] **Step 2:** 把所有剩余引用改为 `PRESETS_DIR`。应覆盖到：
  - `src/tools/setting_lint.py`（如果 Task 2.7 没改干净）
  - `web/app.py`（若有）
  - 任何 `test_*.py`

- [ ] **Step 3:** 删除 `src/config.py` 里的 `GENRES_DIR = PRESETS_DIR` 别名

- [ ] **Step 4:** 确保全仓 `grep GENRES_DIR` 无遗漏（排除历史文档）

```bash
git grep "GENRES_DIR" -- ':!CHANGELOG.md' ':!docs/history' ':!docs/superpowers'
```

Expected: 空

- [ ] **Step 5:** 跑大套件

```bash
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py 2>&1 | tail -20
```

- [ ] **Step 6:** Commit

```bash
git add -A
git commit -m "refactor(phase2): remove GENRES_DIR alias, all callers use PRESETS_DIR"
```

---

## Task 2.9 · Phase 2 Checkpoint

自动化断言脚本：

```bash
set -e
# Module shape
.venv/bin/python3 -c "from src.genre_extractor import core, to_project, to_preset; from src import bootstrap, pipeline, config; assert hasattr(config, 'PRESETS_DIR'); assert not hasattr(config, 'GENRES_DIR')"
# Test suites
.venv/bin/python3 -m pytest tests/test_extract_core.py tests/test_extract_to_project.py tests/test_extract_to_preset.py tests/test_bootstrap_book_centric.py tests/test_pipeline_extract_genre.py -v
# Full suite (minus known-broken trial file)
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py
```

**退出码 0 表示 Phase 2 通过，可进 Phase 3。**
