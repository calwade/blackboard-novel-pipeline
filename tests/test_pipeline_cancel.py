"""Cooperative cancel: setting CANCEL_EVENT before a stage raises PipelineAborted."""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from src import pipeline
from src.blackboard import Blackboard


def test_cancel_event_is_threading_event():
    assert isinstance(pipeline.CANCEL_EVENT, threading.Event)


def test_check_cancel_raises_when_set():
    pipeline.CANCEL_EVENT.set()
    try:
        with pytest.raises(pipeline.PipelineAborted):
            pipeline._check_cancel()
    finally:
        pipeline.CANCEL_EVENT.clear()


def test_check_cancel_passes_when_cleared():
    pipeline.CANCEL_EVENT.clear()
    pipeline._check_cancel()  # does not raise


def test_run_chapter_aborts_between_stages(tmp_path, monkeypatch):
    """If CANCEL_EVENT is set before planner runs, we should see PipelineAborted."""
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    from src import config
    config.refresh_state_dir()
    bb = Blackboard(root=tmp_path)
    bb.write_json("progress.json", {"completed_chapters": [], "current_chapter": 0})

    pipeline.CANCEL_EVENT.set()
    try:
        with pytest.raises(pipeline.PipelineAborted):
            pipeline.run_chapter(bb, chapter=1)
    finally:
        pipeline.CANCEL_EVENT.clear()
