"""Archive controlled EV-05 WAV captures and calculate acceptance metrics."""

from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import wave


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from hardware_adapter.hal.acoustic_profile import (
    ACOUSTIC_PROFILE_VERSION,
    AcousticProfile,
    character_error_rate,
    pcm_metrics,
)


SCENARIO_THRESHOLDS = {
    "silence": {
        "maximum_processed_rms_dbfs": -45.0,
        "maximum_clipped_ratio": 0.001,
    },
    "near_speech": {
        "minimum_processed_rms_dbfs": -30.0,
        "maximum_processed_rms_dbfs": -8.0,
        "maximum_clipped_ratio": 0.001,
        "maximum_character_error_rate": 0.10,
    },
    "far_speech": {
        "minimum_processed_rms_dbfs": -36.0,
        "maximum_processed_rms_dbfs": -8.0,
        "maximum_clipped_ratio": 0.001,
        "maximum_character_error_rate": 0.20,
    },
    "stationary_noise": {
        "minimum_attenuation_db": 6.0,
        "maximum_clipped_ratio": 0.001,
    },
    "echo_only": {
        "minimum_attenuation_db": 12.0,
        "maximum_clipped_ratio": 0.001,
    },
    "double_talk": {
        "maximum_clipped_ratio": 0.001,
        "maximum_character_error_rate": 0.15,
    },
}


def _read_pcm16_mono(path: Path) -> tuple[list[int], dict]:
    with wave.open(str(path), "rb") as wav:
        metadata = {
            "channels": wav.getnchannels(),
            "sample_width_bytes": wav.getsampwidth(),
            "sample_rate_hz": wav.getframerate(),
            "frame_count": wav.getnframes(),
        }
        if metadata["channels"] != 1:
            raise ValueError(f"{path}: expected mono WAV")
        if metadata["sample_width_bytes"] != 2:
            raise ValueError(f"{path}: expected signed 16-bit WAV")
        if metadata["sample_rate_hz"] != 16000:
            raise ValueError(f"{path}: expected 16 kHz WAV")
        payload = wav.readframes(metadata["frame_count"])
    samples = array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise ValueError(f"{path}: WAV contains no samples")
    metadata["duration_seconds"] = round(len(samples) / 16000, 3)
    return list(samples), metadata


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_wav(source: Path, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    samples, metadata = _read_pcm16_mono(destination)
    return {
        "file": destination.name,
        "sha256": _sha256(destination),
        "format": metadata,
        "metrics": pcm_metrics(samples),
    }


def _evaluate(
    scenario: str,
    raw_metrics: dict,
    processed_metrics: dict,
    *,
    expected_text: str,
    observed_text: str,
) -> tuple[dict, bool]:
    thresholds = SCENARIO_THRESHOLDS[scenario]
    measurements = {
        "attenuation_db": round(
            raw_metrics["rms_dbfs"] - processed_metrics["rms_dbfs"],
            3,
        ),
        "processed_rms_dbfs": processed_metrics["rms_dbfs"],
        "processed_clipped_ratio": processed_metrics["clipped_ratio"],
    }
    checks: dict[str, bool] = {
        "clipping": (
            measurements["processed_clipped_ratio"]
            <= thresholds["maximum_clipped_ratio"]
        ),
    }
    if "minimum_attenuation_db" in thresholds:
        checks["attenuation"] = (
            measurements["attenuation_db"]
            >= thresholds["minimum_attenuation_db"]
        )
    if "minimum_processed_rms_dbfs" in thresholds:
        checks["minimum_level"] = (
            measurements["processed_rms_dbfs"]
            >= thresholds["minimum_processed_rms_dbfs"]
        )
    if "maximum_processed_rms_dbfs" in thresholds:
        checks["maximum_level"] = (
            measurements["processed_rms_dbfs"]
            <= thresholds["maximum_processed_rms_dbfs"]
        )
    if "maximum_character_error_rate" in thresholds:
        if not expected_text or not observed_text:
            raise ValueError(
                f"{scenario} requires --expected-text and --observed-text"
            )
        measurements["character_error_rate"] = character_error_rate(
            expected_text,
            observed_text,
        )
        checks["recognition"] = (
            measurements["character_error_rate"]
            <= thresholds["maximum_character_error_rate"]
        )
    return {
        "thresholds": thresholds,
        "measurements": measurements,
        "checks": checks,
    }, all(checks.values())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Archive target-board raw/processed WAVs and calculate EV-05 "
            "metrics without modifying the recordings."
        )
    )
    parser.add_argument(
        "--scenario",
        required=True,
        choices=tuple(SCENARIO_THRESHOLDS),
    )
    parser.add_argument("--raw-wav", type=Path, required=True)
    parser.add_argument("--processed-wav", type=Path, required=True)
    parser.add_argument("--reference-wav", type=Path)
    parser.add_argument("--expected-text", default="")
    parser.add_argument("--observed-text", default="")
    parser.add_argument("--hardware-id", required=True)
    parser.add_argument("--firmware-commit", required=True)
    parser.add_argument(
        "--profile-version",
        default=ACOUSTIC_PROFILE_VERSION,
    )
    parser.add_argument("--reference-delay-ms", type=int, default=60)
    parser.add_argument("--microphone-gain-q8", type=int, default=256)
    parser.add_argument("--clip-limit", type=int, default=30000)
    parser.add_argument("--ns-mode", type=int, default=1)
    parser.add_argument("--agc-gain-db", type=int, default=9)
    parser.add_argument("--agc-target-dbfs", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--confirm-target-capture",
        action="store_true",
        help="Confirm the files came from the stated physical target.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.confirm_target_capture:
        raise SystemExit(
            "--confirm-target-capture is required for EV-05 evidence"
        )
    acoustic_profile = AcousticProfile(
        profile_version=args.profile_version,
        reference_delay_ms=args.reference_delay_ms,
        microphone_gain_q8=args.microphone_gain_q8,
        clip_limit=args.clip_limit,
        ns_mode=args.ns_mode,
        agc_gain_db=args.agc_gain_db,
        agc_target_dbfs=args.agc_target_dbfs,
    )
    acoustic_profile.validate()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = _archive_wav(
        args.raw_wav,
        args.output_dir / f"{args.scenario}-raw.wav",
    )
    processed = _archive_wav(
        args.processed_wav,
        args.output_dir / f"{args.scenario}-processed.wav",
    )
    reference = None
    if args.reference_wav:
        reference = _archive_wav(
            args.reference_wav,
            args.output_dir / f"{args.scenario}-reference.wav",
        )
    evaluation, passed = _evaluate(
        args.scenario,
        raw["metrics"],
        processed["metrics"],
        expected_text=args.expected_text,
        observed_text=args.observed_text,
    )
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target_capture_confirmed": True,
        "hardware_id": args.hardware_id,
        "firmware_commit": args.firmware_commit,
        "acoustic_profile": acoustic_profile.as_dict(),
        "scenario": args.scenario,
        "raw": raw,
        "processed": processed,
        "reference": reference,
        "evaluation": evaluation,
        "passed": passed,
    }
    report_path = args.output_dir / f"{args.scenario}-result.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(report_path)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
