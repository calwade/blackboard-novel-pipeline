"""Adaptive batch sizing for extracting genre rules from existing novels.

Window size decision (see Q3 in the spec):
  <= 50 chapters: 10 chapters/batch (not too few batches)
  51-600:         25 chapters/batch (default sweet spot)
  > 600:          40 chapters/batch (avoid batch explosion)
"""
from __future__ import annotations


def adaptive_batch_size(total_chapters: int) -> int:
    if total_chapters <= 50:
        return 10
    elif total_chapters <= 600:
        return 25
    else:
        return 40


def split_into_batches(*, total_chapters: int, batch_size: int) -> list[tuple[int, int]]:
    """Return [(start_ch, end_ch), ...] inclusive 1-indexed."""
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    if total_chapters <= 0:
        return []
    out: list[tuple[int, int]] = []
    start = 1
    while start <= total_chapters:
        end = min(start + batch_size - 1, total_chapters)
        out.append((start, end))
        start = end + 1
    return out
