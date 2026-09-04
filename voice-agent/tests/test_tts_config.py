import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from voice_pipeline_config import (
    DEFAULT_DEEPGRAM_TTS_MODEL,
    build_tts,
    normalize_deepgram_tts_model,
)


def test_normalize_deepgram_tts_model_fixes_andromeda_typo():
    assert normalize_deepgram_tts_model("aura-andromeda-en") == "aura-2-andromeda-en"
    assert normalize_deepgram_tts_model("aura-asteria-en") == "aura-asteria-en"


def test_build_tts_uses_deepgram_aura_defaults():
    with patch.dict(
        os.environ,
        {"DEEPGRAM_API_KEY": "test-deepgram-key", "VOICE_PROVIDER": "legacy"},
        clear=True,
    ), patch("voice_pipeline_config.deepgram.TTS") as mock_tts:
        tts = build_tts()
    mock_tts.assert_called_once_with(
        model=DEFAULT_DEEPGRAM_TTS_MODEL,
        api_key="test-deepgram-key",
    )
    assert tts is mock_tts.return_value


def test_build_tts_reads_env_override():
    with patch.dict(
        os.environ,
        {
            "DEEPGRAM_API_KEY": "test-deepgram-key",
            "DEEPGRAM_TTS_MODEL": "aura-2-thalia-en",
            "VOICE_PROVIDER": "legacy",
        },
        clear=True,
    ), patch("voice_pipeline_config.deepgram.TTS") as mock_tts:
        build_tts()
    mock_tts.assert_called_once_with(
        model="aura-2-thalia-en",
        api_key="test-deepgram-key",
    )
