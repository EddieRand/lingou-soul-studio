# services/companion-server/app/core/wake_engine.py
"""
Wake detection engine.
MVP: text-matching or trigger-based wake.
- voice_wake: match text against active figure's wake_names
- double_tap / long_press: direct wake
Returns True if wake succeeded.
"""

import sys
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from data.store import get_base, get_figure
from app.core.dialogue_state import transition, set_figure


def detect_wake(base_id: str, trigger: str, text: Optional[str] = None) -> bool:
    """
    Attempt to wake dialogue for base_id.

    trigger: "voice_wake" | "double_tap" | "long_press"
    text: user speech text (only used for voice_wake)

    Returns True if wake succeeded (matched wake name or direct trigger).
    """
    # Resolve active figure
    base = get_base(base_id)
    if not base:
        return False

    figure_id = base.get("active_figure_id")
    if not figure_id:
        return False

    figure = get_figure(figure_id)
    if not figure:
        return False

    # Direct triggers always succeed
    if trigger in ("double_tap", "long_press"):
        set_figure(base_id, figure_id, wake_source=trigger)
        transition(base_id, "wake_detected")
        transition(base_id, "listening")
        return True

    # voice_wake: match text against wake_names
    if trigger == "voice_wake":
        if not text:
            return False
        wake_names = figure.get("wake_names", [])
        # Case-insensitive prefix match
        text_lower = text.lower().strip()
        for name in wake_names:
            if name.lower().strip() in text_lower or text_lower.startswith(name.lower().strip()):
                set_figure(base_id, figure_id, wake_source="voice_wake")
                transition(base_id, "wake_detected")
                transition(base_id, "listening")
                return True
        return False

    return False
