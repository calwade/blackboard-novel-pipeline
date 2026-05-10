"""Websearch tool — on-demand Perplexity Sonar queries.

Architecture decision (skill #20 "不主动联网，按需核查"):
  The creative pipeline (Planner/Generator/Summarizer) has zero internet
  access — worldbuilding facts come from setting pack era.md / timeline.yaml
  that were pre-loaded offline. This keeps plan→prose reproducible.

  BUT, when Evaluator suspects a reality-drift (landmine_13: world/era
  detail looks wrong) and its own evidence is weak, we let the FactChecker
  auditor fire ONE websearch per chapter to cross-check. The result lands
  in state/fixes/ch{N}.fact-patch.md — a read-only artifact, not a pass/
  fail gate. Fixer can consume the patch in its next retry.

  One-shot per chapter, not per-sentence — Pages/Claude/Cognition all warn
  against on-the-fly search loops (Lesson 3: context anxiety). A cached
  one-shot keeps costs bounded and the agent's context Reset-friendly.

Config (via .env or env vars):
  PERPLEXITY_API_KEY   — OpenAI-compat bearer token (required)
  PERPLEXITY_BASE_URL  — defaults to https://work-api-srv.easyclaw.cn/api/v1/search
  PERPLEXITY_MODEL     — defaults to perplexity/sonar-pro

  Absent API key → `search()` raises WebSearchUnavailable; callers treat
  as "degraded gracefully" (no fact-patch produced, Evaluator proceeds).

Every call is logged to state/websearch_log.jsonl (schema analogous to
prompts_log.jsonl) so the Web UI Prompt Inspector can surface it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .. import config


# Shared client for pooling; long read timeout because Sonar synthesizes
# ~3000-token responses with multiple citation round-trips.
_client = httpx.Client(
    timeout=httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
)

WEBSEARCH_LOG_PATH = config.STATE_DIR / "websearch_log.jsonl"

# Optional tiny file-backed cache — avoid double-billing identical queries
# within the same setting. Keyed by md5(query + model). Cache invalidation:
# manual — delete state/websearch_cache/ to re-fetch.
_CACHE_DIR = config.STATE_DIR / "websearch_cache"


class WebSearchUnavailable(RuntimeError):
    """Raised when PERPLEXITY_API_KEY is missing or the endpoint is unreachable.

    Callers should catch this and degrade gracefully (e.g., FactChecker
    skips the patch for this chapter rather than failing the whole run).
    """


@dataclass
class SearchResult:
    query: str
    content: str                          # natural-language summary with inline cite markers
    citations: list[str] = field(default_factory=list)   # list of URLs
    model: str = ""
    latency_ms: int = 0
    cached: bool = False

    def as_markdown(self) -> str:
        """Render for embedding in a fact-patch.md."""
        lines = [f"**查询**：{self.query}", ""]
        lines.append(f"**结果**（{self.model}{' · cached' if self.cached else ''}）：")
        lines.append("")
        lines.append(self.content.strip())
        if self.citations:
            lines.append("")
            lines.append("**来源**：")
            for i, u in enumerate(self.citations, 1):
                lines.append(f"{i}. {u}")
        return "\n".join(lines)


def _log_call(entry: dict) -> None:
    """Append one websearch call record. Atomic-append via open('a')."""
    WEBSEARCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WEBSEARCH_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _cache_key(query: str, model: str) -> str:
    h = hashlib.md5(f"{model}::{query}".encode("utf-8")).hexdigest()
    return h


def _cache_read(query: str, model: str) -> SearchResult | None:
    p = _CACHE_DIR / (_cache_key(query, model) + ".json")
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return SearchResult(
        query=obj.get("query", query),
        content=obj.get("content", ""),
        citations=obj.get("citations", []) or [],
        model=obj.get("model", model),
        latency_ms=obj.get("latency_ms", 0),
        cached=True,
    )


def _cache_write(result: SearchResult) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _CACHE_DIR / (_cache_key(result.query, result.model) + ".json")
    p.write_text(
        json.dumps(
            {
                "query": result.query,
                "content": result.content,
                "citations": result.citations,
                "model": result.model,
                "latency_ms": result.latency_ms,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def is_available() -> bool:
    """Cheap preflight check — no network call, just config presence."""
    key = os.environ.get("PERPLEXITY_API_KEY") or getattr(config, "PERPLEXITY_API_KEY", "")
    return bool(key)


def search(
    query: str,
    *,
    agent_name: str = "fact_checker",
    system_hint: str | None = None,
    use_cache: bool = True,
    max_tokens: int = 2000,
) -> SearchResult:
    """Run ONE Perplexity query. Logged to websearch_log.jsonl.

    Args:
        query: the factual question in plain Chinese/English.
        agent_name: for logging (usually 'fact_checker').
        system_hint: optional extra system prompt. Default is a terse
            instruction to answer with facts + sources, not chat.
        use_cache: if True, hit the file cache first.
        max_tokens: server-side response cap.

    Raises:
        WebSearchUnavailable if no API key.
        RuntimeError on non-2xx from the endpoint.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY") or getattr(config, "PERPLEXITY_API_KEY", "")
    if not api_key:
        raise WebSearchUnavailable(
            "PERPLEXITY_API_KEY not configured. Add it to .env or export it. "
            "FactChecker will skip this chapter."
        )

    base_url = (
        os.environ.get("PERPLEXITY_BASE_URL")
        or getattr(config, "PERPLEXITY_BASE_URL", "")
        or "https://work-api-srv.easyclaw.cn/api/v1/search"
    ).rstrip("/")
    model = (
        os.environ.get("PERPLEXITY_MODEL")
        or getattr(config, "PERPLEXITY_MODEL", "")
        or "perplexity/sonar-pro"
    )

    if use_cache:
        cached = _cache_read(query, model)
        if cached:
            _log_call(
                {
                    "id": str(uuid.uuid4()),
                    "ts": time.time(),
                    "agent_name": agent_name,
                    "model": model,
                    "query": query,
                    "cached": True,
                    "latency_ms": 0,
                    "content_excerpt": cached.content[:300],
                    "citation_count": len(cached.citations),
                    "error": None,
                }
            )
            return cached

    call_id = str(uuid.uuid4())
    started_at = time.time()

    system_prompt = system_hint or (
        "你是一个严谨的事实核查员。针对用户查询，用简体中文给出**以事实为主、可查证**"
        "的回答；回答末尾列出 URL 来源；**不要臆测**；若资料不足请直说『资料不足』。"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = f"{base_url}/chat/completions"
    try:
        resp = _client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as e:
        _log_call(
            {
                "id": call_id,
                "ts": started_at,
                "agent_name": agent_name,
                "model": model,
                "query": query,
                "cached": False,
                "latency_ms": int((time.time() - started_at) * 1000),
                "content_excerpt": "",
                "citation_count": 0,
                "error": f"{type(e).__name__}: {e}",
            }
        )
        raise WebSearchUnavailable(f"network error: {e}") from e

    latency_ms = int((time.time() - started_at) * 1000)

    if resp.status_code >= 400:
        err_body = resp.text[:500]
        _log_call(
            {
                "id": call_id,
                "ts": started_at,
                "agent_name": agent_name,
                "model": model,
                "query": query,
                "cached": False,
                "latency_ms": latency_ms,
                "content_excerpt": "",
                "citation_count": 0,
                "error": f"HTTP {resp.status_code}: {err_body}",
            }
        )
        raise RuntimeError(f"websearch failed ({resp.status_code}): {err_body}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        _log_call(
            {
                "id": call_id,
                "ts": started_at,
                "agent_name": agent_name,
                "model": model,
                "query": query,
                "cached": False,
                "latency_ms": latency_ms,
                "content_excerpt": "",
                "citation_count": 0,
                "error": f"bad response shape: {e}; raw={json.dumps(data)[:200]}",
            }
        )
        raise RuntimeError(f"websearch returned unexpected shape: {data}") from e

    citations = data.get("citations") or []
    if not isinstance(citations, list):
        citations = []

    result = SearchResult(
        query=query,
        content=content,
        citations=[str(c) for c in citations],
        model=model,
        latency_ms=latency_ms,
        cached=False,
    )

    _log_call(
        {
            "id": call_id,
            "ts": started_at,
            "agent_name": agent_name,
            "model": model,
            "query": query,
            "cached": False,
            "latency_ms": latency_ms,
            "content_excerpt": content[:300],
            "citation_count": len(result.citations),
            "error": None,
        }
    )

    if use_cache:
        try:
            _cache_write(result)
        except OSError:
            pass  # cache is an optimization, not a hard dep

    return result


def smoke_test() -> SearchResult:
    """Quick connectivity check; requires PERPLEXITY_API_KEY."""
    return search(
        query="1983年9月24日 香港黑色星期六 港元汇率是多少",
        agent_name="__smoke__",
        max_tokens=500,
    )


if __name__ == "__main__":
    r = smoke_test()
    print(f"[{r.latency_ms} ms · {len(r.citations)} citations]")
    print(r.as_markdown()[:400])
