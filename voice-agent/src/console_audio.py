"""Windows console microphone capture fix for LiveKit Agents.

On some Windows laptops (notably AMD microphone arrays), PortAudio shared-mode
capture via the MME default device returns silence. The same hardware works in
the browser (LiveKit Playground) and in WASAPI exclusive mode at the device's
native sample rate.

This module patches the deprecated rich console (``python src/agent.py console``)
to open the WASAPI input device in exclusive mode, resample to 24 kHz mono, and
disable echo cancellation that can fight laptop microphones.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import numpy as np

logger = logging.getLogger("relaydesk-agent")

TARGET_SAMPLE_RATE = 24000
FRAME_SAMPLES = 240  # 10 ms at 24 kHz
_PATCH_APPLIED = False


def is_windows() -> bool:
    return sys.platform == "win32"


def should_apply_windows_console_audio_patch() -> bool:
    if not is_windows():
        return False
    if os.getenv("DISABLE_CONSOLE_WASAPI", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    return any(arg == "console" for arg in sys.argv[1:])


def find_wasapi_hostapi() -> int | None:
    import sounddevice as sd

    for index, hostapi in enumerate(sd.query_hostapis()):
        if "WASAPI" in hostapi["name"]:
            return index
    return None


def normalize_device_name(name: str) -> str:
    return name.split("(")[0].strip().lower()


def resolve_wasapi_input_device(device: int | str | None) -> tuple[int, dict[str, Any]]:
    """Return the WASAPI input device index and info for a console device selection."""
    import sounddevice as sd

    wasapi_index = find_wasapi_hostapi()
    if wasapi_index is None:
        if device is None:
            device, _ = sd.default.device
        info = dict(sd.query_devices(device, kind="input"))
        return int(device), info

    base_name = ""
    if device is None:
        default_input, _ = sd.default.device
        base_info = sd.query_devices(default_input, kind="input")
        base_name = str(base_info["name"])
    elif isinstance(device, int):
        base_info = sd.query_devices(device, kind="input")
        base_name = str(base_info["name"])
    else:
        base_name = str(device)

    normalized = normalize_device_name(base_name)

    for index, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] <= 0 or dev["hostapi"] != wasapi_index:
            continue
        dev_name = str(dev["name"])
        if isinstance(device, str) and device.lower() in dev_name.lower():
            return index, dict(dev)
        if normalized and normalized in normalize_device_name(dev_name):
            return index, dict(dev)
        if base_name and base_name in dev_name:
            return index, dict(dev)

    for index, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and dev["hostapi"] == wasapi_index:
            logger.warning(
                "no WASAPI name match for %r; using %s",
                base_name or device,
                dev["name"],
            )
            return index, dict(dev)

    if device is None:
        device, _ = sd.default.device
    info = dict(sd.query_devices(device, kind="input"))
    return int(device), info


def mix_to_mono_int16(indata: np.ndarray) -> bytes:
    if indata.ndim == 1:
        mono = indata
    elif indata.shape[1] == 1:
        mono = indata[:, 0]
    else:
        mono = indata.mean(axis=1).astype(np.int16)
    return mono.astype("<i2", copy=False).tobytes()


class PcmFrameBuffer:
    """Accumulate resampled PCM and emit fixed-size 10 ms frames."""

    def __init__(self, *, frame_samples: int = FRAME_SAMPLES) -> None:
        self._frame_bytes = frame_samples * 2
        self._buf = bytearray()

    def extend(self, pcm: bytes) -> list[np.ndarray]:
        self._buf.extend(pcm)
        frames: list[np.ndarray] = []
        while len(self._buf) >= self._frame_bytes:
            chunk = bytes(self._buf[: self._frame_bytes])
            del self._buf[: self._frame_bytes]
            frames.append(np.frombuffer(chunk, dtype=np.int16).reshape(-1, 1))
        return frames


class StreamResampler:
    """Stateful mono resampler for fixed input/output sample rates."""

    def __init__(self) -> None:
        self._remainder = np.array([], dtype=np.float32)
        self._source_pos = 0.0

    def convert(self, pcm: bytes, *, source_rate: int, target_rate: int) -> bytes:
        if source_rate == target_rate:
            return pcm

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return b""

        combined = (
            np.concatenate([self._remainder, samples])
            if self._remainder.size
            else samples
        )
        if combined.size < 2:
            self._remainder = combined
            return b""

        ratio = source_rate / target_rate
        start = self._source_pos
        end = (combined.size - 1) + start
        target_count = int(np.floor((end - start) / ratio)) + 1
        if target_count <= 0:
            self._remainder = combined
            return b""

        source_positions = start + np.arange(target_count, dtype=np.float64) * ratio
        valid = source_positions <= combined.size - 1
        source_positions = source_positions[valid]
        if source_positions.size == 0:
            self._remainder = combined
            self._source_pos = start
            return b""

        resampled = np.interp(
            source_positions,
            np.arange(combined.size, dtype=np.float64),
            combined,
        ).astype(np.int16)

        last_source = source_positions[-1]
        consumed = int(np.floor(last_source))
        self._source_pos = last_source - consumed
        self._remainder = combined[consumed:]

        return resampled.tobytes()


def apply_windows_console_audio_patch() -> None:
    """Patch LiveKit console audio capture for Windows WASAPI exclusive mode."""
    global _PATCH_APPLIED
    if _PATCH_APPLIED or not should_apply_windows_console_audio_patch():
        return

    from livekit import rtc
    from livekit.agents.cli._legacy import AgentsConsole

    original_init = AgentsConsole.__init__
    original_set_microphone_enabled = AgentsConsole.set_microphone_enabled

    def patched_init(self: AgentsConsole, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self._apm = rtc.AudioProcessingModule(
            echo_cancellation=False,
            noise_suppression=True,
            high_pass_filter=True,
            auto_gain_control=True,
        )
        self._wasapi_resampler = StreamResampler()
        self._wasapi_frame_buffer = PcmFrameBuffer()
        self._wasapi_native_rate = TARGET_SAMPLE_RATE

    def wasapi_input_callback(
        self: AgentsConsole,
        indata: np.ndarray,
        frame_count: int,
        time: Any,
        *_: Any,
    ) -> None:
        mono_pcm = mix_to_mono_int16(indata)
        resampled = self._wasapi_resampler.convert(
            mono_pcm,
            source_rate=self._wasapi_native_rate,
            target_rate=TARGET_SAMPLE_RATE,
        )
        for frame in self._wasapi_frame_buffer.extend(resampled):
            self._sd_input_callback(frame, FRAME_SAMPLES, time)

    def patched_set_microphone_enabled(
        self: AgentsConsole,
        enable: bool,
        *,
        device: int | str | None = None,
    ) -> None:
        if not enable:
            original_set_microphone_enabled(self, enable, device=device)
            return

        import sounddevice as sd

        from livekit.agents.cli._legacy import CLIError

        if self._input_stream:
            self._input_stream.close()
            self._input_stream = self._input_name = None

        wasapi_device, device_info = resolve_wasapi_input_device(device)
        native_rate = int(device_info.get("default_samplerate", TARGET_SAMPLE_RATE))
        channels = max(1, min(2, int(device_info.get("max_input_channels", 1))))

        self._input_name = str(device_info.get("name", "Unnamed microphone"))
        self._wasapi_resampler = StreamResampler()
        self._wasapi_frame_buffer = PcmFrameBuffer()
        self._wasapi_native_rate = native_rate

        blocksize = max(int(native_rate * 0.1), FRAME_SAMPLES)
        stream_kwargs: dict[str, Any] = {
            "callback": self._wasapi_input_callback,
            "dtype": "int16",
            "channels": channels,
            "device": wasapi_device,
            "samplerate": native_rate,
            "blocksize": blocksize,
        }

        exclusive = os.getenv("CONSOLE_WASAPI_EXCLUSIVE", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        if exclusive:
            stream_kwargs["extra_settings"] = sd.WasapiSettings(exclusive=True)

        try:
            self._input_stream = sd.InputStream(**stream_kwargs)
            self._input_stream.start()
        except Exception as exc:
            if exclusive:
                logger.warning(
                    "WASAPI exclusive capture failed for %s (%s); retrying shared WASAPI",
                    self._input_name,
                    exc,
                )
                stream_kwargs.pop("extra_settings", None)
                try:
                    self._input_stream = sd.InputStream(**stream_kwargs)
                    self._input_stream.start()
                except Exception:
                    logger.warning(
                        "shared WASAPI capture failed for %s; falling back to default console mic path",
                        self._input_name,
                    )
                    original_set_microphone_enabled(self, enable, device=device)
                    return
            else:
                raise CLIError(
                    "Unable to access the microphone via WASAPI.\n"
                    "Close other apps using the mic (including LiveKit Playground) and retry."
                ) from exc

        logger.info(
            "console mic: using WASAPI %s at %s Hz (%d ch, exclusive=%s, output=%s Hz mono)",
            self._input_name,
            native_rate,
            channels,
            exclusive,
            TARGET_SAMPLE_RATE,
        )

    AgentsConsole.__init__ = patched_init  # type: ignore[method-assign]
    AgentsConsole.set_microphone_enabled = patched_set_microphone_enabled  # type: ignore[method-assign]
    AgentsConsole._wasapi_input_callback = wasapi_input_callback  # type: ignore[attr-defined]
    _PATCH_APPLIED = True
    logger.debug("applied Windows console WASAPI audio patch")
