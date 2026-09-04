import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from console_audio import (
    PcmFrameBuffer,
    StreamResampler,
    apply_windows_console_audio_patch,
    mix_to_mono_int16,
    normalize_device_name,
    resolve_wasapi_input_device,
    should_apply_windows_console_audio_patch,
)


def test_should_apply_patch_only_for_windows_console(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["agent.py", "console"])
    assert should_apply_windows_console_audio_patch() is True

    monkeypatch.setattr(sys, "argv", ["agent.py", "dev"])
    assert should_apply_windows_console_audio_patch() is False

    monkeypatch.setenv("DISABLE_CONSOLE_WASAPI", "true")
    monkeypatch.setattr(sys, "argv", ["agent.py", "console"])
    assert should_apply_windows_console_audio_patch() is False


def test_normalize_device_name_strips_parenthetical_suffix():
    assert normalize_device_name("Microphone Array (AMD Audio Device)") == "microphone array"


def test_mix_to_mono_int16_averages_stereo_channels():
    stereo = np.array([[1000, 3000], [2000, 4000]], dtype=np.int16)
    pcm = mix_to_mono_int16(stereo)
    mono = np.frombuffer(pcm, dtype=np.int16)
    assert mono.tolist() == [2000, 3000]


def test_stream_resampler_converts_48k_to_24k():
    source = (np.sin(np.linspace(0, 4 * np.pi, 480, endpoint=False)) * 10000).astype(
        np.int16
    )
    resampler = StreamResampler()
    converted = resampler.convert(source.tobytes(), source_rate=48000, target_rate=24000)
    assert len(converted) > 0
    assert len(converted) % 2 == 0


def test_pcm_frame_buffer_emits_fixed_size_frames():
    buffer = PcmFrameBuffer(frame_samples=2)
    frames = buffer.extend(b"\x01\x00\x02\x00\x03\x00\x04\x00\x05\x00")
    assert len(frames) == 2
    assert frames[0].shape == (2, 1)
    assert frames[1].shape == (2, 1)
    assert len(buffer.extend(b"")) == 0


def test_resolve_wasapi_input_device_matches_by_name():
    fake_devices = [
        {"name": "Mapper - Input", "max_input_channels": 2, "hostapi": 0},
        {
            "name": "Microphone Array (AMD Audio Device)",
            "max_input_channels": 2,
            "hostapi": 1,
            "default_samplerate": 48000.0,
        },
        {
            "name": "Microphone Array (AMD Audio Device)",
            "max_input_channels": 2,
            "hostapi": 0,
            "default_samplerate": 44100.0,
        },
    ]

    with (
        patch("sounddevice.query_devices", side_effect=lambda idx=None, kind=None: fake_devices if idx is None else fake_devices[idx]),
        patch("sounddevice.default", new=MagicMock(device=[2, 3])),
        patch("sounddevice.query_hostapis", return_value=[{"name": "MME"}, {"name": "Windows WASAPI"}]),
    ):
        index, info = resolve_wasapi_input_device(None)

    assert index == 1
    assert info["hostapi"] == 1
    assert info["default_samplerate"] == 48000.0


def test_apply_patch_replaces_console_init_and_mic_setup(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["agent.py", "console"])

    from livekit.agents.cli import _legacy as legacy

    original_init = legacy.AgentsConsole.__init__
    original_set_mic = legacy.AgentsConsole.set_microphone_enabled

    apply_windows_console_audio_patch()
    assert legacy.AgentsConsole.__init__ is not original_init
    assert legacy.AgentsConsole.set_microphone_enabled is not original_set_mic

    apply_windows_console_audio_patch()
    assert legacy.AgentsConsole.__init__ is not original_init
