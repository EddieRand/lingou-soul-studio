# services/companion-server/app/core/dialogue_state.py
"""
8-state dialogue state machine.
Stores in-memory state per base_id.
States: idle / wake_detected / listening / transcribing / thinking / speaking / error / offline_companion
"""

import threading
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from app.core.emotion_engine import make_default_emotion_state


class DialogueStateEnum(str):
    idle = "idle"
    wake_detected = "wake_detected"
    listening = "listening"
    transcribing = "transcribing"
    thinking = "thinking"
    speaking = "speaking"
    error = "error"
    offline_companion = "offline_companion"


@dataclass
class DialogueState:
    state: str = "idle"
    figure_id: Optional[str] = None
    base_id: Optional[str] = None
    wake_source: Optional[str] = None
    started_at: Optional[str] = None


# In-memory store: base_id -> DialogueState
_state_store: dict[str, DialogueState] = {}
_lock = threading.Lock()


def get_state(base_id: str) -> DialogueState:
    """Get current dialogue state for a base."""
    with _lock:
        if base_id not in _state_store:
            _state_store[base_id] = DialogueState(base_id=base_id)
        return _state_store[base_id]


def transition(base_id: str, new_state: str) -> DialogueState:
    """Transition to a new state."""
    with _lock:
        if base_id not in _state_store:
            _state_store[base_id] = DialogueState(base_id=base_id)
        st = _state_store[base_id]
        st.state = new_state
        if new_state in ("wake_detected", "listening", "offline_companion"):
            st.started_at = datetime.utcnow().isoformat()
        return st


def reset(base_id: str) -> DialogueState:
    """Reset to idle."""
    return transition(base_id, "idle")


def set_figure(base_id: str, figure_id: str, wake_source: Optional[str] = None) -> DialogueState:
    """Set active figure for this base's dialogue session."""
    with _lock:
        if base_id not in _state_store:
            _state_store[base_id] = DialogueState(base_id=base_id)
        st = _state_store[base_id]
        st.figure_id = figure_id
        st.wake_source = wake_source
        return st
