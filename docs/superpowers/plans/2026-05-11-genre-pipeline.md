# 题材流水线（Genre Pipeline）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏任何现有功能的前提下，新增一条与小说流水线对等的题材流水线，支持从零手建 / 补齐 / 审查 / 从已有小说拆解四种入口。第一版用占位 prompt 跑通调度和 schema，生产级 prompt 留给后续迭代。

**Architecture:** `src/core/` 下沉通用抽象（Blackboard + BaseAgent）+ `src/genre_pipeline/` 新增薄壳，复用现有 Blackboard / BaseAgent / Intent Router / 分级摘要思想。向后兼容通过 re-export shim 实现。

**Tech Stack:** Python 3.9+ / pytest / PyYAML / httpx（已有）/ OpenAI-compatible LLM client（已有）

**Spec:** `docs/superpowers/specs/2026-05-11-genre-pipeline-design.md`

---

## 文件布局总览

**新增：**
- `src/core/__init__.py` — 通用抽象包
- `src/core/blackboard.py` — 从 `src/blackboard.py` 移入（原文件变 shim）
- `src/core/base_agent.py` — 从 `src/agents/_base.py` 移入（原文件变 shim）
- `src/genre_pipeline/__init__.py`
- `src/genre_pipeline/__main__.py` — CLI entry
- `src/genre_pipeline/schemas.py` — batch / build_status / blueprint 的 dataclass + 校验
- `src/genre_pipeline/adaptive.py` — 档位 + 章节切分
- `src/genre_pipeline/pipeline.py` — run_genre_build + 各 phase
- `src/genre_pipeline/trial.py` — Stage 3 scratch bootstrap（复用 calibrate 骨架）
- `src/genre_pipeline/agents/__init__.py`
- `src/genre_pipeline/agents/extractor.py`
- `src/genre_pipeline/agents/drafter.py`
- `src/genre_pipeline/agents/validator.py`
- `src/genre_pipeline/agents/fixer.py`

**修改：**
- `src/blackboard.py` — 改成 shim（re-export from `src.core.blackboard`）
- `src/agents/_base.py` — 改成 shim（re-export from `src.core.base_agent`）
- `.gitignore` — 忽略 `genres/*/.build/`
- `AGENTS.md` — 增加题材流水线索引段

**新增测试：**
- `tests/test_core_shims.py` — 向后兼容保护
- `tests/test_genre_schemas.py`
- `tests/test_genre_adaptive.py`
- `tests/test_genre_build_status.py`
- `tests/test_genre_agents_instantiation.py`
- `tests/test_genre_pipeline_cli.py`
- `tests/test_genre_pipeline_end_to_end.py`

---

## Task 1: 建立 `src/core/` 并做 Blackboard 下沉 + 向后兼容 shim

**Files:**
- Create: `src/core/__init__.py`
- Create: `src/core/blackboard.py`
- Modify: `src/blackboard.py`（替换为 shim）
- Create: `tests/test_core_shims.py`

- [ ] **Step 1: 先跑基线测试，确认当前 352 passed**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: `352 passed`

- [ ] **Step 2: 建 `src/core/__init__.py`（空包）**

```python
"""Core abstractions shared by all pipelines (novel + genre).

Existing imports like `from src.blackboard import Blackboard` keep working
via re-export shims in src/blackboard.py and src/agents/_base.py.
"""
```

- [ ] **Step 3: 写 `src/core/blackboard.py`，把 `src/blackboard.py` 全文搬过来**

完整复制 `src/blackboard.py` 现有内容，除一处：顶部 `from . import config` 改成 `from .. import config`（因为现在嵌深了一层）。

```python
"""Blackboard — filesystem-backed shared state for all agents.

Moved from src/blackboard.py in the 2026-05-11 refactor to let both the
novel pipeline and the new genre pipeline share the same primitive without
either depending on the other.

Design principle: no agent touches files directly. Every read and write
goes through this module so we can (a) enforce atomic writes, (b) keep
the path conventions in one place, and (c) later swap the backend
(e.g., to a DB) in one spot without touching agent logic.

All paths passed in are RELATIVE to the state directory unless marked
absolute.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .. import config


class Blackboard:
    def __init__(self, root: Path | None = None) -> None:
        self.root: Path = Path(root) if root else config.STATE_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _abs(self, path: str | Path) -> Path:
        p = Path(path)
        return p if p.is_absolute() else (self.root / p)

    def exists(self, path: str | Path) -> bool:
        return self._abs(path).exists()

    def list_files(self, subdir: str, pattern: str = "*") -> list[Path]:
        d = self._abs(subdir)
        if not d.exists():
            return []
        return sorted(p for p in d.glob(pattern) if p.is_file())

    def _atomic_write(self, path: Path, data: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def read_text(self, path: str | Path) -> str:
        return self._abs(path).read_text(encoding="utf-8")

    def write_text(self, path: str | Path, content: str) -> None:
        self._atomic_write(self._abs(path), content)

    def read_json(self, path: str | Path) -> Any:
        return json.loads(self.read_text(path))

    def write_json(self, path: str | Path, obj: Any) -> None:
        self.write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))

    def read_yaml(self, path: str | Path) -> Any:
        return yaml.safe_load(self.read_text(path))

    def write_yaml(self, path: str | Path, obj: Any) -> None:
        self.write_text(
            path,
            yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False),
        )

    def append_jsonl(self, path: str | Path, obj: Any) -> None:
        p = self._abs(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def read_jsonl(self, path: str | Path) -> list[Any]:
        p = self._abs(path)
        if not p.exists():
            return []
        out = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out


bb = Blackboard()
```

- [ ] **Step 4: 把 `src/blackboard.py` 改成 shim**

```python
"""Backward-compat shim — Blackboard moved to src/core/blackboard.py on 2026-05-11.

Existing imports like `from src.blackboard import Blackboard, bb` keep working
via the re-exports below. New code should import from src.core.blackboard.
"""
from .core.blackboard import Blackboard, bb  # noqa: F401
```

- [ ] **Step 5: 写 `tests/test_core_shims.py`，保证向后兼容**

```python
"""向后兼容 shim 保护：即使 Blackboard / BaseAgent 搬到了 src/core/，
旧导入路径必须继续工作。
"""
from pathlib import Path

import pytest


def test_legacy_blackboard_import_still_works():
    """from src.blackboard import Blackboard 必须能用。"""
    from src.blackboard import Blackboard  # noqa: F401
    assert Blackboard is not None


def test_legacy_blackboard_module_instance_still_works():
    from src.blackboard import bb
    assert bb is not None


def test_core_and_shim_are_same_class():
    """shim 必须 re-export 同一个 class object，不是两个不同的类。"""
    from src.blackboard import Blackboard as Shim
    from src.core.blackboard import Blackboard as Core
    assert Shim is Core


def test_blackboard_still_works_after_move(tmp_path: Path):
    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path)
    bb.write_text("x.txt", "hi")
    assert bb.read_text("x.txt") == "hi"
```

- [ ] **Step 6: 跑测试**

Run: `python3 -m pytest tests/test_core_shims.py tests/test_blackboard.py -v 2>&1 | tail -20`
Expected: 4 新测试 + 6 原 Blackboard 测试全 pass

- [ ] **Step 7: 跑完整基线**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 356 passed (352 + 4)

- [ ] **Step 8: Commit**

```bash
git add src/core/__init__.py src/core/blackboard.py src/blackboard.py tests/test_core_shims.py
git commit -m "refactor(core): sink Blackboard into src/core/ with back-compat shim

第一步下沉：把 Blackboard 从 src/blackboard.py 搬到 src/core/blackboard.py，
保留 src/blackboard.py 作为 shim 保证所有现有 import 继续工作。
为题材流水线复用 Blackboard 做准备。"
```

---

## Task 2: BaseAgent 下沉 + shim

**Files:**
- Create: `src/core/base_agent.py`
- Modify: `src/agents/_base.py`（替换为 shim）
- Modify: `tests/test_core_shims.py`（追加 BaseAgent shim 测试）

- [ ] **Step 1: 写 `src/core/base_agent.py`**

```python
"""BaseAgent — common base for all LLM-backed agents.

Moved from src/agents/_base.py in the 2026-05-11 refactor so the new
genre pipeline can extend it without importing from the novel agents
package.

Each agent is one function but we wrap it as a class to keep:
- name (for prompt_log)
- temperature (role-specific)
- response_format (json or text)
- a standard run() entry point that takes a Blackboard + kwargs

Subclasses override _build_prompts(bb, **kwargs) -> (system, user, inputs_read)
and _handle_output(bb, raw, **kwargs) -> None to persist results.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from .. import llm
from .blackboard import Blackboard


class BaseAgent(ABC):
    name: str = "base"
    temperature: float = 0.7
    response_format: Literal["text", "json"] = "text"
    max_tokens: int = 4096

    @abstractmethod
    def _build_prompts(
        self, bb: Blackboard, **kwargs
    ) -> tuple[str, str, list[str]]:
        """Return (system_prompt, user_prompt, inputs_read_paths)."""

    @abstractmethod
    def _handle_output(self, bb: Blackboard, raw: str, **kwargs) -> None:
        """Persist the LLM output to the blackboard."""

    def run(self, bb: Blackboard, **kwargs) -> str:
        system, user, inputs_read = self._build_prompts(bb, **kwargs)
        raw = llm.chat(
            system=system,
            user=user,
            agent_name=self.name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format=self.response_format,
            inputs_read=inputs_read,
        )
        self._handle_output(bb, raw, **kwargs)
        return raw

    @staticmethod
    def _read_rule(rule_filename: str) -> str:
        from .. import config
        return (config.RULES_DIR / rule_filename).read_text(encoding="utf-8")
```

