"""Run explicitly: python -B tests/test_baseline.py

Uses a real application import, temporary storage, an in-process ASGI client and
a loopback WebSocket server. No real credentials or provider calls are needed.
This suite validates the step-01 environment, not the known product defects.
"""

import asyncio
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SERVER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVER_ROOT.parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True


class BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix="lingou-baseline-"))).resolve()
        cls.runtime = cls.temp / "runtime"
        clean_env = {
            key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")
            if key in os.environ
        }
        clean_env.update(
            LINGOU_DATA_DIR=str(cls.runtime),
            LINGOU_LOAD_DOTENV="0",
            LINGOU_WARMUP_ON_STARTUP="0",
            LINGOU_JWT_SECRET="baseline-only-auth-secret-32-bytes-minimum",
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))

        # Install guards before importing application modules. Disable the audit
        # guard before ExitStack cleans up its temporary directory.
        cls.policy = {"active": True}
        cls.stack.callback(cls.policy.update, active=False)

        def filesystem_guard(event, args):
            if not cls.policy["active"]:
                return
            if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(args[0])).resolve()
                mode, flags = args[1], args[2]
                writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                    isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                )
                if writing and not path.is_relative_to(cls.temp):
                    raise AssertionError("Baseline attempted a write outside its temporary directory")
                if path.name == ".env":
                    raise AssertionError("Baseline attempted to read a real .env file")
                for runtime_root in (PROJECT_ROOT / "data", SERVER_ROOT / "data"):
                    if path.is_relative_to(runtime_root) and path.suffix not in {".py", ".pyc"}:
                        raise AssertionError("Baseline attempted to access existing runtime data")
            elif event in {"os.mkdir", "os.remove", "os.rmdir"} and isinstance(args[0], (str, bytes, os.PathLike)):
                if not Path(os.fsdecode(args[0])).resolve().is_relative_to(cls.temp):
                    raise AssertionError("Baseline attempted to mutate a directory outside its temporary directory")

        sys.addaudithook(filesystem_guard)

        def loopback_only(address):
            return isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}

        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_getaddrinfo = socket.getaddrinfo

        def guarded_connect(sock, address):
            if not loopback_only(address):
                raise AssertionError("External network access is disabled in baseline tests")
            return original_connect(sock, address)

        def guarded_connect_ex(sock, address):
            if not loopback_only(address):
                raise AssertionError("External network access is disabled in baseline tests")
            return original_connect_ex(sock, address)

        def guarded_getaddrinfo(host, *args, **kwargs):
            if host not in {"127.0.0.1", "::1"}:
                raise AssertionError("External DNS resolution is disabled in baseline tests")
            return original_getaddrinfo(host, *args, **kwargs)

        cls.stack.enter_context(patch("socket.socket.connect", guarded_connect))
        cls.stack.enter_context(patch("socket.socket.connect_ex", guarded_connect_ex))
        cls.stack.enter_context(patch("socket.getaddrinfo", guarded_getaddrinfo))
        cls.stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("External processes are disabled")))
        cls.dotenv = cls.stack.enter_context(patch("dotenv.load_dotenv", side_effect=AssertionError("Real dotenv loading is disabled")))

        from app import main
        from app.api import auth
        from app.core import tts_adapter
        from data import store
        cls.main, cls.auth, cls.tts, cls.store = main, auth, tts_adapter, store

    def test_runtime_and_audio_paths_are_isolated(self):
        self.assertEqual(self.store.DATA_DIR, self.runtime)
        for name in ("USER_DATA_DIR", "BASES_DIR", "FIGURES_DIR", "ARCHETYPES_DIR", "EVENTS_DIR",
                     "DIALOGUE_LOGS_DIR", "SYNC_QUEUE_DIR", "VOICE_UPLOADS_DIR"):
            self.assertTrue(getattr(self.store, name).is_relative_to(self.runtime), name)
        self.assertTrue(self.auth.USERS_FILE.is_relative_to(self.runtime))
        for name in ("AUDIO_CACHE_DIR", "VOICE_POOL_DIR", "VOICE_POOL_TEXTS_DIR"):
            path = getattr(self.tts, name)
            self.assertTrue(path.is_relative_to(self.runtime), name)
            self.assertTrue(path.is_dir(), name)
        self.dotenv.assert_not_called()

    def test_fictional_storage_and_upload_round_trip(self):
        figure = {"figure_id": "baseline-figure", "name": "Baseline fixture"}
        saved = self.store.save_figure("baseline-figure", figure, user_id="baseline-owner")
        self.assertEqual(saved["owner_user_id"], "baseline-owner")
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(
            self.store.get_figure("baseline-figure", user_id="baseline-owner"),
            saved,
        )
        path = self.store.save_voice_upload(
            "baseline-figure",
            "fixture.bin",
            b"fictional audio fixture",
            user_id="baseline-owner",
        )
        self.assertTrue(path.is_relative_to(self.runtime))
        self.assertEqual(path.read_bytes(), b"fictional audio fixture")
        cache = self.tts.AUDIO_CACHE_DIR / "fixture.bin"
        cache.write_bytes(b"fictional cached audio")
        self.assertEqual(cache.read_bytes(), b"fictional cached audio")

    def test_application_startup_and_http_smoke(self):
        from fastapi.testclient import TestClient
        with patch.object(self.main.online_brain, "_call_doubao", side_effect=AssertionError("Warmup must be skipped")) as provider:
            with TestClient(self.main.app) as client:
                root = client.get("/")
                self.assertEqual(root.status_code, 200)
                self.assertEqual(root.json()["service"], "lingou-companion-server")
                self.assertEqual(client.get("/health").json(), {"status": "healthy"})
                schema = client.get("/openapi.json")
                self.assertEqual(schema.status_code, 200)
                self.assertIn("/api/auth/register", schema.json()["paths"])
            provider.assert_not_called()

    def test_warmup_can_still_use_an_injected_provider(self):
        fake_provider = Mock(return_value={"choices": [{"message": {"content": "fixture reply"}}]})
        with patch.dict(os.environ, {"LINGOU_WARMUP_ON_STARTUP": "1"}), patch.object(self.main.online_brain, "_call_doubao", fake_provider):
            asyncio.run(self.main.startup_event())
        fake_provider.assert_called_once()

    def test_email_and_password_dependencies_import_and_execute(self):
        import bcrypt
        import jwt
        user = self.auth.UserCreate(username="fixture", email="fixture@example.com", password="fixture-password")
        self.assertEqual(user.email, "fixture@example.com")
        hashed = bcrypt.hashpw(b"fixture-password", bcrypt.gensalt(rounds=4))
        self.assertTrue(bcrypt.checkpw(b"fixture-password", hashed))
        key = "baseline-only-key-for-local-tests-123456"
        token = jwt.encode({"sub": "fixture"}, key, algorithm="HS256")
        self.assertEqual(jwt.decode(token, key, algorithms=["HS256"])["sub"], "fixture")

    def test_websocket_additional_headers_on_loopback(self):
        import websockets

        async def round_trip():
            async def echo(connection):
                self.assertEqual(connection.request.headers["X-Baseline"], "fixture")
                await connection.send(await connection.recv())

            async with websockets.serve(echo, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                async with websockets.connect(f"ws://127.0.0.1:{port}", additional_headers={"X-Baseline": "fixture"}) as connection:
                    await connection.send("fixture")
                    self.assertEqual(await connection.recv(), "fixture")

        asyncio.run(asyncio.wait_for(round_trip(), timeout=5))

    def test_network_guard_rejects_external_destination(self):
        with socket.socket() as sock:
            with self.assertRaisesRegex(AssertionError, "External network"):
                sock.connect(("192.0.2.1", 443))

    def test_filesystem_guard_rejects_existing_runtime_data(self):
        with self.assertRaisesRegex(AssertionError, "existing runtime data"):
            (PROJECT_ROOT / "data" / "baseline-must-not-read.json").read_text()
        with self.assertRaisesRegex(AssertionError, "outside its temporary directory"):
            (SERVER_ROOT / "baseline-must-not-write.txt").write_text("must be blocked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
