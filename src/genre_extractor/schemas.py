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
