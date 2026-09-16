from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_DIR = PROJECT_ROOT / "hardware_adapter" / "service"


class PortableServiceContractTests(unittest.TestCase):
    def test_systemd_service_restarts_and_loads_protected_environment(self):
        source = (
            SERVICE_DIR / "lingou-portable-device.service.example"
        ).read_text()
        self.assertIn("EnvironmentFile=/etc/lingou/device.env", source)
        self.assertIn("Restart=always", source)
        self.assertIn("-m hardware_adapter.portable_voice_client", source)
        self.assertNotIn("BASE-DEVICE-001.", source)

    def test_launchd_service_runs_without_ide_or_browser(self):
        source = (
            SERVICE_DIR / "com.lingou.portable-device.plist.example"
        ).read_text()
        self.assertIn("RunAtLoad", source)
        self.assertIn("KeepAlive", source)
        self.assertIn("-m hardware_adapter.portable_voice_client", source)
        self.assertIn("$HOME/.config/lingou/device.env", source)
        self.assertNotIn("LINGOU_DEVICE_CREDENTIAL=", source)


if __name__ == "__main__":
    unittest.main()
