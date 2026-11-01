import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import PCBoost as app


class BrandAndPriorityTests(unittest.TestCase):
    def test_priority_labels_map_to_documented_windows_classes(self):
        self.assertEqual(app.PRIORITY_VALUES["High"], app.psutil.HIGH_PRIORITY_CLASS)
        self.assertEqual(app.PRIORITY_VALUES["Medium"], app.psutil.NORMAL_PRIORITY_CLASS)
        self.assertEqual(app.PRIORITY_VALUES["Low"], app.psutil.BELOW_NORMAL_PRIORITY_CLASS)
        self.assertNotIn("Realtime", app.PRIORITY_VALUES)

    def test_protected_windows_process_and_system_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Windows"
            system = root / "System32" / "example.exe"
            system.parent.mkdir(parents=True)
            system.touch()
            with patch.dict(os.environ, {"SystemRoot": str(root)}):
                self.assertTrue(app.protected_process("svchost.exe", ""))
                self.assertTrue(app.protected_process("example.exe", str(system)))
                self.assertFalse(app.protected_process("game.exe", str(Path(temp) / "game.exe")))

    def test_legacy_migration_copies_allowlisted_files_without_overwrite_or_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            old = base / "PCBoost"
            new = base / "Kam3 Tweaks"
            old.mkdir()
            new.mkdir()
            (old / "settings.json").write_text('{"old": true}', encoding="utf-8")
            (old / "games.json").write_text("[]", encoding="utf-8")
            (old / "do-not-copy.txt").write_text("keep", encoding="utf-8")
            (new / "settings.json").write_text('{"new": true}', encoding="utf-8")
            with patch.object(app, "LEGACY_APP_DATA", old), patch.object(app, "APP_DATA", new):
                copied = app.migrate_legacy_pcboost_data()
            self.assertEqual(copied, ["games.json"])
            self.assertEqual((new / "settings.json").read_text(encoding="utf-8"), '{"new": true}')
            self.assertEqual((new / "games.json").read_text(encoding="utf-8"), "[]")
            self.assertTrue((old / "settings.json").exists())
            self.assertTrue((old / "games.json").exists())
            self.assertFalse((new / "do-not-copy.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
