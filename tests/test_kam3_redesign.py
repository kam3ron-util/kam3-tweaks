import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import PCBoost as app


class RedesignAndCompatibilityTests(unittest.TestCase):
    def test_priority_safeguard_blocks_system_paths_and_critical_names(self):
        with patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}):
            self.assertTrue(app.protected_process("explorer.exe", r"C:\Windows\explorer.exe"))
            self.assertTrue(app.protected_process("svchost.exe", r"D:\Tools\svchost.exe"))
            self.assertTrue(app.protected_process("Kam3Tweaks.exe", r"D:\PCBoost\Kam3Tweaks.exe"))
            self.assertFalse(app.protected_process("game.exe", r"D:\Games\game.exe"))

    def test_gpu_probe_reads_identity_and_driver_only(self):
        expected = ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader,nounits"]
        with patch.object(app, "WIN", True), patch.object(app, "command", return_value=(0, "NVIDIA RTX test, 555.12", "")) as run:
            name, usage, temperature = app.gpu()
        self.assertEqual(name, "NVIDIA RTX test")
        self.assertIsNone(usage)
        self.assertIsNone(temperature)
        self.assertEqual(app._GPU_DETAILS.get("driver"), "555.12")
        self.assertEqual(run.call_args.args[0], expected)

    def test_gpu_unavailable_is_not_reported_as_zero(self):
        with patch.object(app, "WIN", True), patch.object(app, "command", return_value=(1, "", "nvidia-smi not found")):
            name, usage, temperature = app.gpu()
        self.assertIsNone(name)
        self.assertIsNone(usage)
        self.assertIsNone(temperature)
        self.assertIsNone(app._GPU_DETAILS.get("driver"))

    def test_monitoring_dashboard_and_polling_helpers_are_not_in_source_api(self):
        self.assertFalse(hasattr(app, "HistoryGraph"))
        self.assertFalse(hasattr(app, "PingSignals"))
        self.assertFalse(hasattr(app, "parse_ping_output"))
        self.assertFalse(hasattr(app, "ping_once"))
        self.assertFalse(hasattr(app, "game_candidates"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