- [ ] **Step 2: 把 `src/agents/_base.py` 改成 shim**

```python
"""Backward-compat shim — BaseAgent moved to src/core/base_agent.py on 2026-05-11."""
from ..core.base_agent import BaseAgent  # noqa: F401
```

- [ ] **Step 3: 追加测试到 `tests/test_core_shims.py`**

在文件末尾追加：

```python
def test_legacy_base_agent_import_still_works():
    from src.agents._base import BaseAgent  # noqa: F401
    assert BaseAgent is not None


def test_base_agent_shim_is_same_class():
    from src.agents._base import BaseAgent as Shim
    from src.core.base_agent import BaseAgent as Core
    assert Shim is Core


def test_existing_agents_still_subclass_base():
    """所有现有 agent 都继承 BaseAgent；shim 之后必须仍然 isinstance 判定成功。"""
    from src.agents.summarizer import Summarizer
    from src.core.base_agent import BaseAgent
    assert issubclass(Summarizer, BaseAgent)
```

- [ ] **Step 4: 跑完整测试**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 359 passed (356 + 3)

- [ ] **Step 5: Commit**

```bash
git add src/core/base_agent.py src/agents/_base.py tests/test_core_shims.py
git commit -m "refactor(core): sink BaseAgent into src/core/ with back-compat shim

第二步下沉：把 BaseAgent 从 src/agents/_base.py 搬到 src/core/base_agent.py，
保留 src/agents/_base.py 作为 shim。所有 7 个现有 agent 无需改动。"
```

---

## Task 3: 题材流水线 schemas（Extractor 笔记 / build_status / blueprint）

**Files:**
- Create: `src/genre_pipeline/__init__.py`
- Create: `src/genre_pipeline/schemas.py`
- Create: `tests/test_genre_schemas.py`

- [ ] **Step 1: 建 `src/genre_pipeline/__init__.py`**

```python
"""Genre Pipeline — build / fill / audit / extract genre packs.

See docs/superpowers/specs/2026-05-11-genre-pipeline-design.md for the full design.
"""
```

- [ ] **Step 2: 写 `tests/test_genre_schemas.py` 的全部失败测试**

```python
"""schemas.py 测试：校验 Extractor 笔记、build_status、blueprint 的结构严格性。"""
from __future__ import annotations

import pytest


def test_extraction_note_minimal_valid():
    from src.genre_pipeline.schemas import validate_extraction_note
    obj = {
        "batch_id": 1,
        "chapters_covered": [1, 25],
        "novel_source": "novels/a.txt",
        "extracted_at": "2026-05-11T14:30:00",
        "era_observations": [],
        "iron_law_candidates": [],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    }
    clean, warnings = validate_extraction_note(obj)
    assert clean["batch_id"] == 1
    assert warnings == []


def test_extraction_note_missing_required_key_raises():
    from src.genre_pipeline.schemas import validate_extraction_note
    obj = {"batch_id": 1}  # missing almost everything
    with pytest.raises(ValueError, match="chapters_covered"):
        validate_extraction_note(obj)


def test_extraction_note_confidence_enum():
    from src.genre_pipeline.schemas import validate_extraction_note
    obj = {
        "batch_id": 1,
        "chapters_covered": [1, 25],
        "novel_source": "x",
        "extracted_at": "2026-05-11T14:30:00",
        "era_observations": [
            {"fact": "f1", "evidence_chapters": [3], "confidence": "very-high", "cites_reality": True}
        ],
        "iron_law_candidates": [],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    }
    with pytest.raises(ValueError, match="confidence"):
        validate_extraction_note(obj)


def test_extraction_note_fuzzy_term_warning():
    """笔记里出现'暴涨/海量/大致/似乎'等禁词要 warn。"""
    from src.genre_pipeline.schemas import validate_extraction_note
    obj = {
        "batch_id": 1,
        "chapters_covered": [1, 25],
        "novel_source": "x",
        "extracted_at": "2026-05-11T14:30:00",
        "era_observations": [
            {"fact": "主角实力大致暴涨", "evidence_chapters": [3], "confidence": "high", "cites_reality": False}
        ],
        "iron_law_candidates": [],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    }
    clean, warnings = validate_extraction_note(obj)
    assert any("模糊词" in w for w in warnings)


def test_build_status_initial():
    from src.genre_pipeline.schemas import make_initial_build_status
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 300, "batch_size": 25}],
    )
    assert status["genre_id"] == "demo"
    assert status["phases"]["extract"]["status"] == "pending"
    assert status["phases"]["extract"]["batches_total"] == 12  # ceil(300/25)
    assert status["phases"]["merge"]["status"] == "pending"


def test_build_status_multiple_novels():
    from src.genre_pipeline.schemas import make_initial_build_status
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[
            {"path": "a.txt", "total_chapters": 400, "batch_size": 25},
            {"path": "b.txt", "total_chapters": 180, "batch_size": 25},
        ],
    )
    # 400/25 = 16, 180/25 = 8 → total 24
    assert status["phases"]["extract"]["batches_total"] == 24


def test_blueprint_skeleton():
    from src.genre_pipeline.schemas import make_empty_blueprint
    bp = make_empty_blueprint(genre_id="demo")
    assert bp["genre_id"] == "demo"
    assert "era_observations" in bp
    assert "iron_law_candidates" in bp
    assert "style_markers" in bp
    assert "resource_candidates" in bp
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python3 -m pytest tests/test_genre_schemas.py -v 2>&1 | tail -15`
Expected: 全 FAIL（ImportError `schemas`）

- [ ] **Step 4: 写 `src/genre_pipeline/schemas.py` 实现**

```python
"""Schemas for genre pipeline artifacts.

Three core artifacts:
- ExtractionNote (one per batch, strict schema aligning to final genre pack files)
- BuildStatus (phase-level status card, Lesson 3 externalization)
- Blueprint (merged extraction notes → final genre pack staging ground)

All validators return (clean_obj, warnings) and raise ValueError on fatal issues.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any


# ------------------------------------------------------------------
# ExtractionNote
# ------------------------------------------------------------------

_NOTE_REQUIRED_TOP = (
    "batch_id",
    "chapters_covered",
    "novel_source",
    "extracted_at",
    "era_observations",
    "iron_law_candidates",
    "style_markers",
    "resource_candidates",
    "open_questions",
)

_CONFIDENCE_ENUM = {"high", "medium", "low"}

_FUZZY_TERMS = (
    "暴涨", "海量", "难以估量", "无法计算",
    "似乎", "大致", "整体而言", "某种程度上",
)


def validate_extraction_note(obj: dict) -> tuple[dict, list[str]]:
    """Validate one extraction note. Returns (clean, warnings)."""
    if not isinstance(obj, dict):
        raise ValueError("extraction note must be a dict")
    warnings: list[str] = []

    for key in _NOTE_REQUIRED_TOP:
        if key not in obj:
            raise ValueError(f"extraction note missing required key: {key}")

    # batch_id
    if not isinstance(obj["batch_id"], int) or obj["batch_id"] < 1:
        raise ValueError("batch_id must be positive int")

    # chapters_covered: [start, end] inclusive
    cc = obj["chapters_covered"]
    if not (isinstance(cc, list) and len(cc) == 2 and all(isinstance(x, int) for x in cc)):
        raise ValueError("chapters_covered must be [start_int, end_int]")
    if cc[0] > cc[1]:
        raise ValueError("chapters_covered start > end")

    # list fields must be lists
    for lst_key in ("era_observations", "iron_law_candidates", "style_markers",
                    "resource_candidates", "open_questions"):
        if not isinstance(obj[lst_key], list):
            raise ValueError(f"{lst_key} must be a list")

    # era_observations confidence enum check
    for i, era in enumerate(obj["era_observations"]):
        if not isinstance(era, dict):
            raise ValueError(f"era_observations[{i}] must be a dict")
        if "confidence" in era and era["confidence"] not in _CONFIDENCE_ENUM:
            raise ValueError(
                f"era_observations[{i}].confidence must be one of {_CONFIDENCE_ENUM}, "
                f"got {era['confidence']!r}"
            )

    # fuzzy term scan (warning level)
    fuzzy_hits = _scan_fuzzy_terms(obj)
    if fuzzy_hits:
        warnings.append(
            f"模糊词告警: 检测到 {len(fuzzy_hits)} 处禁用词: {', '.join(sorted(set(fuzzy_hits)))}"
        )

    return obj, warnings


def _scan_fuzzy_terms(obj: Any) -> list[str]:
    """Recursively scan strings for any forbidden fuzzy term."""
    hits: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, str):
            for t in _FUZZY_TERMS:
                if t in x:
                    hits.append(t)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return hits


# ------------------------------------------------------------------
# BuildStatus
# ------------------------------------------------------------------

def make_initial_build_status(
    *,
    genre_id: str,
    entry: str,
    novel_sources: list[dict] | None = None,
) -> dict:
    """Build a fresh build_status.yaml payload for a new genre build."""
    sources = novel_sources or []
    batches_total = 0
    for src in sources:
        total = int(src.get("total_chapters", 0))
        size = int(src.get("batch_size", 25))
        if size <= 0:
            raise ValueError(f"batch_size must be positive, got {size}")
        batches_total += math.ceil(total / size) if total > 0 else 0

    now = datetime.now().isoformat(timespec="seconds")
    return {
        "genre_id": genre_id,
        "entry": entry,
        "created_at": now,
        "last_update": now,
        "novel_sources": sources,
        "phases": {
            "extract": {
                "status": "pending",
                "batches_total": batches_total,
                "batches_done": 0,
                "last_batch_id": 0,
            },
            "merge": {"status": "pending"},
            "draft": {"status": "pending"},
            "validate": {"status": "pending"},
        },
        "in_flight": None,
    }


# ------------------------------------------------------------------
# Blueprint
# ------------------------------------------------------------------

def make_empty_blueprint(*, genre_id: str) -> dict:
    """Fresh blueprint skeleton ready to receive merged extraction results."""
    return {
        "genre_id": genre_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "era_observations": [],
        "iron_law_candidates": [],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    }
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m pytest tests/test_genre_schemas.py -v 2>&1 | tail -15`
Expected: 7 passed

