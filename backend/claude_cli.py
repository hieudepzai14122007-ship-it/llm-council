"""Claude Code CLI client: runs council models on the user's Claude subscription quota.

Drop-in replacement for openrouter.py. Each call runs `claude -p` headless with no tools,
so the model just answers the prompt.
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

from .config import CLAUDE_MAX_CONCURRENT

CLAUDE_BIN = shutil.which("claude") or "claude"

# Council members must not see any project instructions: run from an empty folder outside
# this repo (the CLI looks for CLAUDE.md in every parent folder) and turn CLAUDE.md loading off.
_WORKDIR = Path(tempfile.gettempdir()) / "llm-council-claude"
_ENV = {**os.environ, "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}

# Without --system-prompt the CLI sends its full coding-agent prompt (~6k tokens) on every call.
DEFAULT_SYSTEM_PROMPT = "You are a helpful, knowledgeable assistant. Answer clearly and accurately."

_semaphore: Optional[asyncio.Semaphore] = None


def _flatten(messages: List[Dict[str, str]]) -> str:
    """Turn a chat message list into one prompt (the CLI takes a single prompt)."""
    if len(messages) == 1:
        return messages[0]["content"]
    return "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)


def _run_cli(model: str, prompt: str, system_prompt: Optional[str], timeout: float) -> Dict[str, Any]:
    _WORKDIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        CLAUDE_BIN, "-p",
        "--model", model,
        "--output-format", "json",
        "--tools", "",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--system-prompt", system_prompt or DEFAULT_SYSTEM_PROMPT,
    ]
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        cwd=_WORKDIR,
        env=_ENV,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}")
    data = json.loads(proc.stdout)
    if data.get("is_error"):
        raise RuntimeError(f"claude error: {data.get('result')}")
    return data


def _usage(model: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Token counts and the CLI's API-list-price cost estimate for one call."""
    u = data.get("usage") or {}
    return {
        "model": model,
        "calls": 1,
        "input_tokens": (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                         + u.get("cache_creation_input_tokens", 0)),
        "output_tokens": u.get("output_tokens", 0),
        "cost_usd": data.get("total_cost_usd") or 0.0,
    }


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 300.0,
    system_prompt: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Query a single Claude model through the Claude Code CLI.

    Args:
        model: Claude model alias or id (e.g., "opus", "sonnet", "haiku")
        messages: List of message dicts with 'role' and 'content'
        timeout: Seconds before the call is abandoned
        system_prompt: Optional role / persona for this call

    Returns:
        Response dict with 'content', 'reasoning_details' and 'usage', or None if failed
    """
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(CLAUDE_MAX_CONCURRENT)

    try:
        async with _semaphore:
            # A thread rather than asyncio subprocesses, which need a Proactor loop on Windows.
            data = await asyncio.to_thread(_run_cli, model, _flatten(messages), system_prompt, timeout)
        return {"content": data.get("result", ""), "reasoning_details": None, "usage": _usage(model, data)}
    except Exception as e:
        print(f"Error querying model {model}: {e}")
        return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]]
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of Claude model aliases
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    tasks = [query_model(model, messages) for model in models]
    responses = await asyncio.gather(*tasks)
    return {model: response for model, response in zip(models, responses)}
