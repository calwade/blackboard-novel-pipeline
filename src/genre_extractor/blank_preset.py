"""Create a blank preset — scaffolding only, no LLM.

Writes 4 files with TODO placeholders. User fills them in manually.
No novels/ content (empty dir with .gitkeep). No resource_schema.yaml
(user adds if needed).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from src import config


_STUB_ERA = """# Era (TODO)

在此描述这个题材的时代背景、地理范围、社会结构、关键真实事件等。

Novelforge 会把这份文件当作"世界观事实包"注入给 Generator 和 Evaluator。
写得越具体越好，例如：
- 时间跨度
- 城市 / 场景
- 政治格局
- 关键历史节点
- 日常细节（食物、交通、货币……）
"""

_STUB_WRITING_STYLE = """# Writing Style Extra (TODO)

在此描述这个题材**特有**的写作风格。通用风格已在 rules/writing-style-core.md。

常见补充点：
- 方言/口音（粤语俚语、北方话、吴语……）
- 叙述节奏（冷硬快切、抒情慢铺、对白驱动……）
- 场景密度
- 禁止风格（如"禁止使用古典仙侠八股"）
"""

_STUB_IRON_LAWS = """# Iron Laws Extra (TODO)

在此描述这个题材**不可违反**的铁律。Evaluator 会把这些作为硬检查项。

常见举例：
- 不可写超出时代的科技（如 1983 港综不能出现智能手机）
- 不可颠倒真实历史结果
- 主角不能犯特定低级错误
- 等等
"""


def create_blank_preset(
    preset_id: str,
    *,
    display_name: str,
    tone: str,
    cancel=None,
    on_progress=None,
) -> Path:
    """Create `presets/<preset_id>/` with stub files.

    ``cancel`` / ``on_progress`` are optional job-plumbing hooks kept to
    match the signatures of the other preset-creation entry points; this
    path is synchronous and non-LLM so they mostly fire the "done" event.

    Raises:
        ValueError: preset_id is invalid (empty / wrong format).
        FileExistsError: preset already exists.
    """
    from src.genre_extractor.progress import null_progress
    from src.jobs.cancel import NullCancelToken

    cancel = cancel or NullCancelToken()
    on_progress = on_progress or null_progress

    cancel.check()
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", preset_id):
        raise ValueError(f"invalid preset id: {preset_id!r}")

    preset_dir = config.PRESETS_DIR / preset_id
    if preset_dir.exists():
        raise FileExistsError(f"Preset already exists: {preset_id}")

    preset_dir.mkdir(parents=True)
    (preset_dir / "novels").mkdir()
    (preset_dir / "novels" / ".gitkeep").write_text("", encoding="utf-8")

    (preset_dir / "genre.yaml").write_text(
        yaml.safe_dump(
            {
                "id": preset_id,
                "display_name": display_name or preset_id,
                "tone": tone or "",
                "source": "blank",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (preset_dir / "era.md").write_text(_STUB_ERA, encoding="utf-8")
    (preset_dir / "writing-style-extra.md").write_text(_STUB_WRITING_STYLE, encoding="utf-8")
    (preset_dir / "iron-laws-extra.md").write_text(_STUB_IRON_LAWS, encoding="utf-8")

    on_progress(phase="validate", phase_index=4, progress_text="done")
    return preset_dir
