"""Genre extraction core — pure functions that produce extraction artifacts.

These functions are oblivious to whether artifacts end up in a project or a
preset. Callers (to_project.py / to_preset.py / legacy pipeline.py entry points)
pass an ``out_dir`` explicitly to :func:`render_files_from_blueprint`.

Design:
  - ``count_chapters_in_text`` / ``split_text_into_batches``: thin, pure text
    utilities that wrap :mod:`chapter_detector`.
  - ``run_extract`` / ``run_merge`` / ``run_draft``: operate solely on a
    :class:`Blackboard`. They don't care about genres/<id>/ vs. projects/<id>/.
  - ``render_files_from_blueprint``: takes an explicit ``out_dir`` keyword-only
    and writes the 3 (or 4, with resource_schema) artifact files. Purges a
    stale ``resource_schema.yaml`` when the blueprint no longer has one.

Internal helpers are prefixed with underscore and are not part of the public
surface consumed by ``to_project.py`` / ``to_preset.py``.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterable

import yaml

from src.core.blackboard import Blackboard
from src.genre_extractor import adaptive, chapter_detector, schemas
from src.genre_extractor.chapter_stream import ChapterStream


# Threshold for book-level distill: ≥ 4 arcs → distill. Below that, the
# last arc is promoted to latest_merged directly. See _run_merge_multitier.
BOOK_ARC_THRESHOLD = 4

# Default chapter batch size for extraction. Kept here (not in a deeper
# submodule) so to_preset.py / to_project.py can import one canonical value
# and callers of run_extract don't each pick their own.
DEFAULT_EXTRACTION_BATCH_SIZE = 25


# ---------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------
def count_chapters_in_text(text: str) -> int:
    """Delegate to chapter_detector; supports multi-format chapter markers."""
    return chapter_detector.count_chapters(text)


def split_text_into_batches(
    text: str,
    *,
    batch_size: int = 25,
    total_chapters: int | None = None,
) -> list[str]:
    """Split novel text into batches of exactly ``batch_size`` chapters each.

    Uses real chapter offsets from :mod:`chapter_detector` rather than the
    old character-count approximation, so batch boundaries align with
    chapter boundaries. When no markers are found the whole text is
    returned as a single batch.

    ``total_chapters`` is accepted for backwards compatibility but ignored —
    the detector is re-run to find actual offsets.
    """
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    if not text:
        return []

    splits = chapter_detector.find_chapter_splits(text)
    # splits[i] = start offset of chapter i+1; first is always 0. Append
    # len(text) as a sentinel so we can take [splits[i], splits[i+1]) slices.
    boundaries = splits + [len(text)]

    out: list[str] = []
    n_chapters = len(splits)
    for start_ch in range(0, n_chapters, batch_size):
        end_ch = min(start_ch + batch_size, n_chapters)
        out.append(text[boundaries[start_ch]:boundaries[end_ch]])
    return out


# ---------------------------------------------------------------
# Phase 1: Extract
# ---------------------------------------------------------------
def run_extract(
    bb: Blackboard,
    source_streams: Iterable,
    *,
    cancel=None,
    on_progress=None,
) -> None:
    """Run the Extractor over each novel source, one batch at a time.

    ``source_streams`` is a list of (ChapterStream, batch_size) tuples. Each
    batch's text is loaded lazily via ``stream.read_batch()`` so peak RAM
    stays bounded regardless of novel size.

    ``cancel`` is an optional :class:`src.jobs.cancel.CancelToken` — its
    ``check()`` is called at every batch boundary so web-side abort lands
    within one batch's worth of latency (not mid-LLM-call, which can't be
    interrupted safely).

    ``on_progress`` is an optional :class:`ProgressCallback` — called once
    per completed batch with ``sub_steps={"batch_cur": i, "batch_total": N}``.
    """
    from src.genre_extractor.agents.extractor import GenreExtractor
    from src.genre_extractor.progress import null_progress
    from src.jobs.cancel import NullCancelToken

    if cancel is None:
        cancel = NullCancelToken()
    if on_progress is None:
        on_progress = null_progress

    schemas.update_phase_status(bb, phase="extract", status="in_progress")
    agent = GenreExtractor()

    # Pre-count total batches so progress callbacks can report X/N.
    all_batches: list[tuple[ChapterStream, int, int]] = []
    for stream, bs in source_streams:
        total_ch = stream.total_chapters
        for start_ch, end_ch in adaptive.split_into_batches(
            total_chapters=total_ch, batch_size=bs
        ):
            all_batches.append((stream, start_ch, end_ch))
    total_batches = len(all_batches)

    # Initial "entering extract phase" ping so the UI can highlight the node.
    on_progress(
        phase="extract", phase_index=1,
        sub_steps={"batch_cur": 0, "batch_total": total_batches},
        progress_text=f"extract 0/{total_batches}",
    )

    global_batch_id = 0
    for stream, start_ch, end_ch in all_batches:
        cancel.check()
        global_batch_id += 1
        btxt = stream.read_batch(start_ch, end_ch)
        schemas.set_in_flight(bb, agent="genre_extractor", batch_id=global_batch_id)
        agent.run(bb, batch_id=global_batch_id, batch_text=btxt)
        schemas.record_batch_done(bb, batch_id=global_batch_id)
        on_progress(
            phase="extract", phase_index=1,
            sub_steps={"batch_cur": global_batch_id, "batch_total": total_batches},
            progress_text=f"extract batch {global_batch_id}/{total_batches}",
        )
    schemas.clear_in_flight(bb)
    schemas.update_phase_status(bb, phase="extract", status="done")


# ---------------------------------------------------------------
# Phase 2: Merge (3-tier)
# ---------------------------------------------------------------
def run_merge(
    bb: Blackboard,
    *,
    cancel=None,
    on_progress=None,
) -> None:
    """Three-tier merge: batch → arc → book-level latest_merged.yaml.

    Regimes (drives LLM call count):
      ≤ ARC_BATCH_COUNT batches    → pure concat, 0 LLM calls (short book)
      5 – 4×ARC_BATCH_COUNT batches → arc tier only, ≥2 arc_merger calls
      > 4×ARC_BATCH_COUNT batches  → arc tier + 1 book_distiller call (long book)

    ``cancel`` is called between each arc merge; ``on_progress`` reports
    ``sub_steps={"arc_cur": i, "arc_total": N}`` when the multitier path runs.
    """
    from src.genre_extractor.agents.arc_merger import ARC_BATCH_COUNT
    from src.genre_extractor.progress import null_progress
    from src.jobs.cancel import NullCancelToken

    if cancel is None:
        cancel = NullCancelToken()
    if on_progress is None:
        on_progress = null_progress

    cancel.check()
    schemas.update_phase_status(bb, phase="merge", status="in_progress")
    notes = bb.list_files("extraction_notes", "batch-*.yaml")
    batch_ids = sorted(
        bid for bid in (_parse_batch_id(p.name) for p in notes) if bid is not None
    )

    on_progress(phase="merge", phase_index=2, progress_text="merge started")

    if len(batch_ids) <= ARC_BATCH_COUNT:
        # Regime 1: pure concat, no LLM.
        _run_merge_concat(bb, notes)
    else:
        # Regime 2 & 3: arc tier (always), book distill (when arcs ≥ 4).
        _run_merge_multitier(
            bb, batch_ids, cancel=cancel, on_progress=on_progress,
        )

    # Health dashboard — best-effort.
    try:
        from src.genre_extractor.tally import generate_extraction_tally
        status = bb.read_yaml("build_status.yaml")
        genre_id = (status or {}).get("genre_id", "unknown")
        tally_md = generate_extraction_tally(bb, genre_id)
        bb.write_text("extraction_tally.md", tally_md)
    except Exception:
        pass

    schemas.update_phase_status(bb, phase="merge", status="done")


def _parse_batch_id(fname: str) -> int | None:
    """batch-NNN.yaml → NNN. Returns None if not matching."""
    m = re.match(r"batch-(\d+)\.yaml$", fname)
    return int(m.group(1)) if m else None


def _run_merge_concat(bb: Blackboard, notes) -> None:
    """Short-book fallback: concat all batch notes without LLM."""
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


def _run_merge_multitier(
    bb: Blackboard,
    batch_ids: list[int],
    *,
    cancel=None,
    on_progress=None,
) -> None:
    """Long-book 3-tier merge. Assumes len(batch_ids) > ARC_BATCH_COUNT."""
    from src.genre_extractor.agents.arc_merger import (
        ARC_BATCH_COUNT, GenreArcMerger,
    )
    from src.genre_extractor.agents.book_distiller import GenreBookDistiller
    from src.genre_extractor.progress import null_progress
    from src.jobs.cancel import NullCancelToken

    if cancel is None:
        cancel = NullCancelToken()
    if on_progress is None:
        on_progress = null_progress

    arc_merger = GenreArcMerger()
    arc_ids: list[int] = []

    total_arcs = (len(batch_ids) + ARC_BATCH_COUNT - 1) // ARC_BATCH_COUNT
    for arc_idx, start in enumerate(range(0, len(batch_ids), ARC_BATCH_COUNT), start=1):
        cancel.check()
        group = batch_ids[start:start + ARC_BATCH_COUNT]
        arc_merger.run(bb, arc_id=arc_idx, batch_ids=group)
        arc_ids.append(arc_idx)
        on_progress(
            phase="merge", phase_index=2,
            sub_steps={"arc_cur": arc_idx, "arc_total": total_arcs},
            progress_text=f"merge arc {arc_idx}/{total_arcs}",
        )

    if len(arc_ids) == 1:
        # Defensive: promote the single arc directly.
        arc_yaml = bb.read_yaml(f"extraction_notes/arcs/arc-{arc_ids[0]:03d}.yaml")
        arc_yaml.setdefault("distilled_from_arcs", list(arc_ids))
        bb.write_yaml("extraction_notes/latest_merged.yaml", arc_yaml)
        return

    if len(arc_ids) < BOOK_ARC_THRESHOLD:
        # With 2-3 arcs, promote the final arc directly.
        final_arc = arc_ids[-1]
        arc_yaml = bb.read_yaml(f"extraction_notes/arcs/arc-{final_arc:03d}.yaml")
        arc_yaml.setdefault("distilled_from_arcs", list(arc_ids))
        bb.write_yaml("extraction_notes/latest_merged.yaml", arc_yaml)
        return

    cancel.check()
    on_progress(
        phase="merge", phase_index=2,
        progress_text="book-level distill",
    )
    GenreBookDistiller().run(bb, arc_ids=arc_ids)


# ---------------------------------------------------------------
# Phase 3: Draft
# ---------------------------------------------------------------
def run_draft(
    bb: Blackboard,
    build_key: str,
    *,
    cancel=None,
    on_progress=None,
) -> None:
    """Populate genre_blueprint.yaml via the GenreDrafter agent.

    ``build_key`` is the identifier (genre_id or project_id) used only for
    labeling the blueprint skeleton. It does NOT determine any filesystem
    path — rendering to disk is a separate concern (see
    :func:`render_files_from_blueprint`).

    ``cancel`` is checked once at the start (drafter is a single LLM call and
    can't be interrupted mid-flight safely). ``on_progress`` reports phase
    entry; Chain-of-Density per-pass reporting is currently TODO inside the
    drafter agent.
    """
    from src.genre_extractor.agents.drafter import GenreDrafter
    from src.genre_extractor.progress import null_progress
    from src.jobs.cancel import NullCancelToken

    if cancel is None:
        cancel = NullCancelToken()
    if on_progress is None:
        on_progress = null_progress

    cancel.check()
    schemas.update_phase_status(bb, phase="draft", status="in_progress")
    on_progress(phase="draft", phase_index=3, progress_text="draft started")
    bb.write_yaml(
        "genre_blueprint.yaml",
        schemas.make_empty_blueprint(genre_id=build_key),
    )
    GenreDrafter().run(bb)
    schemas.update_phase_status(bb, phase="draft", status="done")


# ---------------------------------------------------------------
# Rendering blueprint → disk
# ---------------------------------------------------------------
def render_files_from_blueprint(
    blueprint: dict,
    *,
    out_dir: Path,
) -> list[Path]:
    """Write era.md / writing-style-extra.md / iron-laws-extra.md (and
    optionally resource_schema.yaml) to ``out_dir``.

    If the blueprint has no ``resource_schema`` but ``out_dir`` already
    contains a stale ``resource_schema.yaml``, it is deleted so the output
    faithfully represents the current blueprint.

    Returns a list of paths that were written (the stale-purge is not
    included).
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
