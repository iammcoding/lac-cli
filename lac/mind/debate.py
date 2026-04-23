"""
lac/mind/debate.py
──────────────────
Debate engine.

Flow per round:
  - Each model receives the full thread so far (sequential)
  - Streams tokens live via WS broadcast
  - Confidence extracted from model's response
  - Repeat until timer expires

On time up:
  - All models get the full thread + "vote who should summarize"
  - Model with most votes writes the consensus summary
"""

import asyncio
import json
import re
import litellm
import logging
from typing import AsyncIterator, Callable
from lac.mind.models import to_litellm_model

log = logging.getLogger("lacmind.debate")
log.setLevel(logging.DEBUG)

DEBATE_SYSTEM = """You are participating in a multi-model AI debate.
You will receive a prompt and the debate thread so far.
Read what the other models said carefully.

ONLY use SKIP_DEBATE if the prompt is a pure greeting (hi, hello, thanks) with no actual question or request.
For everything else, engage in the debate even if the prompt seems vague - use context from conversation history to understand intent.

If you determine debate should be skipped, respond with:
SKIP_DEBATE: [brief explanation]
CONFIDENCE: 1.0

Otherwise, respond by agreeing, challenging, or updating your position based on the content.
Be direct and concise. Reference specific points when you disagree.
At the end of your response, on a new line write exactly: CONFIDENCE: 0.XX
where 0.XX is your confidence in the current consensus (0.0 = no consensus, 1.0 = full agreement)."""

VOTE_SYSTEM = """The debate time is up. Read the full thread.
Based on the quality of reasoning shown, vote for which model should deliver the final consensus summary.
Write: VOTE: <model_name>
Then one sentence explaining why based on their arguments."""

SUMMARY_SYSTEM = """You have been selected to deliver the final response.
Read the full debate thread and conversation history to understand context.
Deliver what the user asked for based on the context.
If they asked for code, provide complete working code.
If they asked for research or information, provide detailed explanation.
If the prompt references previous conversation (like 'i said research' or 'how it was founded'), use the conversation history to understand what they're referring to.
Do not summarize the debate — deliver the actual work product the user requested.
Be thorough and complete."""


def _build_thread_context(thread: list[dict]) -> str:
    lines = []
    for entry in thread:
        lines.append(f"[{entry['model_name']}]: {entry['content']}")
    return "\n\n".join(lines)


async def stream_model_response(
    model_cfg: dict,
    system: str,
    prompt: str,
    on_token: Callable[[str], None],
) -> str:
    """Stream a model response using LiteLLM. Returns full text."""
    log.info(f"Streaming from {model_cfg['name']} ({model_cfg.get('provider')})")
    full = []
    try:
        response = await litellm.acompletion(
            model=to_litellm_model(model_cfg),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            stream=True,
            api_key=model_cfg.get("api_key") or None,
            api_base=model_cfg.get("base_url") if model_cfg.get("provider") in ("ollama", "custom") else None,
            max_tokens=4000,
        )
        async for chunk in response:
            token = chunk.choices[0].delta.content or ""
            if token:
                full.append(token)
                on_token(token)
    except Exception as e:
        log.error(f"Error streaming from {model_cfg['name']}: {e}")
        error_msg = f"\n[error: {e}]"
        full.append(error_msg)
        on_token(error_msg)

    result = "".join(full)
    log.debug(f"Stream complete: {len(result)} chars")
    return result


def extract_confidence(text: str) -> float:
    match = re.search(r"CONFIDENCE:\s*(0?\.\d+|1\.0|0|1)", text, re.IGNORECASE)
    if match:
        try:
            return max(0.0, min(1.0, float(match.group(1))))
        except ValueError:
            pass
    return 0.5


def should_skip_debate(text: str) -> bool:
    """Check if models want to skip debate for simple prompts"""
    return "SKIP_DEBATE:" in text


