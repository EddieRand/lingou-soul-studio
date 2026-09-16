"""Run explicitly: python -B tests/test_auth_security.py

Step-02 authentication security tests. The suite imports the real ASGI app with
isolated runtime data, blocks external network access, and never calls an ASR,
LLM, or TTS provider.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True

TEST_JWT_SECRET = "step-02-test-only-jwt-secret-at-least-32-bytes"
RETIRED_AUTH_PATHS = {
    "/api/auth/users",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/send-code",
    "/api/auth/login-code",
    "/api/auth/wechat-login",
    "/api/auth/apple-login",
}
PUBLIC_API_PATHS = {"/api/auth/register", "/api/auth/login"}


class AuthenticationSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(
            cls.stack.enter_context(tempfile.TemporaryDirectory(prefix="lingou-auth-security-"))
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
            LINGOU_JWT_SECRET=TEST_JWT_SECRET,
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))

        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_getaddrinfo = socket.getaddrinfo

        def is_loopback(address):
            return isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}

        def guarded_connect(sock, address):
            if not is_loopback(address):
                raise AssertionError("External network access is disabled in auth security tests")
            return original_connect(sock, address)

        def guarded_connect_ex(sock, address):
            if not is_loopback(address):
                raise AssertionError("External network access is disabled in auth security tests")
            return original_connect_ex(sock, address)

        def guarded_getaddrinfo(host, *args, **kwargs):
            if host not in {"127.0.0.1", "::1"}:
                raise AssertionError("External DNS resolution is disabled in auth security tests")
            return original_getaddrinfo(host, *args, **kwargs)

        cls.stack.enter_context(patch("socket.socket.connect", guarded_connect))
        cls.stack.enter_context(patch("socket.socket.connect_ex", guarded_connect_ex))
        cls.stack.enter_context(patch("socket.getaddrinfo", guarded_getaddrinfo))
        cls.dotenv = cls.stack.enter_context(
            patch("dotenv.load_dotenv", side_effect=AssertionError("A real .env must not be loaded"))
        )

        from app import main
        from app.api import asr, auth, character, device_auth, dialogue, hardware, voice
        from data import store

        cls.main = main
        cls.asr = asr
        cls.auth = auth
        cls.character = character
        cls.device_auth = device_auth
        cls.dialogue = dialogue
        cls.hardware = hardware
        cls.store = store
        cls.voice = voice

    def setUp(self):
        self.auth.USERS_FILE.unlink(missing_ok=True)
        for path in self.store.BASES_DIR.glob("*.json"):
            path.unlink()
        with self.auth._ws_ticket_lock:
            self.auth._consumed_ws_tickets.clear()

    def _client(self):
        from fastapi.testclient import TestClient

        return TestClient(self.main.app)

    def _register_and_login(self, *, username: str | None = None, password: str = "fixture-password"):
        username = username or f"fixture-{uuid.uuid4().hex}"
        email = f"{username}@example.com"
        with self._client() as client:
            registered = client.post(
                "/api/auth/register",
                json={"username": username, "email": email, "password": password},
            )
            self.assertEqual(registered.status_code, 200, registered.text)
            logged_in = client.post(
                "/api/auth/login",
                data={"username": username, "password": password},
            )
            self.assertEqual(logged_in.status_code, 200, logged_in.text)
        return registered.json(), logged_in.json()

    @staticmethod
    def _dependency_calls(dependant):
        for child in dependant.dependencies:
            yield child.call
            yield from AuthenticationSecurityTests._dependency_calls(child)

    def _http_api_routes(self):
        """Yield effective API routes across eager and deferred FastAPI routers."""
        from fastapi.routing import APIRoute

        for route in self.main.app.routes:
            if isinstance(route, APIRoute):
                if route.path.startswith("/api/"):
                    yield route
                continue

            # FastAPI 0.128+ keeps include_router calls deferred. Its effective
            # contexts contain the final prefixed path and merged dependencies.
            contexts = getattr(route, "effective_route_contexts", None)
            if contexts is None:
                continue
            for context in contexts():
                if context.dependant is not None and context.path.startswith("/api/"):
                    yield context

    @staticmethod
    def _concrete_path(path: str) -> str:
        return re.sub(r"\{[^{}]+\}", "fixture-id", path)

    def _signed_token(
        self,
        *,
        subject: str,
        token_type: str = "access",
        issued_at: datetime | None = None,
        expires_at: datetime | None = None,
        secret: str = TEST_JWT_SECRET,
        **claims,
    ) -> str:
        import jwt

        now = datetime.now(timezone.utc)
        payload = {
            "sub": subject,
            "typ": token_type,
            "jti": str(uuid.uuid4()),
            "iat": issued_at or now,
            "exp": expires_at or now + timedelta(minutes=5),
            **claims,
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    @staticmethod
    def _bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _create_owned_base(self, owner_user_id: str, base_id: str) -> None:
        self.store.save_base(
            base_id,
            {
                "base_id": base_id,
                "active_figure_id": None,
                "status": "bound",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            owner_user_id=owner_user_id,
        )

    def _assert_ws_rejected(self, client, url: str, *, subprotocols, code: int):
        from starlette.websockets import WebSocketDisconnect

        with client.websocket_connect(url, subprotocols=subprotocols) as websocket:
            with self.assertRaises(WebSocketDisconnect) as raised:
                websocket.receive_text()
        self.assertEqual(raised.exception.code, code)

    @contextmanager
    def _uvicorn_server(self):
        """Serve the real ASGI app so WebSocket handshake behavior is genuine."""
        import uvicorn

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                self.main.app,
                log_level="critical",
                lifespan="off",
            )
        )
        thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [listener]},
            name="lingou-auth-test-uvicorn",
            daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            server.should_exit = True
            thread.join(timeout=2)
            listener.close()
            self.fail("Uvicorn test server did not start")
        try:
            yield port
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()
            self.assertFalse(thread.is_alive(), "Uvicorn test server did not stop")

    def test_only_register_and_login_are_public_api_routes(self):
        api_routes = list(self._http_api_routes())
        self.assertTrue(api_routes)
        self.assertTrue(PUBLIC_API_PATHS.issubset({route.path for route in api_routes}))

        for route in api_routes:
            dependency_calls = set(self._dependency_calls(route.dependant))
            if route.path in PUBLIC_API_PATHS:
                self.assertNotIn(
                    self.auth.require_current_user,
                    dependency_calls,
                    f"public endpoint unexpectedly requires a token: {route.path}",
                )
            elif route.path == "/api/device/events":
                self.assertIn(
                    self.device_auth.require_current_device,
                    dependency_calls,
                    "device endpoint lacks the device auth dependency",
                )
                self.assertNotIn(self.auth.require_current_user, dependency_calls)
            else:
                self.assertIn(
                    self.auth.require_current_user,
                    dependency_calls,
                    f"private endpoint lacks the shared auth dependency: {route.path}",
                )

    def test_http_auth_boundary_rejects_before_reading_private_request_body(self):
        async def unreachable_app(scope, receive, send):
            raise AssertionError("private route ran without authentication")

        middleware = self.main.ApiAuthenticationBoundaryMiddleware(unreachable_app)
        for root_path, path in (
            ("", "/api/voice/upload"),
            ("/lingou", "/lingou/api/voice/upload"),
        ):
            with self.subTest(root_path=root_path):
                received = False
                sent = []

                async def forbidden_receive():
                    nonlocal received
                    received = True
                    raise AssertionError("anonymous request body was read before authentication")

                async def capture_send(message):
                    sent.append(message)

                scope = {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "root_path": root_path,
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": b"",
                    "headers": [(b"content-type", b"multipart/form-data; boundary=fixture")],
                    "client": ("127.0.0.1", 12345),
                    "server": ("127.0.0.1", 8000),
                }
                asyncio.run(middleware(scope, forbidden_receive, capture_send))
                self.assertFalse(received)
                self.assertEqual(sent[0]["type"], "http.response.start")
                self.assertEqual(sent[0]["status"], 401)

        with self._client() as client:
            malformed = client.post(
                "/api/brain/mode",
                content=b"{not-json",
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(malformed.status_code, 401, malformed.text)
        self.assertEqual(malformed.headers.get("www-authenticate"), "Bearer")

        from fastapi.testclient import TestClient

        with TestClient(
            self.main.app,
            base_url="http://testserver/lingou/",
            root_path="/lingou",
        ) as rooted_client:
            rooted = rooted_client.post(
                "/api/brain/mode",
                content=b"{not-json",
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(rooted.status_code, 401, rooted.text)
        self.assertEqual(rooted.headers.get("www-authenticate"), "Bearer")

    def test_cors_preflight_is_limited_to_configured_development_origins(self):
        headers = {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        }
        with self._client() as client:
            allowed = client.options("/api/figures", headers=headers)
            denied = client.options(
                "/api/figures",
                headers={**headers, "Origin": "https://untrusted.example"},
            )
            anonymous = client.get(
                "/api/figures",
                headers={"Origin": "http://localhost:3000"},
            )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://localhost:3000")
        self.assertNotIn("access-control-allow-origin", denied.headers)
        self.assertEqual(anonymous.status_code, 401, anonymous.text)
        self.assertEqual(
            anonymous.headers.get("access-control-allow-origin"),
            "http://localhost:3000",
        )

    def test_every_private_http_operation_rejects_anonymous_requests_before_provider_work(self):
        asr_probe = Mock(side_effect=AssertionError("ASR provider check ran before authentication"))
        brain_probe = Mock(side_effect=AssertionError("LLM provider ran before authentication"))
        character_probe = Mock(side_effect=AssertionError("Character provider ran before authentication"))
        dialogue_probe = Mock(side_effect=AssertionError("Dialogue engine ran before authentication"))
        touch_probe = Mock(side_effect=AssertionError("Touch engine ran before authentication"))
        hardware_speech_probe = Mock(side_effect=AssertionError("Hardware speech ran before authentication"))
        voice_probe = Mock(side_effect=AssertionError("Voice provider ran before authentication"))
        failures = []
        before = {
            path.relative_to(self.runtime): path.read_bytes()
            for path in self.runtime.rglob("*")
            if path.is_file()
        }

        with (
            patch.object(self.asr, "is_asr_available", asr_probe),
            patch.object(self.main.online_brain, "_call_doubao", brain_probe),
            patch.object(self.character, "_call_doubao_json", character_probe),
            patch.object(self.dialogue, "process_text_input", dialogue_probe),
            patch.object(self.hardware, "generate_touch_response", touch_probe),
            patch.object(self.hardware, "speak", hardware_speech_probe),
            patch.object(self.voice, "synthesize_for_delivery", voice_probe),
        ):
            with self._client() as client:
                for route in self._http_api_routes():
                    if route.path in PUBLIC_API_PATHS:
                        continue
                    path = self._concrete_path(route.path)
                    for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                        response = client.request(method, path, content=b"")
                        if response.status_code != 401:
                            failures.append(f"{method} {route.path}: {response.status_code} {response.text[:120]}")

        self.assertEqual(failures, [], "\n".join(failures))
        asr_probe.assert_not_called()
        brain_probe.assert_not_called()
        character_probe.assert_not_called()
        dialogue_probe.assert_not_called()
        touch_probe.assert_not_called()
        hardware_speech_probe.assert_not_called()
        voice_probe.assert_not_called()
        after = {
            path.relative_to(self.runtime): path.read_bytes()
            for path in self.runtime.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

    def test_registration_login_and_verify_survive_client_restart(self):
        username = "persistent-user"
        email = "persistent-user@example.com"
        password = "fixture-password"
        with self._client() as first_client:
            registered = first_client.post(
                "/api/auth/register",
                json={"username": username, "email": email, "password": password},
            )
            self.assertEqual(registered.status_code, 200, registered.text)
            logged_in = first_client.post(
                "/api/auth/login",
                data={"username": email.upper(), "password": password},
            )
            self.assertEqual(logged_in.status_code, 200, logged_in.text)
            token = logged_in.json()["access_token"]

        self.assertTrue(self.auth.USERS_FILE.is_relative_to(self.runtime))
        self.assertTrue(self.auth.USERS_FILE.is_file())

        with self._client() as restarted_client:
            verified = restarted_client.get("/api/auth/verify", headers=self._bearer(token))
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertEqual(verified.json()["user_id"], registered.json()["user_id"])
        self.assertEqual(verified.json()["username"], username)

    def test_invalid_expired_wrong_type_and_deleted_user_tokens_are_rejected(self):
        import jwt

        registered, session = self._register_and_login()
        user_id = registered["user_id"]
        now = datetime.now(timezone.utc)
        valid_claims = {
            "sub": user_id,
            "typ": self.auth.ACCESS_TOKEN_TYPE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }

        def token_without(claim: str) -> str:
            payload = {key: value for key, value in valid_claims.items() if key != claim}
            return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")

        cases = {
            "malformed": "not-a-jwt",
            "alg-none": jwt.encode(valid_claims, key=None, algorithm="none"),
            "wrong-signature": self._signed_token(subject=user_id, secret="different-test-secret-that-is-also-long-enough"),
            "expired": self._signed_token(
                subject=user_id,
                issued_at=now - timedelta(minutes=2),
                expires_at=now - timedelta(minutes=1),
            ),
            "wrong-type": self._signed_token(
                subject=user_id,
                token_type=self.auth.WS_TICKET_TYPE,
                purpose=self.auth.WS_TICKET_PURPOSE,
                base_id="BASE-001",
            ),
            "nonexistent-user": self._signed_token(subject="deleted-or-never-created-user"),
            "missing-sub": token_without("sub"),
            "missing-type": token_without("typ"),
            "missing-issued-at": token_without("iat"),
            "missing-expiry": token_without("exp"),
        }

        with self._client() as client:
            self.assertEqual(
                client.get("/api/auth/verify", headers=self._bearer(session["access_token"])).status_code,
                200,
            )
            for label, token in cases.items():
                with self.subTest(label=label):
                    response = client.get("/api/auth/verify", headers=self._bearer(token))
                    self.assertEqual(response.status_code, 401, response.text)
                    self.assertEqual(response.headers.get("www-authenticate"), "Bearer")
                    self.assertEqual(response.json()["detail"], "登录凭据无效或已过期")

            basic = client.get("/api/auth/verify", headers={"Authorization": "Basic fixture"})
            self.assertEqual(basic.status_code, 401, basic.text)
            self.assertEqual(basic.headers.get("www-authenticate"), "Bearer")

    def test_passwords_are_hashed_bounded_and_login_errors_do_not_enumerate_users(self):
        username = "password-fixture"
        email = "password-fixture@example.com"
        password = "fixture-password"

        with self._client() as client:
            registered = client.post(
                "/api/auth/register",
                json={"username": username, "email": email, "password": password},
            )
            self.assertEqual(registered.status_code, 200, registered.text)
            self.assertNotIn("password", registered.json())
            self.assertNotIn("password_hash", registered.json())

            users_data = self.auth._get_users()
            saved = users_data["users"][0]
            self.assertNotEqual(saved["password_hash"], password)
            self.assertTrue(saved["password_hash"].startswith("$2"))

            wrong_password = client.post(
                "/api/auth/login",
                data={"username": username, "password": "wrong-password"},
            )
            missing_user = client.post(
                "/api/auth/login",
                data={"username": "missing-user", "password": "wrong-password"},
            )
            self.assertEqual(wrong_password.status_code, 401)
            self.assertEqual(missing_user.status_code, 401)
            self.assertEqual(wrong_password.json(), missing_user.json())

            too_long = client.post(
                "/api/auth/register",
                json={
                    "username": "long-password",
                    "email": "long-password@example.com",
                    "password": "密" * 25,
                },
            )
            self.assertEqual(too_long.status_code, 422, too_long.text)

    def test_username_and_email_share_one_collision_free_login_namespace(self):
        with self._client() as client:
            first = client.post(
                "/api/auth/register",
                json={
                    "username": "shared@example.com",
                    "email": "first@example.com",
                    "password": "fixture-password",
                },
            )
            self.assertEqual(first.status_code, 200, first.text)

            email_hits_existing_username = client.post(
                "/api/auth/register",
                json={
                    "username": "second-user",
                    "email": "SHARED@example.com",
                    "password": "fixture-password",
                },
            )
            self.assertEqual(email_hits_existing_username.status_code, 400)

            second = client.post(
                "/api/auth/register",
                json={
                    "username": "third-user",
                    "email": "third@example.com",
                    "password": "fixture-password",
                },
            )
            self.assertEqual(second.status_code, 200, second.text)

            username_hits_existing_email = client.post(
                "/api/auth/register",
                json={
                    "username": "THIRD@example.com",
                    "email": "fourth@example.com",
                    "password": "fixture-password",
                },
            )
            self.assertEqual(username_hits_existing_email.status_code, 400)

            unicode_owner = client.post(
                "/api/auth/register",
                json={
                    "username": "strasse@example.com",
                    "email": "unicode-owner@example.com",
                    "password": "fixture-password",
                },
            )
            self.assertEqual(unicode_owner.status_code, 200, unicode_owner.text)
            unicode_casefold_collision = client.post(
                "/api/auth/register",
                json={
                    "username": "unicode-collision-user",
                    "email": "straße@example.com",
                    "password": "fixture-password",
                },
            )
            self.assertEqual(unicode_casefold_collision.status_code, 400)

            login = client.post(
                "/api/auth/login",
                data={"username": "shared@example.com", "password": "fixture-password"},
            )
            self.assertEqual(login.status_code, 200, login.text)

            # A collision left by an older build must fail closed for either
            # password instead of selecting whichever record appears first.
            users_data = self.auth._get_users()
            users_data["users"].append({
                "user_id": str(uuid.uuid4()),
                "username": "legacy-collision-user",
                "email": "shared@example.com",
                "password_hash": self.auth._hash_password("other-password"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_login": None,
                "sync_enabled": True,
            })
            self.auth._save_users(users_data)

            for candidate_password in ("fixture-password", "other-password"):
                ambiguous = client.post(
                    "/api/auth/login",
                    data={
                        "username": "shared@example.com",
                        "password": candidate_password,
                    },
                )
                self.assertEqual(ambiguous.status_code, 401, ambiguous.text)

    def test_concurrent_registration_creates_exactly_one_identity(self):
        username = f"concurrent-{uuid.uuid4().hex}"
        email = f"{username}@example.com"
        workers = 8
        barrier = threading.Barrier(workers)

        def register_once(_):
            barrier.wait(timeout=5)
            with self._client() as client:
                response = client.post(
                    "/api/auth/register",
                    json={
                        "username": username,
                        "email": email,
                        "password": "fixture-password",
                    },
                )
            return response.status_code

        with ThreadPoolExecutor(max_workers=workers) as pool:
            statuses = list(pool.map(register_once, range(workers)))

        self.assertEqual(statuses.count(200), 1)
        self.assertEqual(statuses.count(400), workers - 1)
        matching_users = [
            user
            for user in self.auth._get_users()["users"]
            if str(user.get("username", "")).casefold() == username.casefold()
        ]
        self.assertEqual(len(matching_users), 1)

    def test_missing_or_weak_jwt_secret_fails_configuration_validation(self):
        with patch.dict(os.environ, {"LINGOU_JWT_SECRET": ""}):
            with self.assertRaisesRegex(RuntimeError, "LINGOU_JWT_SECRET"):
                self.auth.validate_auth_configuration()
        with patch.dict(os.environ, {"LINGOU_JWT_SECRET": "too-short"}):
            with self.assertRaisesRegex(RuntimeError, "at least 32 bytes"):
                self.auth.validate_auth_configuration()

    def test_retired_recovery_code_social_and_user_listing_routes_are_absent(self):
        _, session = self._register_and_login()
        with self._client() as client:
            schema_paths = set(client.get("/openapi.json").json()["paths"])
            self.assertTrue(RETIRED_AUTH_PATHS.isdisjoint(schema_paths))
            for path in sorted(RETIRED_AUTH_PATHS):
                method = "GET" if path.endswith("/users") else "POST"
                anonymous = client.request(method, path, json={})
                self.assertEqual(anonymous.status_code, 401, f"{method} {path}: {anonymous.text}")
                response = client.request(
                    method,
                    path,
                    json={},
                    headers=self._bearer(session["access_token"]),
                )
                self.assertEqual(response.status_code, 404, f"{method} {path}: {response.text}")

    def test_user_store_is_restricted_to_current_os_user(self):
        if os.name != "posix":
            self.skipTest("POSIX permission bits are not available")
        self._register_and_login()
        self.assertEqual(self.auth.USERS_FILE.stat().st_mode & 0o777, 0o600)

        self.auth.USERS_FILE.chmod(0o644)
        self.auth.validate_auth_configuration()
        self.assertEqual(self.auth.USERS_FILE.stat().st_mode & 0o777, 0o600)

        self.auth.USERS_FILE.chmod(0o644)
        self.auth._get_users()
        self.assertEqual(self.auth.USERS_FILE.stat().st_mode & 0o777, 0o600)

        modes_during_write = []
        original_dump = self.auth.json.dump

        def observe_secure_file(data, handle, **kwargs):
            modes_during_write.append(os.fstat(handle.fileno()).st_mode & 0o777)
            return original_dump(data, handle, **kwargs)

        with patch.object(self.auth.json, "dump", side_effect=observe_secure_file):
            self.auth._save_users(self.auth._get_users())
        self.assertEqual(modes_during_write, [0o600])

    def test_ws_ticket_is_one_time_base_bound_and_carried_by_subprotocol(self):
        registered, session = self._register_and_login()
        base_id = "BASE-fixture"
        self._create_owned_base(registered["user_id"], base_id)
        asr_probe = Mock(return_value=False)

        with patch.object(self.asr, "is_asr_available", asr_probe):
            with self._client() as client:
                issued = client.post(
                    "/api/auth/ws-ticket",
                    json={"base_id": base_id},
                    headers=self._bearer(session["access_token"]),
                )
                self.assertEqual(issued.status_code, 200, issued.text)
                ticket = issued.json()["ticket"]
                second = client.post(
                    "/api/auth/ws-ticket",
                    json={"base_id": base_id},
                    headers=self._bearer(session["access_token"]),
                )
                self.assertEqual(second.status_code, 200, second.text)
                self.assertNotEqual(second.json()["ticket"], ticket)
                self.assertEqual(issued.json()["expires_in"], self.auth.WS_TICKET_EXPIRE_SECONDS)
                protocols = [self.asr.WS_PROTOCOL, f"{self.asr.WS_TICKET_PROTOCOL_PREFIX}{ticket}"]

                self._assert_ws_rejected(
                    client,
                    f"/api/asr/stream?base_id=another-base",
                    subprotocols=protocols,
                    code=4403,
                )
                asr_probe.assert_not_called()

                with client.websocket_connect(
                    f"/api/asr/stream?base_id={base_id}", subprotocols=protocols
                ) as websocket:
                    self.assertEqual(websocket.accepted_subprotocol, self.asr.WS_PROTOCOL)
                    message = websocket.receive_json()
                    self.assertEqual(message["type"], "error")
                asr_probe.assert_called_once()

                self._assert_ws_rejected(
                    client,
                    f"/api/asr/stream?base_id={base_id}",
                    subprotocols=protocols,
                    code=4409,
                )

    def test_real_uvicorn_delivers_ws_authentication_close_code(self):
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect

        asr_probe = Mock(side_effect=AssertionError("Provider check ran before WebSocket authentication"))
        with patch.object(self.asr, "is_asr_available", asr_probe):
            with self._uvicorn_server() as port:
                with connect(
                    f"ws://127.0.0.1:{port}/api/asr/stream?base_id=BASE-fixture",
                    subprotocols=[self.asr.WS_PROTOCOL],
                    proxy=None,
                    open_timeout=2,
                    close_timeout=2,
                ) as websocket:
                    with self.assertRaises(ConnectionClosed):
                        websocket.recv()
                    self.assertEqual(websocket.subprotocol, self.asr.WS_PROTOCOL)
                    self.assertEqual(websocket.close_code, 4401)
        asr_probe.assert_not_called()

    def test_ws_query_token_access_token_and_missing_ticket_fail_before_provider(self):
        registered, session = self._register_and_login()
        base_id = "BASE-fixture"
        self._create_owned_base(registered["user_id"], base_id)
        asr_probe = Mock(side_effect=AssertionError("Provider check ran before WebSocket authentication"))

        with patch.object(self.asr, "is_asr_available", asr_probe):
            with self._client() as client:
                issued = client.post(
                    "/api/auth/ws-ticket",
                    json={"base_id": base_id},
                    headers=self._bearer(session["access_token"]),
                )
                self.assertEqual(issued.status_code, 200, issued.text)
                ticket = issued.json()["ticket"]

                self._assert_ws_rejected(
                    client,
                    f"/api/asr/stream?base_id={base_id}&ticket={ticket}",
                    subprotocols=[self.asr.WS_PROTOCOL],
                    code=4401,
                )
                self._assert_ws_rejected(
                    client,
                    f"/api/asr/stream?base_id={base_id}",
                    subprotocols=[
                        self.asr.WS_PROTOCOL,
                        f"{self.asr.WS_TICKET_PROTOCOL_PREFIX}{session['access_token']}",
                    ],
                    code=4401,
                )
                self._assert_ws_rejected(
                    client,
                    f"/api/asr/stream?base_id={base_id}",
                    subprotocols=[self.asr.WS_PROTOCOL],
                    code=4401,
                )
        asr_probe.assert_not_called()

    def test_ws_expired_wrong_purpose_and_unknown_user_tickets_are_rejected(self):
        registered, _ = self._register_and_login()
        base_id = "BASE-fixture"
        now = datetime.now(timezone.utc)
        cases = {
            4401: [
                self._signed_token(
                    subject=registered["user_id"],
                    token_type=self.auth.WS_TICKET_TYPE,
                    issued_at=now - timedelta(minutes=2),
                    expires_at=now - timedelta(minutes=1),
                    purpose=self.auth.WS_TICKET_PURPOSE,
                    base_id=base_id,
                ),
                self._signed_token(
                    subject="missing-user",
                    token_type=self.auth.WS_TICKET_TYPE,
                    purpose=self.auth.WS_TICKET_PURPOSE,
                    base_id=base_id,
                ),
            ],
            4403: [
                self._signed_token(
                    subject=registered["user_id"],
                    token_type=self.auth.WS_TICKET_TYPE,
                    purpose="different-purpose",
                    base_id=base_id,
                ),
            ],
        }
        asr_probe = Mock(side_effect=AssertionError("Provider check ran before ticket validation"))

        with patch.object(self.asr, "is_asr_available", asr_probe):
            with self._client() as client:
                for expected_code, tickets in cases.items():
                    for ticket in tickets:
                        with self.subTest(code=expected_code):
                            self._assert_ws_rejected(
                                client,
                                f"/api/asr/stream?base_id={base_id}",
                                subprotocols=[
                                    self.asr.WS_PROTOCOL,
                                    f"{self.asr.WS_TICKET_PROTOCOL_PREFIX}{ticket}",
                                ],
                                code=expected_code,
                            )
        asr_probe.assert_not_called()

    def test_concurrent_ws_ticket_replay_has_exactly_one_winner(self):
        registered, _ = self._register_and_login()
        base_id = "BASE-concurrent"
        self._create_owned_base(registered["user_id"], base_id)
        ticket = self.auth._create_ws_ticket(registered["user_id"], base_id)
        workers = 12
        barrier = threading.Barrier(workers)

        def consume_once():
            barrier.wait(timeout=5)
            user, close_code = self.auth.consume_ws_ticket(ticket, base_id)
            return user and user["user_id"], close_code

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda _: consume_once(), range(workers)))

        winners = [result for result in results if result[1] == 0]
        replays = [result for result in results if result[1] == 4409]
        self.assertEqual(winners, [(registered["user_id"], 0)])
        self.assertEqual(len(replays), workers - 1)

    def test_ws_ticket_endpoint_requires_a_valid_access_token(self):
        with self._client() as client:
            response = client.post("/api/auth/ws-ticket", json={"base_id": "BASE-001"})
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.headers.get("www-authenticate"), "Bearer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