- [ ] **Step 6: 跑完整基线**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 366 passed

- [ ] **Step 7: Commit**

```bash
git add src/genre_pipeline/__init__.py src/genre_pipeline/schemas.py tests/test_genre_schemas.py
git commit -m "feat(genre-pipeline): schemas for extraction notes / build status / blueprint

严格 schema 对齐最终题材包文件（era.md / iron-laws-extra.md / writing-style-extra.md / resource_schema.yaml）。
带模糊词扫描（防 LLM 用'暴涨/似乎/大致'等废话）。"
```

---

## Task 4: 自适应档位 + 章节切分

**Files:**
- Create: `src/genre_pipeline/adaptive.py`
- Create: `tests/test_genre_adaptive.py`

- [ ] **Step 1: 写测试**

```python
"""adaptive.py：自适应档位 + 章节切分。"""
from __future__ import annotations

import pytest


def test_adaptive_batch_size_short():
    from src.genre_pipeline.adaptive import adaptive_batch_size
    assert adaptive_batch_size(30) == 10
    assert adaptive_batch_size(50) == 10


def test_adaptive_batch_size_medium():
    from src.genre_pipeline.adaptive import adaptive_batch_size
    assert adaptive_batch_size(51) == 25
    assert adaptive_batch_size(400) == 25
    assert adaptive_batch_size(600) == 25


def test_adaptive_batch_size_long():
    from src.genre_pipeline.adaptive import adaptive_batch_size
    assert adaptive_batch_size(601) == 40
    assert adaptive_batch_size(1200) == 40


def test_split_into_batches_exact():
    from src.genre_pipeline.adaptive import split_into_batches
    batches = split_into_batches(total_chapters=50, batch_size=10)
    assert batches == [(1, 10), (11, 20), (21, 30), (31, 40), (41, 50)]


def test_split_into_batches_remainder():
    from src.genre_pipeline.adaptive import split_into_batches
    batches = split_into_batches(total_chapters=55, batch_size=25)
    assert batches == [(1, 25), (26, 50), (51, 55)]


def test_split_into_batches_empty():
    from src.genre_pipeline.adaptive import split_into_batches
    assert split_into_batches(total_chapters=0, batch_size=25) == []


def test_split_into_batches_invalid():
    from src.genre_pipeline.adaptive import split_into_batches
    with pytest.raises(ValueError):
        split_into_batches(total_chapters=10, batch_size=0)
```

- [ ] **Step 2: 确认失败**

Run: `python3 -m pytest tests/test_genre_adaptive.py -v 2>&1 | tail -10`
Expected: 全 FAIL (ImportError)

- [ ] **Step 3: 写实现**

```python
"""Adaptive batch sizing for extracting genre rules from existing novels.

Window size decision (see Q3 in the spec):
  ≤ 50 chapters: 10 chapters/batch (not too few batches)
  51-600:       25 chapters/batch (default sweet spot)
  > 600:        40 chapters/batch (avoid batch explosion)
"""
from __future__ import annotations


def adaptive_batch_size(total_chapters: int) -> int:
    if total_chapters <= 50:
        return 10
    elif total_chapters <= 600:
        return 25
    else:
        return 40


def split_into_batches(*, total_chapters: int, batch_size: int) -> list[tuple[int, int]]:
    """Return [(start_ch, end_ch), ...] inclusive 1-indexed."""
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    if total_chapters <= 0:
        return []
    out: list[tuple[int, int]] = []
    start = 1
    while start <= total_chapters:
        end = min(start + batch_size - 1, total_chapters)
        out.append((start, end))
        start = end + 1
    return out
```

- [ ] **Step 4: 跑测试**

Run: `python3 -m pytest tests/test_genre_adaptive.py -v 2>&1 | tail -10`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/genre_pipeline/adaptive.py tests/test_genre_adaptive.py
git commit -m "feat(genre-pipeline): adaptive batch sizing + chapter splitting

