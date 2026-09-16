"""Run explicitly: python -B tests/test_data_ownership.py

Step-03 attack tests. Every resource lives in a temporary data directory and
all account/device identities are fictional. No ASR, LLM, TTS, microphone, or
physical hardware provider is used.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import json
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


class DataOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(
            cls.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="lingou-data-ownership-")
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
            LINGOU_JWT_SECRET="step-03-test-only-jwt-secret-at-least-32-bytes",
            LINGOU_ENABLE_TEST_DEVICE_AUTH="1",
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))
        cls.stack.enter_context(
            patch("dotenv.load_dotenv", side_effect=AssertionError("dotenv must stay disabled"))
        )
        for target in (
            "socket.socket.connect",
            "socket.socket.connect_ex",
            "socket.getaddrinfo",
            "subprocess.Popen",
        ):
            cls.stack.enter_context(
                patch(target, side_effect=AssertionError("external I/O is disabled"))
            )

        from app import main
        from app.api import brain, device_auth, dialogue, hardware, voice
        from app.core import dialogue_engine, offline_brain, tts_adapter
        from data import store

        cls.main = main
        cls.brain = brain
        cls.device_auth = device_auth
        cls.dialogue = dialogue
        cls.dialogue_engine = dialogue_engine
        cls.hardware = hardware
        cls.offline_brain = offline_brain
        cls.store = store
        cls.tts = tts_adapter
        cls.voice = voice

    def setUp(self):
        self.main.auth.USERS_FILE.unlink(missing_ok=True)
        with self.main.auth._ws_ticket_lock:
            self.main.auth._consumed_ws_tickets.clear()
        with self.dialogue_engine._summary_cache_lock:
            self.dialogue_engine._summary_cache.clear()
        self.offline_brain._pool_ready_cache.clear()

    def _client(self):
        from fastapi.testclient import TestClient

        return TestClient(self.main.app)

    @staticmethod
    def _bearer(session: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {session['access_token']}"}

    def _account(self, client, label: str) -> tuple[dict, dict]:
        suffix = uuid.uuid4().hex
        username = f"{label}-{suffix}"
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

    def _base(self, client, session: dict, label: str) -> str:
        base_id = f"BASE-{label}-{uuid.uuid4().hex}"
        response = client.post(
            "/api/bases/test-bases",
            json={"base_id": base_id},
            headers=self._bearer(session),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("device_credential_hash", response.text)
        return base_id

    def _figure(self, client, session: dict, label: str) -> dict:
        response = client.post(
            "/api/figures",
            json={"name": label, "figure_type": "anime"},
            headers=self._bearer(session),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _activate(self, client, session: dict, base_id: str, figure_id: str) -> None:
        response = client.post(
            f"/api/bases/{base_id}/active-figure",
            json={"figure_id": figure_id},
            headers=self._bearer(session),
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_cross_account_figure_base_and_provider_operations_are_denied(self):
        with self._client() as client:
            account_a, session_a = self._account(client, "owner-a")
            account_b, session_b = self._account(client, "owner-b")
            base_a = self._base(client, session_a, "A")
            base_b = self._base(client, session_b, "B")
            figure_a = self._figure(client, session_a, "Figure A")
            figure_b = self._figure(client, session_b, "Figure B")
            self._activate(client, session_a, base_a, figure_a["figure_id"])
            self._activate(client, session_b, base_b, figure_b["figure_id"])

            a_headers = self._bearer(session_a)
            denied = [
                client.get(f"/api/figures/{figure_b['figure_id']}", headers=a_headers),
                client.put(
                    f"/api/figures/{figure_b['figure_id']}",
                    json={"name": "stolen"},
                    headers=a_headers,
                ),
                client.delete(f"/api/figures/{figure_b['figure_id']}", headers=a_headers),
                client.get(f"/api/bases/{base_b}", headers=a_headers),
                client.post(
                    f"/api/bases/{base_a}/active-figure",
                    json={"figure_id": figure_b["figure_id"]},
                    headers=a_headers,
                ),
                client.post(
                    f"/api/bases/{base_b}/active-figure",
                    json={"figure_id": figure_a["figure_id"]},
                    headers=a_headers,
                ),
            ]
            self.assertTrue(all(item.status_code == 404 for item in denied), denied)
            self.assertEqual(len({item.text for item in denied[:3]}), 1)
            self.assertEqual(len({item.text for item in denied[3:]}), 1)

            listed = client.get("/api/bases", headers=a_headers).json()
            self.assertEqual([item["base"]["base_id"] for item in listed], [base_a])
            self.assertEqual(
                client.get(
                    f"/api/figures/{figure_b['figure_id']}",
                    headers=self._bearer(session_b),
                ).json()["name"],
                "Figure B",
            )

            probes = [
                (self.hardware, "generate_touch_response", "/api/hardware/simulate", {"base_id": base_b, "event_type": "light_touch"}),
                (self.dialogue, "process_text_input", "/api/dialogue/text", {"base_id": base_b, "text": "hello"}),
                (self.voice, "synthesize_for_delivery", "/api/voice/generate", {"figure_id": figure_b["figure_id"], "text": "hello"}),
                (self.brain, "set_forced_mode", f"/api/brain/mode?base_id={base_b}", {"mode": "offline"}),
            ]
            for module, name, path, payload in probes:
                provider = Mock(side_effect=AssertionError("provider/state mutation ran before owner check"))
                with self.subTest(path=path), patch.object(module, name, provider):
                    response = client.post(path, json=payload, headers=a_headers)
                    self.assertEqual(response.status_code, 404, response.text)
                    provider.assert_not_called()

            self.assertNotEqual(account_a["user_id"], account_b["user_id"])

    def test_history_and_sync_namespaces_come_only_from_bearer_subject(self):
        with self._client() as client:
            account_a, session_a = self._account(client, "sync-a")
            account_b, session_b = self._account(client, "sync-b")
            figure_a = self._figure(client, session_a, "Sync A")
            figure_b = self._figure(client, session_b, "Sync B")
            now = datetime.now(timezone.utc).isoformat()
            self.store.save_dialogue_log(
                {
                    "dialogue_id": f"dialogue-{uuid.uuid4().hex}",
                    "figure_id": figure_a["figure_id"],
                    "user_input_text": "A-private-history",
                    "reply_text": "A-reply",
                    "created_at": now,
                },
                user_id=account_a["user_id"],
            )
            self.store.save_dialogue_log(
                {
                    "dialogue_id": f"dialogue-{uuid.uuid4().hex}",
                    "figure_id": figure_b["figure_id"],
                    "user_input_text": "B-private-history",
                    "reply_text": "B-reply",
                    "created_at": now,
                },
                user_id=account_b["user_id"],
            )

            a_headers = self._bearer(session_a)
            own_logs = client.get("/api/dialogue/logs", headers=a_headers)
            self.assertEqual(own_logs.status_code, 200, own_logs.text)
            self.assertIn("A-private-history", own_logs.text)
            self.assertNotIn("B-private-history", own_logs.text)
            cross_logs = client.get(
                f"/api/dialogue/logs?figure_id={figure_b['figure_id']}",
                headers=a_headers,
            )
            self.assertEqual(cross_logs.status_code, 404, cross_logs.text)

            injected_top_level = client.post(
                "/api/sync/upload",
                json={"user_id": account_b["user_id"], "figures": []},
                headers=a_headers,
            )
            self.assertEqual(injected_top_level.status_code, 422, injected_top_level.text)
            injected_record = client.post(
                "/api/sync/upload",
                json={
                    "figures": [{
                        "figure_id": figure_a["figure_id"],
                        "owner_user_id": account_b["user_id"],
                    }]
                },
                headers=a_headers,
            )
            self.assertEqual(injected_record.status_code, 422, injected_record.text)
            cross_queue = client.post(
                "/api/sync",
                json={"figure_id": figure_b["figure_id"], "type": "memory", "data": {}},
                headers=a_headers,
            )
            self.assertEqual(cross_queue.status_code, 404, cross_queue.text)

            own_upload = client.post(
                "/api/sync/upload",
                json={
                    "figures": [{
                        "figure_id": figure_a["figure_id"],
                        "name": "cloud-a",
                        "updated_at": now,
                    }]
                },
                headers=a_headers,
            )
            self.assertEqual(own_upload.status_code, 200, own_upload.text)
            a_download = client.post(
                f"/api/sync/download?user_id={account_b['user_id']}",
                headers=a_headers,
            )
            self.assertEqual(a_download.status_code, 200, a_download.text)
            self.assertIn("cloud-a", a_download.text)
            b_download = client.post(
                "/api/sync/download",
                headers=self._bearer(session_b),
            )
            self.assertEqual(b_download.status_code, 200, b_download.text)
            self.assertNotIn("cloud-a", b_download.text)

    def test_development_device_credential_is_scoped_rotatable_and_owner_bound(self):
        with self._client() as client:
            account, session = self._account(client, "device-owner")
            base_id = self._base(client, session, "DEVICE")
            figure = self._figure(client, session, "Device Figure")
            self._activate(client, session, base_id, figure["figure_id"])
            issued = client.post(
                f"/api/bases/{base_id}/test-device-credential",
                headers=self._bearer(session),
            )
            self.assertEqual(issued.status_code, 200, issued.text)
            credential = issued.json()["device_credential"]
            self.assertTrue(credential.startswith(f"{base_id}."))
            self.assertEqual(
                issued.json()["scope"],
                ["events:write", "voice:stream"],
            )
            self.assertNotIn("device_credential_hash", issued.text)

            bearer_rejected = client.post(
                "/api/device/events",
                json={"event_type": "light_touch"},
                headers=self._bearer(session),
            )
            self.assertEqual(bearer_rejected.status_code, 401, bearer_rejected.text)
            self.assertEqual(bearer_rejected.headers.get("www-authenticate"), "Device")
            device_headers = {"Authorization": f"Device {credential}"}
            user_api_rejected = client.get("/api/figures", headers=device_headers)
            self.assertEqual(user_api_rejected.status_code, 401, user_api_rejected.text)
            self.assertEqual(user_api_rejected.headers.get("www-authenticate"), "Bearer")
            self.assertEqual(
                client.post(
                    "/api/device/events",
                    json={"event_type": "light_touch"},
                    headers={"Authorization": f"Device {base_id}.wrong"},
                ).status_code,
                401,
            )

            before = len(self.store.list_events(user_id=account["user_id"]))
            extra_owner_selector = client.post(
                "/api/device/events",
                json={"base_id": base_id, "event_type": "light_touch"},
                headers=device_headers,
            )
            self.assertEqual(extra_owner_selector.status_code, 422, extra_owner_selector.text)
            self.assertEqual(len(self.store.list_events(user_id=account["user_id"])), before)
            accepted = client.post(
                "/api/device/events",
                json={"event_type": "light_touch"},
                headers=device_headers,
            )
            self.assertEqual(accepted.status_code, 200, accepted.text)
            logs = self.store.list_events(user_id=account["user_id"])
            self.assertEqual(len(logs), before + 1)
            self.assertEqual(logs[0]["base_id"], base_id)
            self.assertEqual(logs[0]["owner_user_id"], account["user_id"])

            rotated = client.post(
                f"/api/bases/{base_id}/test-device-credential",
                headers=self._bearer(session),
            ).json()["device_credential"]
            self.assertNotEqual(rotated, credential)
            self.assertEqual(
                client.post(
                    "/api/device/events",
                    json={"event_type": "light_touch"},
                    headers=device_headers,
                ).status_code,
                401,
            )
            with patch.dict(os.environ, {"LINGOU_ENABLE_TEST_DEVICE_AUTH": "0"}):
                disabled = client.post(
                    "/api/device/events",
                    json={"event_type": "light_touch"},
                    headers={"Authorization": f"Device {rotated}"},
                )
                self.assertEqual(disabled.status_code, 401, disabled.text)

    def test_ws_ticket_checks_owner_at_issue_and_consumption_time(self):
        with self._client() as client:
            account_a, session_a = self._account(client, "ws-a")
            account_b, session_b = self._account(client, "ws-b")
            base_a = self._base(client, session_a, "WSA")
            base_b = self._base(client, session_b, "WSB")
            cross = client.post(
                "/api/auth/ws-ticket",
                json={"base_id": base_b},
                headers=self._bearer(session_a),
            )
            self.assertEqual(cross.status_code, 404, cross.text)
            issued = client.post(
                "/api/auth/ws-ticket",
                json={"base_id": base_a},
                headers=self._bearer(session_a),
            )
            self.assertEqual(issued.status_code, 200, issued.text)
            user, code = self.main.auth.consume_ws_ticket(issued.json()["ticket"], base_a)
            self.assertEqual((user["user_id"], code), (account_a["user_id"], 0))

            second = self.main.auth._create_ws_ticket(account_a["user_id"], base_a)
            path = self.store.BASES_DIR / f"{base_a}.json"
            changed = self.store.get_base_for_owner(base_a, account_a["user_id"])
            changed["owner_user_id"] = account_b["user_id"]
            changed["bound_user_id"] = account_b["user_id"]
            self.store._write_json(path, changed)
            self.assertEqual(self.main.auth.consume_ws_ticket(second, base_a), (None, 4403))
            changed["owner_user_id"] = account_a["user_id"]
            changed["bound_user_id"] = account_a["user_id"]
            self.store._write_json(path, changed)
            user, code = self.main.auth.consume_ws_ticket(second, base_a)
            self.assertEqual((user["user_id"], code), (account_a["user_id"], 0))

    def test_legacy_claim_routes_are_absent_and_owner_selectors_are_rejected(self):
        with self._client() as client:
            account, session = self._account(client, "contract")
            headers = self._bearer(session)
            base_id = self._base(client, session, "CONTRACT")
            schema_paths = set(client.get("/openapi.json").json()["paths"])

            self.assertNotIn("/api/sync/migrate", schema_paths)
            self.assertNotIn("/api/bases/{base_id}/bind", schema_paths)
            self.assertIn("/api/bases/pair", schema_paths)
            self.assertEqual(
                client.post(
                    "/api/auth/ws-ticket",
                    json={
                        "base_id": base_id,
                        "owner_user_id": account["user_id"],
                    },
                    headers=headers,
                ).status_code,
                422,
            )
            with patch.dict(os.environ, {"LINGOU_ENABLE_TEST_DEVICE_AUTH": "0"}):
                disabled = client.post(
                    "/api/bases/test-bases",
                    json={"base_id": f"DISABLED-{uuid.uuid4().hex}"},
                    headers=headers,
                )
            self.assertEqual(disabled.status_code, 404, disabled.text)

    def test_legacy_data_paths_cache_and_playback_are_isolated(self):
        with self._client() as client:
            account_a, session_a = self._account(client, "legacy-a")
            account_b, _session_b = self._account(client, "legacy-b")
            legacy_id = f"legacy-{uuid.uuid4().hex}"
            legacy_path = self.store.FIGURES_DIR / f"{legacy_id}.json"
            legacy_path.write_text(
                json.dumps({"figure_id": legacy_id, "name": "must-not-be-claimed"}),
                encoding="utf-8",
            )
            headers = self._bearer(session_a)
            self.assertEqual(
                client.get(f"/api/figures/{legacy_id}", headers=headers).status_code,
                404,
            )
            self.assertEqual(
                client.delete(f"/api/figures/{legacy_id}", headers=headers).status_code,
                404,
            )
            self.assertTrue(legacy_path.exists())

            namespaced_alias_id = f"alias-{uuid.uuid4().hex}"
            namespaced_alias = (
                self.store.USER_DATA_DIR
                / account_a["user_id"]
                / "figures"
                / f"{namespaced_alias_id}.json"
            )
            namespaced_alias.parent.mkdir(parents=True, exist_ok=True)
            namespaced_alias.write_text(
                json.dumps(
                    {
                        "figure_id": namespaced_alias_id,
                        "owner_id": account_a["user_id"],
                    }
                ),
                encoding="utf-8",
            )
            self.assertIsNone(
                self.store.get_figure(
                    namespaced_alias_id,
                    user_id=account_a["user_id"],
                )
            )
            mismatched_id = f"mismatch-{uuid.uuid4().hex}"
            mismatched_path = (
                self.store.USER_DATA_DIR
                / account_a["user_id"]
                / "figures"
                / f"{mismatched_id}.json"
            )
            mismatched_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "owner_user_id": account_a["user_id"],
                        "figure_id": "different-id",
                    }
                ),
                encoding="utf-8",
            )
            self.assertIsNone(
                self.store.get_figure(mismatched_id, user_id=account_a["user_id"])
            )

            same_id = f"same-{uuid.uuid4().hex}"
            saved_a = self.store.save_figure(
                same_id,
                {"figure_id": same_id, "name": "A"},
                user_id=account_a["user_id"],
            )
            saved_b = self.store.save_figure(
                same_id,
                {"figure_id": same_id, "name": "B"},
                user_id=account_b["user_id"],
            )
            self.assertEqual(saved_a["name"], "A")
            self.assertEqual(saved_b["name"], "B")
            key_a = self.store.figure_storage_key(account_a["user_id"], same_id)
            key_b = self.store.figure_storage_key(account_b["user_id"], same_id)
            self.assertNotEqual(key_a, key_b)
            self.dialogue_engine._update_summary_cache(account_a["user_id"], same_id, "A-summary", 1)
            self.dialogue_engine._update_summary_cache(account_b["user_id"], same_id, "B-summary", 1)
            self.assertEqual(
                self.dialogue_engine._get_cached_summary(account_a["user_id"], same_id)[0],
                "A-summary",
            )
            self.assertEqual(
                self.dialogue_engine._get_cached_summary(account_b["user_id"], same_id)[0],
                "B-summary",
            )
            with patch(
                "app.core.tts_adapter.is_voice_pool_ready",
                side_effect=lambda key: key == key_a,
            ) as pool_ready:
                self.assertTrue(self.offline_brain._pool_is_ready_cached(key_a))
                self.assertFalse(self.offline_brain._pool_is_ready_cached(key_b))
                self.assertEqual(
                    {call.args[0] for call in pool_ready.call_args_list},
                    {key_a, key_b},
                )

            unknown_dir = self.store.USER_DATA_DIR / "read-only-user"
            self.assertIsNone(self.store.get_figure("safe-id", user_id="read-only-user"))
            self.assertFalse(unknown_dir.exists(), "a read must not create an owner directory")
            for invalid in ("../escape", "/absolute", "contains.dot", "x" * 129):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    self.store.get_figure(invalid, user_id=account_a["user_id"])

            self.tts._clear_queued_scope(None)
            self.tts._playback_queue.put(("a.mp3", key_a))
            self.tts._playback_queue.put(("b.mp3", key_b))
            self.assertTrue(self.tts.stop_playback(key_a))
            remaining = self.tts._playback_queue.get_nowait()
            self.tts._playback_queue.task_done()
            self.assertEqual(remaining, ("b.mp3", key_b))

    def test_atomic_owner_log_append_does_not_drop_concurrent_records(self):
        owner = f"owner-{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()

        def append(index: int) -> None:
            self.store.save_event(
                {
                    "event_id": f"event-{index}-{uuid.uuid4().hex}",
                    "event_type": "test",
                    "triggered_at": now,
                },
                user_id=owner,
            )

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(append, range(40)))
        events = self.store.list_events(user_id=owner, limit=100)
        self.assertEqual(len(events), 40)
        self.assertEqual(len({event["event_id"] for event in events}), 40)

    def test_clone_start_rejects_foreign_missing_and_symlinked_references(self):
        with self._client() as client:
            owner, session = self._account(client, "clone-a")
            other, _ = self._account(client, "clone-b")
            figure = self._figure(client, session, "Clone A")
            figure_id = figure["figure_id"]
            headers = self._bearer(session)
            own = self.store.save_voice_upload(
                figure_id, "own.wav", b"own audio", user_id=owner["user_id"]
            )
            foreign = self.store.save_voice_upload(
                figure_id, "foreign.wav", b"foreign audio", user_id=other["user_id"]
            )
            sibling = self.store.save_voice_upload(
                "OTHER-FIGURE", "other.wav", b"other figure", user_id=owner["user_id"]
            )
            linked = own.parent / "linked.wav"
            linked.symlink_to(foreign)
            with patch.dict(os.environ, {"LINGOU_ENABLE_DEV_TOOLS": "1"}):
                for reference in (foreign, sibling, linked, own.parent / "missing.wav"):
                    with self.subTest(reference=reference.name):
                        updated = client.put(
                            f"/api/figures/{figure_id}",
                            json={"voice_profile": {
                                "recording_url": str(reference),
                                "consent": {"agreed": True},
                            }},
                            headers=headers,
                        )
                        self.assertEqual(updated.status_code, 200, updated.text)
                        response = client.post(
                            "/api/voice/clone/start",
                            json={"figure_id": figure_id},
                            headers=headers,
                        )
                        self.assertEqual(response.status_code, 404, response.text)
                        saved = self.store.get_figure(figure_id, user_id=owner["user_id"])
                        self.assertNotEqual(saved["voice_profile"]["clone_status"], "ready")

    def test_forged_ready_clone_cannot_send_another_owners_audio_to_provider(self):
        from app.core import voxcpm_adapter

        with self._client() as client:
            owner, session = self._account(client, "ready-a")
            other, _ = self._account(client, "ready-b")
            figure = self._figure(client, session, "Ready A")
            foreign = self.store.save_voice_upload(
                figure["figure_id"], "secret.wav", b"foreign private audio",
                user_id=other["user_id"],
            )
            headers = self._bearer(session)
            client.put(
                f"/api/figures/{figure['figure_id']}",
                json={"voice_profile": {
                    "voice_mode": "voice_clone",
                    "clone_engine": "voxcpm",
                    "clone_status": "ready",
                    "clone_ref_path": str(foreign),
                }},
                headers=headers,
            )
            with (
                patch.object(voxcpm_adapter, "is_configured", return_value=True),
                patch.object(
                    voxcpm_adapter.urllib.request, "urlopen", autospec=True
                ) as provider,
                patch.object(self.tts, "synthesize_system_say", return_value=False),
            ):
                response = client.post(
                    "/api/voice/generate",
                    json={"figure_id": figure["figure_id"], "text": "hello"},
                    headers=headers,
                )
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(
                    response.json()["detail"]["code"],
                    "VOICE_AUDIO_UNAVAILABLE",
                )
                provider.assert_not_called()

    def test_own_uploaded_reference_can_be_cloned_with_owner_scoped_output(self):
        import base64
        import io
        from app.core import voxcpm_adapter

        with self._client() as client:
            owner, session = self._account(client, "own-clone")
            figure = self._figure(client, session, "Own Clone")
            headers = self._bearer(session)
            with patch.dict(os.environ, {"LINGOU_ENABLE_DEV_TOOLS": "1"}):
                uploaded = client.post(
                    "/api/voice/upload",
                    data={"figure_id": figure["figure_id"], "consent_agreed": "true"},
                    files={"audio": ("sample.wav", b"fictional reference", "audio/wav")},
                    headers=headers,
                )
                self.assertEqual(uploaded.status_code, 200, uploaded.text)
                started = client.post(
                    "/api/voice/clone/start",
                    json={"figure_id": figure["figure_id"]},
                    headers=headers,
                )
                self.assertEqual(started.status_code, 200, started.text)
            fake_reply = io.BytesIO(json.dumps({
                "ok": True,
                "audio_b64": base64.b64encode(b"fictional output").decode(),
            }).encode())
            with (
                patch.object(voxcpm_adapter, "is_configured", return_value=True),
                patch.object(
                    voxcpm_adapter.urllib.request, "urlopen", return_value=fake_reply
                ) as provider,
                patch.object(self.tts, "play_mp3", return_value=True),
            ):
                generated = client.post(
                    "/api/voice/generate",
                    json={"figure_id": figure["figure_id"], "text": "hello"},
                    headers=headers,
                )
            self.assertEqual(generated.status_code, 200, generated.text)
            self.assertEqual(generated.json()["engine"], "voxcpm_clone")
            provider.assert_called_once()
            request = provider.call_args.args[0]
            self.assertEqual(
                base64.b64decode(json.loads(request.data)["prompt_audio_b64"]),
                b"fictional reference",
            )
            output = Path(generated.json()["audio_path"])
            expected_key = self.store.figure_storage_key(owner["user_id"], figure["figure_id"])
            self.assertEqual(output.parent, self.tts.AUDIO_CACHE_DIR / expected_key)
            self.assertEqual(output.read_bytes(), b"fictional output")


if __name__ == "__main__":
    unittest.main(verbosity=2)
