"""Bootstrap — seed a project's state/ dir from its genre + project pack.

Layering (refactored 2026-05-11):
  genres/<genre-id>/         — shared genre definition:
                                 genre.yaml
                                 era.md
                                 writing-style-extra.md
                                 iron-laws-extra.md
                                 [resource_schema.yaml]  (optional)
  projects/<project-id>/     — one novel:
                                 project.yaml              (declares genre + protagonist + targets)
                                 outline.json
                                 characters.yaml
                                 timeline.yaml
                                 state/                    (runtime artifacts)
  projects/.active           — pointer file, single line with active project id

Run:
    python -m src.bootstrap --list                      # list all projects
    python -m src.bootstrap --list-genres               # list all genres
    python -m src.bootstrap --project <project-id>      # activate + seed
    python -m src.bootstrap --new-project <id> --genre <genre-id>
                                                         # create a new project
                                                         # based on a genre

What bootstrap does for --project:
  1. Verify projects/<id>/ exists and its project.yaml references a valid genre
  2. Copy genre-layer files (era/writing-style/iron-laws/resource_schema)
     from genres/<genre>/ into projects/<id>/state/
  3. Copy project-layer files (outline/characters/timeline) from
     projects/<id>/ into projects/<id>/state/
  4. Merge genre.yaml + project.yaml into a runtime setting.yaml for agents
  5. Reset progress.json
  6. Touch empty jsonl accumulators if missing
  7. Write projects/.active so other tools know which project is live
  8. Refresh src.config.STATE_DIR to point at projects/<id>/state/

Agents consume state/ exclusively; the layering above is invisible to them.
This preserves backward compatibility with all existing Agent code.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from . import config
from .blackboard import Blackboard


# -----------------------------------------------------------------------------
# Schema constants
# -----------------------------------------------------------------------------

# Files that MUST exist in every genre pack.
GENRE_REQUIRED_FILES = [
    "genre.yaml",
    "era.md",
    "writing-style-extra.md",
    "iron-laws-extra.md",
]

# Optional genre files (copied to state/ only if present).
GENRE_OPTIONAL_FILES = [
    "resource_schema.yaml",
]

# Files that MUST exist in every project pack.
PROJECT_REQUIRED_FILES = [
    "project.yaml",
    "outline.json",
    "characters.yaml",
    "timeline.yaml",
]


# Identifiers must be filesystem-safe and cannot be used for path traversal.
# Lowercase letters, digits, underscore, hyphen; length 1-64; cannot start with
# hyphen or dot. Matches the conventions used by the built-in genres/projects.
import re as _re
_VALID_ID_RE = _re.compile(r"^[a-z0-9_][a-z0-9_-]{0,63}$")


def _validate_id(kind: str, value: str) -> None:
    """Reject ids that could escape the genres/ or projects/ sandbox.

    Called from the public API surfaces (bootstrap_project, create_project) so
    both the CLI and Web routes are protected. Raises ValueError with a clear
    message; callers map it to HTTP 400 / CLI error.
    """
    if not isinstance(value, str) or not _VALID_ID_RE.match(value):
        raise ValueError(
            f"invalid {kind} id {value!r}: must match [a-z0-9_][a-z0-9_-]* "
            f"(1-64 chars, no path separators, no leading hyphen/dot)"
        )


# -----------------------------------------------------------------------------
# Public API — used by Web UI / CLI / tests
# -----------------------------------------------------------------------------

@dataclass
class BootstrapResult:
    project_id: str
    genre_id: str
    state_dir: Path
    genre_dir: Path
    project_dir: Path
    copied_files: list[str]


def list_genres() -> list[str]:
    """Return sorted list of genre ids that have a valid genre.yaml."""
    if not config.GENRES_DIR.exists():
        return []
    return sorted(
        p.name
        for p in config.GENRES_DIR.iterdir()
        if p.is_dir() and (p / "genre.yaml").exists()
    )


def list_projects() -> list[str]:
    """Return sorted list of project ids that have a valid project.yaml."""
    if not config.PROJECTS_DIR.exists():
        return []
    return sorted(
        p.name
        for p in config.PROJECTS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".") and (p / "project.yaml").exists()
    )


def validate_genre(genre_dir: Path) -> list[str]:
    """Return missing required files. Empty list = valid."""
    return [f for f in GENRE_REQUIRED_FILES if not (genre_dir / f).exists()]


def validate_project(project_dir: Path) -> list[str]:
    """Return missing required files. Empty list = valid."""
    return [f for f in PROJECT_REQUIRED_FILES if not (project_dir / f).exists()]


def empty_progress() -> dict:
    return {
        "current_chapter": 0,
        "completed_chapters": [],
        "in_flight": None,
        "last_update": None,
        "total_llm_calls": 0,
    }


def bootstrap_project(project_id: str, *, preserve_progress: bool = False) -> BootstrapResult:
    """Activate a project and seed its state/ directory in-process.

    This is the pure function that both the CLI and Web API call. It does
    NOT print; it returns a result object. Callers that want progress lines
    should wrap it.

    Raises FileNotFoundError / ValueError for validation problems.
    """
    _validate_id("project", project_id)
    project_dir = config.PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise FileNotFoundError(
            f"Project not found: {project_dir}. "
            f"Known projects: {', '.join(list_projects()) or '(none)'}"
        )

    missing_proj = validate_project(project_dir)
    if missing_proj:
        raise ValueError(
            f"Project '{project_id}' is incomplete. Missing files:\n  - "
            + "\n  - ".join(missing_proj)
        )

    project_yaml = yaml.safe_load((project_dir / "project.yaml").read_text(encoding="utf-8"))
    genre_id = project_yaml.get("genre")
    if not genre_id:
        raise ValueError(f"Project '{project_id}'s project.yaml is missing 'genre' field")

    genre_dir = config.GENRES_DIR / genre_id
    if not genre_dir.exists():
        raise FileNotFoundError(
            f"Genre not found for project '{project_id}': {genre_dir}. "
            f"Known genres: {', '.join(list_genres()) or '(none)'}"
        )
    missing_genre = validate_genre(genre_dir)
    if missing_genre:
        raise ValueError(
            f"Genre '{genre_id}' (referenced by project '{project_id}') "
            f"is incomplete. Missing files:\n  - "
            + "\n  - ".join(missing_genre)
        )

    # Prepare destination
    state_dir = project_dir / "state"
    state_dir.mkdir(exist_ok=True)
    for sub in ("chapters", "summaries", "fixes"):
        (state_dir / sub).mkdir(exist_ok=True)

    copied: list[str] = []

    # 1. Copy genre-layer files
    for fname in GENRE_REQUIRED_FILES:
        if fname == "genre.yaml":
            continue  # genre.yaml is merged into setting.yaml below
        shutil.copy2(genre_dir / fname, state_dir / fname)
        copied.append(fname)
    for fname in GENRE_OPTIONAL_FILES:
        src = genre_dir / fname
        dst = state_dir / fname
        if src.exists():
            shutil.copy2(src, dst)
            copied.append(fname)
        elif dst.exists():
            # Purge stale file left over from a previous genre
            dst.unlink()

    # 2. Copy project-layer files
    for fname in PROJECT_REQUIRED_FILES:
        if fname == "project.yaml":
            continue  # merged into setting.yaml below
        shutil.copy2(project_dir / fname, state_dir / fname)
        copied.append(fname)

    # 3. Merge genre.yaml + project.yaml into a runtime setting.yaml
    genre_yaml = yaml.safe_load((genre_dir / "genre.yaml").read_text(encoding="utf-8"))
    merged = _merge_setting_metadata(genre_yaml, project_yaml)
    _write_yaml(state_dir / "setting.yaml", merged)
    copied.append("setting.yaml (synthesized)")

    # 4. Reset or preserve progress, touch accumulators
    existing_progress = {}
    progress_path = state_dir / "progress.json"
    if preserve_progress and progress_path.exists():
        try:
            existing_progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_progress = {}
    base = empty_progress() if not preserve_progress else {
        "current_chapter": existing_progress.get("current_chapter", 0),
        "completed_chapters": existing_progress.get("completed_chapters", []),
        "in_flight": existing_progress.get("in_flight"),
        "last_update": existing_progress.get("last_update"),
        "total_llm_calls": existing_progress.get("total_llm_calls", 0),
    }
    _write_json(progress_path, {
        **base,
        "active_project": project_id,
        "active_genre": genre_id,
        "bootstrapped_at": datetime.now().isoformat(timespec="seconds"),
    })
    for f in ("issues.jsonl", "debt.jsonl"):
        p = state_dir / f
        if not p.exists():
            p.touch()

    # 5. Activate
    config.set_active_project_id(project_id)
    config.refresh_state_dir()

    return BootstrapResult(
        project_id=project_id,
        genre_id=genre_id,
        state_dir=state_dir,
        genre_dir=genre_dir,
        project_dir=project_dir,
        copied_files=copied,
    )


def create_project(project_id: str, genre_id: str, *, overwrite: bool = False) -> Path:
    """Scaffold a new project based on a genre.

    Copies genre.yaml + the genre's outline/characters/timeline templates if
    the genre packs them as starter files. Otherwise creates minimal stubs.

    Returns the new project dir.
    """
    _validate_id("project", project_id)
    _validate_id("genre", genre_id)
    genre_dir = config.GENRES_DIR / genre_id
    if not genre_dir.exists():
        raise FileNotFoundError(
            f"Genre not found: {genre_id}. Known: {', '.join(list_genres())}"
        )

    project_dir = config.PROJECTS_DIR / project_id
    if project_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Project already exists: {project_dir}")
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True)

    # Seed project.yaml from genre.yaml
    genre_yaml = yaml.safe_load((genre_dir / "genre.yaml").read_text(encoding="utf-8"))
    project_yaml = {
        "id": project_id,
        "display_name": f"{genre_yaml.get('display_name', genre_id)} · new project",
        "genre": genre_id,
        "protagonist_name": "TBD",
        "protagonist_hook": "TBD",
        "opening_year_month": "TBD",
        "chapter_count_target": genre_yaml.get("chapter_count_target", 800),
        "chapters_in_outline": 3,
        "author_persona_overrides": [],
        "extra_prohibited_styles": [],
    }
    _write_yaml(project_dir / "project.yaml", project_yaml)

    # Minimal stubs for required project files
    _write_json(project_dir / "outline.json", {
        "title": project_yaml["display_name"],
        "protagonist": "TBD",
        "chapter_count_target": project_yaml["chapter_count_target"],
        "chapters_in_outline": 3,
        "chapters": [
            {"ch": i, "title": f"第{i}章 (stub)", "key_characters": [], "beats": []}
            for i in (1, 2, 3)
        ],
    })
    _write_yaml(project_dir / "characters.yaml", {
        "protagonist": {"name": "TBD", "age": 30, "traits": [], "redlines": [], "motivation": ""},
        "supporting": [],
    })
    _write_yaml(project_dir / "timeline.yaml", {"2024": []})

    return project_dir


# -----------------------------------------------------------------------------
# Internals
# -----------------------------------------------------------------------------

def _merge_setting_metadata(genre_yaml: dict, project_yaml: dict) -> dict:
    """Compose state/setting.yaml from genre + project metadata.

    Agents currently read fields like `setting.yaml.genre`, `setting.yaml.era`,
    `setting.yaml.protagonist_name`, `setting.yaml.prohibited_styles` — all
    lumped in one file. We preserve that shape for backward compatibility.
    """
    merged: dict[str, Any] = {
        # Identity (project wins on id; genre provides display_name hints)
        "id": project_yaml.get("id"),
        "display_name": project_yaml.get("display_name") or genre_yaml.get("display_name"),
        "subtitle": project_yaml.get("subtitle") or genre_yaml.get("subtitle"),
        "locale": genre_yaml.get("locale", "zh-Hans"),

        # Genre-layer metadata (shared)
        "genre": genre_yaml.get("genre"),
        "era": genre_yaml.get("era"),
        "tone": genre_yaml.get("tone"),
        "genre_id": genre_yaml.get("id"),

        # Project-layer narrative anchors
        "protagonist_name": project_yaml.get("protagonist_name"),
        "protagonist_hook": project_yaml.get("protagonist_hook"),
        "opening_year_month": project_yaml.get("opening_year_month"),
        "chapter_count_target": project_yaml.get("chapter_count_target"),
        "chapters_in_outline": project_yaml.get("chapters_in_outline"),

        # Author persona: project overrides win if provided, else inherit genre's hints
        "author_persona_hints": (
            project_yaml.get("author_persona_overrides")
            or genre_yaml.get("author_persona_hints", [])
        ),

        # Genre avoidance list (shared across all projects of this genre)
        "genre_avoid": genre_yaml.get("genre_avoid", []),

        # Prohibited styles: genre base + project-specific extras
        "prohibited_styles": list(genre_yaml.get("prohibited_styles", []))
                          + list(project_yaml.get("extra_prohibited_styles", [])),
    }
    return merged


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
        description="Seed a project's state/ from its genre + project pack"
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--list", action="store_true",
                     help="List all known projects")
    grp.add_argument("--list-genres", action="store_true",
                     help="List all known genres")
    grp.add_argument("--project", metavar="PROJECT_ID",
                     help="Activate a project and seed its state/")
    grp.add_argument("--new-project", metavar="PROJECT_ID",
                     help="Create a new project scaffold (requires --genre)")
    parser.add_argument("--genre", metavar="GENRE_ID",
                        help="Genre id for --new-project")
    parser.add_argument("--overwrite", action="store_true",
                        help="With --new-project, overwrite if dir exists")
    args = parser.parse_args()

    if args.list:
        projects = list_projects()
        if not projects:
            print("(no projects found under projects/)")
        else:
            for p in projects:
                proj_yaml = yaml.safe_load(
                    (config.PROJECTS_DIR / p / "project.yaml").read_text(encoding="utf-8")
                )
                genre = proj_yaml.get("genre", "?")
                name = proj_yaml.get("display_name", p)
                print(f"  {p:40s}  genre={genre:30s}  {name}")
        return

    if args.list_genres:
        genres = list_genres()
        if not genres:
            print("(no genres found under genres/)")
        else:
            for g in genres:
                g_yaml = yaml.safe_load(
                    (config.GENRES_DIR / g / "genre.yaml").read_text(encoding="utf-8")
                )
                name = g_yaml.get("display_name", g)
                print(f"  {g:40s}  {name}")
        return

    if args.new_project:
        if not args.genre:
            parser.error("--new-project requires --genre <genre-id>")
        try:
            project_dir = create_project(
                args.new_project, args.genre, overwrite=args.overwrite
            )
        except (FileNotFoundError, FileExistsError) as e:
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
        print(f"Seeding state/ for project '{result.project_id}' "
              f"(genre: {result.genre_id})")
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
