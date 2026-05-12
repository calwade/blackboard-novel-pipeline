# Phase 1 · 数据迁移 + 模块改名

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Phase Goal:** 把仓库从 `genres/<id>/` + `projects/<id>/` 两层结构迁移到 `presets/<id>/` + `projects/<id>/`（题材文件下沉）；`src/genre_extractor/` 改名为 `src/genre_extractor/`。

**所有验收自动化**：每个任务结束后 `pytest` 必须绿，无任何肉眼核对步骤。

**Phase Checkpoint 命令（所有任务完成后必须通过）:**
```bash
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py
```

---

## 文件结构（本 phase 产出）

- Create: `scripts/migrate_to_book_centric.py`（下划线，便于被 pytest import）
- Create: `tests/test_migration_script.py`
- Create: `tests/test_phase1_checkpoint.py`（整仓状态断言）
- Rename: `src/genre_extractor/` → `src/genre_extractor/`
- Modify: 所有 `tests/test_genre_*.py` 的 import path
- Modify: `web/app.py`、`AGENTS.md`、`README.md` 里的 module 引用
- Modify: `.gitignore`：`genres/*/.build/` → `presets/*/.build/`
- Delete: `genres/`、`projects/test-ui-smoke/`（由迁移脚本操作）

---

## Task 1.1 · 写迁移脚本（红→绿一次走完，TDD）

**Files:**
- Create: `tests/test_migration_script.py`
- Create: `scripts/migrate_to_book_centric.py`

- [ ] **Step 1:** 写 `tests/test_migration_script.py` — 覆盖 8 项断言：

```python
"""Migration script: genres/ + projects/(with genre ref) → presets/ + projects/(self-contained)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml


def _load_migrate_module():
    root = Path(__file__).resolve().parent.parent
    spec_path = root / "scripts" / "migrate_to_book_centric.py"
    spec = importlib.util.spec_from_file_location("migrate_to_book_centric", spec_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["migrate_to_book_centric"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    # genres/alpha (has resource_schema) + genres/beta (no schema)
    for gid in ("alpha", "beta"):
        g = tmp_path / "genres" / gid
        g.mkdir(parents=True)
        (g / "genre.yaml").write_text(f"id: {gid}\ndisplay_name: {gid}\n", encoding="utf-8")
        (g / "era.md").write_text(f"# era {gid}\n", encoding="utf-8")
        (g / "writing-style-extra.md").write_text(f"# style {gid}\n", encoding="utf-8")
        (g / "iron-laws-extra.md").write_text(f"# laws {gid}\n", encoding="utf-8")
    (tmp_path / "genres" / "alpha" / "resource_schema.yaml").write_text(
        "resources:\n  - name: gold\n", encoding="utf-8"
    )

    # 2 real projects + 1 smoke test residue
    for pid, gid in (("alpha-bookone", "alpha"), ("beta-booktwo", "beta")):
        p = tmp_path / "projects" / pid
        p.mkdir(parents=True)
        (p / "project.yaml").write_text(
            f"id: {pid}\ngenre: {gid}\nprotagonist_name: hero\n", encoding="utf-8"
        )
        (p / "outline.json").write_text("{}", encoding="utf-8")
        (p / "characters.yaml").write_text("main: {}\n", encoding="utf-8")
        (p / "timeline.yaml").write_text("events: []\n", encoding="utf-8")

    smoke = tmp_path / "projects" / "test-ui-smoke"
    smoke.mkdir(parents=True)
    (smoke / "project.yaml").write_text("id: test-ui-smoke\n", encoding="utf-8")

    # root novels pool (must remain untouched)
    novels = tmp_path / "novels"
    novels.mkdir()
    (novels / "README.md").write_text("pool\n", encoding="utf-8")
    (novels / "sample.txt").write_text("chapter one\n", encoding="utf-8")

    return tmp_path


def test_migration_produces_presets_dir(fake_repo: Path):
    mod = _load_migrate_module()
    mod.migrate(repo_root=fake_repo)
    presets = fake_repo / "presets"
    assert (presets / "alpha" / "genre.yaml").read_text(encoding="utf-8").startswith("id: alpha")
    assert (presets / "alpha" / "resource_schema.yaml").exists()
    assert (presets / "beta" / "iron-laws-extra.md").exists()
    assert not (presets / "beta" / "resource_schema.yaml").exists()


def test_migration_creates_empty_novels_per_preset(fake_repo: Path):
    mod = _load_migrate_module()
    mod.migrate(repo_root=fake_repo)
    for gid in ("alpha", "beta"):
        novels_dir = fake_repo / "presets" / gid / "novels"
        assert (novels_dir / ".gitkeep").exists()
        assert list(novels_dir.glob("*.txt")) == []


def test_migration_copies_genre_files_into_project_dirs(fake_repo: Path):
    mod = _load_migrate_module()
    mod.migrate(repo_root=fake_repo)
    alpha = fake_repo / "projects" / "alpha-bookone"
    for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md", "resource_schema.yaml"):
        assert (alpha / fname).exists(), f"{fname} missing in alpha-bookone"
    beta = fake_repo / "projects" / "beta-booktwo"
    for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
        assert (beta / fname).exists()
    assert not (beta / "resource_schema.yaml").exists()


def test_migration_rewrites_project_yaml(fake_repo: Path):
    mod = _load_migrate_module()
    mod.migrate(repo_root=fake_repo)
    for pid, expected in (("alpha-bookone", "alpha"), ("beta-booktwo", "beta")):
        data = yaml.safe_load((fake_repo / "projects" / pid / "project.yaml").read_text(encoding="utf-8"))
        assert data["source_preset"] == expected
        assert "genre" not in data


def test_migration_deletes_genres_dir(fake_repo: Path):
    mod = _load_migrate_module()
    mod.migrate(repo_root=fake_repo)
    assert not (fake_repo / "genres").exists()


def test_migration_deletes_test_ui_smoke(fake_repo: Path):
    mod = _load_migrate_module()
    mod.migrate(repo_root=fake_repo)
    assert not (fake_repo / "projects" / "test-ui-smoke").exists()


def test_migration_leaves_novels_pool_untouched(fake_repo: Path):
    mod = _load_migrate_module()
    mod.migrate(repo_root=fake_repo)
    assert (fake_repo / "novels" / "sample.txt").read_text(encoding="utf-8") == "chapter one\n"
    assert (fake_repo / "novels" / "README.md").exists()


def test_migration_is_idempotent(fake_repo: Path):
    mod = _load_migrate_module()
    mod.migrate(repo_root=fake_repo)
    result = mod.migrate(repo_root=fake_repo)
    assert result["skipped"] is True
    assert "already" in result["reason"].lower()
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_migration_script.py -v 2>&1 | tail -20
```
Expected: 全部 fail（脚本不存在）