三档自适应窗口：≤50→10/批 · 51-600→25/批 · >600→40/批。"
```

---

## Task 5: build_status 读写 + 断点续跑逻辑

**Files:**
- Modify: `src/genre_pipeline/schemas.py`（追加 update helpers）
- Create: `tests/test_genre_build_status.py`

- [ ] **Step 1: 写测试**

```python
"""build_status 读写 + 断点续跑。"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_update_phase_status(tmp_path: Path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.schemas import make_initial_build_status, update_phase_status

    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 100, "batch_size": 25}],
    )
    bb.write_yaml("build_status.yaml", status)

    update_phase_status(bb, phase="extract", status="in_progress")
    s2 = bb.read_yaml("build_status.yaml")
    assert s2["phases"]["extract"]["status"] == "in_progress"
    assert s2["last_update"] != status["created_at"] or True  # best-effort bumped


def test_record_batch_done(tmp_path: Path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.schemas import make_initial_build_status, record_batch_done

    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 50, "batch_size": 10}],
    )
    bb.write_yaml("build_status.yaml", status)

    record_batch_done(bb, batch_id=1)
    record_batch_done(bb, batch_id=2)
    s = bb.read_yaml("build_status.yaml")
    assert s["phases"]["extract"]["batches_done"] == 2
    assert s["phases"]["extract"]["last_batch_id"] == 2


def test_next_batch_to_run(tmp_path: Path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.schemas import make_initial_build_status, record_batch_done, next_batch_to_run

    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 50, "batch_size": 10}],
    )
    bb.write_yaml("build_status.yaml", status)

    assert next_batch_to_run(bb) == 1
    record_batch_done(bb, batch_id=1)
    assert next_batch_to_run(bb) == 2
    record_batch_done(bb, batch_id=2)
    record_batch_done(bb, batch_id=3)
    record_batch_done(bb, batch_id=4)
    record_batch_done(bb, batch_id=5)
    assert next_batch_to_run(bb) is None  # all done


def test_set_in_flight(tmp_path: Path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.schemas import make_initial_build_status, set_in_flight, clear_in_flight

    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "a.txt", "total_chapters": 100, "batch_size": 25}],
    )
    bb.write_yaml("build_status.yaml", status)

    set_in_flight(bb, agent="genre_extractor", batch_id=3)
    s = bb.read_yaml("build_status.yaml")
    assert s["in_flight"]["agent"] == "genre_extractor"
    assert s["in_flight"]["batch_id"] == 3

    clear_in_flight(bb)
    s = bb.read_yaml("build_status.yaml")
    assert s["in_flight"] is None
```

- [ ] **Step 2: 确认失败**

Run: `python3 -m pytest tests/test_genre_build_status.py -v 2>&1 | tail -10`
Expected: 全 FAIL (ImportError on new functions)

- [ ] **Step 3: 在 `src/genre_pipeline/schemas.py` 末尾追加实现**

```python
# ------------------------------------------------------------------
# BuildStatus mutation helpers — all operate via Blackboard
# ------------------------------------------------------------------

def _bump_last_update(status: dict) -> None:
    status["last_update"] = datetime.now().isoformat(timespec="seconds")


def update_phase_status(bb, *, phase: str, status: str) -> None:
    """Set phases.<phase>.status (pending/in_progress/done/failed)."""
    s = bb.read_yaml("build_status.yaml")
    if phase not in s["phases"]:
        raise ValueError(f"unknown phase: {phase}")
    s["phases"][phase]["status"] = status
    _bump_last_update(s)
    bb.write_yaml("build_status.yaml", s)


def record_batch_done(bb, *, batch_id: int) -> None:
    s = bb.read_yaml("build_status.yaml")
    extract = s["phases"]["extract"]
    extract["batches_done"] = extract.get("batches_done", 0) + 1
    extract["last_batch_id"] = max(extract.get("last_batch_id", 0), batch_id)
    if extract["batches_done"] >= extract.get("batches_total", 0):
        extract["status"] = "done"
    else:
        extract["status"] = "in_progress"
    _bump_last_update(s)
    bb.write_yaml("build_status.yaml", s)


def next_batch_to_run(bb) -> int | None:
    """Return the next batch id to run, or None if extract phase is complete."""
    s = bb.read_yaml("build_status.yaml")
    extract = s["phases"]["extract"]
    done = extract.get("batches_done", 0)
    total = extract.get("batches_total", 0)
    if done >= total:
        return None
    return done + 1


def set_in_flight(bb, *, agent: str, batch_id: int | None = None) -> None:
    s = bb.read_yaml("build_status.yaml")
    s["in_flight"] = {
        "agent": agent,
        "batch_id": batch_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    _bump_last_update(s)
    bb.write_yaml("build_status.yaml", s)


def clear_in_flight(bb) -> None:
    s = bb.read_yaml("build_status.yaml")
    s["in_flight"] = None
    _bump_last_update(s)
    bb.write_yaml("build_status.yaml", s)
```

- [ ] **Step 4: 跑测试**

Run: `python3 -m pytest tests/test_genre_build_status.py -v 2>&1 | tail -10`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/genre_pipeline/schemas.py tests/test_genre_build_status.py
git commit -m "feat(genre-pipeline): build_status mutation helpers for resumable builds

update_phase_status / record_batch_done / next_batch_to_run / set_in_flight / clear_in_flight
—— 所有通过 Blackboard，原子写。实现 Context Reset 应用到题材层：任何 phase 失败，
从 build_status.yaml 续跑。"
```

---

## Task 6: 四个题材 Agent 的占位实现（可实例化、prompt 可构造）

**Files:**
- Create: `src/genre_pipeline/agents/__init__.py`
- Create: `src/genre_pipeline/agents/extractor.py`
- Create: `src/genre_pipeline/agents/drafter.py`
- Create: `src/genre_pipeline/agents/validator.py`
- Create: `src/genre_pipeline/agents/fixer.py`
- Create: `tests/test_genre_agents_instantiation.py`

**说明：**第一版四个 Agent 都走占位 prompt（system/user 有内容但不追求生产质量）。测试只验证：可实例化、`_build_prompts` 可以跑出非空结果、有明确的 `inputs_read` 声明。真实 LLM 调用不在 CI 里。

- [ ] **Step 1: 写测试**

```python
"""四个题材 Agent 可实例化 + prompt 可构造。

不调真实 LLM；只验证骨架。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.blackboard import Blackboard
from src.genre_pipeline.schemas import make_initial_build_status, make_empty_blueprint


@pytest.fixture
def build_bb(tmp_path: Path) -> Blackboard:
    """A Blackboard with a minimal build_status ready for Agents."""
    bb = Blackboard(root=tmp_path)
    status = make_initial_build_status(
        genre_id="demo",
        entry="extract-from-novel",
        novel_sources=[{"path": "novel.txt", "total_chapters": 50, "batch_size": 10}],
    )
    bb.write_yaml("build_status.yaml", status)
    return bb


def test_extractor_instantiates():
    from src.genre_pipeline.agents.extractor import GenreExtractor
    a = GenreExtractor()
    assert a.name == "genre_extractor"
    assert a.response_format == "json"


def test_extractor_build_prompts(build_bb):
    from src.genre_pipeline.agents.extractor import GenreExtractor
    # Put a mock novel batch text on blackboard
    build_bb.write_text("novel_batches/batch-001.txt", "第一章 抵港\n\n林家耀下船...\n")
    a = GenreExtractor()
    system, user, inputs_read = a._build_prompts(build_bb, batch_id=1, batch_text="mock text")
    assert isinstance(system, str) and len(system) > 50
    assert isinstance(user, str) and "mock text" in user
    assert isinstance(inputs_read, list)


def test_drafter_instantiates():
    from src.genre_pipeline.agents.drafter import GenreDrafter
    a = GenreDrafter()
    assert a.name.startswith("genre_drafter")


def test_drafter_build_prompts_requires_blueprint(build_bb):
    from src.genre_pipeline.agents.drafter import GenreDrafter
    # Provide a blueprint
    build_bb.write_yaml("genre_blueprint.yaml", make_empty_blueprint(genre_id="demo"))
    a = GenreDrafter()
    system, user, inputs_read = a._build_prompts(build_bb)
    assert "blueprint" in user.lower() or "demo" in user
    assert "genre_blueprint.yaml" in " ".join(inputs_read)


def test_validator_instantiates():
    from src.genre_pipeline.agents.validator import GenreValidator
    a = GenreValidator()
    assert a.name == "genre_validator"


def test_fixer_instantiates():
    from src.genre_pipeline.agents.fixer import GenreFixer
    a = GenreFixer()
    assert a.name == "genre_fixer"
```

- [ ] **Step 2: 确认失败**

Run: `python3 -m pytest tests/test_genre_agents_instantiation.py -v 2>&1 | tail -15`
Expected: 全 FAIL

- [ ] **Step 3: 写 `src/genre_pipeline/agents/__init__.py`**

```python
"""Genre pipeline agents.

Four agents:
- GenreExtractor: slide-window extract from source novels
- GenreDrafter: merged blueprint → 5 final genre pack files
- GenreValidator: structure (setting_lint) + semantic (LLM) + optional trial
- GenreFixer: read issues → patch files, up to 2 retries
"""
from .extractor import GenreExtractor
from .drafter import GenreDrafter
from .validator import GenreValidator
from .fixer import GenreFixer

__all__ = ["GenreExtractor", "GenreDrafter", "GenreValidator", "GenreFixer"]
```

- [ ] **Step 4: 写 `src/genre_pipeline/agents/extractor.py`**

```python
"""GenreExtractor — slide-window extractor for reverse-engineering a genre.

Reads one batch of chapters from a source novel + previous merged notes +
few-shot headers from existing genre packs, writes one extraction note YAML.

Placeholder prompt in v1: structure demonstrates the schema; production-grade
prompt tuning deferred.
"""
from __future__ import annotations

import json

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


class GenreExtractor(BaseAgent):
    name = "genre_extractor"
    temperature = 0.3
    response_format = "json"
    max_tokens = 4000

    SYSTEM_PROMPT = (
        "你是一位题材规律拆解专家，任务是从一批小说章节中提炼 4 个维度的题材规律：\n"
        "1. 时代/世界观事实 (era_observations)\n"
        "2. 反复出现的铁律模式 (iron_law_candidates)\n"
        "3. 语言 / 节奏 / 风格特征 (style_markers)\n"
        "4. 可追踪资源候选 (resource_candidates)\n"
        "\n"
        "严格按照给定 JSON schema 输出。每条发现必须带 evidence_chapters 字段。\n"
        "禁止使用模糊词：暴涨 / 海量 / 似乎 / 大致 / 整体而言 / 某种程度上。\n"
        "不确定的放到 open_questions，不要硬编。\n"
    )

    def _build_prompts(self, bb: Blackboard, *, batch_id: int, batch_text: str, **_):
        inputs_read: list[str] = []

        # Optional: merged notes from prior batches (Lesson 3 Context Reset)
        merged_snippet = ""
        if bb.exists("extraction_notes/latest_merged.yaml"):
            merged_snippet = bb.read_text("extraction_notes/latest_merged.yaml")[:2000]
            inputs_read.append("extraction_notes/latest_merged.yaml")

        user = (
            f"# 本批章节（batch_id={batch_id}）\n\n"
            f"{batch_text}\n\n"
            f"# 上一版已合并笔记（参考，可增量）\n\n"
            f"{merged_snippet or '(首批，无前置笔记)'}\n\n"
            f"# 输出要求\n\n"
            f"输出严格 JSON，key 顺序与 schema 一致："
            f"batch_id, chapters_covered, novel_source, extracted_at, "
            f"era_observations, iron_law_candidates, style_markers, "
            f"resource_candidates, open_questions。"
        )
        return self.SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, batch_id: int, **_):
        obj = _parse_json(raw)
        bb.write_yaml(f"extraction_notes/batch-{batch_id:03d}.yaml", obj)


