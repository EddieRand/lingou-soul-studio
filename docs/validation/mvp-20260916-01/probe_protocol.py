"""Controlled WS integration probes for the portable client, no paid providers."""
import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from hardware_adapter.portable_voice_client import PortableVoiceClient, DEVICE_PROTOCOL
import websockets

OUT = Path(os.getenv(
    "LINGOU_VALIDATION_OUT",
    str(Path(__file__).resolve().parent),
))
OUT.mkdir(parents=True, exist_ok=True)
results = []


class Audio:
    def __init__(self, delay=0):
        self.delay = delay
        self.input = asyncio.Queue()
        self.played = []
        self.stops = 0
        self.muted = False
        self.alerts = 0
        self.closed = False

    async def start(self): pass
    async def stop(self): self.closed = True
    async def read_input(self): return await self.input.get()
    async def play(self, data):
        if not data or len(data) % 2:
            raise ValueError("invalid PCM length")
        await asyncio.sleep(self.delay)
        self.played.append(bytes(data))
    async def stop_playback(self): self.stops += 1
    async def alert(self): self.alerts += 1
    def set_input_muted(self, value): self.muted = value


class Socket:
    def __init__(self): self.messages = []
    async def send(self, data):
        self.messages.append(json.loads(data) if isinstance(data, str) else {"binary_bytes": len(data)})


def client(audio=None):
    c = PortableVoiceClient(server_url="ws://127.0.0.1:1/api/asr/device-stream",
                            device_credential="BASE-QA." + "x" * 43, audio=audio or Audio())
    c.websocket = Socket()
    c.session_id = "SESSION-CURRENT"
    return c


def chunk(index=0, count=1, size=4, **kwargs):
    return dict(type="audio_chunk", session_id="SESSION-CURRENT", turn_id="TURN-CURRENT",
                audio_id="AUDIO-CURRENT", chunk_index=index, chunk_count=count,
                chunk_byte_length=size, audio_format="pcm", sample_rate=24000,
                channels=1, sample_format="s16le", **kwargs)


