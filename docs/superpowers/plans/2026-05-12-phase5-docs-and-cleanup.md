# Phase 5 · 文档重写 + 清理 + 整体验收

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Phase Goal:**
1. 重写 README.md / AGENTS.md / projects/README.md / presets/README.md / docs/web-ui-guide.md 为"一本书的生命周期"单一工作流视角
2. 删除迁移脚本（已用完）
3. CHANGELOG.md 新增 `[Unreleased]` 条目
4. 整体验收：全仓 grep 无"从 X 改为 Y"叙事；`genre_pipeline` 只在历史档案出现；测试全绿

**Phase Checkpoint 命令:**
```bash
.venv/bin/python3 -m pytest tests/ -x -q --ignore=tests/test_genre_trial.py
.venv/bin/python3 -m pytest tests/test_phase5_final_state.py -v
```

---

## Task 5.1 · 重写 README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** 写一个结构断言测试 `tests/test_phase5_final_state.py`（本文件渐进式扩展，每个 task 追加）：

```python
"""Phase 5 final-state assertions: docs, cleanup, overall acceptance."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent


def test_readme_describes_single_workflow():
    """README must frame the project as one workflow (a book's lifecycle),
    not two independent pipelines."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    # Positive markers
    assert "一本书" in text
    assert "preset" in text.lower() or "预设" in text
    # Must no longer describe genre_pipeline as a peer to the novel pipeline
    assert "题材流水线" not in text or "（原题材流水线，已合并" in text
    assert "src/genre_pipeline" not in text


def test_readme_mentions_4_step_wizard():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "4 步" in text or "向导" in text


def test_readme_cli_refers_to_new_commands():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "--extract-genre" in text
    assert "python -m src.genre_extractor --to-preset" in text
    assert "python -m src.genre_pipeline" not in text
```

- [ ] **Step 2:** 跑失败确认

```bash
.venv/bin/python3 -m pytest tests/test_phase5_final_state.py -v 2>&1 | tail -10
```

- [ ] **Step 3:** 重写 `README.md`。关键章节：

**顶部介绍**（保留原 Novelforge 定位 + 5 大难题对照）

**新章节"一本书的生命周期"**（替代原"Genre + Project 两层架构"章节）：

```markdown
## 一本书的生命周期

Novelforge 把"写一本小说"封装成单一工作流：

```
新建作品 (4 步向导)
    ↓
  第 1 步：基本信息（书名 / 主角 / 目标章数）
  第 2 步：题材起点（三选一）
           ├── 从 preset 拷贝：挑一个现成 preset 作为起点
           ├── 从原著拆：从 novels/ 大池子勾选 txt，LLM 生成题材规范
           └── 最小脚手架：产出 4 份空壳
  第 3 步：大纲起点（梗概 → LLM 生成 outline.json；或空壳）
  第 4 步：角色起点（人物简介 → LLM 生成 characters.yaml；或空壳）
    ↓
作品 ready → projects/<book-id>/ 下自带所有需要的文件
    ↓
bootstrap → projects/<book-id>/state/ 就绪
    ↓
pipeline --chapter N （Planner → Generator → Evaluator → Fixer → Summarizer + 记账 + 审计）
    ↓
作品完结 → pipeline --packaging（书名 / 简介 / 封面 / 标签）
```

题材不是独立概念。一本书 = `projects/<book-id>/` 目录下的全部文件：

```
projects/<book-id>/
├── project.yaml          # 书的元信息（含可选 source_preset 字段记录起点）
├── outline.json          # 大纲
├── characters.yaml       # 人物
├── timeline.yaml         # 时间线
├── era.md                # 题材文件：时代/世界观事实包
├── writing-style-extra.md   # 题材文件：特有写作风格
├── iron-laws-extra.md       # 题材文件：特有铁律
├── resource_schema.yaml  # 可选：可追踪资源定义
└── state/                # 运行时产物（.gitignore）
```

**preset 是新书的可选起点模板**，位于 `presets/<preset-id>/`，结构和作品相同但不包含 outline/characters/timeline。新建作品时可以从 preset 拷贝题材 4 份文件作为起点；拷完就和 preset 解耦。

### 从原著拆题材

新建作品或已有作品都可以「从原著拆题材」：

```bash
# 新建作品时：4 步向导的第 2 步选"从原著拆"
# 或：CLI 对已有作品操作
python -m src.pipeline --extract-genre <book-id> --sources novels/a.txt,novels/b.txt [--with-trial]

