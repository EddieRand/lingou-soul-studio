from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from hardware_adapter.hal.boards import DNESP32S3_PROFILE
from hardware_adapter.hal.contracts import (
    IndicatorState,
    InputEvent,
    InputEventKind,
    MICROPHONE_FORMAT,
    NetworkState,
    SPEAKER_FORMAT,
)
from hardware_adapter.hal.fake import build_fake_hal
from hardware_adapter.hal.lifecycle import (
    DeviceHALSupervisor,
    HALShutdownError,
    HALStartupError,
)
from hardware_adapter.hal.portable_audio import HALAudioBackend
from hardware_adapter.hal.task_model import (
    DEVICE_TASK_MODEL,
    QueueOverflowPolicy,
    TaskRole,
    validate_task_model,
)
from hardware_adapter.portable_voice_client import PortableVoiceClient


class FakeWebSocket:
    def __init__(self):
        self.sent: list[str | bytes] = []

    async def send(self, payload) -> None:
        self.sent.append(payload)


class DeviceHALContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_lifecycle_uses_stable_reverse_shutdown_order(self):
        fixture = build_fake_hal()
        supervisor = DeviceHALSupervisor(fixture.hal)

        await supervisor.start()
        self.assertEqual(supervisor.started_components, (
            "secure_storage",
            "network",
            "microphone",
            "speaker",
            "inputs",
            "indicator",
            "resources",
        ))
        await supervisor.stop()

        self.assertEqual(fixture.audit, [
            "start:secure_storage",
            "start:network",
            "start:microphone",
            "start:speaker",
            "start:inputs",
            "start:indicator",
            "start:resources",
            "stop:resources",
            "stop:indicator",
            "stop:inputs",
            "stop:speaker",
            "stop:microphone",
            "stop:network",
            "stop:secure_storage",
        ])
        self.assertEqual(supervisor.started_components, ())

    async def test_partial_start_failure_rolls_back_started_components(self):
        fixture = build_fake_hal(fail_component="speaker")
        supervisor = DeviceHALSupervisor(fixture.hal)

        with self.assertRaises(HALStartupError) as raised:
            await supervisor.start()

        self.assertEqual(raised.exception.component, "speaker")
        self.assertEqual(raised.exception.rollback_failures, ())
        self.assertEqual(fixture.audit, [
            "start:secure_storage",
            "start:network",
            "start:microphone",
            "start:speaker",
            "stop:speaker",
            "stop:microphone",
            "stop:network",
            "stop:secure_storage",
        ])
        self.assertFalse(fixture.microphone.started)
        self.assertFalse(fixture.network.started)
        self.assertFalse(fixture.secure_storage.started)

    async def test_shutdown_reports_all_failures_after_attempting_every_stop(self):
        fixture = build_fake_hal()
        supervisor = DeviceHALSupervisor(fixture.hal)
        await supervisor.start()
        fixture.speaker.fail_on_stop = True
        fixture.network.fail_on_stop = True

        with self.assertRaises(HALShutdownError) as raised:
            await supervisor.stop()

        self.assertEqual(
            {failure.component for failure in raised.exception.failures},
            {"speaker", "network"},
        )
        self.assertEqual(supervisor.started_components, ())
        self.assertFalse(fixture.secure_storage.started)

    async def test_fake_ports_cover_io_network_indicator_and_secure_storage(self):
        fixture = build_fake_hal()
        async with DeviceHALSupervisor(fixture.hal):
            await fixture.network.connect()
            self.assertEqual(
                fixture.network.snapshot().state,
                NetworkState.ONLINE,
            )
            fixture.secure_storage.write_secret("device_identity", b"secret")
            self.assertEqual(
                fixture.secure_storage.read_secret("device_identity"),
                b"secret",
            )
            await fixture.indicator.set_state(IndicatorState.LISTENING)
            fixture.inputs.push_event(InputEvent(
                kind=InputEventKind.HEAVY_PRESS,
                monotonic_ms=fixture.clock.monotonic_ms(),
                raw_value=900,
            ))
            event = await asyncio.wait_for(
                fixture.inputs.next_event(),
                timeout=1,
            )
            self.assertEqual(event.kind, InputEventKind.HEAVY_PRESS)
            self.assertEqual(
                fixture.indicator.states,
                [IndicatorState.LISTENING],
            )

    async def test_hal_audio_backend_reuses_current_pcm_protocol_formats(self):
        fixture = build_fake_hal()
        backend = HALAudioBackend(fixture.hal)
        await backend.start()
        try:
            microphone_payload = b"\x01\x00" * (
                MICROPHONE_FORMAT.frame_bytes // 2
            )
            fixture.microphone.push_frame(microphone_payload)
            self.assertEqual(await backend.read_input(), microphone_payload)

            speaker_payload = b"\x02\x00" * 100
            await backend.play(speaker_payload)
            self.assertEqual(
                fixture.speaker.frames[-1].payload,
                speaker_payload,
            )
            await backend.stop_playback()
            self.assertEqual(fixture.speaker.abort_count, 1)
        finally:
            await backend.stop()

        self.assertEqual(MICROPHONE_FORMAT.frame_bytes, 640)
        self.assertEqual(SPEAKER_FORMAT.max_frame_bytes, 4096)

    async def test_fake_resource_snapshot_is_structured_and_not_hardware_proof(self):
        fixture = build_fake_hal()
        async with DeviceHALSupervisor(fixture.hal):
            snapshot = fixture.resources.snapshot()

        self.assertEqual(snapshot.source, "fake_hal_simulated")
        self.assertIsNotNone(snapshot.free_heap_bytes)
        self.assertIsNotNone(snapshot.free_psram_bytes)
        self.assertEqual(
            set(snapshot.stack_high_water_bytes),
            {spec.name for spec in DEVICE_TASK_MODEL},
        )
        self.assertEqual(
            set(snapshot.cpu_percent_by_task),
            {spec.name for spec in DEVICE_TASK_MODEL},
        )

    async def test_fake_hal_runs_existing_session_turn_audio_contract(self):
        fixture = build_fake_hal()
        backend = HALAudioBackend(fixture.hal)
        websocket = FakeWebSocket()
        client = PortableVoiceClient(
            server_url="ws://127.0.0.1:8000/api/asr/device-stream",
            device_credential="BASE-HAL." + ("x" * 43),
            audio=backend,
        )
        client.websocket = websocket
        client.session_id = "SESSION-HAL"
        await backend.start()
        try:
            await client._handle_server_message({
                "type": "speaking",
                "status": "start",
                "session_id": "SESSION-HAL",
                "turn_id": "TURN-HAL",
            })
            await client._handle_server_message({
                "type": "audio_chunk",
                "session_id": "SESSION-HAL",
                "turn_id": "TURN-HAL",
                "audio_id": "AUDIO-HAL",
                "chunk_index": 0,
                "chunk_count": 1,
                "chunk_byte_length": 4,
                "audio_format": "pcm",
                "sample_rate": 24000,
                "channels": 1,
                "sample_format": "s16le",
            })
            await client._handle_audio_frame(b"\x01\x00\x02\x00")
            await asyncio.wait_for(client._playback_queue.join(), timeout=1)
        finally:
            await client._reset_connection_state(report_failure=False)
            await backend.stop()

        receipts = [json.loads(item) for item in websocket.sent]
        self.assertEqual(
            [item["stage"] for item in receipts],
            ["decoded", "playback_started", "playback_completed"],
        )
        self.assertEqual(fixture.speaker.frames[0].payload, b"\x01\x00\x02\x00")
        self.assertTrue(all(
            item["session_id"] == "SESSION-HAL"
            and item["turn_id"] == "TURN-HAL"
            and item["audio_id"] == "AUDIO-HAL"
            for item in receipts
        ))

    def test_task_model_has_one_bounded_queue_per_runtime_role(self):
        validate_task_model()
        self.assertEqual(
            {spec.role for spec in DEVICE_TASK_MODEL},
            set(TaskRole),
        )
        self.assertTrue(
            all(spec.queue_capacity > 0 for spec in DEVICE_TASK_MODEL)
        )
        self.assertTrue(
            all(spec.stack_budget_bytes >= 2048 for spec in DEVICE_TASK_MODEL)
        )

    def test_audio_queue_budgets_match_ev04_firmware_policy(self):
        by_role = {spec.role: spec for spec in DEVICE_TASK_MODEL}
        capture = by_role[TaskRole.AUDIO_CAPTURE]
        playback = by_role[TaskRole.AUDIO_PLAYBACK]
        self.assertEqual(capture.queue_capacity, 12)
        self.assertEqual(capture.stack_budget_bytes, 8192)
        self.assertEqual(
            capture.overflow_policy,
            QueueOverflowPolicy.DROP_OLDEST,
        )
        self.assertEqual(playback.queue_capacity, 8)
        self.assertEqual(
            playback.overflow_policy,
            QueueOverflowPolicy.REJECT_NEW,
        )

    def test_board_pinout_matches_verified_reference_firmware(self):
        pinout = DNESP32S3_PROFILE.pinout
        self.assertEqual((
            pinout.led,
            pinout.fsr,
            pinout.microphone_bclk,
            pinout.microphone_ws,
            pinout.microphone_data_in,
            pinout.speaker_bclk,
            pinout.speaker_lrc,
            pinout.speaker_data_out,
        ), (18, 16, 5, 7, 4, 6, 15, 17))
        self.assertFalse(DNESP32S3_PROFILE.validated_aec)

    def test_fake_hal_matches_enabled_device_voice_contract(self):
        contract = json.loads(
            (
                PROJECT_ROOT
                / "docs"
                / "contracts"
                / "device-voice-v1.contract.json"
            ).read_text()
        )
        profile = contract["profiles"][
            contract["selection"]["legacy_profile_id"]
        ]
        self.assertEqual(profile["uplink"]["frame_bytes"], 640)
        self.assertEqual(
            profile["uplink"]["sample_rate_hz"],
            MICROPHONE_FORMAT.sample_rate_hz,
        )
        self.assertEqual(
            profile["downlink"]["sample_rate_hz"],
            SPEAKER_FORMAT.sample_rate_hz,
        )
        self.assertEqual(
            profile["downlink"]["max_frame_bytes"],
            SPEAKER_FORMAT.max_frame_bytes,
        )

    def test_generic_hal_has_no_server_core_or_gpio_dependencies(self):
        generic_files = (
            PROJECT_ROOT / "hardware_adapter" / "hal" / "acoustic_profile.py",
            PROJECT_ROOT / "hardware_adapter" / "hal" / "contracts.py",
            PROJECT_ROOT / "hardware_adapter" / "hal" / "lifecycle.py",
            PROJECT_ROOT / "hardware_adapter" / "hal" / "task_model.py",
            PROJECT_ROOT / "hardware_adapter" / "hal" / "portable_audio.py",
        )
        source = "\n".join(path.read_text() for path in generic_files)
        for forbidden in (
            "app.core",
            "data.store",
            "persona",
            "owner_user_id",
            "GPIO_NUM_",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
