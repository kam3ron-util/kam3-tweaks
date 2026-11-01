import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcboost21 import MonitoringHistory, compare_benchmark_rows, import_presentmon_csv, validate_profile


class FeatureTests(unittest.TestCase):
    def test_presentmon_csv_metrics_filter_dropped_and_1_percent(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "capture.csv"
            with file.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Application", "ProcessID", "MsBetweenDisplayChange", "Dropped"])
                writer.writeheader()
                for value in [10, 10, 20, 100]: writer.writerow({"Application": "game.exe", "ProcessID": 10, "MsBetweenDisplayChange": value, "Dropped": 0})
                writer.writerow({"Application": "other.exe", "ProcessID": 20, "MsBetweenDisplayChange": 1, "Dropped": 0})
                writer.writerow({"Application": "game.exe", "ProcessID": 10, "MsBetweenDisplayChange": 1, "Dropped": 1})
            got = import_presentmon_csv(file, "game")
            self.assertEqual(got["frames"], 4)
            self.assertEqual(got["avg_fps"], 28.57)
            self.assertEqual(got["low_1_fps"], 10.0)
            self.assertEqual(got["source"], "PresentMon CSV (imported)")

    def test_presentmon_rejects_multiple_pids_and_no_supported_frame_time(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "capture.csv"
            file.write_text("Application,ProcessID,MsBetweenPresents\na.exe,1,10\na.exe,2,11\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "multiple process IDs"):
                import_presentmon_csv(file)
            file.write_text("Application,FPS\na.exe,100\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frame-time"):
                import_presentmon_csv(file)

    def test_benchmark_alignment_includes_game_resolution_settings_duration_method(self):
        a = {"game":"G", "resolution":"1080p", "settings":"High", "duration":60, "method":"display" , "avg_fps":100}
        b = dict(a, avg_fps=110)
        self.assertTrue(compare_benchmark_rows(a,b)["matched"])
        b["resolution"] = "1440p"
        self.assertIn("resolutions differ", compare_benchmark_rows(a,b)["mismatches"])

    def test_history_is_bounded_and_exports_unavailable_values(self):
        history = MonitoringHistory(maximum=2)
        history.add({"cpu":1,"gpu":None}, "t1"); history.add({"cpu":2,"gpu":3}, "t2"); history.add({"cpu":4}, "t3")
        self.assertEqual(len(history.rows), 2)
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/"history.csv"; self.assertEqual(history.export_csv(file),2)
            text=file.read_text(encoding="utf-8-sig")
            self.assertIn("t2",text); self.assertIn("t3",text); self.assertIn("gpu",text)

    def test_profile_validation_is_opt_in_and_rejects_unsupported_values(self):
        self.assertEqual(validate_profile({}), {"game_mode":"unchanged","background_capture":"unchanged","power_plan":"unchanged","priority":"Unchanged"})
        self.assertEqual(validate_profile({"priority":"medium"})["priority"], "Medium")
        with self.assertRaises(ValueError): validate_profile({"game_mode":"on" , "priority":"Realtime"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
