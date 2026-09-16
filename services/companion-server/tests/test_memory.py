"""Run explicitly: python -B tests/test_memory.py.

Step-09 confirmed-memory tests use fictional data, fake extraction and an
isolated runtime directory.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True


class ConfirmedMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(
            cls.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="lingou-confirmed-memory-")
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
            LINGOU_JWT_SECRET="step-09-test-only-jwt-secret-at-least-32-bytes",
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))
        cls.stack.enter_context(
            patch(
                "dotenv.load_dotenv",
                side_effect=AssertionError("dotenv must stay disabled"),
            )
        )

        from app import main
        from app.core import dialogue_engine, memory_engine, persona_builder
        from data import store

        cls.main = main
        cls.dialogue_engine = dialogue_engine
        cls.memory_engine = memory_engine
        cls.persona_builder = persona_builder
        cls.store = store

    def setUp(self):
        self.main.auth.USERS_FILE.unlink(missing_ok=True)
        with self.dialogue_engine._summary_cache_lock:
            self.dialogue_engine._summary_cache.clear()
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

    def _figure(self, owner: str, label: str = "Memory Fixture") -> dict:
        figure_id = f"FIGURE-{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        return self.store.save_figure(
            figure_id,
            {
                "figure_id": figure_id,
                "name": label,
                "created_at": now,
                "soul_profile": {
                    "archetype": "冷淡守护型",
                    "address_user_as": "搭档",
                    "persona": {"speaking_style": "冷静"},
                    "emotion_state": {},
                },
                "voice_profile": {},
                "memory": {
                    "interaction_count": 0,
                    "relationship_points": 0,
                    "relationship_level": "陌生",
                    "favorite_responses": [],
                    "first_met_at": now,
                },
            },
            user_id=owner,
        )

    def _base(self, owner: str, figure_id: str) -> str:
        base_id = f"BASE-{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        self.store.save_base(
            base_id,
            {
                "base_id": base_id,
                "active_figure_id": figure_id,
                "status": "bound",
                "created_at": now,
                "updated_at": now,
            },
            owner_user_id=owner,
        )
        return base_id

    def _client(self):
        from fastapi.testclient import TestClient

        return TestClient(self.main.app)

    @staticmethod
    def _headers(session: dict) -> dict[str, str]:
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

    def test_confirmed_fact_survives_a_fresh_process_and_enters_prompt(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        figure = self._figure(owner)
        record, created = self.memory_engine.create_confirmed_memory(
            figure["figure_id"],
            "我每周三晚上学习日语",
            user_id=owner,
        )
        self.assertTrue(created)
        self.assertEqual(record["status"], "confirmed")

        code = """