# 造一个可复用的新 preset
python -m src.genre_extractor --to-preset <new-preset-id> --sources novels/a.txt,novels/b.txt
```

Web UI：作品首页 ⎇ 覆盖题材按钮 / `/presets/<id>` 从原著拆新 preset 入口。
```

**"项目结构"章节**：只列当前真实布局，不讲"重构前 vs 之后"。

**"如何跑"章节**：保留；CLI 部分改成：
- `python -m src.bootstrap --list-presets` / `--list`
- `python -m src.bootstrap --new-project <id> --preset <preset-id> --display-name "..." --protagonist "..." --chapters 50`
- `python -m src.pipeline --extract-genre <book-id> --sources ...`
- `python -m src.genre_extractor --to-preset <new-preset-id> --sources ...`

删除 "Genre Pipeline" 独立章节（合入上面"从原著拆题材"）。

**"测试"章节**：保留列表，补上新增的 drafter / wizard / preset API 测试。

**"设计文档"章节**：链接改到
- `docs/superpowers/specs/book-centric-workflow-design.md` (代替原 genre-pipeline-design)

- [ ] **Step 4:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_phase5_final_state.py::test_readme_describes_single_workflow tests/test_phase5_final_state.py::test_readme_mentions_4_step_wizard tests/test_phase5_final_state.py::test_readme_cli_refers_to_new_commands -v
```

- [ ] **Step 5:** Commit

```bash
git add README.md tests/test_phase5_final_state.py
git commit -m "docs(phase5): rewrite README around single book-centric workflow"
```

---

## Task 5.2 · 重写 AGENTS.md + projects/README.md + presets/README.md

**Files:**
- Modify: `AGENTS.md`
- Modify: `projects/README.md`
- Modify: `presets/README.md`

- [ ] **Step 1:** 追加断言到 `tests/test_phase5_final_state.py`：

```python
def test_agents_md_describes_single_layer():
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    # No "两层架构" framing
    assert "两层架构" not in text
    # project files live in projects/<id>/ directly
    assert "projects/<project-id>/" in text or "projects/<book-id>/" in text
    # preset as optional seed
    assert "preset" in text.lower() or "预设" in text


def test_agents_md_state_map_has_outline_drafter_entry_point():
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "OutlineDrafter" in text
    assert "CharactersDrafter" in text


def test_projects_readme_describes_self_contained_book():
    text = (REPO / "projects" / "README.md").read_text(encoding="utf-8")
    assert "source_preset" in text
    assert "题材文件" in text or "era.md" in text  # mentions the inline genre files
    # No reference to the old genres/ directory layering
    assert "genres/" not in text or "原" in text  # if mentioned, it's in a historical context


def test_presets_readme_describes_seed_only():
    text = (REPO / "presets" / "README.md").read_text(encoding="utf-8")
    assert "preset" in text.lower() or "预设" in text
    # preset only acts at new-project time
    assert "运行时不参与" in text or "运行时不" in text
