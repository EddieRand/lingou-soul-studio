"""Run explicitly: python -B tests/test_pairing_activation.py.

Step-04 pairing, idempotent creation and activation tests. All data and device
secrets are fictional and live under one temporary runtime directory.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True


class PairingActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(
            cls.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="lingou-pairing-activation-")
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
            LINGOU_JWT_SECRET="step-04-test-only-jwt-secret-at-least-32-bytes",
            LINGOU_ENABLE_TEST_DEVICE_AUTH="1",
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))
        cls.stack.enter_context(
            patch(
                "dotenv.load_dotenv",
                side_effect=AssertionError("dotenv must stay disabled"),
            )
        )

        from app import main
        from app.api import device_auth
        from data import store

        cls.main = main
        cls.device_auth = device_auth
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

    @staticmethod
    def _bearer(session: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {session['access_token']}"}

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

    def _provision(self, label: str) -> tuple[str, str, str]:
        base_id = f"BASE-{label}-{uuid.uuid4().hex}"
        pairing_token = f"{base_id}.{'p' * 43}"
        device_credential = f"{base_id}.{'d' * 43}"
        self.store.provision_base(
            base_id,
            pairing_token=pairing_token,
            device_credential=device_credential,
        )
        return base_id, pairing_token, device_credential

    def _pair(self, client, session: dict, token: str):
        return client.post(
            "/api/bases/pair",
            json={"qr_token": f"lingou://pair?token={token}"},
            headers=self._bearer(session),
        )

    @staticmethod
    def _figure_payload(
        request_id: str,
        base_id: str,
        name: str = "Fixture Soul",
    ) -> dict:
        return {
            "creation_request_id": request_id,
            "activate_base_id": base_id,
            "name": name,
            "figure_type": "soul",
            "wake_names": ["Fixture"],
            "soul_profile": {
                "archetype": "软萌治愈型",
                "character_profile": {"name": name, "background": "fixture"},
            },
            "voice_profile": {"speaker": "fixture-speaker"},
        }

    def test_pairing_is_real_idempotent_and_conflict_safe(self):
        base_id, token, _ = self._provision("PAIR")
        second_id, second_token, _ = self._provision("SECOND")
        with self._client() as client:
            _account_a, session_a = self._account(client, "pair-a")
            _account_b, session_b = self._account(client, "pair-b")
            headers_a = self._bearer(session_a)

            invalid = client.post(
                "/api/bases/pair",
                json={"qr_token": f"{base_id}.{'x' * 43}"},
                headers=headers_a,
            )
            self.assertEqual(invalid.status_code, 400, invalid.text)
            self.assertEqual(invalid.json()["error_code"], "INVALID_QR_CODE")

            first = self._pair(client, session_a, token)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertTrue(first.json()["newly_bound"])
            self.assertEqual(first.json()["base_id"], base_id)
            for secret_field in (
                "pairing_token_hash",
                "device_credential_hash",
                "device_credential_scope",
            ):
                self.assertNotIn(secret_field, first.text)

            replay = self._pair(client, session_a, token)
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertFalse(replay.json()["newly_bound"])

            occupied = self._pair(client, session_b, token)
            self.assertEqual(occupied.status_code, 409, occupied.text)
            self.assertEqual(occupied.json()["error_code"], "BASE_ALREADY_BOUND")

            extra = self._pair(client, session_a, second_token)
            self.assertEqual(extra.status_code, 409, extra.text)
            self.assertEqual(
                extra.json()["error_code"],
                "ACCOUNT_ALREADY_HAS_BASE",
            )
            self.assertIsNotNone(self.store.get_base(second_id))

    def test_create_retry_is_idempotent_and_activates_in_one_request(self):
        base_id, token, _ = self._provision("CREATE")
        with self._client() as client:
            account, session = self._account(client, "creator")
            self.assertEqual(self._pair(client, session, token).status_code, 200)
            headers = self._bearer(session)
            request_id = f"create-{uuid.uuid4().hex}"
            payload = self._figure_payload(request_id, base_id)

            first = client.post("/api/figures", json=payload, headers=headers)
            self.assertEqual(first.status_code, 200, first.text)
            figure_id = first.json()["figure_id"]
            self.assertEqual(first.json()["base_id"], base_id)

            retry_payload = dict(payload, name="must-not-create-a-second-record")
            retry = client.post("/api/figures", json=retry_payload, headers=headers)
            self.assertEqual(retry.status_code, 200, retry.text)
            self.assertEqual(retry.json()["figure_id"], figure_id)
            self.assertEqual(retry.json()["name"], "Fixture Soul")

            figures = client.get("/api/figures", headers=headers).json()
            self.assertEqual([item["figure_id"] for item in figures], [figure_id])
            detail = client.get(f"/api/bases/{base_id}", headers=headers).json()
            self.assertEqual(detail["base"]["active_figure_id"], figure_id)
            self.assertEqual(detail["figure"]["base_id"], base_id)

            child_env = os.environ.copy()
            child_env.update(
                LINGOU_DATA_DIR=str(self.runtime),
                LINGOU_LOAD_DOTENV="0",
                LINGOU_JWT_SECRET="step-04-test-only-jwt-secret-at-least-32-bytes",
            )
            code = (
                "import json,sys;"
                f"sys.path.insert(0,{str(SERVER_ROOT)!r});"
                "from data.store import get_base_for_owner,get_figure;"
                f"print(json.dumps({{'base':get_base_for_owner({base_id!r},{account['user_id']!r}),"
                f"'figure':get_figure({figure_id!r},user_id={account['user_id']!r})}}))"
            )
            restarted = subprocess.run(
                [sys.executable, "-B", "-c", code],
                env=child_env,
                capture_output=True,
                text=True,
                check=True,
            )
            snapshot = json.loads(restarted.stdout)
            self.assertEqual(snapshot["base"]["active_figure_id"], figure_id)
            self.assertEqual(snapshot["figure"]["base_id"], base_id)

    def test_invalid_activation_does_not_create_an_orphan(self):
        base_id, token, _ = self._provision("VALID")
        foreign_id, foreign_token, _ = self._provision("FOREIGN")
        with self._client() as client:
            _account_a, session_a = self._account(client, "invalid-a")
            _account_b, session_b = self._account(client, "invalid-b")
            self.assertEqual(self._pair(client, session_a, token).status_code, 200)
            self.assertEqual(
                self._pair(client, session_b, foreign_token).status_code,
                200,
            )
            payload = self._figure_payload(
                f"invalid-{uuid.uuid4().hex}",
                foreign_id,
            )
            failed = client.post(
                "/api/figures",
                json=payload,
                headers=self._bearer(session_a),
            )
            self.assertEqual(failed.status_code, 409, failed.text)
            self.assertEqual(
                client.get(
                    "/api/figures",
                    headers=self._bearer(session_a),
                ).json(),
                [],
            )
            self.assertIsNotNone(self.store.get_base(base_id))

    def test_switching_active_figure_detaches_the_previous_figure(self):
        base_id, token, _ = self._provision("SWITCH")
        with self._client() as client:
            account, session = self._account(client, "switch")
            self.assertEqual(self._pair(client, session, token).status_code, 200)
            headers = self._bearer(session)
            first = client.post(
                "/api/figures",
                json=self._figure_payload(f"first-{uuid.uuid4().hex}", base_id, "First"),
                headers=headers,
            ).json()
            second = client.post(
                "/api/figures",
                json=self._figure_payload(f"second-{uuid.uuid4().hex}", base_id, "Second"),
                headers=headers,
            ).json()

            saved_base = self.store.get_base_for_owner(base_id, account["user_id"])
            saved_first = self.store.get_figure(
                first["figure_id"],
                user_id=account["user_id"],
            )
            saved_second = self.store.get_figure(
                second["figure_id"],
                user_id=account["user_id"],
            )
            self.assertEqual(saved_base["active_figure_id"], second["figure_id"])
            self.assertIsNone(saved_first["base_id"])
            self.assertEqual(saved_second["base_id"], base_id)

    def test_interrupted_creation_recovers_before_idempotent_retry(self):
        base_id, token, _ = self._provision("RECOVER")
        with self._client() as client:
            account, session = self._account(client, "recover")
            self.assertEqual(self._pair(client, session, token).status_code, 200)
            headers = self._bearer(session)
            request_id = f"recover-{uuid.uuid4().hex}"
            payload = self._figure_payload(request_id, base_id)
            original_write = self.store._write_json
            calls = 0

            def fail_after_first_target(path, data):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("fictional interrupted write")
                return original_write(path, data)

            with patch.object(self.store, "_write_json", side_effect=fail_after_first_target):
                failed = client.post("/api/figures", json=payload, headers=headers)
            self.assertEqual(failed.status_code, 409, failed.text)
            self.assertEqual(len(list(self.store.TRANSACTIONS_DIR.glob("*.json"))), 1)

            retry = client.post("/api/figures", json=payload, headers=headers)
            self.assertEqual(retry.status_code, 200, retry.text)
            figures = self.store.list_figures(user_id=account["user_id"])
            self.assertEqual(len(figures), 1)
            self.assertEqual(figures[0]["figure_id"], retry.json()["figure_id"])
            self.assertEqual(figures[0]["base_id"], base_id)
            self.assertEqual(
                self.store.get_base_for_owner(base_id, account["user_id"])[
                    "active_figure_id"
                ],
                figures[0]["figure_id"],
            )
            self.assertEqual(list(self.store.TRANSACTIONS_DIR.glob("*.json")), [])

    def test_unbind_persists_and_device_events_require_fresh_identity(self):
        base_id, token, device_credential = self._provision("DEVICE")
        with self._client() as client:
            account_a, session_a = self._account(client, "device-a")
            account_b, session_b = self._account(client, "device-b")
            self.assertEqual(self._pair(client, session_a, token).status_code, 200)
            headers_a = self._bearer(session_a)
            created = client.post(
                "/api/figures",
                json=self._figure_payload(f"device-{uuid.uuid4().hex}", base_id),
                headers=headers_a,
            )
            self.assertEqual(created.status_code, 200, created.text)
            device_headers = {"Authorization": f"Device {device_credential}"}

            missing_identity = client.post(
                "/api/device/events",
                json={"event_type": "light_touch"},
                headers=device_headers,
            )
            self.assertEqual(missing_identity.status_code, 422, missing_identity.text)
            invalid_identity = client.post(
                "/api/device/events",
                json={
                    "event_type": "light_touch",
                    "event_id": "../invalid",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                },
                headers=device_headers,
            )
            self.assertEqual(invalid_identity.status_code, 422, invalid_identity.text)
            event_id = f"event-{uuid.uuid4().hex}"
            payload = {
                "event_type": "light_touch",
                "event_id": event_id,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            accepted = client.post(
                "/api/device/events",
                json=payload,
                headers=device_headers,
            )
            self.assertEqual(accepted.status_code, 200, accepted.text)
            replay = client.post(
                "/api/device/events",
                json=payload,
                headers=device_headers,
            )
            self.assertEqual(replay.status_code, 409, replay.text)
            stale = client.post(
                "/api/device/events",
                json={
                    "event_type": "light_touch",
                    "event_id": f"event-{uuid.uuid4().hex}",
                    "occurred_at": (
                        datetime.now(timezone.utc) - timedelta(minutes=10)
                    ).isoformat(),
                },
                headers=device_headers,
            )
            self.assertEqual(stale.status_code, 409, stale.text)

            unbound = client.post(
                f"/api/bases/{base_id}/unbind",
                headers=headers_a,
            )
            self.assertEqual(unbound.status_code, 200, unbound.text)
            self.assertEqual(client.get("/api/bases", headers=headers_a).json(), [])
            self.assertIsNone(
                self.store.get_figure(
                    created.json()["figure_id"],
                    user_id=account_a["user_id"],
                )["base_id"]
            )
            raw = self.store.get_base(base_id)
            self.assertEqual(raw["status"], "unbound")
            self.assertNotIn("owner_user_id", raw)
            self.assertIsNone(
                self.device_auth.authenticate_device_credential(device_credential)
            )

            transferred = self._pair(client, session_b, token)
            self.assertEqual(transferred.status_code, 200, transferred.text)
            self.assertEqual(
                self.device_auth.authenticate_device_credential(
                    device_credential
                )["owner_user_id"],
                account_b["user_id"],
            )
            revoked = client.post(
                f"/api/bases/{base_id}/device-credential/revoke",
                headers=self._bearer(session_b),
            )
            self.assertEqual(revoked.status_code, 200, revoked.text)
            self.assertIsNone(
                self.device_auth.authenticate_device_credential(device_credential)
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
