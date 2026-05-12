"""Trial-book runner — build a throwaway project and run 3 chapters.

Part of the genre pipeline validation suite. Given a candidate genre pack,
we spin up a temp "trial-probe" project, point config at it, run the full
novel pipeline for N chapters (default 3), aggregate the Evaluator
verdicts, and log a summary record to `genre_issues.jsonl`.

Design notes
------------
- We do NOT reuse `src.tools.calibrate_evaluator.setup_scratch_state`: that
  helper skips `config.set_active_project_id` / `config.refresh_state_dir`,
  so agents would read the wrong STATE_DIR.
- Instead we monkey-patch `config.PROJECTS_DIR` + `config.ACTIVE_POINTER`
  to a tmp location, then call `bootstrap.bootstrap_project()` exactly
  the way `tests/conftest.py::isolated_project` does.
- On exit we restore config + any prior active project, and `rmtree`
  the tmp dir unless `keep_scratch=True`.
- `dry_run=True` walks the whole bootstrap + cleanup path but skips the
  per-chapter run_chapter call — used by tests and by CLI smoke-checks.

Concurrency: NOT safe to call in parallel with another pipeline run in
the same process, because it mutates `config.PROJECTS_DIR` and the
active-project pointer. v1 is strictly serial.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from src import bootstrap, config
from src.core.blackboard import Blackboard


TRIAL_PROJECT_ID = "trial-probe"


def run_trial(
    genre_id: str,
    bb: Blackboard,
    chapters: int = 3,
    *,
    dry_run: bool = False,
    keep_scratch: bool = False,
) -> None:
    """Run an N-chapter trial against a candidate genre.

    Parameters
    ----------
    genre_id
        The candidate genre id (must exist under `config.GENRES_DIR`).
    bb
        Genre-pipeline blackboard (rooted at `genres/<id>/.build/`). We
        append the trial's summary to its `genre_issues.jsonl`.
    chapters
        Number of chapters to try (default 3).
    dry_run
        If True, do everything except the per-chapter LLM work.
    keep_scratch
        If True, leave the scratch tmpdir on disk for post-mortem.

    Appends to `bb/genre_issues.jsonl`:
      - severity="info" if dry_run or all chapters passed
      - severity="warning" for each failed chapter + a rollup record
      - severity="warning" if bootstrap itself fails
    """
    # 1. Validate genre up front so bad inputs fail fast.
    genre_dir = config.GENRES_DIR / genre_id
    if not genre_dir.exists():
        raise FileNotFoundError(
            f"Genre not found: {genre_dir}. Known: "
            f"{', '.join(bootstrap.list_genres()) or '(none)'}"
        )
    missing = bootstrap.validate_genre(genre_dir)
    if missing:
        raise ValueError(
            f"Genre '{genre_id}' is incomplete; cannot run trial. Missing: "
            + ", ".join(missing)
        )

    # 2. Remember what config looked like BEFORE we touch anything, so
    #    the finally-block can restore it verbatim.
    prior_active = config.get_active_project_id()
    prior_projects_dir = config.PROJECTS_DIR
    prior_active_pointer = config.ACTIVE_POINTER
    prior_state_dir = config.STATE_DIR

    scratch_root = Path(tempfile.mkdtemp(prefix=f"genre_trial_{genre_id}_"))
    try:
        tmp_projects = scratch_root / "projects"
        tmp_projects.mkdir()

        # 3. Seed the trial project's source files inside the tmp projects dir.
        trial_dir = tmp_projects / TRIAL_PROJECT_ID
        trial_dir.mkdir()
        _write_trial_project_files(trial_dir, genre_id, genre_dir)

        # 4. Point config at the tmp projects dir (but keep GENRES_DIR as-is
        #    — the trial validates THE EXISTING genre, in place).
        config.PROJECTS_DIR = tmp_projects
        config.ACTIVE_POINTER = tmp_projects / ".active"

        # 5. Bootstrap: copies genre files + trial files into
        #    tmp_projects/trial-probe/state/ and flips active.
        bootstrap.bootstrap_project(TRIAL_PROJECT_ID)

        # 6. Run chapters. Each chapter is driven through the real pipeline.
        verdicts: list[dict[str, Any]] = []
        if not dry_run:
            # Import here to avoid importing the pipeline stack when only
            # CLI dry-runs are requested.
            from src.pipeline import run_chapter

            # Blackboard() now captures the freshly-refreshed STATE_DIR.
            novel_bb = Blackboard()
            for ch in range(1, chapters + 1):
                try:
                    run_chapter(novel_bb, ch)
                except Exception as e:
                    bb.append_jsonl("genre_issues.jsonl", {
                        "severity": "warning",
                        "file": "(trial)",
                        "message": (
                            f"trial chapter {ch} crashed: "
                            f"{type(e).__name__}: {e}"
                        ),
                        "genre_id": genre_id,
                        "chapter": ch,
                    })
                    # Keep going — downstream chapters still informative.
                    continue

                vpath = f"chapters/ch{ch:03d}.verdict.json"
                if novel_bb.exists(vpath):
                    verdicts.append({"ch": ch, **novel_bb.read_json(vpath)})

        # 7. Aggregate & log
        _log_summary(bb, genre_id, chapters, verdicts, dry_run=dry_run)

    except Exception:
        # Surface the failure to the caller; finally-block still restores.
        raise
    finally:
        # 8. Restore config to its pre-trial state.
        config.PROJECTS_DIR = prior_projects_dir
        config.ACTIVE_POINTER = prior_active_pointer
        if prior_active is None:
            # Make sure no stale active pointer we just wrote sticks around.
            try:
                if prior_active_pointer.exists():
                    prior_active_pointer.unlink()
            except OSError:
                pass
        else:
            # Write back the old active id (under the REAL ACTIVE_POINTER).
            try:
                prior_active_pointer.parent.mkdir(parents=True, exist_ok=True)
                prior_active_pointer.write_text(
                    prior_active + "\n", encoding="utf-8"
                )
            except OSError:
                pass
        # Snap STATE_DIR back. If the prior STATE_DIR was under the soon-to-be
        # deleted tmpdir, refresh_state_dir() will re-resolve to the legacy
        # fallback or the restored active project.
        try:
            config.refresh_state_dir()
        except OSError:
            config.STATE_DIR = prior_state_dir  # best-effort
        # 9. Clean up scratch.
        if not keep_scratch:
            shutil.rmtree(scratch_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _write_trial_project_files(trial_dir: Path, genre_id: str,
                               genre_dir: Path) -> None:
    """Write the 4 required project-layer files into `trial_dir`.

    The fields below satisfy `bootstrap.validate_project` and the minimum
    shape that Planner/Generator/Evaluator/Fixer expect. Values are
    deliberately generic — the trial cares about "does the genre let
    agents produce anything?", not about telling a specific story.
    """
    genre_yaml = yaml.safe_load((genre_dir / "genre.yaml").read_text(encoding="utf-8"))
    # Best-effort opening_year_month from the genre's era (e.g. "1983-2000 香港"
    # or "北宋年间"); if we can't parse a year, pick a bland default.
    opening = _infer_opening_year_month(genre_yaml.get("era", ""))

    project_yaml = {
        "id": TRIAL_PROJECT_ID,
        "display_name": f"Trial Probe · {genre_id}",
        "genre": genre_id,
        "protagonist_name": "试验主角",
        "protagonist_hook": f"试验用占位主角，验证 {genre_id} 题材包是否可产出",
        "opening_year_month": opening,
        "chapter_count_target": 3,
        "chapters_in_outline": 3,
        "author_persona_overrides": [],
        "extra_prohibited_styles": [],
    }
    (trial_dir / "project.yaml").write_text(
        yaml.safe_dump(project_yaml, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # outline.json — 3 chapters, each with the fields Planner/Generator look up.
    chapters = []
    for i in (1, 2, 3):
        chapters.append({
            "ch": i,
            "title": f"第{i}章 · 试验",
            "year_month": opening,
            "key_location": "试验场景",
            "key_characters": ["试验主角", "试验配角"],
            "beats": [
                f"节拍一：试验主角在试验场景出现（第{i}章）",
                "节拍二：发生一次小冲突，推进主角处境",
                "节拍三：章末落下一个悬念，引向下一章",
            ],
            "opening_hook": f"第{i}章开场钩子：主角登场。",
            "closing_hook": f"第{i}章收束钩子：悬念抛出。",
            "tension": "生存 + 身份切换",
            "landmines_to_avoid": ["流水账", "AI 味"],
            "word_target": 3000,
        })
    (trial_dir / "outline.json").write_text(
        _json_dumps({
            "title": f"Trial Probe · {genre_id}",
            "protagonist": "试验主角",
            "chapter_count_target": 3,
            "chapters_in_outline": 3,
            "chapters": chapters,
        }),
        encoding="utf-8",
    )

    characters = {
        "protagonist": {
            "id": "trial_mc",
            "name": "试验主角",
            "age": 25,
            "appearance": "身形普通，眼神平静",
            "traits": ["冷静", "有底线"],
            "redlines": ["不伤无辜"],
            "catchphrase": ["先算账"],
            "motivation": "验证本题材包是否可工作",
        },
        "supporting": [
            {"id": "trial_side", "name": "试验配角", "role": "辅助",
             "traits": ["憨直"], "motivation": "陪同主角"},
        ],
    }
    (trial_dir / "characters.yaml").write_text(
        yaml.safe_dump(characters, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    timeline = {
        opening.split("-")[0] if "-" in opening else "当代": [
            {"date": opening, "event": "试验主角进入故事"},
        ],
    }
    (trial_dir / "timeline.yaml").write_text(
        yaml.safe_dump(timeline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _infer_opening_year_month(era: str) -> str:
    """Pull a YYYY-MM from a genre's era string, falling back to '2024-01'."""
    import re
    m = re.search(r"(1\d{3}|20\d{2})", era or "")
    if m:
        year = m.group(1)
        return f"{year}-01"
    return "2024-01"


