"""Board-independent contracts for the Lingou hardware voice runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class AudioFormat:
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frame_duration_ms: Optional[int] = None
    max_frame_bytes: Optional[int] = None

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if self.sample_width_bytes <= 0:
            raise ValueError("sample_width_bytes must be positive")
        if self.frame_duration_ms is not None and self.frame_duration_ms <= 0:
            raise ValueError("frame_duration_ms must be positive")
        if self.max_frame_bytes is not None and self.max_frame_bytes <= 0:
            raise ValueError("max_frame_bytes must be positive")

    @property
    def frame_bytes(self) -> Optional[int]:
        if self.frame_duration_ms is None:
            return None
        samples = self.sample_rate_hz * self.frame_duration_ms
        if samples % 1000:
            raise ValueError("frame duration does not produce whole samples")
        return (
            samples
            // 1000
            * self.channels
            * self.sample_width_bytes
        )


MICROPHONE_FORMAT = AudioFormat(
    sample_rate_hz=16000,
    channels=1,
    sample_width_bytes=2,
    frame_duration_ms=20,
)

SPEAKER_FORMAT = AudioFormat(
    sample_rate_hz=24000,
    channels=1,
    sample_width_bytes=2,
    max_frame_bytes=4096,
)


@dataclass(frozen=True)
class AudioFrame:
    payload: bytes
    sequence: int
    monotonic_ms: int

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("audio frame payload must not be empty")
        if self.sequence < 0:
            raise ValueError("audio frame sequence must not be negative")
        if self.monotonic_ms < 0:
            raise ValueError("monotonic_ms must not be negative")


class IndicatorState(str, Enum):
    BOOTING = "booting"
    PROVISIONING = "provisioning"
    OFFLINE = "offline"
    CONNECTING = "connecting"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"


class InputEventKind(str, Enum):
    LIGHT_TOUCH = "light_touch"
    HEAVY_PRESS = "heavy_press"
    DOUBLE_TAP = "double_tap"
    BUTTON_PRESS = "button_press"
    FACTORY_RESET_HOLD = "factory_reset_hold"


@dataclass(frozen=True)
class InputEvent:
    kind: InputEventKind
    monotonic_ms: int
    raw_value: Optional[int] = None


class NetworkState(str, Enum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class NetworkSnapshot:
    state: NetworkState
    reconnect_attempts: int = 0
    rssi_dbm: Optional[int] = None
    ip_address: Optional[str] = None


@dataclass(frozen=True)
class ResourceSnapshot:
    monotonic_ms: int
    source: str
    free_heap_bytes: Optional[int] = None
    minimum_free_heap_bytes: Optional[int] = None
    free_psram_bytes: Optional[int] = None
    stack_high_water_bytes: dict[str, int] = field(default_factory=dict)
    cpu_percent_by_task: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.monotonic_ms < 0:
            raise ValueError("monotonic_ms must not be negative")
        for value in (
            self.free_heap_bytes,
            self.minimum_free_heap_bytes,
            self.free_psram_bytes,
        ):
            if value is not None and value < 0:
                raise ValueError("resource byte counts must not be negative")
        if any(value < 0 for value in self.stack_high_water_bytes.values()):
            raise ValueError("stack high-water values must not be negative")
        if any(
            value < 0 or value > 100
            for value in self.cpu_percent_by_task.values()
        ):
            raise ValueError("CPU percentages must be between 0 and 100")


@runtime_checkable
class LifecyclePort(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@runtime_checkable
class MicrophonePort(LifecyclePort, Protocol):
    @property
    def audio_format(self) -> AudioFormat: ...

    async def read_frame(self) -> AudioFrame: ...

    def discard_buffer(self) -> int: ...


@runtime_checkable
class SpeakerPort(LifecyclePort, Protocol):
    @property
    def audio_format(self) -> AudioFormat: ...

    async def write_frame(self, frame: AudioFrame) -> None: ...

    async def abort(self) -> None: ...


@runtime_checkable
class IndicatorPort(LifecyclePort, Protocol):
    async def set_state(self, state: IndicatorState) -> None: ...


@runtime_checkable
class InputPort(LifecyclePort, Protocol):
    async def next_event(self) -> InputEvent: ...


@runtime_checkable
class NetworkPort(LifecyclePort, Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    def snapshot(self) -> NetworkSnapshot: ...


@runtime_checkable
class ClockPort(Protocol):
    def monotonic_ms(self) -> int: ...

    def utc_iso(self) -> str: ...


@runtime_checkable
class SecureStoragePort(LifecyclePort, Protocol):
    def read_secret(self, key: str) -> Optional[bytes]: ...

    def write_secret(self, key: str, value: bytes) -> None: ...

    def delete_secret(self, key: str) -> None: ...


@runtime_checkable
class ResourceMonitorPort(LifecyclePort, Protocol):
    def snapshot(self) -> ResourceSnapshot: ...


@dataclass
class DeviceHAL:
    microphone: MicrophonePort
    speaker: SpeakerPort
    indicator: IndicatorPort
    inputs: InputPort
    network: NetworkPort
    clock: ClockPort
    secure_storage: SecureStoragePort
    resources: ResourceMonitorPort

    def lifecycle_components(self) -> tuple[tuple[str, LifecyclePort], ...]:
        return (
            ("secure_storage", self.secure_storage),
            ("network", self.network),
            ("microphone", self.microphone),
            ("speaker", self.speaker),
            ("inputs", self.inputs),
            ("indicator", self.indicator),
            ("resources", self.resources),
        )
