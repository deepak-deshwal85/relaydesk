"""STT / LLM / TTS factories for the RelayDesk voice pipeline.

Providers (``VOICE_PROVIDER``):
  legacy (default) — AssemblyAI U3.5 Pro RT STT, DeepSeek V4 Flash LLM, Deepgram Aura-1 TTS
  sarvam           — Saaras v3 STT, Sarvam LLM, Bulbul v3 TTS (Indian languages)
"""

from __future__ import annotations

import os
from typing import Literal

from livekit.plugins import assemblyai, deepgram, openai, sarvam

VoiceProvider = Literal["sarvam", "legacy"]

# --- Sarvam defaults (https://docs.sarvam.ai/integrations/livekit) ---
DEFAULT_SARVAM_STT_MODEL = "saaras:v3"
DEFAULT_SARVAM_STT_LANGUAGE = "en-IN"
DEFAULT_SARVAM_STT_MODE = "transcribe"
DEFAULT_SARVAM_TTS_MODEL = "bulbul:v3"
DEFAULT_SARVAM_TTS_LANGUAGE = "en-IN"
DEFAULT_SARVAM_TTS_SPEAKER = "shubh"
DEFAULT_SARVAM_LLM_MODEL = "sarvam-30b"  # use sarvam-105b only if latency is acceptable

# --- Legacy defaults (AssemblyAI U3.5 Pro RT + DeepSeek V4 Flash + Deepgram Aura-1) ---
DEFAULT_STT_MODEL = "universal-3-5-pro"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPGRAM_TTS_MODEL = "aura-asteria-en"

DEEPSEEK_NON_THINKING_BODY = {"thinking": {"type": "disabled"}}

# Common typos / shorthand → valid Deepgram model IDs (see developers.deepgram.com/docs/tts-models)
_DEEPGRAM_TTS_ALIASES = {
    "aura-andromeda-en": "aura-2-andromeda-en",
}

# AssemblyAI streaming model aliases (LiveKit plugin accepts u3-rt-pro, universal-3-5-pro, …)
_ASSEMBLYAI_STT_ALIASES = {
    "universal-3.5-pro-realtime": "universal-3-5-pro",
    "universal-3-5-pro-realtime": "universal-3-5-pro",
    "u3-pro": "universal-3-5-pro",
    "u3-rt-pro": "universal-3-5-pro",
}


def normalize_assemblyai_stt_model(model: str) -> str:
    normalized = model.strip()
    return _ASSEMBLYAI_STT_ALIASES.get(normalized.lower(), normalized)


def normalize_deepgram_tts_model(model: str) -> str:
    normalized = model.strip()
    return _DEEPGRAM_TTS_ALIASES.get(normalized.lower(), normalized)


def get_voice_provider() -> VoiceProvider:
    raw = os.getenv("VOICE_PROVIDER", "legacy").strip().lower()
    if raw == "sarvam":
        return "sarvam"
    return "legacy"


def uses_stt_turn_detection() -> bool:
    """True when STT emits end-of-turn signals (Cartesia ink-2, Sarvam saaras)."""
    return get_voice_provider() == "sarvam"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_stt(*, model: str | None = None, api_key: str | None = None):
    if get_voice_provider() == "sarvam":
        return sarvam.STT(
            language=os.getenv("SARVAM_STT_LANGUAGE", DEFAULT_SARVAM_STT_LANGUAGE),
            model=model or os.getenv("SARVAM_STT_MODEL", DEFAULT_SARVAM_STT_MODEL),
            mode=os.getenv("SARVAM_STT_MODE", DEFAULT_SARVAM_STT_MODE),
            api_key=api_key or os.getenv("SARVAM_API_KEY"),
            flush_signal=_bool_env("SARVAM_STT_FLUSH_SIGNAL", True),
            high_vad_sensitivity=_bool_env("SARVAM_STT_HIGH_VAD", True),
            sample_rate=int(os.getenv("SARVAM_STT_SAMPLE_RATE", "16000")),
        )
    return assemblyai.STT(
        model=normalize_assemblyai_stt_model(
            model or os.getenv("STT_MODEL", DEFAULT_STT_MODEL)
        ),
        api_key=api_key or os.getenv("ASSEMBLYAI_API_KEY"),
    )


def build_llm(
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
):
    if get_voice_provider() == "sarvam":
        return sarvam.LLM(
            model=model or os.getenv("SARVAM_LLM_MODEL", DEFAULT_SARVAM_LLM_MODEL),
            api_key=api_key or os.getenv("SARVAM_API_KEY"),
        )
    return openai.LLM(
        model=model or os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
        api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
        base_url=base_url or os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
        extra_body=DEEPSEEK_NON_THINKING_BODY,
    )


def build_tts(*, model: str | None = None, api_key: str | None = None):
    if get_voice_provider() == "sarvam":
        return sarvam.TTS(
            target_language_code=os.getenv(
                "SARVAM_TTS_LANGUAGE", DEFAULT_SARVAM_TTS_LANGUAGE
            ),
            model=model or os.getenv("SARVAM_TTS_MODEL", DEFAULT_SARVAM_TTS_MODEL),
            speaker=os.getenv("SARVAM_TTS_SPEAKER", DEFAULT_SARVAM_TTS_SPEAKER),
            api_key=api_key or os.getenv("SARVAM_API_KEY"),
        )
    return deepgram.TTS(
        model=normalize_deepgram_tts_model(
            model or os.getenv("DEEPGRAM_TTS_MODEL", DEFAULT_DEEPGRAM_TTS_MODEL)
        ),
        api_key=api_key or os.getenv("DEEPGRAM_API_KEY"),
    )
