import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from client_config import ClientConfig
from rag_client.models import RagSearchHit, filter_relevant_hits, format_search_hits
from rag_client.prefetch import (
    DocumentPrefetchCache,
    build_prefetched_context_message,
    extract_message_text,
    play_processing_filler,
    requires_sync_turn_completion,
    should_auto_search_user_text,
)


def test_extract_message_text_from_string_list():
    assert extract_message_text(["What is Reliance revenue?"]) == (
        "What is Reliance revenue?"
    )


def test_should_auto_search_skips_short_confirmations():
    assert should_auto_search_user_text("no") is False
    assert should_auto_search_user_text("Yes.") is False
    assert should_auto_search_user_text("Oh, stop.") is False
    assert should_auto_search_user_text("ठीक है") is False
    assert should_auto_search_user_text("नहीं सर") is False
    assert should_auto_search_user_text("I") is False
    assert should_auto_search_user_text("What is Reliance Industries?") is True
    assert should_auto_search_user_text("who founded reliance") is True


def test_should_auto_search_skips_stop_signal_in_any_position():
    # Interrupt phrases that contain a stop-signal word should not trigger RAG.
    assert should_auto_search_user_text("Good. Stop. Stop.") is False
    assert should_auto_search_user_text("Good stop") is False
    assert should_auto_search_user_text("Bye for now") is False
    assert should_auto_search_user_text("Okay. Stop.") is False


def test_warmup_queries_defaults():
    from rag_client.prefetch import DEFAULT_WARMUP_QUERIES, warmup_queries

    assert warmup_queries() == DEFAULT_WARMUP_QUERIES


def test_warmup_queries_from_env(monkeypatch):
    from rag_client.prefetch import warmup_queries

    monkeypatch.setenv("RAG_WARMUP_QUERIES", "foo, bar")
    assert warmup_queries() == ("foo", "bar")


def test_warmup_knowledge_retriever_runs_searches():
    import asyncio
    from unittest.mock import AsyncMock

    from rag_client.prefetch import warmup_knowledge_retriever

    retriever = AsyncMock()
    retriever.warmup = AsyncMock()
    retriever.search = AsyncMock(return_value=[])

    config = ClientConfig(
        phone_number="911171366880",
        client_name="Test Client",
        client_email_id="client@example.com",
        greeting_message="Hello.",
    )

    asyncio.run(
        warmup_knowledge_retriever(
            client_config=config,
            retriever=retriever,
        )
    )

    retriever.warmup.assert_awaited_once()
    assert retriever.search.await_count == 5


def test_document_prefetch_cache_reuses_inflight_task():
    import asyncio

    async def slow_prefetch() -> str:
        await asyncio.sleep(0.05)
        return "cached context"

    async def _run() -> None:
        cache = DocumentPrefetchCache()
        cache.schedule("revenue", slow_prefetch())
        result = await cache.consume("revenue")
        assert result == "cached context"
        assert await cache.consume("revenue") == "cached context"

    asyncio.run(_run())


def test_play_processing_filler_waits_then_speaks():
    import asyncio

    async def _run() -> None:
        session = MagicMock()
        session.say = AsyncMock()
        await play_processing_filler(
            session,
            language="hi-IN",
            delay_seconds=0,
            allow_interruptions=False,
        )
        session.say.assert_awaited_once()

    asyncio.run(_run())


def test_filter_relevant_hits_drops_weak_matches():
    hits = [
        RagSearchHit(text="strong", score=0.62, source_uri="a.txt"),
        RagSearchHit(text="weak", score=0.18, source_uri="b.txt"),
    ]
    filtered = filter_relevant_hits(hits, min_score=0.3)
    assert len(filtered) == 1
    assert filtered[0].text == "strong"


def test_requires_sync_turn_completion():
    config = ClientConfig(
        phone_number="911171366880",
        client_name="Test Client",
        client_email_id="client@example.com",
        greeting_message="Hello.",
    )
    assert requires_sync_turn_completion(config) is True


def test_build_prefetched_context_message_includes_excerpts():
    message = build_prefetched_context_message(
        user_query="revenue",
        hits=[
            RagSearchHit(
                text="Annual revenues were US$ 10.1 billion.",
                score=0.9,
                source_uri="reliance.pdf",
            )
        ],
    )
    assert "Uploaded document search results" in message
    assert "Annual revenues" in message
    assert "uploaded documents" in message.lower()


def test_format_search_hits_limits_count_and_truncates_text():
    formatted = format_search_hits(
        [
            RagSearchHit(text="A" * 400, score=0.9, source_uri="a.txt"),
            RagSearchHit(text="Second hit", score=0.8, source_uri="b.txt"),
            RagSearchHit(text="Third hit", score=0.7, source_uri="c.txt"),
        ]
    )
    assert "1." in formatted
    assert "2." in formatted
    assert "3." not in formatted
    assert "Third hit" not in formatted
    assert "…" in formatted
