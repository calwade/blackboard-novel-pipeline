"""LLM client — OpenAI-compatible Chat Completions against DeepSeek-V4-Pro.

Every successful call appends a structured record to state/prompts_log.jsonl
so the Web UI's Prompt Inspector can show "each agent call is fresh context,
here's exactly what was sent and what came back". This is the UI affordance
that converts our architecture claims into visible evidence.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Literal

import httpx

from . import config

# We reuse a single httpx client for connection pooling.
# Read timeout is long because Generator can take 2-4 minutes for 3000-char
# Chinese chapters. We trust the server's own timeout to cut us off if it dies.
_client = httpx.Client(timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0))

def _prompts_log_path():
    """Resolve at call time so it follows project switches."""
    return config.STATE_DIR / "prompts_log.jsonl"


def _log_call(entry: dict) -> None:
    """Append one call record to the prompt log. Atomic-append via open('a')."""
    log_path = _prompts_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def chat(
    system: str,
    user: str,
    *,
    agent_name: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: Literal["text", "json"] = "text",
    inputs_read: list[str] | None = None,
) -> str:
    """Send a chat completion request. Returns the raw assistant text.

    Args:
        system: system prompt
        user: user prompt
        agent_name: for logging (e.g., 'planner', 'generator')
        temperature: sampling
        max_tokens: server-side cap
        response_format: 'json' forces JSON mode when supported
        inputs_read: optional list of state/ file paths this agent read,
                     purely for logging transparency.

    Raises:
        httpx.HTTPError on transport error.
        RuntimeError on non-2xx with provider error body.
    """
    config.assert_llm_configured()

    call_id = str(uuid.uuid4())
    started_at = time.time()

    payload: dict = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format == "json":
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    url = f"{config.LLM_BASE_URL}/chat/completions"
    resp = _client.post(url, headers=headers, json=payload)
    latency_ms = int((time.time() - started_at) * 1000)

    if resp.status_code >= 400:
        err_body = resp.text
        _log_call(
            {
                "id": call_id,
                "ts": started_at,
                "agent_name": agent_name,
                "system": system,
                "user": user,
                "inputs_read": inputs_read or [],
                "model": config.LLM_MODEL,
                "temperature": temperature,
                "response_format": response_format,
                "latency_ms": latency_ms,
                "output": None,
                "usage": None,
                "error": f"HTTP {resp.status_code}: {err_body[:500]}",
            }
        )
        raise RuntimeError(f"LLM call failed ({resp.status_code}): {err_body[:500]}")

    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})

    _log_call(
        {
            "id": call_id,
            "ts": started_at,
            "agent_name": agent_name,
            "system": system,
            "user": user,
            "inputs_read": inputs_read or [],
            "model": config.LLM_MODEL,
            "temperature": temperature,
            "response_format": response_format,
            "latency_ms": latency_ms,
            "output": text,
            "usage": usage,
            "error": None,
        }
    )
    return text


def smoke_test() -> str:
    """Quick connectivity sanity check."""
    return chat(
        system="You are a terse assistant.",
        user="说一句中文，然后报出你是哪个模型。",
        agent_name="__smoke__",
        temperature=0.0,
        max_tokens=120,
    )


if __name__ == "__main__":
    print(smoke_test())
