"""STT / LLM / TTS factories for the RelayDesk voice pipeline.

Default stack (cost-optimized):
  STT: AssemblyAI universal-streaming-english (~$0.0025/min)
  LLM: DeepSeek V4 Flash via OpenAI-compatible API
  TTS: Deepgram Aura-2
"""

from __future__ import annotations

import os

from livekit.plugins import assemblyai, deepgram, openai

# Streaming English tier matches Universal-2 pricing ($0.15/hr ≈ $0.0025/min).
DEFAULT_STT_MODEL = "universal-streaming-english"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPGRAM_TTS_MODEL = "aura-2-andromeda-en"

# Disable DeepSeek "thinking" mode for lower voice latency.
DEEPSEEK_NON_THINKING_BODY = {"thinking": {"type": "disabled"}}


def build_stt(*, model: str | None = None, api_key: str | None = None) -> assemblyai.STT:
    return assemblyai.STT(
        model=model or os.getenv("STT_MODEL", DEFAULT_STT_MODEL),
        api_key=api_key or os.getenv("ASSEMBLYAI_API_KEY"),
    )


def build_llm(
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> openai.LLM:
    return openai.LLM(
        model=model or os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
        api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
        base_url=base_url or os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
        extra_body=DEEPSEEK_NON_THINKING_BODY,
    )


def build_tts(*, model: str | None = None, api_key: str | None = None) -> deepgram.TTS:
    return deepgram.TTS(
        model=model or os.getenv("DEEPGRAM_TTS_MODEL", DEFAULT_DEEPGRAM_TTS_MODEL),
        api_key=api_key or os.getenv("DEEPGRAM_API_KEY"),
    )
