"""Run explicitly: python -B tests/test_device_voice.py.

Step-11 device voice protocol tests. All accounts, bases, credentials, audio,
providers, WebSockets and storage live in isolated fixtures.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True


class FakeWebSocket:
    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}
        self.accepted_subprotocols: list[str | None] = []
        self.closed: list[tuple[int, str]] = []
        self.json_messages: list[dict] = []
        self.binary_messages: list[bytes] = []
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()

    async def accept(self, subprotocol: str | None = None):
        self.accepted_subprotocols.append(subprotocol)

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed.append((code, reason))

    async def send_json(self, payload: dict):
        self.json_messages.append(payload)

    async def send_bytes(self, payload: bytes):
        self.binary_messages.append(payload)

    async def receive(self):
        return await self.incoming.get()


class DeviceVoiceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(
            cls.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="lingou-device-voice-")
            )
        ).resolve()
        cls.runtime = cls.temp / "runtime"
        clean_env = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")
            if key in os.environ
        }
        clean_env.update(
            LINGOU_DATA_DIR=str(cls.runtime),
            LINGOU_LOAD_DOTENV="0",
            LINGOU_WARMUP_ON_STARTUP="0",
            LINGOU_ENABLE_TEST_DEVICE_AUTH="1",
            LINGOU_JWT_SECRET="step-11-test-only-jwt-secret-at-least-32-bytes",
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))
        cls.stack.enter_context(
            patch(
                "dotenv.load_dotenv",
                side_effect=AssertionError("dotenv must stay disabled"),
            )
        )

        from app import main
        from app.api import asr
        from app.core import tts_adapter
        from data import store

        cls.main = main
        cls.asr = asr
        cls.tts = tts_adapter
        cls.store = store

    def setUp(self):
        self.main.auth.USERS_FILE.unlink(missing_ok=True)
        for directory in (
            self.store.BASES_DIR,
            self.store.USER_DATA_DIR,
            self.store.TRANSACTIONS_DIR,
        ):
            if directory.exists():
                for path in sorted(directory.rglob("*"), reverse=True):
                    if path.is_file() or path.is_symlink():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
            directory.mkdir(parents=True, exist_ok=True)
        with self.asr.voice_session_registry._lock:
            self.asr.voice_session_registry._sessions.clear()

    def _client(self):
        from fastapi.testclient import TestClient

        return TestClient(self.main.app)

    @staticmethod
    def _bearer(session: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {session['access_token']}"}

    def _device_fixture(self, *, activate: bool = True) -> tuple[str, str, str]:
        with self._client() as client:
            username = f"device-voice-{uuid.uuid4().hex}"
            account = client.post(
                "/api/auth/register",
                json={
                    "username": username,
                    "email": f"{username}@example.com",
                    "password": "fictional-password",
                },
            ).json()
            session = client.post(
                "/api/auth/login",
                data={"username": username, "password": "fictional-password"},
            ).json()
            headers = self._bearer(session)
            base_id = f"BASE-VOICE-{uuid.uuid4().hex}"
            created_base = client.post(
                "/api/bases/test-bases",
                json={"base_id": base_id},
                headers=headers,
            )
            self.assertEqual(created_base.status_code, 201, created_base.text)
            if activate:
                figure = client.post(
                    "/api/figures",
                    json={"name": "Device Voice", "figure_type": "soul"},
                    headers=headers,
                )
                self.assertEqual(figure.status_code, 200, figure.text)
                activated = client.post(
                    f"/api/bases/{base_id}/active-figure",
                    json={"figure_id": figure.json()["figure_id"]},
                    headers=headers,
                )
                self.assertEqual(activated.status_code, 200, activated.text)
            issued = client.post(
                f"/api/bases/{base_id}/test-device-credential",
                headers=headers,
            )
            self.assertEqual(issued.status_code, 200, issued.text)
            return account["user_id"], base_id, issued.json()["device_credential"]

    async def test_device_socket_derives_owner_and_base_from_scoped_credential(self):
        owner_user_id, base_id, credential = self._device_fixture()
        websocket = FakeWebSocket({
            "authorization": f"Device {credential}",
            "sec-websocket-protocol": self.asr.DEVICE_WS_PROTOCOL,
        })
        with patch.object(
            self.asr,
            "_serve_voice_socket",
            new=AsyncMock(),
        ) as serve:
            await self.asr.asr_device_stream_ws(websocket)

        self.assertEqual(
            websocket.accepted_subprotocols,
            [self.asr.DEVICE_WS_PROTOCOL],
        )
        serve.assert_awaited_once_with(
            websocket,
            base_id=base_id,
            owner_user_id=owner_user_id,
            client_kind="device",
            output_audio_format="pcm",
            output_sample_rate=24000,
            max_audio_frame_bytes=4096,
            device_credential=credential,
        )

    async def test_registered_device_socket_accepts_auth_before_provider_check(self):
        _owner_user_id, _base_id, credential = self._device_fixture()
        with (
            self._client() as client,
            patch.object(self.asr, "is_asr_available", return_value=False),
            client.websocket_connect(
                "/api/asr/device-stream",
                headers={"Authorization": f"Device {credential}"},
                subprotocols=[self.asr.DEVICE_WS_PROTOCOL],
            ) as websocket,
        ):
            self.assertEqual(
                websocket.accepted_subprotocol,
                self.asr.DEVICE_WS_PROTOCOL,
            )
            message = websocket.receive_json()
            self.assertEqual(message["type"], "error")
            self.assertIn("语音服务未配置", message["message"])

    async def test_device_socket_rejects_missing_voice_scope_before_provider(self):
        owner_user_id, base_id, credential = self._device_fixture()
        base = self.store.get_base_for_owner(base_id, owner_user_id)
        base["device_credential_scope"] = ["events:write"]
        self.store.save_base(base_id, base, owner_user_id=owner_user_id)
        websocket = FakeWebSocket({
            "authorization": f"Device {credential}",
            "sec-websocket-protocol": self.asr.DEVICE_WS_PROTOCOL,
        })
        with patch.object(
            self.asr,
            "_serve_voice_socket",
            new=AsyncMock(),
        ) as serve:
            await self.asr.asr_device_stream_ws(websocket)

        self.assertEqual(websocket.closed[0][0], self.asr.DEVICE_AUTH_CLOSE_CODE)
        serve.assert_not_awaited()

    async def test_device_socket_requires_an_active_figure(self):
        _owner_user_id, _base_id, credential = self._device_fixture(activate=False)
        websocket = FakeWebSocket({
            "authorization": f"Device {credential}",
            "sec-websocket-protocol": self.asr.DEVICE_WS_PROTOCOL,
        })
        with patch.object(
            self.asr,
            "_serve_voice_socket",
            new=AsyncMock(),
        ) as serve:
            await self.asr.asr_device_stream_ws(websocket)

        self.assertEqual(
            websocket.closed[0][0],
            self.asr.DEVICE_NOT_READY_CLOSE_CODE,
        )
        serve.assert_not_awaited()

    async def test_active_device_socket_revalidates_revoked_credential(self):
        owner_user_id, base_id, credential = self._device_fixture()
        websocket = FakeWebSocket({
            "authorization": f"Device {credential}",
            "sec-websocket-protocol": self.asr.DEVICE_WS_PROTOCOL,
        })

        async def no_provider_connection(_session):
            return None

        with (
            patch.object(self.asr, "is_asr_available", return_value=True),
            patch.object(
                self.asr.VoiceCallSession,
                "_start_volc_connection_background",
                new=no_provider_connection,
            ),
            patch.object(
                self.asr.VoiceCallSession,
                "send_audio",
                new=AsyncMock(),
            ) as send_audio,
        ):
            task = asyncio.create_task(
                self.asr.asr_device_stream_ws(websocket)
            )
            deadline = asyncio.get_running_loop().time() + 1
            while not websocket.json_messages:
                if asyncio.get_running_loop().time() >= deadline:
                    self.fail("device socket did not enter listening state")
                await asyncio.sleep(0.005)

            base = self.store.get_base_for_owner(base_id, owner_user_id)
            base["device_credential_status"] = "revoked"
            self.store.save_base(
                base_id,
                base,
                owner_user_id=owner_user_id,
            )
            await websocket.incoming.put({
                "type": "websocket.receive",
                "bytes": b"\x00" * 640,
            })
            await asyncio.wait_for(task, timeout=1)

        send_audio.assert_not_awaited()
        self.assertIn(
            (self.asr.DEVICE_AUTH_CLOSE_CODE,
             "device credential is no longer authorized"),
            websocket.closed,
        )

    async def test_production_credential_rotation_is_explicit_and_revokes_old_secret(self):
        from app.api.device_auth import (
            EVENTS_WRITE_SCOPE,
            VOICE_STREAM_SCOPE,
            authenticate_device_credential,
        )

        base_id = f"BASE-ROTATE-{uuid.uuid4().hex}"
        pairing_token = f"{base_id}.{'p' * 43}"
        old_credential = f"{base_id}.{'o' * 43}"
        new_credential = f"{base_id}.{'n' * 43}"
        self.store.provision_base(
            base_id,
            pairing_token=pairing_token,
            device_credential=old_credential,
        )
        self.store.claim_base(
            pairing_token,
            owner_user_id=f"OWNER-ROTATE-{uuid.uuid4().hex}",
        )
        self.assertIsNotNone(
            authenticate_device_credential(
                old_credential,
                required_scope=VOICE_STREAM_SCOPE,
            )
        )

        self.store.rotate_production_device_credential(
            base_id,
            device_credential=new_credential,
        )

        self.assertIsNone(
            authenticate_device_credential(
                old_credential,
                required_scope=EVENTS_WRITE_SCOPE,
            )
        )
        principal = authenticate_device_credential(
            new_credential,
            required_scope=VOICE_STREAM_SCOPE,
        )
        self.assertEqual(
            principal["scope"],
            (EVENTS_WRITE_SCOPE, VOICE_STREAM_SCOPE),
        )

    async def test_pcm_audio_is_split_into_bounded_device_frames(self):
        websocket = FakeWebSocket()
        session = self.asr.VoiceCallSession(
            websocket,
            "BASE-DEVICE-FRAMES",
            "OWNER-DEVICE-FRAMES",
            client_kind="device",
            output_audio_format="pcm",
            output_sample_rate=24000,
            max_audio_frame_bytes=4096,
        )
        self.asr.voice_session_registry.replace(session)
        turn = await session._begin_turn("fixture")
        payload = bytes(index % 251 for index in range(9000))

        self.assertTrue(await session._send_turn_audio(turn, payload))
        chunk_messages = [
            message
            for message in websocket.json_messages
            if message.get("type") == "audio_chunk"
        ]
        self.assertEqual([len(item) for item in websocket.binary_messages], [4096, 4096, 808])
        self.assertEqual(
            [message["chunk_index"] for message in chunk_messages],
            [0, 1, 2],
        )
        self.assertTrue(all(message["chunk_count"] == 3 for message in chunk_messages))
        self.assertTrue(all(message["audio_format"] == "pcm" for message in chunk_messages))
        self.assertTrue(all(message["sample_format"] == "s16le" for message in chunk_messages))
        self.assertEqual(b"".join(websocket.binary_messages), payload)
        await session.close_volc()
        self.asr.voice_session_registry.discard(session)

    async def test_initial_provider_connection_announces_ready(self):
        websocket = FakeWebSocket()
        session = self.asr.VoiceCallSession(
            websocket,
            "BASE-DEVICE-READY",
            "OWNER-DEVICE-READY",
            client_kind="device",
            output_audio_format="pcm",
        )
        session.connect_volc_with_retry = AsyncMock(return_value=True)

        await session._start_volc_connection_background()

        self.assertIn(
            {
                "type": "status",
                "status": "ready",
                "session_id": session.session_id,
            },
            websocket.json_messages,
        )
        await session.close_volc()

    async def test_device_can_explicitly_interrupt_active_playback(self):
        websocket = FakeWebSocket()
        session = self.asr.VoiceCallSession(
            websocket,
            "BASE-DEVICE-CANCEL",
            "OWNER-DEVICE-CANCEL",
            client_kind="device",
            output_audio_format="pcm",
        )
        self.asr.voice_session_registry.replace(session)
        turn = await session._begin_turn("fixture")

        await session.handle_client_message({
            "type": "cancel_turn",
            "session_id": session.session_id,
        })

        self.assertTrue(turn.cancel_event.is_set())
        self.assertIsNone(session._active_turn)
        self.assertIn("stop_audio", [item.get("type") for item in websocket.json_messages])
        acknowledgements = [
            item for item in websocket.json_messages
            if item.get("type") == "cancel_ack"
        ]
        self.assertEqual(acknowledgements[0]["interrupted_turn_id"], turn.turn_id)
        await session.close_volc()
        self.asr.voice_session_registry.discard(session)

    async def test_pcm_playback_receipt_completes_the_original_turn(self):
        websocket = FakeWebSocket()
        session = self.asr.VoiceCallSession(
            websocket,
            "BASE-DEVICE-RECEIPT",
            "OWNER-DEVICE-RECEIPT",
            client_kind="device",
            output_audio_format="pcm",
            max_audio_frame_bytes=4096,
        )
        self.asr.voice_session_registry.replace(session)
        turn = await session._begin_turn("fixture")
        await session._send_turn_audio(turn, b"\x00\x01" * 3000)
        audio_id = next(iter(turn.audio_ids))
        turn.audio_stream_complete = True

        for stage in ("decoded", "playback_started", "playback_completed"):
            await session.handle_client_message({
                "type": "audio_playback",
                "session_id": session.session_id,
                "turn_id": turn.turn_id,
                "audio_id": audio_id,
                "stage": stage,
            })

        self.assertTrue(turn.playback_done.is_set())
        self.assertIn("playback_completed", turn.timestamps)
        await session.close_volc()
        self.asr.voice_session_registry.discard(session)

    async def test_playback_receipts_reject_out_of_order_and_conflicting_terminal(self):
        websocket = FakeWebSocket()
        session = self.asr.VoiceCallSession(
            websocket,
            "BASE-DEVICE-RECEIPT-ORDER",
            "OWNER-DEVICE-RECEIPT-ORDER",
            client_kind="device",
            output_audio_format="pcm",
            max_audio_frame_bytes=4096,
        )
        self.asr.voice_session_registry.replace(session)
        turn = await session._begin_turn("fixture")
        await session._send_turn_audio(turn, b"\x00\x01" * 100)
        audio_id = next(iter(turn.audio_ids))
        turn.audio_stream_complete = True
        base_receipt = {
            "type": "audio_playback",
            "session_id": session.session_id,
            "turn_id": turn.turn_id,
            "audio_id": audio_id,
        }

        await session.handle_client_message({
            **base_receipt,
            "stage": "playback_completed",
        })
        self.assertFalse(turn.playback_done.is_set())
        self.assertNotIn(audio_id, turn.audio_playback_stages)

        for stage in ("decoded", "decoded", "playback_started",
                      "playback_completed", "playback_failed"):
            await session.handle_client_message({
                **base_receipt,
                "stage": stage,
            })

        self.assertTrue(turn.playback_done.is_set())
        self.assertEqual(
            turn.audio_playback_stages[audio_id],
            "playback_completed",
        )
        self.assertFalse(turn.audio_failed)
        self.assertNotIn("playback_failed", turn.timestamps)
        await session.close_volc()
        self.asr.voice_session_registry.discard(session)

    async def test_device_turn_reuses_dialogue_owner_memory_path_with_pcm_output(self):
        websocket = FakeWebSocket()
        session = self.asr.VoiceCallSession(
            websocket,
            "BASE-DEVICE-DIALOGUE",
            "OWNER-DEVICE-DIALOGUE",
            client_kind="device",
            output_audio_format="pcm",
            output_sample_rate=24000,
            max_audio_frame_bytes=4096,
        )
        self.asr.voice_session_registry.replace(session)
        session._reconnect_for_next_turn = AsyncMock(return_value=None)
        captured: dict = {}

        def fake_process(base_id, text, **kwargs):
            captured.update(base_id=base_id, text=text, **kwargs)
            kwargs["text_sink"]("fixture reply")
            kwargs["audio_sink"](b"\x01\x02" * 200)
            return {
                "reply": "fixture reply",
                "brain_mode": "online",
                "tts_engine": "fixture",
            }

        with patch.object(self.asr, "process_text_input", side_effect=fake_process):
            await session._finalize_text("remember this")
            turn = session._active_turn
            deadline = asyncio.get_running_loop().time() + 1
            while not turn.audio_ids:
                if asyncio.get_running_loop().time() >= deadline:
                    self.fail("device turn did not emit audio")
                await asyncio.sleep(0.005)
            audio_id = next(iter(turn.audio_ids))
            for stage in ("decoded", "playback_started", "playback_completed"):
                await session.handle_client_message({
                    "type": "audio_playback",
                    "session_id": session.session_id,
                    "turn_id": turn.turn_id,
                    "audio_id": audio_id,
                    "stage": stage,
                })
            await asyncio.wait_for(asyncio.shield(turn.task), timeout=2)

        self.assertEqual(captured["base_id"], "BASE-DEVICE-DIALOGUE")
        self.assertEqual(captured["owner_user_id"], "OWNER-DEVICE-DIALOGUE")
        self.assertEqual(captured["text"], "remember this")
        self.assertEqual(captured["audio_format"], "pcm")
        self.assertEqual(captured["audio_sample_rate"], 24000)
        self.assertEqual(captured["session_id"], session.session_id)
        self.assertEqual(captured["turn_id"], turn.turn_id)
        await session.close_volc()
        self.asr.voice_session_registry.discard(session)

    async def test_pcm_delivery_requests_pcm_from_tts_provider(self):
        audio_path = self.temp / "fixture.pcm"
        audio_path.write_bytes(b"\x01\x02" * 100)
        sink = Mock(return_value=True)
        with (
            patch.object(self.tts, "is_volc_configured", return_value=True),
            patch.object(
                self.tts,
                "_synthesize_volcano_impl",
                return_value=str(audio_path),
            ) as provider,
        ):
            result = self.tts.speak_sentence_streaming(
                "fixture",
                {"tts_engine": "volcano_tts", "speaker": "speaker-a"},
                "OWNER__FIGURE",
                audio_sink=sink,
                audio_format="pcm",
                sample_rate=24000,
            )

        self.assertTrue(result["success"])
        provider.assert_called_once_with(
            "fixture",
            speaker="speaker-a",
            figure_id="OWNER__FIGURE",
            timeout=10.0,
            audio_format="pcm",
            sample_rate=24000,
        )
        sink.assert_called_once_with(audio_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
