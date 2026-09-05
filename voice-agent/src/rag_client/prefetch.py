from __future__ import annotations

import asyncio
import inspect
import logging
import os
import random
import re
import time
from collections.abc import Coroutine

from client_config import ClientConfig
from rag_client.api_retriever import create_api_rag_retriever
from rag_client.config import RagClientSettings, load_rag_settings
from rag_client.models import RagSearchHit, filter_relevant_hits, format_search_hits

logger = logging.getLogger("relaydesk-agent")

_RAW_SKIP_AUTO_SEARCH_PHRASES = {
    "no",
    "nope",
    "yes",
    "yeah",
    "yep",
    "ok",
    "okay",
    "okay stop",
    "thanks",
    "thank you",
    "stop",
    "oh stop",
    "bye",
    "goodbye",
    "hi",
    "hello",
    "ok sir",
    "okay sir",
    "ठीक है",
    "ठीक है सर",
    "ठीक है जी",
    "हां",
    "हाँ",
    "हाँ जी",
    "जी",
    "जी सर",
    "नहीं",
    "नहीं सर",
}
SKIP_AUTO_SEARCH_PHRASES = frozenset(
    re.sub(r"[^\w\s]", "", phrase.strip().lower()) for phrase in _RAW_SKIP_AUTO_SEARCH_PHRASES
)

# Single words that always indicate an interrupt/dismissal, even inside a longer
# phrase. e.g. "Good. Stop. Stop." is not a searchable question.
STOP_SIGNAL_WORDS = frozenset({"stop", "bye", "goodbye"})

DEFAULT_MIN_AUTO_SEARCH_WORDS = 2

# Filler phrases spoken immediately while RAG runs in background.
# Varied pool avoids sounding robotic.
_FILLER_PHRASES_BY_LANGUAGE = {
    "hi-IN": (
        "एक क्षण, मैं यह देखता हूं।",
        "जी, मैं यह जानकारी देखता हूं।",
        "कृपया एक सेकंड, मैं जांच कर रहा हूं।",
        "मैं अभी यह जानकारी देखता हूं।",
        "ठीक है, मैं इसे देखकर बताता हूं।",
        "मैं आपकी मदद कर रहा हूं, एक क्षण।",
    ),
    "en-IN": (
        "Let me check that for you.",
        "Sure, let me look that up.",
        "One moment while I find that.",
        "Let me find that information for you.",
        "Just a second, looking that up now.",
    ),
}


def pick_filler_phrase(language: str = "en-IN") -> str:
    phrases = _FILLER_PHRASES_BY_LANGUAGE.get(
        language,
        _FILLER_PHRASES_BY_LANGUAGE["en-IN"],
    )
    return random.choice(phrases)


async def play_processing_filler(
    session,
    *,
    language: str,
    delay_seconds: float,
    allow_interruptions: bool,
) -> None:
    """Speak a short hold phrase only when processing takes noticeably long."""
    await asyncio.sleep(delay_seconds)
    result = session.say(
        pick_filler_phrase(language),
        allow_interruptions=allow_interruptions,
        add_to_chat_ctx=False,
    )
    if inspect.isawaitable(result):
        await result

DEFAULT_WARMUP_QUERIES = (
    "Who is the appellant",
    "What is the case name",
    "Who delivered the judgment",
    "What is the order date",
    "Who is the counsel",
)


def warmup_queries() -> tuple[str, ...]:
    raw = os.getenv("RAG_WARMUP_QUERIES", "").strip()
    if raw:
        return tuple(query.strip() for query in raw.split(",") if query.strip())
    return DEFAULT_WARMUP_QUERIES


async def warmup_knowledge_retriever(
    *,
    client_config: ClientConfig,
    retriever,
) -> None:
    """Prime HTTP, embedding cache, and Qdrant before the first user question."""
    warmup = getattr(retriever, "warmup", None)
    if warmup is not None:
        await warmup()

    queries = warmup_queries()
    if not queries:
        return

    started = time.perf_counter()
    max_results = 1
    results = await asyncio.gather(
        *[
            retriever.search(query, max_results=max_results)
            for query in queries
        ],
        return_exceptions=True,
    )
    ok = sum(1 for result in results if not isinstance(result, Exception))
    logger.info(
        "rag warmup phone=%s queries=%d ok=%d total_ms=%.0f",
        client_config.phone_number,
        len(queries),
        ok,
        (time.perf_counter() - started) * 1000,
    )


