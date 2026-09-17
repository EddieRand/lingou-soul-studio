"""Measure speaker-to-microphone signal capture without storing raw audio."""

from __future__ import annotations

import argparse
import asyncio
from array import array
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys


SERVER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVER_ROOT.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from hardware_adapter.portable_voice_client import (  # noqa: E402
    INPUT_FRAME_SAMPLES,
    INPUT_SAMPLE_RATE,
    OUTPUT_SAMPLE_RATE,
    SoundDeviceAudioBackend,
)


DEFAULT_OUTPUT = (
    PROJECT_ROOT / "docs" / "validation" / "ev02-baseline-20260917"
)
TONE_FREQUENCY_HZ = 997
TONE_AMPLITUDE = 3000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect a low-volume acoustic loopback signal baseline.",
    )
    parser.add_argument("--confirm-audio-io", action="store_true")
    parser.add_argument("--input-device", default="0")
    parser.add_argument("--output-device", default="1")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser


def _device_argument(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def _samples(payloads: list[bytes]) -> array:
    result = array("h")
    for payload in payloads:
        result.frombytes(payload)
    if sys.byteorder != "little":
        result.byteswap()
    return result


def _signal_metrics(payloads: list[bytes]) -> dict:
    samples = _samples(payloads)
    if not samples:
        raise AssertionError("microphone produced no samples")
    square_sum = sum(float(value) * value for value in samples)
    rms = math.sqrt(square_sum / len(samples))
    cosine = 0.0
    sine = 0.0
    for index, value in enumerate(samples):
        phase = 2 * math.pi * TONE_FREQUENCY_HZ * index / INPUT_SAMPLE_RATE
        cosine += value * math.cos(phase)
        sine += value * math.sin(phase)
    component = 2 * math.sqrt(cosine * cosine + sine * sine) / len(samples)
    return {
        "frames": len(payloads),
        "samples": len(samples),
        "rms": round(rms, 2),
        "peak": max(abs(value) for value in samples),
        "tone_component": round(component, 2),
    }


def _tone_payload(duration_seconds: float = 1.0) -> bytes:
    samples = array("h")
    sample_count = round(OUTPUT_SAMPLE_RATE * duration_seconds)
    fade_samples = round(OUTPUT_SAMPLE_RATE * 0.02)
    for index in range(sample_count):
        envelope = min(
            1.0,
            index / max(1, fade_samples),
            (sample_count - index - 1) / max(1, fade_samples),
        )
        samples.append(round(
            TONE_AMPLITUDE
            * envelope
            * math.sin(2 * math.pi * TONE_FREQUENCY_HZ * index / OUTPUT_SAMPLE_RATE)
        ))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


async def _capture(audio: SoundDeviceAudioBackend, frames: int) -> list[bytes]:
    return [
        await asyncio.wait_for(audio.read_input(), timeout=2)
        for _ in range(frames)
    ]


async def _trial(
    *,
    input_device: str | int,
    output_device: str | int,
) -> dict:
    audio = SoundDeviceAudioBackend(
        input_device=input_device,
        output_device=output_device,
    )
    await audio.start()
    try:
        audio.discard_input_buffer()
        baseline = _signal_metrics(await _capture(audio, 50))
        audio.discard_input_buffer()
        capture_task = asyncio.create_task(_capture(audio, 60))
        await asyncio.sleep(0.05)
        await audio.play(_tone_payload())
        tone = _signal_metrics(await capture_task)
        audio_metrics = audio.metrics_snapshot()
    finally:
        await audio.stop()

    baseline_component = max(float(baseline["tone_component"]), 0.01)
    ratio = float(tone["tone_component"]) / baseline_component
    return {
        "baseline": baseline,
        "tone": tone,
        "audio_metrics": audio_metrics,
        "tone_component_ratio": round(ratio, 2),
        "tone_detected": (
            tone["tone_component"] >= 20
            and ratio >= 2.0
        ),
    }


async def _run(args: argparse.Namespace) -> dict:
    input_device = _device_argument(args.input_device)
    output_device = _device_argument(args.output_device)
    trials = [
        await _trial(
            input_device=input_device,
            output_device=output_device,
        )
        for _ in range(args.trials)
    ]
    ratios = [float(item["tone_component_ratio"]) for item in trials]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_device": args.input_device,
        "output_device": args.output_device,
        "input_sample_rate": INPUT_SAMPLE_RATE,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
        "tone_frequency_hz": TONE_FREQUENCY_HZ,
        "tone_amplitude": TONE_AMPLITUDE,
        "raw_audio_saved": False,
        "trials": trials,
        "summary": {
            "requested": args.trials,
            "tone_detected": sum(item["tone_detected"] for item in trials),
            "ratio_min": round(min(ratios), 2),
            "ratio_median": round(statistics.median(ratios), 2),
            "ratio_max": round(max(ratios), 2),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirm_audio_io:
        print("Refusing without --confirm-audio-io")
        return 2
    if args.trials < 1:
        print("--trials must be positive")
        return 2
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(_run(args))
    output_path = output_dir / "acoustic-io-baseline.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps({
        "output": str(output_path),
        "tone_detected": report["summary"]["tone_detected"],
        "trials": args.trials,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
