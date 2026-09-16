"""Run explicitly: python -B tests/test_voice_turns.py.

Step-05 deterministic voice-session tests. Providers and WebSockets are fake;
the suite does not use credentials, microphones, speakers, or external network.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True


class FakeWebSocket:
    def __init__(self):
        self.json_messages: list[dict] = []
        self.binary_messages: list[bytes] = []
        self.closed: list[tuple[int, str]] = []

    async def send_json(self, payload: dict):
        self.json_messages.append(payload)

    async def send_bytes(self, payload: bytes):
        self.binary_messages.append(payload)

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed.append((code, reason))


class VoiceTurnTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(
            cls.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="lingou-voice-turns-")
            )
        ).resolve()
        clean_env = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")
            if key in os.environ
        }
        clean_env.update(
            LINGOU_DATA_DIR=str(cls.temp / "runtime"),
            LINGOU_LOAD_DOTENV="0",
            LINGOU_WARMUP_ON_STARTUP="0",
            LINGOU_JWT_SECRET="step-05-test-only-jwt-secret-at-least-32-bytes",
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))
        cls.stack.enter_context(
            patch(
                "dotenv.load_dotenv",
                side_effect=AssertionError("dotenv must stay disabled"),
            )
        )

        from app.api import asr
        from app.core import dialogue_engine, online_brain
        from data import store

        cls.asr = asr
        cls.dialogue_engine = dialogue_engine
        cls.online_brain = online_brain
        cls.store = store

    async def asyncSetUp(self):
        with self.asr.voice_session_registry._lock:
            self.asr.voice_session_registry._sessions.clear()
        self.websocket = FakeWebSocket()
        self.session = self.asr.VoiceCallSession(
            self.websocket,
            "BASE-VOICE-TEST",
            "OWNER-VOICE-TEST",
        )
        self.asr.voice_session_registry.replace(self.session)
        self.session._reconnect_for_next_turn = AsyncMock(return_value=None)

    async def asyncTearDown(self):
        await self.session.close_volc()
        self.asr.voice_session_registry.discard(self.session)

    async def _ack_all_audio(self, turn):
        deadline = asyncio.get_running_loop().time() + 1
        while not turn.audio_ids:
            if asyncio.get_running_loop().time() >= deadline:
                self.fail("turn did not emit audio")
            await asyncio.sleep(0.005)
        for audio_id in list(turn.audio_ids):
            for stage in ("decoded", "playback_started", "playback_completed"):
                await self.session.handle_client_message({
                    "type": "audio_playback",
                    "session_id": self.session.session_id,
                    "turn_id": turn.turn_id,
                    "audio_id": audio_id,
                    "stage": stage,
                })

    async def test_superseded_turn_cannot_emit_late_text_audio_or_reply(self):
        first_started = threading.Event()
        first_finished = threading.Event()
        second_started = threading.Event()
        release_second = threading.Event()

        def fake_process(_base_id, text, *, audio_sink, text_sink, cancel_event, **_kwargs):
            if text == "first":
                first_started.set()
                while not cancel_event.is_set():
                    time.sleep(0.005)
                text_sink("late-first")
                audio_sink(b"late-first-audio")
                first_finished.set()
                return {
                    "reply": "late-first",
                    "brain_mode": "online",
                    "tts_engine": "fake",
                }
            second_started.set()
            while not release_second.is_set():
                time.sleep(0.005)
            text_sink("second-chunk")
            audio_sink(b"second-audio")
            return {
                "reply": "second-reply",
                "brain_mode": "online",
                "tts_engine": "fake",
            }

        with patch.object(self.asr, "process_text_input", side_effect=fake_process):
            await self.session._finalize_text("first")
            self.assertTrue(
                await asyncio.to_thread(first_started.wait, 1),
                "first turn did not start",
            )
            first_turn_id = self.session._active_turn.turn_id
            await self.session._finalize_text("second")
            second_turn = self.session._active_turn
            self.assertNotEqual(first_turn_id, second_turn.turn_id)
            self.assertTrue(await asyncio.to_thread(second_started.wait, 1))
            self.assertTrue(await asyncio.to_thread(first_finished.wait, 1))
            self.assertIs(self.session._active_turn, second_turn)
            self.assertTrue(self.session._replying)
            release_second.set()
            await self._ack_all_audio(second_turn)
            await asyncio.wait_for(asyncio.shield(second_turn.task), timeout=2)
            await asyncio.sleep(0)

        serialized = str(self.websocket.json_messages)
        self.assertNotIn("late-first", serialized)
        self.assertEqual(self.websocket.binary_messages, [b"second-audio"])
        replies = [
            item for item in self.websocket.json_messages
            if item.get("type") == "reply" and item.get("reply")
        ]
        self.assertEqual([item["reply"] for item in replies], ["second-reply"])
        self.assertEqual(replies[0]["turn_id"], second_turn.turn_id)
        cancelled = [
            item for item in self.websocket.json_messages
            if item.get("type") == "turn_cancelled"
        ]
        self.assertEqual(cancelled[0]["turn_id"], first_turn_id)

    async def test_disconnect_cancels_generation_and_suppresses_late_output(self):
        started = threading.Event()
        finished = threading.Event()

        def fake_process(_base_id, _text, *, audio_sink, text_sink, cancel_event, **_kwargs):
            started.set()
            while not cancel_event.is_set():
                time.sleep(0.005)
            text_sink("late-after-close")
            audio_sink(b"late-after-close")
            finished.set()
            return {
                "reply": "late-after-close",
                "brain_mode": "online",
                "tts_engine": "fake",
            }

        with patch.object(self.asr, "process_text_input", side_effect=fake_process):
            await self.session._finalize_text("disconnect")
            turn = self.session._active_turn
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            await self.session.close_volc()
            self.assertTrue(turn.cancel_event.is_set())
            self.assertTrue(await asyncio.to_thread(finished.wait, 1))
            await asyncio.sleep(0)

        self.assertNotIn("late-after-close", str(self.websocket.json_messages))
        self.assertEqual(self.websocket.binary_messages, [])

    async def test_newest_connection_replaces_previous_without_registry_race(self):
        old_turn = await self.session._begin_turn("old")
        replacement_ws = FakeWebSocket()
        replacement = self.asr.VoiceCallSession(
            replacement_ws,
            self.session.base_id,
            self.session.owner_user_id,
        )

        previous = self.asr.voice_session_registry.replace(replacement)
        self.assertIs(previous, self.session)
        await previous.supersede(replacement.session_id)

        self.assertTrue(old_turn.cancel_event.is_set())
        self.assertEqual(
            self.websocket.closed[-1][0],
            self.asr.SESSION_REPLACED_CLOSE_CODE,
        )
        self.assertEqual(
            [
                message["type"]
                for message in self.websocket.json_messages
                if message["type"] == "session_replaced"
            ],
            ["session_replaced"],
        )
        self.assertTrue(self.asr.voice_session_registry.is_current(replacement))
        self.assertFalse(self.asr.voice_session_registry.discard(self.session))
        self.assertTrue(self.asr.voice_session_registry.is_current(replacement))
        await replacement.close_volc()
        self.asr.voice_session_registry.discard(replacement)

    async def test_completed_turn_reports_identifiers_and_key_timings(self):
        def fake_process(_base_id, _text, *, audio_sink, text_sink, **_kwargs):
            text_sink("chunk")
            audio_sink(b"audio")
            return {
                "reply": "complete",
                "brain_mode": "online",
                "tts_engine": "fake",
            }

        with patch.object(self.asr, "process_text_input", side_effect=fake_process):
            await self.session._finalize_text("metrics")
            turn = self.session._active_turn
            await self._ack_all_audio(turn)
            await asyncio.wait_for(asyncio.shield(turn.task), timeout=2)

        turn_messages = [
            item for item in self.websocket.json_messages
            if item.get("turn_id") == turn.turn_id
        ]
        self.assertTrue(turn_messages)
        self.assertTrue(
            all(item["session_id"] == self.session.session_id for item in turn_messages)
        )
        metrics = next(
            item for item in turn_messages if item["type"] == "turn_metrics"
        )
        self.assertEqual(metrics["status"], "completed")
        self.assertIn("speech_finalized_ms", metrics["timings"])
        self.assertIn("reply_started_ms", metrics["timings"])
        self.assertIn("first_text_ms", metrics["timings"])
        self.assertIn("first_audio_ms", metrics["timings"])
        self.assertIn("first_audio_synthesized_ms", metrics["timings"])
        self.assertIn("first_audio_transferred_ms", metrics["timings"])
        self.assertIn("first_audio_decoded_ms", metrics["timings"])
        self.assertIn("playback_started_ms", metrics["timings"])
        self.assertIn("playback_completed_ms", metrics["timings"])
        self.assertIn("reply_completed_ms", metrics["timings"])
        self.assertEqual(self.websocket.binary_messages, [b"audio"])
        audio_stages = [
            item["stage"]
            for item in turn_messages
            if item.get("type") == "audio_output"
        ]
        self.assertEqual(
            audio_stages,
            ["synthesized", "transferred", "stream_complete"],
        )

    async def test_turn_without_audio_reports_failure_instead_of_success(self):
        def fake_process(_base_id, _text, *, text_sink, **_kwargs):
            text_sink("text-only")
            return {
                "reply": "text-only",
                "brain_mode": "online",
                "tts_engine": "none",
                "audio_synthesized": False,
                "audio_transferred": False,
                "audio_error": "no_deliverable_audio",
            }

        with patch.object(self.asr, "process_text_input", side_effect=fake_process):
            await self.session._finalize_text("no audio")
            turn = self.session._active_turn
            await asyncio.wait_for(asyncio.shield(turn.task), timeout=2)

        failures = [
            item for item in self.websocket.json_messages
            if item.get("type") == "audio_output"
            and item.get("stage") == "failed"
        ]
        self.assertEqual(failures[0]["error_code"], "NO_AUDIO_GENERATED")
        metrics = next(
            item for item in self.websocket.json_messages
            if item.get("type") == "turn_metrics"
            and item.get("turn_id") == turn.turn_id
        )
        self.assertEqual(metrics["status"], "audio_failed")
        reply = next(
            item for item in self.websocket.json_messages
            if item.get("type") == "reply"
            and item.get("turn_id") == turn.turn_id
        )
        self.assertEqual(reply["audio_status"], "failed")

    async def test_cancellation_closes_the_active_model_stream(self):
        entered = threading.Event()
        closed = threading.Event()

        class BlockingResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

            def __iter__(self):
                return self

            def __next__(self):
                entered.set()
                closed.wait(timeout=2)
                raise OSError("stream closed")

            def close(self):
                closed.set()

        token = self.asr.TurnCancellation()
        with patch(
            "urllib.request.urlopen",
            return_value=BlockingResponse(),
        ):
            task = asyncio.create_task(
                asyncio.to_thread(
                    lambda: list(
                        self.online_brain._call_doubao_streaming(
                            [],
                            cancel_event=token,
                        )
                    )
                )
            )
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            token.set()
            result = await asyncio.wait_for(task, timeout=2)

        self.assertTrue(closed.is_set())
        self.assertEqual(result, [])

    def test_cancelled_dialogue_does_not_persist_figure_or_log(self):
        owner = "OWNER-PERSISTENCE"
        base_id = "BASE-PERSISTENCE"
        figure_id = "FIGURE-PERSISTENCE"
        now = datetime.now(timezone.utc).isoformat()
        self.store.save_base(
            base_id,
            {
                "base_id": base_id,
                "active_figure_id": figure_id,
                "status": "waiting",
                "created_at": now,
                "updated_at": now,
            },
            owner_user_id=owner,
        )
        self.store.save_figure(
            figure_id,
            {
                "figure_id": figure_id,
                "name": "Fixture",
                "voice_profile": {},
                "soul_profile": {"emotion_state": {}},
                "memory": {"interaction_count": 0},
            },
            user_id=owner,
        )
        token = self.asr.TurnCancellation()

        def cancelled_stream(*_args, **_kwargs):
            yield "partial"
            token.set()

        with (
            patch.object(
                self.dialogue_engine,
                "route_reply_streaming",
                side_effect=cancelled_stream,
            ),
            patch.object(
                self.dialogue_engine,
                "speak_sentence_streaming",
                return_value={"success": True},
            ),
        ):
            result = self.dialogue_engine.process_text_input(
                base_id,
                "cancel me",
                brain_mode_override="online",
                cancel_event=token,
                owner_user_id=owner,
            )

        self.assertTrue(result["cancelled"])
        saved = self.store.get_figure(figure_id, user_id=owner)
        self.assertEqual(saved["memory"]["interaction_count"], 0)
        self.assertEqual(
            self.store.list_dialogue_logs(user_id=owner, figure_id=figure_id),
            [],
        )

    def test_completed_dialogue_persists_session_and_turn_ids(self):
        owner = "OWNER-TRACE"
        base_id = "BASE-TRACE"
        figure_id = "FIGURE-TRACE"
        now = datetime.now(timezone.utc).isoformat()
        self.store.save_base(
            base_id,
            {
                "base_id": base_id,
                "active_figure_id": figure_id,
                "status": "waiting",
                "created_at": now,
                "updated_at": now,
            },
            owner_user_id=owner,
        )
        self.store.save_figure(
            figure_id,
            {
                "figure_id": figure_id,
                "name": "Trace Fixture",
                "voice_profile": {},
                "soul_profile": {
                    "archetype": "软萌治愈型",
                    "emotion_state": {
                        "happy": 50,
                        "lonely": 0,
                        "attached": 0,
                        "annoyed": 0,
                        "attention": 0,
                        "sleepy": 0,
                        "last_dialogue_at": None,
                    },
                },
                "memory": {
                    "interaction_count": 0,
                    "favorite_responses": [],
                },
            },
            user_id=owner,
        )

        def completed_stream(*_args, **_kwargs):
            yield "complete"
            return "online"

        with (
            patch.object(
                self.dialogue_engine,
                "route_reply_streaming",
                side_effect=completed_stream,
            ),
            patch.object(
                self.dialogue_engine,
                "speak_sentence_streaming",
                return_value={"success": True},
            ),
            patch.object(
                self.dialogue_engine,
                "_background_compress_history",
            ),
        ):
            result = self.dialogue_engine.process_text_input(
                base_id,
                "trace me",
                brain_mode_override="online",
                cancel_event=self.asr.TurnCancellation(),
                owner_user_id=owner,
                session_id="SESSION-TRACE",
                turn_id="TURN-TRACE",
            )

        self.assertEqual(result["session_id"], "SESSION-TRACE")
        self.assertEqual(result["turn_id"], "TURN-TRACE")
        logs = self.store.list_dialogue_logs(
            user_id=owner,
            figure_id=figure_id,
        )
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["dialogue_id"], "TURN-TRACE")
        self.assertEqual(logs[0]["session_id"], "SESSION-TRACE")
        self.assertEqual(logs[0]["turn_id"], "TURN-TRACE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
