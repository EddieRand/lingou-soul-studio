"""Run explicitly: python -B tests/test_persona_dialogue.py.

Step-08 persona and shared-turn tests. Providers are replaced with deterministic
fakes and all persisted data uses a temporary runtime directory.
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
from unittest.mock import Mock, patch
import uuid


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.dont_write_bytecode = True


class PersonaDialogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(
            cls.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="lingou-persona-dialogue-")
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
            LINGOU_JWT_SECRET="step-08-test-only-jwt-secret-at-least-32-bytes",
        )
        cls.stack.enter_context(patch.dict(os.environ, clean_env, clear=True))
        cls.stack.enter_context(
            patch(
                "dotenv.load_dotenv",
                side_effect=AssertionError("dotenv must stay disabled"),
            )
        )

        from app.api import dialogue as dialogue_api, figures as figures_api
        from app.core import (
            dialogue_engine,
            offline_brain,
            online_brain,
            persona_builder,
        )
        from app.core.dialogue_state import reset
        from data import store

        cls.dialogue_api = dialogue_api
        cls.figures_api = figures_api
        cls.dialogue_engine = dialogue_engine
        cls.offline_brain = offline_brain
        cls.online_brain = online_brain
        cls.persona_builder = persona_builder
        cls.reset_dialogue_state = staticmethod(reset)
        cls.store = store

    @staticmethod
    def _rich_figure() -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "figure_id": "FIGURE-PERSONA",
            "name": "阿澈",
            "description": "守护旧书店的灵偶",
            "created_at": now,
            "soul_profile": {
                "archetype": "冷淡守护型",
                "one_line": "嘴硬但会认真守住承诺",
                "address_user_as": "搭档",
                "persona": {
                    "traits": ["克制", "可靠"],
                    "speaking_style": "短句、冷静、不卖萌",
                },
                "emotion_state": {},
                "character_profile": {
                    "character_name": "旧名字",
                    "one_line": "旧核心设定",
                    "background": "曾在海边旧书店工作，珍惜每一本被遗忘的书。",
                    "traits": ["谨慎", "守信", "外冷内热"],
                    "speech_style": "先给结论，再表达关心",
                    "catchphrases": ["我记得。", "别逞强。"],
                    "signature_lines": ["答应你的事，我不会忘。"],
                    "relationships": {"店长": "恩人", "小满": "旧友"},
                    "knowledge_bounds": {
                        "knows": ["旧书修复", "海边天气"],
                        "unknowns": ["实时股票"],
                    },
                    "values": ["承诺", "诚实"],
                    "taboos": ["嘲笑用户的脆弱"],
                    "address_user_as": "过期称呼",
                },
            },
            "memory": {
                "relationship_level": "熟悉",
                "relationship_points": 30,
                "first_met_at": now,
            },
        }

    def test_persona_builder_includes_effective_fields_and_transparent_identity(self):
        prompt = self.persona_builder.build_persona_prompt(
            self._rich_figure(),
            "搭档昨天提到今天要面试。",
        )

        for expected in (
            "名字：阿澈",
            "核心设定：嘴硬但会认真守住承诺",
            "背景：曾在海边旧书店工作",
            "稳定特质：谨慎、守信、外冷内热",
            "表达方式：先给结论，再表达关心",
            "口头禅：我记得。；别逞强。",
            "代表台词：答应你的事，我不会忘。",
            "重视的事：承诺、诚实",
            "重要关系：店长：恩人；小满：旧友",
            "熟悉领域：旧书修复、海边天气",
            "不了解或应谨慎的领域：实时股票",
            "禁忌与边界：嘲笑用户的脆弱",
            "对用户的称呼：搭档",
            "近期对话摘要：搭档昨天提到今天要面试。",
            "由 AI 驱动",
            "不得否认",
        ):
            self.assertIn(expected, prompt)
        self.assertNotIn("过期称呼", prompt)
        self.assertNotIn("Eddie", prompt)
        self.assertNotIn("绝不承认自己是 AI", prompt)

    def test_editing_persona_changes_the_next_prompt(self):
        figure = self._rich_figure()
        before = self.persona_builder.build_persona_prompt(figure)
        edited = deepcopy(figure)
        edited["soul_profile"]["character_profile"]["values"] = ["自由", "好奇"]
        edited["soul_profile"]["character_profile"]["speech_style"] = "轻快地追问细节"

        after = self.persona_builder.build_persona_prompt(edited)

        self.assertNotEqual(before, after)
        self.assertIn("重视的事：自由、好奇", after)
        self.assertIn("表达方式：轻快地追问细节", after)
        self.assertNotIn("重视的事：承诺、诚实", after)

    def test_sparse_persona_uses_neutral_address_without_developer_name(self):
        prompt = self.persona_builder.build_persona_prompt({
            "name": "小灯",
            "soul_profile": {
                "archetype": "陪伴型",
                "address_user_as": "Eddie",
                "character_profile": {"address_user_as": "Eddie"},
            },
            "memory": {},
        })

        self.assertIn("对用户的称呼：你", prompt)
        self.assertNotIn("Eddie", prompt)
        self.assertNotIn("称呼用户「主人」", prompt)

    def test_figure_creation_promotes_generated_address_to_canonical_persona(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        saved = self.figures_api.create_figure(
            self.figures_api.CreateFigureRequest(
                name="新角色",
                figure_type="soul",
                soul_profile={
                    "archetype": "冷淡守护型",
                    "character_profile": {"address_user_as": "队长"},
                },
            ),
            current_user={"user_id": owner},
        )

        self.assertEqual(saved["soul_profile"]["address_user_as"], "队长")
        self.assertEqual(
            saved["soul_profile"]["character_profile"]["address_user_as"],
            "队长",
        )

    def test_persisted_persona_edit_is_used_by_the_next_prompt(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        saved = self.figures_api.create_figure(
            self.figures_api.CreateFigureRequest(
                name="小灯",
                figure_type="soul",
                soul_profile={
                    "archetype": "陪伴型",
                    "character_profile": {
                        "background": "旧背景",
                        "values": ["安静"],
                    },
                },
            ),
            current_user={"user_id": owner},
        )
        self.figures_api.update_figure(
            saved["figure_id"],
            self.figures_api.UpdateFigureRequest(
                soul_profile={
                    "address_user_as": "队长",
                    "character_profile": {
                        "background": "在灯塔记录每一次归航。",
                        "values": ["守信", "耐心"],
                        "address_user_as": "队长",
                    },
                },
            ),
            current_user={"user_id": owner},
        )
        reread = self.store.get_figure(saved["figure_id"], user_id=owner)
        prompt = self.persona_builder.build_persona_prompt(reread)

        self.assertIn("背景：在灯塔记录每一次归航。", prompt)
        self.assertIn("重视的事：守信、耐心", prompt)
        self.assertIn("对用户的称呼：队长", prompt)
        self.assertNotIn("背景：旧背景", prompt)

    def test_truthful_ai_disclosure_is_not_filtered_as_role_breaking(self):
        transparent_reply = "我是由 AI 驱动的灵偶阿澈，但我会继续用阿澈的方式陪你聊。"
        self.assertFalse(self.online_brain._detect_breaking_out(transparent_reply))
        provider = Mock(return_value=transparent_reply)
        with (
            patch.object(self.online_brain, "_is_configured", return_value=True),
            patch.object(self.online_brain, "_call_doubao", provider),
        ):
            result = self.online_brain.generate_online_reply(
                self._rich_figure(),
                "你是不是AI？",
            )
        self.assertEqual(result, transparent_reply)
        provider.assert_called_once()
        self.assertTrue(
            self.online_brain._detect_breaking_out(
                "我是 ChatGPT，请问有什么可以帮您？"
            )
        )
        offline_reply = self.offline_brain.generate_offline_reply(
            self._rich_figure(),
            "你是不是AI？",
        )
        self.assertIn("AI驱动的灵偶阿澈", offline_reply)

    def test_sync_streaming_and_bot_paths_build_identical_context(self):
        figure = self._rich_figure()
        history = [
            {"role": "user", "content": "昨天我要面试"},
            {"role": "assistant", "content": "我记得。"},
        ]
        captured: list[list[dict]] = []

        def sync_provider(messages, **_kwargs):
            captured.append(messages)
            return "今天准备得怎么样？"

        def sentence_stream(messages, **_kwargs):
            captured.append(messages)
            yield "今天准备得怎么样？"

        with (
            patch.object(self.online_brain, "_is_configured", return_value=True),
            patch.object(self.online_brain, "_call_doubao", side_effect=sync_provider),
        ):
            self.online_brain.generate_online_reply(
                figure,
                "我有点紧张",
                history,
                "用户今天要面试。",
            )
        with (
            patch.object(self.online_brain, "_is_configured", return_value=True),
            patch.object(
                self.online_brain,
                "_generate_sentence_stream",
                side_effect=sentence_stream,
            ),
        ):
            list(self.online_brain.generate_online_reply_streaming(
                figure,
                "我有点紧张",
                history,
                "用户今天要面试。",
            ))
        with (
            patch.object(self.online_brain, "_is_bot_configured", return_value=False),
            patch.object(
                self.online_brain,
                "_generate_sentence_stream",
                side_effect=sentence_stream,
            ),
        ):
            list(self.online_brain.generate_online_reply_streaming_with_bot(
                figure,
                "我有点紧张",
                history,
                "用户今天要面试。",
            ))

        self.assertEqual(len(captured), 3)
        self.assertEqual(captured[0], captured[1])
        self.assertEqual(captured[1], captured[2])
        self.assertIn("对用户的称呼：搭档", captured[0][0]["content"])

    def test_text_and_voice_turns_share_one_completion_path(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        base_id = f"BASE-{uuid.uuid4().hex}"
        figure_id = f"FIGURE-{uuid.uuid4().hex}"
        figure = self._rich_figure()
        figure["figure_id"] = figure_id
        figure["memory"] = {
            "interaction_count": 0,
            "relationship_points": 0,
            "relationship_level": "陌生",
            "favorite_responses": [],
            "first_met_at": datetime.now(timezone.utc).isoformat(),
        }
        now = datetime.now(timezone.utc).isoformat()
        self.store.save_figure(figure_id, figure, user_id=owner)
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

        def stream_reply(*_args, **_kwargs):
            yield "我记得，慢慢说。"
            return "online"

        def fake_speech(*_args, audio_sink=None, **_kwargs):
            if audio_sink:
                audio_sink(b"fixture-audio")
            return {
                "engine": "fixture",
                "audio_path": "fixture.mp3",
                "success": True,
                "synthesized": True,
                "transferred": bool(audio_sink),
            }

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
            patch.object(
                self.dialogue_engine,
                "_background_compress_history",
            ),
            patch.object(
                self.dialogue_engine,
                "is_weather_query",
                return_value=False,
            ),
            patch.object(
                self.dialogue_engine,
                "should_use_bot_search",
                return_value=False,
            ),
            patch.object(
                self.dialogue_engine,
                "extract_city",
                return_value=None,
            ),
        ):
            text_result = self.dialogue_engine.process_text_input(
                base_id,
                "文字入口",
                owner_user_id=owner,
            )
            voice_result = self.dialogue_engine.process_text_input(
                base_id,
                "语音入口",
                audio_sink=lambda _payload: True,
                owner_user_id=owner,
                session_id="VOICE-SESSION",
                turn_id="VOICE-TURN",
            )

        saved = self.store.get_figure(figure_id, user_id=owner)
        logs = self.store.list_dialogue_logs(user_id=owner, figure_id=figure_id)
        self.assertEqual(saved["memory"]["interaction_count"], 2)
        self.assertEqual(saved["memory"]["relationship_points"], 0)
        self.assertEqual(len(logs), 2)
        self.assertTrue(text_result["session_id"].startswith("session-"))
        self.assertTrue(text_result["turn_id"])
        self.assertEqual(voice_result["session_id"], "VOICE-SESSION")
        self.assertEqual(voice_result["turn_id"], "VOICE-TURN")
        self.assertEqual(
            {log["turn_id"] for log in logs},
            {text_result["turn_id"], "VOICE-TURN"},
        )
        self.reset_dialogue_state(base_id)

    def test_http_text_transport_does_not_apply_a_second_completion(self):
        owner = f"OWNER-{uuid.uuid4().hex}"
        base_id = f"BASE-{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        self.store.save_base(
            base_id,
            {
                "base_id": base_id,
                "active_figure_id": "FIGURE-TRANSPORT",
                "status": "bound",
                "created_at": now,
                "updated_at": now,
            },
            owner_user_id=owner,
        )
        process_result = {
            "reply": "共同入口已完成",
            "brain_mode": "online",
            "tts_engine": "fixture",
            "emotion_state": {},
            "figure_id": "FIGURE-TRANSPORT",
            "session_id": "TEXT-SESSION",
            "turn_id": "TEXT-TURN",
        }
        with (
            patch.object(
                self.dialogue_api,
                "process_text_input",
                return_value=process_result,
            ) as process,
            patch.object(
                self.dialogue_api,
                "save_figure",
                side_effect=AssertionError("transport must not persist again"),
            ),
        ):
            response = self.dialogue_api.dialogue_text(
                self.dialogue_api.TextRequest(base_id=base_id, text="你好"),
                current_user={"user_id": owner},
            )

        process.assert_called_once_with(
            base_id,
            "你好",
            brain_mode_override=None,
            owner_user_id=owner,
        )
        self.assertEqual(response["session_id"], "TEXT-SESSION")
        self.assertEqual(response["turn_id"], "TEXT-TURN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
