import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from session_greeting import (
    GREETING_INSTRUCTIONS,
    build_default_spoken_greeting,
    build_instruction_style_spoken_greeting,
    build_greeting_reply_instructions,
    greet_caller,
    is_greeting_instructions,
    is_session_closing_error,
)


def test_is_session_closing_error():
    assert is_session_closing_error(
        RuntimeError("AgentSession is closing, cannot use generate_reply()")
    )
    assert not is_session_closing_error(RuntimeError("something else"))
    assert not is_session_closing_error(ValueError("AgentSession is closing"))


def test_is_greeting_instructions_detects_prompt_style_text():
    assert is_greeting_instructions(GREETING_INSTRUCTIONS)
    assert is_greeting_instructions(
        "Greet the caller briefly. Ask we are offerings home construction service."
    )
    assert not is_greeting_instructions("Hello, thanks for calling Acme Builders.")


def test_build_greeting_reply_instructions_uses_language_and_client_name():
    spoken = build_greeting_reply_instructions(
        client_name="Acme Builders",
        instructions=GREETING_INSTRUCTIONS,
        voice_agent_language="hi-IN",
    )
    assert "Acme Builders" in spoken
    assert "Hindi" in spoken


def test_build_default_spoken_greeting_uses_hindi_template():
    spoken = build_default_spoken_greeting(
        client_name="Deepak Deshwal",
        voice_agent_language="hi-IN",
    )
    assert "Deepak Deshwal" in spoken
    assert "नमस्ते" in spoken


def test_build_instruction_style_spoken_greeting_uses_direct_template():
    spoken = build_instruction_style_spoken_greeting(
        client_name="Deepak Deshwal",
        instructions=(
            "Greet the caller briefly. Introduce the business and summarize key "
            "service offerings in home construction."
        ),
        voice_agent_language="hi-IN",
    )
    assert "Deepak Deshwal" in spoken
    assert "नमस्ते" in spoken


@pytest.mark.asyncio
async def test_greet_caller_uses_direct_tts_for_script():
    session = MagicMock()
    session.say = AsyncMock()
    assert (
        await greet_caller(
            session,
            greeting_instructions="Hello from Acme Builders.",
            client_name="Acme Builders",
        )
        is True
    )
    session.say.assert_awaited_once_with(
        "Hello from Acme Builders.",
        allow_interruptions=False,
    )


@pytest.mark.asyncio
async def test_greet_caller_uses_direct_default_template_for_default_instructions():
    session = MagicMock()
    session.say = AsyncMock()
    assert (
        await greet_caller(
            session,
            greeting_instructions=GREETING_INSTRUCTIONS,
            client_name="Deepak Deshwal",
            voice_agent_language="hi-IN",
        )
        is True
    )
    session.say.assert_awaited_once()
    spoken = session.say.await_args.args[0]
    assert "Deepak Deshwal" in spoken
    assert "नमस्ते" in spoken
    session.generate_reply.assert_not_called()


@pytest.mark.asyncio
async def test_greet_caller_uses_direct_tts_for_custom_instruction_style_greeting():
    session = MagicMock()
    session.say = AsyncMock()
    assert (
        await greet_caller(
            session,
            greeting_instructions=(
                "Greet the caller briefly. Introduce the business and summarize key "
                "service offerings in home construction. Ask what they would like to know."
            ),
            client_name="Deepak Deshwal",
            voice_agent_language="hi-IN",
        )
        is True
    )
    session.say.assert_awaited_once()
    spoken = session.say.await_args.args[0]
    assert "Deepak Deshwal" in spoken
    assert "नमस्ते" in spoken
    session.generate_reply.assert_not_called()


@pytest.mark.asyncio
async def test_greet_caller_skips_when_session_closing():
    session = MagicMock()
    session.say = AsyncMock(
        side_effect=RuntimeError("AgentSession is closing, cannot use generate_reply()")
    )
    assert (
        await greet_caller(
            session,
            greeting_instructions="Hello from Acme Builders.",
        )
        is False
    )
