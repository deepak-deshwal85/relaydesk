from __future__ import annotations

import logging
import re

from livekit.agents import AgentSession

from client_config import DEFAULT_VOICE_AGENT_GREETING

logger = logging.getLogger("relaydesk-agent")

GREETING_INSTRUCTIONS = DEFAULT_VOICE_AGENT_GREETING

_INSTRUCTION_MARKERS = (
    "greet the caller",
    "introduce the business",
    "summarize key service",
    "say you can answer",
    "ask what they would like",
    "ask we are offerings",
)


def is_session_closing_error(exc: BaseException) -> bool:
    return isinstance(exc, RuntimeError) and "AgentSession is closing" in str(exc)


def is_greeting_instructions(text: str) -> bool:
    """True when the greeting field holds LLM instructions, not speakable script."""
    normalized = " ".join(text.strip().lower().split())
    if normalized == " ".join(DEFAULT_VOICE_AGENT_GREETING.strip().lower().split()):
        return True
    return any(marker in normalized for marker in _INSTRUCTION_MARKERS)


def build_spoken_greeting(*, client_name: str, instructions: str) -> str:
    """Fast TTS path for instruction-style greetings (avoids an LLM round-trip)."""
    _ = instructions
    name = client_name.strip() or "our office"
    return (
        f"Hello, thank you for calling {name}. "
        "We offer professional home construction services. "
        "I can answer questions from our uploaded documents. "
        "What would you like to know?"
    )


def normalize_spoken_greeting(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


async def greet_caller(
    session: AgentSession,
    *,
    greeting_instructions: str,
    client_name: str = "",
) -> bool:
    """Speak the opening greeting. Returns False if the call ended first."""
    instructions = greeting_instructions.strip()
    if not instructions:
        logger.warning("empty greeting instructions; skipping greeting")
        return False

    if is_greeting_instructions(instructions):
        spoken = build_spoken_greeting(
            client_name=client_name,
            instructions=instructions,
        )
        logger.info("using direct TTS greeting (instruction-style config)")
    else:
        spoken = normalize_spoken_greeting(instructions)
        logger.info("using direct TTS greeting (script text from config)")

    try:
        await session.say(spoken, allow_interruptions=False)
        return True
    except RuntimeError as exc:
        if is_session_closing_error(exc):
            logger.info("skipping greeting: session ended before reply could start")
            return False
        raise