def create_knowledge_retriever(
    client_config: ClientConfig,
    settings: RagClientSettings | None = None,
):
    rag_settings = settings or load_rag_settings()
    return create_api_rag_retriever(
        client_config=client_config,
        settings=rag_settings,
    )


def extract_message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif hasattr(item, "text"):
            parts.append(str(item.text))
    return " ".join(parts).strip()


def min_auto_search_words() -> int:
    return int(os.getenv("RAG_MIN_QUERY_WORDS", str(DEFAULT_MIN_AUTO_SEARCH_WORDS)))


def should_auto_search_user_text(user_text: str) -> bool:
    normalized = re.sub(r"[^\w\s]", "", user_text.strip().lower())
    normalized = " ".join(normalized.split())
    if not normalized:
        return False
    if normalized in SKIP_AUTO_SEARCH_PHRASES:
        return False
    words = normalized.split()
    # Skip if any stop/interrupt signal word is present anywhere in the utterance
    # (e.g. "Good. Stop. Stop." should not trigger a RAG search).
    if any(word in STOP_SIGNAL_WORDS for word in words):
        return False
    return len(words) >= min_auto_search_words()


def build_prefetched_context_message(*, user_query: str, hits: list[RagSearchHit]) -> str:
    if hits:
        excerpts = format_search_hits(hits)
        return (
            f"Uploaded document search results for the caller's question ({user_query!r}):\n"
            f"{excerpts}\n"
            "Answer using these excerpts when they are relevant. "
            "If they do not contain the answer, say you do not have that detail "
            "in the uploaded documents."
        )

    return (
        f"Uploaded document search results for the caller's question ({user_query!r}):\n"
        "No matching information was found in the knowledge base.\n"
        "Tell the caller you do not have that detail in the uploaded documents."
    )


def requires_sync_turn_completion(client_config: ClientConfig) -> bool:
    """RAG prefetch in on_user_turn_completed must finish before the LLM runs."""
    return create_knowledge_retriever(client_config) is not None


class DocumentPrefetchCache:
    """Starts document search early on final STT transcripts."""

    def __init__(self) -> None:
        self._active_query: str | None = None
        self._task: asyncio.Task[str | None] | None = None

    def schedule(
        self,
        user_text: str,
        coro: Coroutine[object, object, str | None],
    ) -> None:
        normalized = user_text.strip()
        if not normalized:
            return
        if (
            self._task is not None
            and not self._task.done()
            and self._active_query == normalized
        ):
            return
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._active_query = normalized
        self._task = asyncio.create_task(coro)

    async def consume(self, user_text: str) -> str | None:
        normalized = user_text.strip()
        if self._task is None or self._active_query != normalized:
            return None
        try:
            return await self._task
        except asyncio.CancelledError:
            return None


async def prefetch_uploaded_documents(
    *,
    client_config: ClientConfig,
    user_text: str,
    retriever,
    settings: RagClientSettings | None = None,
    already_filtered: bool = False,
) -> str | None:
    if not already_filtered and not should_auto_search_user_text(user_text):
        return None

    rag_settings = settings or load_rag_settings()
    max_results = int(os.getenv("RAG_MAX_RESULTS", str(rag_settings.max_results)))
    raw_hits = await retriever.search(user_text, max_results=max_results)
    hits = filter_relevant_hits(raw_hits, min_score=rag_settings.min_score)
    top_score = max((hit.score for hit in raw_hits), default=0.0)
    logger.info(
        "auto document search phone=%s query=%r hits=%d raw_hits=%d top_score=%.3f min_score=%.2f",
        client_config.phone_number,
        user_text[:80],
        len(hits),
        len(raw_hits),
        top_score,
        rag_settings.min_score,
    )
    return build_prefetched_context_message(user_query=user_text, hits=hits)
