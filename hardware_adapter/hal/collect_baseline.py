"""Write the EV-03 HAL contract baseline without claiming target measurements."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import glob
import json
from pathlib import Path

from hardware_adapter.hal.boards import DNESP32S3_PROFILE
from hardware_adapter.hal.fake import build_fake_hal
from hardware_adapter.hal.lifecycle import DeviceHALSupervisor
from hardware_adapter.hal.task_model import DEVICE_TASK_MODEL


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "docs"
    / "validation"
    / "ev03-hal-20260917"
    / "hal-baseline.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect the EV-03 fake HAL and target-availability baseline.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


async def collect() -> dict:
    fixture = build_fake_hal()
    supervisor = DeviceHALSupervisor(fixture.hal)
    await supervisor.start()
    try:
        snapshot = fixture.resources.snapshot()
    finally:
        await supervisor.stop()

    serial_ports = sorted(
        path
        for path in glob.glob("/dev/cu.*")
        if path not in {
            "/dev/cu.Bluetooth-Incoming-Port",
            "/dev/cu.debug-console",
        }
    )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "branch_intent": "feat/hardware-voice-adapter",
        "board_profile": asdict(DNESP32S3_PROFILE),
        "task_model": [
            {
                **asdict(spec),
                "role": spec.role.value,
                "overflow_policy": spec.overflow_policy.value,
            }
            for spec in DEVICE_TASK_MODEL
        ],
        "fake_hal": {
            "measurement_kind": "simulated_contract_fixture",
            "must_not_be_used_as_target_hardware_evidence": True,
            "resource_snapshot": asdict(snapshot),
            "lifecycle_audit": fixture.audit,
        },
        "target_hardware": {
            "connected": bool(serial_ports),
            "candidate_serial_ports": serial_ports,
            "measurement_kind": "not_measured",
            "free_heap_bytes": None,
            "minimum_free_heap_bytes": None,
            "free_psram_bytes": None,
            "stack_high_water_bytes": None,
            "cpu_percent_by_task": None,
            "blocked_reason": (
                None
                if serial_ports
                else "No target ESP32 serial device is connected."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(collect())
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "output": str(output),
        "target_connected": report["target_hardware"]["connected"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