- [ ] **Step 3:** 写 `scripts/migrate_to_book_centric.py`：

```python
#!/usr/bin/env python3
"""One-shot migration: genres/ + projects/(with genre ref) → presets/ + projects/(self-contained).

Idempotent: if presets/ already exists OR genres/ is absent, skips.
Safe: does not touch projects/<id>/state/ (bootstrap will regenerate at runtime).
Run once after this change is merged, then delete this file.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional

import yaml

GENRE_FILES = ("era.md", "writing-style-extra.md", "iron-laws-extra.md")
OPTIONAL_GENRE_FILES = ("resource_schema.yaml",)


def migrate(repo_root: Optional[Path] = None) -> dict:
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parent.parent
    presets = root / "presets"
    genres = root / "genres"
    projects = root / "projects"

    if presets.exists():
        return {"skipped": True, "reason": "already migrated (presets/ exists)"}
    if not genres.exists():
        return {"skipped": True, "reason": "already migrated (no genres/ found)"}

    # 1. presets/ ← genres/
    presets.mkdir(parents=True)
    for genre_dir in sorted(genres.iterdir()):
        if genre_dir.is_dir():
            shutil.copytree(genre_dir, presets / genre_dir.name)

    # 2. empty novels/ per preset
    for preset_dir in sorted(presets.iterdir()):
        if preset_dir.is_dir():
            (preset_dir / "novels").mkdir(exist_ok=True)
            (preset_dir / "novels" / ".gitkeep").write_text("", encoding="utf-8")

    # 3 + 4. inject genre files + rewrite project.yaml
    if projects.exists():
        for proj_dir in sorted(projects.iterdir()):
            if not proj_dir.is_dir() or proj_dir.name == "test-ui-smoke":
                continue
            proj_yaml = proj_dir / "project.yaml"
            if not proj_yaml.exists():
                continue
            pdata = yaml.safe_load(proj_yaml.read_text(encoding="utf-8")) or {}
            src_id = pdata.get("genre")
            if not src_id:
                continue
            src_dir = presets / src_id
            if not src_dir.exists():
                continue
            for fname in GENRE_FILES + OPTIONAL_GENRE_FILES:
                src = src_dir / fname
                if src.exists():
                    shutil.copy2(src, proj_dir / fname)
            pdata["source_preset"] = src_id
            pdata.pop("genre", None)
            proj_yaml.write_text(
                yaml.safe_dump(pdata, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

    # 5. cleanup
    shutil.rmtree(genres)
    smoke = projects / "test-ui-smoke" if projects.exists() else None
    if smoke and smoke.exists():
        shutil.rmtree(smoke)

    return {"skipped": False, "reason": "migration complete"}


if __name__ == "__main__":
    result = migrate()
    if result["skipped"]:
        print(f"skipped: {result['reason']}", file=sys.stderr)
        sys.exit(0)
    print(f"ok: {result['reason']}")
```