def log(case, variant, passed, observation):
    results.append(dict(case=case, variant=variant, passed=bool(passed),
                        observation=observation, environment="T1 controlled WS / fake sound output",
                        time=time.time()))
    (OUT / "protocol-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(case, variant, "PASS" if passed else "FAIL", flush=True)


async def feed(sequence):
    c = client()
    error = None
    try:
        for meta, data in sequence:
            await c._handle_server_message(meta)
            await c._handle_audio_frame(data)
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    await c._playback_queue.join()
    done = [m for m in c.websocket.messages if m.get("stage") == "playback_completed"]
    return c, error, done


async def frame_checks():
    pcm = bytes(i % 251 for i in range(9000))
    seq = [(chunk(i, 3, len(b)), b) for i, b in enumerate([pcm[:4096], pcm[4096:8192], pcm[8192:]])]
    c, error, done = await feed(seq)
    log("PROTOCOL-01", "9000 bytes, 4096/4096/808",
        not error and len(done) == 1 and b"".join(c.audio.played) == pcm,
        {"error": error, "receipts": c.websocket.messages,
         "received_sha256": hashlib.sha256(b"".join(c.audio.played)).hexdigest()})
    for name, action in [
        ("binary without descriptor", lambda c: c._handle_audio_frame(b"\0" * 4)),
        ("length mismatch", lambda c: send_mismatch(c)),
        ("two descriptors", lambda c: two_descriptors(c)),
    ]:
        c = client()
        try:
            await action(c)
            error = None
        except Exception as exc:
            error = str(exc)
        log("PROTOCOL-02", name, bool(error) and not c.audio.played,
            {"error": error, "played_frames": len(c.audio.played)})
    for name, size, overrides in [
        ("empty", 0, {}), ("odd", 3, {}), ("4096 valid", 4096, {}),
        ("4098 oversized", 4098, {}), ("mp3 claimed", 4, {"audio_format": "mp3"}),
        ("stereo claimed", 4, {"channels": 2}), ("float32 claimed", 4, {"sample_format": "float32"}),
        ("rate16000", 4, {"sample_rate": 16000}), ("rate48000", 4, {"sample_rate": 48000}),
    ]:
        meta = chunk(size=size)
        meta.update(overrides)
        c, error, done = await feed([(meta, b"\0" * size)])
        expect_valid = name == "4096 valid"
        passed = not error and len(done) == 1 if expect_valid else bool(error) and not done
        log("PROTOCOL-03", name, passed, {"error": error, "played_bytes": sum(map(len, c.audio.played)), "completed": len(done)})
    for name, indexes, counts in [
        ("missing middle", [0, 2], [3, 3]), ("duplicate middle", [0, 1, 1, 2], [3] * 4),
        ("out of order", [1, 0, 2], [3] * 3), ("negative", [-1], [3]),
        ("index==count", [3], [3]), ("zero count", [0], [0]), ("count changes", [0, 1], [3, 2]),
    ]:
        c, error, done = await feed([(chunk(i, n), b"\0" * 4) for i, n in zip(indexes, counts)])
        log("PROTOCOL-04", name, bool(error) and not done,
            {"error": error, "played_frames": len(c.audio.played), "completed": len(done)})
    c = client()
    old = chunk()
    old.update(session_id="SESSION-OLD", turn_id="TURN-OLD", audio_id="AUDIO-OLD")
    await c._handle_server_message(old)
    await c._handle_audio_frame(b"\1\0" * 2)
    log("PROTOCOL-05", "old session audio and status", not c.audio.played and c.session_id == "SESSION-CURRENT",
        {"session_after_old_audio": c.session_id, "played_frames": len(c.audio.played), "receipts": c.websocket.messages})


async def send_mismatch(c):
    await c._handle_server_message(chunk(size=6))
    await c._handle_audio_frame(b"\0" * 4)


async def two_descriptors(c):
    await c._handle_server_message(chunk())
    await c._handle_server_message(chunk())


async def cancellation_checks():
    c = client()
    c.server_speaking = True
    await c._handle_server_message(chunk(0, 2))
    await c._handle_audio_frame(b"\1\0" * 2)
    await c._playback_queue.join()
    await c.interrupt_or_resume()
    old_count = len(c.audio.played)
    await c._handle_server_message(chunk(1, 2))
    await c._handle_audio_frame(b"\2\0" * 2)
    log("CANCEL-03", "late frame after cancel",
        len(c.audio.played) == old_count and not any(m.get("stage") == "playback_completed" for m in c.websocket.messages),
        {"frames_before_cancel": old_count, "frames_after": len(c.audio.played), "messages": c.websocket.messages})
    c = client()
    c.server_speaking = True
    await c._handle_server_message(chunk(0, 2))
    await c.interrupt_or_resume()
    try:
        await c._handle_audio_frame(b"\0" * 4)
        error = None
    except Exception as exc:
        error = str(exc)
    log("CANCEL-02", "cancel between descriptor and binary", not error and not c.audio.played,
        {"error": error, "played_frames": len(c.audio.played)})
    c = client()
    c.server_speaking = True
    await c._handle_server_message(chunk(0, 2))
    await c._handle_server_message({"type": "stop_audio", "session_id": "SESSION-CURRENT", "turn_id": "TURN-OLD"})
    log("CANCEL-05", "old stop affects active new turn",
        c.pending_binary is not None and c.server_speaking and c.audio.stops == 0,
        {"pending_discarded": c.pending_binary is None, "speaking": c.server_speaking, "output_stops": c.audio.stops})
    c = client()
    await c._handle_server_message({"type": "final", "session_id": "SESSION-CURRENT",
                                    "turn_id": "TURN-CURRENT", "text": "old recognized"})
    await c._handle_server_message({"type": "reply", "session_id": "SESSION-CURRENT",
                                    "turn_id": "TURN-CURRENT", "reply": "old reply"})
    await c._handle_server_message(chunk())
    await c._handle_audio_frame(b"\0" * 4)
    await c._playback_queue.join()
    await c._reset_connection_state(report_failure=False)
    c.websocket = Socket()
    await c._handle_server_message({"type": "status", "status": "listening",
                                    "session_id": "SESSION-NEW", "audio_format": "pcm",
                                    "audio_sample_rate": 24000})
    log("RECOVER-08", "new session inherits old completion",
        not c.playback_completed_event.is_set() and not c.last_final_text and not c.last_reply_text,
        {"session": c.session_id, "completion_set": c.playback_completed_event.is_set(),
         "final": c.last_final_text, "reply": c.last_reply_text, "audio": c.last_completed_audio_id})


async def socket_checks():
    count = 0
    timestamps = []
    async def close_clean(ws):
        nonlocal count
        count += 1
        timestamps.append(time.monotonic())
        await ws.close(1000)
    async with websockets.serve(close_clean, "127.0.0.1", 0, subprotocols=[DEVICE_PROTOCOL]) as server:
        port = server.sockets[0].getsockname()[1]
        c = PortableVoiceClient(server_url=f"ws://127.0.0.1:{port}", device_credential="BASE.x", audio=Audio())
        task = asyncio.create_task(c.run())
        await asyncio.sleep(0.4)
        c.request_stop()
        await asyncio.wait_for(task, 3)
    log("RECOVER-03", "real WS repeated clean closure (0.4s bounded)",
        count <= 2, {"connections": count, "elapsed_seconds": 0.4, "intervals_ms": [round((b-a)*1000, 2) for a,b in zip(timestamps,timestamps[1:])][:20]})
    # Real connection replacement, held for the stipulated 60s before explicit resume.
    connected = asyncio.Event()
    calls = 0
    async def replace(ws):
        nonlocal calls
        calls += 1
        if calls == 1:
            await ws.send(json.dumps({"type": "session_replaced", "session_id": "SESSION-CURRENT"}))
            await ws.close(4410)
        else:
            connected.set()
            await ws.wait_closed()
    async with websockets.serve(replace, "127.0.0.1", 0, subprotocols=[DEVICE_PROTOCOL]) as server:
        c = PortableVoiceClient(server_url=f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}",
                                device_credential="BASE.x", audio=Audio())
        task = asyncio.create_task(c.run())
        await asyncio.sleep(60)
        before = calls
        await c.interrupt_or_resume()
        await asyncio.wait_for(connected.wait(), 3)
        c.request_stop()
        await asyncio.wait_for(task, 3)
    log("CANCEL-06", "T1 replacement 60s pause and explicit resume", before == 1 and calls == 2,
        {"connections_before_resume": before, "after_resume": calls, "scope": "loopback WS, not T3/H5 acoustic"})
    # Slow playback blocks the real receive loop from processing a stop frame.
    stop_sent = asyncio.Event()
    async def slow_server(ws):
        await ws.send(json.dumps(chunk()))
        await ws.send(b"\0" * 4)
        await ws.send(json.dumps({"type": "stop_audio", "session_id": "SESSION-CURRENT", "turn_id": "TURN-CURRENT"}))
        stop_sent.set()
        await asyncio.sleep(0.5)
    async with websockets.serve(slow_server, "127.0.0.1", 0, subprotocols=[DEVICE_PROTOCOL]) as server:
        audio = Audio(delay=0.4)
        c = client(audio)
        async with websockets.connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}",
                                      subprotocols=[DEVICE_PROTOCOL]) as ws:
            c.websocket = ws
            task = asyncio.create_task(c._receive_server(ws))
            await stop_sent.wait()
            await asyncio.sleep(0.1)
            stops_during_write = audio.stops
            await task
    log("PROTOCOL-08", "stop blocked behind sound write",
        stops_during_write > 0, {"output_delay_ms": 400, "stops_100ms_after_server_stop": stops_during_write,
                               "eventual_output_stops": audio.stops})


async def main():
    await frame_checks()
    await cancellation_checks()
    await socket_checks()


if __name__ == "__main__":
    asyncio.run(main())
