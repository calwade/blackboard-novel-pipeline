"""STATE_DIR 必须在切项目后被 llm / websearch 的日志写入端感知到。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src import config
from src import llm


def test_prompts_log_path_follows_state_dir(tmp_path, monkeypatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    monkeypatch.setenv("STATE_DIR", str(a))
    config.refresh_state_dir()
    assert llm._prompts_log_path() == a / "prompts_log.jsonl"

    monkeypatch.setenv("STATE_DIR", str(b))
    config.refresh_state_dir()
    assert llm._prompts_log_path() == b / "prompts_log.jsonl"


def test_websearch_paths_follow_state_dir(tmp_path, monkeypatch):
    from src.tools import websearch

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    monkeypatch.setenv("STATE_DIR", str(a))
    config.refresh_state_dir()
    assert websearch._websearch_log_path() == a / "websearch_log.jsonl"
    assert websearch._websearch_cache_dir() == a / "websearch_cache"

    monkeypatch.setenv("STATE_DIR", str(b))
    config.refresh_state_dir()
    assert websearch._websearch_log_path() == b / "websearch_log.jsonl"
    assert websearch._websearch_cache_dir() == b / "websearch_cache"
