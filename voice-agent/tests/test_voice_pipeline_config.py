import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from voice_pipeline_config import (
    DEFAULT_DEEPGRAM_TTS_MODEL,
    DEFAULT_LLM_MODEL,
    DEFAULT_SARVAM_LLM_MODEL,
    DEFAULT_SARVAM_STT_MODEL,
    DEFAULT_SARVAM_TTS_MODEL,
    DEFAULT_SARVAM_TTS_SPEAKER,
    DEFAULT_STT_MODEL,
    build_llm,
    build_stt,
    build_tts,
    get_voice_provider,
    normalize_assemblyai_stt_model,
    uses_stt_turn_detection,
)


def test_default_voice_provider_is_legacy():
    with patch.dict(os.environ, {}, clear=True):
        assert get_voice_provider() == "legacy"
        assert uses_stt_turn_detection() is False


def test_sarvam_voice_provider():
    with patch.dict(os.environ, {"VOICE_PROVIDER": "sarvam"}, clear=True):
        assert get_voice_provider() == "sarvam"
        assert uses_stt_turn_detection() is True


def test_legacy_voice_provider():
    with patch.dict(os.environ, {"VOICE_PROVIDER": "legacy"}, clear=True):
        assert get_voice_provider() == "legacy"
        assert uses_stt_turn_detection() is False


def test_build_sarvam_stt_defaults():
    with patch.dict(
        os.environ,
        {"SARVAM_API_KEY": "test-sarvam-key", "VOICE_PROVIDER": "sarvam"},
        clear=True,
    ), patch("voice_pipeline_config.sarvam.STT") as mock_stt:
        build_stt()
    mock_stt.assert_called_once_with(
        language="en-IN",
        model=DEFAULT_SARVAM_STT_MODEL,
        mode="transcribe",
        api_key="test-sarvam-key",
        flush_signal=True,
        high_vad_sensitivity=True,
        sample_rate=16000,
    )
    assert DEFAULT_SARVAM_STT_MODEL == "saaras:v3"


def test_build_sarvam_llm_defaults():
    with patch.dict(
        os.environ,
        {"SARVAM_API_KEY": "test-sarvam-key", "VOICE_PROVIDER": "sarvam"},
        clear=True,
    ), patch("voice_pipeline_config.sarvam.LLM") as mock_llm:
        build_llm()
    mock_llm.assert_called_once_with(
        model=DEFAULT_SARVAM_LLM_MODEL,
        api_key="test-sarvam-key",
    )
    assert DEFAULT_SARVAM_LLM_MODEL == "sarvam-30b"


def test_build_sarvam_tts_defaults():
    with patch.dict(
        os.environ,
        {"SARVAM_API_KEY": "test-sarvam-key", "VOICE_PROVIDER": "sarvam"},
        clear=True,
    ), patch("voice_pipeline_config.sarvam.TTS") as mock_tts:
        build_tts()
    mock_tts.assert_called_once_with(
        target_language_code="en-IN",
        model=DEFAULT_SARVAM_TTS_MODEL,
        speaker=DEFAULT_SARVAM_TTS_SPEAKER,
        api_key="test-sarvam-key",
    )
    assert DEFAULT_SARVAM_TTS_MODEL == "bulbul:v3"


def test_default_stt_model_is_universal_3_5_pro():
    assert DEFAULT_STT_MODEL == "universal-3-5-pro"


def test_normalize_assemblyai_stt_model_aliases():
    assert normalize_assemblyai_stt_model("u3-rt-pro") == "universal-3-5-pro"
    assert (
        normalize_assemblyai_stt_model("universal-3.5-pro-realtime")
        == "universal-3-5-pro"
    )


def test_build_legacy_stt_uses_assemblyai():
    with patch.dict(
        os.environ,
        {"ASSEMBLYAI_API_KEY": "test-aai-key", "VOICE_PROVIDER": "legacy"},
        clear=True,
    ), patch("voice_pipeline_config.assemblyai.STT") as mock_stt:
        build_stt()
    mock_stt.assert_called_once_with(
        model=DEFAULT_STT_MODEL,
        api_key="test-aai-key",
    )


def test_build_legacy_llm_uses_deepseek():
    with patch.dict(
        os.environ,
        {"DEEPSEEK_API_KEY": "test-deepseek-key", "VOICE_PROVIDER": "legacy"},
        clear=True,
    ), patch("voice_pipeline_config.openai.LLM") as mock_llm:
        build_llm()
    mock_llm.assert_called_once_with(
        model=DEFAULT_LLM_MODEL,
        api_key="test-deepseek-key",
        base_url="https://api.deepseek.com",
        extra_body={"thinking": {"type": "disabled"}},
    )


def test_build_legacy_tts_uses_deepgram():
    with patch.dict(
        os.environ,
        {"DEEPGRAM_API_KEY": "test-deepgram-key", "VOICE_PROVIDER": "legacy"},
        clear=True,
    ), patch("voice_pipeline_config.deepgram.TTS") as mock_tts:
        build_tts()
    mock_tts.assert_called_once_with(
        model=DEFAULT_DEEPGRAM_TTS_MODEL,
        api_key="test-deepgram-key",
    )
