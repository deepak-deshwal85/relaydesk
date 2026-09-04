import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from session_greeting import (
    GREETING_INSTRUCTIONS,
    build_spoken_greeting,
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


def test_build_spoken_greeting_uses_client_name():
    spoken = build_spoken_greeting(
        client_name="Acme Builders",
        instructions=GREETING_INSTRUCTIONS,
    )
    assert "Acme Builders" in spoken
    assert "What would you like to know?" in spoken


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
    session.say = AsyncMock()
    assert (
        await greet_caller(
            session,
            greeting_instructions=GREETING_INSTRUCTIONS,
            client_name="Deepak Deshwal",
        )
        is True
    )
    session.say.assert_awaited_once()
    spoken = session.say.await_args.args[0]
    assert "Deepak Deshwal" in spoken


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