```

- [ ] **Step 2:** 跑失败确认

- [ ] **Step 3:** 重写 `AGENTS.md`。保留目录页性质，主要改动：

- "两层架构" → "一本书 = projects/<book-id>/ 下的全部文件；preset 只是新建时的可选起点"
- "题材层" / "作品层" 描述删除
- State 地图：移除"题材层拷入"/"作品层拷入"列，改为单列"来源"
- Agent 名册：追加 OutlineDrafter / CharactersDrafter（单次 LLM 调用，向导用）
- Bootstrap 描述：改为"只拷 projects/<id>/ 顶层文件到 state/ + 合成 setting.yaml"
- 删除对 `src/genre_pipeline` 的任何残留引用；改 `src/genre_extractor`

- [ ] **Step 4:** 重写 `projects/README.md`：删除"基于哪个 genre"所有叙事，改为：
  - 一本书 = 这个目录下的全部
  - 题材文件（era.md 等）直接住在这里
  - `project.yaml` 可能有 `source_preset` 字段记录起点（可选，仅审计用）
  - 激活一本书：`python -m src.bootstrap --project <id>`（会把本目录内容拷到 `state/`）
  - 新建书的 3 种方式：Web 向导 / CLI `--new-project` / 手动复制现有作品

- [ ] **Step 5:** 重写 `presets/README.md`：
  - 1 句话：preset 是新建作品的可选起点模板
  - 目录结构：`genre.yaml` + 4 份题材规范 + `novels/` 子目录
  - 不参与运行时
  - 内置 3 个不可编辑、不可删除
  - 造新 preset 的方式：Web `/presets` 页的"从原著拆"入口 / CLI `python -m src.genre_extractor --to-preset`

- [ ] **Step 6:** 跑测试

```bash
.venv/bin/python3 -m pytest tests/test_phase5_final_state.py -v 2>&1 | tail -10
```

- [ ] **Step 7:** Commit

```bash
git add AGENTS.md projects/README.md presets/README.md tests/test_phase5_final_state.py
git commit -m "docs(phase5): rewrite AGENTS.md + projects/README.md + presets/README.md"
```

---

## Task 5.3 · 重写 docs/web-ui-guide.md

**Files:**
- Modify: `docs/web-ui-guide.md`

- [ ] **Step 1:** 追加断言：

```python
def test_web_ui_guide_routes_point_to_presets():
    text = (REPO / "docs" / "web-ui-guide.md").read_text(encoding="utf-8")
    # No /genres routes mentioned
    assert "/genres" not in text
    # /presets is documented
    assert "/presets" in text
    # draft endpoints
    assert "draft-outline" in text
    assert "draft-characters" in text
    # wizard 4-step mention
    assert "4 步" in text or "四步" in text or "向导" in text
```

- [ ] **Step 2:** 改 `docs/web-ui-guide.md`：
  - 所有 `/genres` → `/presets`
  - `web/templates/genres/` → `web/templates/presets/`
  - 新增 `/api/projects/<id>/extract-genre` / `draft-outline` / `draft-characters` 条目到 API 路由表
  - 「作品首页」章节新增"⎇ 覆盖题材配置"按钮说明
  - 「新建作品向导」章节扩为 4 步说明（对应 spec §3）
  - 素材库 `/novels` 章节增加：每个 txt 显示 `used_by_presets`；删除时被引用要二次确认
  - 删除"题材库" 菜单入口表述；`/presets` 不是题材库，只是起点模板库

- [ ] **Step 3:** 跑测试 + commit

```bash
.venv/bin/python3 -m pytest tests/test_phase5_final_state.py::test_web_ui_guide_routes_point_to_presets -v
git add docs/web-ui-guide.md tests/test_phase5_final_state.py
git commit -m "docs(phase5): rewrite web-ui-guide for book-centric routes and wizard"
```

---

## Task 5.4 · 删除迁移脚本 + 更新 CHANGELOG

**Files:**
- Delete: `scripts/migrate_to_book_centric.py`
- Delete: `tests/test_migration_script.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1:** 追加断言：

```python
def test_migration_script_removed_after_use():
    """Migration script is one-shot; it should be deleted after the migration
    is merged to main."""
    assert not (REPO / "scripts" / "migrate_to_book_centric.py").exists()
    assert not (REPO / "tests" / "test_migration_script.py").exists()


def test_changelog_mentions_book_centric():
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    # A new [Unreleased] or dated block should cover this refactor
    assert "book-centric" in text.lower() or "一本书" in text
```

- [ ] **Step 2:** 跑失败确认

- [ ] **Step 3:** 删除两个文件

```bash
git rm scripts/migrate_to_book_centric.py tests/test_migration_script.py
```

- [ ] **Step 4:** 编辑 `CHANGELOG.md`：在 `[Unreleased]` 追加/新增一个 dated 块：

