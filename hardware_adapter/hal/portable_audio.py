"""Bridge a DeviceHAL into the existing portable voice protocol client."""

from __future__ import annotations

from hardware_adapter.hal.contracts import (
    AudioFrame,
    DeviceHAL,
    IndicatorState,
    MICROPHONE_FORMAT,
    SPEAKER_FORMAT,
)
from hardware_adapter.hal.lifecycle import DeviceHALSupervisor


class HALAudioBackend:
    """AudioBackend-compatible facade that keeps protocol logic board-neutral."""

    def __init__(self, hal: DeviceHAL):
        if hal.microphone.audio_format != MICROPHONE_FORMAT:
            raise ValueError("HAL microphone format is not protocol-compatible")
        if hal.speaker.audio_format != SPEAKER_FORMAT:
            raise ValueError("HAL speaker format is not protocol-compatible")
        self.hal = hal
        self.supervisor = DeviceHALSupervisor(hal)
        self._input_muted = False
        self._output_sequence = 0

    async def start(self) -> None:
        await self.supervisor.start()
        try:
            await self.hal.network.connect()
            await self.hal.indicator.set_state(IndicatorState.CONNECTING)
        except BaseException:
            await self.supervisor.stop()
            raise

    async def stop(self) -> None:
        try:
            if self.hal.network.snapshot().state.value != "offline":
                await self.hal.network.disconnect()
        finally:
            await self.supervisor.stop()

    async def read_input(self) -> bytes:
        while True:
            frame = await self.hal.microphone.read_frame()
            if not self._input_muted:
                return frame.payload

    async def play(self, payload: bytes) -> None:
        frame = AudioFrame(
            payload=bytes(payload),
            sequence=self._output_sequence,
            monotonic_ms=self.hal.clock.monotonic_ms(),
        )
        self._output_sequence += 1
        await self.hal.speaker.write_frame(frame)

    async def stop_playback(self) -> None:
        await self.hal.speaker.abort()

    async def alert(self) -> None:
        await self.hal.indicator.set_state(IndicatorState.ERROR)

    def set_input_muted(self, muted: bool) -> None:
        self._input_muted = muted
        if muted:
            self.hal.microphone.discard_buffer()

    def discard_input_buffer(self) -> int:
        return self.hal.microphone.discard_buffer()

    def metrics_snapshot(self) -> dict:
        snapshot = self.hal.resources.snapshot()
        return {
            "input_overflows": 0,
            "input_queue_overflows": 0,
            "playback_underruns": 0,
            "resource_source": snapshot.source,
            "free_heap_bytes": snapshot.free_heap_bytes,
            "minimum_free_heap_bytes": snapshot.minimum_free_heap_bytes,
            "free_psram_bytes": snapshot.free_psram_bytes,
            "stack_high_water_bytes": snapshot.stack_high_water_bytes,
            "cpu_percent_by_task": snapshot.cpu_percent_by_task,
        }
