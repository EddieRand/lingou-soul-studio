import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from hardware_adapter.portable_voice_client import (
    INPUT_FRAME_BYTES,
    PortableVoiceClient,
    SoundDeviceAudioBackend,
)


class FakeAudio:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.muted = False
        self.played: list[bytes] = []
        self.playback_stops = 0
        self.alerts = 0
        self.input_queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def read_input(self):
        return await self.input_queue.get()

    async def play(self, payload):
        self.played.append(payload)

    async def stop_playback(self):
        self.playback_stops += 1

    async def alert(self):
        self.alerts += 1

    def set_input_muted(self, muted):
        self.muted = muted


class FakeWebSocket:
    def __init__(self):
        self.sent: list[bytes | str] = []

    async def send(self, payload):
        self.sent.append(payload)


class PortableVoiceClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.audio = FakeAudio()
        self.client = PortableVoiceClient(
            server_url="ws://127.0.0.1:8000/api/asr/device-stream",
            device_credential="BASE-PORTABLE." + ("x" * 43),
            audio=self.audio,
        )
        self.websocket = FakeWebSocket()
        self.client.websocket = self.websocket
        self.client.session_id = "SESSION-1"

    @staticmethod
    def _chunk(**overrides):
        payload = {
            "type": "audio_chunk",
            "session_id": "SESSION-1",
            "turn_id": "TURN-1",
            "audio_id": "AUDIO-1",
            "chunk_index": 0,
            "chunk_count": 1,
            "chunk_byte_length": 4,
            "audio_format": "pcm",
            "sample_rate": 24000,
            "channels": 1,
            "sample_format": "s16le",
        }
        payload.update(overrides)
        return payload

    async def _wait_for_playback(self):
        await asyncio.wait_for(self.client._playback_queue.join(), timeout=1)

    async def test_pcm_chunk_is_played_and_receipts_preserve_original_ids(self):
        await self.client._handle_server_message({
            "type": "status",
            "status": "listening",
            "session_id": "SESSION-1",
            "audio_format": "pcm",
            "audio_sample_rate": 24000,
        })
        await self.client._handle_server_message({
            "type": "speaking",
            "status": "start",
            "session_id": "SESSION-1",
            "turn_id": "TURN-1",
        })
        await self.client._handle_server_message(self._chunk())
        await self.client._handle_audio_frame(b"\x01\x00\x02\x00")
        await self._wait_for_playback()

        self.assertTrue(self.audio.muted)
        self.assertEqual(self.audio.played, [b"\x01\x00\x02\x00"])
        self.assertEqual(self.client.last_completed_audio_id, "AUDIO-1")
        self.assertTrue(self.client.playback_completed_event.is_set())
        receipts = [json.loads(item) for item in self.websocket.sent]
        self.assertEqual(
            [item["stage"] for item in receipts],
            ["decoded", "playback_started", "playback_completed"],
        )
        self.assertTrue(all(item["session_id"] == "SESSION-1" for item in receipts))
        self.assertTrue(all(item["turn_id"] == "TURN-1" for item in receipts))
        self.assertTrue(all(item["audio_id"] == "AUDIO-1" for item in receipts))

    async def test_final_and_reply_text_are_exposed_for_health_checks(self):
        await self.client._handle_server_message({
            "type": "final",
            "session_id": "SESSION-1",
            "text": "recognized",
        })
        await self.client._handle_server_message({
            "type": "reply",
            "session_id": "SESSION-1",
            "reply": "answered",
        })
        self.assertEqual(self.client.last_final_text, "recognized")
        self.assertEqual(self.client.last_reply_text, "answered")

    async def test_interrupt_reports_failure_and_cancels_current_turn(self):
        self.client.server_speaking = True
        await self.client._handle_server_message(self._chunk(
            turn_id="TURN-2",
            audio_id="AUDIO-2",
            chunk_count=2,
        ))

        await self.client.interrupt_or_resume()

        messages = [json.loads(item) for item in self.websocket.sent]
        self.assertEqual(messages[0]["type"], "audio_playback")
        self.assertEqual(messages[0]["stage"], "playback_failed")
        self.assertEqual(messages[0]["audio_id"], "AUDIO-2")
        self.assertEqual(messages[1], {
            "type": "cancel_turn",
            "session_id": "SESSION-1",
        })
        self.assertEqual(self.audio.playback_stops, 1)

    async def test_session_replacement_pauses_until_explicit_resume(self):
        await self.client._handle_server_message({
            "type": "session_replaced",
            "session_id": "SESSION-1",
        })
        self.assertTrue(self.client.paused_for_replacement)
        self.assertEqual(self.audio.playback_stops, 1)

        await self.client.interrupt_or_resume()

        self.assertFalse(self.client.paused_for_replacement)
        self.assertTrue(self.client.resume_event.is_set())

    async def test_microphone_sender_requires_exact_twenty_millisecond_frames(self):
        await self.audio.input_queue.put(b"\x00" * INPUT_FRAME_BYTES)
        sender = asyncio.create_task(
            self.client._send_microphone(self.websocket)
        )
        deadline = asyncio.get_running_loop().time() + 1
        while not self.websocket.sent:
            if asyncio.get_running_loop().time() >= deadline:
                self.fail("microphone frame was not sent")
            await asyncio.sleep(0.005)
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        self.assertEqual(self.websocket.sent, [b"\x00" * INPUT_FRAME_BYTES])

    async def test_server_stop_unmutes_input_and_clears_playback(self):
        self.client.server_speaking = True
        self.client.current_turn_id = "TURN-1"
        self.audio.set_input_muted(True)
        await self.client._handle_server_message({
            "type": "stop_audio",
            "session_id": "SESSION-1",
            "turn_id": "TURN-1",
        })
        self.assertFalse(self.client.server_speaking)
        self.assertFalse(self.audio.muted)
        self.assertEqual(self.audio.playback_stops, 1)

    async def test_pcm_metadata_and_frame_boundaries_are_strict(self):
        invalid = (
            {"audio_format": "mp3"},
            {"channels": 2},
            {"sample_format": "float32"},
            {"sample_rate": 16000},
            {"chunk_byte_length": 0},
            {"chunk_byte_length": 3},
            {"chunk_byte_length": 4098},
            {"chunk_index": 1},
            {"chunk_count": 0},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaises(RuntimeError):
                    await self.client._handle_server_message(
                        self._chunk(**overrides)
                    )
                self.client.pending_binary = None
                self.client.audio_streams.clear()

    async def test_missing_duplicate_and_changed_count_chunks_are_rejected(self):
        await self.client._handle_server_message(self._chunk(chunk_count=3))
        await self.client._handle_audio_frame(b"\x00" * 4)
        with self.assertRaises(RuntimeError):
            await self.client._handle_server_message(
                self._chunk(chunk_index=2, chunk_count=3)
            )

        await self._wait_for_playback()
        await self.client._reset_playback(report_failure=False)
        self.client.cancelled_turns.clear()
        self.client.current_turn_id = ""
        await self.client._handle_server_message(
            self._chunk(turn_id="TURN-2", audio_id="AUDIO-2", chunk_count=3)
        )
        await self.client._handle_audio_frame(b"\x00" * 4)
        with self.assertRaises(RuntimeError):
            await self.client._handle_server_message(
                self._chunk(
                    turn_id="TURN-2",
                    audio_id="AUDIO-2",
                    chunk_index=1,
                    chunk_count=2,
                )
            )

    async def test_old_session_audio_is_consumed_without_playback_or_state_change(self):
        await self.client._handle_server_message(self._chunk(
            session_id="SESSION-OLD",
            turn_id="TURN-OLD",
            audio_id="AUDIO-OLD",
        ))
        await self.client._handle_audio_frame(b"\x00" * 4)

        self.assertEqual(self.client.session_id, "SESSION-1")
        self.assertEqual(self.audio.played, [])
        self.assertEqual(self.websocket.sent, [])

    async def test_cancelled_turn_discards_pending_and_later_chunks(self):
        self.client.server_speaking = True
        await self.client._handle_server_message(self._chunk(chunk_count=2))
        await self.client._handle_audio_frame(b"\x01\x00\x02\x00")
        await self._wait_for_playback()
        await self.client.interrupt_or_resume()
        played_before_late_frame = list(self.audio.played)

        await self.client._handle_server_message(
            self._chunk(chunk_index=1, chunk_count=2)
        )
        await self.client._handle_audio_frame(b"\x03\x00\x04\x00")

        self.assertEqual(self.audio.played, played_before_late_frame)
        receipts = [json.loads(item) for item in self.websocket.sent]
        self.assertNotIn(
            "playback_completed",
            [item.get("stage") for item in receipts],
        )

        other = PortableVoiceClient(
            server_url=self.client.server_url,
            device_credential=self.client.device_credential,
            audio=FakeAudio(),
        )
        other.websocket = FakeWebSocket()
        other.session_id = "SESSION-1"
        other.server_speaking = True
        await other._handle_server_message(self._chunk(chunk_count=2))
        await other.interrupt_or_resume()
        await other._handle_audio_frame(b"\x00" * 4)
        self.assertEqual(other.audio.played, [])

    async def test_old_turn_stop_does_not_interrupt_current_turn(self):
        self.client.server_speaking = True
        await self.client._handle_server_message(self._chunk())
        await self.client._handle_server_message({
            "type": "stop_audio",
            "session_id": "SESSION-1",
            "turn_id": "TURN-OLD",
        })

        self.assertIsNotNone(self.client.pending_binary)
        self.assertTrue(self.client.server_speaking)
        self.assertEqual(self.audio.playback_stops, 0)

    async def test_new_connection_clears_health_observations(self):
        self.client.last_final_text = "old final"
        self.client.last_reply_text = "old reply"
        self.client.last_completed_audio_id = "old audio"
        self.client.playback_completed_event.set()
        self.client.provider_ready_event.set()

        await self.client._reset_connection_state(report_failure=False)
        self.client.websocket = self.websocket
        await self.client._handle_server_message({
            "type": "status",
            "status": "listening",
            "session_id": "SESSION-2",
            "audio_format": "pcm",
            "audio_sample_rate": 24000,
        })

        self.assertEqual(self.client.session_id, "SESSION-2")
        self.assertEqual(self.client.last_final_text, "")
        self.assertEqual(self.client.last_reply_text, "")
        self.assertEqual(self.client.last_completed_audio_id, "")
        self.assertFalse(self.client.playback_completed_event.is_set())
        self.assertFalse(self.client.provider_ready_event.is_set())

    async def test_runtime_status_does_not_repeat_audio_negotiation(self):
        await self.client._handle_server_message({
            "type": "status",
            "status": "ready",
            "session_id": "SESSION-1",
        })

        self.assertEqual(self.client.session_id, "SESSION-1")
        self.assertTrue(self.client.provider_ready_event.is_set())
        self.assertTrue(self.client._accept_turn("TURN-2", allow_new=True))
        self.assertTrue(self.client.provider_ready_event.is_set())

    async def test_slow_playback_does_not_block_stop_control(self):
        play_started = asyncio.Event()

        async def slow_play(_payload):
            play_started.set()
            await asyncio.sleep(10)

        self.audio.play = slow_play
        self.client.server_speaking = True
        await self.client._handle_server_message(self._chunk())
        await self.client._handle_audio_frame(b"\x00" * 4)
        await asyncio.wait_for(play_started.wait(), timeout=1)

        await asyncio.wait_for(
            self.client._handle_server_message({
                "type": "stop_audio",
                "session_id": "SESSION-1",
                "turn_id": "TURN-1",
            }),
            timeout=0.2,
        )

        self.assertEqual(self.audio.playback_stops, 1)
        receipts = [json.loads(item) for item in self.websocket.sent]
        self.assertNotIn(
            "playback_completed",
            [item.get("stage") for item in receipts],
        )

    async def test_clean_disconnect_uses_reconnect_backoff(self):
        attempts = 0
        started_at = asyncio.get_running_loop().time()

        async def connection():
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                self.client.request_stop()

        self.client._run_connection = connection
        self.client.reconnect_initial_seconds = 0.02
        self.client.reconnect_max_seconds = 0.02

        await self.client.run()

        self.assertEqual(attempts, 2)
        self.assertGreaterEqual(
            asyncio.get_running_loop().time() - started_at,
            0.015,
        )
        self.assertEqual(self.audio.alerts, 0)

    async def test_shutdown_closes_audio_when_stop_playback_fails(self):
        async def fail_stop_playback():
            raise RuntimeError("fixture abort failure")

        async def connection():
            self.client.request_stop()

        self.audio.stop_playback = fail_stop_playback
        self.client._run_connection = connection

        await self.client.run()

        self.assertTrue(self.audio.stopped)

    async def test_partial_audio_start_closes_created_input_stream(self):
        state = {"closed": False}

        class InputStream:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                state["closed"] = True

        def fail_output(**_kwargs):
            raise RuntimeError("fixture output init failed")

        audio = SoundDeviceAudioBackend()
        sounddevice = SimpleNamespace(
            RawInputStream=InputStream,
            RawOutputStream=fail_output,
        )
        with patch.object(audio, "_sounddevice", return_value=sounddevice):
            with self.assertRaisesRegex(RuntimeError, "fixture output init failed"):
                await audio.start()

        self.assertTrue(state["closed"])
        self.assertIsNone(audio._input_stream)

    async def test_transient_disconnect_alerts_and_reconnects(self):
        attempts = 0

        async def connection():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("fixture disconnect")
            self.client.request_stop()

        self.client._run_connection = connection
        self.client.reconnect_initial_seconds = 0.001
        self.client.reconnect_max_seconds = 0.001

        await self.client.run()

        self.assertEqual(attempts, 2)
        self.assertEqual(self.audio.alerts, 1)
        self.assertTrue(self.audio.started)
        self.assertTrue(self.audio.stopped)

    def test_invalid_urls_and_credentials_are_rejected(self):
        with self.assertRaises(ValueError):
            PortableVoiceClient(
                server_url="http://127.0.0.1:8000",
                device_credential="BASE.secret",
                audio=self.audio,
            )
        with self.assertRaises(ValueError):
            PortableVoiceClient(
                server_url="ws://127.0.0.1:8000/api/asr/device-stream",
                device_credential="invalid",
                audio=self.audio,
            )


if __name__ == "__main__":
    unittest.main()
