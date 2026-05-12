"""BaseAgent — common base for all LLM-backed agents.

Moved from src/agents/_base.py in the 2026-05-11 refactor so the new
genre pipeline can extend it without importing from the novel agents
package.

Each agent is one function but we wrap it as a class to keep:
- name (for prompt_log)
- temperature (role-specific)
- response_format (json or text)
- a standard run() entry point that takes a Blackboard + kwargs

Subclasses override _build_prompts(bb, **kwargs) -> (system, user, inputs_read)
and _handle_output(bb, raw, **kwargs) -> None to persist results.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from .. import llm
from .blackboard import Blackboard


class BaseAgent(ABC):
    name: str = "base"
    temperature: float = 0.7
    response_format: Literal["text", "json"] = "text"
    max_tokens: int = 4096

    @abstractmethod
    def _build_prompts(
        self, bb: Blackboard, **kwargs
    ) -> tuple[str, str, list[str]]:
        """Return (system_prompt, user_prompt, inputs_read_paths)."""

    @abstractmethod
    def _handle_output(self, bb: Blackboard, raw: str, **kwargs) -> None:
        """Persist the LLM output to the blackboard."""

    def run(self, bb: Blackboard, **kwargs) -> str:
        system, user, inputs_read = self._build_prompts(bb, **kwargs)
        raw = llm.chat(
            system=system,
            user=user,
            agent_name=self.name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format=self.response_format,
            inputs_read=inputs_read,
        )
        self._handle_output(bb, raw, **kwargs)
        return raw

    # Helpers subclasses can use
    @staticmethod
    def _read_rule(rule_filename: str) -> str:
        from .. import config
        return (config.RULES_DIR / rule_filename).read_text(encoding="utf-8")
