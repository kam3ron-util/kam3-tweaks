import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import PCBoost as app


class FakeKey:
    def __init__(self, registry, root, path):
        self.registry, self.root, self.path = registry, root, path
    def __enter__(self): return self
    def __exit__(self, *_): return False


class FakeRegistry:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1
    REG_DWORD = 4
    def __init__(self): self.values = {}; self.keys = set()
    def CreateKeyEx(self, root, path, reserved, access):
        self.keys.add((root, path)); return FakeKey(self, root, path)
    def OpenKey(self, root, path, reserved=0, access=0):
        if (root, path) not in self.keys and not any(k[:2] == (root, path) for k in self.values):
            raise FileNotFoundError(path)
        return FakeKey(self, root, path)
    def QueryValueEx(self, key, name):
        try: return self.values[(key.root, key.path, name)]
        except KeyError: raise FileNotFoundError(name)
    def SetValueEx(self, key, name, reserved, kind, value):
        self.keys.add((key.root, key.path)); self.values[(key.root, key.path, name)] = (value, kind)
    def DeleteValue(self, key, name):
        try: del self.values[(key.root, key.path, name)]
        except KeyError: raise FileNotFoundError(name)
    def DeleteKey(self, root, path):
        if any(k[:2] == (root, path) for k in self.values): raise OSError("key is not empty")
        self.keys.discard((root, path))


class SafetyActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = FakeRegistry()
        self.patches = [
            patch.object(app, "APP_DATA", self.root / "appdata"),
            patch.object(app, "WIN", True),
            patch.object(app, "winreg", self.registry),
        ]
        for item in self.patches: item.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def make_undo(self, name="undo.json"):
        undo = app.Undo(); undo.file = self.root / name; undo.items = []; undo.current = None
        return undo

    def test_registry_undo_restores_absence_and_removes_created_key(self):
        key = r"Software\Kam3Test\NewValue"
        undo = self.make_undo()
        undo.begin("create a value"); app.set_dword(undo, key, "Probe", 1); undo.finish()
        self.assertEqual(app.reg_read(key, "Probe")[:2], (True, 1))
        ok, message = undo.undo()
        self.assertTrue(ok, message)
        self.assertEqual(app.reg_read(key, "Probe"), (False, None, None))
        self.assertFalse(app.reg_key_exists(key))

    def test_registry_undo_restores_exact_previous_value_and_type(self):
        key = r"Software\Kam3Test\Typed"
        self.registry.CreateKeyEx("HKCU", key, 0, 2)
        with self.registry.OpenKey("HKCU", key) as handle:
            self.registry.SetValueEx(handle, "Probe", 0, self.registry.REG_SZ, "prior text")
        undo = self.make_undo()
        undo.begin("replace a value"); app.set_dword(undo, key, "Probe", 1); undo.finish()
        ok, message = undo.undo()
        self.assertTrue(ok, message)
        self.assertEqual(app.reg_read(key, "Probe"), (True, "prior text", self.registry.REG_SZ))

    def test_game_mode_and_capture_use_current_user_values_and_undo_absence(self):
        undo = self.make_undo(); undo.begin("game settings")
        app.set_dword(undo, app.GAMEBAR, "AutoGameModeEnabled", 1)
        app.set_dword(undo, app.CAPTURE, "AppCaptureEnabled", 0)
        app.set_dword(undo, app.GAMECONFIG, "GameDVR_Enabled", 0)
        undo.finish()
        self.assertEqual(app.reg_read(app.GAMEBAR, "AutoGameModeEnabled")[:2], (True, 1))
        self.assertEqual(app.reg_read(app.CAPTURE, "AppCaptureEnabled")[:2], (True, 0))
        self.assertEqual(app.reg_read(app.GAMECONFIG, "GameDVR_Enabled")[:2], (True, 0))
        ok, message = undo.undo()
        self.assertTrue(ok, message)
        self.assertFalse(app.reg_read(app.GAMEBAR, "AutoGameModeEnabled")[0])
        self.assertFalse(app.reg_read(app.CAPTURE, "AppCaptureEnabled")[0])
        self.assertFalse(app.reg_read(app.GAMECONFIG, "GameDVR_Enabled")[0])

    def test_undo_refuses_to_overwrite_registry_value_changed_after_apply(self):
        key = r"Software\Kam3Test\Conflict"
        undo = self.make_undo()
        undo.begin("create a value"); app.set_dword(undo, key, "Probe", 1); undo.finish()
        with self.registry.OpenKey("HKCU", key) as handle:
            self.registry.SetValueEx(handle, "Probe", 0, self.registry.REG_DWORD, 7)
        ok, message = undo.undo()
        self.assertFalse(ok)
        self.assertIn("changed after", message)
        self.assertEqual(app.reg_read(key, "Probe")[:2], (True, 7))
        self.assertTrue(undo.items, "conflicted undo must remain available")

    def test_startup_profile_validation_rejects_out_of_scope_and_malformed_approvals(self):
        approved={"kind":"registry","id":"run:GameHelper","key":r"Software\Microsoft\Windows\CurrentVersion\Run","name":"GameHelper","value":"C:\\Games\\helper.exe","type":1}
        self.assertEqual(app.validate_startup_profile([approved]),[approved])
        unsafe={**approved,"key":r"Software\Microsoft\Windows\CurrentVersion\RunOnce"}
        invalid_type={**approved,"type":3}
        malformed={"kind":"shortcut","id":"shortcut:C:\\Startup\\x.lnk","path":"C:\\Startup\\x.lnk","name":"x","sha256":"bad"}
        self.assertEqual(app.validate_startup_profile([unsafe,invalid_type,malformed,"junk"]),[])

    def test_menu_animation_undo_restores_documented_boolean_preference(self):
        undo=app.Undo(); undo.items=[{"label":"Windows Tweaks","actions":[{"type":"spi_bool","old":True,"expected":False}]}]
        state={"value":False}
        def spi(value=None):
            if value is not None: state["value"]=value; return True
            return state["value"]
        with patch.object(app,"system_menu_animation",side_effect=spi):
            ok,message=undo.undo_category("Windows Tweaks")
        self.assertTrue(ok,message); self.assertTrue(state["value"])

    def test_custom_profile_undo_detects_newer_registry_value(self):
        key=r"Software\Kam3Test\ProfileConflict"; profile_id="6ab3a1eb-74a1-45cc-ae4b-a169b0fcb805"
        undo=self.make_undo(); undo.begin("Custom Profile "+profile_id,{"custom_profile_id":profile_id,"display_label":"Profile: Test"})
        app.set_dword(undo,key,"Mode",1); undo.finish()
        with self.registry.OpenKey("HKCU",key) as handle: self.registry.SetValueEx(handle,"Mode",0,self.registry.REG_DWORD,7)
        ok,message=undo.undo_profile(profile_id)
        self.assertFalse(ok); self.assertIn("changed after",message)
        self.assertEqual(app.reg_read(key,"Mode"),(True,7,self.registry.REG_DWORD))
        self.assertTrue(any(item.get("custom_profile_id")==profile_id for item in undo.items))

    def test_named_category_undo_skips_unrelated_newer_transaction_and_detects_conflict(self):
        undo=self.make_undo(); key=r"Software\Kam3Test\Category"
        undo.begin("Gaming Tweaks"); app.set_dword(undo,key,"GameMode",1); undo.finish()
        undo.begin("Power Tweaks"); app.set_dword(undo,key,"OtherSetting",2); undo.finish()
        ok,message=undo.undo_category("Gaming Tweaks")
        self.assertTrue(ok,message)
        self.assertFalse(app.reg_read(key,"GameMode")[0])
        self.assertTrue(app.reg_read(key,"OtherSetting")[0])
        undo.begin("Gaming Tweaks"); app.set_dword(undo,key,"GameMode",1); undo.finish()
        with self.registry.OpenKey("HKCU",key) as handle: self.registry.SetValueEx(handle,"GameMode",0,self.registry.REG_DWORD,7)
        ok,message=undo.undo_category("Gaming Tweaks")
        self.assertFalse(ok)
        self.assertIn("changed after",message)
        self.assertEqual(app.reg_read(key,"GameMode"),(True,7,self.registry.REG_DWORD))

    def test_power_plan_undo_uses_saved_guid_and_preserves_newer_choice(self):
        old = "11111111-1111-1111-1111-111111111111"
        target = "22222222-2222-2222-2222-222222222222"
        current = {"guid": target}; calls = []
        def fake_command(args,timeout=5):
            calls.append(args)
            if len(args)>2 and args[1]=="/setactive": current["guid"]=args[2]
            return (0,"","")
        with patch.object(app, "active_plan", side_effect=lambda: (current["guid"], "test plan")), \
             patch.object(app, "command", side_effect=fake_command):
            undo = self.make_undo(); undo.items = [{"label": "power", "actions": [{"type": "power", "guid": old, "expected": target}]}]
            ok, message = undo.undo()
            self.assertTrue(ok, message)
            self.assertEqual(calls, [["powercfg", "/setactive", old]])
            current["guid"] = "33333333-3333-3333-3333-333333333333"; calls.clear()
            undo.items = [{"label": "power", "actions": [{"type": "power", "guid": old, "expected": target}]}]
            ok, message = undo.undo()
            self.assertFalse(ok)
            self.assertIn("changed after", message)
            self.assertEqual(calls, [])

    def test_power_undo_fails_closed_if_current_plan_is_unreadable_or_restore_unverified(self):
        old="11111111-1111-1111-1111-111111111111"; target="22222222-2222-2222-2222-222222222222"
        undo=self.make_undo(); undo.items=[{"label":"power","actions":[{"type":"power","guid":old,"expected":target}]}]
        with patch.object(app,"active_plan",return_value=(None,"unreadable")),patch.object(app,"command") as command:
            ok,message=undo.undo(); self.assertFalse(ok); self.assertIn("could not identify",message); command.assert_not_called()
        undo.items=[{"label":"power","actions":[{"type":"power","guid":old,"expected":target}]}]
        with patch.object(app,"active_plan",side_effect=[(target,"target"),(target,"still target")]),patch.object(app,"command",return_value=(0,"","")):
            ok,message=undo.undo(); self.assertFalse(ok); self.assertIn("did not verify",message)

    def test_priority_and_affinity_undo_restore_exact_values_and_detect_conflicts(self):
        class FakeProcess:
            def __init__(self): self.created = 12.5; self.priority = 0; self.affinity = [0, 1, 2, 3]
            def create_time(self): return self.created
            def nice(self, value=None):
                if value is not None: self.priority = value
                return self.priority
            def cpu_affinity(self, value=None):
                if value is not None: self.affinity = list(value)
                return list(self.affinity)
        process = FakeProcess()
        with patch.object(app.psutil, "Process", return_value=process):
            undo = self.make_undo()
            undo.items = [{"label":"priority", "actions":[{"type":"priority","pid":55,"created":12.5,"old":0,"expected":128}]}]
            process.priority = 128
            ok, message = undo.undo()
            self.assertTrue(ok, message); self.assertEqual(process.priority, 0)
            undo.items = [{"label":"priority", "actions":[{"type":"priority","pid":55,"created":12.5,"old":0,"expected":128}]}]
            process.priority = 10
            ok, message = undo.undo()
            self.assertFalse(ok); self.assertIn("changed after", message); self.assertEqual(process.priority, 10)
            undo.items = [{"label":"affinity", "actions":[{"type":"affinity","pid":55,"created":12.5,"old":[0,1,2,3],"expected":[0,2]}]}]
            process.affinity = [0, 2]
            ok, message = undo.undo()
            self.assertTrue(ok, message); self.assertEqual(process.affinity, [0,1,2,3])

    def test_windows_temp_preview_only_includes_old_direct_regular_files(self):
        folder = self.root / "WindowsTemp"; folder.mkdir()
        old = folder / "old.tmp"; old.write_text("old")
        fresh = folder / "fresh.tmp"; fresh.write_text("new")
        nested = folder / "nested"; nested.mkdir(); (nested / "old.tmp").write_text("nested")
        now = 2_000_000_000
        os.utime(old, (now - 10 * 86400, now - 10 * 86400))
        os.utime(fresh, (now, now))
        with patch.object(app, "windows_temp_dir", return_value=folder):
            reviewed, items = app.windows_temp_preview_details(now=now)
        self.assertEqual(reviewed, folder)
        self.assertEqual([item[0] for item in items], ["old.tmp"])

    def test_temp_cleanup_skips_locked_and_changed_files_and_reports_removed(self):
        folder = self.root / "profile" / "Temp"; folder.mkdir(parents=True)
        removable = folder / "remove.tmp"; removable.write_text("safe")
        locked = folder / "locked.tmp"; locked.write_text("locked")
        changed = folder / "changed.tmp"; changed.write_text("old")
        preview = [(p.name, p.stat().st_size, p.stat().st_dev, p.stat().st_ino, p.stat().st_mtime_ns) for p in (removable, locked, changed)]
        changed.write_text("changed after preview")
        original_unlink = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == locked: raise PermissionError("locked by a test process")
            return original_unlink(path, *args, **kwargs)
        with patch.object(app, "temp_dir", return_value=folder), patch.object(Path, "unlink", unlink):
            removed, freed, skipped, names = app.clean_temp_selected(folder, preview, report=True)
        self.assertEqual((removed, skipped, names), (1, 2, ["remove.tmp"]))
        self.assertEqual(freed, len("safe"))
        self.assertFalse(removable.exists()); self.assertTrue(locked.exists()); self.assertTrue(changed.exists())

    def test_startup_shortcut_move_undo_restores_exact_bytes(self):
        startup = self.root / "Startup"; startup.mkdir()
        source = startup / "GameHelper.lnk"; original = b"isolated fake shortcut bytes"
        source.write_bytes(original)
        with patch.object(app, "startup_folder_path", return_value=startup):
            undo = self.make_undo("startup-undo.json"); undo.begin("disable shortcut")
            destination = app.disable_startup_shortcut(source, undo); undo.finish()
            self.assertFalse(source.exists()); self.assertEqual(destination.read_bytes(), original)
            ok, message = undo.undo()
            self.assertTrue(ok, message)
            self.assertEqual(source.read_bytes(), original); self.assertFalse(destination.exists())

    def test_current_user_startup_run_value_undo_restores_exact_type_and_data(self):
        key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        self.registry.CreateKeyEx("HKCU", key, 0, 2)
        original = '"C:\\Apps\\Launcher.exe" --background'
        with self.registry.OpenKey("HKCU", key) as handle:
            self.registry.SetValueEx(handle, "Launcher", 0, self.registry.REG_SZ, original)
        undo = self.make_undo(); undo.begin("disable startup item")
        app.remove_registry_value(undo, key, "Launcher"); undo.finish()
        self.assertFalse(app.reg_read(key, "Launcher")[0])
        ok, message = undo.undo()
        self.assertTrue(ok, message)
        self.assertEqual(app.reg_read(key, "Launcher"), (True, original, self.registry.REG_SZ))

    def test_backup_validation_does_not_restore_enabled_priority_watcher(self):
        payload = {"format": app.LOCAL_BACKUP_FORMAT,
                   "settings": {"welcome_seen": True, "priority_rules_enabled": True},
                   "profiles": {"Minecraft": {"priority": "High"}},
                   "games": [{"name": "Minecraft", "path": str(self.root / "javaw.exe"), "priority": "Medium"}],
                   "priority_rules": [{"name": "Game", "path": str(self.root / "game.exe"), "priority": "High", "mode": "automatic", "enabled": True}],
                   "startup_profile": [{"kind":"registry","id":"run:GameHelper","key":r"Software\Microsoft\Windows\CurrentVersion\Run","name":"GameHelper","value":"C:\\Games\\helper.exe","type":1}]}
        parsed = app.validate_local_backup(payload)
        self.assertTrue(parsed["settings"]["welcome_seen"])
        self.assertNotIn("priority_rules_enabled", parsed["settings"])
        self.assertEqual(parsed["profiles"]["Minecraft"]["priority"], "High")
        self.assertEqual(parsed["priority_rules"][0]["mode"], "automatic")
        self.assertEqual(parsed["startup_profile"], payload["startup_profile"])
        payload["priority_rules"][0]["priority"] = "Realtime"
        with self.assertRaises(ValueError): app.validate_local_backup(payload)

    def test_catalog_has_distinct_features_and_marks_shortcuts_separately(self):
        self.assertTrue(app.validate_catalog())
        self.assertEqual(len(app.OPTIMIZATION_CATALOG), 61)
        shortcuts = [entry for entry in app.OPTIMIZATION_CATALOG if entry["kind"] == "Settings shortcut"]
        self.assertEqual(len(shortcuts), 25)
        self.assertTrue(all(entry["action"] in {"shortcut", "gpu_settings", "browser_edge", "browser_chrome", "browser_firefox"} for entry in shortcuts))
        self.assertEqual(len({entry["key"] for entry in app.OPTIMIZATION_CATALOG}), len(app.OPTIMIZATION_CATALOG))


if __name__ == "__main__":
    unittest.main(verbosity=2)
