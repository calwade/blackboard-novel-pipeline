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


def _ensure_dna_structured_schema(dna: dict) -> dict:
    """Fill missing default fields so from_description's dna_structured.yaml
    has the same shape as NovelDNA Stage 2.5 output.

    Mirrors src.genre_extractor.miners.novel_dna._structure_dna_tips
    post-process — without it Planner/Generator查表会缺 key。
    """
    if not isinstance(dna, dict):
        return {}
    dna.setdefault("schema_version", 1)
    dna.setdefault("tips_by_chapter_type", {})
    dna.setdefault("tips_by_scene_purpose", {})
    dna.setdefault("hook_recipes", {"opening_hooks": [], "closing_hooks": []})
    dna.setdefault("universal", {})
    dna.setdefault(
        "plot_unit_structure",
        {"unit_size": 5, "pattern": [], "pacing": {}},
    )
    dna.setdefault("payoff_recipes", {})
    dna.setdefault("villain_defeat_patterns", [])
    dna.setdefault(
        "volume_transition_techniques",
        {
            "scaling_method": "",
            "arc_closer_template": "",
            "next_arc_opener_template": "",
        },
    )
    if isinstance(dna["tips_by_chapter_type"], dict):
        for k in ("战斗", "布局", "过渡", "回收"):
            dna["tips_by_chapter_type"].setdefault(k, [])
    if isinstance(dna["tips_by_scene_purpose"], dict):
        for k in ("推进主线", "塑造人物", "埋伏笔"):
            dna["tips_by_scene_purpose"].setdefault(k, [])
    if isinstance(dna["payoff_recipes"], dict):
        for k in ("爽感", "掌控感", "黑色幽默", "生存智慧"):
            dna["payoff_recipes"].setdefault(
                k,
                {"formula": "", "dialog_template": [], "sample_50_chars": ""},
            )
    return dna


def _render_files_from_blueprint(blueprint: dict, *, out_dir: Path) -> list[Path]:
    """Write era.md / writing-style-extra.md / iron-laws-extra.md +
    optionally resource_schema.yaml + dna_structured.yaml to ``out_dir``.

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

    # P2: 写 dna_structured.yaml（与 NovelDNA Stage 2.5 同 schema）
    dna = blueprint.get("dna_structured")
    dna_path = out_dir / "dna_structured.yaml"
    if isinstance(dna, dict) and dna:
        dna_full = _ensure_dna_structured_schema(dict(dna))
        # 加文件头注释（只在 from_description 路径上，提示作者这是 LLM 推测）
        header = (
            "# AUTO-GENERATED from sparse description, refine if needed.\n"
            "# Source path: from_description (single LLM call, no source novels).\n"
            "# Schema matches NovelDNA Stage 2.5 output for downstream compatibility.\n"
        )
        dna_path.write_text(
            header + yaml.safe_dump(dna_full, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written.append(dna_path)
    elif dna_path.exists():
        dna_path.unlink()
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

dna_structured:
  schema_version: 1
  # 4 老桶
  tips_by_chapter_type:
    战斗:    [<3-5 条具体动作指令>]
    布局:    [<3-5 条>]
    过渡:    [<3-5 条>]
    回收:    [<3-5 条>]
  tips_by_scene_purpose:
    推进主线: [<3-5 条>]
    塑造人物: [<3-5 条>]
    埋伏笔:   [<3-5 条>]
  hook_recipes:
    opening_hooks:
      - {pattern: <款式名>, sample: <样板句式>, applies_to: [<chapter_type 列表>]}
    closing_hooks:
      - {pattern: <款式名>, sample: <样板句式>, applies_to: [<chapter_type 列表>]}
  universal:
    writing_style:      [<3-5 条>]
    value_anchors:      [<2-4 条>]
    character_handling: [<2-4 条>]
  # 4 新桶（P0 修复 dna 知识在长链中被过滤）
  plot_unit_structure:
    unit_size: 5
    pattern:
      - {phase: 起, chapters: 1,    typical_action: <1 句>}
      - {phase: 承, chapters: "1-2", typical_action: <1 句>}
      - {phase: 转, chapters: 1,    typical_action: <1 句>}
      - {phase: 合, chapters: 1,    typical_action: <1 句>}
    pacing:
      small_payoff_every: "2-3 章"
      big_payoff_every:   "5 章"
  payoff_recipes:
    爽感:
      formula: <完整工艺链描述>
      dialog_template:
        - {speaker: villain,      beats: [<1-3 条短指令>]}
        - {speaker: protagonist,  beats: [<1-3 条短指令>]}
        - {speaker: bystander,    beats: [<1-3 条短指令>]}
      sample_50_chars: <50-100 字典型对白>
    掌控感:    {formula, dialog_template, sample_50_chars}
    黑色幽默:  {formula, dialog_template, sample_50_chars}
    生存智慧:  {formula, dialog_template, sample_50_chars}
  villain_defeat_patterns:
    - {pattern: 信息差打脸, setup: <1 句>, twist: <1 句>, payoff_line_template: <1 句>}
    - {pattern: 实力差秒杀, setup: <1 句>, twist: <1 句>, payoff_line_template: <1 句>}
    - {pattern: 心理战崩溃, setup: <1 句>, twist: <1 句>, payoff_line_template: <1 句>}
    # 至少 3 项
  volume_transition_techniques:
    scaling_method:           <每卷如何升级>
    arc_closer_template:      <本卷大反派被解决 + 暗示更高层势力>
    next_arc_opener_template: <新卷如何拉开>
```

规则：
1. 三段 markdown 内容必须完整、具体、可落地。不要只写一句"TODO"。
2. 默认 resource_schema 为 null。只有用户描述里**明确提到**可追踪资源量时才填 schema。
3. **dna_structured 必须输出全部 8 个顶层字段**（4 老 + 4 新）；本路径不读源小说，
   是基于用户描述合理推测出可用配方。具体填法：
   - 用户描述里**明确指向某种网文类型**（如末世/修仙/都市奇幻）→ 按该类型典型套路填充；
   - 信息不足 → 按"通用都市爽文"的保守默认填充，不要留空字段；
   - payoff_recipes 必须给齐 4 个 anchor（爽感/掌控感/黑色幽默/生存智慧），即便是
     "通用模板"也要给完整的 formula + dialog_template + sample_50_chars 三段；
   - villain_defeat_patterns 必须 ≥3 种；
   - 注意：本路径产出的 dna 配方质量不如 NovelDNA 路径（无源小说原料），
     但 schema 必须与 NovelDNA 路径一致，下游 Planner / Generator 才能复用。
4. 只输出 YAML。不要代码块。不要额外说明。
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
        # P2: dna_structured 是可选字段（旧版 LLM 可能不输出），渲染层若为 None
        # 会跳过写盘。下游 Planner / Generator 不存在时也是优雅降级。
        "dna_structured": parsed.get("dna_structured") or None,
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
