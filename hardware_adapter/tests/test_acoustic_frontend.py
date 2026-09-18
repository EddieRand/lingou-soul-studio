from __future__ import annotations

from array import array
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from hardware_adapter.hal.acoustic_profile import (
    ACOUSTIC_PROFILE_VERSION,
    DEFAULT_ACOUSTIC_PROFILE,
    PlaybackReferenceResampler,
    apply_gain_and_clip,
    character_error_rate,
    pcm_metrics,
)


FIRMWARE = (
    PROJECT_ROOT
    / "firmware"
    / "lingou_device_v1"
    / "lingou_device_v1.ino"
)
ACOUSTIC_HEADER = (
    FIRMWARE.parent
    / "hal"
    / "esp_sr_acoustic_frontend.h"
)
CONFIG_EXAMPLE = FIRMWARE.with_name("device_config.example.h")
BOARD_PROFILE = FIRMWARE.parent / "hal" / "dnesp32s3_board_profile.h"
COLLECTOR = (
    PROJECT_ROOT
    / "services"
    / "companion-server"
    / "scripts"
    / "collect_ev05_acoustic_baseline.py"
)


class AcousticFrontendTests(unittest.TestCase):
    def test_profile_is_versioned_and_bounded(self):
        profile = DEFAULT_ACOUSTIC_PROFILE
        profile.validate()
        self.assertEqual(
            profile.profile_version,
            ACOUSTIC_PROFILE_VERSION,
        )
        self.assertEqual(profile.aec_mode, "AEC_MODE_FD_LOW_COST")
        self.assertEqual(profile.aec_filter_length, 4)
        self.assertEqual(profile.reference_delay_ms, 60)
        self.assertEqual(profile.ns_mode, 1)
        self.assertEqual(profile.agc_mode, "AGC_MODE_2")
        self.assertEqual(profile.clip_limit, 30000)

    def test_reference_resampler_is_exact_across_chunk_boundaries(self):
        samples = list(range(-120, 120))
        whole = PlaybackReferenceResampler().process(samples)
        chunked_resampler = PlaybackReferenceResampler()
        chunked = []
        for offset in range(0, len(samples), 17):
            chunked.extend(
                chunked_resampler.process(samples[offset:offset + 17])
            )

        self.assertEqual(chunked, whole)
        self.assertEqual(len(whole), len(samples) * 2 // 3)
        self.assertEqual(whole[:4], [-120, -118, -117, -115])

    def test_gain_and_clip_counts_saturated_samples(self):
        output, clipped = apply_gain_and_clip(
            [-20000, -1000, 1000, 20000],
            gain_q8=512,
            clip_limit=30000,
        )
        self.assertEqual(output, [-30000, -2000, 2000, 30000])
        self.assertEqual(clipped, 2)
        metrics = pcm_metrics(output)
        self.assertEqual(metrics["clipped_samples"], 0)

    def test_firmware_selects_esp_sr_and_keeps_aec_opt_in(self):
        source = FIRMWARE.read_text()
        header = ACOUSTIC_HEADER.read_text()
        config = CONFIG_EXAMPLE.read_text()
        board = BOARD_PROFILE.read_text()

        self.assertIn("aec_create_from_config", header)
        self.assertIn("AEC_MODE_FD_LOW_COST", header)
        self.assertIn("AEC_NLP_LEVEL_AGGR", header)
        self.assertIn("ns_pro_create", header)
        self.assertIn("AGC_MODE_2", header)
        self.assertGreaterEqual(header.count("alignas(16) int16_t aec_"), 3)
        self.assertIn('"esp-sr-2.4.6-fd-lowcost-v1"', header)
        self.assertIn("#define LINGOU_AEC_REFERENCE_DELAY_MS 60", header)
        self.assertIn("#define LINGOU_MIC_DIGITAL_GAIN_Q8 256", header)
        self.assertIn("#define LINGOU_MIC_CLIP_LIMIT 30000", header)
        self.assertIn("heap_caps_get_total_size(MALLOC_CAP_SPIRAM)", header)
        self.assertIn("generation != reference_generation_", header)
        self.assertIn("if (reference_delay_pending_)", header)
        self.assertIn("PushPlayback24k", source)
        self.assertIn(
            "(serverSpeaking && !acousticFrontend.Active())",
            source,
        )
        self.assertIn("#define LINGOU_ENABLE_ESP_SR_AFE 0", config)
        self.assertIn(
            "inline constexpr bool VALIDATED_AEC = false;",
            board,
        )

    def test_collector_archives_real_inputs_and_evaluates_echo_threshold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw.wav"
            processed = root / "processed.wav"
            output = root / "evidence"
            self._write_tone(raw, amplitude=12000)
            self._write_tone(processed, amplitude=2000)

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(COLLECTOR),
                    "--scenario",
                    "echo_only",
                    "--raw-wav",
                    str(raw),
                    "--processed-wav",
                    str(processed),
                    "--hardware-id",
                    "fixture-board",
                    "--firmware-commit",
                    "fixture-commit",
                    "--output-dir",
                    str(output),
                    "--confirm-target-capture",
                ],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(
                (output / "echo_only-result.json").read_text()
            )
            self.assertTrue(report["passed"])
            self.assertGreaterEqual(
                report["evaluation"]["measurements"]["attenuation_db"],
                12.0,
            )
            self.assertEqual(
                report["acoustic_profile"]["profile_version"],
                ACOUSTIC_PROFILE_VERSION,
            )
            self.assertTrue((output / "echo_only-raw.wav").is_file())
            self.assertTrue((output / "echo_only-processed.wav").is_file())

    def test_character_error_rate_supports_chinese_without_word_splitting(self):
        self.assertEqual(character_error_rate("你好 灵偶", "你好灵偶"), 0.0)
        self.assertEqual(character_error_rate("你好灵偶", "你好朋友"), 0.5)

    @staticmethod
    def _write_tone(path: Path, *, amplitude: int) -> None:
        samples = array(
            "h",
            (
                round(amplitude * math.sin(2 * math.pi * 997 * i / 16000))
                for i in range(16000)
            ),
        )
        if sys.byteorder != "little":
            samples.byteswap()
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(samples.tobytes())


if __name__ == "__main__":
    unittest.main()
