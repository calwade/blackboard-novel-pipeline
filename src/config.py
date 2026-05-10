"""Central configuration. Loaded once at import time."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from project root if present
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# LLM settings
LLM_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
LLM_BASE_URL: str = os.environ.get(
    "DEEPSEEK_BASE_URL", "https://work-api-srv.easyclaw.cn/v1"
).rstrip("/")
LLM_MODEL: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

# Optional Perplexity web-search (A-1). When absent, FactChecker skips
# gracefully; Evaluator is unaffected. OpenAI-compatible chat/completions
# shape — see src/tools/websearch.py.
PERPLEXITY_API_KEY: str = os.environ.get("PERPLEXITY_API_KEY", "")
PERPLEXITY_BASE_URL: str = os.environ.get(
    "PERPLEXITY_BASE_URL", "https://work-api-srv.easyclaw.cn/api/v1/search"
).rstrip("/")
PERPLEXITY_MODEL: str = os.environ.get("PERPLEXITY_MODEL", "perplexity/sonar-pro")

# Paths (all relative to project root)
PROJECT_ROOT: Path = _PROJECT_ROOT

# Allow STATE_DIR override via env. On hosted deployments (Railway, Render)
# we point STATE_DIR at demo_snapshot/ so the Web UI shows real produced content
# without needing to run the pipeline server-side.
_state_env = os.environ.get("STATE_DIR")
if _state_env:
    STATE_DIR = Path(_state_env)
else:
    STATE_DIR = _PROJECT_ROOT / "state"

RULES_DIR: Path = _PROJECT_ROOT / "rules"
DOCS_DIR: Path = _PROJECT_ROOT / "docs"

# Ensure state directory and subdirs exist at import
for sub in ("", "chapters", "summaries", "fixes"):
    (STATE_DIR / sub).mkdir(parents=True, exist_ok=True)


def assert_llm_configured() -> None:
    """Raise a helpful error early if the API key is missing."""
    if not LLM_API_KEY or LLM_API_KEY.startswith("dc-sk-put-yours"):
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not configured. Copy .env.example to .env "
            "and fill in your key from the EasyClaw platform."
        )
