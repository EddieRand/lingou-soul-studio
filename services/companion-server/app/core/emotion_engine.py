# services/companion-server/app/core/emotion_engine.py
"""
Emotion engine: applies event-based emotion deltas to EmotionState.
Emotion deltas per plan.md §2.7.1:
  figure_placed: happy +10, lonely -8
  light_touch:  happy +5,  attached +2
  heavy_press:  annoyed +8
  double_tap:    attention +10
  idle_timeout:  lonely +15  (future)
Values can accumulate, but are floored at 0.
"""

from typing import Dict

# Event → emotion deltas mapping
EMOTION_DELTAS: Dict[str, Dict[str, int]] = {
    "figure_placed": {"happy": 10, "lonely": -8},
    "light_touch":   {"happy": 5,  "attached": 2},
    "heavy_press":   {"annoyed": 8},
    "double_tap":    {"attention": 10},
    # idle_timeout reserved for future
}

# Default initial emotion state (from plan.md)
DEFAULT_EMOTION_STATE = {
    "happy": 50,
    "lonely": 0,
    "attached": 0,
    "annoyed": 0,
    "attention": 0,
    "sleepy": 0,
    "last_dialogue_at": None,
}


def apply_emotion_delta(current_state: dict, event_type: str) -> dict:
    """
    Apply emotion deltas for event_type to current_state.
    Returns a new updated emotion state dict (does not mutate input).
    Values are floored at 0.
    """
    new_state = dict(current_state)
    deltas = EMOTION_DELTAS.get(event_type, {})

    for emotion, delta in deltas.items():
        if emotion in new_state:
            new_state[emotion] = max(0, new_state[emotion] + delta)

    return new_state


def make_default_emotion_state() -> dict:
    """Return a fresh default emotion state."""
    return dict(DEFAULT_EMOTION_STATE)
