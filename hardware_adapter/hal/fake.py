"""Deterministic fake HAL for protocol and lifecycle tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Optional

from hardware_adapter.hal.contracts import (
    AudioFormat,
    AudioFrame,
    DeviceHAL,
    IndicatorState,
    InputEvent,
    MICROPHONE_FORMAT,
    NetworkSnapshot,
    NetworkState,
    ResourceSnapshot,
    SPEAKER_FORMAT,
)


class FakeLifecycleComponent:
    def __init__(
        self,
        name: str,
        audit: list[str],
        *,
        fail_on_start: bool = False,
        fail_on_stop: bool = False,
    ):
        self.name = name
        self.audit = audit
        self.fail_on_start = fail_on_start
        self.fail_on_stop = fail_on_stop
        self.started = False

    async def start(self) -> None:
        self.audit.append(f"start:{self.name}")
        if self.fail_on_start:
            raise RuntimeError(f"{self.name} start failure")
        self.started = True

    async def stop(self) -> None:
        self.audit.append(f"stop:{self.name}")
        self.started = False
        if self.fail_on_stop:
            raise RuntimeError(f"{self.name} stop failure")

    def require_started(self) -> None:
        if not self.started:
            raise RuntimeError(f"{self.name} is not started")


class FakeClock:
    def __init__(self, monotonic_ms: int = 1000):
        self._monotonic_ms = monotonic_ms

    def monotonic_ms(self) -> int:
        return self._monotonic_ms

    def utc_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def advance(self, milliseconds: int) -> None:
        if milliseconds < 0:
            raise ValueError("clock cannot move backwards")
        self._monotonic_ms += milliseconds


class FakeMicrophone(FakeLifecycleComponent):
    def __init__(
        self,
        audit: list[str],
        clock: FakeClock,
        *,
        fail_on_start: bool = False,
    ):
        super().__init__(
            "microphone",
            audit,
            fail_on_start=fail_on_start,
        )
        self._clock = clock
        self._frames: asyncio.Queue[AudioFrame] = asyncio.Queue(maxsize=100)
        self._next_sequence = 0

    @property
    def audio_format(self) -> AudioFormat:
        return MICROPHONE_FORMAT

    def push_frame(self, payload: bytes) -> AudioFrame:
        if len(payload) != MICROPHONE_FORMAT.frame_bytes:
            raise ValueError(
                f"microphone frame must be {MICROPHONE_FORMAT.frame_bytes} bytes"
            )
        frame = AudioFrame(
            payload=bytes(payload),
            sequence=self._next_sequence,
            monotonic_ms=self._clock.monotonic_ms(),
        )
        self._next_sequence += 1
        self._frames.put_nowait(frame)
        return frame

    async def read_frame(self) -> AudioFrame:
        self.require_started()
        return await self._frames.get()

    def discard_buffer(self) -> int:
        discarded = 0
        while True:
            try:
                self._frames.get_nowait()
                discarded += 1
            except asyncio.QueueEmpty:
                return discarded


class FakeSpeaker(FakeLifecycleComponent):
    def __init__(
        self,
        audit: list[str],
        *,
        fail_on_start: bool = False,
    ):
        super().__init__("speaker", audit, fail_on_start=fail_on_start)
        self.frames: list[AudioFrame] = []
        self.abort_count = 0

    @property
    def audio_format(self) -> AudioFormat:
        return SPEAKER_FORMAT

    async def write_frame(self, frame: AudioFrame) -> None:
        self.require_started()
        if len(frame.payload) % SPEAKER_FORMAT.sample_width_bytes:
            raise ValueError("speaker frame must contain complete samples")
        if (
            SPEAKER_FORMAT.max_frame_bytes is not None
            and len(frame.payload) > SPEAKER_FORMAT.max_frame_bytes
        ):
            raise ValueError("speaker frame exceeds max_frame_bytes")
        self.frames.append(frame)

    async def abort(self) -> None:
        self.require_started()
        self.abort_count += 1


class FakeIndicator(FakeLifecycleComponent):
    def __init__(self, audit: list[str], *, fail_on_start: bool = False):
        super().__init__("indicator", audit, fail_on_start=fail_on_start)
        self.states: list[IndicatorState] = []

    async def set_state(self, state: IndicatorState) -> None:
        self.require_started()
        self.states.append(state)


class FakeInputs(FakeLifecycleComponent):
    def __init__(self, audit: list[str], *, fail_on_start: bool = False):
        super().__init__("inputs", audit, fail_on_start=fail_on_start)
        self._events: asyncio.Queue[InputEvent] = asyncio.Queue(maxsize=32)

    def push_event(self, event: InputEvent) -> None:
        self._events.put_nowait(event)

    async def next_event(self) -> InputEvent:
        self.require_started()
        return await self._events.get()


class FakeNetwork(FakeLifecycleComponent):
    def __init__(self, audit: list[str], *, fail_on_start: bool = False):
        super().__init__("network", audit, fail_on_start=fail_on_start)
        self._snapshot = NetworkSnapshot(NetworkState.OFFLINE)

    async def connect(self) -> None:
        self.require_started()
        self._snapshot = NetworkSnapshot(
            state=NetworkState.ONLINE,
            reconnect_attempts=self._snapshot.reconnect_attempts,
            rssi_dbm=-45,
            ip_address="192.0.2.10",
        )

    async def disconnect(self) -> None:
        self.require_started()
        self._snapshot = NetworkSnapshot(
            state=NetworkState.OFFLINE,
            reconnect_attempts=self._snapshot.reconnect_attempts,
        )

    def snapshot(self) -> NetworkSnapshot:
        return self._snapshot


class FakeSecureStorage(FakeLifecycleComponent):
    def __init__(self, audit: list[str], *, fail_on_start: bool = False):
        super().__init__(
            "secure_storage",
            audit,
            fail_on_start=fail_on_start,
        )
        self._values: dict[str, bytes] = {}

    def read_secret(self, key: str) -> Optional[bytes]:
        self.require_started()
        value = self._values.get(key)
        return bytes(value) if value is not None else None

    def write_secret(self, key: str, value: bytes) -> None:
        self.require_started()
        if not key or not value:
            raise ValueError("secret key and value must not be empty")
        self._values[key] = bytes(value)

    def delete_secret(self, key: str) -> None:
        self.require_started()
        self._values.pop(key, None)


class FakeResourceMonitor(FakeLifecycleComponent):
    def __init__(
        self,
        audit: list[str],
        clock: FakeClock,
        *,
        fail_on_start: bool = False,
    ):
        super().__init__("resources", audit, fail_on_start=fail_on_start)
        self._clock = clock
        self._snapshot = ResourceSnapshot(
            monotonic_ms=clock.monotonic_ms(),
            source="fake_hal_simulated",
            free_heap_bytes=220000,
            minimum_free_heap_bytes=200000,
            free_psram_bytes=8 * 1024 * 1024,
            stack_high_water_bytes={
                "lingou_control": 2048,
                "lingou_capture": 2304,
                "lingou_playback": 2304,
                "lingou_network": 3072,
                "lingou_diagnostics": 1536,
            },
            cpu_percent_by_task={
                "lingou_control": 2.0,
                "lingou_capture": 8.0,
                "lingou_playback": 6.0,
                "lingou_network": 4.0,
                "lingou_diagnostics": 1.0,
            },
        )

    def snapshot(self) -> ResourceSnapshot:
        self.require_started()
        return replace(
            self._snapshot,
            monotonic_ms=self._clock.monotonic_ms(),
        )


@dataclass
class FakeHALFixture:
    hal: DeviceHAL
    audit: list[str]
    clock: FakeClock
    microphone: FakeMicrophone
    speaker: FakeSpeaker
    indicator: FakeIndicator
    inputs: FakeInputs
    network: FakeNetwork
    secure_storage: FakeSecureStorage
    resources: FakeResourceMonitor


def build_fake_hal(
    *,
    fail_component: Optional[str] = None,
) -> FakeHALFixture:
    audit: list[str] = []
    clock = FakeClock()

    def fails(name: str) -> bool:
        return fail_component == name

    microphone = FakeMicrophone(
        audit,
        clock,
        fail_on_start=fails("microphone"),
    )
    speaker = FakeSpeaker(audit, fail_on_start=fails("speaker"))
    indicator = FakeIndicator(audit, fail_on_start=fails("indicator"))
    inputs = FakeInputs(audit, fail_on_start=fails("inputs"))
    network = FakeNetwork(audit, fail_on_start=fails("network"))
    secure_storage = FakeSecureStorage(
        audit,
        fail_on_start=fails("secure_storage"),
    )
    resources = FakeResourceMonitor(
        audit,
        clock,
        fail_on_start=fails("resources"),
    )
    hal = DeviceHAL(
        microphone=microphone,
        speaker=speaker,
        indicator=indicator,
        inputs=inputs,
        network=network,
        clock=clock,
        secure_storage=secure_storage,
        resources=resources,
    )
    return FakeHALFixture(
        hal=hal,
        audit=audit,
        clock=clock,
        microphone=microphone,
        speaker=speaker,
        indicator=indicator,
        inputs=inputs,
        network=network,
        secure_storage=secure_storage,
        resources=resources,
    )
