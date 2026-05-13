"""Extract a genre pack into projects/<book-id>/.

Sources resolve via the same rules as to_preset (pool-first, absolute ok).
Prior era.md/writing-style-extra.md/iron-laws-extra.md/resource_schema.yaml
contents are backed up into projects/<book-id>/state/.backup/ with a timestamp.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from src import config
from src.blackboard import Blackboard
from src.genre_extractor import core, schemas
from src.genre_extractor.chapter_stream import ChapterStream
from src.genre_extractor.progress import null_progress
from src.genre_extractor.to_preset import _resolve_source
from src.jobs.cancel import NullCancelToken

GENRE_FILES = (
    "era.md",
    "writing-style-extra.md",
    "iron-laws-extra.md",
    "resource_schema.yaml",
)

# Legacy 2-arg phase callback. New code should use ``on_progress`` instead.
PhaseCallback = Callable[[str, Optional[str]], None]


def _safe_phase(on_phase: Optional[PhaseCallback], phase: str, progress: Optional[str] = None) -> None:
    """Fire a phase event if a callback is wired, swallowing any exception.

    Phase reporting must never take the extraction flow down with it — a
    broken UI poll should not corrupt a 60-minute LLM run.
    """
    if on_phase is None:
        return
    try:
        on_phase(phase, progress)
    except Exception:
        pass


def _run_full_extraction_to_blueprint(
    bb: Blackboard,
    sources: list,
    *,
    on_phase: Optional[PhaseCallback] = None,
    cancel=None,
    on_progress=None,
) -> dict:
    """Drive the core pipeline end-to-end; return the final blueprint dict.

    Own function so tests can monkeypatch to avoid LLMs.

    ``sources`` is a list of :class:`ChapterStream` instances owned by the
    caller. They must remain alive for the whole call (they hold a
    tempfile via ``__del__`` for non-UTF-8 source novels).

    Fires legacy ``on_phase("extract" | "merge" | "draft")`` AND the new
    structured ``on_progress`` at each stage boundary.
    """
    cancel = cancel or NullCancelToken()
    on_progress = on_progress or null_progress

    cancel.check()
    _safe_phase(on_phase, "extract")
    # core.run_extract expects (ChapterStream, batch_size) tuples.
    core.run_extract(
        bb,
        [(s, core.DEFAULT_EXTRACTION_BATCH_SIZE) for s in sources],
        cancel=cancel,
        on_progress=on_progress,
    )
    cancel.check()
    _safe_phase(on_phase, "merge")
    core.run_merge(bb, cancel=cancel, on_progress=on_progress)
    cancel.check()
    _safe_phase(on_phase, "draft")
    core.run_draft(bb, build_key=str(bb.root), cancel=cancel, on_progress=on_progress)
    return bb.read_yaml("genre_blueprint.yaml") or {}


def extract_to_project(
    book_id: str,
    *,
    sources: list[str],
    with_trial: bool = False,
    on_phase: Optional[PhaseCallback] = None,
    cancel=None,
    on_progress=None,
) -> dict:
    """Extract a genre pack into this book's own directory (overwriting in place,
    prior versions backed up).

    ``cancel`` / ``on_progress`` — see :func:`extract_to_preset` docstring.
    """
    cancel = cancel or NullCancelToken()
    on_progress = on_progress or null_progress

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

    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    for fname in GENRE_FILES:
        src = book_dir / fname
        if src.exists():
            stem, dot, ext = fname.rpartition(".")
            # produce "era.<ts>.md" style names
            backup_name = f"{stem}.{ts}.{ext}" if dot else f"{fname}.{ts}"
            shutil.copy2(src, backup_dir / backup_name)

    bb = Blackboard(root=build_dir)

    # Build ChapterStream instances up front (mirrors extract_to_preset):
    # surfaces encoding errors, gives us total_chapters for the
    # build_status seed, and avoids re-parsing. Held in this local so
    # their tempfile-cleaning __del__ only fires after the whole pipeline
    # finishes.
    streams = [ChapterStream(p) for p in resolved]
    novel_sources = [
        {
            "path": str(p),
            "total_chapters": s.total_chapters,
            "batch_size": core.DEFAULT_EXTRACTION_BATCH_SIZE,
        }
        for p, s in zip(resolved, streams)
    ]

    # Seed build_status.yaml BEFORE run_extract — its first op reads this file.
    bb.write_yaml(
        "build_status.yaml",
        schemas.make_initial_build_status(
            genre_id=book_id,
            entry="extract-to-project",
            novel_sources=novel_sources,
        ),
    )

    blueprint = _run_full_extraction_to_blueprint(
        bb, streams,
        on_phase=on_phase, cancel=cancel, on_progress=on_progress,
    )
    core.render_files_from_blueprint(blueprint, out_dir=book_dir)

    # P0-2: run Validator + Fixer retry loop against the book's own genre
    # files (not PRESETS_DIR). Closes the gap where extract_to_project used
    # to bypass the Validator entirely.
    from src.genre_extractor import pipeline
    cancel.check()
    _safe_phase(on_phase, "validate")
    on_progress(phase="validate", phase_index=4, progress_text="validate started")
    try:
        pipeline._run_validate(
            bb,
            book_id,
            with_trial=False,
            files_dir=book_dir,
        )
    except Exception as e:
        # Validate failure must not break the extraction output — log and move on.
        bb.append_jsonl("genre_issues.jsonl", {
            "severity": "warning",
            "file": "(validator)",
            "message": f"validate phase failed: {type(e).__name__}: {e}",
            "genre_id": book_id,
        })

    result = {"book_id": book_id, "sources": [str(p) for p in resolved]}
    if with_trial:
        # Pragmatic gap: trial.run_trial internally requires
        # ``config.PRESETS_DIR / genre_id`` to exist (it bootstraps a
        # throwaway project from a preset dir). Book dirs don't live
        # under PRESETS_DIR, and the book is about to run its own real
        # chapters anyway — so a trial here would be both broken and
        # redundant. We keep the API signature stable and surface the
        # skip as an info-level note in genre_issues.jsonl.
        bb.append_jsonl("genre_issues.jsonl", {
            "severity": "info",
            "file": "(trial)",
            "message": "with_trial 在作品路径暂不支持（作品本身即将跑真实章节）；跳过",
            "project_id": book_id,
        })
    _safe_phase(on_phase, "done")
    return result