def extract_vote(text: str) -> str:
    match = re.search(r"VOTE:\s*(.+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


async def run_debate(
    prompt: str,
    models: list[dict],
    duration_seconds: int,
    broadcast: Callable[[dict], None],
    stop_event: asyncio.Event = None,
    conversation_history: list[dict] = None,
):
    """
    Main debate loop.
    - Sequential rounds within the time window
    - On timeout: vote round → summary round
    Returns consensus summary string.
    """
    log.info(f"Starting debate with {len(models)} models, duration={duration_seconds}s")
    thread = []

    # Quick check: if prompt is very short and casual, skip debate entirely
    prompt_lower = prompt.lower().strip()

    is_pure_greeting = (
        prompt_lower in ['hi', 'hello', 'hey', 'sup', 'yo', 'thanks', 'thank you', 'ok', 'okay', 'bye', 'goodbye'] or
        (len(prompt_lower.split()) <= 2 and prompt_lower.split()[0] in ['hi', 'hello', 'hey'])
    )

    if is_pure_greeting:
        log.info(f"Detected casual greeting/response, skipping debate: {prompt}")
        await broadcast({"type": "debate_start", "prompt": prompt, "duration": duration_seconds, "models": [m["name"] for m in models]})
        await broadcast({"type": "time_up"})

        winner_cfg = models[0]
        winner_name = models[0]["name"]
        await broadcast({"type": "winner", "model": winner_name, "votes": {}})

        summary_prompt = f"{prompt}\n\nProvide a brief, friendly response:"
        summary_tokens = []

        def on_summary_token(token: str):
            summary_tokens.append(token)
            asyncio.create_task(broadcast({"type": "token", "model": winner_name, "token": token, "phase": "summary"}))

        summary = await stream_model_response(winner_cfg, SUMMARY_SYSTEM, summary_prompt, on_summary_token)
        await broadcast({"type": "consensus", "summary": summary, "delivered_by": winner_name})
        return summary, thread

    # Reserve time for voting and summary
    voting_time = len(models) * 10
    summary_time = 15
    debate_time = max(10, duration_seconds - voting_time - summary_time)

    deadline = asyncio.get_event_loop().time() + debate_time
    log.info(f"Debate time: {debate_time}s, Voting: {voting_time}s, Summary: {summary_time}s")

    # Build conversation context from history
    conversation_context = ""
    if conversation_history:
        history_lines = []
        for entry in conversation_history:
            history_lines.append(f"User: {entry['question']}")
            history_lines.append(f"Assistant: {entry['answer']}")
        conversation_context = "\n\n".join(history_lines) + "\n\n"

    model_labels = {m["name"]: f"Model {chr(65 + i)}" for i, m in enumerate(models)}
    log.debug(f"Model labels: {model_labels}")

    round_num = 0
    skip_debate = False

    while asyncio.get_event_loop().time() < deadline and not skip_debate:
        if stop_event and stop_event.is_set():
            log.info("Stop event triggered, ending debate early")
            break

        round_num += 1
        log.info(f"Round {round_num} starting")
        await broadcast({"type": "round_start", "round": round_num})

        for model_cfg in models:
            if asyncio.get_event_loop().time() >= deadline:
                break

            if stop_event and stop_event.is_set():
                break

            label = model_labels[model_cfg["name"]]
            log.debug(f"Model {model_cfg['name']} ({label}) starting turn")
            thread_context = _build_thread_context([
                {**e, "model_name": model_labels.get(e["model_name"], e["model_name"])}
                for e in thread
            ])

            if thread_context:
                user_prompt = f"{conversation_context}Current question: {prompt}\n\nDebate so far:\n{thread_context}\n\nYour response:"
            else:
                user_prompt = f"{conversation_context}Current question: {prompt}\n\nYou go first. Share your analysis:"

            await broadcast({"type": "model_start", "model": model_cfg["name"], "label": label, "round": round_num})
            log.debug(f"Sent model_start for {model_cfg['name']}")

            tokens_buffer = []

            def on_token(token: str, name=model_cfg["name"], lbl=label):
                tokens_buffer.append(token)
                log.debug(f"Token from {name}: {repr(token[:20])}")
                asyncio.create_task(broadcast({"type": "token", "model": name, "label": lbl, "token": token}))

            full_response = await stream_model_response(model_cfg, DEBATE_SYSTEM, user_prompt, on_token)
            log.info(f"Model {model_cfg['name']} completed response: {len(full_response)} chars")

            if round_num == 1 and should_skip_debate(full_response):
                log.info(f"Model {model_cfg['name']} requested to skip debate in round 1")
                skip_debate = True

            confidence = extract_confidence(full_response)
            log.debug(f"Extracted confidence: {confidence}")

            thread.append({"model_name": model_cfg["name"], "content": full_response, "confidence": confidence})

            await broadcast({
                "type": "model_done",
                "model": model_cfg["name"],
                "label": label,
                "confidence": confidence,
                "round": round_num,
            })

            if skip_debate:
                break

        if not skip_debate:
            await asyncio.sleep(0.5)

    # ── Time up: vote round ───────────────────────────────────────────────────
    await broadcast({"type": "time_up"})

    if skip_debate:
        log.info("Debate skipped, selecting first model for summary")
        winner_cfg = models[0]
        winner_name = models[0]["name"]
        await broadcast({"type": "winner", "model": winner_name, "votes": {}})
    else:
        thread_context = _build_thread_context([
            {**e, "model_name": model_labels.get(e["model_name"], e["model_name"])}
            for e in thread
        ])
        vote_prompt = f"{conversation_context}Current question: {prompt}\n\nFull debate:\n{thread_context}\n\nWho should summarize?"

        votes: dict[str, int] = {}
        vote_reasons: dict[str, str] = {}

        for model_cfg in models:
            label = model_labels[model_cfg["name"]]
            await broadcast({"type": "voting", "model": model_cfg["name"], "label": label})

            vote_tokens = []

            def on_vote_token(token: str, name=model_cfg["name"], lbl=label):
                vote_tokens.append(token)
                asyncio.create_task(broadcast({"type": "token", "model": name, "label": lbl, "token": token, "phase": "vote"}))

            vote_text = await stream_model_response(model_cfg, VOTE_SYSTEM, vote_prompt, on_vote_token)
            voted_for = extract_vote(vote_text)

            if voted_for:
                votes[voted_for] = votes.get(voted_for, 0) + 1
                vote_reasons[voted_for] = vote_text

            await broadcast({"type": "vote_cast", "model": model_cfg["name"], "voted_for": voted_for})

        if votes:
            winner_name = max(votes, key=lambda k: (votes[k], next(
                (e["confidence"] for e in reversed(thread) if e["model_name"] == k), 0
            )))
        else:
            winner_name = max(thread, key=lambda e: e["confidence"])["model_name"]

        winner_cfg = next((m for m in models if m["name"] == winner_name), models[0])
        await broadcast({"type": "winner", "model": winner_name, "votes": votes})

    # ── Summary round ─────────────────────────────────────────────────────────
    if skip_debate:
        summary_prompt = f"{conversation_context}Current question: {prompt}\n\nThis prompt doesn't require debate. Provide a brief, direct response:"
    else:
        thread_context = _build_thread_context([
            {**e, "model_name": model_labels.get(e["model_name"], e["model_name"])}
            for e in thread
        ])
        summary_prompt = f"{conversation_context}Current question: {prompt}\n\nFull debate:\n{thread_context}\n\nDeliver the consensus summary:"

    summary_tokens = []

    def on_summary_token(token: str):
        summary_tokens.append(token)
        asyncio.create_task(broadcast({"type": "token", "model": winner_name, "token": token, "phase": "summary"}))

    summary = await stream_model_response(winner_cfg, SUMMARY_SYSTEM, summary_prompt, on_summary_token)

    await broadcast({"type": "consensus", "summary": summary, "delivered_by": winner_name})

    return summary, thread