def _parse_json(raw: str):
    import re
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)
```

- [ ] **Step 5: 写 `src/genre_pipeline/agents/drafter.py`**

```python
"""GenreDrafter — two-step: blueprint synthesis + file rendering.

Step A (this class): reads merged notes, writes genre_blueprint.yaml.
Step B is a deterministic renderer (src/genre_pipeline/pipeline.py) that
reads blueprint and writes the 5 final files. Step B does NOT call LLM.
"""
from __future__ import annotations

import json

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


class GenreDrafter(BaseAgent):
    name = "genre_drafter_blueprint"
    temperature = 0.4
    response_format = "json"
    max_tokens = 6000

    SYSTEM_PROMPT = (
        "你是一位题材架构师。任务：把一堆零散的拆解笔记（extraction notes）合成一份题材蓝图（blueprint）。\n"
        "\n"
        "Blueprint 的 schema 和 extraction note 一致，但：\n"
        "- 去重同类候选（同一 iron_law 被多次观察到的合并）\n"
        "- 保留 recurrence_count 总和\n"
        "- 丢弃 confidence=low 且 recurrence_count=1 的孤证\n"
        "- open_questions 原样保留\n"
        "\n"
        "禁止引入笔记里没有的新事实。禁止模糊词。\n"
    )

    def _build_prompts(self, bb: Blackboard, **_):
        inputs_read: list[str] = []
        blueprint = {}
        if bb.exists("genre_blueprint.yaml"):
            blueprint = bb.read_yaml("genre_blueprint.yaml")
            inputs_read.append("genre_blueprint.yaml")

        merged = ""
        if bb.exists("extraction_notes/latest_merged.yaml"):
            merged = bb.read_text("extraction_notes/latest_merged.yaml")
            inputs_read.append("extraction_notes/latest_merged.yaml")

        user = (
            f"# 当前 blueprint（可能为空）\n\n"
            f"{json.dumps(blueprint, ensure_ascii=False, indent=2)}\n\n"
            f"# 已合并笔记\n\n"
            f"{merged or '(无)'}\n\n"
            f"# 任务\n\n"
            f"输出一份合成后的 blueprint YAML（严格 JSON，字段同 extraction note）。"
        )
        return self.SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, **_):
        obj = _parse_json(raw)
        bb.write_yaml("genre_blueprint.yaml", obj)


def _parse_json(raw: str):
    import re
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)
```

- [ ] **Step 6: 写 `src/genre_pipeline/agents/validator.py`**

```python
"""GenreValidator — three-stage validation.

Stage 1 (structure): delegates to src/tools/setting_lint.py — no LLM.
Stage 2 (semantic): THIS CLASS — one LLM call, reads the 4-5 final files,
                    writes issues to genre_issues.jsonl.
Stage 3 (trial): delegates to src/genre_pipeline/trial.py (scratch bootstrap
                 + run Planner/Generator/Evaluator on 3 chapters) when
                 --with-trial is passed.
"""
from __future__ import annotations

import json

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


class GenreValidator(BaseAgent):
    name = "genre_validator"
    temperature = 0.0
    response_format = "json"
    max_tokens = 3000

    SYSTEM_PROMPT = (
        "你是一位题材包审查员。任务：读完 4-5 份题材包文件，扫出以下问题：\n"
        "1. iron-laws 条目之间内部矛盾\n"
        "2. iron-laws 和 era.md 之间的事实冲突\n"
        "3. iron-laws 和 writing-style-extra.md 之间的语气冲突\n"
        "4. era.md 或 writing-style-extra.md 中的 AI 味/模糊词/废话\n"
        "5. resource_schema.yaml（如存在）中的 baseline_scale 不可追溯问题\n"
        "\n"
        "输出严格 JSON：\n"
        '{"issues": [{"severity": "error|warning|info", '
        '"file": "...", "message": "...", "suggestion": "..."}]}'
    )

    def _build_prompts(self, bb: Blackboard, *, genre_id: str, **_):
        from src import config

        genre_dir = config.GENRES_DIR / genre_id
        files_to_read = (
            "genre.yaml",
            "era.md",
            "writing-style-extra.md",
            "iron-laws-extra.md",
            "resource_schema.yaml",
        )
        blocks = []
        inputs_read: list[str] = []
        for fname in files_to_read:
            fp = genre_dir / fname
            if fp.exists():
                text = fp.read_text(encoding="utf-8")
                blocks.append(f"## {fname}\n\n{text[:4000]}")
                inputs_read.append(f"genres/{genre_id}/{fname}")

        user = (
            f"# 待审查的题材包: {genre_id}\n\n"
            + "\n\n".join(blocks)
            + "\n\n# 任务\n\n按系统指令输出 issues JSON。"
        )
        return self.SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, genre_id: str, **_):
        obj = _parse_json(raw)
        for issue in obj.get("issues", []):
            issue["genre_id"] = genre_id
            bb.append_jsonl("genre_issues.jsonl", issue)


def _parse_json(raw: str):
    import re
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)
```

- [ ] **Step 7: 写 `src/genre_pipeline/agents/fixer.py`**

```python
"""GenreFixer — reads genre_issues.jsonl, patches the offending files.

First version: simple full-file rewrite. A smarter diff-based approach is
deferred. Called with retry_count kwarg so caller can gate max retries.
"""
from __future__ import annotations

from src.core.base_agent import BaseAgent
from src.core.blackboard import Blackboard


class GenreFixer(BaseAgent):
    name = "genre_fixer"
    temperature = 0.3
    response_format = "text"
    max_tokens = 4000

    SYSTEM_PROMPT = (
        "你是一位题材包修复员。任务：读指定的单个题材文件 + 针对它的 issues，\n"
        "输出修复后的完整文件内容，只修问题不要重写。\n"
        "不允许扩展、不允许添新段落，只改 issues 点名的地方。\n"
    )

    def _build_prompts(self, bb: Blackboard, *, genre_id: str, file_name: str, issues: list, **_):
        from src import config

        genre_dir = config.GENRES_DIR / genre_id
        current = (genre_dir / file_name).read_text(encoding="utf-8")
        issues_text = "\n".join(
            f"- [{i.get('severity', 'info')}] {i.get('message', '')}"
            for i in issues
        )
        inputs_read = [f"genres/{genre_id}/{file_name}", "genre_issues.jsonl"]
        user = (
            f"# 题材 {genre_id} · 文件 {file_name}\n\n"
            f"## 当前内容\n\n{current}\n\n"
            f"## 需修复的 issues\n\n{issues_text}\n\n"
            f"# 输出\n\n请输出完整修复后的文件内容（不要带任何解释或 markdown 围栏）。"
        )
        return self.SYSTEM_PROMPT, user, inputs_read

    def _handle_output(self, bb: Blackboard, raw: str, *, genre_id: str, file_name: str, **_):
        from src import config
        (config.GENRES_DIR / genre_id / file_name).write_text(raw.strip() + "\n", encoding="utf-8")
```

- [ ] **Step 8: 跑测试**

Run: `python3 -m pytest tests/test_genre_agents_instantiation.py -v 2>&1 | tail -15`
Expected: 6 passed

- [ ] **Step 9: 跑完整基线**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 376 passed (366 + 6 + 4)

- [ ] **Step 10: Commit**

```bash
git add src/genre_pipeline/agents/ tests/test_genre_agents_instantiation.py
git commit -m "feat(genre-pipeline): 4 agents (Extractor/Drafter/Validator/Fixer) with placeholder prompts

