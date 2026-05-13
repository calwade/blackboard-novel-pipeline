"""Create a preset from a free-text description (single LLM call).

Unlike to_preset.extract_to_preset which reads novels, this path takes a
natural-language description and asks the LLM to synthesize the whole blueprint
in one shot. Useful when the user knows what they want but has no source
material to scan.

Output shape matches the other preset creation paths — 3 required md files,
optional resource_schema.yaml (LLM decides based on description content).
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

import yaml

from src import config, llm


def _render_files_from_blueprint(blueprint: dict, *, out_dir: Path) -> list[Path]:
    """Write era.md / writing-style-extra.md / iron-laws-extra.md +
    optionally resource_schema.yaml to ``out_dir``.

    Moved inline from the deleted src/genre_extractor/core.py (2026-05-14).
    Only from_description consumes this, so it lives next to its caller.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    mapping = {
        "era": "era.md",
        "writing_style_extra": "writing-style-extra.md",
        "iron_laws_extra": "iron-laws-extra.md",
    }
    for key, fname in mapping.items():
        node = blueprint.get(key) or {}
        content = node.get("content", "") if isinstance(node, dict) else ""
        path = out_dir / fname
        path.write_text(content, encoding="utf-8")
        written.append(path)
    schema = blueprint.get("resource_schema")
    schema_path = out_dir / "resource_schema.yaml"
    if schema:
        schema_path.write_text(
            yaml.safe_dump(schema, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written.append(schema_path)
    elif schema_path.exists():
        schema_path.unlink()
    return written

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
你是资深中文小说责编，擅长把一段题材需求描述转成完整的题材规范。

用户会给你：
- 一段自由文本描述（时代 / 地域 / 基调 / 禁忌 / 风格 / 可能的可追踪资源）

你要输出**严格的 YAML**（不要 markdown 代码块，不要注释），schema：

```
era: |
  # Era
  <时代/世界观事实包，markdown，≥ 400 字>

writing_style_extra: |
  # Writing Style
  <题材特有写作风格，markdown，≥ 200 字>

iron_laws_extra: |
  # Iron Laws
  <题材特有铁律列表，markdown，≥ 5 条>

resource_schema: null
# 或者，如果描述里提到了可追踪资源（灵石/金币/情报值/因果值 等），输出：
# resource_schema:
#   resources:
#     - name: spirit_stone
#       unit: 颗
#       visibility: public    # public / private
#     - ...
```

规则：
1. 三段 markdown 内容必须完整、具体、可落地。不要只写一句"TODO"。
2. 默认 resource_schema 为 null。只有用户描述里**明确提到**可追踪资源量时才填 schema。
3. 只输出 YAML。不要代码块。不要额外说明。
"""


def _parse_llm_output(raw: str) -> dict:
    """Parse LLM output into blueprint dict. Raise ValueError on bad output."""
    if not raw or not raw.strip():
        raise ValueError("LLM output is empty")
    # Strip accidental markdown fences
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        _, _, text = text.partition("\n")
        text = text.rpartition("```")[0] if "```" in text else text
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"LLM output is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"LLM output is not a dict (got {type(data).__name__})")
    for key in ("era", "writing_style_extra", "iron_laws_extra"):
        if key not in data or not data[key]:
            raise ValueError(f"LLM output missing required field: {key}")
    return data


def _blueprint_from_parsed(parsed: dict) -> dict:
    """Shape parsed LLM dict into the format render_files_from_blueprint expects."""
    return {
        "era": {"content": str(parsed["era"]).strip() + "\n"},
        "writing_style_extra": {"content": str(parsed["writing_style_extra"]).strip() + "\n"},
        "iron_laws_extra": {"content": str(parsed["iron_laws_extra"]).strip() + "\n"},
        "resource_schema": parsed.get("resource_schema") or None,
    }


def extract_from_description(
    preset_id: str,
    *,
    display_name: str,
    tone: str,
    description: str,
    cancel=None,
    on_progress=None,
) -> dict:
    """Generate a preset from a free-text description via a single LLM call.

    ``cancel`` / ``on_progress`` are optional job-plumbing hooks. Since this
    path is a single LLM call it can only honor cancel before the call
    (mid-call cancel is not safe without streaming, which we don't use here).

    Raises:
        ValueError: invalid id / empty description / bad LLM output.
        FileExistsError: preset already exists.
    """
    from src.genre_extractor.progress import null_progress
    from src.jobs.cancel import NullCancelToken

    cancel = cancel or NullCancelToken()
    on_progress = on_progress or null_progress

    if not re.match(r"^[a-z0-9][a-z0-9-]*$", preset_id):
        raise ValueError(f"invalid preset id: {preset_id!r}")
    if not description or not description.strip():
        raise ValueError("description must not be empty")

    preset_dir = config.PRESETS_DIR / preset_id
    if preset_dir.exists():
        raise FileExistsError(f"Preset already exists: {preset_id}")

    # Phase: treat description→preset as a single "draft" phase. extract
    # and merge don't apply (no novel sources), validate runs at the end.
    cancel.check()
    on_progress(phase="draft", phase_index=3, progress_text="drafting from description")

    # Call LLM
    user_prompt = (
        f"题材 id: {preset_id}\n"
        f"显示名: {display_name or preset_id}\n"
        f"基调: {tone or '(未指定)'}\n\n"
        f"题材描述：\n{description}\n"
    )
    raw = llm.chat(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        agent_name="preset_from_description",
        temperature=0.4,
        max_tokens=4000,
        response_format="text",
    )

    cancel.check()
    on_progress(phase="validate", phase_index=4, progress_text="parsing & rendering")

    # Parse. If bad, abort cleanly — don't leave a half-built preset.
    try:
        parsed = _parse_llm_output(raw)
    except ValueError:
        raise

    # Write files
    preset_dir.mkdir(parents=True)
    try:
        (preset_dir / "novels").mkdir()
        (preset_dir / "novels" / ".gitkeep").write_text("", encoding="utf-8")

        (preset_dir / "genre.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": preset_id,
                    "display_name": display_name or preset_id,
                    "tone": tone or "",
                    "source": "description",
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        blueprint = _blueprint_from_parsed(parsed)
        _render_files_from_blueprint(blueprint, out_dir=preset_dir)
    except Exception:
        # Clean up on any write failure
        if preset_dir.exists():
            shutil.rmtree(preset_dir)
        raise

    on_progress(phase="validate", phase_index=4, progress_text="done")
    return {
        "preset_id": preset_id,
        "source": "description",
        "has_resource_schema": bool(blueprint.get("resource_schema")),
    }
