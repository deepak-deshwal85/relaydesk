import sys
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from client_config import ClientConfig
from turn_handling_config import (
    DEFAULT_TURN_ENDPOINTING_ALPHA,
    DEFAULT_TURN_ENDPOINTING_MAX_DELAY,
    DEFAULT_TURN_ENDPOINTING_MAX_DELAY_CONSOLE,
    DEFAULT_TURN_ENDPOINTING_MIN_DELAY,
    build_endpointing_options,
    build_interruption_options,
    build_preemptive_generation_options,
    build_turn_handling_options,
)


def _sample_client_config() -> ClientConfig:
    return ClientConfig(
        phone_number="911171366880",
        client_name="Test Client",
        client_email_id="client@example.com",
        greeting_message="Hello.",
    )


@pytest.fixture
def mock_turn_detector():
    with patch(
        "turn_handling_config.inference.TurnDetector",
        return_value=MagicMock(name="turn_detector"),
    ) as detector:
        yield detector


def test_build_endpointing_options_defaults():
    options = build_endpointing_options()
    assert options["mode"] == "dynamic"
    assert options["min_delay"] == DEFAULT_TURN_ENDPOINTING_MIN_DELAY
    assert options["max_delay"] == DEFAULT_TURN_ENDPOINTING_MAX_DELAY
    assert options["alpha"] == DEFAULT_TURN_ENDPOINTING_ALPHA


def test_build_endpointing_options_from_env(monkeypatch):
    monkeypatch.setenv("TURN_ENDPOINTING_MODE", "fixed")
    monkeypatch.setenv("TURN_ENDPOINTING_MIN_DELAY", "0.2")
    monkeypatch.setenv("TURN_ENDPOINTING_MAX_DELAY", "1.5")
    monkeypatch.setenv("TURN_ENDPOINTING_ALPHA", "0.7")

    options = build_endpointing_options()
    assert options["mode"] == "fixed"
    assert options["min_delay"] == 0.2
    assert options["max_delay"] == 1.5
    assert options["alpha"] == 0.7


def test_build_endpointing_options_invalid_mode_falls_back(monkeypatch):
    monkeypatch.setenv("TURN_ENDPOINTING_MODE", "invalid")

    options = build_endpointing_options()
    assert options["mode"] == "dynamic"


def test_build_interruption_options_defaults(monkeypatch):
    monkeypatch.setenv("VOICE_PROVIDER", "legacy")
    options = build_interruption_options()
    assert options["mode"] == "adaptive"
    assert options["min_words"] == 3
    assert options["resume_false_interruption"] is True
    assert options["false_interruption_timeout"] == 2.0


def test_build_interruption_options_from_env(monkeypatch):
    monkeypatch.setenv("TURN_INTERRUPTION_MODE", "vad")
    monkeypatch.setenv("TURN_RESUME_FALSE_INTERRUPTION", "false")
    monkeypatch.setenv("TURN_FALSE_INTERRUPTION_TIMEOUT", "3.5")

    options = build_interruption_options()
    assert options["mode"] == "vad"
    assert options["resume_false_interruption"] is False
    assert options["false_interruption_timeout"] == 3.5


def test_build_preemptive_generation_disabled_when_sync_required():
    options = build_preemptive_generation_options(requires_sync=True)
    assert options == {"enabled": False}


def test_build_preemptive_generation_enabled_when_sync_not_required():
    options = build_preemptive_generation_options(requires_sync=False)
    assert options["enabled"] is True
    assert options["preemptive_tts"] is False
    assert options["max_speech_duration"] == 10.0
    assert options["max_retries"] == 3


def test_build_preemptive_generation_from_env(monkeypatch):
    monkeypatch.setenv("TURN_PREEMPTIVE_TTS", "true")
    monkeypatch.setenv("TURN_PREEMPTIVE_MAX_SPEECH_DURATION", "8.0")
    monkeypatch.setenv("TURN_PREEMPTIVE_MAX_RETRIES", "5")

    options = build_preemptive_generation_options(requires_sync=False)
    assert options["preemptive_tts"] is True
    assert options["max_speech_duration"] == 8.0
    assert options["max_retries"] == 5


def test_build_turn_handling_options_with_rag(mock_turn_detector, monkeypatch):
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")
    monkeypatch.setenv("VOICE_PROVIDER", "legacy")

    with patch(
        "turn_handling_config.requires_sync_turn_completion",
        return_value=True,
    ):
        options = build_turn_handling_options(_sample_client_config())

    mock_turn_detector.assert_called_once_with(version="v1")
    assert options["endpointing"]["mode"] == "dynamic"
    assert options["interruption"]["mode"] == "adaptive"
    assert options["preemptive_generation"] == {"enabled": False}


def test_build_turn_handling_options_without_rag(mock_turn_detector, monkeypatch):
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")
    monkeypatch.setenv("VOICE_PROVIDER", "legacy")

    with patch(
        "turn_handling_config.requires_sync_turn_completion",
        return_value=False,
    ):
        options = build_turn_handling_options(_sample_client_config())

    assert options["preemptive_generation"]["enabled"] is True
    assert options["preemptive_generation"]["preemptive_tts"] is False


def test_build_endpointing_options_console_uses_longer_max_delay(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["agent.py", "console"])
    options = build_endpointing_options()
    assert options["max_delay"] == DEFAULT_TURN_ENDPOINTING_MAX_DELAY_CONSOLE


def test_build_interruption_options_sarvam_uses_vad(monkeypatch):
    monkeypatch.setenv("VOICE_PROVIDER", "sarvam")
    options = build_interruption_options()
    assert options["mode"] == "vad"


def test_build_turn_handling_options_sarvam_uses_stt_turn_detection(monkeypatch):
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")
    monkeypatch.setenv("VOICE_PROVIDER", "sarvam")

    with patch(
        "turn_handling_config.requires_sync_turn_completion",
        return_value=False,
    ):
        options = build_turn_handling_options(_sample_client_config())

    assert options["turn_detection"] == "stt"
