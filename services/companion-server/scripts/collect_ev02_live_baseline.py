"""Collect repeatable EV-02 live provider and acoustic timing samples."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any


SERVER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVER_ROOT.parents[1]
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "docs" / "validation" / "ev02-baseline-20260917"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect EV-02 direct-provider and live-acoustic samples.",
    )
    parser.add_argument("--confirm-live-providers", action="store_true")
    parser.add_argument("--confirm-audio-io", action="store_true")
    parser.add_argument("--direct-runs", type=int, default=3)
    parser.add_argument("--acoustic-runs", type=int, default=3)
    parser.add_argument("--input-device", default="0")
    parser.add_argument("--output-device", default="1")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--reaggregate-existing",
        action="store_true",
        help="Rebuild only the aggregate section from an existing output.",
    )
    return parser


def _last_json_object(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("probe produced no JSON result")


def _text_summary(value: str) -> dict[str, Any]:
    encoded = value.encode("utf-8")
    return {
        "characters": len(value),
        "utf8_bytes": len(encoded),
        "sha256_16": hashlib.sha256(encoded).hexdigest()[:16],
    }


def _sanitize_result(result: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(result)
    asr_text = str(result.get("asr_text") or "")
    reply_text = str(result.get("reply_text") or "")
    sanitized["asr_text"] = _text_summary(asr_text)
    sanitized["reply_text"] = _text_summary(reply_text)
    sanitized["semantic_checks"] = {
        "asr_contains_preference_question": (
            "喜欢" in asr_text and "颜色" in asr_text
        ),
        "reply_contains_confirmed_fact": "蓝色" in reply_text,
    }
    return sanitized


def _safe_failure_output(completed: subprocess.CompletedProcess[str]) -> dict:
    stderr_lines = completed.stderr.splitlines()[-20:]
    stdout_lines = [
        line
        for line in completed.stdout.splitlines()[-20:]
        if not any(
            marker in line.lower()
            for marker in ("credential", "token", '"asr_text"', '"reply_text"')
        )
    ]
    return {
        "returncode": completed.returncode,
        "stdout_tail": stdout_lines,
        "stderr_tail": stderr_lines,
    }


def _run_probe(
    *,
    kind: str,
    index: int,
    input_device: str,
    output_device: str,
) -> dict[str, Any]:
    if kind == "direct":
        command = [
            sys.executable,
            "-B",
            "scripts/verify_device_voice_live.py",
            "--confirm-live-providers",
        ]
    elif kind == "acoustic":
        command = [
            sys.executable,
            "-B",
            "scripts/verify_portable_carrier_live.py",
            "--confirm-live-providers",
            "--confirm-audio-io",
            "--input-device",
            input_device,
            "--output-device",
            output_device,
        ]
    else:
        raise ValueError(f"unknown probe kind: {kind}")

    started_at = datetime.now(timezone.utc).isoformat()
    completed = subprocess.run(
        command,
        cwd=SERVER_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    record = {
        "kind": kind,
        "sample": index,
        "started_at": started_at,
        "returncode": completed.returncode,
    }
    if completed.returncode != 0:
        return {**record, "passed": False, "failure": _safe_failure_output(completed)}
    try:
        result = _last_json_object(completed.stdout)
    except ValueError:
        return {**record, "passed": False, "failure": _safe_failure_output(completed)}
    return {
        **record,
        "passed": True,
        "result": _sanitize_result(result),
    }


def _nested_number(record: dict, path: tuple[str, ...]) -> float | None:
    value: Any = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _summary(
    records: list[dict[str, Any]],
    path: tuple[str, ...],
) -> dict[str, Any] | None:
    values = [
        value
        for record in records
        if record.get("passed")
        for value in [_nested_number(record, path)]
        if value is not None
    ]
    if not values:
        return None
    return {
        "samples": len(values),
        "min": round(min(values), 1),
        "median": round(statistics.median(values), 1),
        "max": round(max(values), 1),
    }


def _difference_summary(
    records: list[dict[str, Any]],
    later_path: tuple[str, ...],
    earlier_path: tuple[str, ...],
) -> dict[str, Any] | None:
    values = []
    for record in records:
        if not record.get("passed"):
            continue
        later = _nested_number(record, later_path)
        earlier = _nested_number(record, earlier_path)
        if later is not None and earlier is not None:
            values.append(later - earlier)
    if not values:
        return None
    return {
        "samples": len(values),
        "min": round(min(values), 1),
        "median": round(statistics.median(values), 1),
        "max": round(max(values), 1),
    }


def _observation_time(record: dict, event: str) -> float | None:
    observations = record.get("result", {}).get("client_observations", [])
    for item in observations:
        if item.get("event") == event:
            value = item.get("relative_to_prompt_ms")
            if isinstance(value, (int, float)):
                return float(value)
    return None


def _observation_summary(
    records: list[dict[str, Any]],
    event: str,
) -> dict[str, Any] | None:
    values = [
        value
        for record in records
        if record.get("passed")
        for value in [_observation_time(record, event)]
        if value is not None
    ]
    if not values:
        return None
    return {
        "samples": len(values),
        "min": round(min(values), 1),
        "median": round(statistics.median(values), 1),
        "max": round(max(values), 1),
    }


def _observation_difference_summary(
    records: list[dict[str, Any]],
    *,
    later_event: str,
    earlier_event: str,
) -> dict[str, Any] | None:
    values = []
    for record in records:
        if not record.get("passed"):
            continue
        later = _observation_time(record, later_event)
        earlier = _observation_time(record, earlier_event)
        if later is not None and earlier is not None:
            values.append(later - earlier)
    if not values:
        return None
    return {
        "samples": len(values),
        "min": round(min(values), 1),
        "median": round(statistics.median(values), 1),
        "max": round(max(values), 1),
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    direct = [record for record in records if record["kind"] == "direct"]
    acoustic = [record for record in records if record["kind"] == "acoustic"]
    server_fields = (
        "reply_started_ms",
        "first_text_ms",
        "first_audio_synthesized_ms",
        "first_audio_transferred_ms",
        "playback_started_ms",
        "playback_completed_ms",
        "reply_completed_ms",
    )
    client_fields = (
        "final_received_ms",
        "first_audio_received_ms",
        "reply_received_ms",
        "turn_metrics_received_ms",
    )
    acoustic_events = (
        "speech_finalized_received",
        "first_audio_received",
        "audio_output_started",
        "audio_output_completed",
        "turn_metrics_received",
    )
    return {
        "sample_note": (
            "Three-run baselines report min/median/max only; they are not "
            "P50/P95 production claims."
        ),
        "direct": {
            "requested": len(direct),
            "passed": sum(bool(record.get("passed")) for record in direct),
            "semantic_matches": sum(
                bool(
                    record.get("result", {})
                    .get("semantic_checks", {})
                    .get("asr_contains_preference_question")
                )
                for record in direct
            ),
            "server_timings_ms": {
                field: _summary(
                    direct,
                    ("result", "server_timings_ms", field),
                )
                for field in server_fields
            },
            "client_timings_ms": {
                field: _summary(
                    direct,
                    ("result", "client_timings_ms", field),
                )
                for field in client_fields
            },
            "derived_timings_ms": {
                "final_to_first_audio": _difference_summary(
                    direct,
                    ("result", "client_timings_ms", "first_audio_received_ms"),
                    ("result", "client_timings_ms", "final_received_ms"),
                ),
                "final_to_turn_complete": _difference_summary(
                    direct,
                    ("result", "client_timings_ms", "turn_metrics_received_ms"),
                    ("result", "client_timings_ms", "final_received_ms"),
                ),
            },
        },
        "acoustic": {
            "requested": len(acoustic),
            "passed": sum(bool(record.get("passed")) for record in acoustic),
            "semantic_matches": sum(
                bool(
                    record.get("result", {})
                    .get("semantic_checks", {})
                    .get("asr_contains_preference_question")
                )
                for record in acoustic
            ),
            "server_timings_ms": {
                field: _summary(
                    acoustic,
                    ("result", "server_timings_ms", field),
                )
                for field in server_fields
            },
            "relative_to_prompt_ms": {
                event: _observation_summary(acoustic, event)
                for event in acoustic_events
            },
            "derived_timings_ms": {
                "final_to_first_audio": _observation_difference_summary(
                    acoustic,
                    later_event="first_audio_received",
                    earlier_event="speech_finalized_received",
                )
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir.resolve()
    output_path = output_dir / "live-baseline.json"
    if args.reaggregate_existing:
        report = json.loads(output_path.read_text())
        for record in report.get("records", []):
            failure = record.get("failure")
            if isinstance(failure, dict):
                failure["stdout_tail"] = [
                    line
                    for line in failure.get("stdout_tail", [])
                    if "[DEBUG vol] CALLING API" not in line
                ]
            counters = record.get("result", {}).get("client_counters")
            if isinstance(counters, dict):
                counters.setdefault("input_overflows", None)
                counters.setdefault("input_queue_overflows", None)
                counters.setdefault("playback_underruns", None)
                counters.setdefault("playback_overflows", None)
        report["aggregate"] = _aggregate(report["records"])
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        print(json.dumps({"output": str(output_path), "reaggregated": True}))
        return 0
    if not args.confirm_live_providers or not args.confirm_audio_io:
        print(
            "Refusing without --confirm-live-providers and --confirm-audio-io"
        )
        return 2
    if args.direct_runs < 1 or args.acoustic_runs < 1:
        print("direct and acoustic run counts must both be positive")
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index in range(1, args.direct_runs + 1):
        record = _run_probe(
            kind="direct",
            index=index,
            input_device=args.input_device,
            output_device=args.output_device,
        )
        records.append(record)
        print(json.dumps({
            "kind": "direct",
            "sample": index,
            "passed": record["passed"],
        }))
    for index in range(1, args.acoustic_runs + 1):
        record = _run_probe(
            kind="acoustic",
            index=index,
            input_device=args.input_device,
            output_device=args.output_device,
        )
        records.append(record)
        print(json.dumps({
            "kind": "acoustic",
            "sample": index,
            "passed": record["passed"],
        }))

    report = {
        "run_id": output_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "transport": "websocket",
        "profile_id": "ws-pcm-s16le-v1",
        "input_device": args.input_device,
        "output_device": args.output_device,
        "records": records,
        "aggregate": _aggregate(records),
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    failures = [record for record in records if not record.get("passed")]
    print(json.dumps({
        "output": str(output_path),
        "samples": len(records),
        "failures": len(failures),
    }))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
