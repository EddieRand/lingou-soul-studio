"""Portable Linux/macOS carrier for the Lingou device voice protocol."""

from __future__ import annotations

import argparse
import asyncio
from array import array
from dataclasses import dataclass, replace
import json
import math
import os
import signal
import ssl
import sys
import time
from typing import Any, Callable, Optional, Protocol
from urllib.parse import urlparse


DEVICE_PROTOCOL = "lingou.device.voice.v1"
DEFAULT_DEVICE_URL = "ws://127.0.0.1:8000/api/asr/device-stream"
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
MAX_OUTPUT_FRAME_BYTES = 4096
PLAYBACK_QUEUE_CAPACITY = 8
INPUT_FRAME_SAMPLES = 320
INPUT_FRAME_BYTES = INPUT_FRAME_SAMPLES * SAMPLE_WIDTH_BYTES
SESSION_REPLACED_CLOSE_CODE = 4410
WEBSOCKET_CLOSE_TIMEOUT_SECONDS = 2


@dataclass(frozen=True)
class AudioChunkDescriptor:
    session_id: str
    turn_id: str
    audio_id: str
    chunk_index: int
    chunk_count: int
    byte_length: int
    sample_rate: int
    discard: bool = False


@dataclass
class AudioStreamState:
    session_id: str
    turn_id: str
    chunk_count: int
    next_chunk_index: int = 0


