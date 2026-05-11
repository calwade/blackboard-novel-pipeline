"""Central configuration. Loaded once at import time.

Layering model (refactored 2026-05-11):
  - genres/<genre-id>/            — shared genre definition (rules, style, era)
  - projects/<project-id>/        — one specific novel (outline, characters,
                                    timeline, state/)
  - projects/<project-id>/state/  — runtime artifacts for that novel
  - projects/.active              — pointer file; single line with the id of
                                    the currently active project

STATE_DIR dynamically resolves to the active project's state/ subdir. Agents
stay agnostic: they keep reading/writing `state/...` paths via the Blackboard
module; the Blackboard's root is bound to config.STATE_DIR once, and that
resolution chases the active project.

Legacy compatibility:
  - If the STATE_DIR env var is set (e.g. for hosted read-only demos pointing
    at a frozen docs/demo_snapshot/), that wins — mirrors prior behaviour.
  - If no active project and no env override, STATE_DIR falls back to the
    legacy top-level `state/` directory. This keeps the repo runnable even
    before any project has been bootstrapped.
"""
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
# gracefully; Evaluator is unaffected.
PERPLEXITY_API_KEY: str = os.environ.get("PERPLEXITY_API_KEY", "")
PERPLEXITY_BASE_URL: str = os.environ.get(
    "PERPLEXITY_BASE_URL", "https://work-api-srv.easyclaw.cn/api/v1/search"
).rstrip("/")
PERPLEXITY_MODEL: str = os.environ.get("PERPLEXITY_MODEL", "perplexity/sonar-pro")

# Paths (all relative to project root)
PROJECT_ROOT: Path = _PROJECT_ROOT
GENRES_DIR: Path = _PROJECT_ROOT / "genres"
PROJECTS_DIR: Path = _PROJECT_ROOT / "projects"
ACTIVE_POINTER: Path = PROJECTS_DIR / ".active"

RULES_DIR: Path = _PROJECT_ROOT / "rules"
DOCS_DIR: Path = _PROJECT_ROOT / "docs"


def get_active_project_id() -> str | None:
    """Return the id of the active project, or None if nothing is active."""
    if not ACTIVE_POINTER.exists():
        return None
    try:
        name = ACTIVE_POINTER.read_text(encoding="utf-8").strip()
        return name or None
    except OSError:
        return None


def set_active_project_id(project_id: str) -> None:
    """Atomically mark a project as active. Raises if project dir doesn't exist."""
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise FileNotFoundError(f"Project not found: {project_dir}")
    ACTIVE_POINTER.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_POINTER.write_text(project_id + "\n", encoding="utf-8")


def active_project_dir() -> Path | None:
    pid = get_active_project_id()
    return PROJECTS_DIR / pid if pid else None


def active_state_dir() -> Path:
    """Resolve STATE_DIR dynamically. Priority:
      1. Explicit STATE_DIR env override (for hosted read-only demos)
      2. Active project's state/ subdir (the normal case)
      3. Legacy top-level `state/` directory (for pre-refactor snapshots)
    """
    env_override = os.environ.get("STATE_DIR")
    if env_override:
        return Path(env_override)
    pd = active_project_dir()
    if pd:
        return pd / "state"
    return _PROJECT_ROOT / "state"  # legacy fallback


# Eagerly resolve at import time. Most callers read this value once; the few
# that need live reload (e.g. Web UI when switching project) call
# refresh_state_dir() after a bootstrap.
STATE_DIR: Path = active_state_dir()

# Ensure state directory and its well-known subdirs exist at import
for sub in ("", "chapters", "summaries", "fixes"):
    (STATE_DIR / sub).mkdir(parents=True, exist_ok=True)


def refresh_state_dir() -> Path:
    """Re-resolve STATE_DIR after a project switch. Returns the new path.

    Agents and Blackboard instances created BEFORE the refresh will keep
    pointing at the previous root. Callers who need live reload (Web UI)
    should rebuild their Blackboard with the new root.
    """
    global STATE_DIR
    STATE_DIR = active_state_dir()
    for sub in ("", "chapters", "summaries", "fixes"):
        (STATE_DIR / sub).mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def reload_env() -> None:
    """Re-read .env and update module-level LLM/Perplexity config globals.

    Safe to call from the Web UI after writing new keys. Because llm.py and
    websearch.py always dereference `config.X` at call time (not at import),
    updates take effect on the next LLM call in the same process.
    """
    global LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
    global PERPLEXITY_API_KEY, PERPLEXITY_BASE_URL, PERPLEXITY_MODEL

    load_dotenv(_PROJECT_ROOT / ".env", override=True)
    LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    LLM_BASE_URL = os.environ.get(
        "DEEPSEEK_BASE_URL", "https://work-api-srv.easyclaw.cn/v1"
    ).rstrip("/")
    LLM_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")
    PERPLEXITY_BASE_URL = os.environ.get(
        "PERPLEXITY_BASE_URL", "https://work-api-srv.easyclaw.cn/api/v1/search"
    ).rstrip("/")
    PERPLEXITY_MODEL = os.environ.get("PERPLEXITY_MODEL", "perplexity/sonar-pro")


def assert_llm_configured() -> None:
    """Raise a helpful error early if the API key is missing."""
    if not LLM_API_KEY or LLM_API_KEY.startswith("dc-sk-put-yours"):
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not configured. Copy .env.example to .env "
            "and fill in your key from the EasyClaw platform."
        )