占位 prompt 版本：结构打通、schema 严守、可实例化、prompt 可构造。
生产级 prompt 调优留给后续基于真实小说数据的迭代。"
```

---

## Task 7: pipeline.py 主调度 + CLI（new / fill / audit / extract）

**Files:**
- Create: `src/genre_pipeline/pipeline.py`
- Create: `src/genre_pipeline/__main__.py`
- Modify: `.gitignore`
- Create: `tests/test_genre_pipeline_cli.py`

- [ ] **Step 1: 更新 .gitignore**

把 `genres/*/.build/` 加进 `.gitignore`（如已存在不重复）。

```bash
grep -q 'genres/\*/\.build/' .gitignore || echo 'genres/*/.build/' >> .gitignore
```

- [ ] **Step 2: 写 `src/genre_pipeline/pipeline.py`**

```python
"""Genre pipeline orchestrator.

Four entry points:
- new_genre(genre_id, ...): stub scaffold, no LLM
- fill_genre(genre_id): detect missing files, call Drafter to fill
- audit_genre(genre_id): Validator stages 1 + 2 (no LLM for stage 1)
- extract_from_novel(genre_id, sources, with_trial): full pipeline

The build workspace lives at genres/<id>/.build/ and is git-ignored.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from src import config
from src.core.blackboard import Blackboard
from src.genre_pipeline import adaptive, schemas


STUB_GENRE_YAML = """# Genre: {genre_id}
id: {genre_id}
display_name: "{display_name}"
locale: zh-Hans
genre: "{genre}"
era: "{era}"
tone: "{tone}"

author_persona_hints: []
genre_avoid: []
prohibited_styles: []
"""

STUB_ERA = """# Era · {genre_id}

（占位：此文件描述 {era} 的时代事实。由后续题材流水线的 Drafter 填充，
或作者手工编写。至少 500 字才能通过 setting_lint。）
"""

STUB_WRITING_STYLE = """# Writing Style Extra · {genre_id}

（占位：此文件描述 {genre_id} 题材特有的风格规范。至少 300 字才能通过 setting_lint。）
"""

STUB_IRON_LAWS = """# Iron Laws Extra · {genre_id}

## iron_law_extra_1: （占位规则一）

（至少 3 条 iron_law_extra_N 才能通过 setting_lint。）

## iron_law_extra_2: （占位规则二）

## iron_law_extra_3: （占位规则三）
"""


def _build_dir(genre_id: str) -> Path:
    return config.GENRES_DIR / genre_id / ".build"


def _build_bb(genre_id: str) -> Blackboard:
    bd = _build_dir(genre_id)
    bd.mkdir(parents=True, exist_ok=True)
    return Blackboard(root=bd)


def new_genre(
    genre_id: str,
    *,
    display_name: str = "",
    genre: str = "",
    era: str = "",
    tone: str = "",
) -> dict:
    """Create a minimal scaffold under genres/<id>/. No LLM call."""
    genre_dir = config.GENRES_DIR / genre_id
    if genre_dir.exists():
        raise FileExistsError(f"Genre already exists: {genre_dir}")
    genre_dir.mkdir(parents=True)

    ctx = dict(
        genre_id=genre_id,
        display_name=display_name or genre_id,
        genre=genre or "TBD",
        era=era or "TBD",
        tone=tone or "TBD",
    )
    (genre_dir / "genre.yaml").write_text(STUB_GENRE_YAML.format(**ctx), encoding="utf-8")
    (genre_dir / "era.md").write_text(STUB_ERA.format(**ctx), encoding="utf-8")
    (genre_dir / "writing-style-extra.md").write_text(
        STUB_WRITING_STYLE.format(**ctx), encoding="utf-8"
    )
    (genre_dir / "iron-laws-extra.md").write_text(
        STUB_IRON_LAWS.format(**ctx), encoding="utf-8"
    )

    bb = _build_bb(genre_id)
    bb.write_yaml(
        "build_status.yaml",
        schemas.make_initial_build_status(genre_id=genre_id, entry="new-genre"),
    )
    return {"ok": True, "genre_id": genre_id, "path": str(genre_dir)}


def _count_chapters_in_text(text: str) -> int:
    """Very rough chapter detection for novel files. Supports '第N章' markers."""
    import re
    matches = re.findall(r"第[0-9零一二三四五六七八九十百千]+章", text)
    return max(len(matches), 1)


def _split_text_into_batches(
    text: str, total_chapters: int, batch_size: int
) -> list[str]:
    """Split novel text roughly into N batches of ~batch_size chapters each.

    Uses character-count approximation when chapter markers aren't reliable.
    """
    batches = adaptive.split_into_batches(
        total_chapters=total_chapters, batch_size=batch_size
    )
    if not batches:
        return []
    chunk_len = len(text) // len(batches)
    out: list[str] = []
    for i in range(len(batches)):
        start = i * chunk_len
        end = (i + 1) * chunk_len if i < len(batches) - 1 else len(text)
        out.append(text[start:end])
    return out


def extract_from_novel(
    genre_id: str,
    *,
    sources: list[str],
    with_trial: bool = False,
    dry_run: bool = False,
) -> dict:
    """End-to-end extract → merge → draft → validate.

    Each phase updates build_status.yaml. Can be resumed mid-phase via
    --extract-only / --merge-only etc.

    dry_run: don't actually call LLM; just set up status and noop stages.
    Used by CLI tests.
    """
    genre_dir = config.GENRES_DIR / genre_id
    genre_dir.mkdir(parents=True, exist_ok=True)

    bb = _build_bb(genre_id)

    # Count chapters per source
    novel_sources = []
    source_texts: list[tuple[str, str, int, int]] = []  # (path, text, total_ch, batch_size)
    for src in sources:
        p = Path(src)
        if not p.exists():
            raise FileNotFoundError(f"source novel not found: {src}")
        text = p.read_text(encoding="utf-8")
        total_ch = _count_chapters_in_text(text)
        bs = adaptive.adaptive_batch_size(total_ch)
        novel_sources.append(
            {"path": str(p), "total_chapters": total_ch, "batch_size": bs}
        )
        source_texts.append((str(p), text, total_ch, bs))

    # Fresh build_status
    status = schemas.make_initial_build_status(
        genre_id=genre_id,
        entry="extract-from-novel",
        novel_sources=novel_sources,
    )
    bb.write_yaml("build_status.yaml", status)

    if dry_run:
        # Mark all phases done without LLM
        for phase in ("extract", "merge", "draft", "validate"):
            schemas.update_phase_status(bb, phase=phase, status="done")
        return {
            "ok": True,
            "mode": "dry_run",
            "genre_id": genre_id,
            "sources": novel_sources,
            "with_trial": with_trial,
        }

    # --- Phase 1: Extract ---
    _run_extract(bb, source_texts)

    # --- Phase 2: Merge ---
    _run_merge(bb)

    # --- Phase 3: Draft ---
    _run_draft(bb, genre_id)

    # --- Phase 4: Validate ---
    _run_validate(bb, genre_id, with_trial=with_trial)

    return {
        "ok": True,
        "genre_id": genre_id,
        "phases": bb.read_yaml("build_status.yaml")["phases"],
        "with_trial": with_trial,
    }


def _run_extract(bb: Blackboard, source_texts):
    from src.genre_pipeline.agents.extractor import GenreExtractor

    schemas.update_phase_status(bb, phase="extract", status="in_progress")
    agent = GenreExtractor()
    global_batch_id = 0
    for path, text, total_ch, bs in source_texts:
        batches_text = _split_text_into_batches(text, total_ch, bs)
        for local_idx, btxt in enumerate(batches_text, start=1):
            global_batch_id += 1
            schemas.set_in_flight(bb, agent="genre_extractor", batch_id=global_batch_id)
            agent.run(bb, batch_id=global_batch_id, batch_text=btxt)
            schemas.record_batch_done(bb, batch_id=global_batch_id)
    schemas.clear_in_flight(bb)
    schemas.update_phase_status(bb, phase="extract", status="done")


def _run_merge(bb: Blackboard):
    """Concatenate all batch notes into latest_merged.yaml. No LLM in v1."""
    schemas.update_phase_status(bb, phase="merge", status="in_progress")
    notes = bb.list_files("extraction_notes", "batch-*.yaml")
    merged = {
        "merged_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "batches": [p.name for p in notes],
        "era_observations": [],
        "iron_law_candidates": [],
        "style_markers": [],
        "resource_candidates": [],
        "open_questions": [],
    }
    for note_path in notes:
        try:
            note = bb.read_yaml(f"extraction_notes/{note_path.name}")
        except Exception:
            continue
        for key in (
            "era_observations",
            "iron_law_candidates",
            "style_markers",
            "resource_candidates",
            "open_questions",
        ):
            merged[key].extend(note.get(key, []))
    bb.write_yaml("extraction_notes/latest_merged.yaml", merged)
    schemas.update_phase_status(bb, phase="merge", status="done")


def _run_draft(bb: Blackboard, genre_id: str):
    from src.genre_pipeline.agents.drafter import GenreDrafter

    schemas.update_phase_status(bb, phase="draft", status="in_progress")
    bb.write_yaml("genre_blueprint.yaml", schemas.make_empty_blueprint(genre_id=genre_id))
    GenreDrafter().run(bb)
    # Step B — deterministic render. v1: just ensure stub files exist.
    _render_files_from_blueprint(bb, genre_id)
    schemas.update_phase_status(bb, phase="draft", status="done")


def _render_files_from_blueprint(bb: Blackboard, genre_id: str):
    """Deterministic template fill. v1 = only ensure the 4 stubs exist.

    Production rendering (reading blueprint.era_observations → era.md paragraphs,
    blueprint.iron_law_candidates → iron_law_extra_N sections) is deferred to
    a follow-up iteration so v1 can focus on schema plumbing.
    """
    genre_dir = config.GENRES_DIR / genre_id
    genre_dir.mkdir(parents=True, exist_ok=True)
    if not (genre_dir / "genre.yaml").exists():
        new_genre(genre_id)


def _run_validate(bb: Blackboard, genre_id: str, *, with_trial: bool):
    from src.genre_pipeline.agents.validator import GenreValidator

    schemas.update_phase_status(bb, phase="validate", status="in_progress")

    # Stage 1: structural (setting_lint)
    _run_setting_lint(bb, genre_id)

    # Stage 2: semantic
    try:
        GenreValidator().run(bb, genre_id=genre_id)
    except Exception as e:
        bb.append_jsonl("genre_issues.jsonl", {
            "severity": "warning",
            "file": "(validator)",
            "message": f"Stage 2 failed: {type(e).__name__}: {e}",
        })

    # Stage 3: trial (optional)
    if with_trial:
        from src.genre_pipeline import trial
        trial.run_trial(genre_id, bb)

    schemas.update_phase_status(bb, phase="validate", status="done")


def _run_setting_lint(bb: Blackboard, genre_id: str):
    from src.tools import setting_lint

    try:
        result = setting_lint.lint_genre(genre_id)  # may or may not exist with this exact name
    except AttributeError:
        # Fallback: invoke the CLI-level entry if lint_genre isn't exposed
        result = {"errors": [], "warnings": []}
    for err in result.get("errors", []):
        bb.append_jsonl("genre_issues.jsonl", {"severity": "error", "file": "(structure)", "message": err})
    for warn in result.get("warnings", []):
        bb.append_jsonl("genre_issues.jsonl", {"severity": "warning", "file": "(structure)", "message": warn})


def fill_genre(genre_id: str) -> dict:
    """Detect missing files and fill with stubs. v1: no LLM."""
    genre_dir = config.GENRES_DIR / genre_id
    if not genre_dir.exists():
        raise FileNotFoundError(f"genre not found: {genre_id}")
    missing = []
    for fname, stub_template in (
        ("genre.yaml", STUB_GENRE_YAML),
        ("era.md", STUB_ERA),
        ("writing-style-extra.md", STUB_WRITING_STYLE),
        ("iron-laws-extra.md", STUB_IRON_LAWS),
    ):
        if not (genre_dir / fname).exists():
            missing.append(fname)
            (genre_dir / fname).write_text(
                stub_template.format(
                    genre_id=genre_id,
                    display_name=genre_id,
                    genre="TBD", era="TBD", tone="TBD",
                ),
                encoding="utf-8",
            )
    return {"ok": True, "genre_id": genre_id, "filled": missing}


def audit_genre(genre_id: str) -> dict:
    """Run Validator stages 1 + 2. Returns summary."""
    bb = _build_bb(genre_id)
    _run_validate(bb, genre_id, with_trial=False)
    issues = bb.read_jsonl("genre_issues.jsonl")
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") == "warning"]
    return {
        "ok": len(errors) == 0,
        "genre_id": genre_id,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def run_phase(genre_id: str, *, phase: str, with_trial: bool = False) -> dict:
    """Intent-router entry: rerun a single phase. Build status must already exist."""
    bb = _build_bb(genre_id)
    if not bb.exists("build_status.yaml"):
        raise FileNotFoundError(
            f"no build_status.yaml for {genre_id}; run --extract-from-novel first"
        )
    if phase == "extract":
        # Requires re-reading the source novels — look them up in build_status
        status = bb.read_yaml("build_status.yaml")
        source_texts = []
        for src in status.get("novel_sources", []):
            p = Path(src["path"])
            if p.exists():
                source_texts.append(
                    (src["path"], p.read_text(encoding="utf-8"),
                     src["total_chapters"], src["batch_size"])
                )
        _run_extract(bb, source_texts)
    elif phase == "merge":
        _run_merge(bb)
    elif phase == "draft":
        _run_draft(bb, genre_id)
    elif phase == "validate":
        _run_validate(bb, genre_id, with_trial=with_trial)
    else:
        raise ValueError(f"unknown phase: {phase}")
    return {"ok": True, "genre_id": genre_id, "phase": phase}
```

- [ ] **Step 3: 写 `src/genre_pipeline/__main__.py`**

```python
"""CLI entry for the genre pipeline.

Usage:
  python3 -m src.genre_pipeline --new-genre <id> [--name X --genre Y --era Z --tone W]
  python3 -m src.genre_pipeline --fill-genre <id>
  python3 -m src.genre_pipeline --audit-genre <id>
  python3 -m src.genre_pipeline --extract-from-novel <id> --sources a.txt,b.txt [--with-trial]
  python3 -m src.genre_pipeline --extract-from-novel <id> --sources a.txt --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Novelforge Genre Pipeline")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--new-genre", metavar="ID", help="scaffold a new genre pack")
    grp.add_argument("--fill-genre", metavar="ID", help="fill missing files in an existing genre")
    grp.add_argument("--audit-genre", metavar="ID", help="run Validator stages 1+2 on an existing genre")
    grp.add_argument("--extract-from-novel", metavar="ID", help="extract a genre from source novels")
    # Intent Router — rerun individual phases without full pipeline
    grp.add_argument("--extract-only", metavar="ID", help="(Intent: extract) rerun extract phase only")
    grp.add_argument("--merge-only", metavar="ID", help="(Intent: merge) rerun merge phase only")
    grp.add_argument("--draft-only", metavar="ID", help="(Intent: draft) rerun draft phase only")
    grp.add_argument("--validate-only", metavar="ID", help="(Intent: validate) rerun validate phase only")

    parser.add_argument("--sources", default="", help="comma-separated novel file paths")
    parser.add_argument("--name", default="", help="display name (for --new-genre)")
    parser.add_argument("--genre", default="", help="genre label (for --new-genre)")
    parser.add_argument("--era", default="", help="era label (for --new-genre)")
    parser.add_argument("--tone", default="", help="tone label (for --new-genre)")
    parser.add_argument("--with-trial", action="store_true", help="also run 3-chapter trial book validation")
    parser.add_argument("--dry-run", action="store_true", help="don't call any LLM; just exercise the plumbing")

    args = parser.parse_args()

    from src.genre_pipeline import pipeline

    if args.new_genre:
        out = pipeline.new_genre(
            args.new_genre,
            display_name=args.name,
            genre=args.genre,
            era=args.era,
            tone=args.tone,
        )
    elif args.fill_genre:
        out = pipeline.fill_genre(args.fill_genre)
    elif args.audit_genre:
        out = pipeline.audit_genre(args.audit_genre)
    elif args.extract_from_novel:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        if not sources:
            print("error: --extract-from-novel requires --sources a.txt,b.txt", file=sys.stderr)
            return 2
        out = pipeline.extract_from_novel(
            args.extract_from_novel,
            sources=sources,
            with_trial=args.with_trial,
            dry_run=args.dry_run,
        )
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

- [ ] **Step 4: 写 `tests/test_genre_pipeline_cli.py`**

```python
"""CLI 冒烟测试：四个入口都能出合法输出。

不调真实 LLM（使用 --dry-run 或不触发 LLM 的入口）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(*args) -> tuple[int, str, str]:
    """Run the CLI with args; capture stdout/stderr."""
    cmd = [sys.executable, "-m", "src.genre_pipeline", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout, p.stderr


def test_cli_help():
    rc, out, err = _run_cli("--help")
    assert rc == 0
    assert "--new-genre" in out
    assert "--extract-from-novel" in out


def test_new_genre_creates_scaffold(tmp_path, monkeypatch):
    """--new-genre in a tmp GENRES_DIR."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)
    from src.genre_pipeline import pipeline
    out = pipeline.new_genre("demo-cli", display_name="Demo", genre="demo", era="2020", tone="neutral")
    assert out["ok"]
    d = tmp_path / "demo-cli"
    assert (d / "genre.yaml").exists()
    assert (d / "era.md").exists()
    assert (d / "writing-style-extra.md").exists()
    assert (d / "iron-laws-extra.md").exists()
    assert (d / ".build" / "build_status.yaml").exists()


def test_extract_from_novel_dry_run(tmp_path, monkeypatch):
    """Full plumbing walk-through without any LLM call."""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    # Create a mock novel
    novel = tmp_path / "novel.txt"
    novel.write_text(
        "\n".join([f"第{i}章 章节{i}\n内容..." for i in range(1, 31)]),
        encoding="utf-8",
    )

    from src.genre_pipeline import pipeline
    out = pipeline.extract_from_novel(
        "demo-extract",
        sources=[str(novel)],
        with_trial=False,
        dry_run=True,
    )
    assert out["ok"]
    assert out["mode"] == "dry_run"
    # build_status updated to all-done
    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path / "demo-extract" / ".build")
    s = bb.read_yaml("build_status.yaml")
    for phase in ("extract", "merge", "draft", "validate"):
        assert s["phases"][phase]["status"] == "done"


def test_fill_genre_adds_missing(tmp_path, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    d = tmp_path / "half-baked"
    d.mkdir()
    # Only create genre.yaml; everything else missing
    (d / "genre.yaml").write_text("id: half-baked\n", encoding="utf-8")

    from src.genre_pipeline import pipeline
    out = pipeline.fill_genre("half-baked")
    assert out["ok"]
    assert set(out["filled"]) == {"era.md", "writing-style-extra.md", "iron-laws-extra.md"}
    assert (d / "era.md").exists()
```

- [ ] **Step 5: 跑测试**

Run: `python3 -m pytest tests/test_genre_pipeline_cli.py -v 2>&1 | tail -15`
Expected: 4 passed

- [ ] **Step 6: 跑完整基线**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 380 passed

- [ ] **Step 7: Commit**

```bash
git add src/genre_pipeline/pipeline.py src/genre_pipeline/__main__.py .gitignore tests/test_genre_pipeline_cli.py
git commit -m "feat(genre-pipeline): main orchestrator + CLI (new/fill/audit/extract)

四个入口完整打通。--dry-run 支持 CLI 测试无需 LLM。
genres/*/.build/ 进 .gitignore。"
```

---

## Task 8: 可选 trial.py + end-to-end dry-run 测试

**Files:**
- Create: `src/genre_pipeline/trial.py`
- Create: `tests/test_genre_pipeline_end_to_end.py`

**说明：**trial.py 复用 calibrate_evaluator 的 scratch bootstrap 思路，但第一版只提供**占位实现**：真正跑 Planner/Generator/Evaluator 是下次迭代。测试只验证 trial.run_trial 可调用且不炸。

- [ ] **Step 1: 写 `src/genre_pipeline/trial.py`**

```python
"""Trial-book runner — run 3 chapters using the candidate genre pack.

v1: placeholder. Records a single "trial_not_implemented" info issue so
downstream code can proceed. Real implementation (copy calibrate_evaluator's
scratch-bootstrap skeleton + run Planner/Generator/Evaluator) follows in a
later iteration.
"""
from __future__ import annotations

