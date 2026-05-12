"""Genre pipeline agents.

Four agents:
- GenreExtractor: slide-window extract from source novels
- GenreDrafter: merged blueprint -> 5 final genre pack files
- GenreValidator: structure (setting_lint) + semantic (LLM) + optional trial
- GenreFixer: read issues -> patch files, up to 2 retries
"""
from .extractor import GenreExtractor
from .drafter import GenreDrafter
from .validator import GenreValidator
from .fixer import GenreFixer

__all__ = ["GenreExtractor", "GenreDrafter", "GenreValidator", "GenreFixer"]