def _log_summary(bb: Blackboard, genre_id: str, chapters: int,
                 verdicts: list[dict], *, dry_run: bool) -> None:
    """Write one or more genre_issues.jsonl records summarizing the trial."""
    if dry_run:
        bb.append_jsonl("genre_issues.jsonl", {
            "severity": "info",
            "file": "(trial)",
            "message": f"trial dry-run completed (genre_id={genre_id}, chapters={chapters})",
            "genre_id": genre_id,
        })
        return

    passed = sum(1 for v in verdicts if v.get("overall_pass"))
    total = len(verdicts)

    # Per-failed-chapter warnings (so downstream Fixer can see specifics).
    for v in verdicts:
        if v.get("overall_pass"):
            continue
        hits = [
            mid for mid, m in (v.get("landmines") or {}).items() if m.get("hit")
        ]
        bb.append_jsonl("genre_issues.jsonl", {
            "severity": "warning",
            "file": "(trial)",
            "message": (
                f"trial book failed on ch{v.get('ch')} "
                f"(landmines={hits or 'unknown'})"
            ),
            "genre_id": genre_id,
            "chapter": v.get("ch"),
            "top_3_fixes": v.get("top_3_fixes", []),
        })

    # Rollup record.
    if total == 0:
        bb.append_jsonl("genre_issues.jsonl", {
            "severity": "warning",
            "file": "(trial)",
            "message": (
                f"trial produced 0 verdicts (genre_id={genre_id}); "
                "every chapter crashed before Evaluator"
            ),
            "genre_id": genre_id,
        })
    elif passed == total == chapters:
        bb.append_jsonl("genre_issues.jsonl", {
            "severity": "info",
            "file": "(trial)",
            "message": f"trial passed {passed}/{chapters}",
            "genre_id": genre_id,
        })
    else:
        bb.append_jsonl("genre_issues.jsonl", {
            "severity": "warning",
            "file": "(trial)",
            "message": (
                f"trial passed {passed}/{chapters} "
                f"(got verdicts for {total}/{chapters})"
            ),
            "genre_id": genre_id,
        })


def _json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)
