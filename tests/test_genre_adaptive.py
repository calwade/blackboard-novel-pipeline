"""adaptive.py：自适应档位 + 章节切分。"""
from __future__ import annotations

import pytest


def test_adaptive_batch_size_short():
    from src.genre_pipeline.adaptive import adaptive_batch_size
    assert adaptive_batch_size(30) == 10
    assert adaptive_batch_size(50) == 10


def test_adaptive_batch_size_medium():
    from src.genre_pipeline.adaptive import adaptive_batch_size
    assert adaptive_batch_size(51) == 25
    assert adaptive_batch_size(400) == 25
    assert adaptive_batch_size(600) == 25


def test_adaptive_batch_size_long():
    from src.genre_pipeline.adaptive import adaptive_batch_size
    assert adaptive_batch_size(601) == 40
    assert adaptive_batch_size(1200) == 40


def test_split_into_batches_exact():
    from src.genre_pipeline.adaptive import split_into_batches
    batches = split_into_batches(total_chapters=50, batch_size=10)
    assert batches == [(1, 10), (11, 20), (21, 30), (31, 40), (41, 50)]


def test_split_into_batches_remainder():
    from src.genre_pipeline.adaptive import split_into_batches
    batches = split_into_batches(total_chapters=55, batch_size=25)
    assert batches == [(1, 25), (26, 50), (51, 55)]


def test_split_into_batches_empty():
    from src.genre_pipeline.adaptive import split_into_batches
    assert split_into_batches(total_chapters=0, batch_size=25) == []


def test_split_into_batches_invalid():
    from src.genre_pipeline.adaptive import split_into_batches
    with pytest.raises(ValueError):
        split_into_batches(total_chapters=10, batch_size=0)
