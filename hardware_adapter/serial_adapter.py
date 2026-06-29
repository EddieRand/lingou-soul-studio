# hardware_adapter/serial_adapter.py
# Serial hardware adapter for ESP32 - STUB (not yet implemented)

from typing import Optional

from hardware_adapter.base import BaseHardwareAdapter
from hardware_adapter.event_protocol import HardwareEvent


class SerialHardwareAdapter(BaseHardwareAdapter):
    """
    Serial adapter for ESP32 hardware.
    STUB: To be implemented when ESP32 hardware arrives.
    Expected serial protocol: JSON lines over UART, e.g.
        {"type":"touch","event":"light_touch","base_id":"BASE-001","ts":1234567890}
    """

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self._serial = None
        self._event: Optional[HardwareEvent] = None

    def get_current_event(self) -> HardwareEvent | None:
        # TODO: read from serial, parse JSON, return HardwareEvent
        raise NotImplementedError("SerialHardwareAdapter not yet implemented")

    def start_listening(self) -> None:
        # TODO: open serial connection
        raise NotImplementedError("SerialHardwareAdapter not yet implemented")

    def stop_listening(self) -> None:
        # TODO: close serial connection
        raise NotImplementedError("SerialHardwareAdapter not yet implemented")
