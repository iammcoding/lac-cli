"""
server/router.py
────────────────
Routes AI completion requests to the correct provider.

Supports:
  - claude    → Anthropic API (streaming)
  - openai    → OpenAI API (streaming)
  - ollama    → local Ollama (streaming)
  - custom    → any OpenAI-compatible endpoint

Each router function is an async generator that yields string tokens.
"""

import httpx
import json
from typing import AsyncIterator

# ── System prompt shared across all providers ────────────────────────────────
COMPLETION_SYSTEM = """You are a terminal autocomplete engine.
Given the user's partial command and their recent shell history, predict and complete the command.
Rules:
- Reply with ONLY the completed command, nothing else
- No explanation, no markdown, no punctuation outside the command
- Keep it as short and accurate as possible
- If uncertain, complete with the most common/safe version"""

NL_SYSTEM = """You are a natural language to shell command converter.
The user types in plain English — you return ONLY the shell command.
Rules:
- Reply with ONLY the shell command, nothing else
- No explanation, no markdown, no extra text
- Use safe flags (avoid -rf unless clearly needed)
- Prefer portable POSIX commands"""


def _build_prompt(text: str, history: list[str], cwd: str, mode: str) -> str:
    """Build the prompt string sent to the AI."""
    history_str = "\n".join(history[:10]) if history else "none"
    if mode == "complete":
        return (
            f"Current directory: {cwd}\n"
            f"Recent commands:\n{history_str}\n\n"
            f"Complete this command: {text}"
        )
    else:  # nl_command
        return (
            f"Current directory: {cwd}\n"
            f"Recent commands:\n{history_str}\n\n"
            f"Convert to shell command: {text}"
        )


# ── Claude (Anthropic) ───────────────────────────────────────────────────────

async def claude_stream(
    text: str,
    history: list[str],
    cwd: str,
    mode: str,
    api_key: str,
    model: str,
    base_url: str,
) -> AsyncIterator[str]:
    """Stream completions from Anthropic's API."""

    system = COMPLETION_SYSTEM if mode == "complete" else NL_SYSTEM
    prompt = _build_prompt(text, history, cwd, mode)

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "accept": "text/event-stream",
    }
    body = {
        "model": model,
        "max_tokens": 150,
        "stream": True,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream(
            "POST",
            f"{base_url}/v1/messages",
            headers=headers,
            json=body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    # Anthropic SSE format
                    if data.get("type") == "content_block_delta":
                        token = data["delta"].get("text", "")
                        if token:
                            yield token
                except json.JSONDecodeError:
                    continue


# ── OpenAI (and OpenAI-compatible) ───────────────────────────────────────────

async def openai_stream(
    text: str,
    history: list[str],
    cwd: str,
    mode: str,
    api_key: str,
    model: str,
    base_url: str,
) -> AsyncIterator[str]:
    """Stream completions from OpenAI or any compatible endpoint."""

    system = COMPLETION_SYSTEM if mode == "complete" else NL_SYSTEM
    prompt = _build_prompt(text, history, cwd, mode)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 150,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers=headers,
            json=body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    token = (
                        data.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if token:
                        yield token
                except json.JSONDecodeError:
                    continue


# ── Ollama ───────────────────────────────────────────────────────────────────

async def ollama_stream(
    text: str,
    history: list[str],
    cwd: str,
    mode: str,
    model: str,
    base_url: str,
) -> AsyncIterator[str]:
    """Stream completions from local Ollama instance."""

    system = COMPLETION_SYSTEM if mode == "complete" else NL_SYSTEM
    prompt = _build_prompt(text, history, cwd, mode)

    body = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            f"{base_url}/api/chat",
            json=body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue


# ── Unified router ────────────────────────────────────────────────────────────

async def route(
    provider: str,
    text: str,
    history: list[str],
    cwd: str,
    mode: str,        # "complete" | "nl_command"
    api_key: str,
    model: str,
    base_url: str,
) -> AsyncIterator[str]:
    """
    Route a request to the correct provider.

    Args:
        provider:  "claude" | "openai" | "ollama" | "custom"
        text:      user's partial input
        history:   recent command history
        cwd:       current working directory
        mode:      "complete" for autocomplete, "nl_command" for NL→cmd
        api_key:   provider api key
        model:     model identifier
        base_url:  provider base url

    Yields:
        string tokens from the AI
    """
    if provider == "claude":
        async for token in claude_stream(text, history, cwd, mode, api_key, model, base_url):
            yield token

    elif provider in ("openai", "custom"):
        async for token in openai_stream(text, history, cwd, mode, api_key, model, base_url):
            yield token

    elif provider == "ollama":
        async for token in ollama_stream(text, history, cwd, mode, model, base_url):
            yield token

    else:
        raise ValueError(f"Unknown provider: {provider}")