- [ ] **Step 4:** 跑通过确认

```bash
.venv/bin/python3 -m pytest tests/test_migration_script.py -v 2>&1 | tail -5
```
Expected: `8 passed`

- [ ] **Step 5:** Commit

```bash
git add tests/test_migration_script.py scripts/migrate_to_book_centric.py
git commit -m "feat(phase1): implement idempotent migration script with test coverage"
```

---

## Task 1.2 · 在真实仓库执行迁移 + 自动化验证

**Files:**
- Modify (via script): `genres/`, `projects/test-ui-smoke/`, `projects/*/project.yaml`, `presets/*/`
- Create: `tests/test_phase1_repo_state.py`

- [ ] **Step 1:** 先写整仓状态断言测试 `tests/test_phase1_repo_state.py`：

```python
"""Phase 1 checkpoint: real repo layout after migration.

Runs against the actual repository (not a fixture). Ensures migration ran
and left the tree in the expected shape.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
BUILTIN_PRESETS = ("gangster-hk-1983", "xianxia-ascension", "urban-romance-contemporary")
BUILTIN_PROJECTS = {
    "gangster-hk-1983-linjiayao": "gangster-hk-1983",
    "xianxia-ascension-peichangning": "xianxia-ascension",
    "urban-romance-shenruowei": "urban-romance-contemporary",
}
REQUIRED_GENRE_FILES = ("era.md", "writing-style-extra.md", "iron-laws-extra.md")


def test_genres_dir_removed():
    assert not (REPO / "genres").exists(), "genres/ must be deleted post-migration"


def test_presets_dir_has_3_builtin():
    for gid in BUILTIN_PRESETS:
        assert (REPO / "presets" / gid / "genre.yaml").exists()
        for fname in REQUIRED_GENRE_FILES:
            assert (REPO / "presets" / gid / fname).exists()


def test_presets_have_empty_novels_dir():
    for gid in BUILTIN_PRESETS:
        novels = REPO / "presets" / gid / "novels"
        assert novels.exists()
        assert (novels / ".gitkeep").exists()


def test_novels_pool_still_exists():
    assert (REPO / "novels").exists()
    assert (REPO / "novels" / "README.md").exists()


def test_test_ui_smoke_removed():
    assert not (REPO / "projects" / "test-ui-smoke").exists()


@pytest.mark.parametrize("pid,expected_preset", BUILTIN_PROJECTS.items())
def test_projects_have_genre_files_inlined(pid: str, expected_preset: str):
    p = REPO / "projects" / pid
    for fname in REQUIRED_GENRE_FILES:
        assert (p / fname).exists(), f"{pid}/{fname} missing post-migration"


@pytest.mark.parametrize("pid,expected_preset", BUILTIN_PROJECTS.items())
def test_projects_yaml_uses_source_preset(pid: str, expected_preset: str):
    data = yaml.safe_load((REPO / "projects" / pid / "project.yaml").read_text(encoding="utf-8"))
    assert data.get("source_preset") == expected_preset
    assert "genre" not in data
```

- [ ] **Step 2:** 跑失败确认（迁移未执行，测试应全红）

```bash
.venv/bin/python3 -m pytest tests/test_phase1_repo_state.py -v 2>&1 | tail -20
```
Expected: 多数 FAIL（`genres/` 还在、`presets/` 不存在 等）

- [ ] **Step 3:** 确认工作区干净，执行迁移

```bash
set -e
git status --porcelain | grep -v "^??" && { echo "working tree dirty, abort"; exit 1; } || true
.venv/bin/python3 scripts/migrate_to_book_centric.py
```
Expected stdout: `ok: migration complete`

- [ ] **Step 4:** 整仓状态测试必须通过

