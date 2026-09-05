from __future__ import annotations

import logging
import re

from livekit.agents import AgentSession

from client_config import DEFAULT_VOICE_AGENT_GREETING, voice_agent_language_label

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


def build_greeting_reply_instructions(
    *, client_name: str, instructions: str, voice_agent_language: str
) -> str:
    language = voice_agent_language_label(voice_agent_language)
    return (
        f"{instructions.strip()}\n\n"
        "You are speaking on a phone call. "
        f"Greet the caller in {language}. "
        f"Mention the business name as {client_name.strip() or 'our office'}. "
        "Keep it brief and natural, using one or two short sentences. "
        "Do not use markdown or bullet points."
    )


def normalize_spoken_greeting(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


async def greet_caller(
    session: AgentSession,
    *,
    greeting_instructions: str,
    client_name: str = "",
    voice_agent_language: str = "hi-IN",
) -> bool:
    """Speak the opening greeting. Returns False if the call ended first."""
    instructions = greeting_instructions.strip()
    if not instructions:
        logger.warning("empty greeting instructions; skipping greeting")
        return False

    if is_greeting_instructions(instructions):
        reply_instructions = build_greeting_reply_instructions(
            client_name=client_name,
            instructions=instructions,
            voice_agent_language=voice_agent_language,
        )
        logger.info(
            "using LLM-generated greeting (instruction-style config, language=%s)",
            voice_agent_language,
        )
    else:
        spoken = normalize_spoken_greeting(instructions)
        logger.info("using direct TTS greeting (script text from config)")

    try:
        if is_greeting_instructions(instructions):
            handle = session.generate_reply(
                instructions=reply_instructions,
                allow_interruptions=False,
                tool_choice="none",
            )
            await handle.wait_for_playout()
        else:
            await session.say(spoken, allow_interruptions=False)
        return True
    except RuntimeError as exc:
        if is_session_closing_error(exc):
            logger.info("skipping greeting: session ended before reply could start")
            return False
        raise