```markdown
## 2026-05-12 — Book-centric workflow 重构

### Breaking
- `genres/` 目录删除；题材 4 份文件下沉到 `projects/<book-id>/` 根目录
- `src/genre_pipeline/` 重命名为 `src/genre_extractor/`；CLI 入口改为 `--to-preset`
- `src/pipeline.py` 新增 `--extract-genre <book-id> --sources ...`
- Web `/genres*` 路由全部删除，替换为 `/presets*`；新建 preset 仅通过"从原著拆"入口
- `config.GENRES_DIR` 删除；改用 `config.PRESETS_DIR`
- `bootstrap_project` 不再合并 genre + project 两层；单层拷贝

### Added
- `presets/` 目录（新建作品的可选起点模板库）
- 新建作品向导扩展为 4 步（基本信息 / 题材起点三选一 / 大纲梗概 / 人物简介）
- `OutlineDrafter` / `CharactersDrafter`：两个轻量向导 agent
- `POST /api/projects/<id>/extract-genre` / `draft-outline` / `draft-characters`
- `POST /api/presets/new-from-novel` + `/api/presets/<id>/status`
- `/api/novels` 响应补 `used_by_presets`；删除被引用素材要二次确认
```

- [ ] **Step 5:** 跑测试 + commit

```bash
.venv/bin/python3 -m pytest tests/test_phase5_final_state.py -v 2>&1 | tail -10
git add -A
git commit -m "chore(phase5): remove one-shot migration script, update CHANGELOG"
```

---

## Task 5.5 · 最终整体验收 + 集成冒烟

**Files:**
- Create: `tests/test_phase5_integration.py`

- [ ] **Step 1:** 写集成烟测 `tests/test_phase5_integration.py`，对真实仓库的 3 个内置作品跑 bootstrap（不调 LLM）：

```python
"""End-to-end integration smoke: each built-in project can be bootstrapped."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BUILTIN_BOOKS = ("gangster-hk-1983-linjiayao", "xianxia-ascension-peichangning", "urban-romance-shenruowei")


@pytest.mark.parametrize("book_id", BUILTIN_BOOKS)
def test_builtin_project_bootstraps_cleanly(book_id: str, monkeypatch):
    """Each built-in book must bootstrap successfully after migration, no LLM."""
    from src import bootstrap
    result = bootstrap.bootstrap_project(book_id)
    assert result.project_id == book_id
    state = result.state_dir
    for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md",
                  "setting.yaml", "outline.json", "characters.yaml", "timeline.yaml",
                  "progress.json"):
        assert (state / fname).exists(), f"{book_id}/state/{fname} missing"


@pytest.mark.parametrize("book_id", BUILTIN_BOOKS)
def test_builtin_project_yaml_has_source_preset(book_id: str):
    import yaml
    data = yaml.safe_load((REPO / "projects" / book_id / "project.yaml").read_text(encoding="utf-8"))
    assert data.get("source_preset") is not None


def test_cli_pipeline_help_mentions_extract_genre():
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "src.pipeline", "--help"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert "--extract-genre" in result.stdout


def test_cli_genre_extractor_help_mentions_to_preset():
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "src.genre_extractor", "--help"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert "--to-preset" in result.stdout


def test_no_references_to_genre_pipeline_outside_history():
    """src.genre_pipeline must not appear anywhere except CHANGELOG and docs/history/."""
    import subprocess
    r = subprocess.run(
        ["git", "grep", "-l", "genre_pipeline"],
        cwd=REPO, capture_output=True, text=True,
    )
    offenders = [
        line for line in r.stdout.splitlines()
        if line and line != "CHANGELOG.md" and not line.startswith("docs/history/")
    ]
    assert offenders == [], f"stale genre_pipeline references: {offenders}"


def test_no_orphaned_genres_dir():
    assert not (REPO / "genres").exists()


def test_no_test_ui_smoke_project():
    assert not (REPO / "projects" / "test-ui-smoke").exists()


def test_gitignore_has_presets_build():
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "presets/*/.build/" in text
```

- [ ] **Step 2:** 跑

```bash
.venv/bin/python3 -m pytest tests/test_phase5_integration.py -v 2>&1 | tail -25
```

全部必须 PASS。若有失败：
- `bootstrap_project` 失败——说明 Phase 2 的 bootstrap 还有边界 case 没处理。回去修。
- `project.yaml` 没有 `source_preset`——Phase 1 迁移漏了，手动补字段。
- `genre_pipeline` 残留——用脚本扫剩余引用并替换。

