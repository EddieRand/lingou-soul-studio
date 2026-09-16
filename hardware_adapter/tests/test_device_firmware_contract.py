from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = (
    PROJECT_ROOT
    / "firmware"
    / "lingou_device_v1"
    / "lingou_device_v1.ino"
)
CONFIG_EXAMPLE = FIRMWARE.with_name("device_config.example.h")


class DeviceFirmwareContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FIRMWARE.read_text()
        cls.config = CONFIG_EXAMPLE.read_text()

    def test_verified_hardware_pins_are_fixed(self):
        expected = {
            "LED_PIN": "GPIO_NUM_18",
            "FSR_PIN": "GPIO_NUM_16",
            "MIC_BCLK_PIN": "GPIO_NUM_5",
            "MIC_WS_PIN": "GPIO_NUM_7",
            "MIC_DIN_PIN": "GPIO_NUM_4",
            "SPK_BCLK_PIN": "GPIO_NUM_6",
            "SPK_LRC_PIN": "GPIO_NUM_15",
            "SPK_DOUT_PIN": "GPIO_NUM_17",
        }
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertRegex(
                    self.source,
                    rf"constexpr gpio_num_t {name} = {value};",
                )

    def test_startup_has_the_required_three_red_flashes(self):
        body = re.search(
            r"void showBootVersionSignal\(\) \{(?P<body>.*?)\n\}",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(body)
        self.assertIn("index < 3", body.group("body"))
        self.assertIn("setRing(48, 0, 0)", body.group("body"))
        self.assertIn("showBootVersionSignal();", self.source)

    def test_voice_transport_uses_scoped_device_auth_and_pcm_contract(self):
        self.assertIn('/api/asr/device-stream', self.source)
        self.assertIn('"lingou.device.voice.v1"', self.source)
        self.assertIn('"Authorization: Device "', self.source)
        self.assertIn("constexpr int MIC_SAMPLE_RATE = 16000;", self.source)
        self.assertIn("constexpr int SPEAKER_SAMPLE_RATE = 24000;", self.source)
        self.assertIn('"audio_playback"', self.source)
        self.assertIn('"cancel_turn"', self.source)

    def test_idle_output_is_zeroed_and_playback_mutes_microphone(self):
        self.assertIn("i2s_zero_dma_buffer(SPK_I2S_PORT)", self.source)
        self.assertIn(
            "if (!socketConnected || serverSpeaking || samples == 0)",
            self.source,
        )

    def test_disconnect_has_local_feedback_and_bounded_reconnect(self):
        self.assertIn("localServiceAlert();", self.source)
        self.assertIn("webSocket.setReconnectInterval(3000);", self.source)
        self.assertIn("webSocket.enableHeartbeat(15000, 3000, 2);", self.source)
        self.assertIn("connectWiFi();", self.source)
        self.assertIn("if (WiFi.status() != WL_CONNECTED)", self.source)
        self.assertIn("pausedForReplacement = true;", self.source)
        self.assertIn("if (pausedForReplacement)", self.source)

    def test_secrets_live_in_ignored_device_config(self):
        gitignore = (PROJECT_ROOT / ".gitignore").read_text()
        self.assertIn(
            "firmware/lingou_device_v1/device_config.h",
            gitignore,
        )
        self.assertIn("your-wifi-ssid", self.config)
        self.assertNotIn("base-619", self.source)
        self.assertNotIn("base0619", self.source)
        self.assertNotRegex(
            self.source,
            r'LINGOU_DEVICE_CREDENTIAL\s+"BASE-[^"]+\.[A-Za-z0-9_-]{32,}"',
        )


if __name__ == "__main__":
    unittest.main()
