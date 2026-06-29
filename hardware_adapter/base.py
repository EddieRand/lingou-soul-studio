# hardware_adapter/base.py
# Abstract base class for hardware adapters

from abc import ABC, abstractmethod
from typing import Optional

from hardware_adapter.event_protocol import HardwareEvent


class BaseHardwareAdapter(ABC):
    """Abstract base for hardware adapters (mock / serial)."""

    @abstractmethod
    def get_current_event(self) -> HardwareEvent | None:
        """Get current hardware event (non-blocking). Returns None if no event."""
        pass

    @abstractmethod
    def start_listening(self) -> None:
        """Start listening for hardware events."""
        pass

    @abstractmethod
    def stop_listening(self) -> None:
        """Stop listening for hardware events."""
        pass

    def get_figure_id_for_base(self, base_id: str) -> str | None:
        """Resolve figure_id from base_id. Override in subclasses."""
        return None
