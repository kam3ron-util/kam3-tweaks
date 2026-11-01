import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
import PCBoost as app


class GuiReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.original_style = cls.qt.styleSheet()
        cls.qt.setStyleSheet(app.STYLE)

    def make_window(self, temp):
        data = Path(temp) / "appdata"
        data.mkdir(parents=True)
        (data / "settings.json").write_text('{"welcome_seen": true}', encoding="utf-8")
        stack = [
            patch.object(app, "APP_DATA", data),
            patch.object(app, "LEGACY_APP_DATA", Path(temp) / "no-legacy-data"),
            patch.object(app, "WIN", False),
            patch.object(app, "fetch_latest_release", side_effect=RuntimeError("Offline test fixture")),
            patch.object(app, "admin", return_value=False),
            patch.object(app, "plans", return_value=[]),
            patch.object(app, "active_plan", return_value=(None, "Unavailable outside Windows")),
            patch.object(app, "gpu", return_value=(None, None, None)),
            patch.object(app, "startup_entries", return_value=[]),
            patch.object(app, "startup_folder_entries", return_value=[]),
        ]
        for item in stack: item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(stack)])
        return app.Window()

    def test_seven_page_navigation_and_quick_tweaks_features(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            window.show(); self.qt.processEvents()
            expected = ["Home", "Quick Tweaks", "Optimizations", "Gaming", "Network", "Cleanup", "Settings"]
            try:
                self.assertEqual(window.PAGE_NAMES, expected)
                self.assertEqual([b.text().replace("&&", "&").strip() for b in window.nav_buttons], expected)
                self.assertEqual(len(window.pages), 7)
                self.assertEqual(window.optimization_table.rowCount(), 61)
                self.assertEqual(window.profile_priority.itemText(0), "Unchanged")
                self.assertEqual([window.quick_tabs.tabText(i) for i in range(window.quick_tabs.count())], window.QUICK_TAB_NAMES)
                self.assertEqual(set(window.quick_category_cards), set(window.QUICK_TAB_NAMES))
                self.assertEqual(len(window.inline_undo_buttons), 7)
                self.assertTrue(all(not button.isEnabled() for button in window.inline_undo_buttons))
                window.undo.items = [{"label": "Mock reversible change", "actions": []}]
                window.refresh_undo()
                self.assertTrue(all(not button.isEnabled() for button in window.inline_undo_buttons))
                window.undo.items.append({"label":"Windows Tweaks","actions":[]}); window.refresh_undo()
                self.assertTrue(window.quick_restore_buttons[0].isEnabled())
                self.assertFalse(window.quick_restore_buttons[1].isEnabled())
                window.undo.items = []; window.refresh_undo()
                for index, button in enumerate(window.nav_buttons):
                    button.click(); self.qt.processEvents()
                    self.assertEqual(window.stack.currentIndex(), index)
                    self.assertEqual(window.top_title.text(), expected[index])
                    self.assertEqual(sum(item.isChecked() for item in window.nav_buttons), 1)
                quick_button = window.nav_buttons[1]
                quick_button.click(); self.qt.processEvents()
                for index in range(window.quick_tabs.count()):
                    window.stack.widget(1).ensureWidgetVisible(window.quick_view_buttons[index])
                    window.quick_view_buttons[index].click(); self.qt.processEvents()
                    self.assertTrue(window.quick_tabs.isVisible())
                    self.assertEqual(window.quick_tabs.currentIndex(), index)
                self.assertTrue(window.priority_btn.isEnabled() is False or not app.WIN)
                self.assertIsNotNone(window.rule_save_btn)
                self.assertIsNotNone(window.affinity_btn)
                self.assertIsNotNone(window.startup_table)
                self.assertIsNotNone(window.startup_disable_btn)
                self.assertIsNotNone(window.gpu_app_path)
                self.assertIsNotNone(window.nvidia_adapter_text)
                self.assertTrue(window.activity_panel.isHidden())
                window.nav_buttons[6].click(); self.qt.processEvents()
                window.stack.widget(6).ensureWidgetVisible(window.activity_history_toggle)
                window.activity_history_toggle.click(); self.qt.processEvents()
                self.assertTrue(window.activity_history_toggle.isChecked())
                self.assertFalse(window.activity_panel.isHidden())
                window.open_activity_history(); self.qt.processEvents()
                self.assertEqual(window.stack.currentIndex(), 6)
                self.assertTrue(window.activity_history_toggle.isChecked())
                self.assertFalse(any(name in window.PAGE_NAMES for name in ("Startup", "Restore & History", "GPU & Display", "CPU & Processes")))
                for size in ((1280, 720), (1920, 1080)):
                    window.resize(*size); window.show(); self.qt.processEvents()
                    self.assertGreater(window.width(), 1000)
                    self.assertEqual(len(window.nav_buttons), 7)
                    self.assertTrue(window.stack.currentWidget().isVisible())
                self.assertFalse(hasattr(window, "timer"))
                self.assertFalse(hasattr(window, "ping_timer"))
            finally:
                window.close()

    def test_gpu_vendor_detection_and_adapter_probe_are_read_only(self):
        self.assertEqual(app.gpu_vendor("NVIDIA GeForce RTX"), "NVIDIA")
        self.assertEqual(app.gpu_vendor("AMD Radeon RX"), "AMD")
        self.assertEqual(app.gpu_vendor("Intel Arc"), "Intel")
        self.assertEqual(app.gpu_vendor("Unknown adapter"), "Other")
        with patch.object(app, "WIN", False), patch.object(app, "command") as command:
            self.assertEqual(app.gpu_adapters(), [])
            command.assert_not_called()

    def test_theme_selection_persists_and_changes_the_application_palette(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            try:
                self.assertEqual(window.current_theme, "Violet Aurora")
                violet = app.theme_stylesheet("Violet Aurora")
                blue = app.theme_stylesheet("Midnight Blue")
                self.assertNotEqual(violet, blue)
                self.assertIn(app.THEME_PALETTES["Violet Aurora"]["accent"], violet)
                window.theme_combo.setCurrentText("Midnight Blue")
                self.assertEqual(window.current_theme, "Midnight Blue")
                self.assertIn(app.THEME_PALETTES["Midnight Blue"]["accent"], window.styleSheet())
                saved = json.loads((Path(temp) / "appdata" / "settings.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["theme"], "Midnight Blue")
            finally:
                window.close()

    def test_github_update_settings_show_newer_release_and_error_without_downloading(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            try:
                self.assertEqual(window.update_check_btn.text(),"Check for Updates")
                self.assertEqual(window.update_open_btn.text(),"View Releases")
                newer={"version":(4,7,1,0),"tag":"v4.7.1","url":"https://github.com/kam3ron-util/kam3-tweaks/releases/tag/v4.7.1","notes":"Bug fixes and improvements.","assets":[]}
                window.on_update_check_complete({"ok":True,"release":newer})
                self.assertIn("Update Available",window.update_status.text())
                self.assertEqual(window.update_notes.text(),newer["notes"])
                with patch.object(app.webbrowser,"open",return_value=True) as open_page:
                    window.open_update_page(); open_page.assert_called_once_with(newer["url"])
                current={**newer,"tag":"v"+app.APP_VERSION,"version":tuple(map(int,app.APP_VERSION.split(".")))+(0,),"url":"https://github.com/kam3ron-util/kam3-tweaks/releases/tag/v"+app.APP_VERSION}
                window.on_update_check_complete({"ok":True,"release":current})
                self.assertIn("Up to date",window.update_status.text())
                self.assertNotIn("Update Available",window.update_status.text())
                window.on_update_check_complete({"ok":False,"error":"GitHub rate limit reached. Try again later."})
                self.assertIn("Unable to check",window.update_status.text())
            finally: window.close()

    def test_updates_settings_are_available_persist_and_fail_closed_without_publisher_key(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            try:
                self.assertTrue(hasattr(window,"update_auto_check"))
                self.assertTrue(window.update_auto_check.isChecked())
                self.assertFalse(window.update_auto_download.isChecked())
                self.assertFalse(window.update_auto_install.isEnabled())
                self.assertFalse(window.update_now_btn.isEnabled())
                window.update_auto_download.setChecked(True)
                saved=json.loads((Path(temp)/"appdata"/"settings.json").read_text(encoding="utf-8"))
                self.assertTrue(saved["auto_download_updates"])
                self.assertFalse(saved.get("auto_install_updates",False))
                with patch.object(app,"verification_ready",return_value=False),patch.object(app,"download_verified_update") as download:
                    newer={"version":(4,8,0,0),"tag":"v4.8.0","url":"https://github.com/kam3ron-util/kam3-tweaks/releases/tag/v4.8.0","notes":"Signed release","assets":[{"name":"Kam3Tweaks.exe"},{"name":"Kam3TweaksUpdater.exe"},{"name":"update-manifest.json"},{"name":"update-manifest.sig"}]}
                    window.latest_release=newer; window.start_update_download(); download.assert_not_called()
                    self.assertIn("no pinned publisher verification key",window.update_status.text())
            finally: window.close()

    def test_update_check_worker_uses_mocked_github_response_and_surfaces_version(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            try:
                newer={"version":(4,8,0,0),"tag":"v4.8.0","url":"https://github.com/kam3ron-util/kam3-tweaks/releases/tag/v4.8.0","notes":"New release notes","assets":[]}
                with patch.object(app,"fetch_latest_release",return_value=newer):
                    window.check_for_updates()
                    self.assertIsNotNone(window._update_thread)
                    deadline=__import__("time").monotonic()+3
                    while window._update_thread is not None and __import__("time").monotonic()<deadline:
                        self.qt.processEvents(); QTest.qWait(20)
                    self.assertIsNone(window._update_thread)
                    self.qt.processEvents()
                self.assertIn("Update Available",window.update_status.text())
                self.assertIn("v4.8.0",window.update_status.text())
                self.assertEqual(window.update_notes.text(),"New release notes")
            finally: window.close()

    def test_update_progress_cancel_install_confirmation_and_failure_state(self):
        import threading
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            try:
                window.on_update_download_progress(50,100)
                self.assertEqual(window.update_progress.value(),500)
                self.assertIn("0.0 MB / 0.0 MB",window.update_status.text())
                class Worker: cancel_event=threading.Event()
                window._download_worker=Worker(); window.cancel_update_download()
                self.assertTrue(window._download_worker.cancel_event.is_set())
                window._verified_update={"metadata":{"version":"4.7.0"}}
                with patch.object(app,"verification_ready",return_value=True),patch.object(app.sys,"frozen",True,create=True),patch.object(window,"_helper_path",return_value=True),patch.object(app.QMessageBox,"question",return_value=app.QMessageBox.StandardButton.No),patch.object(app.subprocess,"Popen") as launch:
                    window.install_verified_update(); launch.assert_not_called()
                window.on_update_download_complete({"ok":False,"error":"Release manifest signature is invalid."})
                self.assertFalse(window.update_install_btn.isEnabled())
                self.assertIn("failed",window.update_status.text().casefold())
                self.assertFalse(window.update_retry_btn.isHidden())
            finally: window.close()

    def test_update_history_records_and_backup_restores_safe_update_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            try:
                window._record_update_history("detected","v4.7.0","stable release")
                window.refresh_update_history()
                self.assertIn("v4.7.0",window.update_history_label.text())
                valid=app.validate_local_backup({"format":app.LOCAL_BACKUP_FORMAT,
                    "settings":{"auto_check_updates":False,"auto_download_updates":True,"auto_install_updates":True,"theme":"Midnight Blue"},
                    "profiles":{name:{} for name in app.PROFILE_NAMES},"games":[],"priority_rules":[],"startup_profile":[],"custom_profiles":[]})
                self.assertFalse(valid["settings"]["auto_check_updates"])
                self.assertTrue(valid["settings"]["auto_download_updates"])
                self.assertFalse(valid["settings"]["auto_install_updates"])
                self.assertEqual(valid["settings"]["theme"],"Midnight Blue")
            finally: window.close()

    def test_quick_category_apply_buttons_route_to_existing_confirmed_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            try:
                with patch.object(window, "view_quick_category"), patch.object(window, "apply_windows_tweaks") as windows:
                    window.apply_quick_category("Windows Tweaks"); windows.assert_called_once_with()
                with patch.object(window, "view_quick_category"), patch.object(window, "apply_startup_profile") as startup:
                    window.apply_quick_category("Startup Tweaks"); startup.assert_called_once_with()
                with patch.object(window, "view_quick_category"), patch.object(window, "apply_cpu_tweaks") as cpu:
                    window.apply_quick_category("CPU Tweaks"); cpu.assert_called_once()
                with patch.object(window, "view_quick_category") as graphics:
                    window.apply_quick_category("NVIDIA Tweaks"); graphics.assert_called_once_with(4)
                with patch.object(window,"apply_quick_category") as windows:
                    window.one_click_category_apply_buttons[0].click()
                    windows.assert_called_once_with("Windows Tweaks")
            finally:
                window.close()

    def test_gaming_tweaks_apply_uses_one_confirmation_skips_correct_values_and_verifies(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            state = {(app.GAMEBAR,"AutoGameModeEnabled"):(True,0,4),
                     (app.CAPTURE,"AppCaptureEnabled"):(True,0,4),
                     (app.GAMECONFIG,"GameDVR_Enabled"):(True,1,4)}
            calls=[]; results=[]
            def read(key,name): return state.get((key,name),(False,None,None))
            def write(undo,key,name,value):
                exists,old,kind=read(key,name)
                if exists and old==value and kind==4: return False
                undo.record({"type":"reg","key":key,"name":name,"exists":exists,"value":old,"kind":kind,
                             "expected_exists":True,"expected_value":value,"expected_kind":4})
                state[(key,name)]=(True,value,4); return True
            def finish(label,fn):
                window.undo.begin(label); results.append(fn()); window.undo.finish()
            window.ask=lambda title,body: calls.append((title,body)) or True
            with patch.object(app,"WIN",True), patch.object(app,"winreg",SimpleNamespace(REG_DWORD=4)), \
                 patch.object(app,"reg_read",side_effect=read), patch.object(app,"set_dword",side_effect=write), \
                 patch.object(app,"active_plan",return_value=("guid","Balanced")), patch.object(window,"finish_change",side_effect=finish):
                window.apply_gaming_tweaks()
            self.assertEqual(len(calls),1)
            self.assertIn("Current power plan: Balanced",calls[0][1])
            self.assertIn("No process priorities",calls[0][1])
            self.assertEqual(state[(app.GAMEBAR,"AutoGameModeEnabled")][1],1)
            self.assertEqual(state[(app.CAPTURE,"AppCaptureEnabled")][1],0)
            self.assertEqual(state[(app.GAMECONFIG,"GameDVR_Enabled")][1],0)
            self.assertIn("2 change(s) verified",results[0])
            self.assertEqual(window.undo.label,"Gaming Tweaks")
            window.close()

    def test_gaming_tweaks_cancel_and_partial_failures_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            window.ask=lambda *_:False
            with patch.object(app,"WIN",True), patch.object(app,"winreg",SimpleNamespace(REG_DWORD=4)), \
                 patch.object(app,"reg_read",return_value=(True,0,4)), patch.object(app,"set_dword") as setter:
                window.apply_gaming_tweaks(); setter.assert_not_called()
            state={(app.GAMEBAR,"AutoGameModeEnabled"):(True,0,4)}
            def read(key,name): return state.get((key,name),(True,1,4))
            attempted=[]
            def write(undo,key,name,value):
                attempted.append(name)
                if name=="AppCaptureEnabled": raise PermissionError("mock access denied")
                state[(key,name)]=(True,value,4); return True
            result=[]
            def finish(label,fn): result.append(fn())
            window.ask=lambda *_:True
            with patch.object(app,"WIN",True), patch.object(app,"winreg",SimpleNamespace(REG_DWORD=4)), \
                 patch.object(app,"reg_read",side_effect=read), patch.object(app,"set_dword",side_effect=write), \
                 patch.object(app,"active_plan",return_value=(None,"Unavailable")), patch.object(window,"finish_change",side_effect=finish):
                window.apply_gaming_tweaks()
            self.assertEqual(len(attempted),3)
            self.assertIn("2 change(s) verified",result[0])
            self.assertIn("mock access denied",result[0])
            window.close()

    def test_gaming_undo_routes_only_latest_category_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            window.ask=lambda *_: True
            window.undo.items=[{"label":"Gaming Tweaks","actions":[]}]
            with patch.object(window.undo,"undo_category",return_value=(True,"Undid.")) as undo, patch.object(app.QMessageBox,"information"):
                window.undo_gaming_tweaks(); undo.assert_called_once_with("Gaming Tweaks")
            window.close()

    def test_power_tweaks_one_click_records_exact_previous_guid(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); window.ask=lambda *_:True; output=[]
            plans=[("old-guid","Balanced"),("fast-guid","High performance")]
            def active(): return ("old-guid","Balanced") if len(output)==0 else ("fast-guid","High performance")
            def finish(label,fn): window.undo.begin(label); output.append(fn()); window.undo.finish()
            with patch.object(app,"WIN",True), patch.object(app,"plans",return_value=plans), \
                 patch.object(app,"active_plan",side_effect=[("old-guid","Balanced"),("fast-guid","High performance")]), \
                 patch.object(app,"command",return_value=(0,"","")), patch.object(window,"finish_change",side_effect=finish):
                window.apply_power_tweaks()
            self.assertIn("verified",output[0])
            self.assertEqual(window.undo.items[-1]["actions"],[{"type":"power","guid":"old-guid","expected":"fast-guid"}])
            window.close()

    def test_cpu_tweaks_only_applies_saved_matching_priority_rules(self):
        class FakeProcess:
            def __init__(self): self.value=app.PRIORITY_VALUES["Medium"]
            def create_time(self): return 12.5
            def nice(self,value=None):
                if value is not None: self.value=value
                return self.value
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); path=str(Path(temp)/"game.exe"); proc=FakeProcess(); result=[]
            window.settings["priority_rules_enabled"]=True
            window.priority_rules=[{"path":path,"priority":"High","mode":"automatic","enabled":True}]
            info=(777,"game.exe",os.path.normcase(os.path.abspath(path)),12.5)
            window.ask=lambda *_:True
            def finish(label,fn): window.undo.begin(label); result.append(fn()); window.undo.finish()
            with patch.object(app,"WIN",True), patch.object(window,"_enumerate_priority_targets",return_value=[info]), \
                 patch.object(app.psutil,"Process",return_value=proc), patch.object(window,"finish_change",side_effect=finish):
                window.apply_cpu_tweaks()
            self.assertEqual(proc.value,app.PRIORITY_VALUES["High"])
            self.assertIn("1 application(s) verified",result[0])
            self.assertEqual(window.undo.items[-1]["label"],"CPU Tweaks")
            window.close()

    def test_windows_tweaks_one_click_changes_and_undoes_documented_menu_animation(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); state={"menu":True,"minimize":True}; confirmations=[]
            def spi_menu(value=None):
                if value is not None: state["menu"]=value
                return state["menu"]
            def spi_minimize(value=None):
                if value is not None: state["minimize"]=value
                return state["minimize"]
            def finish(label,fn): window.undo.begin(label); fn(); window.undo.finish()
            window.ask=lambda title,body:confirmations.append((title,body)) or True
            with patch.object(app,"system_menu_animation",side_effect=spi_menu), patch.object(app,"system_minimize_animation",side_effect=spi_minimize), patch.object(window,"finish_change",side_effect=finish):
                window.apply_windows_tweaks()
            self.assertFalse(state["menu"]); self.assertFalse(state["minimize"]); self.assertEqual(len(confirmations),1)
            self.assertEqual(window.undo.items[-1]["label"],"Windows Tweaks")
            self.assertEqual([action["type"] for action in window.undo.items[-1]["actions"]],["spi_bool","spi_minimize_animation"])
            state["menu"]=True; state["minimize"]=True
            with patch.object(app,"system_menu_animation",side_effect=spi_menu), patch.object(app,"system_minimize_animation",side_effect=spi_minimize):
                ok,_=window.undo.undo_category("Windows Tweaks")
            self.assertTrue(ok); self.assertTrue(state["menu"]); self.assertTrue(state["minimize"])
            window.close()

    def test_startup_profile_applies_only_saved_user_approved_registry_item(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); key=r"Software\Microsoft\Windows\CurrentVersion\Run"; state={"entry":(True,"C:/Games/helper.exe",1)}; confirms=[]; output=[]
            window.startup_profile=[{"kind":"registry","id":"run:Helper","key":key,"name":"Helper","value":"C:/Games/helper.exe","type":1}]
            window.ask=lambda title,body:confirms.append((title,body)) or True
            def finish(label,fn): window.undo.begin(label); output.append(fn()); window.undo.finish()
            def remove(undo,k,n):
                undo.record({"type":"reg","key":k,"name":n,"exists":True,"key_exists":True,"value":"C:/Games/helper.exe","kind":1,"expected_exists":False,"expected_value":None,"expected_kind":None})
                state.update(entry=(False,None,None))
            with patch.object(app,"WIN",True), patch.object(app,"reg_read",side_effect=lambda k,n:state["entry"]), \
                 patch.object(app,"remove_registry_value",side_effect=remove), \
                 patch.object(window,"finish_change",side_effect=finish):
                window.apply_startup_profile()
            self.assertEqual(len(confirms),1); self.assertFalse(state["entry"][0]); self.assertIn("1 startup item(s) disabled",output[0])
            self.assertEqual(window.undo.items[-1]["label"],"Startup Tweaks")
            window.close()

    def test_startup_profile_cancellation_and_stale_value_never_remove_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); key=r"Software\Microsoft\Windows\CurrentVersion\Run"
            window.startup_profile=[{"kind":"registry","id":"run:Helper","key":key,"name":"Helper","value":"old.exe","type":1}]
            window.ask=lambda *_:False
            with patch.object(app,"WIN",True), patch.object(app,"reg_read",return_value=(True,"old.exe",1)), patch.object(app,"remove_registry_value") as remove:
                window.apply_startup_profile()
            remove.assert_not_called(); self.assertEqual(window.undo.items,[])
            window.ask=lambda *_:True
            with patch.object(app,"WIN",True), patch.object(app,"reg_read",return_value=(True,"new.exe",1)), patch.object(app,"remove_registry_value") as remove:
                window.finish_change=lambda label,fn:fn()
                window.apply_startup_profile()
            remove.assert_not_called()
            window.close()

    def test_startup_profile_permission_failure_is_reported_and_not_journaled(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); key=r"Software\Microsoft\Windows\CurrentVersion\Run"; results=[]
            window.startup_profile=[{"kind":"registry","id":"run:Helper","key":key,"name":"Helper","value":"old.exe","type":1}]
            window.ask=lambda *_:True
            def finish(label,fn):
                window.undo.begin(label); results.append(fn()); window.undo.finish()
            with patch.object(app,"WIN",True), patch.object(app,"reg_read",return_value=(True,"old.exe",1)), \
                 patch.object(app,"remove_registry_value",side_effect=PermissionError("access denied")), \
                 patch.object(window,"finish_change",side_effect=finish):
                window.apply_startup_profile()
            self.assertIn("Failed:",results[0]); self.assertIn("access denied",results[0]); self.assertEqual(window.undo.items,[])
            window.close()

    def test_custom_profiles_create_edit_duplicate_delete_and_survive_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            profile={"id":str(app.uuid.uuid4()),"name":"Fortnite Evening","game_mode_on":True,"capture_off":True,"menu_animation_off":False,"minimize_animation_off":False,"power_guid":None,"priority_rules":[]}
            profile_id=window.save_custom_profile(profile)
            self.assertEqual(window.custom_profile_combo.currentData(),profile_id)
            changed={**profile,"name":"Fortnite Quiet","capture_off":False}
            window.save_custom_profile(changed)
            duplicate={**changed,"id":str(app.uuid.uuid4()),"name":"Fortnite Quiet Copy"}
            duplicate_id=window.save_custom_profile(duplicate)
            self.assertEqual(len(window.custom_profiles),2)
            window.close()
            restarted=app.Window()
            self.assertEqual({item["id"] for item in restarted.custom_profiles},{profile_id,duplicate_id})
            restarted.custom_profile_combo.setCurrentIndex(restarted.custom_profile_combo.findData(duplicate_id))
            with patch.object(restarted,"ask",return_value=True), patch.object(app.QMessageBox,"information"):
                restarted.delete_custom_profile()
            self.assertEqual(len(restarted.custom_profiles),1)
            self.assertEqual(restarted.custom_profiles[0]["id"],profile_id)
            restarted.close()

    def test_custom_profile_applies_once_and_undoes_after_unrelated_change(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); old="11111111-1111-1111-1111-111111111111"; target="22222222-2222-2222-2222-222222222222"
            profile={"id":str(app.uuid.uuid4()),"name":"Gaming Night","game_mode_on":False,"capture_off":False,"menu_animation_off":True,"minimize_animation_off":False,"power_guid":target,"priority_rules":[]}
            profile_id=window.save_custom_profile(profile); state={"animation":True,"power":old}; confirmations=[]
            window.ask=lambda title,body:confirmations.append((title,body)) or True
            window.refresh_settings=lambda:None; window.refresh_plans=lambda:None; window.refresh_startup=lambda:None; window.refresh_activity=lambda:None
            def command(args,timeout=5): state["power"]=args[-1]; return 0,"", ""
            try:
                with patch.object(app,"WIN",True), patch.object(app,"winreg",SimpleNamespace(REG_DWORD=4)), \
                     patch.object(app,"plans",return_value=[(target,"High Performance")]), \
                     patch.object(app,"active_plan",side_effect=lambda:(state["power"],"plan")), \
                     patch.object(app,"command",side_effect=command), \
                     patch.object(app,"system_menu_animation",side_effect=lambda value=None:state.update(animation=value) or True if value is not None else state["animation"]), \
                     patch.object(app.QMessageBox,"information"), patch.object(app.QMessageBox,"warning"):
                    window.apply_custom_profile()
                    self.assertEqual(len(confirmations),1); self.assertFalse(state["animation"]); self.assertEqual(state["power"],target)
                    self.assertEqual(window.undo.items[-1]["custom_profile_id"],profile_id)
                    window.undo.items.append({"label":"Unrelated category","actions":[]})
                    window.undo.save()
                    window.undo_custom_profile()
                self.assertTrue(state["animation"]); self.assertEqual(state["power"],old)
                self.assertEqual([item["label"] for item in window.undo.items],["Unrelated category"])
            finally: window.close()

    def test_custom_profile_reports_partial_power_failure_but_keeps_successful_undo(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); old="11111111-1111-1111-1111-111111111111"; target="22222222-2222-2222-2222-222222222222"
            profile={"id":str(app.uuid.uuid4()),"name":"Partial","game_mode_on":False,"capture_off":False,"menu_animation_off":True,"minimize_animation_off":False,"power_guid":target,"priority_rules":[]}
            window.save_custom_profile(profile); state={"animation":True,"power":old}; window.ask=lambda *_:True
            window.refresh_settings=lambda:None; window.refresh_plans=lambda:None; window.refresh_startup=lambda:None; window.refresh_activity=lambda:None
            def command(*_args,**_kwargs): return 1,"","access denied"
            try:
                with patch.object(app,"WIN",True), patch.object(app,"winreg",SimpleNamespace(REG_DWORD=4)), \
                     patch.object(app,"plans",return_value=[(target,"High Performance")]), \
                     patch.object(app,"active_plan",side_effect=lambda:(state["power"],"plan")), \
                     patch.object(app,"command",side_effect=command), \
                     patch.object(app,"system_menu_animation",side_effect=lambda value=None:state.update(animation=value) or True if value is not None else state["animation"]), \
                     patch.object(app.QMessageBox,"information"), patch.object(app.QMessageBox,"warning"):
                    window.apply_custom_profile()
                self.assertFalse(state["animation"]); self.assertEqual(state["power"],old)
                self.assertEqual(len(window.undo.items),1); self.assertEqual([a["type"] for a in window.undo.items[0]["actions"]],["spi_bool","power"])
                self.assertIn("Failed:",window.status.text()); self.assertIn("access denied",window.status.text())
            finally: window.close()

    def test_custom_profile_preserves_setting_changed_after_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); profile={"id":str(app.uuid.uuid4()),"name":"Game Mode","game_mode_on":True,"capture_off":False,"menu_animation_off":False,"minimize_animation_off":False,"power_guid":None,"priority_rules":[]}
            window.save_custom_profile(profile); key=(app.GAMEBAR,"AutoGameModeEnabled"); state={key:(True,0,4)}; writes=[]
            def confirm(*_): state[key]=(True,2,4); return True
            window.ask=confirm; window.refresh_settings=lambda:None; window.refresh_plans=lambda:None; window.refresh_startup=lambda:None; window.refresh_activity=lambda:None
            try:
                with patch.object(app,"WIN",True), patch.object(app,"winreg",SimpleNamespace(REG_DWORD=4)), \
                     patch.object(app,"reg_read",side_effect=lambda k,n:state.get((k,n),(False,None,None))), \
                     patch.object(app,"set_dword",side_effect=lambda *args:writes.append(args)), \
                     patch.object(app.QMessageBox,"information"), patch.object(app.QMessageBox,"warning"):
                    window.apply_custom_profile()
                self.assertEqual(state[key],(True,2,4)); self.assertEqual(writes,[])
                self.assertIn("changed after confirmation",window.status.text())
                self.assertFalse(window.undo.items)
            finally: window.close()

    def test_custom_profile_skips_already_configured_values_without_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); profile={"id":str(app.uuid.uuid4()),"name":"Already Set","game_mode_on":True,"capture_off":False,"menu_animation_off":False,"minimize_animation_off":False,"power_guid":None,"priority_rules":[]}
            window.save_custom_profile(profile); key=(app.GAMEBAR,"AutoGameModeEnabled"); state={key:(True,1,4)}; window.ask=lambda *_:self.fail("already-configured profile must not ask to apply")
            try:
                with patch.object(app,"WIN",True), patch.object(app,"winreg",SimpleNamespace(REG_DWORD=4)), \
                     patch.object(app,"reg_read",side_effect=lambda k,n:state.get((k,n),(False,None,None))), patch.object(app.QMessageBox,"information"):
                    window.apply_custom_profile()
                self.assertFalse(window.undo.items)
            finally: window.close()

    def test_custom_profile_applies_selected_exact_path_priority_rule_and_restores_it(self):
        class FakeProcess:
            def __init__(self): self.value=app.PRIORITY_VALUES["Medium"]; self.created=12.5
            def create_time(self): return self.created
            def nice(self,value=None):
                if value is not None: self.value=value
                return self.value
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); path=str((Path(temp)/"FortniteClient.exe").resolve()); process=FakeProcess(); info=(777,"FortniteClient.exe",os.path.normcase(os.path.abspath(path)),12.5)
            window.priority_rules=[{"name":"Fortnite","path":info[2],"priority":"High","mode":"automatic","enabled":True}]
            profile={"id":str(app.uuid.uuid4()),"name":"Fortnite","game_mode_on":False,"capture_off":False,"menu_animation_off":False,"minimize_animation_off":False,"power_guid":None,"priority_rules":[{"name":"Fortnite","path":path,"priority":"High"}]}
            window.save_custom_profile(profile); confirmations=[]; window.ask=lambda title,body:confirmations.append((title,body)) or True
            try:
                with patch.object(app,"WIN",True), patch.object(app,"winreg",SimpleNamespace(REG_DWORD=4)), \
                     patch.object(window,"_enumerate_priority_targets",return_value=[info]), patch.object(app.psutil,"Process",return_value=process), \
                     patch.object(app.QMessageBox,"information"), patch.object(app.QMessageBox,"warning"):
                    window.apply_custom_profile()
                    self.assertEqual(process.value,app.PRIORITY_VALUES["High"]); self.assertEqual(len(confirmations),1)
                    window.ask=lambda *_:True; window.undo_custom_profile()
                self.assertEqual(process.value,app.PRIORITY_VALUES["Medium"])
                self.assertFalse(window._priority_applied)
            finally: window.close()

    def test_optimization_routes_open_the_reorganized_destinations(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            try:
                for action, tab in (("priority", "CPU Tweaks"), ("affinity", "CPU Tweaks"),
                                    ("startup", "Startup Tweaks"), ("startup_folder", "Startup Tweaks")):
                    with patch.object(window, "open_quick_tab") as open_tab:
                        result = window.dispatch_optimization({"action": action})
                        open_tab.assert_called_once_with(tab)
                        self.assertIn(tab, result)
                with patch.object(window, "open_activity_history") as history:
                    result = window.dispatch_optimization({"action": "history"})
                    history.assert_called_once()
                    self.assertIn("Settings", result)
                with patch.object(window, "undo_last") as undo:
                    result = window.dispatch_optimization({"action": "undo"})
                    undo.assert_called_once()
                    self.assertIn("Undo", result)
            finally:
                window.close()

    def test_cancelled_direct_actions_do_not_reach_registry_or_command(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            try:
                window.ask = lambda *_: False
                window.mode.setCurrentText("On"); window.capture.setCurrentText("Off")
                with patch.object(app, "set_dword") as registry_write, patch.object(app, "command") as command:
                    window.apply_mode(); window.apply_capture(); window.flush_dns()
                    window.plan.addItem("High performance", "22222222-2222-2222-2222-222222222222")
                    window.apply_plan()
                    registry_write.assert_not_called(); command.assert_not_called()
            finally: window.close()

    def test_unknown_and_partial_registry_states_do_not_default_to_off(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            try:
                with patch.object(app, "WIN", True), patch.object(app, "reg_read", return_value=(False, None, None)):
                    window.refresh_settings()
                    self.assertEqual(window.mode.currentIndex(), -1)
                    self.assertEqual(window.capture.currentIndex(), -1)
                    window.ask = lambda *_: False
                    with patch.object(app, "set_dword") as setter, patch.object(app.QMessageBox, "information"):
                        window.apply_mode(); window.apply_capture(); setter.assert_not_called()
            finally: window.close()

    def test_local_restore_is_confirmed_and_keeps_watcher_paused(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            backup = Path(temp) / "backup.json"
            payload = {"format": app.LOCAL_BACKUP_FORMAT,
                       "settings": {"welcome_seen": True, "priority_rules_enabled": True},
                       "profiles": {"Minecraft": {"priority": "High"}},
                       "games": [{"name": "Minecraft", "path": str(Path(temp) / "javaw.exe"), "priority": "Medium"}],
                       "priority_rules": [{"name": "Game", "path": str(Path(temp) / "game.exe"), "priority": "High", "mode": "automatic", "enabled": True}]}
            backup.write_text(json.dumps(payload), encoding="utf-8")
            try:
                with patch.object(app.QFileDialog, "getOpenFileName", return_value=(str(backup), "JSON files (*.json)")), patch.object(app.QMessageBox, "information"), patch.object(app.QMessageBox, "warning"):
                    window.ask = lambda *_: False
                    window.restore_settings()
                    self.assertFalse(window.priority_rules)
                    window.ask = lambda *_: True
                    window.restore_settings()
                self.assertEqual(window.profiles["Minecraft"]["priority"], "High")
                self.assertEqual(len(window.games), 1); self.assertEqual(len(window.priority_rules), 1)
                self.assertFalse(window.settings.get("priority_rules_enabled", False))
                self.assertFalse(window.priority_timer.isActive())
            finally: window.close()

    def test_optimization_filters_and_action_confirmation_are_wired(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            try:
                window.optimization_search.setText("capture")
                visible = [row for row in range(window.optimization_table.rowCount()) if not window.optimization_table.isRowHidden(row)]
                self.assertTrue(visible)
                self.assertTrue(all("capture" in " ".join(str(value) for value in window._optimization_entries[row].values()).casefold() for row in visible))
                window.optimization_search.clear()
                target = next(i for i, entry in enumerate(window._optimization_entries) if entry["key"] == "power_plan")
                window.optimization_table.selectRow(target); window.ask = lambda *_: True
                with patch.object(window, "apply_plan") as apply_plan, patch.object(app.QMessageBox, "information"):
                    window.apply_selected_optimization()
                    apply_plan.assert_called_once()
                row_widget = window.optimization_table.cellWidget(target, 6)
                self.assertIsNotNone(row_widget)
                row_apply = row_widget.findChild(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton, "rowApply")
                self.assertIsNotNone(row_apply)
                with patch.object(window, "apply_optimization_key") as apply_key:
                    row_apply.click()
                    apply_key.assert_called_once_with("power_plan")
            finally: window.close()

    def test_game_profiles_cannot_target_protected_windows_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            window.games = [{"name": "System service", "path": r"C:\Windows\System32\svchost.exe", "priority": "High"}]
            window.game_list.addItem("System service")
            window.game_list.setCurrentRow(0)
            try:
                with patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}), \
                     patch.object(app.psutil, "process_iter") as processes, \
                     patch.object(QMessageBox, "warning") as warning:
                    window.apply_game_profile()
                    warning.assert_called_once()
                    processes.assert_not_called()
            finally:
                window.close()

    def test_game_profile_only_touches_explicitly_selected_settings(self):
        class FakeProcess:
            def __init__(self): self.priority = app.PRIORITY_VALUES["Medium"]; self.priority_writes = []
            def create_time(self): return 5.0
            def nice(self, value=None):
                if value is not None: self.priority_writes.append(value); self.priority = value
                return self.priority
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            path = str(Path(temp) / "game.exe")
            window.games = [{"name":"Game", "path":path, "priority":"Medium", "profile_key":"Fortnite"}]
            window.game_list.addItem("Game"); window.game_list.setCurrentRow(0)
            window.profiles["Fortnite"] = app.validate_profile({"game_mode":"on", "priority":"unchanged"})
            window.ask = lambda *_: True
            process = FakeProcess()
            info = {"pid":99991, "exe":path, "create_time":5.0}
            refresh = ["refresh_settings", "refresh_plans", "refresh_startup", "refresh_activity"]
            patches = [patch.object(window, name) for name in refresh]
            for item in patches: item.start()
            self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
            try:
                with patch.object(app, "WIN", True), \
                     patch.object(app, "protected_process", return_value=False), \
                     patch.object(app.psutil, "process_iter", return_value=[type("Proc", (), {"info":info})()]), \
                     patch.object(app.psutil, "Process", return_value=process), \
                     patch.object(app, "set_dword", return_value=True) as set_value, \
                     patch.object(app.QMessageBox, "information"), patch.object(app, "write_activity"):
                    window.apply_game_profile()
                set_value.assert_called_once_with(window.undo, app.GAMEBAR, "AutoGameModeEnabled", 1)
                self.assertEqual(process.priority_writes, [], "Unchanged profile priority must not touch the process")
                self.assertFalse(window.undo.items, "The mocked registry action must not create a real Undo transaction")
            finally: window.close()

    def test_process_priority_apply_and_undo_use_mocked_process(self):
        class FakeProcess:
            def __init__(self): self.created = 6.0; self.priority = app.PRIORITY_VALUES["Medium"]
            def create_time(self): return self.created
            def nice(self, value=None):
                if value is not None: self.priority = value
                return self.priority
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            process = FakeProcess(); path = str(Path(temp) / "game.exe")
            item = QListWidgetItem("game.exe PID 99992"); item.setData(app.Qt.ItemDataRole.UserRole,(99992,"game.exe",6.0,path)); window.proc_list.addItem(item); window.proc_list.setCurrentItem(item)
            window.priority.setCurrentText("High"); window.ask = lambda *_: True
            refresh = ["refresh_settings", "refresh_plans", "refresh_startup", "refresh_activity"]
            patches = [patch.object(window, name) for name in refresh]
            for value in patches: value.start()
            self.addCleanup(lambda: [value.stop() for value in reversed(patches)])
            try:
                with patch.object(app, "protected_process", return_value=False), \
                     patch.object(app.psutil, "Process", return_value=process), \
                     patch.object(app.QMessageBox, "information"), patch.object(app, "write_activity"):
                    window.apply_priority()
                    self.assertEqual(process.priority, app.PRIORITY_VALUES["High"])
                    self.assertTrue(window.undo.items)
                    ok, message = window.undo.undo()
                    self.assertTrue(ok, message)
                    self.assertEqual(process.priority, app.PRIORITY_VALUES["Medium"])
            finally: window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
