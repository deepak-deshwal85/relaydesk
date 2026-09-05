from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

MAX_FORMATTED_HITS = 2
MAX_HIT_TEXT_CHARS = 280


@dataclass(frozen=True)
class RagSearchHit:
    text: str
    score: float
    source_uri: str | None = None


class RagRetriever(Protocol):
    async def search(self, query: str, *, max_results: int) -> list[RagSearchHit]: ...


def filter_relevant_hits(
    hits: list[RagSearchHit],
    *,
    min_score: float,
) -> list[RagSearchHit]:
    return [hit for hit in hits if hit.score >= min_score]


def format_search_hits(hits: list[RagSearchHit]) -> str:
    if not hits:
        return "No matching information was found in the knowledge base."

    lines = ["Relevant document excerpts:"]
    for index, hit in enumerate(hits[:MAX_FORMATTED_HITS], start=1):
        source = f" (source: {hit.source_uri})" if hit.source_uri else ""
        text = hit.text.strip()
        if len(text) > MAX_HIT_TEXT_CHARS:
            text = text[:MAX_HIT_TEXT_CHARS].rstrip() + "…"
        lines.append(f"{index}. {text}{source}")
    return "\n".join(lines)
