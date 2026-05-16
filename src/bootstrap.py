"""Single-layer bootstrap.

Each project owns its own genre files (era.md, writing-style-extra.md,
iron-laws-extra.md, optional resource_schema.yaml) directly under its project
directory. Bootstrap just copies that tree into projects/<id>/state/ and
synthesizes setting.yaml from project.yaml.

Presets (presets/<id>/) are **only** consumed by create_project(from_preset=...)
as a seed template. Runtime code never reads presets/.

CLI:
    python -m src.bootstrap --list                      # list all projects
    python -m src.bootstrap --list-presets              # list all presets
    python -m src.bootstrap --project <project-id>      # activate + seed
    python -m src.bootstrap --new-project <id> --preset <preset-id>
    python -m src.bootstrap --new-project <id> --blank-genre
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from . import config


# -----------------------------------------------------------------------------
# Schema constants
# -----------------------------------------------------------------------------

REQUIRED_PROJECT_FILES = (
    "project.yaml",
    "outline.json",
    "characters.yaml",
    "timeline.yaml",
    "era.md",
    "writing-style-extra.md",
    "iron-laws-extra.md",
)
OPTIONAL_PROJECT_FILES = (
    "resource_schema.yaml",
    # era_sensory_kit.yaml: 由 SensoryKitMiner 产出的按 location 五感清单，
    # Planner 读取它改善 sensory_prompts 质量。可选文件——不存在时 Planner
    # 行为退回到纯 LLM 外推（100% 向后兼容）。详见
    # docs/superpowers/specs/genre-mining-v2-step1-sensory-kit.md
    "era_sensory_kit.yaml",
    # dna_structured.yaml: NovelDNA Stage 2.5 产出的可查表 tips 库（按
    # chapter_type × scene_purpose 索引）。Planner/Generator 按当前章节的
    # 语境查表注入相关创作手法。可选——不存在时退回到"只读 4 份题材文件"
    # 的旧行为（100% 向后兼容）。
    "dna_structured.yaml",
    # plot_arc.yaml: 全书坐标系（Oracle P0+P1 修复）。Planner 读取它获得
    # "我在写哪一章 / 当前是哪个 act / 还剩多少 / 必须收束什么"的全局视角，
    # 避免退化为"局部贪心"原地循环。不存在时 Planner 行为不变（100% 向后兼容），
    # 但 bootstrap 会发出 warning 建议作者跑 init_plot_arc 生成模板。
    "plot_arc.yaml",
)


# Identifiers must be filesystem-safe and cannot be used for path traversal.
_VALID_ID_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,63}$")


def _validate_id(kind: str, value: str) -> None:
    if not isinstance(value, str) or not _VALID_ID_RE.match(value):
        raise ValueError(
            f"invalid {kind} id {value!r}: must match [a-z0-9_][a-z0-9_-]* "
            f"(1-64 chars, no path separators, no leading hyphen/dot)"
        )


def auto_generate_project_id(display_name: str, protagonist_name: str = "") -> str:
    """从书名（display_name）自动生成一个符合 _VALID_ID_RE 的作品 id。

    策略：
      1. 取 display_name 中所有 ASCII 字母数字连字符字符串 → 小写 + hyphen
      2. 若结果为空（全中文 / 特殊字符），用 protagonist_name 的 ASCII 字符兜底
      3. 仍为空 → 用 "book" 前缀 + 8 位 uuid
      4. 附加 8 位 uuid 后缀保证唯一（即使用户重名也不冲突）

    返回的 id 保证：
      - 符合 `_VALID_ID_RE`
      - 与当前 PROJECTS_DIR 下已存在的 id 不重复（用 uuid 后缀保证）
    """
    import uuid
    # Strip / lowercase ASCII-ish chars
    stem = re.sub(r"[^a-zA-Z0-9\s-]", "", display_name or "").strip().lower()
    stem = re.sub(r"\s+", "-", stem)  # 空格 → hyphen
    stem = re.sub(r"-+", "-", stem).strip("-")  # 合并多个 hyphen，去首尾
    if not stem:
        stem = re.sub(r"[^a-zA-Z0-9]", "", protagonist_name or "").lower()
    if not stem or not re.match(r"^[a-z0-9_]", stem):
        stem = "book"
    # 截短 + uuid 后缀保唯一
    stem = stem[:50]
    suffix = uuid.uuid4().hex[:8]
    candidate = f"{stem}-{suffix}"
    # 极端情况（stem 首字符非法）用 book- 前缀
    if not _VALID_ID_RE.match(candidate):
        candidate = f"book-{suffix}"
    return candidate


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

@dataclass
class BootstrapResult:
    project_id: str
    source_preset: Optional[str]
    state_dir: Path
    project_dir: Path
    copied_files: list[str] = field(default_factory=list)


def list_presets() -> list[str]:
    """Return sorted list of preset ids present under presets/."""
    if not config.PRESETS_DIR.exists():
        return []
    return sorted(
        p.name for p in config.PRESETS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def list_projects() -> list[str]:
    """Return sorted list of project ids that have a valid project.yaml."""
    if not config.PROJECTS_DIR.exists():
        return []
    return sorted(
        p.name for p in config.PROJECTS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".") and (p / "project.yaml").exists()
    )


def validate_project(project_dir: Path) -> list[str]:
    """Return missing required files. Empty list = valid."""
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
    """Activate a project and seed its state/ directory in-process."""
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
            f"Project '{project_id}' is incomplete. Missing files:\n  - "
            + "\n  - ".join(missing)
        )

    project_yaml = yaml.safe_load(
        (project_dir / "project.yaml").read_text(encoding="utf-8")
    )
    source_preset = project_yaml.get("source_preset")

    state_dir = project_dir / "state"
    state_dir.mkdir(exist_ok=True)
    for sub in ("chapters", "summaries", "fixes"):
        (state_dir / sub).mkdir(exist_ok=True)

    copied: list[str] = []

    # Copy required files (skip project.yaml — merged into setting.yaml)
    for fname in REQUIRED_PROJECT_FILES:
        if fname == "project.yaml":
            continue
        shutil.copy2(project_dir / fname, state_dir / fname)
        copied.append(fname)

    # Copy optional files (or purge stale copies from previous bootstraps)
    for fname in OPTIONAL_PROJECT_FILES:
        src = project_dir / fname
        dst = state_dir / fname
        if src.exists():
            shutil.copy2(src, dst)
            copied.append(fname)
        elif dst.exists():
            dst.unlink()

    # Plot-arc warning: 全书坐标系是 Oracle P0+P1 修复的核心，强烈建议配置。
    # 不存在时不阻断 bootstrap（100% 向后兼容），但打 warning 让作者注意。
    if not (project_dir / "plot_arc.yaml").exists():
        print(
            f"⚠ {project_id} 未配置 plot_arc.yaml — Planner 将无全书坐标系，"
            f"易退化为局部贪心。\n"
            f"  建议跑：python -m src.tools.init_plot_arc {project_id} 生成模板，"
            f"再编辑后重新 bootstrap。",
            file=sys.stderr,
        )

    # Synthesize setting.yaml from project.yaml + runtime fields
    merged = dict(project_yaml)
    merged["active_project"] = project_id
    bootstrapped_at = datetime.now().isoformat(timespec="seconds")
    merged["bootstrapped_at"] = bootstrapped_at
    _write_yaml(state_dir / "setting.yaml", merged)
    copied.append("setting.yaml (synthesized)")

    # Progress handling
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
    _write_json(progress_path, {
        **base,
        "active_project": project_id,
        "bootstrapped_at": bootstrapped_at,
    })

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
    protagonist_name: str = "",
    chapter_count_target: int = 50,
    from_preset: Optional[str] = None,
    blank_genre: bool = False,
    outline_synopsis: Optional[str] = None,
    blank_outline: bool = False,
    characters_brief: Optional[str] = None,
    blank_characters: bool = False,
    overwrite: bool = False,
    warnings_collector: Optional[list] = None,
) -> Path:
    """Scaffold a new project (book-centric single-layer).

    Genre starter flags are mutually exclusive (pick exactly one):
      - from_preset=<id>: copy 3-4 genre files verbatim from presets/<id>/
      - blank_genre=True: write TODO stubs

    Outline starter flags are mutually exclusive:
      - outline_synopsis=<str>: run OutlineDrafter to draft outline.json
      - blank_outline=True: write empty outline.json shell

    Characters starter flags are mutually exclusive:
      - characters_brief=<str>: run CharactersDrafter to draft characters.yaml
      - blank_characters=True: write empty characters.yaml shell

    Genre from-novel (fusion) is NOT a flag here anymore — submit
    `POST /api/jobs {kind:"from-novel", target:{type:"preset", id:...}}`
    to generate a preset first, then create a project from_preset=<that id>.
    """
    _validate_id("project", project_id)

    genre_choices = [bool(from_preset), bool(blank_genre)]
    if sum(genre_choices) != 1:
        raise ValueError(
            "Genre starter flags are mutually exclusive; pick exactly one of "
            "from_preset / blank_genre"
        )

    # --- Outline starter: 2-way mutex ---
    outline_choices = [bool(outline_synopsis), blank_outline]
    if sum(outline_choices) != 1:
        raise ValueError(
            "Outline starter flags are mutually exclusive; pick exactly one of "
            "outline_synopsis / blank_outline"
        )

    # --- Characters starter: 2-way mutex ---
    characters_choices = [bool(characters_brief), blank_characters]
    if sum(characters_choices) != 1:
        raise ValueError(
            "Characters starter flags are mutually exclusive; pick exactly one of "
            "characters_brief / blank_characters"
        )

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
        "source_preset": from_preset,
    })

    # Genre files
    if from_preset:
        preset_dir = config.PRESETS_DIR / from_preset
        if not preset_dir.exists():
            shutil.rmtree(project_dir)
            raise FileNotFoundError(f"preset not found: {from_preset}")
        for fname in ("era.md", "writing-style-extra.md", "iron-laws-extra.md"):
            src = preset_dir / fname
            if not src.exists():
                shutil.rmtree(project_dir)
                raise FileNotFoundError(
                    f"preset '{from_preset}' is missing required file: {fname}"
                )
            shutil.copy2(src, project_dir / fname)
        if (preset_dir / "resource_schema.yaml").exists():
            shutil.copy2(
                preset_dir / "resource_schema.yaml",
                project_dir / "resource_schema.yaml",
            )
        # Optional era_sensory_kit.yaml (Genre-mining v2 Step 1). Preset
        # authors may curate one; otherwise作品激活后可跑 SensoryKitMiner
        # 自动生成。Planner 不存在时走 LLM 外推（100% 向后兼容）。
        if (preset_dir / "era_sensory_kit.yaml").exists():
            shutil.copy2(
                preset_dir / "era_sensory_kit.yaml",
                project_dir / "era_sensory_kit.yaml",
            )
        # Optional dna_structured.yaml (NovelDNA Stage 2.5). 按 chapter_type ×
        # scene_purpose 索引的创作 tips 库。Planner/Generator 按当前章节的
        # 语境查表注入样本。不存在时两个 agent 都不读，行为退回到"只看 4 份
        # 题材文件"的旧模式。
        if (preset_dir / "dna_structured.yaml").exists():
            shutil.copy2(
                preset_dir / "dna_structured.yaml",
                project_dir / "dna_structured.yaml",
            )
    elif blank_genre:
        # Blank stubs so the project is structurally complete.
        (project_dir / "era.md").write_text(
            f"# Era for {display_name}\n\n(TODO: fill in the era pack.)\n",
            encoding="utf-8",
        )
        (project_dir / "writing-style-extra.md").write_text(
            "# Writing style\n\n(TODO.)\n",
            encoding="utf-8",
        )
        (project_dir / "iron-laws-extra.md").write_text(
            "# Iron laws\n\n(TODO.)\n",
            encoding="utf-8",
        )

    # outline.json — drafter or blank
    # drafter 失败（网络/LLM 格式）不阻断作品创建：落 blank 兜底 +
    # warnings_collector 里加一条，前端据此提示"去详情页重跑 drafter"。
    #
    # 注意：blank outline **不能**写 `chapters: []` —— Planner 按 `ch` 字段查
    # 找当前章节条目，找不到就抛 `ValueError("Chapter N not in outline")`，
    # 流水线直接崩在第 1 章。所以 blank 路径要预填 N 个空壳章节
    # （N = chapter_count_target），让 Planner 依赖 status_card +
    # pending_hooks + 前情摘要即兴写。
    if outline_synopsis:
        try:
            from src.agents.outline_drafter import OutlineDrafter
            outline_data = OutlineDrafter().run(
                synopsis=outline_synopsis,
                chapter_count_target=chapter_count_target,
                display_name=display_name,
            )
            _write_json(project_dir / "outline.json", outline_data)
        except Exception as e:  # noqa: BLE001
            _write_json(project_dir / "outline.json", {
                "title": display_name,
                "chapters": _blank_chapters(chapter_count_target),
            })
            if warnings_collector is not None:
                warnings_collector.append({
                    "field": "outline",
                    "reason": f"OutlineDrafter failed: {type(e).__name__}: {e}",
                    "retry_endpoint": f"/api/projects/{project_id}/draft-outline",
                    "synopsis": outline_synopsis,
                })
    else:
        _write_json(project_dir / "outline.json", {
            "title": display_name,
            "chapters": _blank_chapters(chapter_count_target),
        })

    # characters.yaml — drafter or blank（同样 drafter 失败不阻断）
    if characters_brief:
        try:
            from src.agents.characters_drafter import CharactersDrafter
            chars_data = CharactersDrafter().run(
                brief=characters_brief,
                protagonist_name=protagonist_name,
            )
            _write_yaml(project_dir / "characters.yaml", chars_data)
        except Exception as e:  # noqa: BLE001
            _write_yaml(project_dir / "characters.yaml", {
                "protagonist": {"name": protagonist_name or "主角", "description": ""},
                "supporting": [],
            })
            if warnings_collector is not None:
                warnings_collector.append({
                    "field": "characters",
                    "reason": f"CharactersDrafter failed: {type(e).__name__}: {e}",
                    "retry_endpoint": f"/api/projects/{project_id}/draft-characters",
                    "brief": characters_brief,
                })
    else:
        _write_yaml(project_dir / "characters.yaml", {
            "protagonist": {"name": protagonist_name or "主角", "description": ""},
            "supporting": [],
        })

    # timeline.yaml — blank
    _write_yaml(project_dir / "timeline.yaml", {"events": []})

    return project_dir


# -----------------------------------------------------------------------------
# Internals
# -----------------------------------------------------------------------------

def _blank_chapters(n: int) -> list[dict]:
    """Return N empty chapter shells for blank-outline projects.

    Planner 按 `ch` 字段定位当前章节；没有预填条目的话会抛
    ValueError("Chapter N not in outline")。这里给每章一个空 beats 的占位，
    让流水线能跑起来（Planner 依赖 status_card / pending_hooks / 摘要即兴写）。
    """
    if n <= 0:
        return []
    return [
        {"ch": i, "title": f"第 {i} 章", "beats": []}
        for i in range(1, n + 1)
    ]


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Novelforge bootstrap (book-centric single-layer)"
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--list", action="store_true",
                     help="List all known projects")
    grp.add_argument("--list-presets", action="store_true",
                     help="List all known presets under presets/")
    grp.add_argument("--project", metavar="PROJECT_ID",
                     help="Activate a project and seed its state/")
    grp.add_argument("--new-project", metavar="PROJECT_ID",
                     help="Create a new project scaffold")
    parser.add_argument("--preset", metavar="PRESET_ID",
                        help="(with --new-project) seed genre files from this preset")
    parser.add_argument("--blank-genre", action="store_true",
                        help="(with --new-project) scaffold TODO stubs for genre files")
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--protagonist", default="TBD")
    parser.add_argument("--chapters", type=int, default=50)
    parser.add_argument("--overwrite", action="store_true",
                        help="With --new-project, overwrite if dir exists")
    args = parser.parse_args()

    if args.list_presets:
        presets = list_presets()
        if not presets:
            print("(no presets found under presets/)")
        else:
            for pid in presets:
                print(f"  {pid}")
        return

    if args.list:
        projects = list_projects()
        if not projects:
            print("(no projects found under projects/)")
        else:
            for p in projects:
                proj_yaml = yaml.safe_load(
                    (config.PROJECTS_DIR / p / "project.yaml").read_text(encoding="utf-8")
                )
                preset = proj_yaml.get("source_preset") or "(none)"
                name = proj_yaml.get("display_name", p)
                print(f"  {p:40s}  preset={preset:30s}  {name}")
        return

    if args.new_project:
        if not (args.preset or args.blank_genre):
            parser.error("--new-project requires --preset <id> OR --blank-genre")
        if args.preset and args.blank_genre:
            parser.error("--preset and --blank-genre are mutually exclusive")
        try:
            project_dir = create_project(
                args.new_project,
                display_name=args.display_name or args.new_project,
                protagonist_name=args.protagonist,
                chapter_count_target=args.chapters,
                from_preset=args.preset if not args.blank_genre else None,
                blank_genre=args.blank_genre,
                blank_outline=True,
                blank_characters=True,
                overwrite=args.overwrite,
            )
        except (FileNotFoundError, FileExistsError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)
        print(f"✓ Created project scaffold at {project_dir}")
        print(f"  Edit project.yaml / outline.json / characters.yaml / timeline.yaml")
        print(f"  Then: python -m src.bootstrap --project {args.new_project}")
        return

    if args.project:
        try:
            result = bootstrap_project(args.project)
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)
        print(f"Seeding state/ for project '{result.project_id}'"
              + (f"  (source_preset: {result.source_preset})" if result.source_preset else ""))
        print(f"  project dir : {result.project_dir}")
        print(f"  state dir   : {result.state_dir}")
        for fname in result.copied_files:
            size_hint = ""
            p = result.state_dir / fname.split(" ")[0]
            if p.exists() and p.is_file():
                size_hint = f"  ({p.stat().st_size} B)"
            print(f"  ✓ {fname}{size_hint}")
        print(f"\n✓ Active project: {result.project_id}")
        print(f"  Next: python -m src.pipeline --chapter 1")
        return


if __name__ == "__main__":
    main()
