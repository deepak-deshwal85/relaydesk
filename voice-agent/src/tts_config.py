"""Backward-compatible TTS helper — delegates to Deepgram Aura in voice_pipeline_config."""

from voice_pipeline_config import build_tts as build_deepgram_tts

# Legacy import name used by older tests/docs.
build_cartesia_tts = build_deepgram_tts

__all__ = ["build_cartesia_tts", "build_deepgram_tts"]
