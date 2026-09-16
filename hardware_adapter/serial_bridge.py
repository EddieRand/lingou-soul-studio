# hardware_adapter/serial_bridge.py
# Run a quiet bridge from ESP32 serial logs to the Lingou backend event API.

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

from hardware_adapter.serial_adapter import SerialHardwareAdapter


SUPPORTED_BACKEND_EVENTS = {
    "figure_placed",
    "light_touch",
    "heavy_press",
    "double_tap",
}

DEFAULT_DEVICE_EVENT_ENDPOINT = "http://localhost:8000/api/device/events"
DRY_RUN_BASE_ID = "DRY-RUN-UNASSIGNED"


def post_event(endpoint: str, event_type: str, device_credential: str) -> dict:
    """Post one uniquely identified event using the device authentication scheme."""
    credential = device_credential.strip()
    if not credential:
        raise ValueError("device_credential must be non-empty")

    payload = json.dumps({
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }).encode("utf-8")
    headers = {
        "Authorization": f"Device {credential}",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bridge ESP32 Lingou base events into the backend.")
    parser.add_argument("--port", default="/dev/cu.usbmodem101", help="ESP32 serial port")
    parser.add_argument("--baudrate", type=int, default=115200, help="ESP32 serial baudrate")
    parser.add_argument(
        "--base-id",
        help="Expected Lingou base id (required outside --dry-run; never sent as device authority)",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_DEVICE_EVENT_ENDPOINT,
        help="Development test-device event endpoint.",
    )
    parser.add_argument(
        "--device-credential",
        default=(
            os.getenv("LINGOU_DEVICE_CREDENTIAL")
            or os.getenv("LINGOU_TEST_DEVICE_CREDENTIAL", "")
        ),
        help=(
            "Provisioned or development device credential "
            "(defaults to LINGOU_DEVICE_CREDENTIAL, then the legacy "
            "LINGOU_TEST_DEVICE_CREDENTIAL)."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Print parsed events without POSTing")
    parser.add_argument("--emit-raw-knock", action="store_true", help="Also print raw KNOCK_EDGE events")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Fail before constructing the adapter or opening the serial port."""
    if args.dry_run:
        return

    missing = []
    if not args.base_id or not args.base_id.strip():
        missing.append("--base-id")
    if not args.device_credential or not args.device_credential.strip():
        missing.append(
            "--device-credential, LINGOU_DEVICE_CREDENTIAL, "
            "or LINGOU_TEST_DEVICE_CREDENTIAL"
        )
    if missing:
        parser.error("non-dry-run mode requires " + " and ".join(missing))

    base_id = args.base_id.strip()
    credential = args.device_credential.strip()
    credential_base_id, separator, secret = credential.partition(".")
    if not separator or not credential_base_id or not secret:
        parser.error("development device credential must use <base-id>.<secret> format")
    if credential_base_id != base_id:
        parser.error("development device credential does not belong to --base-id")

    args.base_id = base_id
    args.device_credential = credential


def run_bridge(args: argparse.Namespace, adapter_factory=None) -> int:
    if adapter_factory is None:
        adapter_factory = SerialHardwareAdapter

    local_base_id = (args.base_id or DRY_RUN_BASE_ID).strip()

    adapter = adapter_factory(
        port=args.port,
        baudrate=args.baudrate,
        base_id=local_base_id,
        emit_raw_knock=args.emit_raw_knock,
    )

    print(f"[bridge] opening {args.port} @ {args.baudrate}, base_id={local_base_id}")
    print(f"[bridge] endpoint={args.endpoint} dry_run={args.dry_run}")
    print("[bridge] press Ctrl+C to stop")

    try:
        adapter.start_listening()
        while True:
            event = adapter.get_current_event()
            if not event:
                time.sleep(0.02)
                continue

            data = event.to_dict()
            print(f"[event] {json.dumps(data, ensure_ascii=False)}")

            if event.event_type not in SUPPORTED_BACKEND_EVENTS:
                continue

            if args.dry_run:
                continue

            try:
                response = post_event(
                    args.endpoint,
                    event.event_type,
                    args.device_credential,
                )
                reply = response.get("reply", "")
                led_effect = response.get("led_effect")
                print(f"[backend] event={event.event_type} led_effect={led_effect} reply={reply}")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"[backend:error] {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[bridge] stopping")
    finally:
        adapter.stop_listening()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    return run_bridge(args)


if __name__ == "__main__":
    raise SystemExit(main())
