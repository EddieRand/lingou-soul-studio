from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    PROJECT_ROOT
    / "docs"
    / "contracts"
    / "device-voice-v1.contract.json"
)
PORTABLE_CLIENT = PROJECT_ROOT / "hardware_adapter" / "portable_voice_client.py"
SERVER = (
    PROJECT_ROOT
    / "services"
    / "companion-server"
    / "app"
    / "api"
    / "asr.py"
)
FIRMWARE = (
    PROJECT_ROOT
    / "firmware"
    / "lingou_device_v1"
    / "lingou_device_v1.ino"
)


class ProtocolDesignError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _contains_forbidden_field(value, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            key.lower() in forbidden
            or _contains_forbidden_field(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_field(item, forbidden) for item in value)
    return False


def _reference_negotiate(
    contract: dict,
    hello,
    *,
    locked_profile: str | None = None,
) -> dict:
    """Executable form of the EV-01 design, not production negotiation."""
    selection = contract["selection"]
    negotiation = contract["negotiation"]
    if hello is None:
        return {
            "status": "selected",
            "mode": "legacy",
            "profile_id": selection["legacy_profile_id"],
        }
    if locked_profile is not None:
        return {
            "status": "rejected",
            "code": "NEGOTIATION_LOCKED",
            "profile_id": locked_profile,
        }
    if not isinstance(hello, dict):
        raise ProtocolDesignError("INVALID_CAPABILITIES")

    forbidden = {
        field.lower()
        for field in contract["identity"]["forbidden_device_hello_fields"]
    }
    if _contains_forbidden_field(hello, forbidden):
        raise ProtocolDesignError("IDENTITY_FIELD_FORBIDDEN")

    offered = hello.get("offered_profile_ids")
    valid = (
        hello.get("type") == negotiation["hello_type"]
        and hello.get("protocol") == contract["subprotocol"]
        and hello.get("capabilities_version") == 1
        and isinstance(offered, list)
        and 0 < len(offered) <= 8
        and all(isinstance(item, str) and 0 < len(item) <= 64 for item in offered)
        and len(offered) == len(set(offered))
    )
    if not valid:
        raise ProtocolDesignError("INVALID_CAPABILITIES")

    enabled = set(selection["enabled_profile_ids"])
    for profile_id in selection["server_preference"]:
        if profile_id in enabled and profile_id in offered:
            return {
                "status": "selected",
                "mode": "negotiated",
                "profile_id": profile_id,
            }
    raise ProtocolDesignError(selection["no_common_profile_error"])


class DeviceVoiceProtocolDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text())
        cls.portable_source = PORTABLE_CLIENT.read_text()
        cls.server_source = SERVER.read_text()
        cls.firmware_source = FIRMWARE.read_text()

    def _evaluate_example(self, example: dict) -> dict:
        try:
            result = _reference_negotiate(
                self.contract,
                example.get("hello"),
            )
        except ProtocolDesignError as exc:
            result = {
                "status": "rejected",
                "code": exc.code,
                "close_code": self.contract["selection"][
                    "incompatible_close_code"
                ],
            }
        return result

    def test_contract_identifiers_match_all_current_runtimes(self):
        protocol = self.contract["subprotocol"]
        endpoint = self.contract["endpoint"]
        self.assertIn(f'DEVICE_PROTOCOL = "{protocol}"', self.portable_source)
        self.assertIn(
            f'DEVICE_WS_PROTOCOL = "{protocol}"',
            self.server_source,
        )
        self.assertIn(f'"{protocol}"', self.firmware_source)
        self.assertIn(endpoint, self.portable_source)
        self.assertIn(endpoint, self.firmware_source)
        self.assertIn('@router.websocket("/device-stream")', self.server_source)

    def test_legacy_profile_matches_current_pcm_constants(self):
        profile = self.contract["profiles"][
            self.contract["selection"]["legacy_profile_id"]
        ]
        self.assertEqual(profile["state"], "enabled")
        self.assertEqual(profile["uplink"], {
            "codec": "pcm_s16le",
            "sample_rate_hz": 16000,
            "channels": 1,
            "frame_duration_ms": 20,
            "frame_bytes": 640,
        })
        self.assertEqual(profile["downlink"], {
            "codec": "pcm_s16le",
            "sample_rate_hz": 24000,
            "channels": 1,
            "max_frame_bytes": 4096,
        })
        expected_constants = (
            "INPUT_SAMPLE_RATE = 16000",
            "OUTPUT_SAMPLE_RATE = 24000",
            "INPUT_FRAME_BYTES = INPUT_FRAME_SAMPLES * SAMPLE_WIDTH_BYTES",
            "MAX_OUTPUT_FRAME_BYTES = 4096",
        )
        for constant in expected_constants:
            self.assertIn(constant, self.portable_source)
        self.assertRegex(
            self.server_source,
            r'DEVICE_AUDIO_FORMAT\s*=\s*"pcm"',
        )
        self.assertRegex(
            self.server_source,
            r"DEVICE_AUDIO_SAMPLE_RATE\s*=\s*24000",
        )
        self.assertRegex(
            self.server_source,
            r"DEVICE_AUDIO_FRAME_BYTES\s*=\s*4096",
        )

    def test_only_pcm_is_enabled_until_later_tasks_pass(self):
        enabled = set(self.contract["selection"]["enabled_profile_ids"])
        self.assertEqual(enabled, {"ws-pcm-s16le-v1"})
        self.assertEqual(
            {
                profile_id
                for profile_id, profile in self.contract["profiles"].items()
                if profile["state"] == "enabled"
            },
            enabled,
        )
        self.assertEqual(
            self.contract["profiles"]["ws-opus-v1"]["state"],
            "planned",
        )
        self.assertEqual(
            self.contract["profiles"]["rtc-lite-v1"]["state"],
            "experimental",
        )

    def test_negotiation_examples_are_deterministic(self):
        for example in self.contract["examples"]:
            with self.subTest(example=example["name"]):
                self.assertEqual(
                    self._evaluate_example(example),
                    example["expected"],
                )

    def test_malformed_hello_variants_are_rejected(self):
        base = {
            "type": "device_hello",
            "protocol": self.contract["subprotocol"],
            "capabilities_version": 1,
            "offered_profile_ids": ["ws-pcm-s16le-v1"],
        }
        invalid = (
            [],
            {**base, "type": "wrong"},
            {**base, "protocol": "lingou.device.voice.v2"},
            {**base, "capabilities_version": 2},
            {**base, "offered_profile_ids": []},
            {**base, "offered_profile_ids": ["ws-pcm-s16le-v1"] * 2},
            {**base, "offered_profile_ids": list(map(str, range(9)))},
            {**base, "offered_profile_ids": [7]},
        )
        for hello in invalid:
            with self.subTest(hello=hello):
                with self.assertRaisesRegex(
                    ProtocolDesignError,
                    "INVALID_CAPABILITIES",
                ):
                    _reference_negotiate(self.contract, hello)

    def test_identity_injection_is_rejected_at_any_depth(self):
        base = {
            "type": "device_hello",
            "protocol": self.contract["subprotocol"],
            "capabilities_version": 1,
            "offered_profile_ids": ["ws-pcm-s16le-v1"],
        }
        for field in self.contract["identity"]["server_owned_fields"]:
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    ProtocolDesignError,
                    "IDENTITY_FIELD_FORBIDDEN",
                ):
                    _reference_negotiate(
                        self.contract,
                        {**base, "metadata": {field: "forged"}},
                    )

    def test_late_hello_keeps_locked_legacy_profile(self):
        legacy = self.contract["selection"]["legacy_profile_id"]
        result = _reference_negotiate(
            self.contract,
            {
                "type": "device_hello",
                "protocol": self.contract["subprotocol"],
                "capabilities_version": 1,
                "offered_profile_ids": ["ws-opus-v1", legacy],
            },
            locked_profile=legacy,
        )
        self.assertEqual(result, {
            "status": "rejected",
            "code": "NEGOTIATION_LOCKED",
            "profile_id": legacy,
        })

    def test_every_connection_requires_fresh_server_owned_configuration(self):
        negotiation = self.contract["negotiation"]
        self.assertTrue(negotiation["requires_hello_each_connection"])
        self.assertEqual(
            negotiation["configuration_scope"],
            "websocket_connection",
        )
        self.assertEqual(
            self.contract["identity"]["authority"],
            "authorization_header",
        )
        self.assertIn(
            "session_id",
            self.contract["identity"]["server_owned_fields"],
        )

    def test_rtc_mapping_cannot_replace_application_identifiers(self):
        mapping = self.contract["rtc_mapping"]
        self.assertEqual(mapping["authority"], "lingou_application_server")
        self.assertEqual(
            mapping["round_id"],
            "mapped_to_server_allocated_turn_id",
        )
        self.assertEqual(mapping["voice_interrupt"], "cancel_turn")
        self.assertEqual(mapping["playout_confirmation"], "audio_playback")

    def test_measurement_contract_uses_ids_without_sensitive_content(self):
        measurements = self.contract["measurements"]
        self.assertEqual(
            measurements["correlation_fields"],
            ["session_id", "turn_id", "audio_id"],
        )
        self.assertIn("speech_finalized", measurements["server_turn_marks"])
        self.assertIn("playback_completed", measurements["server_turn_marks"])
        self.assertIn("audio_output_stopped", measurements["device_local_marks"])
        self.assertIn("playback_underruns", measurements["device_counters"])
        self.assertIn(
            "device_credential",
            measurements["forbidden_content_fields"],
        )
        self.assertNotIn(
            "user_input_text",
            measurements["correlation_fields"],
        )

    def test_incompatible_close_code_does_not_overlap_existing_codes(self):
        close_code = self.contract["selection"]["incompatible_close_code"]
        self.assertEqual(close_code, 4406)
        existing_codes = {
            int(value)
            for value in re.findall(r"\b44(?:01|03|04|09|10)\b", (
                self.server_source + self.portable_source
            ))
        }
        self.assertNotIn(close_code, existing_codes)


if __name__ == "__main__":
    unittest.main()
