"""Run explicitly: python -B tests/test_primary_flow.py.

Step-10 primary-flow tests keep deferred gameplay and diagnostic writes out of
the default runtime while preserving them behind explicit development flags.
"""

from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True


class PrimaryFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(
            cls.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="lingou-primary-flow-")
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
            LINGOU_JWT_SECRET="step-10-test-only-jwt-secret-at-least-32-bytes",
            LINGOU_ENABLE_DEV_TOOLS="0",
            LINGOU_ENABLE_DEFERRED_GAMEPLAY="0",
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))
        cls.stack.enter_context(
            patch(
                "dotenv.load_dotenv",
                side_effect=AssertionError("dotenv must stay disabled"),
            )
        )

        from app import main
        from app.core import persona_builder, response_engine
        from data import store

        cls.main = main
        cls.persona_builder = persona_builder
        cls.response_engine = response_engine
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

    def _account(self, client) -> tuple[dict, dict]:
        username = f"primary-{uuid.uuid4().hex}"
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

    def _figure_and_base(self, owner: str) -> tuple[dict, str]:
        now = datetime.now(timezone.utc).isoformat()
        figure_id = f"FIGURE-{uuid.uuid4().hex}"
        figure = self.store.save_figure(
            figure_id,
            {
                "figure_id": figure_id,
                "name": "Primary Fixture",
                "created_at": now,
                "soul_profile": {
                    "archetype": "冷淡守护型",
                    "address_user_as": "搭档",
                    "emotion_state": {
                        "happy": 50,
                        "lonely": 0,
                        "attached": 0,
                        "annoyed": 0,
                        "attention": 0,
                        "sleepy": 0,
                    },
                },
                "voice_profile": {},
                "touch_reactions": {
                    "figure_placed": ["你来了。"],
                    "light_touch": ["我在。"],
                    "heavy_press": ["轻一点。"],
                },
                "touch_escalation": {
                    "heavy_press": {
                        "tier2": ["别再按了。"],
                        "tier3": ["停下。"],
                    },
                },
                "memory": {
                    "interaction_count": 0,
                    "relationship_points": 12,
                    "relationship_level": "陌生",
                    "streak_days": 4,
                    "last_interaction_at": now,
                },
            },
            user_id=owner,
        )
        base_id = f"BASE-{uuid.uuid4().hex}"
        self.store.save_base(
            base_id,
            {
                "base_id": base_id,
                "owner_user_id": owner,
                "active_figure_id": figure_id,
                "status": "bound",
                "created_at": now,
                "updated_at": now,
            },
            owner_user_id=owner,
        )
        return figure, base_id

    def test_deferred_write_endpoints_are_hidden_by_default(self):
        with self._client() as client:
            owner, session = self._account(client)
            figure, base_id = self._figure_and_base(owner["user_id"])
            headers = self._headers(session)
            before = deepcopy(
                self.store.get_figure(figure["figure_id"], user_id=owner["user_id"])
            )
            probes = (
                (
                    "POST",
                    f"/api/figures/{figure['figure_id']}/simulate-absence",
                    {"json": {"hours": 72}},
                ),
                (
                    "POST",
                    f"/api/figures/{figure['figure_id']}/boost-relationship",
                    {"json": {"level": "羁绊"}},
                ),
                (
                    "POST",
                    "/api/hardware/simulate",
                    {"json": {"base_id": base_id, "event_type": "light_touch"}},
                ),
                (
                    "POST",
                    "/api/events",
                    {"json": {"base_id": base_id, "event_type": "light_touch"}},
                ),
                (
                    "POST",
                    f"/api/brain/mode?base_id={base_id}",
                    {"json": {"mode": "offline"}},
                ),
                (
                    "GET",
                    f"/api/voice/clone/status?figure_id={figure['figure_id']}",
                    {},
                ),
                (
                    "POST",
                    "/api/voice/clone/start",
                    {"json": {"figure_id": figure["figure_id"]}},
                ),
                (
                    "GET",
                    "/api/hardware/system-voices",
                    {},
                ),
            )
            for method, path, kwargs in probes:
                with self.subTest(path=path):
                    response = client.request(
                        method,
                        path,
                        headers=headers,
                        **kwargs,
                    )
                    self.assertEqual(response.status_code, 404, response.text)

            after = self.store.get_figure(
                figure["figure_id"],
                user_id=owner["user_id"],
            )
            self.assertEqual(after, before)

    def test_development_switch_can_enable_owned_diagnostic_operation(self):
        with self._client() as client:
            owner, session = self._account(client)
            figure, _base_id = self._figure_and_base(owner["user_id"])
            with patch.dict(os.environ, {"LINGOU_ENABLE_DEV_TOOLS": "1"}):
                response = client.post(
                    f"/api/figures/{figure['figure_id']}/boost-relationship",
                    json={"points": 50},
                    headers=self._headers(session),
                )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["memory"]["relationship_points"], 50)

    def test_normal_creation_does_not_initialize_deferred_gameplay(self):
        with self._client() as client:
            _owner, session = self._account(client)
            response = client.post(
                "/api/figures",
                json={
                    "name": "MVP Figure",
                    "figure_type": "soul",
                    "wake_names": ["小忆"],
                    "soul_profile": {
                        "archetype": "冷淡守护型",
                        "one_line": "会记住重要事情的伙伴",
                    },
                },
                headers=self._headers(session),
            )
            self.assertEqual(response.status_code, 200, response.text)
            memory = response.json()["memory"]
            self.assertEqual(memory["interaction_count"], 0)
            self.assertEqual(memory["confirmed_facts"], [])
            self.assertNotIn("relationship_points", memory)
            self.assertNotIn("relationship_level", memory)
            self.assertNotIn("streak_days", memory)
            self.assertNotIn("memory_capsule", memory)

    def test_default_touch_and_dialogue_context_do_not_run_gameplay_rules(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        figure, base_id = self._figure_and_base(owner)
        before_mood = deepcopy(figure["soul_profile"]["emotion_state"])

        first = self.response_engine.generate_touch_response(
            base_id,
            "heavy_press",
            owner_user_id=owner,
        )
        second = self.response_engine.generate_touch_response(
            base_id,
            "heavy_press",
            owner_user_id=owner,
        )
        saved = self.store.get_figure(figure["figure_id"], user_id=owner)

        self.assertEqual(first["reply"], "轻一点。")
        self.assertEqual(second["reply"], "轻一点。")
        self.assertFalse(first["deferred_gameplay"])
        self.assertNotIn("touch_streak", saved)
        self.assertEqual(saved["memory"]["relationship_points"], 12)
        self.assertEqual(saved["memory"]["streak_days"], 4)
        self.assertEqual(saved["memory"]["interaction_count"], 2)
        self.assertEqual(saved["soul_profile"]["emotion_state"], before_mood)

        prompt = self.persona_builder.build_persona_prompt(saved)
        self.assertNotIn("关系阶段", prompt)
        self.assertNotIn("当前状态", prompt)
        self.assertNotIn("羁绊点", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
