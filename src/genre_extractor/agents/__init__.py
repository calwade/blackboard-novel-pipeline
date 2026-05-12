"""Genre pipeline agents.

Primary agents + multi-tier mergers:
- GenreExtractor: slide-window extract from source novels
- GenreArcMerger: second-level merge (batch -> arc)
- GenreBookDistiller: third-level distill (arc -> book-level latest_merged)
- GenreDrafter: merged blueprint -> 5 final genre pack files
- GenreValidator: structure (setting_lint) + semantic (LLM) + optional trial
- GenreFixer: read issues -> patch files, up to 2 retries
"""
from .extractor import GenreExtractor
from .arc_merger import GenreArcMerger
from .book_distiller import GenreBookDistiller
from .drafter import GenreDrafter
from .validator import GenreValidator
from .fixer import GenreFixer

__all__ = [
    "GenreExtractor",
    "GenreArcMerger",
    "GenreBookDistiller",
    "GenreDrafter",
    "GenreValidator",
    "GenreFixer",
]
