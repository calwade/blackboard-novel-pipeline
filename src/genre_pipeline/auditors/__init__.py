"""Genre-pipeline auditors — fan-out review agents.

Splits the former monolithic GenreValidator LLM review into 3 focused agents
that can run in parallel:

- GenreFactChecker         — era.md factual correctness (optionally web-verified)
- GenreConsistencyGuard    — iron-laws internal / vs era / vs resource_schema
- GenreStyleGuard          — writing-style internal / vs core / AI-slop

Each tags its issues with a distinct `source` field so downstream tooling can
see which auditor raised which issue.
"""
from .genre_fact_checker import GenreFactChecker
from .genre_consistency_guard import GenreConsistencyGuard
from .genre_style_guard import GenreStyleGuard

__all__ = [
    "GenreFactChecker",
    "GenreConsistencyGuard",
    "GenreStyleGuard",
]
