"""Run explicitly: python -B tests/test_audio_delivery.py.

Step-07 audio-delivery tests. Data, providers, audio devices and network are
fully isolated; generated audio is a fictional byte fixture.
"""

from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True


class AudioDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(
            cls.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="lingou-audio-delivery-")
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
            LINGOU_JWT_SECRET="step-07-test-only-jwt-secret-at-least-32-bytes",
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))
        cls.stack.enter_context(
            patch(
                "dotenv.load_dotenv",
                side_effect=AssertionError("dotenv must stay disabled"),
            )
        )

        from app import main
        from app.api import voice
        from app.core import tts_adapter
        from data import store

        cls.main = main
        cls.voice = voice
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

    def _client(self):
        from fastapi.testclient import TestClient

        return TestClient(self.main.app)

    def _account(self, client, label: str) -> tuple[dict, dict]:
        username = f"{label}-{uuid.uuid4().hex}"
        registered = client.post(
            "/api/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": "fictional-password",
            },
        )
        self.assertEqual(registered.status_code, 200, registered.text)
        session = client.post(
            "/api/auth/login",
            data={"username": username, "password": "fictional-password"},
        )
        self.assertEqual(session.status_code, 200, session.text)
        return registered.json(), session.json()

    @staticmethod
    def _headers(session: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {session['access_token']}"}

    def _figure(self, client, session: dict, speaker: str) -> dict:
        response = client.post(
            "/api/figures",
            json={
                "name": "Audio Fixture",
                "figure_type": "soul",
                "voice_profile": {"speaker": speaker},
            },
            headers=self._headers(session),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_browser_delivery_without_audio_is_not_success(self):
        sink = Mock(return_value=True)
        with (
            patch.object(self.tts, "is_volc_configured", return_value=False),
            patch.object(self.tts, "is_voice_pool_ready", return_value=False),
            patch.object(
                self.tts,
                "synthesize_system_say",
                side_effect=AssertionError("must not play on the server"),
            ),
        ):
            result = self.tts.speak_sentence_streaming(
                "fixture",
                {"tts_engine": "volcano_tts"},
                "OWNER__FIGURE",
                audio_sink=sink,
            )

        self.assertFalse(result["success"])
        self.assertFalse(result["synthesized"])
        self.assertFalse(result["transferred"])
        self.assertEqual(result["error"], "no_deliverable_audio")
        sink.assert_not_called()

    def test_synthesis_and_transfer_are_separate_results(self):
        audio_path = self.temp / "fixture.mp3"
        audio_path.write_bytes(b"fictional-mp3-bytes")
        sink = Mock(return_value=False)
        with (
            patch.object(self.tts, "is_volc_configured", return_value=True),
            patch.object(
                self.tts,
                "_synthesize_volcano_impl",
                return_value=str(audio_path),
            ),
            patch.object(
                self.tts,
                "play_mp3",
                side_effect=AssertionError("must not play on the server"),
            ),
        ):
            result = self.tts.speak_sentence_streaming(
                "fixture",
                {"tts_engine": "volcano_tts", "speaker": "speaker-a"},
                "OWNER__FIGURE",
                audio_sink=sink,
            )

        self.assertTrue(result["synthesized"])
        self.assertFalse(result["transferred"])
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "audio_transfer_failed")
        sink.assert_called_once_with(b"fictional-mp3-bytes")

    def test_preview_uses_requested_candidate_and_returns_audio_bytes(self):
        speaker = self.voice._load_voice_library()[0]["speaker_id"]
        audio_path = self.temp / "candidate.mp3"
        audio_path.write_bytes(b"candidate-audio")
        with self._client() as client:
            _owner, session = self._account(client, "preview")
            provider = Mock(return_value={
                "engine": "fixture_tts",
                "audio_path": str(audio_path),
                "success": True,
                "error": None,
            })
            with patch.object(self.voice, "synthesize_for_delivery", provider):
                response = client.post(
                    "/api/voice/preview",
                    json={"speaker": speaker, "text": "candidate phrase"},
                    headers=self._headers(session),
                )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, b"candidate-audio")
        self.assertEqual(response.headers["x-lingou-voice-speaker"], speaker)
        self.assertEqual(response.headers["x-lingou-audio-engine"], "fixture_tts")
        self.assertEqual(response.headers["x-lingou-audio-source"], "synthesized")
        self.assertEqual(provider.call_args.kwargs["speaker"], speaker)

    def test_preview_without_audio_returns_explicit_failure(self):
        speaker = self.voice._load_voice_library()[0]["speaker_id"]
        with self._client() as client:
            _owner, session = self._account(client, "no-audio")
            with (
                patch.object(
                    self.voice,
                    "synthesize_for_delivery",
                    return_value={
                        "engine": "none",
                        "audio_path": None,
                        "success": False,
                        "error": "no_deliverable_audio",
                    },
                ),
                patch.object(self.voice, "_download_catalog_demo", return_value=None),
            ):
                response = client.post(
                    "/api/voice/preview",
                    json={"speaker": speaker, "text": "no audio"},
                    headers=self._headers(session),
                )

        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "VOICE_AUDIO_UNAVAILABLE",
        )

    def test_voice_save_is_validated_and_round_trips(self):
        speakers = [
            item for item in self.voice._load_voice_library()
            if not item.get("ip_risk", False)
        ]
        first = speakers[0]["speaker_id"]
        second = speakers[1]["speaker_id"]
        with self._client() as client:
            _owner, session = self._account(client, "voice-save")
            figure = self._figure(client, session, first)
            saved = client.post(
                "/api/voice/design",
                json={"figure_id": figure["figure_id"], "speaker": second},
                headers=self._headers(session),
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            reread = client.get(
                f"/api/figures/{figure['figure_id']}",
                headers=self._headers(session),
            )

        self.assertEqual(saved.json()["voice_profile"]["speaker"], second)
        self.assertEqual(reread.json()["voice_profile"]["speaker"], second)

    def test_preview_cannot_read_another_owners_figure_voice(self):
        speaker = self.voice._load_voice_library()[0]["speaker_id"]
        with self._client() as client:
            _owner_a, session_a = self._account(client, "preview-owner-a")
            _owner_b, session_b = self._account(client, "preview-owner-b")
            figure_b = self._figure(client, session_b, speaker)
            provider = Mock(
                side_effect=AssertionError("ownership must fail before synthesis")
            )
            with patch.object(self.voice, "synthesize_for_delivery", provider):
                response = client.post(
                    "/api/voice/preview",
                    json={
                        "figure_id": figure_b["figure_id"],
                        "text": "private voice",
                    },
                    headers=self._headers(session_a),
                )

        self.assertEqual(response.status_code, 404, response.text)
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
