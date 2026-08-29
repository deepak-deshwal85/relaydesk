import sys
from pathlib import Path
from unittest.mock import patch

from livekit.agents.types import NOT_GIVEN

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent import build_room_options


def test_console_mode_skips_ai_coustics() -> None:
    with patch.object(sys, "argv", ["agent.py", "console"]):
        options = build_room_options()
    assert options.audio_input is NOT_GIVEN or options.audio_input is None


def test_production_mode_enables_ai_coustics() -> None:
    with patch.object(sys, "argv", ["agent.py", "start"]):
        options = build_room_options()
    assert options.audio_input is not None
    assert options.audio_input.noise_cancellation is not None
