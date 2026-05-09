"""Evaluator verdict schema validator + skeleton detector.

Extracted from evaluator.py so it's unit-testable without LLM calls.

The LLM output can fail in three distinct ways that all look like "passed":

1. **Missing fields** — e.g., landmine_7 is omitted. Old code silently
   setdefault()'d, which means missing == not hit. Now we flag it so
   the caller can decide whether to retry or accept the default.

2. **Skeleton echo** — the LLM returns top_3_fixes with placeholder where/what
   (e.g., "…" / "..." / short strings). This is a false-pass because the
   model didn't actually read the chapter, it just echoed the schema.

3. **Invalid types / enum values** — severity not in {"high","medium","low"},
   hit not a bool, overall_pass not a bool. These get coerced to safe
   defaults and recorded in validation_warnings.

The validator returns a dict with:
    - clean_verdict: the normalized verdict, safe to persist
    - validation_warnings: list of human-readable strings for debugging
    - skeleton_detected: bool — when True, caller MUST treat as fail+retry
"""
from __future__ import annotations

from typing import Any


LANDMINE_IDS = [f"landmine_{i}" for i in range(1, 19)]
VALID_SEVERITIES = {"high", "medium", "low"}

# Strings the LLM might use as placeholders. All stripped before comparison.
SKELETON_MARKERS = {"…", "...", "", "..", "。。。", "<...>", "<string>", "<str>"}

# Minimum substantive lengths per prompt spec:
#   where: "原文引文，至少 6 个字"
#   what:  "改写方向，至少 10 个字"
#   evidence: must be real quote from the chapter, so at least 6 chars
MIN_WHERE_LEN = 6
MIN_WHAT_LEN = 10
MIN_EVIDENCE_LEN = 6


def validate_verdict(raw: Any) -> dict:
    """Normalize + validate a parsed verdict dict.

    Args:
        raw: whatever json.loads returned; may be malformed in many ways.

    Returns:
        {
            "clean_verdict": dict (always has all 18 landmines, valid severities,
                                   valid types, overall_pass recomputed, etc.),
            "validation_warnings": list[str],
            "skeleton_detected": bool,
        }

    This function is PURE — no I/O, no LLM calls, no file writes. Makes it
    unit-testable.
    """
    warnings: list[str] = []

    if not isinstance(raw, dict):
        # Complete garbage. Synthesize a minimal failing verdict.
        return {
            "clean_verdict": _synth_skeleton_verdict(
                "LLM did not return a JSON object (got %s)" % type(raw).__name__
            ),
            "validation_warnings": [
                f"Evaluator returned non-dict: {type(raw).__name__}"
            ],
            "skeleton_detected": True,
        }

    # ---- landmines normalization ----
    mines_raw = raw.get("landmines")
    if not isinstance(mines_raw, dict):
        warnings.append("landmines field missing or wrong type; defaulting all to hit=false")
        mines_raw = {}

    clean_mines: dict = {}
    for mine_id in LANDMINE_IDS:
        entry = mines_raw.get(mine_id)
        clean_mines[mine_id] = _normalize_mine_entry(entry, mine_id, warnings)

    # Detect missing landmines
    missing = [m for m in LANDMINE_IDS if m not in mines_raw]
    if missing:
        warnings.append(
            f"{len(missing)} landmine(s) missing from output, defaulted: {missing[:3]}"
            + ("..." if len(missing) > 3 else "")
        )

    # ---- top_3_fixes normalization ----
    fixes_raw = raw.get("top_3_fixes")
    if fixes_raw is None:
        fixes_raw = []
    if not isinstance(fixes_raw, list):
        warnings.append(
            f"top_3_fixes wrong type ({type(fixes_raw).__name__}); treating as empty"
        )
        fixes_raw = []

    clean_fixes = []
    for i, f in enumerate(fixes_raw):
        cleaned = _normalize_fix_entry(f, i, warnings)
        if cleaned is not None:
            clean_fixes.append(cleaned)

    # ---- skeleton detection ----
    skeleton = _detect_skeleton(clean_fixes, clean_mines)

    if skeleton:
        # Replace verdict contents with a failing synthetic one.
        synth = _synth_skeleton_verdict(
            "All top_3_fixes entries are placeholders/too-short, or all hit "
            "evidences are placeholders"
        )
        return {
            "clean_verdict": synth,
            "validation_warnings": warnings + ["[skeleton] " + synth["_skeleton_reason"]],
            "skeleton_detected": True,
        }

    # ---- recompute overall_pass from severities ----
    high_hits = sum(1 for m in clean_mines.values() if m["hit"] and m["severity"] == "high")
    med_hits = sum(1 for m in clean_mines.values() if m["hit"] and m["severity"] == "medium")
    overall_pass = high_hits == 0 and med_hits < 2

    clean_verdict = {
        "overall_pass": overall_pass,
        "landmines": clean_mines,
        "top_3_fixes": clean_fixes,
        "_severity_counts": {"high": high_hits, "medium": med_hits},
    }
    return {
        "clean_verdict": clean_verdict,
        "validation_warnings": warnings,
        "skeleton_detected": False,
    }


