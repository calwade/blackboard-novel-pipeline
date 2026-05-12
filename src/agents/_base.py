"""Backward-compat shim — BaseAgent moved to src/core/base_agent.py on 2026-05-11.

The `llm` module is also re-exported at module level because many existing tests
monkey-patch `src.agents._base.llm.chat` directly. Removing it would break those
tests even though the actual BaseAgent code now lives in src/core/base_agent.py.
Both shim and core module reference the same underlying `src.llm` module, so
patches against either path take effect.
"""
from ..core.base_agent import BaseAgent  # noqa: F401
from .. import llm  # noqa: F401  # re-export for monkeypatch compatibility
