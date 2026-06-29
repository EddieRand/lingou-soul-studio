# hardware_adapter/mock_adapter.py
# Mock hardware adapter for development - keyboard triggered

import threading
from typing import Optional

from hardware_adapter.base import BaseHardwareAdapter
from hardware_adapter.event_protocol import HardwareEvent


class MockHardwareAdapter(BaseHardwareAdapter):
    """Mock adapter for development - triggered programmatically."""

    def __init__(self):
        self._event: Optional[HardwareEvent] = None
        self._listening = False
        self._lock = threading.Lock()

    def trigger_event(self, base_id: str, event_type: str, figure_id: Optional[str] = None) -> HardwareEvent:
        """Programmatically trigger a hardware event (used by API/hardware.py)."""
        from datetime import datetime
        evt = HardwareEvent(
            event_type=event_type,
            base_id=base_id,
            figure_id=figure_id,
            timestamp=datetime.utcnow(),
        )
        with self._lock:
            self._event = evt
        return evt

    def get_current_event(self) -> Optional[HardwareEvent]:
        with self._lock:
            evt = self._event
            self._event = None
            return evt

    def start_listening(self) -> None:
        self._listening = True

    def stop_listening(self) -> None:
        self._listening = False

    def get_figure_id_for_base(self, base_id: str) -> Optional[str]:
        """Mock: reads active_figure_id from base JSON."""
        import sys
        from pathlib import Path
        # Add services/companion-server to path
        srv_path = Path(__file__).parent.parent / "services" / "companion-server"
        if str(srv_path) not in sys.path:
            sys.path.insert(0, str(srv_path))
        try:
            from data.store import get_base
            base = get_base(base_id)
            return base.get("active_figure_id") if base else None
        except Exception:
            return None
