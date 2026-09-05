"""Detect when STT transcribed the agent's own TTS output (speaker bleed / echo)."""

from __future__ import annotations

import re

from rag_client.prefetch import extract_message_text

def normalize_echo_text(text: str) -> str:
    normalized = re.sub(r"[^\w\s]", "", text.strip().lower())
    return " ".join(normalized.split())

_RAW_ECHO_SKIP_PHRASES = {
    "i dont have",
    "i don't have",
    "that detail",
    "have that detail",
    "since you have no further",
    "no further question",
    "other questions",
    "uploaded documents",
    "let me check",
    "one moment",
    "looking that up",
    "just a second",
    "let me find",
    "let me find that information",
    "एक क्षण",
    "एक सेकंड",
    "मैं यह जानकारी देखता",
    "मैं जांच कर रहा",
    "मैं इसे देखकर बताता",
    "जस्ट अ सेकंड",
    "लेट मी चेक",
    "लेट मी फाइंड",
}
_ECHO_SKIP_PHRASES = frozenset(normalize_echo_text(phrase) for phrase in _RAW_ECHO_SKIP_PHRASES)


def recent_assistant_text(chat_ctx, *, max_messages: int = 3) -> str:
    parts: list[str] = []
    for item in reversed(getattr(chat_ctx, "items", ())):
        if getattr(item, "role", None) != "assistant":
            continue
        text = extract_message_text(getattr(item, "content", ""))
        if text:
            parts.append(text)
        if len(parts) >= max_messages:
            break
    return " ".join(reversed(parts))


def is_likely_agent_echo(
    user_text: str,
    assistant_text: str,
    *,
    agent_speaking: bool = False,
) -> bool:
    user = normalize_echo_text(user_text)
    if not user:
        return True

    if user in _ECHO_SKIP_PHRASES or any(phrase in user for phrase in _ECHO_SKIP_PHRASES):
        return True

    assistant = normalize_echo_text(assistant_text)
    if not assistant:
        return False

    if user in assistant or assistant in user:
        return True

    user_words = user.split()
    if not user_words:
        return True

    assistant_words = set(assistant.split())
    overlap = sum(1 for word in user_words if word in assistant_words) / len(user_words)
    max_words = 10 if agent_speaking else 8
    threshold = 0.7 if agent_speaking else 0.85
    return len(user_words) <= max_words and overlap >= threshold
