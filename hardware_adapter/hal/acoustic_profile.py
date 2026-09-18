"""Versioned EV-05 acoustic profile and host-side measurement helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable


ACOUSTIC_PROFILE_VERSION = "esp-sr-2.4.6-fd-lowcost-v1"
MICROPHONE_SAMPLE_RATE_HZ = 16000
PLAYBACK_SAMPLE_RATE_HZ = 24000
MICROPHONE_FRAME_SAMPLES = 320


@dataclass(frozen=True)
class AcousticProfile:
    profile_version: str = ACOUSTIC_PROFILE_VERSION
    provider: str = "espressif-esp-sr"
    provider_version: str = "2.4.6"
    aec_mode: str = "AEC_MODE_FD_LOW_COST"
    aec_filter_length: int = 4
    aec_nlp_level: str = "AEC_NLP_LEVEL_AGGR"
    reference_delay_ms: int = 60
    ns_mode: int = 1
    agc_mode: str = "AGC_MODE_2"
    agc_gain_db: int = 9
    agc_target_dbfs: int = 3
    microphone_gain_q8: int = 256
    clip_limit: int = 30000
    microphone_sample_rate_hz: int = MICROPHONE_SAMPLE_RATE_HZ
    playback_sample_rate_hz: int = PLAYBACK_SAMPLE_RATE_HZ

    def validate(self) -> None:
        if not self.profile_version:
            raise ValueError("profile_version must not be empty")
        if self.aec_mode != "AEC_MODE_FD_LOW_COST":
            raise ValueError("EV-05 requires the full-duplex low-cost AEC mode")
        if self.aec_filter_length <= 0:
            raise ValueError("aec_filter_length must be positive")
        if not 0 <= self.reference_delay_ms <= 200:
            raise ValueError("reference_delay_ms must be between 0 and 200")
        if self.ns_mode not in {0, 1, 2}:
            raise ValueError("ns_mode must be 0, 1 or 2")
        if not 0 <= self.agc_gain_db <= 30:
            raise ValueError("agc_gain_db must be between 0 and 30")
        if not 0 <= self.agc_target_dbfs <= 31:
            raise ValueError("agc_target_dbfs must be between 0 and 31")
        if not 1 <= self.microphone_gain_q8 <= 1024:
            raise ValueError("microphone_gain_q8 must be between 1 and 1024")
        if not 1000 <= self.clip_limit <= 32767:
            raise ValueError("clip_limit must be between 1000 and 32767")
        if self.microphone_sample_rate_hz != MICROPHONE_SAMPLE_RATE_HZ:
            raise ValueError("microphone sample rate must remain 16 kHz")
        if self.playback_sample_rate_hz != PLAYBACK_SAMPLE_RATE_HZ:
            raise ValueError("playback sample rate must remain 24 kHz")

    def as_dict(self) -> dict:
        self.validate()
        return asdict(self)


DEFAULT_ACOUSTIC_PROFILE = AcousticProfile()


class PlaybackReferenceResampler:
    """Stateful, deterministic 24 kHz to 16 kHz reference converter."""

    def __init__(self):
        self._pending: list[int] = []

    def reset(self) -> None:
        self._pending.clear()

    def process(self, samples: Iterable[int]) -> list[int]:
        output: list[int] = []
        for sample in samples:
            self._pending.append(int(sample))
            if len(self._pending) == 3:
                output.append(self._pending[0])
                output.append(int(
                    (self._pending[1] + self._pending[2]) / 2
                ))
                self._pending.clear()
        return output


def apply_gain_and_clip(
    samples: Iterable[int],
    *,
    gain_q8: int,
    clip_limit: int,
) -> tuple[list[int], int]:
    if not 1 <= gain_q8 <= 1024:
        raise ValueError("gain_q8 must be between 1 and 1024")
    if not 1000 <= clip_limit <= 32767:
        raise ValueError("clip_limit must be between 1000 and 32767")
    output: list[int] = []
    clipped = 0
    for sample in samples:
        value = int(sample) * gain_q8 // 256
        if value > clip_limit:
            value = clip_limit
            clipped += 1
        elif value < -clip_limit:
            value = -clip_limit
            clipped += 1
        output.append(value)
    return output, clipped


def pcm_metrics(samples: Iterable[int]) -> dict[str, float | int]:
    values = [int(sample) for sample in samples]
    if not values:
        raise ValueError("PCM samples must not be empty")
    square_mean = sum(value * value for value in values) / len(values)
    rms = math.sqrt(square_mean)
    peak = max(abs(value) for value in values)
    rms_dbfs = (
        20 * math.log10(rms / 32768)
        if rms
        else -120.0
    )
    peak_dbfs = (
        20 * math.log10(peak / 32768)
        if peak
        else -120.0
    )
    clipped = sum(abs(value) >= 32760 for value in values)
    return {
        "samples": len(values),
        "rms": round(rms, 3),
        "rms_dbfs": round(rms_dbfs, 3),
        "peak": peak,
        "peak_dbfs": round(peak_dbfs, 3),
        "clipped_samples": clipped,
        "clipped_ratio": round(clipped / len(values), 8),
    }


def character_error_rate(expected: str, observed: str) -> float:
    expected_chars = list("".join(expected.split()).lower())
    observed_chars = list("".join(observed.split()).lower())
    if not expected_chars:
        return 0.0 if not observed_chars else 1.0
    previous = list(range(len(observed_chars) + 1))
    for expected_index, expected_char in enumerate(expected_chars, start=1):
        current = [expected_index]
        for observed_index, observed_char in enumerate(
            observed_chars,
            start=1,
        ):
            current.append(min(
                current[-1] + 1,
                previous[observed_index] + 1,
                previous[observed_index - 1]
                + (expected_char != observed_char),
            ))
        previous = current
    return round(previous[-1] / len(expected_chars), 6)