class AudioBackend(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def read_input(self) -> bytes: ...

    async def play(self, payload: bytes) -> None: ...

    async def stop_playback(self) -> None: ...

    async def alert(self) -> None: ...

    def set_input_muted(self, muted: bool) -> None: ...

    def discard_input_buffer(self) -> int: ...


class SoundDeviceAudioBackend:
    """Raw PCM audio using PortAudio through python-sounddevice."""

    def __init__(
        self,
        *,
        input_device: Optional[str | int] = None,
        output_device: Optional[str | int] = None,
    ):
        self.input_device = input_device
        self.output_device = output_device
        self._input_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._input_stream: Any = None
        self._output_stream: Any = None
        self._input_muted = False
        self._output_lock = asyncio.Lock()
        self._input_overflows = 0
        self._input_queue_overflows = 0
        self._playback_underruns = 0

    @staticmethod
    def _sounddevice():
        try:
            import sounddevice
        except ImportError as exc:
            raise RuntimeError(
                "sounddevice is required; install "
                "hardware_adapter/requirements-portable-device.txt"
            ) from exc
        return sounddevice

    @classmethod
    def list_devices(cls) -> str:
        return str(cls._sounddevice().query_devices())

    def _enqueue_input(self, payload: bytes) -> None:
        if self._input_muted:
            return
        try:
            self._input_queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._input_queue_overflows += 1
            try:
                self._input_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._input_queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def _input_callback(self, indata, frames, _time_info, status) -> None:
        if status:
            print(f"[audio:input] {status}", file=sys.stderr)
            if getattr(status, "input_overflow", False):
                self._input_overflows += 1
        if frames <= 0 or self._loop is None or self._input_muted:
            return
        self._loop.call_soon_threadsafe(self._enqueue_input, bytes(indata))

    async def start(self) -> None:
        sounddevice = self._sounddevice()
        self._loop = asyncio.get_running_loop()
        try:
            self._input_stream = sounddevice.RawInputStream(
                samplerate=INPUT_SAMPLE_RATE,
                blocksize=INPUT_FRAME_SAMPLES,
                device=self.input_device,
                channels=CHANNELS,
                dtype="int16",
                callback=self._input_callback,
            )
            self._output_stream = sounddevice.RawOutputStream(
                samplerate=OUTPUT_SAMPLE_RATE,
                blocksize=0,
                device=self.output_device,
                channels=CHANNELS,
                dtype="int16",
            )
            self._input_stream.start()
            self._output_stream.start()
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        async with self._output_lock:
            for stream in (self._input_stream, self._output_stream):
                if stream is None:
                    continue
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            self._input_stream = None
            self._output_stream = None

    async def read_input(self) -> bytes:
        return await self._input_queue.get()

    async def play(self, payload: bytes) -> None:
        if not payload or len(payload) % SAMPLE_WIDTH_BYTES:
            raise ValueError("output PCM must contain complete int16 samples")
        async with self._output_lock:
            output_stream = self._output_stream
            if output_stream is None:
                raise RuntimeError("output stream is not started")
        underflowed = await asyncio.to_thread(output_stream.write, payload)
        if underflowed:
            self._playback_underruns += 1

    async def stop_playback(self) -> None:
        async with self._output_lock:
            if self._output_stream is None:
                return
            try:
                self._output_stream.abort()
            finally:
                self._output_stream.start()

    async def alert(self) -> None:
        samples = array("h")
        for frequency, duration_ms in ((330, 120), (220, 180)):
            count = OUTPUT_SAMPLE_RATE * duration_ms // 1000
            for index in range(count):
                value = int(
                    math.sin(2 * math.pi * frequency * index / OUTPUT_SAMPLE_RATE)
                    * 6000
                )
                samples.append(value)
            samples.extend([0] * (OUTPUT_SAMPLE_RATE * 60 // 1000))
        await self.play(samples.tobytes())

    def discard_input_buffer(self) -> int:
        discarded = 0
        while True:
            try:
                self._input_queue.get_nowait()
                discarded += 1
            except asyncio.QueueEmpty:
                return discarded

    def metrics_snapshot(self) -> dict[str, int]:
        return {
            "input_overflows": self._input_overflows,
            "input_queue_overflows": self._input_queue_overflows,
            "playback_underruns": self._playback_underruns,
        }

    def set_input_muted(self, muted: bool) -> None:
        self._input_muted = muted
        if muted:
            self.discard_input_buffer()


class PortableVoiceClient:
    def __init__(
        self,
        *,
        server_url: str,
        device_credential: str,
        audio: AudioBackend,
        reconnect_initial_seconds: float = 1.0,
        reconnect_max_seconds: float = 15.0,
        observation_sink: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        parsed = urlparse(server_url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
            raise ValueError("server_url must be a ws:// or wss:// URL")
        if not device_credential or "." not in device_credential:
            raise ValueError("device credential must use <base-id>.<secret>")
        self.server_url = server_url
        self.device_credential = device_credential
        self.audio = audio
        self.reconnect_initial_seconds = reconnect_initial_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self.observation_sink = observation_sink
        self.stop_event = asyncio.Event()
        self.resume_event = asyncio.Event()
        self.connected_event = asyncio.Event()
        self.provider_ready_event = asyncio.Event()
        self.final_text_event = asyncio.Event()
        self.reply_text_event = asyncio.Event()
        self.turn_metrics_event = asyncio.Event()
        self.paused_for_replacement = False
        self.server_speaking = False
        self.session_id = ""
        self.current_turn_id = ""
        self.websocket: Any = None
        self.pending_binary: Optional[AudioChunkDescriptor] = None
        self.started_audio_ids: set[str] = set()
        self.active_audio_ids: dict[str, AudioChunkDescriptor] = {}
        self.audio_streams: dict[str, AudioStreamState] = {}
        self.completed_audio_ids: set[str] = set()
        self.cancelled_turns: set[tuple[str, str]] = set()
        self.cancelled_audio_ids: set[tuple[str, str, str]] = set()
        self.last_final_text = ""
        self.last_reply_text = ""
        self.last_turn_metrics: dict[str, Any] = {}
        self.last_completed_audio_id = ""
        self.playback_completed_event = asyncio.Event()
        self._playback_queue: asyncio.Queue[
            tuple[int, float, AudioChunkDescriptor, bytes]
        ] = asyncio.Queue(maxsize=PLAYBACK_QUEUE_CAPACITY)
        self._playback_task: Optional[asyncio.Task] = None
        self._playback_generation = 0
        self._send_lock = asyncio.Lock()
        self._received_audio_ids: set[str] = set()
        self._observation_sequence = 0
        self._counters = {
            "connection_attempts": 0,
            "successful_connections": 0,
            "uplink_frames": 0,
            "uplink_bytes": 0,
            "downlink_frames": 0,
            "downlink_bytes": 0,
            "dropped_input_frames": 0,
            "reconnect_attempts": 0,
            "playback_overflows": 0,
            "playback_dropped_frames": 0,
            "playback_max_queue_depth": 0,
            "playback_max_queue_wait_ms": 0.0,
        }

    def _observe(self, event: str, **details: Any) -> None:
        sink = self.observation_sink
        if sink is None:
            return
        self._observation_sequence += 1
        payload = {
            "sequence": self._observation_sequence,
            "event": event,
            "monotonic_ms": round(time.monotonic() * 1000, 3),
            "session_id": self.session_id or None,
            "turn_id": self.current_turn_id or None,
            **details,
        }
        try:
            sink(payload)
        except Exception as exc:
            print(
                f"[carrier:metrics] observation sink failed: {exc}",
                file=sys.stderr,
            )

    def metrics_snapshot(self) -> dict[str, Any]:
        audio_metrics_reader = getattr(self.audio, "metrics_snapshot", None)
        audio_metrics = (
            audio_metrics_reader()
            if callable(audio_metrics_reader)
            else {}
        )
        return {
            **self._counters,
            "dropped_input_frames": (
                self._counters["dropped_input_frames"]
                + int(audio_metrics.get("input_queue_overflows", 0))
            ),
            "input_overflows": audio_metrics.get("input_overflows"),
            "input_queue_overflows": audio_metrics.get(
                "input_queue_overflows"
            ),
            "playback_underruns": audio_metrics.get("playback_underruns"),
            "session_id": self.session_id or None,
            "turn_id": self.current_turn_id or None,
            "active_audio_count": len(self.active_audio_ids),
            "queued_audio_frames": self._playback_queue.qsize(),
        }

    def _discard_input_buffer(self) -> None:
        discard = getattr(self.audio, "discard_input_buffer", None)
        if callable(discard):
            discarded = int(discard() or 0)
        else:
            self.audio.set_input_muted(True)
            self.audio.set_input_muted(False)
            discarded = 0
        if discarded:
            self._counters["dropped_input_frames"] += discarded
            self._observe("input_buffer_discarded", frames=discarded)

    def request_stop(self) -> None:
        self.stop_event.set()
        self.resume_event.set()

    async def interrupt_or_resume(self) -> None:
        if self.paused_for_replacement:
            print("[carrier] resuming device voice")
            self.paused_for_replacement = False
            self.resume_event.set()
            return
        if not self.server_speaking or self.websocket is None:
            return
        if self.session_id and self.current_turn_id:
            self.cancelled_turns.add((self.session_id, self.current_turn_id))
        self._observe("cancel_requested")
        await self._fail_active_audio("carrier_interrupted")
        await self._send_json({
            "type": "cancel_turn",
            "session_id": self.session_id,
        })

    async def run(self) -> None:
        await self.audio.start()
        self._observe("carrier_started")
        try:
            delay = self.reconnect_initial_seconds
            while not self.stop_event.is_set():
                if self.paused_for_replacement:
                    print(
                        "[carrier] H5 owns this base; send SIGUSR1 or press "
                        "Enter to resume"
                    )
                    self.resume_event.clear()
                    await self.resume_event.wait()
                    if self.stop_event.is_set():
                        break
                connected_at = asyncio.get_running_loop().time()
                connection_error: Optional[Exception] = None
                self._counters["connection_attempts"] += 1
                if self._counters["connection_attempts"] > 1:
                    self._counters["reconnect_attempts"] += 1
                    self._observe(
                        "reconnect_started",
                        retry_delay_ms=round(delay * 1000, 1),
                    )
                self._observe(
                    "connection_attempt",
                    attempt=self._counters["connection_attempts"],
                )
                try:
                    await self._run_connection()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    connection_error = exc
                    if self.stop_event.is_set():
                        break
                    code = getattr(exc, "code", None)
                    if code == SESSION_REPLACED_CLOSE_CODE:
                        self.paused_for_replacement = True
                        continue
                    print(f"[carrier:error] {type(exc).__name__}: {exc}")
                    await self.audio.alert()
                if self.stop_event.is_set() or self.paused_for_replacement:
                    continue
                if connection_error is None:
                    print("[carrier] connection closed; retrying with backoff")
                connected_for = asyncio.get_running_loop().time() - connected_at
                if connected_for >= 30:
                    delay = self.reconnect_initial_seconds
                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(),
                        timeout=delay,
                    )
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self.reconnect_max_seconds)
        finally:
            try:
                await self._reset_connection_state(report_failure=False)
            finally:
                await self.audio.stop()
                self._observe("carrier_stopped", counters=self.metrics_snapshot())

    async def _run_connection(self) -> None:
        import websockets

        ssl_context = ssl.create_default_context() if self.server_url.startswith("wss://") else None
        headers = {"Authorization": f"Device {self.device_credential}"}
        print(f"[carrier] connecting to {self.server_url}")
        try:
            async with websockets.connect(
                self.server_url,
                subprotocols=[DEVICE_PROTOCOL],
                additional_headers=headers,
                ssl=ssl_context,
                ping_interval=15,
                ping_timeout=5,
                close_timeout=WEBSOCKET_CLOSE_TIMEOUT_SECONDS,
                max_size=2 * 1024 * 1024,
            ) as websocket:
                if websocket.subprotocol != DEVICE_PROTOCOL:
                    raise RuntimeError(
                        "server did not accept the device voice protocol"
                    )
                self.websocket = websocket
                self._discard_input_buffer()
                self.connected_event.set()
                self._counters["successful_connections"] += 1
                self._observe(
                    "socket_connected",
                    connection=self._counters["successful_connections"],
                )
                if self._counters["successful_connections"] > 1:
                    self._observe("reconnect_completed")
                print("[carrier] connected; listening")
                sender = asyncio.create_task(
                    self._send_microphone(websocket),
                    name="lingou-carrier-microphone",
                )
                receiver = asyncio.create_task(
                    self._receive_server(websocket),
                    name="lingou-carrier-server",
                )
                stopper = asyncio.create_task(
                    self.stop_event.wait(),
                    name="lingou-carrier-stop",
                )
                done, pending = await asyncio.wait(
                    {sender, receiver, stopper},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    if task is stopper:
                        try:
                            await asyncio.wait_for(
                                websocket.close(),
                                timeout=WEBSOCKET_CLOSE_TIMEOUT_SECONDS,
                            )
                        except asyncio.TimeoutError:
                            pass
                        continue
                    exception = task.exception()
                    if exception is not None:
                        raise exception
        finally:
            if self.websocket is not None:
                self._observe("socket_disconnected")
            await self._reset_connection_state(report_failure=False)

    async def _send_microphone(self, websocket) -> None:
        while True:
            payload = await self.audio.read_input()
            if self.server_speaking or not payload:
                continue
            if len(payload) != INPUT_FRAME_BYTES:
                raise RuntimeError(
                    f"microphone frame must be {INPUT_FRAME_BYTES} bytes"
                )
            async with self._send_lock:
                await websocket.send(payload)
            self._counters["uplink_frames"] += 1
            self._counters["uplink_bytes"] += len(payload)

    async def _receive_server(self, websocket) -> None:
        async for item in websocket:
            if isinstance(item, bytes):
                await self._handle_audio_frame(item)
                continue
            try:
                payload = json.loads(item)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                await self._handle_server_message(payload)

    async def _handle_server_message(self, payload: dict) -> None:
        message_type = str(payload.get("type") or "")

        if message_type == "status":
            session_id = str(payload.get("session_id") or "")
            if not session_id:
                raise RuntimeError("server status is missing session_id")
            if self.session_id and session_id != self.session_id:
                raise RuntimeError("server changed session_id on an active connection")
            if payload.get("status") == "listening":
                if payload.get("audio_format") != "pcm":
                    raise RuntimeError("server did not negotiate PCM output")
                if int(payload.get("audio_sample_rate", 0)) != OUTPUT_SAMPLE_RATE:
                    raise RuntimeError("server output sample rate is not 24 kHz")
                if not self.session_id:
                    self._clear_session_observations()
                    self.session_id = session_id
                    self._observe(
                        "session_started",
                        audio_format=payload.get("audio_format"),
                        audio_sample_rate=payload.get("audio_sample_rate"),
                    )
            elif not self.session_id:
                raise RuntimeError("server sent runtime status before negotiation")
            elif payload.get("status") in {"ready", "reconnected"}:
                self.provider_ready_event.set()
                self._observe(
                    "provider_ready",
                    provider_status=payload.get("status"),
                )
            return
        if not self._message_matches_current_session(payload):
            if message_type == "audio_chunk":
                if self.pending_binary is not None:
                    raise RuntimeError(
                        "audio metadata arrived before prior binary frame"
                    )
                self.pending_binary = self._parse_audio_descriptor(
                    payload,
                    discard=True,
                )
            return
        if message_type == "speaking":
            turn_id = str(payload.get("turn_id") or "")
            if not self._accept_turn(turn_id, allow_new=payload.get("status") == "start"):
                return
            self.server_speaking = payload.get("status") == "start"
            self.audio.set_input_muted(self.server_speaking)
            return
        if message_type == "final":
            turn_id = str(payload.get("turn_id") or "")
            if turn_id and not self._accept_turn(turn_id, allow_new=True):
                return
            self.last_final_text = str(payload.get("text") or "")
            self.final_text_event.set()
            self._observe("speech_finalized_received")
            return
        if message_type == "reply":
            turn_id = str(payload.get("turn_id") or "")
            if turn_id and not self._accept_turn(turn_id, allow_new=False):
                return
            self.last_reply_text = str(payload.get("reply") or "")
            self.reply_text_event.set()
            self._observe("reply_completed_received")
            return
        if message_type == "turn_metrics":
            self.last_turn_metrics = dict(payload)
            self.turn_metrics_event.set()
            self._observe(
                "turn_metrics_received",
                turn_status=payload.get("status"),
                timings=payload.get("timings"),
            )
            return
        if message_type == "audio_chunk":
            if self.pending_binary is not None:
                raise RuntimeError("audio metadata arrived before prior binary frame")
            descriptor = self._parse_audio_descriptor(payload)
            identity = (
                descriptor.session_id,
                descriptor.turn_id,
                descriptor.audio_id,
            )
            if (
                (descriptor.session_id, descriptor.turn_id) in self.cancelled_turns
                or identity in self.cancelled_audio_ids
                or not self._accept_turn(
                    descriptor.turn_id,
                    allow_new=not bool(self.current_turn_id),
                )
            ):
                self.pending_binary = replace(descriptor, discard=True)
                return
            stream = self.audio_streams.get(descriptor.audio_id)
            if stream is None:
                if (
                    descriptor.audio_id in self.completed_audio_ids
                    or descriptor.chunk_index != 0
                ):
                    raise RuntimeError("audio chunks must start at index 0")
                stream = AudioStreamState(
                    session_id=descriptor.session_id,
                    turn_id=descriptor.turn_id,
                    chunk_count=descriptor.chunk_count,
                )
                self.audio_streams[descriptor.audio_id] = stream
            if (
                stream.session_id != descriptor.session_id
                or stream.turn_id != descriptor.turn_id
                or stream.chunk_count != descriptor.chunk_count
            ):
                raise RuntimeError("audio chunk identity or count changed")
            if descriptor.chunk_index != stream.next_chunk_index:
                raise RuntimeError("audio chunks are missing, duplicated, or out of order")
            self.pending_binary = descriptor
            self.active_audio_ids[descriptor.audio_id] = descriptor
            return
        if message_type in {"stop_audio", "turn_cancelled"}:
            turn_id = str(payload.get("turn_id") or "")
            if not turn_id or turn_id != self.current_turn_id:
                return
            turn_key = (self.session_id, turn_id)
            if turn_key in self.cancelled_turns:
                return
            self.cancelled_turns.add(turn_key)
            await self._reset_playback(report_failure=False)
            return
        if message_type == "session_replaced":
            self.paused_for_replacement = True
            await self._reset_playback(report_failure=False)
            return
        if message_type == "audio_output" and payload.get("stage") == "failed":
            turn_id = str(payload.get("turn_id") or "")
            if turn_id and turn_id != self.current_turn_id:
                return
            await self._reset_playback(report_failure=False)
            await self.audio.alert()
            return
        if message_type == "error":
            print(f"[carrier:server] {payload.get('message', 'unknown error')}")

    async def _handle_audio_frame(self, payload: bytes) -> None:
        descriptor = self.pending_binary
        self.pending_binary = None
        if descriptor is None:
            raise RuntimeError("binary PCM arrived without metadata")
        if descriptor.discard:
            return
        if descriptor.byte_length and len(payload) != descriptor.byte_length:
            raise RuntimeError("binary PCM length does not match metadata")
        if (
            not payload
            or len(payload) > MAX_OUTPUT_FRAME_BYTES
            or len(payload) % SAMPLE_WIDTH_BYTES
        ):
            raise RuntimeError("binary PCM frame must be 2..4096 even bytes")
        stream = self.audio_streams.get(descriptor.audio_id)
        if stream is None or descriptor.chunk_index != stream.next_chunk_index:
            raise RuntimeError("audio chunk state changed before binary frame")
        stream.next_chunk_index += 1
        self._counters["downlink_frames"] += 1
        self._counters["downlink_bytes"] += len(payload)
        if descriptor.audio_id not in self._received_audio_ids:
            self._received_audio_ids.add(descriptor.audio_id)
            self._observe(
                "first_audio_received",
                audio_id=descriptor.audio_id,
                chunk_count=descriptor.chunk_count,
                chunk_bytes=len(payload),
            )
        try:
            self._playback_queue.put_nowait((
                self._playback_generation,
                time.monotonic(),
                descriptor,
                bytes(payload),
            ))
        except asyncio.QueueFull as exc:
            self._counters["playback_overflows"] += 1
            self._counters["playback_dropped_frames"] += 1
            self._observe(
                "playback_queue_overflow",
                audio_id=descriptor.audio_id,
                queue_capacity=PLAYBACK_QUEUE_CAPACITY,
            )
            await self._fail_active_audio("playback_queue_overflow")
            raise RuntimeError("playback queue is full") from exc
        self._counters["playback_max_queue_depth"] = max(
            self._counters["playback_max_queue_depth"],
            self._playback_queue.qsize(),
        )
        self._ensure_playback_worker()
        await asyncio.sleep(0)

    def _parse_audio_descriptor(
        self,
        payload: dict,
        *,
        discard: bool = False,
    ) -> AudioChunkDescriptor:
        try:
            descriptor = AudioChunkDescriptor(
                session_id=str(payload.get("session_id") or ""),
                turn_id=str(payload.get("turn_id") or ""),
                audio_id=str(payload.get("audio_id") or ""),
                chunk_index=int(payload.get("chunk_index", -1)),
                chunk_count=int(payload.get("chunk_count", 0)),
                byte_length=int(payload.get("chunk_byte_length", 0)),
                sample_rate=int(payload.get("sample_rate", 0)),
                discard=discard,
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError("invalid audio_chunk descriptor") from exc
        if (
            not descriptor.session_id
            or not descriptor.turn_id
            or not descriptor.audio_id
            or descriptor.chunk_index < 0
            or descriptor.chunk_count <= 0
            or descriptor.chunk_index >= descriptor.chunk_count
            or descriptor.byte_length <= 0
            or descriptor.byte_length > MAX_OUTPUT_FRAME_BYTES
            or descriptor.byte_length % SAMPLE_WIDTH_BYTES
            or descriptor.sample_rate != OUTPUT_SAMPLE_RATE
            or payload.get("audio_format") != "pcm"
            or payload.get("channels") != CHANNELS
            or payload.get("sample_format") != "s16le"
        ):
            raise RuntimeError("invalid audio_chunk descriptor")
        return descriptor

    def _message_matches_current_session(self, payload: dict) -> bool:
        return bool(
            self.session_id
            and str(payload.get("session_id") or "") == self.session_id
        )

    def _accept_turn(self, turn_id: str, *, allow_new: bool) -> bool:
        if not turn_id:
            return False
        if not self.current_turn_id:
            if not allow_new:
                return False
            self.current_turn_id = turn_id
            self.last_completed_audio_id = ""
            self.playback_completed_event.clear()
            return True
        if turn_id == self.current_turn_id:
            return True
        if not allow_new:
            return False
        self.current_turn_id = turn_id
        self.last_completed_audio_id = ""
        self.playback_completed_event.clear()
        return True

    def _audio_is_cancelled(self, descriptor: AudioChunkDescriptor) -> bool:
        return (
            descriptor.session_id != self.session_id
            or descriptor.turn_id != self.current_turn_id
            or (descriptor.session_id, descriptor.turn_id) in self.cancelled_turns
            or (
                descriptor.session_id,
                descriptor.turn_id,
                descriptor.audio_id,
            ) in self.cancelled_audio_ids
        )

    def _ensure_playback_worker(self) -> None:
        if self._playback_task is None or self._playback_task.done():
            self._playback_task = asyncio.create_task(
                self._playback_worker(),
                name="lingou-carrier-playback",
            )

    async def _playback_worker(self) -> None:
        current_task = asyncio.current_task()
        try:
            while True:
                try:
                    generation, enqueued_at, descriptor, payload = (
                        self._playback_queue.get_nowait()
                    )
                except asyncio.QueueEmpty:
                    return
                try:
                    self._counters["playback_max_queue_wait_ms"] = max(
                        self._counters["playback_max_queue_wait_ms"],
                        round((time.monotonic() - enqueued_at) * 1000, 3),
                    )
                    if (
                        generation != self._playback_generation
                        or self._audio_is_cancelled(descriptor)
                    ):
                        continue
                    if descriptor.audio_id not in self.started_audio_ids:
                        await self._send_playback_receipt(descriptor, "decoded")
                        await self._send_playback_receipt(
                            descriptor,
                            "playback_started",
                        )
                        self.started_audio_ids.add(descriptor.audio_id)
                        self._observe(
                            "audio_output_started",
                            audio_id=descriptor.audio_id,
                        )
                    await self.audio.play(payload)
                    if (
                        generation != self._playback_generation
                        or self._audio_is_cancelled(descriptor)
                    ):
                        continue
                    if descriptor.chunk_index == descriptor.chunk_count - 1:
                        await self._send_playback_receipt(
                            descriptor,
                            "playback_completed",
                        )
                        self.last_completed_audio_id = descriptor.audio_id
                        self.playback_completed_event.set()
                        self._observe(
                            "audio_output_completed",
                            audio_id=descriptor.audio_id,
                        )
                        self.completed_audio_ids.add(descriptor.audio_id)
                        self.active_audio_ids.pop(descriptor.audio_id, None)
                        self.audio_streams.pop(descriptor.audio_id, None)
                        self.started_audio_ids.discard(descriptor.audio_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if not self._audio_is_cancelled(descriptor):
                        await self._send_playback_receipt(
                            descriptor,
                            "playback_failed",
                            str(exc),
                        )
                    self.cancelled_audio_ids.add((
                        descriptor.session_id,
                        descriptor.turn_id,
                        descriptor.audio_id,
                    ))
                    self.active_audio_ids.pop(descriptor.audio_id, None)
                    self.audio_streams.pop(descriptor.audio_id, None)
                    self.started_audio_ids.discard(descriptor.audio_id)
                finally:
                    self._playback_queue.task_done()
        finally:
            if self._playback_task is current_task:
                self._playback_task = None

    async def _stop_playback_work(self) -> None:
        self._playback_generation += 1
        task = self._playback_task
        self._playback_task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        dropped_frames = 0
        while True:
            try:
                self._playback_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                dropped_frames += 1
                self._playback_queue.task_done()
        self._counters["playback_dropped_frames"] += dropped_frames
        try:
            await self.audio.stop_playback()
        except Exception as exc:
            print(f"[carrier:audio] failed to stop playback: {exc}")

    async def _send_playback_receipt(
        self,
        descriptor: AudioChunkDescriptor,
        stage: str,
        error: Optional[str] = None,
    ) -> None:
        await self._send_json({
            "type": "audio_playback",
            "stage": stage,
            "session_id": descriptor.session_id,
            "turn_id": descriptor.turn_id,
            "audio_id": descriptor.audio_id,
            **({"error": error} if error else {}),
        })

    async def _send_json(self, payload: dict) -> None:
        websocket = self.websocket
        if websocket is None:
            return
        async with self._send_lock:
            await websocket.send(json.dumps(payload, ensure_ascii=False))

    async def _fail_active_audio(self, reason: str) -> None:
        descriptors = list(self.active_audio_ids.values())
        await self._stop_playback_work()
        for descriptor in descriptors:
            self.cancelled_audio_ids.add((
                descriptor.session_id,
                descriptor.turn_id,
                descriptor.audio_id,
            ))
            await self._send_playback_receipt(
                descriptor,
                "playback_failed",
                reason,
            )
        self.active_audio_ids.clear()
        self.audio_streams.clear()
        self.started_audio_ids.clear()
        if self.pending_binary is not None:
            self.pending_binary = replace(self.pending_binary, discard=True)

    async def _reset_playback(self, *, report_failure: bool) -> None:
        if report_failure:
            await self._fail_active_audio("connection_lost")
        else:
            await self._stop_playback_work()
            for descriptor in self.active_audio_ids.values():
                self.cancelled_audio_ids.add((
                    descriptor.session_id,
                    descriptor.turn_id,
                    descriptor.audio_id,
                ))
            self.active_audio_ids.clear()
            self.audio_streams.clear()
            self.started_audio_ids.clear()
            if self.pending_binary is not None:
                self.pending_binary = replace(self.pending_binary, discard=True)
        self.server_speaking = False
        self.audio.set_input_muted(False)

    async def _reset_connection_state(self, *, report_failure: bool) -> None:
        if self.websocket is not None and report_failure:
            await self._reset_playback(report_failure=True)
        else:
            await self._reset_playback(report_failure=False)
        self.websocket = None
        self.connected_event.clear()
        self._discard_input_buffer()
        self.session_id = ""
        self._clear_session_observations()

    def _clear_session_observations(self) -> None:
        self.current_turn_id = ""
        self.pending_binary = None
        self.started_audio_ids.clear()
        self.active_audio_ids.clear()
        self.audio_streams.clear()
        self.completed_audio_ids.clear()
        self.cancelled_turns.clear()
        self.cancelled_audio_ids.clear()
        self.last_final_text = ""
        self.last_reply_text = ""
        self.last_turn_metrics = {}
        self.last_completed_audio_id = ""
        self.final_text_event.clear()
        self.reply_text_event.clear()
        self.turn_metrics_event.clear()
        self.playback_completed_event.clear()
        self.provider_ready_event.clear()
        self._received_audio_ids.clear()


async def _keyboard_control(client: PortableVoiceClient) -> None:
    loop = asyncio.get_running_loop()
    try:
        stdin_fd = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):
        return
    ready: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)

    def read_ready() -> None:
        try:
            value = os.read(stdin_fd, 4096)
        except OSError:
            value = b""
        if ready.empty():
            ready.put_nowait(value)

    try:
        loop.add_reader(stdin_fd, read_ready)
    except (AttributeError, NotImplementedError, OSError):
        return
    try:
        while not client.stop_event.is_set():
            input_task = asyncio.create_task(ready.get())
            stop_task = asyncio.create_task(client.stop_event.wait())
            done, pending = await asyncio.wait(
                {input_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if stop_task in done:
                return
            if input_task.result() == b"":
                return
            await client.interrupt_or_resume()
    finally:
        loop.remove_reader(stdin_fd)


def _device_argument(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a Linux/macOS computer as an independent Lingou carrier",
    )
    parser.add_argument(
        "--server-url",
        default=os.getenv("LINGOU_DEVICE_VOICE_URL", DEFAULT_DEVICE_URL),
    )
    parser.add_argument("--input-device", type=_device_argument)
    parser.add_argument("--output-device", type=_device_argument)
    parser.add_argument(
        "--list-audio-devices",
        action="store_true",
        help="List PortAudio devices and exit.",
    )
    parser.add_argument(
        "--no-keyboard-control",
        action="store_true",
        help="Disable Enter-to-interrupt; SIGUSR1 remains available.",
    )
    return parser


async def async_main(args: argparse.Namespace) -> int:
    credential = os.getenv("LINGOU_DEVICE_CREDENTIAL", "").strip()
    if not credential:
        print("LINGOU_DEVICE_CREDENTIAL is required", file=sys.stderr)
        return 2
    audio = SoundDeviceAudioBackend(
        input_device=args.input_device,
        output_device=args.output_device,
    )
    client = PortableVoiceClient(
        server_url=args.server_url,
        device_credential=credential,
        audio=audio,
    )
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(stop_signal, client.request_stop)
        except NotImplementedError:
            pass
    if hasattr(signal, "SIGUSR1"):
        try:
            loop.add_signal_handler(
                signal.SIGUSR1,
                lambda: asyncio.create_task(client.interrupt_or_resume()),
            )
        except NotImplementedError:
            pass

    keyboard_task = None
    if not args.no_keyboard_control and sys.stdin.isatty():
        keyboard_task = asyncio.create_task(
            _keyboard_control(client),
            name="lingou-carrier-keyboard",
        )
    try:
        await client.run()
    finally:
        if keyboard_task:
            keyboard_task.cancel()
            await asyncio.gather(keyboard_task, return_exceptions=True)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_audio_devices:
        print(SoundDeviceAudioBackend.list_devices())
        return 0
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