- [ ] **Step 3:** 跑完整套件

```bash
.venv/bin/python3 -m pytest tests/ -q --ignore=tests/test_genre_trial.py 2>&1 | tail -30
```

必须全绿（允许原有的 xfail/skip，但不能有新 failure）。

- [ ] **Step 4:** Commit

```bash
git add tests/test_phase5_integration.py
git commit -m "test(phase5): integration smoke for all built-in books + CLI help contracts"
```

---

## Task 5.6 · 归档 spec 到 docs/history/

**Files:**
- Move: `docs/superpowers/specs/genre-pipeline-design.md` → `docs/history/genre-pipeline-design.md`（原设计已被 book-centric 取代）

- [ ] **Step 1:** 追加断言：

```python
def test_old_genre_pipeline_spec_archived():
    assert not (REPO / "docs" / "superpowers" / "specs" / "genre-pipeline-design.md").exists()


def test_book_centric_spec_exists():
    assert (REPO / "docs" / "superpowers" / "specs" / "book-centric-workflow-design.md").exists()
```

- [ ] **Step 2:** 迁移

```bash
git mv docs/superpowers/specs/genre-pipeline-design.md docs/history/genre-pipeline-design.md
```

- [ ] **Step 3:** 在归档的 md 顶部加 banner：

```bash
.venv/bin/python3 <<'PY'
from pathlib import Path
p = Path("docs/history/genre-pipeline-design.md")
t = p.read_text(encoding="utf-8")
banner = "> **📦 历史档案** · 本设计已由 `docs/superpowers/specs/book-centric-workflow-design.md` 取代。保留仅为历史脉络。\n\n"
if not t.startswith("> **📦 历史档案**"):
    # Insert after first H1
    lines = t.split("\n", 1)
    t = lines[0] + "\n\n" + banner + (lines[1] if len(lines) > 1 else "")
    p.write_text(t, encoding="utf-8")
PY
```

- [ ] **Step 4:** 全仓搜索 `genre-pipeline-design.md` 的路径引用并替换为新路径（排除 CHANGELOG 与 history）：

```bash
.venv/bin/python3 <<'PY'
from pathlib import Path
for p in Path(".").rglob("*"):
    if not p.is_file(): continue
    if p.suffix not in (".md", ".py"): continue
    s = str(p).replace("\\", "/")
    if "/.venv/" in f"/{s}/" or "/.git/" in f"/{s}/" or "/docs/history/" in f"/{s}/" or s == "CHANGELOG.md":
        continue
    t = p.read_text(encoding="utf-8", errors="ignore")
    new = t.replace("docs/superpowers/specs/genre-pipeline-design.md", "docs/superpowers/specs/book-centric-workflow-design.md")
    if new != t:
        p.write_text(new, encoding="utf-8")
        print("patched", p)
PY
```

- [ ] **Step 5:** 跑测试 + commit

```bash
.venv/bin/python3 -m pytest tests/test_phase5_final_state.py -v
.venv/bin/python3 -m pytest tests/ -q --ignore=tests/test_genre_trial.py 2>&1 | tail -10
git add -A
git commit -m "docs(phase5): archive old genre-pipeline-design spec; point everything to book-centric"
```

---

## Phase 5 最终 Checkpoint

```bash
set -e
.venv/bin/python3 -m pytest tests/test_phase5_final_state.py tests/test_phase5_integration.py -v
.venv/bin/python3 -m pytest tests/ -q --ignore=tests/test_genre_trial.py
# repo shape assertions
test ! -d genres
test ! -d projects/test-ui-smoke
test ! -f scripts/migrate_to_book_centric.py
test -d presets
test -d presets/gangster-hk-1983
test -f projects/gangster-hk-1983-linjiayao/era.md
test -f docs/superpowers/specs/book-centric-workflow-design.md
test ! -f docs/superpowers/specs/genre-pipeline-design.md
# no stale genre_pipeline refs
! git grep genre_pipeline -- ':!CHANGELOG.md' ':!docs/history'
echo "Phase 5 done."
```

退出码 0 = 整体重构完成。
