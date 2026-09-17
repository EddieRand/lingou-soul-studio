"""Collect controlled EV-02 WebSocket delay, jitter, and outage evidence."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import time
from typing import Any
import uuid


SERVER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVER_ROOT.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from hardware_adapter.portable_voice_client import (  # noqa: E402
    INPUT_FRAME_BYTES,
    PortableVoiceClient,
)


DEFAULT_OUTPUT = (
    PROJECT_ROOT / "docs" / "validation" / "ev02-baseline-20260917"
)
PROTOCOL = "lingou.device.voice.v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect controlled WebSocket delay and outage evidence.",
    )
    parser.add_argument("--outage-seconds", type=float, default=30.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--output-name",
        default="controlled-network-baseline.json",
    )
    return parser


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _wait_until(predicate, *, timeout: float, message: str) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(message)
        await asyncio.sleep(0.01)


class ControlledAudio:
    def __init__(self):
        self.input_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.played: list[bytes] = []
        self.started = False
        self.stopped = False
        self.muted = False
        self.playback_stops = 0
        self.alerts = 0

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def read_input(self) -> bytes:
        return await self.input_queue.get()

    async def play(self, payload: bytes) -> None:
        self.played.append(bytes(payload))

    async def stop_playback(self) -> None:
        self.playback_stops += 1

    async def alert(self) -> None:
        self.alerts += 1

    def discard_input_buffer(self) -> int:
        discarded = 0
        while True:
            try:
                self.input_queue.get_nowait()
                discarded += 1
            except asyncio.QueueEmpty:
                return discarded

    @staticmethod
    def metrics_snapshot() -> dict[str, int]:
        return {
            "input_overflows": 0,
            "input_queue_overflows": 0,
            "playback_underruns": 0,
        }

    def set_input_muted(self, muted: bool) -> None:
        self.muted = muted


class ControlledVoiceServer:
    def __init__(
        self,
        *,
        port: int,
        response_delay_ms: float | None = None,
        chunk_intervals_ms: list[float] | None = None,
    ):
        self.port = port
        self.response_delay_ms = response_delay_ms
        self.chunk_intervals_ms = chunk_intervals_ms or [0.0]
        self.server = None
        self.connection_count = 0
        self.sessions: list[dict[str, Any]] = []

    async def _handler(self, websocket) -> None:
        self.connection_count += 1
        session_id = f"SESSION-{self.connection_count}-{uuid.uuid4().hex[:8]}"
        record = {
            "session_id": session_id,
            "binary_frames": [],
            "receipts": [],
        }
        self.sessions.append(record)
        await websocket.send(json.dumps({
            "type": "status",
            "status": "listening",
            "session_id": session_id,
            "connection_policy": "newest_connection_wins",
            "client_kind": "device",
            "audio_format": "pcm",
            "audio_sample_rate": 24000,
        }))
        await websocket.send(json.dumps({
            "type": "status",
            "status": "ready",
            "session_id": session_id,
        }))

        response_sent = False
        async for message in websocket:
            if isinstance(message, bytes):
                record["binary_frames"].append(bytes(message))
                if (
                    self.response_delay_ms is not None
                    and not response_sent
                ):
                    response_sent = True
                    await asyncio.sleep(self.response_delay_ms / 1000)
                    await self._send_audio(websocket, session_id)
                continue
            try:
                payload = json.loads(message)
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("type") == "audio_playback":
                record["receipts"].append(payload.get("stage"))

    async def _send_audio(self, websocket, session_id: str) -> None:
        turn_id = f"TURN-{uuid.uuid4().hex[:8]}"
        audio_id = f"AUDIO-{uuid.uuid4().hex[:8]}"
        await websocket.send(json.dumps({
            "type": "speaking",
            "status": "start",
            "session_id": session_id,
            "turn_id": turn_id,
        }))
        chunk_count = len(self.chunk_intervals_ms)
        for index, interval_ms in enumerate(self.chunk_intervals_ms):
            if interval_ms:
                await asyncio.sleep(interval_ms / 1000)
            payload = bytes([index + 1, 0]) * 320
            await websocket.send(json.dumps({
                "type": "audio_chunk",
                "stage": "transferring",
                "session_id": session_id,
                "turn_id": turn_id,
                "audio_id": audio_id,
                "chunk_index": index,
                "chunk_count": chunk_count,
                "chunk_byte_length": len(payload),
                "audio_format": "pcm",
                "sample_rate": 24000,
                "channels": 1,
                "sample_format": "s16le",
            }))
            await websocket.send(payload)
        await websocket.send(json.dumps({
            "type": "speaking",
            "status": "end",
            "session_id": session_id,
            "turn_id": turn_id,
        }))

    async def start(self) -> None:
        from websockets.asyncio.server import serve

        self.server = await serve(
            self._handler,
            "127.0.0.1",
            self.port,
            subprotocols=[PROTOCOL],
            compression=None,
        )

    async def stop(self) -> None:
        if self.server is None:
            return
        self.server.close()
        await self.server.wait_closed()
        self.server = None


def _event_time(observations: list[dict], event: str) -> float:
    for item in observations:
        if item.get("event") == event:
            return float(item["monotonic_ms"])
    raise AssertionError(f"missing observation: {event}")


async def _roundtrip_scenario(
    *,
    name: str,
    response_delay_ms: float,
    chunk_intervals_ms: list[float],
) -> dict[str, Any]:
    port = _free_port()
    server = ControlledVoiceServer(
        port=port,
        response_delay_ms=response_delay_ms,
        chunk_intervals_ms=chunk_intervals_ms,
    )
    await server.start()
    audio = ControlledAudio()
    observations: list[dict] = []
    client = PortableVoiceClient(
        server_url=f"ws://127.0.0.1:{port}",
        device_credential="BASE-EV02." + ("x" * 43),
        audio=audio,
        observation_sink=observations.append,
        reconnect_initial_seconds=0.1,
        reconnect_max_seconds=0.2,
    )
    task = asyncio.create_task(client.run(), name=f"ev02-{name}")
    queued_at_ms = time.monotonic() * 1000
    try:
        await asyncio.wait_for(client.provider_ready_event.wait(), timeout=5)
        queued_at_ms = time.monotonic() * 1000
        await audio.input_queue.put(b"\x01\x00" * (INPUT_FRAME_BYTES // 2))
        await asyncio.wait_for(client.playback_completed_event.wait(), timeout=10)
        await _wait_until(
            lambda: bool(server.sessions[0]["receipts"])
            and server.sessions[0]["receipts"][-1] == "playback_completed",
            timeout=2,
            message="controlled server did not receive playback completion",
        )
        completion_ms = _event_time(observations, "audio_output_completed")
        first_audio_ms = _event_time(observations, "first_audio_received")
        return {
            "name": name,
            "passed": True,
            "response_delay_ms": response_delay_ms,
            "chunk_intervals_ms": chunk_intervals_ms,
            "queued_to_first_audio_ms": round(first_audio_ms - queued_at_ms, 1),
            "queued_to_playback_complete_ms": round(
                completion_ms - queued_at_ms,
                1,
            ),
            "received_chunks": len(audio.played),
            "client_counters": client.metrics_snapshot(),
            "receipt_sequence": server.sessions[0]["receipts"],
        }
    finally:
        client.request_stop()
        await asyncio.wait_for(task, timeout=5)
        await server.stop()


async def _outage_scenario(outage_seconds: float) -> dict[str, Any]:
    port = _free_port()
    server = ControlledVoiceServer(port=port)
    await server.start()
    audio = ControlledAudio()
    observations: list[dict] = []
    client = PortableVoiceClient(
        server_url=f"ws://127.0.0.1:{port}",
        device_credential="BASE-EV02." + ("y" * 43),
        audio=audio,
        observation_sink=observations.append,
    )
    task = asyncio.create_task(client.run(), name="ev02-outage")
    online_frame = b"\x11\x00" * (INPUT_FRAME_BYTES // 2)
    offline_frame = b"\x22\x00" * (INPUT_FRAME_BYTES // 2)
    recovery_frame = b"\x33\x00" * (INPUT_FRAME_BYTES // 2)
    try:
        await asyncio.wait_for(client.provider_ready_event.wait(), timeout=5)
        first_session = client.session_id
        await audio.input_queue.put(online_frame)
        await _wait_until(
            lambda: bool(server.sessions[0]["binary_frames"]),
            timeout=2,
            message="initial online frame was not received",
        )

        outage_started = time.monotonic()
        await server.stop()
        await _wait_until(
            lambda: not client.connected_event.is_set(),
            timeout=5,
            message="client did not observe outage",
        )
        for _ in range(10):
            await audio.input_queue.put(offline_frame)
        elapsed = time.monotonic() - outage_started
        if elapsed < outage_seconds:
            await asyncio.sleep(outage_seconds - elapsed)

        server = ControlledVoiceServer(port=port)
        await server.start()
        await _wait_until(
            lambda: server.connection_count >= 1
            and client.connected_event.is_set()
            and client.session_id != first_session,
            timeout=20,
            message="client did not reconnect with a new session",
        )
        outage_elapsed = time.monotonic() - outage_started
        await asyncio.sleep(0.5)
        restored_frames_before_new_input = [
            frame
            for frame in server.sessions[0]["binary_frames"]
        ]
        await audio.input_queue.put(recovery_frame)
        await _wait_until(
            lambda: recovery_frame in server.sessions[0]["binary_frames"],
            timeout=5,
            message="post-recovery frame was not received",
        )

        leaked_offline_frames = sum(
            frame == offline_frame
            for frame in server.sessions[0]["binary_frames"]
        )
        passed = (
            client.session_id != first_session
            and not restored_frames_before_new_input
            and leaked_offline_frames == 0
            and recovery_frame in server.sessions[0]["binary_frames"]
        )
        return {
            "name": "thirty_second_outage",
            "passed": passed,
            "requested_outage_seconds": outage_seconds,
            "actual_outage_seconds": round(outage_elapsed, 3),
            "new_session": client.session_id != first_session,
            "frames_received_before_new_input": len(
                restored_frames_before_new_input
            ),
            "offline_frames_uploaded_after_reconnect": leaked_offline_frames,
            "post_recovery_frame_received": (
                recovery_frame in server.sessions[0]["binary_frames"]
            ),
            "client_counters": client.metrics_snapshot(),
            "observation_events": [
                item["event"]
                for item in observations
                if item["event"] in {
                    "socket_connected",
                    "socket_disconnected",
                    "reconnect_started",
                    "reconnect_completed",
                    "session_started",
                }
            ],
        }
    finally:
        client.request_stop()
        await asyncio.wait_for(task, timeout=5)
        await server.stop()


async def _run(outage_seconds: float) -> dict[str, Any]:
    scenarios = [
        await _roundtrip_scenario(
            name="stable_loopback",
            response_delay_ms=0,
            chunk_intervals_ms=[0, 0, 0],
        ),
        await _roundtrip_scenario(
            name="fixed_100ms",
            response_delay_ms=100,
            chunk_intervals_ms=[0, 0, 0],
        ),
        await _roundtrip_scenario(
            name="jitter_100_120_10_80ms",
            response_delay_ms=100,
            chunk_intervals_ms=[0, 120, 10, 80],
        ),
        await _outage_scenario(outage_seconds),
    ]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "environment": "loopback WebSocket with controlled service impairment",
        "transport": "websocket",
        "profile_id": "ws-pcm-s16le-v1",
        "scope": (
            "Real WebSocket/reconnect/client tasks with fake audio and no "
            "provider calls; not an RF or internet packet-loss test."
        ),
        "scenarios": scenarios,
        "passed": all(item["passed"] for item in scenarios),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.outage_seconds < 30:
        print("--outage-seconds must be at least 30")
        return 2
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(_run(args.outage_seconds))
    output_path = output_dir / args.output_name
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps({
        "output": str(output_path),
        "passed": report["passed"],
    }))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
