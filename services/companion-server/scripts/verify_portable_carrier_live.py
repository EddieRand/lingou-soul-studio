"""Verify a portable carrier through real speaker-to-microphone acoustics."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from dotenv import load_dotenv


SERVER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVER_ROOT.parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_device_voice_live import _free_port, _wait_until_ready


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one live Lingou turn through the default speaker and microphone"
        ),
    )
    parser.add_argument("--confirm-live-providers", action="store_true")
    parser.add_argument("--confirm-audio-io", action="store_true")
    parser.add_argument("--input-device")
    parser.add_argument("--output-device")
    return parser


def _device_argument(value: str | None) -> str | int | None:
    if value is None:
        return None
    return int(value) if value.isdigit() else value


async def _run_carrier(
    *,
    port: int,
    credential: str,
    prompt_pcm: bytes,
    input_device: str | int | None,
    output_device: str | int | None,
) -> dict:
    from hardware_adapter.portable_voice_client import (
        PortableVoiceClient,
        SoundDeviceAudioBackend,
    )

    observations: list[dict] = []
    audio = SoundDeviceAudioBackend(
        input_device=input_device,
        output_device=output_device,
    )
    client = PortableVoiceClient(
        server_url=f"ws://127.0.0.1:{port}/api/asr/device-stream",
        device_credential=credential,
        audio=audio,
        observation_sink=observations.append,
    )
    client_task = asyncio.create_task(
        client.run(),
        name="lingou-portable-carrier-live",
    )
    try:
        await asyncio.wait_for(client.connected_event.wait(), timeout=15)
        await asyncio.wait_for(client.provider_ready_event.wait(), timeout=15)
        # This is intentionally acoustic: speaker output is recaptured by the
        # microphone. No input fixture bytes are injected into the WebSocket.
        prompt_started = asyncio.get_running_loop().time()
        await audio.play(prompt_pcm)
        prompt_completed = asyncio.get_running_loop().time()
        await asyncio.wait_for(
            client.turn_metrics_event.wait(),
            timeout=90,
        )
        if not client.last_final_text:
            raise AssertionError("portable carrier produced no ASR text")
        if not client.last_reply_text:
            raise AssertionError("portable carrier produced no reply")
        if client.last_turn_metrics.get("status") != "completed":
            raise AssertionError(
                f"portable carrier turn did not complete: "
                f"{client.last_turn_metrics}"
            )
        origin_ms = prompt_started * 1000
        relative_observations = [
            {
                **item,
                "relative_to_prompt_ms": round(
                    float(item["monotonic_ms"]) - origin_ms,
                    1,
                ),
            }
            for item in observations
        ]
        return {
            "asr_text": client.last_final_text,
            "reply_text": client.last_reply_text,
            "completed_audio_id": client.last_completed_audio_id,
            "session_id": client.session_id,
            "turn_id": client.last_turn_metrics.get("turn_id"),
            "server_timings_ms": client.last_turn_metrics.get("timings", {}),
            "prompt_playback_ms": round(
                (prompt_completed - prompt_started) * 1000,
                1,
            ),
            "client_observations": relative_observations,
            "client_counters": client.metrics_snapshot(),
        }
    finally:
        client.request_stop()
        await asyncio.wait_for(client_task, timeout=10)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirm_live_providers or not args.confirm_audio_io:
        print(
            "Refusing without --confirm-live-providers and --confirm-audio-io"
        )
        return 2

    load_dotenv(SERVER_ROOT / ".env")
    required = ("ARK_API_KEY", "ARK_ENDPOINT_ID", "VOLC_TTS_API_KEY")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        print("Missing provider configuration: " + ", ".join(missing))
        return 2

    with tempfile.TemporaryDirectory(prefix="lingou-portable-live-") as temporary:
        runtime = Path(temporary) / "data"
        os.environ.update(
            LINGOU_DATA_DIR=str(runtime),
            LINGOU_LOAD_DOTENV="1",
            LINGOU_WARMUP_ON_STARTUP="0",
            LINGOU_JWT_SECRET="portable-live-test-secret-at-least-32-bytes",
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
        base_id = f"BASE-PORTABLE-{suffix}"
        owner_id = f"OWNER-PORTABLE-{suffix}"
        figure_id = f"FIGURE-PORTABLE-{suffix}"
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
                "name": "替代载体测试灵偶",
                "figure_type": "soul",
                "soul_profile": {
                    "archetype": "温和伙伴",
                    "name": "替代载体测试灵偶",
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
                        "memory_id": "FACT-PORTABLE",
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

        prompt_path = _synthesize_volcano_impl(
            "你好，请告诉我，你记得我喜欢什么颜色。",
            speaker,
            "portable-live-prompt",
            audio_format="pcm",
            sample_rate=24000,
        )
        if not prompt_path:
            raise RuntimeError("failed to synthesize acoustic prompt")
        prompt_pcm = Path(prompt_path).read_bytes()

        port = _free_port()
        server_log = Path(temporary) / "uvicorn.log"
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
                env=os.environ.copy(),
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                _wait_until_ready(port, server)
                result = asyncio.run(
                    _run_carrier(
                        port=port,
                        credential=credential,
                        prompt_pcm=prompt_pcm,
                        input_device=_device_argument(args.input_device),
                        output_device=_device_argument(args.output_device),
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
            raise AssertionError("persisted turn is missing session/turn ids")
        print(
            json.dumps(
                {**result, "persisted_turns": len(logs)},
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
