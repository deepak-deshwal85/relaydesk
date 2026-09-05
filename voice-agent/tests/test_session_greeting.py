import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from session_greeting import (
    GREETING_INSTRUCTIONS,
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
async def test_greet_caller_uses_spoken_template_for_instructions():
    session = MagicMock()
    session.generate_reply = MagicMock()
    handle = MagicMock()
    handle.wait_for_playout = AsyncMock()
    session.generate_reply.return_value = handle
    assert (
        await greet_caller(
            session,
            greeting_instructions=GREETING_INSTRUCTIONS,
            client_name="Deepak Deshwal",
            voice_agent_language="hi-IN",
        )
        is True
    )
    session.generate_reply.assert_called_once()
    assert "Deepak Deshwal" in session.generate_reply.call_args.kwargs["instructions"]
    assert "Hindi" in session.generate_reply.call_args.kwargs["instructions"]
    handle.wait_for_playout.assert_awaited_once()


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
