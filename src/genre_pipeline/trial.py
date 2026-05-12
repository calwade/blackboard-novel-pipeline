"""Trial-book runner - run 3 chapters using the candidate genre pack.

v1: placeholder. Records a single "trial_not_implemented" info issue so
downstream code can proceed. Real implementation (copy calibrate_evaluator's
scratch-bootstrap skeleton + run Planner/Generator/Evaluator) follows in a
later iteration.
"""
from __future__ import annotations

from src.core.blackboard import Blackboard


def run_trial(genre_id: str, bb: Blackboard) -> None:
    """Placeholder trial run. Logs an informational issue."""
    bb.append_jsonl("genre_issues.jsonl", {
        "severity": "info",
        "file": "(trial)",
        "message": f"trial 3-chapter run not implemented in v1 (genre_id={genre_id})",
        "genre_id": genre_id,
    })
