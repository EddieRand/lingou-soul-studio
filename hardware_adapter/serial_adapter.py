# hardware_adapter/serial_adapter.py
# Serial hardware adapter for ESP32 Lingou base events.

from __future__ import annotations

import queue
import re
import threading
from typing import Optional

from hardware_adapter.base import BaseHardwareAdapter
from hardware_adapter.event_protocol import HardwareEvent


FSR_LINE_RE = re.compile(r"^FSR_RAW=(?P<raw>\d+)\s+STATE=(?P<state>[A-Z_]+)")
STATE_CHANGED_RE = re.compile(r"^STATE_CHANGED=(?P<state>[A-Z_]+)")
EVENT_RE = re.compile(r"^EVENT=(?P<event>[A-Z_]+)(?:\s+VALUE=(?P<value>-?\d+))?")

STATE_TO_EVENT = {
    "LIGHT_TOUCH": "light_touch",
    "HEAVY_PRESS": "heavy_press",
}

FIRMWARE_EVENT_TO_EVENT = {
    "FIGURE_PLACED": "figure_placed",
    "DOUBLE_TAP": "double_tap",
    "DOUBLE_TAP_WAKE": "double_tap",
}


class SerialHardwareAdapter(BaseHardwareAdapter):
    """
    Serial adapter for ESP32 hardware.

    Current ESP32 firmware prints text lines such as:
        FSR_RAW=4095 STATE=NO_TOUCH
        STATE_CHANGED=LIGHT_TOUCH
        EVENT=KNOCK_EDGE VALUE=1

    This adapter maps stable high-level events into Lingou's existing touch
    protocol. Raw knock edges are preserved in raw_data, but are not promoted
    to double_tap until firmware or a tap-state layer emits DOUBLE_TAP_WAKE.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        *,
        base_id: str,
        emit_raw_knock: bool = False,
    ):
        if not base_id.strip():
            raise ValueError("base_id must be explicit and non-empty")
        self.port = port
        self.baudrate = baudrate
        self.base_id = base_id.strip()
        self.emit_raw_knock = emit_raw_knock
        self._serial = None
        self._events: queue.Queue[HardwareEvent] = queue.Queue()
        self._listening = False
        self._thread: threading.Thread | None = None
        self.last_fsr_raw: int | None = None
        self.last_fsr_state: str | None = None

    def parse_line(self, line: str) -> HardwareEvent | None:
        """Parse one ESP32 log line into a Lingou hardware event, if any."""
        line = line.strip()
        if not line:
            return None

        fsr_match = FSR_LINE_RE.match(line)
        if fsr_match:
            self.last_fsr_raw = int(fsr_match.group("raw"))
            self.last_fsr_state = fsr_match.group("state")
            return None

        state_match = STATE_CHANGED_RE.match(line)
        if state_match:
            state = state_match.group("state")
            self.last_fsr_state = state
            event_type = STATE_TO_EVENT.get(state)
            if not event_type:
                return None
            return HardwareEvent(
                event_type=event_type,
                base_id=self.base_id,
                raw_data={
                    "source": "esp32",
                    "line": line,
                    "fsr_raw": self.last_fsr_raw,
                    "state": state,
                },
            )

        event_match = EVENT_RE.match(line)
        if event_match:
            firmware_event = event_match.group("event")
            value = event_match.group("value")
            raw_data = {
                "source": "esp32",
                "line": line,
                "firmware_event": firmware_event,
                "value": int(value) if value is not None else None,
            }

            event_type = FIRMWARE_EVENT_TO_EVENT.get(firmware_event)
            if event_type:
                return HardwareEvent(
                    event_type=event_type,
                    base_id=self.base_id,
                    raw_data=raw_data,
                )

            if firmware_event == "KNOCK_EDGE" and self.emit_raw_knock:
                return HardwareEvent(
                    event_type="knock_edge",
                    base_id=self.base_id,
                    raw_data=raw_data,
                )

        return None

    def _listen_loop(self) -> None:
        while self._listening and self._serial:
            raw_line = self._serial.readline()
            if not raw_line:
                continue
            try:
                line = raw_line.decode("utf-8", errors="replace")
            except AttributeError:
                line = str(raw_line)
            event = self.parse_line(line)
            if event:
                self._events.put(event)

    def get_current_event(self) -> HardwareEvent | None:
        try:
            return self._events.get_nowait()
        except queue.Empty:
            return None

    def start_listening(self) -> None:
        if self._listening:
            return

        try:
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is required for SerialHardwareAdapter. "
                "Install it with: python3 -m pip install pyserial"
            ) from exc

        self._serial = serial.Serial(self.port, self.baudrate, timeout=0.1)
        self._listening = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop_listening(self) -> None:
        self._listening = False
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        if self._serial:
            self._serial.close()
            self._serial = None
