# hardware_adapter/event_protocol.py
# Unified event protocol for hardware events (Mock or ESP32)

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# String-based touch type (not importing from TS package)
TouchType = str  # "figure_placed" | "light_touch" | "heavy_press" | "double_tap"


@dataclass
class HardwareEvent:
    """Unified hardware event format - used by both mock and serial adapters."""

    event_type: str  # TouchType
    base_id: str
    figure_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    raw_data: Optional[dict] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "base_id": self.base_id,
            "figure_id": self.figure_id,
            "timestamp": self.timestamp.isoformat(),
            "raw_data": self.raw_data,
        }
