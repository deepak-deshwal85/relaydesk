from __future__ import annotations

import logging
import os

from livekit.agents import llm

from call_summary_builder import EMPTY_TRANSCRIPT_MESSAGE, MAX_SUMMARY_LENGTH
from voice_pipeline_config import build_llm

logger = logging.getLogger("relaydesk-agent")

MAX_TRANSCRIPT_INPUT_CHARS = 12000
MAX_SUMMARY_OUTPUT_CHARS = 2000

SUMMARY_SYSTEM_INSTRUCTIONS = """You write concise call summaries for a business phone assistant.

Given a call transcript, produce a short summary (3–6 sentences) that covers:
- Why the caller contacted the business
- Main questions or topics discussed
- Key answers or information provided from documents
- Whether a meeting was offered or booked (if mentioned in the transcript)

Write in plain prose for a business owner to read. Do not use markdown, bullet lists, or speaker labels.
Do not invent details that are not in the transcript."""


def _is_empty_transcript(transcript: str) -> bool:
    normalized = transcript.strip()
    return not normalized or normalized == EMPTY_TRANSCRIPT_MESSAGE


def _truncate_transcript(transcript: str) -> str:
    if len(transcript) <= MAX_TRANSCRIPT_INPUT_CHARS:
        return transcript
    return transcript[:MAX_TRANSCRIPT_INPUT_CHARS] + "…"


def _build_user_prompt(
    transcript: str,
    *,
    client_name: str | None,
    meeting_scheduled: bool,
) -> str:
    business = client_name.strip() if client_name else "the business"
    meeting_note = (
        "A meeting was successfully booked during this call."
        if meeting_scheduled
        else "No meeting was booked during this call."
    )
    return (
        f"Business: {business}\n"
        f"Meeting outcome: {meeting_note}\n\n"
        "Transcript:\n"
        f"{_truncate_transcript(transcript)}"
    )


async def summarize_call_transcript(
    transcript: str,
    *,
    client_name: str | None = None,
    meeting_scheduled: bool = False,
    llm_instance: llm.LLM | None = None,
) -> str:
    """Convert a raw Caller/Agent transcript into a concise LLM summary."""
    if _is_empty_transcript(transcript):
        return EMPTY_TRANSCRIPT_MESSAGE

    summary_model = os.getenv("CALL_SUMMARY_LLM_MODEL", "").strip() or None
    model = llm_instance or build_llm(model=summary_model)
    owns_llm = llm_instance is None

    chat_ctx = llm.ChatContext()
    chat_ctx.add_message(role="system", content=SUMMARY_SYSTEM_INSTRUCTIONS)
    chat_ctx.add_message(
        role="user",
        content=_build_user_prompt(
            transcript,
            client_name=client_name,
            meeting_scheduled=meeting_scheduled,
        ),
    )

    try:
        response = await model.chat(chat_ctx=chat_ctx).collect()
        summary = response.text.strip()
        if not summary:
            raise ValueError("LLM returned empty summary")
        if len(summary) > MAX_SUMMARY_OUTPUT_CHARS:
            summary = summary[:MAX_SUMMARY_OUTPUT_CHARS].rstrip() + "…"
        logger.info(
            "generated call summary via llm chars=%d meeting_scheduled=%s",
            len(summary),
            meeting_scheduled,
        )
        return summary
    except Exception:
        logger.exception("call summary llm failed; using transcript excerpt fallback")
        excerpt = transcript.strip()
        if len(excerpt) > MAX_SUMMARY_LENGTH:
            excerpt = excerpt[:MAX_SUMMARY_LENGTH] + "…"
        return excerpt
    finally:
        if owns_llm:
            await model.aclose()
