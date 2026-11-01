"""Offscreen DNS-control integration tests; all Windows effects are mocked."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import PCBoost as app
import test_gui_smoke as gui
from PySide6.QtWidgets import QApplication, QMessageBox


def adapter(source="dhcp", servers=None, index=7):
    servers=servers or {"ipv4":[],"ipv6":[]}
    families={}
    for family in ("ipv4","ipv6"):
        families[family]={"source":source,"servers":list(servers[family]),"register":"primary","supported":True,"reason":""}
    return {"interface_index":index,"alias":"Test adapter","is_default_route":True,"families":families,"supported":True,"reason":""}


class DnsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.qt=QApplication.instance() or QApplication([])

    def make_window(self,temp):
        data=Path(temp)/"appdata"; data.mkdir()
        (data/"settings.json").write_text('{"welcome_seen":true}',encoding="utf-8")
        patches=[patch.object(app,"APP_DATA",data),patch.object(app,"LEGACY_APP_DATA",Path(temp)/"none"),
                 patch.object(app,"WIN",False),patch.object(app,"admin",return_value=False),
                 patch.object(app,"fetch_latest_release",side_effect=RuntimeError("offline")),
                 patch.object(app,"plans",return_value=[]),patch.object(app,"active_plan",return_value=(None,"unavailable")),
                 patch.object(app,"gpu",return_value=(None,None,None)),patch.object(app,"startup_entries",return_value=[]),
                 patch.object(app,"startup_folder_entries",return_value=[])]
        for item in patches:item.start()
        self.addCleanup(lambda:[item.stop() for item in reversed(patches)])
        window=app.Window(); self.addCleanup(window.close); return window

    def load_adapter(self,window,snapshot):
        window._dns_adapters=[copy.deepcopy(snapshot)]
        window.update_dns_adapter_list()

    def patch_finish_refreshes(self):
        return [patch.object(app.Window,name) for name in ("refresh_settings","refresh_plans","refresh_startup","refresh_custom_profile_controls","refresh_activity","refresh_preset_controls","refresh_home","refresh_network_details")]

    def test_page_exposes_adapter_provider_custom_undo_and_network_safety_note(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            self.assertEqual(window.dns_mode_combo.count(),5)
            self.assertEqual(window.dns_adapter_combo.accessibleName(),"Network adapter for DNS configuration")
            self.assertEqual(window.dns_custom_input.accessibleName(),"Custom DNS server IP addresses")
            self.assertTrue(any("do not guarantee lower ping" in label.text().casefold() for label in window.findChildren(type(window.dns_state_label))))
            self.assertTrue(hasattr(window,"dns_undo_config_btn"))

    def test_mouse_acceleration_button_uses_one_confirmation_and_exact_undo(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); state={"value":(6,10,2)}; prompts=[]
            def reader(values=None):
                if values is not None: state["value"]=tuple(values); return True
                return state["value"]
            def finish(label,fn,transaction_metadata=None):
                window.undo.begin(label,transaction_metadata); result=fn(); window.undo.finish(); return result
            with patch.object(app,"WIN",True),patch.object(app,"system_mouse_info",side_effect=reader), \
                 patch.object(window,"ask",side_effect=lambda *args:(prompts.append(args) or True)), \
                 patch.object(window,"finish_change",side_effect=finish):
                window.apply_mouse_acceleration()
                self.assertEqual(state["value"],(0,0,0)); self.assertEqual(len(prompts),1)
                self.assertEqual(window.undo.items[-1]["actions"],[{"type":"spi_mouse","old":[6,10,2],"expected":[0,0,0]}])
                ok,message=window.undo.undo_category("Mouse pointer acceleration")
            self.assertTrue(ok,message); self.assertEqual(state["value"],(6,10,2))

    def test_apply_provider_uses_one_confirmation_journals_before_writes_and_verifies_both_families(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); current=adapter(); self.load_adapter(window,current)
            window.dns_mode_combo.setCurrentIndex(window.dns_mode_combo.findData("cloudflare"))
            calls=[]
            def writer(index,alias,version,target):
                calls.append((version,copy.deepcopy(current["families"]["ipv4" if version==4 else "ipv6"])))
                current["families"]["ipv4" if version==4 else "ipv6"]={**copy.deepcopy(target),"supported":True}
            refreshes=self.patch_finish_refreshes()
            for item in refreshes:item.start()
            self.addCleanup(lambda:[item.stop() for item in reversed(refreshes)])
            with patch.object(app,"WIN",True),patch.object(app,"admin",return_value=True),patch.object(window,"ask",return_value=True) as ask, \
                 patch.object(app,"query_dns_adapters",side_effect=lambda **kwargs:([copy.deepcopy(current)],"")), \
                 patch.object(app,"set_dns_family",side_effect=writer),patch.object(QMessageBox,"information"),patch.object(QMessageBox,"warning"):
                window.update_dns_controls(); self.assertTrue(window.dns_apply_config_btn.isEnabled()); window.dns_apply_config_btn.click()
            self.assertEqual(ask.call_count,1,window.status.text())
            self.assertEqual([item[0] for item in calls],[4,6],window.status.text())
            self.assertTrue(all(item[1]["source"]=="dhcp" for item in calls))
            self.assertEqual(current["families"]["ipv4"]["servers"],["1.1.1.1","1.0.0.1"])
            self.assertEqual(current["families"]["ipv6"]["servers"],["2606:4700:4700::1111","2606:4700:4700::1001"])
            tx=window.undo.items[-1]
            self.assertEqual(tx["label"],"DNS configuration")
            self.assertEqual([item["family"] for item in tx["actions"]],[4,6])
            self.assertEqual(tx["actions"][0]["old"]["source"],"dhcp")

    def test_cancel_and_already_configured_make_no_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            preset={"ipv4":["1.1.1.1","1.0.0.1"],"ipv6":["2606:4700:4700::1111","2606:4700:4700::1001"]}
            snapshot=adapter("static",preset); self.load_adapter(window,snapshot)
            window.dns_mode_combo.setCurrentIndex(window.dns_mode_combo.findData("cloudflare"))
            with patch.object(app,"WIN",True),patch.object(app,"admin",return_value=True),patch.object(window,"ask",return_value=False) as ask, \
                 patch.object(app,"query_dns_adapters",return_value=([snapshot],"")) as query,patch.object(app,"set_dns_family") as writer,patch.object(QMessageBox,"information") as info:
                window.apply_dns_configuration()
                self.assertFalse(window.undo.items); writer.assert_not_called(); ask.assert_not_called(); query.assert_not_called()
                # Change the target provider so one confirmation is shown, then cancel.
                window.dns_mode_combo.setCurrentIndex(window.dns_mode_combo.findData("google"))
                window.apply_dns_configuration()
                ask.assert_called_once(); writer.assert_not_called(); self.assertFalse(window.undo.items)

    def test_standard_user_is_not_elevated_and_gets_clear_message(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); self.load_adapter(window,adapter())
            with patch.object(app,"WIN",True),patch.object(app,"admin",return_value=False),patch.object(app,"query_dns_adapters") as query, \
                 patch.object(app,"set_dns_family") as writer,patch.object(QMessageBox,"warning") as warning:
                window.apply_dns_configuration()
            query.assert_not_called(); writer.assert_not_called(); warning.assert_called_once()
            self.assertIn("will not elevate",warning.call_args.args[2])

    def test_partial_failure_keeps_category_undo_records(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); current=adapter(); self.load_adapter(window,current)
            window.dns_mode_combo.setCurrentIndex(window.dns_mode_combo.findData("google"))
            def writer(index,alias,version,target):
                if version==6: raise PermissionError("IPv6 access denied")
                current["families"]["ipv4"]={**copy.deepcopy(target),"supported":True}
            refreshes=self.patch_finish_refreshes()
            for item in refreshes:item.start()
            self.addCleanup(lambda:[item.stop() for item in reversed(refreshes)])
            with patch.object(app,"WIN",True),patch.object(app,"admin",return_value=True),patch.object(window,"ask",return_value=True), \
                 patch.object(app,"query_dns_adapters",side_effect=lambda **kwargs:([copy.deepcopy(current)],"")), \
                 patch.object(app,"set_dns_family",side_effect=writer),patch.object(QMessageBox,"information"),patch.object(QMessageBox,"warning") as warning:
                window.update_dns_controls(); window.apply_dns_configuration()
            self.assertEqual([a["family"] for a in window.undo.items[-1]["actions"]],[4,6])
            self.assertEqual(window.operation_state.text(),"Needs attention")
            self.assertTrue(warning.called)

    def test_undo_conflict_does_not_overwrite_newer_dns_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp); original=adapter(); expected={"source":"static","servers":["1.1.1.1"],"register":"primary"}
            action={"type":"dns_family","interface_index":7,"alias":"Test adapter","family":4,
                    "old":original["families"]["ipv4"],"expected":expected,"expected_variants":[expected]}
            window.undo.items=[{"label":"DNS configuration","actions":[action]}]
            changed=adapter("static",{"ipv4":["9.9.9.9"],"ipv6":[]})
            import network_dns
            with patch.object(network_dns,"query_dns_adapters",return_value=([changed],"")),patch.object(app,"set_dns_family") as writer:
                ok,message=window.undo.undo_category("DNS configuration")
            self.assertFalse(ok); self.assertIn("newer configuration untouched",message); writer.assert_not_called()
            self.assertEqual(len(window.undo.items),1)

    def test_dns_catalog_action_routes_to_actual_network_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            window=self.make_window(temp)
            row=next(i for i,item in enumerate(window._optimization_entries) if item["key"]=="dns_manage")
            widget=window.optimization_table.cellWidget(row,6)
            self.assertEqual(widget.findChildren(__import__("PySide6.QtWidgets",fromlist=["QPushButton"]).QPushButton)[0].text(),"Configure")
            window.apply_optimization_key("dns_manage")
            self.assertEqual(window.stack.currentIndex(),window.PAGE_NAMES.index("Network"))


if __name__=="__main__": unittest.main(verbosity=2)
