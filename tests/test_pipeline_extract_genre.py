"""--extract-genre CLI: extract a genre pack into an existing book."""
from __future__ import annotations

import pytest


def test_pipeline_extract_genre_invokes_to_project(monkeypatch):
    """Test the function layer."""
    from src import pipeline
    captured = {}

    def fake_extract_to_project(book_id, *, sources, with_trial):
        captured.update(book_id=book_id, sources=sources, with_trial=with_trial)
        return {"book_id": book_id}

    monkeypatch.setattr(
        "src.genre_extractor.to_project.extract_to_project",
        fake_extract_to_project,
    )
    # Avoid real bootstrap (book dir doesn't exist in test)
    monkeypatch.setattr(pipeline, "bootstrap_project", lambda *a, **kw: None)
    # Force "not active" so re-bootstrap path isn't taken
    from src import config
    monkeypatch.setattr(config, "get_active_project_id", lambda: None)

    result = pipeline.run_extract_genre("mybook", sources=["a.txt"], with_trial=False)
    assert captured["book_id"] == "mybook"
    assert captured["sources"] == ["a.txt"]
    assert captured["with_trial"] is False
    assert result["book_id"] == "mybook"


def test_pipeline_extract_genre_re_bootstraps_when_active(monkeypatch):
    """If the book is the active project, re-bootstrap so state/ picks up new files."""
    from src import pipeline, config
    bootstrap_calls = []
    monkeypatch.setattr(
        "src.genre_extractor.to_project.extract_to_project",
        lambda book_id, *, sources, with_trial: {"book_id": book_id},
    )
    monkeypatch.setattr(
        pipeline, "bootstrap_project",
        lambda pid, **kw: bootstrap_calls.append((pid, kw)),
    )
    monkeypatch.setattr(config, "get_active_project_id", lambda: "mybook")

    pipeline.run_extract_genre("mybook", sources=["a.txt"])
    assert bootstrap_calls == [("mybook", {"preserve_progress": True})]


def test_pipeline_cli_extract_genre_flag_parsed():
    """--extract-genre <book-id> --sources a.txt must route to run_extract_genre."""
    from src import pipeline
    parser = pipeline._build_parser()
    args = parser.parse_args(["--extract-genre", "mybook", "--sources", "a.txt,b.txt"])
    assert args.extract_genre == "mybook"
    assert args.sources == "a.txt,b.txt"


def test_pipeline_cli_help_mentions_extract_genre():
    """--help should advertise --extract-genre."""
    from src import pipeline
    parser = pipeline._build_parser()
    text = parser.format_help()
    assert "--extract-genre" in text
