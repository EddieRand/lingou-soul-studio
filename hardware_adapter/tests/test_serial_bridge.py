import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from unittest.mock import Mock, patch

from hardware_adapter.event_protocol import HardwareEvent
from hardware_adapter import serial_bridge


class _Response:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self._payload


class _OneEventAdapter:
    def __init__(self, event: HardwareEvent):
        self.event = event
        self.started = False
        self.stopped = False

    def start_listening(self) -> None:
        self.started = True

    def get_current_event(self):
        if self.event is None:
            raise KeyboardInterrupt
        event = self.event
        self.event = None
        return event

    def stop_listening(self) -> None:
        self.stopped = True


class SerialBridgeTests(unittest.TestCase):
    def test_device_request_has_scoped_scheme_and_no_base_id(self):
        response = _Response({"ok": True})
        with patch.object(serial_bridge.urllib.request, "urlopen", return_value=response) as opened:
            result = serial_bridge.post_event(
                "http://localhost:8000/api/device/events",
                "light_touch",
                "BASE-DEV-001.fixture-device-credential",
            )

        self.assertEqual(result, {"ok": True})
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:8000/api/device/events")
        self.assertEqual(
            request.get_header("Authorization"),
            "Device BASE-DEV-001.fixture-device-credential",
        )
        payload = json.loads(request.data)
        self.assertEqual(payload["event_type"], "light_touch")
        self.assertNotIn("base_id", payload)
        self.assertTrue(payload["event_id"])
        self.assertIsNotNone(datetime.fromisoformat(payload["occurred_at"]).tzinfo)

    def test_non_dry_run_rejects_missing_inputs_before_adapter_construction(self):
        cases = (
            ([], "--base-id"),
            (["--base-id", "BASE-DEV-001"], "--device-credential"),
            (["--device-credential", "BASE-DEV-001.fixture"], "--base-id"),
        )
        for argv, expected in cases:
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                with (
                    patch.dict(os.environ, {}, clear=True),
                    patch.object(serial_bridge, "SerialHardwareAdapter") as adapter_factory,
                    redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as raised,
                ):
                    serial_bridge.main(argv)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(expected, stderr.getvalue())
                adapter_factory.assert_not_called()

    def test_non_dry_run_rejects_credential_for_another_base_before_open(self):
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(serial_bridge, "SerialHardwareAdapter") as adapter_factory,
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            serial_bridge.main(
                [
                    "--base-id",
                    "BASE-DEV-001",
                    "--device-credential",
                    "BASE-DEV-002.fixture-device-credential",
                ]
            )

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("does not belong to --base-id", stderr.getvalue())
        adapter_factory.assert_not_called()

    def test_dry_run_needs_no_base_credential_or_network(self):
        adapter = _OneEventAdapter(
            HardwareEvent(
                event_type="light_touch",
                base_id=serial_bridge.DRY_RUN_BASE_ID,
            )
        )
        adapter_factory = Mock(return_value=adapter)

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(serial_bridge, "SerialHardwareAdapter", adapter_factory),
            patch.object(serial_bridge, "post_event") as post_event,
            redirect_stdout(io.StringIO()),
        ):
            result = serial_bridge.main(["--dry-run", "--port", "fixture-port"])

        self.assertEqual(result, 0)
        self.assertTrue(adapter.started)
        self.assertTrue(adapter.stopped)
        post_event.assert_not_called()
        self.assertEqual(
            adapter_factory.call_args.kwargs["base_id"],
            serial_bridge.DRY_RUN_BASE_ID,
        )

    def test_real_run_uses_explicit_base_and_device_credential(self):
        adapter = _OneEventAdapter(
            HardwareEvent(event_type="double_tap", base_id="BASE-DEV-001")
        )
        adapter_factory = Mock(return_value=adapter)

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(serial_bridge, "SerialHardwareAdapter", adapter_factory),
            patch.object(serial_bridge, "post_event", return_value={}) as post_event,
            redirect_stdout(io.StringIO()),
        ):
            result = serial_bridge.main(
                [
                    "--base-id",
                    "BASE-DEV-001",
                    "--device-credential",
                    "BASE-DEV-001.fixture-device-credential",
                    "--port",
                    "fixture-port",
                ]
            )

        self.assertEqual(result, 0)
        self.assertTrue(adapter.started)
        self.assertTrue(adapter.stopped)
        post_event.assert_called_once_with(
            serial_bridge.DEFAULT_DEVICE_EVENT_ENDPOINT,
            "double_tap",
            "BASE-DEV-001.fixture-device-credential",
        )
        self.assertEqual(adapter_factory.call_args.kwargs["base_id"], "BASE-DEV-001")

    def test_real_run_accepts_device_credential_from_environment(self):
        adapter = _OneEventAdapter(
            HardwareEvent(event_type="figure_placed", base_id="BASE-DEV-001")
        )
        adapter_factory = Mock(return_value=adapter)
        credential = "BASE-DEV-001.fixture-env-credential"

        with (
            patch.dict(
                os.environ,
                {"LINGOU_DEVICE_CREDENTIAL": credential},
                clear=True,
            ),
            patch.object(serial_bridge, "SerialHardwareAdapter", adapter_factory),
            patch.object(serial_bridge, "post_event", return_value={}) as post_event,
            redirect_stdout(io.StringIO()),
        ):
            result = serial_bridge.main(["--base-id", "BASE-DEV-001"])

        self.assertEqual(result, 0)
        post_event.assert_called_once_with(
            serial_bridge.DEFAULT_DEVICE_EVENT_ENDPOINT,
            "figure_placed",
            credential,
        )


if __name__ == "__main__":
    unittest.main()