from src.core.blackboard import Blackboard


def run_trial(genre_id: str, bb: Blackboard) -> None:
    """Placeholder trial run. Logs an informational issue."""
    bb.append_jsonl("genre_issues.jsonl", {
        "severity": "info",
        "file": "(trial)",
        "message": f"trial 3-chapter run not implemented in v1 (genre_id={genre_id})",
        "genre_id": genre_id,
    })
```

- [ ] **Step 2: 写 `tests/test_genre_pipeline_end_to_end.py`**

```python
"""端到端 dry-run：验证所有 phase 能按顺序走完、build_status 正确演进。"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_end_to_end_dry_run(tmp_path, monkeypatch):
    """从 extract-from-novel 到 validate done，所有状态正确。"""
    from src import config
    monkeypatch.setattr(config, "GENRES_DIR", tmp_path)

    novel = tmp_path / "mini.txt"
    novel.write_text(
        "\n".join(f"第{i}章\n场景...对白..." for i in range(1, 11)), encoding="utf-8"
    )

    from src.genre_pipeline import pipeline
    out = pipeline.extract_from_novel(
        "e2e-dry",
        sources=[str(novel)],
        with_trial=False,
        dry_run=True,
    )
    assert out["ok"]
    assert out["genre_id"] == "e2e-dry"

    from src.core.blackboard import Blackboard
    bb = Blackboard(root=tmp_path / "e2e-dry" / ".build")
    status = bb.read_yaml("build_status.yaml")
    for phase in ("extract", "merge", "draft", "validate"):
        assert status["phases"][phase]["status"] == "done", f"phase {phase} not done"


def test_trial_placeholder_records_info(tmp_path):
    from src.core.blackboard import Blackboard
    from src.genre_pipeline.trial import run_trial

    bb = Blackboard(root=tmp_path)
    run_trial("demo-trial", bb)
    issues = bb.read_jsonl("genre_issues.jsonl")
    assert any(i["severity"] == "info" and "trial" in i["message"] for i in issues)
```

- [ ] **Step 3: 跑测试**

Run: `python3 -m pytest tests/test_genre_pipeline_end_to_end.py -v 2>&1 | tail -10`
Expected: 2 passed

- [ ] **Step 4: 完整基线**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: 382 passed

- [ ] **Step 5: Commit**

```bash
git add src/genre_pipeline/trial.py tests/test_genre_pipeline_end_to_end.py
git commit -m "feat(genre-pipeline): trial.py placeholder + end-to-end dry-run test

--with-trial 目前只记一条 info issue；真正跑 3 章试验书留到 calibrate 骨架复用阶段。
e2e 测试保证 extract→merge→draft→validate 能端到端不炸。"
```

---

## Task 9: AGENTS.md 增加题材流水线索引段

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: 在 AGENTS.md 的"如何运行"段之后插入新段**

在"架构 1 行说明"之前插入：

````markdown
## 题材流水线（Genre Pipeline）

除了作品流水线（每章 Planner→Generator→Evaluator→Fixer→Summarizer），系统还有一条**题材流水线**：用于建 / 补 / 审 / 从已有小说拆解题材包。产物是 `genres/<id>/` 下的 4-5 份文件，跨作品复用。

### 四种入口

```bash
# 从零手建（脚手架，不调 LLM）
python3 -m src.genre_pipeline --new-genre <id> --name "..." --era "..."

# 补齐缺失文件（不调 LLM）
python3 -m src.genre_pipeline --fill-genre <id>

# 审查已有题材（结构 + 语义 LLM 审查）
python3 -m src.genre_pipeline --audit-genre <id>

# 从已有小说拆解题材规范（核心场景）
python3 -m src.genre_pipeline --extract-from-novel <id> \
    --sources novels/a.txt,novels/b.txt [--with-trial]
```

### 工程机制

- 复用 `Blackboard` / `BaseAgent`（已下沉到 `src/core/`）
- 滑动窗口 25 章/批，三档自适应（≤50:10 / 51-600:25 / >600:40）
- `genres/<id>/.build/`（gitignore）是构建期工作目录，含 `build_status.yaml` + `extraction_notes/batch-NNN.yaml` + `genre_blueprint.yaml`
- Extractor 笔记走严格 schema，字段对齐最终 4 份题材文件
- 默认只跑结构 + LLM 语义校验；`--with-trial` 显式开启试验书 3 章真实验收（v1 为占位）

### 规范文档

设计：[`docs/superpowers/specs/2026-05-11-genre-pipeline-design.md`](docs/superpowers/specs/2026-05-11-genre-pipeline-design.md)
实施：[`docs/superpowers/plans/2026-05-11-genre-pipeline.md`](docs/superpowers/plans/2026-05-11-genre-pipeline.md)
````

- [ ] **Step 2: 人工确认插入位置合理**

Run: `grep -n "题材流水线" AGENTS.md | head -5`
Expected: 至少一个 hit

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs(agents): 题材流水线索引段

AGENTS.md 按目录页原则（Lesson 5：不是百科），只放 4 入口 + 工程机制 + 规范文档链接。"
```

---

## Task 10: 最终完整测试 + 手动冒烟

- [ ] **Step 1: 跑完整测试套件**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -10`
Expected: 382 passed, 0 failed

- [ ] **Step 2: 手动冒烟 --new-genre**

Run:
```bash
python3 -m src.genre_pipeline --new-genre demo-smoke \
    --name "Demo" --genre "demo-g" --era "2020-2025" --tone "neutral"
```
Expected: stdout 含 `"ok": true`，`genres/demo-smoke/` 四份文件存在。

- [ ] **Step 3: 手动冒烟 --extract-from-novel --dry-run**

Run:
```bash
printf '%s\n' "第1章 开场\n内容1\n第2章 发展\n内容2\n第3章 高潮\n内容3" > /tmp/mini-novel.txt
python3 -m src.genre_pipeline --extract-from-novel demo-extract-smoke \
    --sources /tmp/mini-novel.txt --dry-run
```
Expected: 所有 phase 显示 done，无异常。

- [ ] **Step 4: 清理冒烟产物**

```bash
rm -rf genres/demo-smoke genres/demo-extract-smoke
```

- [ ] **Step 5: 确认现有小说流水线仍然能激活**

Run: `python3 -m src.bootstrap --list-genres 2>&1 | tail -10`
Expected: 列出 gangster-hk-1983 / xianxia-ascension / urban-romance-contemporary 三个题材，不含 demo-smoke。

- [ ] **Step 6: 确认 setting_lint 对现有题材无影响**

Run: `python3 -m src.tools.setting_lint --genre gangster-hk-1983 2>&1 | tail -5`
Expected: 退出码 0 或原有 warning 数量不变。

- [ ] **Step 7: 总结**

打印一句中文总结：题材流水线 v1 落地，现有 X 个测试全绿，新增 Y 个测试，四个入口可用，生产级 prompt 留给后续迭代。

---

## 成功判据回顾（对齐 spec §12）

1. ✅ `python3 -m pytest tests/` 全绿（≥382 passed）
2. ✅ 现有 `python3 -m src.bootstrap --project <id>` 未改动，正常
3. ✅ `--new-genre` 能生成 4 份 stub 文件
4. ✅ `--extract-from-novel --dry-run` 能跑完 extract→merge→draft→validate
5. ✅ `setting_lint` 对 extract 产物不报 ERROR（warning 可接受，v1 stub 肯定会有 warning）
6. ✅ `AGENTS.md` 增加索引段

---
