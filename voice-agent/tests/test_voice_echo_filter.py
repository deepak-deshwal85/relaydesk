import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from voice_echo_filter import is_likely_agent_echo, recent_assistant_text


def test_is_likely_agent_echo_detects_substring_match():
    assistant = (
        "Since you have no further questions, would you like to schedule a meeting?"
    )
    assert is_likely_agent_echo("since you have no further question", assistant) is True


def test_is_likely_agent_echo_detects_fragment_overlap():
    assistant = "I don't have that detail in the uploaded documents."
    assert is_likely_agent_echo("i don't have that detail", assistant) is True


def test_is_likely_agent_echo_allows_real_user_question():
    assistant = "I don't have that detail in the uploaded documents."
    assert (
        is_likely_agent_echo("what is yono banking", assistant, agent_speaking=False)
        is False
    )


def test_recent_assistant_text_reads_chat_context():
    msg = MagicMock(role="assistant", content=["Hello from the agent."])
    chat_ctx = MagicMock(items=[msg])
    assert recent_assistant_text(chat_ctx) == "Hello from the agent."