import json, os
from app.core.memory_engine import list_memory_records
from app.core.persona_builder import build_persona_prompt
from data.store import get_figure
figure = get_figure(os.environ["TEST_FIGURE_ID"], user_id=os.environ["TEST_OWNER"])
data = list_memory_records(os.environ["TEST_FIGURE_ID"], user_id=os.environ["TEST_OWNER"])
print(json.dumps({
    "facts": [item["content"] for item in data["confirmed_facts"]],
    "in_prompt": "我每周三晚上学习日语" in build_persona_prompt(figure),
}, ensure_ascii=False))
"""
        env = os.environ.copy()
        env.update(TEST_OWNER=owner, TEST_FIGURE_ID=figure["figure_id"])
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=SERVER_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        restarted = json.loads(result.stdout)
        self.assertEqual(restarted["facts"], ["我每周三晚上学习日语"])
        self.assertTrue(restarted["in_prompt"])

    def test_correction_and_deletion_cannot_be_resurrected_by_extraction(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        figure = self._figure(owner)
        record, _ = self.memory_engine.create_confirmed_memory(
            figure["figure_id"],
            "我住在北京",
            user_id=owner,
        )
        corrected = self.memory_engine.update_memory_record(
            figure["figure_id"],
            record["memory_id"],
            "我住在上海",
            user_id=owner,
        )
        self.assertEqual(corrected["content"], "我住在上海")
        old_candidate, old_created = self.memory_engine.add_memory_candidate(
            figure["figure_id"],
            "我住在北京",
            source_turn_id="TURN-OLD",
            user_id=owner,
        )
        self.assertIsNone(old_candidate)
        self.assertFalse(old_created)

        current = self.store.get_figure(figure["figure_id"], user_id=owner)
        prompt = self.persona_builder.build_persona_prompt(current)
        self.assertIn("我住在上海", prompt)
        self.assertNotIn("我住在北京", prompt)

        self.memory_engine.delete_memory_record(
            figure["figure_id"],
            record["memory_id"],
            user_id=owner,
        )
        deleted_candidate, deleted_created = self.memory_engine.add_memory_candidate(
            figure["figure_id"],
            "我住在上海",
            source_turn_id="TURN-DELETED",
            user_id=owner,
        )
        self.assertIsNone(deleted_candidate)
        self.assertFalse(deleted_created)
        current = self.store.get_figure(figure["figure_id"], user_id=owner)
        prompt = self.persona_builder.build_persona_prompt(current)
        self.assertNotIn("我住在北京", prompt)
        self.assertNotIn("我住在上海", prompt)

    def test_concurrent_confirmed_fact_updates_do_not_lose_records(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        figure = self._figure(owner)

        def create(index: int) -> None:
            self.memory_engine.create_confirmed_memory(
                figure["figure_id"],
                f"并发事实 {index}",
                user_id=owner,
            )

        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(create, range(10)))

        data = self.memory_engine.list_memory_records(
            figure["figure_id"],
            user_id=owner,
        )
        self.assertEqual(len(data["confirmed_facts"]), 10)
        self.assertEqual(
            {item["content"] for item in data["confirmed_facts"]},
            {f"并发事实 {index}" for index in range(10)},
        )
        self.assertEqual(data["revision"], 10)
        with self.assertRaises(self.memory_engine.MemoryLimitError):
            self.memory_engine.create_confirmed_memory(
                figure["figure_id"],
                "第十一条事实",
                user_id=owner,
            )

    def test_dialogue_commit_preserves_concurrently_updated_memory(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        figure = self._figure(owner)
        stale = self.store.get_figure(figure["figure_id"], user_id=owner)
        self.memory_engine.create_confirmed_memory(
            figure["figure_id"],
            "不会被旧对话对象覆盖",
            user_id=owner,
        )
        stale["memory"]["interaction_count"] = 1
        now = datetime.now(timezone.utc).isoformat()
        self.store.save_dialogue_turn(
            figure["figure_id"],
            stale,
            {
                "dialogue_id": f"TURN-{uuid.uuid4().hex}",
                "figure_id": figure["figure_id"],
                "base_id": f"BASE-{uuid.uuid4().hex}",
                "user_input_text": "fixture",
                "reply_text": "fixture",
                "created_at": now,
            },
            user_id=owner,
        )

        data = self.memory_engine.list_memory_records(
            figure["figure_id"],
            user_id=owner,
        )
        self.assertEqual(
            [item["content"] for item in data["confirmed_facts"]],
            ["不会被旧对话对象覆盖"],
        )

    def test_candidates_do_not_enter_prompt_until_confirmed(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        figure = self._figure(owner)
        candidate, created = self.memory_engine.add_memory_candidate(
            figure["figure_id"],
            "我喜欢爵士乐",
            source_turn_id="TURN-CANDIDATE",
            user_id=owner,
        )
        self.assertTrue(created)
        current = self.store.get_figure(figure["figure_id"], user_id=owner)
        self.assertNotIn(
            "我喜欢爵士乐",
            self.persona_builder.build_persona_prompt(current),
        )

        confirmed = self.memory_engine.confirm_memory_candidate(
            figure["figure_id"],
            candidate["memory_id"],
            user_id=owner,
        )
        self.assertEqual(confirmed["source_turn_id"], "TURN-CANDIDATE")
        current = self.store.get_figure(figure["figure_id"], user_id=owner)
        self.assertIn(
            "用户已确认事实：我喜欢爵士乐",
            self.persona_builder.build_persona_prompt(current),
        )

    def test_memory_api_crud_and_owner_isolation(self):
        with self._client() as client:
            owner_a, session_a = self._account(client, "memory-a")
            _owner_b, session_b = self._account(client, "memory-b")
            figure = self._figure(owner_a["user_id"])
            headers_a = self._headers(session_a)
            headers_b = self._headers(session_b)

            denied = client.get(
                f"/api/figures/{figure['figure_id']}/memories",
                headers=headers_b,
            )
            self.assertEqual(denied.status_code, 404, denied.text)

            created = client.post(
                f"/api/figures/{figure['figure_id']}/memories",
                json={"content": "我不喝含糖饮料"},
                headers=headers_a,
            )
            self.assertEqual(created.status_code, 201, created.text)
            memory_id = created.json()["memory"]["memory_id"]
            updated = client.put(
                f"/api/figures/{figure['figure_id']}/memories/{memory_id}",
                json={"content": "我只喝无糖饮料"},
                headers=headers_a,
            )
            self.assertEqual(updated.status_code, 200, updated.text)
            listed = client.get(
                f"/api/figures/{figure['figure_id']}/memories",
                headers=headers_a,
            )
            self.assertEqual(
                [item["content"] for item in listed.json()["confirmed_facts"]],
                ["我只喝无糖饮料"],
            )
            deleted = client.delete(
                f"/api/figures/{figure['figure_id']}/memories/{memory_id}",
                headers=headers_a,
            )
            self.assertEqual(deleted.status_code, 204, deleted.text)
            listed = client.get(
                f"/api/figures/{figure['figure_id']}/memories",
                headers=headers_a,
            )
            self.assertEqual(listed.json()["confirmed_facts"], [])

    def test_extraction_runs_after_reply_without_blocking_response(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        figure = self._figure(owner)
        base_id = self._base(owner, figure["figure_id"])
        extraction_started = threading.Event()
        release_extraction = threading.Event()
        first_text = threading.Event()

        def blocking_extractor(*_args, **_kwargs):
            extraction_started.set()
            release_extraction.wait(timeout=2)
            return json.dumps({
                "worth_remember": True,
                "content": "我周五要参加考试",
            }, ensure_ascii=False)

        def stream_reply(*_args, **_kwargs):
            yield "先准备最重要的部分。"
            return "online"

        def fake_speech(*_args, **_kwargs):
            return {
                "engine": "fixture",
                "audio_path": "fixture.mp3",
                "success": True,
                "synthesized": True,
                "transferred": False,
            }

        started_at = time.monotonic()
        with (
            patch.object(
                self.dialogue_engine,
                "route_reply_streaming",
                side_effect=stream_reply,
            ),
            patch.object(
                self.dialogue_engine,
                "speak_sentence_streaming",
                side_effect=fake_speech,
            ),
            patch.object(self.dialogue_engine, "is_weather_query", return_value=False),
            patch.object(
                self.dialogue_engine,
                "should_use_bot_search",
                return_value=False,
            ),
            patch.object(self.dialogue_engine, "extract_city", return_value=None),
            patch.object(self.memory_engine, "_is_configured", return_value=True),
            patch.object(
                self.memory_engine,
                "_call_doubao",
                side_effect=blocking_extractor,
            ),
        ):
            result = self.dialogue_engine.process_text_input(
                base_id,
                "我周五要参加考试",
                owner_user_id=owner,
                text_sink=lambda _text: first_text.set(),
                audio_sink=lambda _payload: True,
                session_id="VOICE-MEMORY-SESSION",
                turn_id="VOICE-MEMORY-TURN",
            )
            elapsed = time.monotonic() - started_at
            self.assertTrue(first_text.is_set())
            self.assertTrue(extraction_started.wait(timeout=1))
            self.assertLess(elapsed, 0.5)
            self.assertEqual(result["reply"], "先准备最重要的部分。")
            release_extraction.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                data = self.memory_engine.list_memory_records(
                    figure["figure_id"],
                    user_id=owner,
                )
                if data["candidates"]:
                    break
                time.sleep(0.01)
            else:
                self.fail("memory candidate was not persisted")

        self.assertEqual(data["candidates"][0]["content"], "我周五要参加考试")
        self.assertEqual(
            data["candidates"][0]["source_turn_id"],
            "VOICE-MEMORY-TURN",
        )

    def test_recent_history_is_bounded_and_stale_summary_is_ignored(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        figure = self._figure(owner)
        for index in range(110):
            self.store.save_dialogue_log(
                {
                    "dialogue_id": f"TURN-{index:03d}",
                    "figure_id": figure["figure_id"],
                    "base_id": "BASE-HISTORY",
                    "user_input_text": f"用户消息 {index}",
                    "reply_text": f"角色回复 {index}",
                    "created_at": f"2026-09-15T10:{index // 60:02d}:{index % 60:02d}+00:00",
                },
                user_id=owner,
            )
        with self.dialogue_engine._summary_cache_lock:
            self.dialogue_engine._summary_cache[(owner, figure["figure_id"])] = {
                "summary": "已删除的旧事实",
                "summarized_upto": 100,
            }

        history, summary = self.dialogue_engine._load_history_fast(
            owner,
            figure["figure_id"],
        )
        self.assertEqual(len(history), 12)
        self.assertEqual(summary, "")
        self.assertEqual(history[0]["content"], "用户消息 104")
        self.dialogue_engine._background_compress_history(
            owner,
            figure["figure_id"],
            figure,
        )
        with self.dialogue_engine._summary_cache_lock:
            self.assertEqual(
                self.dialogue_engine._summary_cache[(owner, figure["figure_id"])][
                    "summary"
                ],
                "已删除的旧事实",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
