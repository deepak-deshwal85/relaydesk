import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from voice_pipeline_config import (
    DEFAULT_DEEPGRAM_TTS_MODEL,
    DEFAULT_LLM_MODEL,
    DEFAULT_STT_MODEL,
    build_llm,
    build_stt,
    build_tts,
)


def test_build_stt_uses_assemblyai_streaming_default():
    with patch.dict(
        os.environ,
        {"ASSEMBLYAI_API_KEY": "test-aai-key"},
        clear=True,
    ), patch("voice_pipeline_config.assemblyai.STT") as mock_stt:
        build_stt()
    mock_stt.assert_called_once_with(
        model=DEFAULT_STT_MODEL,
        api_key="test-aai-key",
    )
    assert DEFAULT_STT_MODEL == "universal-streaming-english"


def test_build_stt_reads_model_override():
    with patch.dict(
        os.environ,
        {
            "ASSEMBLYAI_API_KEY": "test-aai-key",
            "STT_MODEL": "universal-3-5-pro",
        },
        clear=True,
    ), patch("voice_pipeline_config.assemblyai.STT") as mock_stt:
        build_stt()
    mock_stt.assert_called_once_with(
        model="universal-3-5-pro",
        api_key="test-aai-key",
    )


def test_build_llm_uses_deepseek_openai_compatible():
    with patch.dict(
        os.environ,
        {"DEEPSEEK_API_KEY": "test-deepseek-key"},
        clear=True,
    ), patch("voice_pipeline_config.openai.LLM") as mock_llm:
        build_llm()
    mock_llm.assert_called_once_with(
        model=DEFAULT_LLM_MODEL,
        api_key="test-deepseek-key",
        base_url="https://api.deepseek.com",
        extra_body={"thinking": {"type": "disabled"}},
    )
    assert DEFAULT_LLM_MODEL == "deepseek-v4-flash"


def test_build_tts_uses_deepgram_aura_default():
    with patch.dict(
        os.environ,
        {"DEEPGRAM_API_KEY": "test-deepgram-key"},
        clear=True,
    ), patch("voice_pipeline_config.deepgram.TTS") as mock_tts:
        build_tts()
    mock_tts.assert_called_once_with(
        model=DEFAULT_DEEPGRAM_TTS_MODEL,
        api_key="test-deepgram-key",
    )
    assert DEFAULT_DEEPGRAM_TTS_MODEL == "aura-2-andromeda-en"


def test_build_tts_reads_model_override():
    with patch.dict(
        os.environ,
        {
            "DEEPGRAM_API_KEY": "test-deepgram-key",
            "DEEPGRAM_TTS_MODEL": "aura-2-thalia-en",
        },
        clear=True,
    ), patch("voice_pipeline_config.deepgram.TTS") as mock_tts:
        build_tts()
    mock_tts.assert_called_once_with(
        model="aura-2-thalia-en",
        api_key="test-deepgram-key",
    )
