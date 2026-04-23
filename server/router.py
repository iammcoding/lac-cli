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

import re
import httpx
import json
from typing import AsyncIterator

# ── System prompt shared across all providers ────────────────────────────────
COMPLETION_SYSTEM = """You are a terminal autocomplete engine.
Given the user's partial command and their recent shell history, predict and complete the command.
Rules:
- Reply with ONLY the completed command, nothing else
- No explanation, no markdown, no backticks, no punctuation outside the command
- Keep it as short and accurate as possible
- If uncertain, complete with the most common/safe version"""

NL_SYSTEM = """You are a natural language to shell command converter.
The user types in plain English — you return ONLY the shell command.
Rules:
- Reply with ONLY the shell command, nothing else
- No explanation, no markdown, no backticks, no extra text
- Use safe flags (avoid -rf unless clearly needed)
- Prefer portable POSIX commands"""


# ── Output cleaner ────────────────────────────────────────────────────────────

def clean_command(text: str) -> str:
    """
    Strip all markdown/code-block artifacts from AI output.

    Handles:
      - ```bash\\n...\\n```   (fenced code blocks with language tag)
      - ```\\n...\\n```        (fenced code blocks without tag)
      - `single backtick`    (inline code)
      - leading/trailing whitespace and newlines
      - ANSI escape codes (just in case)
    """
    t = text.strip()

    # Remove fenced code block wrappers: ```[lang]\n...\n```
    t = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", t)
    t = re.sub(r"\n?```$", "", t)

    # Remove inline backticks: `command`
    t = re.sub(r"`([^`]*)`", r"\1", t)

    # Remove any remaining stray backticks
    t = t.replace("`", "")

    # Strip ANSI escape codes
    t = re.sub(r"\x1b\[[0-9;]*m", "", t)

    # Collapse multiple newlines into one, then strip
    t = re.sub(r"\n{2,}", "\n", t)

    return t.strip()


def _build_prompt(text: str, history: list[str], session: list[dict], cwd: str, mode: str) -> str:
    """Build the prompt string sent to the AI."""
    history_str = "\n".join(history[:10]) if history else "none"

    session_str = ""
    if session:
        session_lines = []
        for entry in session[-10:]:
            session_lines.append(f"$ {entry['cmd']}")
            if entry.get("output"):
                session_lines.append(entry["output"][:500])
        session_str = "\n".join(session_lines)

    session_context = f"Session context:\n{session_str}\n\n" if session_str else ""

    if mode == "complete":
        return (
            f"Current directory: {cwd}\n"
            f"Recent commands:\n{history_str}\n\n"
            f"{session_context}"
            f"Complete this command: {text}"
        )
    else:  # nl_command
        return (
            f"Current directory: {cwd}\n"
            f"Recent commands:\n{history_str}\n\n"
            f"{session_context}"
            f"Convert to shell command: {text}"
        )


# ── Streaming helpers ─────────────────────────────────────────────────────────

async def _yield_cleaned(raw_stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """
    Collect full response from any provider stream, clean it, then
    re-yield it as a single chunk.

    Why collect first instead of cleaning token by token?
    Backtick wrappers like ```bash\\n...\\n``` span multiple tokens —
    you can't clean them mid-stream without buffering anyway.
    """
    buffer = ""
    async for token in raw_stream:
        buffer += token

    cleaned = clean_command(buffer)
    if cleaned:
        yield cleaned


# ── Claude (Anthropic) ───────────────────────────────────────────────────────

async def claude_stream(
    text: str,
    history: list[str],
    session: list[dict],
    cwd: str,
    mode: str,
    api_key: str,
    model: str,
    base_url: str,
) -> AsyncIterator[str]:
    system = COMPLETION_SYSTEM if mode == "complete" else NL_SYSTEM
    prompt = _build_prompt(text, history, session, cwd, mode)

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
    session: list[dict],
    cwd: str,
    mode: str,
    api_key: str,
    model: str,
    base_url: str,
) -> AsyncIterator[str]:
    system = COMPLETION_SYSTEM if mode == "complete" else NL_SYSTEM
    prompt = _build_prompt(text, history, session, cwd, mode)

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
    session: list[dict],
    cwd: str,
    mode: str,
    model: str,
    base_url: str,
) -> AsyncIterator[str]:
    system = COMPLETION_SYSTEM if mode == "complete" else NL_SYSTEM
    prompt = _build_prompt(text, history, session, cwd, mode)

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
    session: list[dict],
    cwd: str,
    mode: str,        # "complete" | "nl_command"
    api_key: str,
    model: str,
    base_url: str,
) -> AsyncIterator[str]:
    """
    Route a request to the correct provider, clean the output, and yield tokens.

    Args:
        provider:  "claude" | "openai" | "ollama" | "custom"
        text:      user's partial input
        history:   recent command history
        session:   recent commands + outputs [{cmd: str, output: str}]
        cwd:       current working directory
        mode:      "complete" for autocomplete, "nl_command" for NL→cmd
        api_key:   provider api key
        model:     model identifier
        base_url:  provider base url

    Yields:
        cleaned string tokens (backticks and markdown removed)
    """
    if provider == "claude":
        raw = claude_stream(text, history, session, cwd, mode, api_key, model, base_url)

    elif provider in ("openai", "custom"):
        raw = openai_stream(text, history, session, cwd, mode, api_key, model, base_url)

    elif provider == "ollama":
        raw = ollama_stream(text, history, session, cwd, mode, model, base_url)

    else:
        raise ValueError(f"Unknown provider: {provider}")

    async for token in _yield_cleaned(raw):
        yield token