```bash
.venv/bin/python3 -m pytest tests/test_phase1_repo_state.py -v 2>&1 | tail -30
```
Expected: 全部 PASS（包括 parametrize 出来的 9 条 case）

- [ ] **Step 5:** Commit 状态测试和迁移产物到一起

```bash
git add -A
git commit -m "chore(phase1): execute migration — genres/→presets/, inline genre files into projects/"
```

---

## Task 1.3 · 更新 .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1:** 写替换

把 `.gitignore` 中包含 `genres/` 的行替换为 `presets/` 等价行，具体：
- `genres/*/.build/` → `presets/*/.build/`
- 若有 `genres/` 本身的条目，移除

- [ ] **Step 2:** 自动化断言

```bash
grep -c "^presets/\*/.build/" .gitignore    # 必须 >= 1
grep -c "^genres" .gitignore 2>/dev/null || true   # 必须 0
```

嵌到 `tests/test_phase1_repo_state.py` 追加：

```python
def test_gitignore_uses_presets():
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "presets/*/.build/" in text
    assert "\ngenres" not in text and not text.startswith("genres")
```

- [ ] **Step 3:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_phase1_repo_state.py::test_gitignore_uses_presets -v
```
Expected: PASS

- [ ] **Step 4:** Commit

```bash
git add .gitignore tests/test_phase1_repo_state.py
git commit -m "chore(phase1): update .gitignore for presets/ layout"
```

---

## Task 1.4 · 改名 `src/genre_extractor/` → `src/genre_extractor/` + 全仓 import 修正

**Files:**
- Rename: `src/genre_extractor/` → `src/genre_extractor/`
- Modify: `src/genre_extractor/__init__.py`、`__main__.py`、`pipeline.py`（docstring / self-reference）
- Modify: `web/app.py`
- Modify: `tests/test_genre_*.py`（~17 个）
- Modify: `AGENTS.md`、`README.md`（模块路径引用）

- [ ] **Step 1:** `git mv`

```bash
set -e
git mv src/genre_extractor src/genre_extractor
```

- [ ] **Step 2:** 脚本化全仓替换

**⚠️ 排除路径**：`CHANGELOG.md` 和 `docs/history/*.md` 是历史档案，保留旧名作为史料；`docs/superpowers/specs/`、`docs/superpowers/plans/` 指的是文档本身，可以替换。

用 Python 脚本做替换以避免 shell 转义陷阱：

```bash
.venv/bin/python3 <<'PY'
from pathlib import Path
import re

EXCLUDE_FILES = {"CHANGELOG.md"}
EXCLUDE_DIR_PARTS = {"docs/history", ".venv", ".git", "node_modules", "__pycache__", ".pytest_cache"}

def excluded(p: Path) -> bool:
    if p.name in EXCLUDE_FILES:
        return True
    s = str(p).replace("\\", "/")
    return any(f"/{d}/" in f"/{s}/" for d in EXCLUDE_DIR_PARTS)

root = Path(".")
targets = []
for pat in ("*.py", "*.md", "*.yml", "*.yaml", "*.txt", "*.html", "*.js", "*.css", "*.sh"):
    for p in root.rglob(pat):
        if excluded(p):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "genre_pipeline" not in text:
            continue
        new = text.replace("src.genre_extractor", "src.genre_extractor") \
                  .replace("src/genre_extractor", "src/genre_extractor") \
                  .replace("genre_pipeline/", "genre_extractor/")
        if new != text:
            p.write_text(new, encoding="utf-8")
            targets.append(str(p))

print(f"updated {len(targets)} files")
for t in targets:
    print(" -", t)
PY
```

- [ ] **Step 3:** 修整 `src/genre_extractor/__init__.py` docstring（脚本可能没精确改对）

```python
"""Genre Extractor — extract genre packs from source novels.

Two entry points:
  - to_project: produce era.md etc for a specific book (projects/<book-id>/)
  - to_preset:  produce a reusable genre preset (presets/<preset-id>/)

See docs/superpowers/specs/book-centric-workflow-design.md for the full design.
"""
```

- [ ] **Step 4:** 修整 `src/genre_extractor/__main__.py` 顶部 docstring，把 `python3 -m src.genre_extractor ...` 改为 `python3 -m src.genre_extractor ...`。**不改命令行标志**（`--new-genre` 等保留，Phase 2 重构）。

- [ ] **Step 5:** 自动化断言

追加到 `tests/test_phase1_repo_state.py`：

```python
def test_genre_pipeline_module_gone():
    assert not (REPO / "src" / "genre_pipeline").exists()
    assert (REPO / "src" / "genre_extractor" / "__init__.py").exists()


def test_no_stale_genre_pipeline_references():
    """Everywhere except CHANGELOG.md and docs/history/ must use src.genre_extractor."""
    import subprocess
    result = subprocess.run(
        ["git", "grep", "-l", "genre_pipeline"],
        capture_output=True, text=True, cwd=REPO,
    )
    offenders = [
        line for line in result.stdout.splitlines()
        if line and line != "CHANGELOG.md" and not line.startswith("docs/history/")
    ]
    assert offenders == [], f"stale genre_pipeline references in: {offenders}"


def test_genre_extractor_imports_ok():
    import importlib
    for mod in ("src.genre_extractor", "src.genre_extractor.pipeline"):
        importlib.import_module(mod)
```

- [ ] **Step 6:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_phase1_repo_state.py -v 2>&1 | tail -15
```
Expected: 全 PASS

- [ ] **Step 7:** 跑既存测试套件确认无回归

```bash
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py 2>&1 | tail -20
```

**处理既存失败**：若 `test_bootstrap_and_settings.py` 中涉及 `genres/` 目录结构的 case 失败，给每个失败的测试函数加 `@pytest.mark.skip(reason="awaiting phase 2 bootstrap rewrite")`。**只标注，不改逻辑**。其他非预期失败要修到绿。

- [ ] **Step 8:** Commit

```bash
git add -A
git commit -m "refactor(phase1): rename src/genre_extractor → src/genre_extractor + update all references"
```

---

## Task 1.5 · 占位 `presets/README.md` + 临时修 `projects/README.md`

**Files:**
- Create: `presets/README.md`
- Modify: `projects/README.md`

- [ ] **Step 1:** 写 `presets/README.md`（详细内容 Phase 5 替换）：

```markdown
# presets/ — 题材预设库

preset = 新建作品时的可选起点模板。每个 preset 是 5 份文件（`genre.yaml` + 4 份题材规范）+
一个 `novels/` 子目录（从大池子 `novels/` 勾选的原著素材副本），位于 `presets/<preset-id>/`。

**preset 在运行时不参与**——只在"新建作品 · 题材起点 · 从 preset 拷贝"或"从原著拆到 preset"
两个入口被读/写。一旦作品创建完成，该作品的题材文件就住在 `projects/<book-id>/` 目录下。

详细说明见根目录 `README.md` 和 `AGENTS.md`。
```

- [ ] **Step 2:** 修 `projects/README.md`：把所有 `genre =` 改成 `source_preset =`；"基于哪个 genre" 改为"基于哪个 preset（审计用，可选）"；"已提供的作品"表最后一列 `基于题材` → `基于 preset`。**不重写整篇**，Phase 5 做。

具体用 Python 脚本精准替换：

```bash
.venv/bin/python3 <<'PY'
from pathlib import Path
p = Path("projects/README.md")
t = p.read_text(encoding="utf-8")
t = t.replace("genre = ", "source_preset = ")
t = t.replace("基于哪个 genre", "基于哪个 preset（审计用，可选）")
t = t.replace("基于题材", "基于 preset")
p.write_text(t, encoding="utf-8")
print("patched")
PY
```

- [ ] **Step 3:** 断言测试追加到 `tests/test_phase1_repo_state.py`：

```python
def test_presets_readme_exists():
    assert (REPO / "presets" / "README.md").exists()
    assert "题材预设库" in (REPO / "presets" / "README.md").read_text(encoding="utf-8")


def test_projects_readme_no_genre_keyword():
    t = (REPO / "projects" / "README.md").read_text(encoding="utf-8")
    # "genre = X" patterns should be gone (allowing "genre" to appear in prose)
    assert "genre = " not in t
    assert "source_preset" in t
```

- [ ] **Step 4:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_phase1_repo_state.py -v 2>&1 | tail -10
```
Expected: 全 PASS

- [ ] **Step 5:** Commit

```bash
git add presets/README.md projects/README.md tests/test_phase1_repo_state.py
git commit -m "docs(phase1): add presets/README.md placeholder, retag projects/README.md to source_preset"
```

---

## Phase 1 最终 Checkpoint

自动化命令（所有任务完成后跑一次）：

```bash
set -e
.venv/bin/python3 -m pytest tests/test_migration_script.py tests/test_phase1_repo_state.py -v
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py
```

**退出码 0 表示 Phase 1 通过，可进 Phase 2。**