# ---------------- helpers ----------------

def _normalize_mine_entry(entry: Any, mine_id: str, warnings: list[str]) -> dict:
    """Coerce one landmine entry into {hit, evidence, severity}."""
    if not isinstance(entry, dict):
        return {"hit": False, "evidence": None, "severity": None}

    hit = bool(entry.get("hit"))

    evidence = entry.get("evidence")
    if evidence is not None and not isinstance(evidence, str):
        warnings.append(f"{mine_id}.evidence wrong type, nulled")
        evidence = None

    severity = entry.get("severity")
    if hit:
        if severity not in VALID_SEVERITIES:
            warnings.append(
                f"{mine_id} hit=true but severity={severity!r} invalid; defaulting to 'medium'"
            )
            severity = "medium"
        if not evidence or not isinstance(evidence, str):
            warnings.append(f"{mine_id} hit=true but evidence empty/null")
            # keep evidence=None; skeleton detector will catch this if enough
    else:
        severity = None
        evidence = None  # clear evidence on non-hit for hygiene

    return {"hit": hit, "evidence": evidence, "severity": severity}


def _normalize_fix_entry(entry: Any, idx: int, warnings: list[str]) -> dict | None:
    """Coerce one top_3_fix entry into {where, what} or drop it entirely."""
    if not isinstance(entry, dict):
        warnings.append(f"top_3_fixes[{idx}] not a dict; dropped")
        return None
    where = (entry.get("where") or "").strip() if isinstance(entry.get("where"), str) else ""
    what = (entry.get("what") or "").strip() if isinstance(entry.get("what"), str) else ""
    # Don't drop here — we want the skeleton detector to see placeholders and
    # trigger. Just return normalized.
    return {"where": where, "what": what}


def _is_placeholder_fix(fix: dict) -> bool:
    where = fix.get("where", "")
    what = fix.get("what", "")
    if where in SKELETON_MARKERS or what in SKELETON_MARKERS:
        return True
    if len(where) < MIN_WHERE_LEN or len(what) < MIN_WHAT_LEN:
        return True
    return False


def _is_placeholder_evidence(text: str | None) -> bool:
    """Evidence with placeholder markers or too-short is skeleton-like."""
    if text is None:
        return False
    t = text.strip()
    if t in SKELETON_MARKERS:
        return True
    if len(t) < MIN_EVIDENCE_LEN:
        return True
    return False


def _detect_skeleton(clean_fixes: list[dict], clean_mines: dict) -> bool:
    """Skeleton detection covers TWO vectors:

    1. All top_3_fixes entries have placeholder where/what.
    2. There are HIT landmines but ALL their evidences are placeholder.

    A genuine pass (no fixes + no hits) is NOT skeleton — that's valid output
    for a clean chapter.
    """
    # Vector 1
    if clean_fixes and all(_is_placeholder_fix(f) for f in clean_fixes):
        return True

    # Vector 2
    hit_mines = [m for m in clean_mines.values() if m["hit"]]
    if hit_mines and all(_is_placeholder_evidence(m["evidence"]) for m in hit_mines):
        return True

    return False


def _synth_skeleton_verdict(reason: str) -> dict:
    """Build a verdict that forces the pipeline to retry.

    Keeps the shape identical to a real verdict so downstream code doesn't
    need special-case handling; only marks `_skeleton_detected` and sets
    landmine_1 to a high-severity synthetic hit.
    """
    mines = {
        m: {"hit": False, "evidence": None, "severity": None} for m in LANDMINE_IDS
    }
    mines["landmine_1"] = {
        "hit": True,
        "evidence": f"[skeleton_detector] {reason}",
        "severity": "high",
    }
    return {
        "overall_pass": False,
        "_skeleton_detected": True,
        "_skeleton_reason": reason,
        "landmines": mines,
        "top_3_fixes": [
            {
                "where": "Evaluator 上一次调用返回占位符或格式错误",
                "what": "重新判稿。where 必须 ≥6 字原文引文，what 必须 ≥10 字改写方向，evidence 必须是章节原文具体片段。",
            }
        ],
        "_severity_counts": {"high": 1, "medium": 0},
    }
