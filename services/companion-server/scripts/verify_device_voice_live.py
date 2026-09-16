"""Run one isolated device-voice turn against real configured providers."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

from dotenv import load_dotenv


SERVER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVER_ROOT.parents[1]
sys.path.insert(0, str(SERVER_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the device PCM protocol with live ASR, Ark and TTS",
    )
    parser.add_argument(
        "--confirm-live-providers",
        action="store_true",
        help="Required because this probe invokes configured paid providers.",
    )
    return parser


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_until_ready(port: int, server: subprocess.Popen) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        if server.poll() is not None:
            raise RuntimeError("uvicorn exited before readiness")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health",
                timeout=1,
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise TimeoutError("uvicorn did not become ready")


async def _run_device_turn(
    *,
    port: int,
    credential: str,
    input_pcm: bytes,
) -> dict:
    import websockets

    uri = f"ws://127.0.0.1:{port}/api/asr/device-stream"
    messages: list[dict] = []
    pcm_output = bytearray()
    pending: dict | None = None
    started: set[str] = set()
    completed: set[str] = set()

    async with websockets.connect(
        uri,
        subprotocols=["lingou.device.voice.v1"],
        additional_headers={"Authorization": f"Device {credential}"},
        max_size=2 * 1024 * 1024,
    ) as websocket:
        status = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10))
        if status.get("type") != "status" or status.get("audio_format") != "pcm":
            raise AssertionError(f"unexpected device status: {status}")

        for offset in range(0, len(input_pcm), 640):
            await websocket.send(input_pcm[offset:offset + 640])
            await asyncio.sleep(0.02)
        for _ in range(100):
            await websocket.send(b"\x00" * 640)
            await asyncio.sleep(0.02)

        deadline = asyncio.get_running_loop().time() + 60
        while asyncio.get_running_loop().time() < deadline:
            item = await asyncio.wait_for(websocket.recv(), timeout=10)
            if isinstance(item, bytes):
                if pending is None:
                    raise AssertionError("binary frame lacks audio_chunk metadata")
                pcm_output.extend(item)
                audio_id = str(pending["audio_id"])
                receipt = {
                    "type": "audio_playback",
                    "session_id": pending["session_id"],
                    "turn_id": pending["turn_id"],
                    "audio_id": audio_id,
                }
                if audio_id not in started:
                    for stage in ("decoded", "playback_started"):
                        await websocket.send(
                            json.dumps({**receipt, "stage": stage})
                        )
                    started.add(audio_id)
                if pending["chunk_index"] == pending["chunk_count"] - 1:
                    await websocket.send(
                        json.dumps({**receipt, "stage": "playback_completed"})
                    )
                    completed.add(audio_id)
                pending = None
                continue

            message = json.loads(item)
            messages.append(message)
            if message.get("type") == "audio_chunk":
                pending = message
            if message.get("type") == "turn_metrics":
                break
        else:
            raise TimeoutError("device turn did not complete")

    final = next((item for item in messages if item.get("type") == "final"), None)
    reply = next((item for item in messages if item.get("type") == "reply"), None)
    metrics = next(
        (item for item in messages if item.get("type") == "turn_metrics"),
        None,
    )
    if not final or not final.get("text"):
        raise AssertionError("ASR produced no final text")
    if not reply or not reply.get("reply"):
        raise AssertionError("dialogue produced no reply")
    if not pcm_output or len(pcm_output) % 2:
        raise AssertionError("device received invalid PCM")
    if not metrics or metrics.get("status") != "completed":
        raise AssertionError(f"turn did not complete: {metrics}")
    return {
        "asr_text": final["text"],
        "reply_text": reply["reply"],
        "pcm_bytes": len(pcm_output),
        "audio_ids_completed": len(completed),
        "turn_status": metrics["status"],
        "client_kind": status.get("client_kind"),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirm_live_providers:
        print("Refusing live provider calls without --confirm-live-providers")
        return 2

    load_dotenv(SERVER_ROOT / ".env")
    required = ("ARK_API_KEY", "ARK_ENDPOINT_ID", "VOLC_TTS_API_KEY")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        print("Missing provider configuration: " + ", ".join(missing))
        return 2

    with tempfile.TemporaryDirectory(prefix="lingou-step11-live-") as temporary:
        runtime = Path(temporary) / "data"
        os.environ.update(
            LINGOU_DATA_DIR=str(runtime),
            LINGOU_LOAD_DOTENV="1",
            LINGOU_WARMUP_ON_STARTUP="0",
            LINGOU_JWT_SECRET="step-11-live-protocol-secret-at-least-32-bytes",
        )

        from app.core.tts_adapter import _synthesize_volcano_impl, _volc_config
        from data.store import (
            activate_figure,
            claim_base,
            list_dialogue_logs,
            provision_base,
            save_figure,
        )

        suffix = uuid.uuid4().hex
        base_id = f"BASE-STEP11-{suffix}"
        owner_id = f"OWNER-STEP11-{suffix}"
        figure_id = f"FIGURE-STEP11-{suffix}"
        pairing_token = f"{base_id}.{'p' * 43}"
        credential = f"{base_id}.{'d' * 43}"
        provision_base(
            base_id,
            pairing_token=pairing_token,
            device_credential=credential,
        )
        claim_base(pairing_token, owner_user_id=owner_id)
        now = datetime.now(timezone.utc).isoformat()
        speaker = _volc_config()["default_speaker"]
        save_figure(
            figure_id,
            {
                "figure_id": figure_id,
                "name": "协议测试灵偶",
                "figure_type": "soul",
                "soul_profile": {
                    "archetype": "温和伙伴",
                    "name": "协议测试灵偶",
                    "one_line": "简短、自然地回应测试者。",
                    "address_user_as": "你",
                },
                "voice_profile": {
                    "tts_engine": "volcano_tts",
                    "speaker": speaker,
                },
                "memory": {
                    "figure_id": figure_id,
                    "confirmed_facts": [{
                        "memory_id": "FACT-STEP11",
                        "content": "用户喜欢蓝色。",
                        "status": "confirmed",
                        "created_at": now,
                        "updated_at": now,
                    }],
                    "memory_candidates": [],
                    "memory_tombstones": [],
                    "memory_revision": 1,
                    "interaction_count": 0,
                },
                "created_at": now,
                "updated_at": now,
            },
            user_id=owner_id,
        )
        activate_figure(base_id, figure_id, owner_user_id=owner_id)

        input_path = _synthesize_volcano_impl(
            "你好，请告诉我你记得我喜欢什么颜色。",
            speaker,
            "step11-live-input",
            audio_format="pcm",
            sample_rate=16000,
        )
        if not input_path:
            raise RuntimeError("failed to synthesize the input fixture")
        input_pcm = Path(input_path).read_bytes()

        port = _free_port()
        server_log = Path(temporary) / "uvicorn.log"
        environment = os.environ.copy()
        with server_log.open("w") as output:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=SERVER_ROOT,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                _wait_until_ready(port, server)
                result = asyncio.run(
                    _run_device_turn(
                        port=port,
                        credential=credential,
                        input_pcm=input_pcm,
                    )
                )
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)

        logs = list_dialogue_logs(
            user_id=owner_id,
            figure_id=figure_id,
            limit=10,
        )
        if len(logs) != 1:
            raise AssertionError(f"expected one persisted turn, got {len(logs)}")
        if not logs[0].get("session_id") or not logs[0].get("turn_id"):
            raise AssertionError("persisted turn is missing trace ids")
        print(
            json.dumps(
                {**result, "persisted_turns": len(logs)},
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
