"""4.7 UI regressions: programmatic Qt APIs only, no screenshots or desktop input."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from PySide6.QtTest import QTest
import PCBoost as app
import test_gui_smoke as gui
from github_updates import compare_release


class Ui470Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def make_window(self, temp):
        window = gui.GuiReleaseTests.make_window(self, temp)
        self.addCleanup(window.close)
        return window

    def settle(self):
        for _ in range(4):
            self.qt.processEvents()
            QTest.qWait(5)

    def test_candidate_metadata_and_older_stable_release(self):
        self.assertEqual(app.APP_VERSION, '4.7.0')
        self.assertLess(compare_release(app.APP_VERSION, {'version': (4, 6, 1, 0)}), 0)
        for name in ('version_info.txt', 'updater_version_info.txt'):
            text = (Path(app.__file__).parent / name).read_text(encoding='utf-8')
            self.assertIn('(4, 7, 0, 0)', text)
            self.assertIn("'ProductVersion', '4.7.0.0'", text)

    def test_previews_do_not_probe_write_or_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            files = {p.name:p.read_bytes() for p in app.APP_DATA.glob('*') if p.is_file()}
            with patch.object(app, 'command') as command, patch.object(app, 'reg_read') as reg, \
                 patch.object(app, 'set_dword') as write, patch.object(window, 'finish_change') as finish, \
                 patch.object(app.QMessageBox, 'information') as dialog:
                for name in [*window.QUICK_TAB_NAMES, 'Gaming Tweaks', 'Power Tweaks']:
                    window.preview_quick_category(name)
                self.assertEqual(dialog.call_count, 9)
                for call in dialog.call_args_list:
                    self.assertIn('This preview does not apply changes', call.args[2])
                    self.assertIn('Undo:', call.args[2])
                command.assert_not_called(); reg.assert_not_called(); write.assert_not_called(); finish.assert_not_called()
            self.assertEqual(files, {p.name:p.read_bytes() for p in app.APP_DATA.glob('*') if p.is_file()})
            self.assertIn('watcher paused', window.quick_preview_text('CPU Tweaks'))
            self.assertIn('0 saved approved', window.quick_preview_text('Startup Tweaks'))

    def test_windows_ui_effects_apply_and_undo_use_one_confirmation_and_saved_original(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); state={"value":True}; prompts=[]
            def ui_effects(value=None):
                if value is not None: state["value"]=value; return True
                return state["value"]
            def finish(label,fn,transaction_metadata=None):
                window.undo.begin(label,transaction_metadata); result=fn(); window.undo.finish(); return result
            with patch.object(app,"WIN",True), patch.object(app,"system_menu_animation",return_value=False), \
                 patch.object(app,"system_minimize_animation",return_value=False), patch.object(app,"system_ui_effects",side_effect=ui_effects), \
                 patch.object(window,"ask",side_effect=lambda *args:(prompts.append(args) or True)), \
                 patch.object(window,"finish_change",side_effect=finish):
                window.apply_windows_tweaks()
                self.assertFalse(state["value"])
                self.assertEqual(len(prompts),1)
                self.assertIn("Windows UI effects",prompts[0][1])
                self.assertEqual(window.undo.items[-1]["actions"],[{"type":"spi_ui_effects","old":True,"expected":False}])
                ok,message=window.undo.undo_category("Windows Tweaks")
            self.assertTrue(ok,message); self.assertTrue(state["value"])

    def test_optimization_library_has_reversible_ui_effect_control_and_one_review(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); state={"value":True}
            def ui_effects(value=None):
                if value is not None: state["value"]=value; return True
                return state["value"]
            def finish(label,fn,transaction_metadata=None):
                window.undo.begin(label,transaction_metadata); result=fn(); window.undo.finish(); return result
            row=next(i for i,item in enumerate(window._optimization_entries) if item["key"]=="windows_ui_effects")
            window.optimization_table.selectRow(row)
            window.optimization_selected()
            self.assertIn("documented system-wide",window.optimization_explanation.text())
            with patch.object(app,"WIN",True), patch.object(app,"system_ui_effects",side_effect=ui_effects), \
                 patch.object(window,"ask",return_value=True) as ask, patch.object(window,"finish_change",side_effect=finish), \
                 patch.object(window,"refresh_home"), patch.object(window,"refresh_activity"), patch.object(app.QMessageBox,"information"):
                window.apply_optimization_key("windows_ui_effects")
            self.assertEqual(ask.call_count,1)
            self.assertFalse(state["value"])
            self.assertEqual(window.undo.items[-1]["label"],"Windows Tweaks")
            self.assertEqual(window.optimization_table.rowCount(),61)

    def test_builtin_preset_builder_contains_only_explicit_supported_settings(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/"game.exe"; exe.write_bytes(b"fixture")
            rules=[{"name":"Game","path":str(exe),"priority":"High","mode":"automatic","enabled":True},
                   {"name":"Paused","path":str(exe),"priority":"Low","mode":"automatic","enabled":False},
                   {"name":"One time","path":str(exe),"priority":"Low","mode":"once","enabled":True}]
            gaming=app.build_builtin_preset("Gaming",include_capture=True,include_priority=True,saved_rules=rules)
            self.assertTrue(gaming["game_mode_on"]); self.assertTrue(gaming["capture_off"])
            self.assertEqual([rule["name"] for rule in gaming["priority_rules"]],["Game"])
            self.assertNotIn("dns",gaming); self.assertNotIn("dns_provider",gaming)
            performance=app.build_builtin_preset("Performance",power_guid="11111111-1111-1111-1111-111111111111",include_visuals=True)
            self.assertEqual(performance["power_guid"],"11111111-1111-1111-1111-111111111111")
            self.assertTrue(performance["menu_animation_off"] and performance["minimize_animation_off"] and performance["ui_effects_off"])
            balanced=app.build_builtin_preset("Balanced",include_priority=True,saved_rules=rules)
            self.assertFalse(balanced["game_mode_on"] or balanced["capture_off"] or balanced["priority_rules"])
            with self.assertRaises(ValueError): app.build_builtin_preset("Extreme")

    def test_gaming_preset_uses_single_review_and_existing_restore_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); state={"exists":False,"value":None,"kind":None}; prompts=[]
            def read(key,name): return (state["exists"],state["value"],state["kind"])
            def set_value(undo,key,name,target):
                undo.record({"type":"reg","key":key,"name":name,"exists":state["exists"],"key_exists":False,"value":None,"kind":None,"expected_exists":True,"expected_value":target,"expected_kind":app.winreg.REG_DWORD})
                state.update(exists=True,value=target,kind=app.winreg.REG_DWORD)
            def finish(label,fn,transaction_metadata=None):
                window.undo.begin(label,transaction_metadata); result=fn(); window.undo.finish(); return result
            with patch.object(app,"WIN",True), patch.object(app,"reg_read",side_effect=read), patch.object(app,"set_dword",side_effect=set_value), \
                 patch.object(window,"ask",side_effect=lambda *args:(prompts.append(args) or True)), patch.object(window,"finish_change",side_effect=finish):
                window.builtin_preset_combo.setCurrentIndex(window.builtin_preset_combo.findData("Gaming"))
                window.preset_capture_check.setChecked(False); window.preset_priority_check.setChecked(False); window.preset_power_combo.setCurrentIndex(0)
                window.apply_selected_preset()
            self.assertEqual(len(prompts),1)
            self.assertIn("Turn on Windows Game Mode",prompts[0][1])
            self.assertEqual(state["value"],1)
            self.assertEqual(window.undo.items[-1]["builtin_preset"],"Gaming Preset")
            self.assertTrue(window.preset_undo_btn.isEnabled())

    def test_ui_scale_font_sizes_keep_navigation_and_quick_tweaks_reachable(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); window.show()
            for factor in (1.0,1.25,1.5,2.0):
                window.setFont(QFont("Segoe UI",max(10,round(10*factor))))
                window.resize(1280,720); self.settle()
                for index,button in enumerate(window.nav_buttons):
                    self.assertTrue(button.isVisible()); self.assertEqual(button.accessibleName(),window.PAGE_NAMES[index])
                window.select_page(1); self.settle()
                self.assertEqual(window.stack.currentWidget().horizontalScrollBar().maximum(),0)
            window.setFont(QFont("Segoe UI",10))

    def test_custom_profile_can_apply_and_restore_the_new_windows_ui_effect_setting(self):
        import uuid
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); state={"value":True}; profile_id=str(uuid.uuid4())
            profile=app.validate_custom_profile({"id":profile_id,"name":"UI Effects","ui_effects_off":True})
            window.custom_profiles=[profile]; window.refresh_custom_profiles()
            def ui_effects(value=None):
                if value is not None: state["value"]=value; return True
                return state["value"]
            def finish(label,fn,transaction_metadata=None):
                window.undo.begin(label,transaction_metadata); result=fn(); window.undo.finish(); return result
            with patch.object(app,"WIN",True), patch.object(app,"system_ui_effects",side_effect=ui_effects), \
                 patch.object(window,"ask",return_value=True) as ask, patch.object(window,"finish_change",side_effect=finish):
                window.apply_custom_profile()
                self.assertFalse(state["value"]); ask.assert_called_once()
                self.assertEqual(window.undo.items[-1]["custom_profile_id"],profile_id)
                ok,message=window.undo.undo_profile(profile_id)
            self.assertTrue(ok,message); self.assertTrue(state["value"])

    def test_network_details_query_runs_off_the_ui_thread(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            from types import SimpleNamespace
            interfaces={"Wi-Fi":[SimpleNamespace(family=2,address="10.0.0.5")]}
            stats={"Wi-Fi":SimpleNamespace(isup=True,speed=1200)}
            query_thread=[]
            def read_adapters(addresses,adapter_stats):
                query_thread.append(__import__('threading').get_ident())
                return ([{"name":"Wi-Fi","link_speed":"1200 Mbps","has_default_route":True,"dns_servers":["10.0.0.1"]}],"")
            with patch.object(app,"WIN",True), patch.object(app.psutil,"net_if_addrs",return_value=interfaces), \
                 patch.object(app.psutil,"net_if_stats",return_value=stats), patch.object(app,"query_adapters",side_effect=read_adapters), \
                 patch.object(app,"query_dns_adapters",return_value=([],"DNS test fixture")):
                window.refresh_network_details()
                self.assertIsNotNone(window._network_query_thread)
                import time
                deadline=time.monotonic()+3
                while window._network_query_thread is not None and time.monotonic()<deadline:
                    self.settle(); QTest.qWait(10)
                self.assertIsNone(window._network_query_thread)
                self.settle()
            self.assertTrue(query_thread); self.assertNotEqual(query_thread[0],__import__('threading').get_ident())
            self.assertIn("active IPv4 default-route adapter",window.adapter_text.text())
            self.assertTrue(window.adapter_refresh_btn.isEnabled())

    def test_network_adapter_details_render_speed_route_dns_and_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            from types import SimpleNamespace
            interfaces={"Wi-Fi":[SimpleNamespace(family="AF_INET",address="192.0.2.12"),SimpleNamespace(family="AF_INET6",address="2001:db8::12")]}
            stats={"Wi-Fi":SimpleNamespace(isup=True)}
            window._render_network_details({"ok":True,"interfaces":interfaces,"stats":stats,"adapters":[{"name":"Wi-Fi","link_speed":"866 Mbps","has_default_route":True,"dns_servers":["1.1.1.1"]}],"detail_error":""})
            displayed=window.adapter_text.text()
            for word in ("Wi-Fi","Up","default-route adapter","866 Mbps","192.0.2.12","1.1.1.1"):
                self.assertIn(word,displayed)
            window._render_network_details({"ok":True,"interfaces":interfaces,"stats":stats,"adapters":[],"detail_error":"Access denied"})
            self.assertIn("Access denied",window.adapter_text.text())

    def test_power_card_routes_to_existing_confirmation_handler(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            with patch.object(window, 'apply_power_tweaks') as power:
                window.power_apply_btn.click()
                power.assert_called_once_with()
            self.assertFalse(window.power_undo_btn.isEnabled())

    def test_category_undo_restores_only_latest_matching_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            window = self.make_window(temp)
            first={'label':'Windows Tweaks','actions':[]}
            chosen={'label':'Windows Tweaks','actions':[{'type':'spi_bool','old':True,'expected':False}]}
            other={'label':'Gaming Tweaks','actions':[]}
            window.undo.items=[first,chosen,other]; window.undo.save(); window.refresh_undo()
            self.assertEqual(window.quick_restore_buttons[0].text(), 'Undo category (2)')
            self.assertFalse(window.quick_restore_buttons[3].isEnabled())
            state={'animation':False}
            def animation(value=None):
                if value is not None: state['animation']=value
                return state['animation']
            with patch.object(window,'ask',return_value=True) as ask, \
                 patch.object(app,'system_menu_animation',side_effect=animation), \
                 patch.object(app.QMessageBox,'information'):
                window.quick_restore_buttons[0].click()
            self.assertTrue(state['animation'])
            self.assertEqual(window.undo.items,[first,other])
            self.assertIn('Windows Tweaks',ask.call_args.args[1])
            self.assertEqual(window.operation_state.text(),'Complete')

    def test_category_undo_conflict_preserves_newer_value_and_order(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            tx={'label':'Windows Tweaks','actions':[{'type':'spi_bool','old':True,'expected':False}]}
            other={'label':'Gaming Tweaks','actions':[]}; window.undo.items=[tx,other]
            with patch.object(window,'ask',return_value=True), \
                 patch.object(app,'system_menu_animation',return_value=None) as animation, \
                 patch.object(app.QMessageBox,'warning'):
                window.undo_quick_category('Windows Tweaks')
            animation.assert_called_once_with()
            self.assertEqual(window.undo.items,[tx,other])
            self.assertIn('newer value untouched',window.status.text())
            self.assertEqual(window.operation_state.text(),'Needs attention')

    def test_category_undo_cancel_and_empty_category_cannot_target_global_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            window.undo.items=[{'label':'Gaming Tweaks','actions':[]}]; window.refresh_undo()
            with patch.object(window.undo,'_undo_at') as undo, patch.object(window,'ask',return_value=False), \
                 patch.object(app.QMessageBox,'information'):
                window.undo_quick_category('GPU Tweaks')
                window.undo_quick_category('Gaming Tweaks')
                undo.assert_not_called()
            self.assertEqual(len(window.undo.items),1)

    def test_category_matching_keeps_profiles_separate_and_includes_manual_cpu_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            window.undo.items=[{'label':'game.exe priority','actions':[{'type':'priority'}]},
                               {'label':'Profile','custom_profile_id':'saved','actions':[{'type':'priority'}]},
                               {'label':'Fortnite game profile','actions':[{'type':'priority'}]},
                               {'label':'power plan','actions':[]}, {'label':'startup entry','actions':[]}]
            self.assertEqual([i for i,_ in window.category_transactions('CPU Tweaks')],[0])
            self.assertEqual([i for i,_ in window.category_transactions('Power Tweaks')],[3])
            self.assertEqual([i for i,_ in window.category_transactions('Startup Tweaks')],[4])

    def test_cpu_undo_explains_enabled_watcher_without_changing_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            window.settings['priority_rules_enabled']=True
            window.undo.items=[{'label':'CPU Tweaks','actions':[]}]
            with patch.object(window,'ask',return_value=False) as ask, patch.object(window.undo,'_undo_at') as undo:
                window.undo_quick_category('CPU Tweaks')
            self.assertIn('can reapply',ask.call_args.args[1])
            self.assertIn('Pause automatic rules before Undo',window.quick_preview_text('CPU Tweaks'))
            self.assertTrue(window.settings['priority_rules_enabled'])
            undo.assert_not_called()

    def test_busy_state_prevents_reentry_and_restores_disabled_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); window.power_apply_btn.setEnabled(False)
            with patch.object(window,'apply_windows_tweaks') as change, patch.object(window.undo,'_undo_at') as undo:
                window.set_busy(True,'Checking chosen settings…')
                self.assertFalse(window.nav_buttons[0].isEnabled())
                self.assertFalse(window.quick_apply_buttons[0].isEnabled())
                self.assertFalse(window.undo_btn.isEnabled())
                self.assertTrue(window.operation_progress.isVisibleTo(window))
                self.assertEqual(window.operation_progress.maximum(),0)
                window.apply_quick_category('Windows Tweaks'); window.undo_quick_category('Gaming Tweaks')
                change.assert_not_called(); undo.assert_not_called()
                nested=Mock(); window.finish_change('Nested change',nested); nested.assert_not_called()
                before=window.stack.currentIndex(); window.select_page(2)
                self.assertEqual(window.stack.currentIndex(),before)
                window.set_busy(False)
            self.assertTrue(window.nav_buttons[0].isEnabled())
            self.assertFalse(window.power_apply_btn.isEnabled())
            self.assertTrue(window.operation_progress.isHidden())

    def test_partial_failure_and_exception_have_distinct_outcomes(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            with patch.object(app.QMessageBox,'warning') as warning, patch.object(app.QMessageBox,'information') as info:
                window.finish_change('Windows Tweaks',lambda:'1 preference verified.\nFailed: access denied')
                self.assertEqual(window.operation_state.text(),'Needs attention')
                warning.assert_called_once(); info.assert_not_called()
                self.assertIn('access denied',window.status.accessibleDescription())
                def denied(): raise PermissionError('test permission denied')
                window.finish_change('Windows Tweaks',denied)
                self.assertEqual(window.operation_state.text(),'Error')
                self.assertFalse(window._operation_busy)
                self.assertTrue(window.quick_apply_buttons[0].isEnabled())
            rows=[json.loads(line) for line in app.activity_file().read_text(encoding='utf-8').splitlines()]
            self.assertEqual([row['status'] for row in rows],['partial','error'])

    def test_full_operation_details_remain_available(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); message='2 settings verified.\nFailed: one setting was denied.\nUndo is available.'
            window.set_operation_result('Needs attention',message)
            with patch.object(app.QMessageBox,'information') as dialog:
                window.operation_details_btn.click()
            self.assertEqual(dialog.call_args.args[2],message)
            self.assertEqual(window.status.textFormat(),Qt.TextFormat.PlainText)
            window.status.setText('Theme changed.')
            self.assertEqual(window.operation_state.property('severity'),'normal')

    def test_dashboard_and_quick_cards_reflow_without_page_horizontal_scroll(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); window.show()
            measurements=[]
            for width in (900,1280,1920):
                window.resize(width,800); self.settle()
                for page in (0,1):
                    window.select_page(page); self.settle()
                    scroll=window.stack.currentWidget()
                    self.assertEqual(scroll.horizontalScrollBar().maximum(),0,(width,page))
                measurements.append(window.quick_grid.columns)
                for card in window.quick_grid.cards:
                    for label in card.findChildren(QLabel):
                        self.assertLessEqual(label.geometry().right(),card.width(),label.text())
                        if label.wordWrap():
                            self.assertGreaterEqual(label.height(),label.heightForWidth(label.width()),label.text())
            self.assertEqual(measurements[0],1)
            self.assertEqual(measurements[-1],2)

    def test_scaled_font_reduces_columns_and_keeps_all_navigation_accessible(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); window.show(); window.resize(1280,800)
            window.setStyleSheet(window.styleSheet().replace('font-size:10pt','font-size:15pt'))
            window.setFont(QFont('Segoe UI',15)); window.select_page(1); self.settle()
            self.assertEqual(window.quick_grid.columns,1)
            self.assertEqual(window.stack.currentWidget().horizontalScrollBar().maximum(),0)
            for index,button in enumerate(window.nav_buttons):
                self.assertEqual(button.accessibleName(),window.PAGE_NAMES[index])
                self.assertEqual(button.focusPolicy(),Qt.FocusPolicy.StrongFocus)
            self.assertIn('QPushButton:focus',window.styleSheet())

    def test_high_contrast_theme_persists_without_mutating_profiles(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); profiles=dict(window.profiles)
            window.theme_combo.setCurrentText('High Contrast')
            self.assertEqual(window.current_theme,'High Contrast')
            self.assertIn('#ffffff',window.styleSheet())
            self.assertEqual(window.profiles,profiles)
            saved=json.loads(app.settings_file().read_text(encoding='utf-8'))
            self.assertEqual(saved['theme'],'High Contrast')
            self.assertFalse(saved.get('auto_install_updates',False))


if __name__=='__main__': unittest.main(verbosity=2)
