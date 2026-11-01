import sys,ctypes,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import PCBoost as app

class VisualPreferenceTests(unittest.TestCase):
    def test_documented_mouse_info_reader_and_writer_preserve_three_values(self):
        calls=[]
        class User32:
            values=[6,10,2]
            def SystemParametersInfoW(self,action,param,pointer,flags):
                calls.append((action,param,flags))
                array=ctypes.cast(pointer,ctypes.POINTER(ctypes.c_int*3)).contents
                if action==app.SPI_GETMOUSE:
                    for i,value in enumerate(self.values): array[i]=value
                elif action==app.SPI_SETMOUSE: self.values=list(array)
                else: return 0
                return 1
        class Windll: user32=User32()
        with patch.object(app,"WIN",True),patch.object(app.ctypes,"windll",Windll(),create=True):
            self.assertEqual(app.system_mouse_info(),(6,10,2))
            app.system_mouse_info((0,0,0))
            self.assertEqual(app.system_mouse_info(),(0,0,0))
        self.assertEqual([item[0] for item in calls],[app.SPI_GETMOUSE,app.SPI_SETMOUSE,app.SPI_GETMOUSE])
        self.assertEqual(calls[1][2],app.SPIF_UPDATEINIFILE|app.SPIF_SENDCHANGE)

    def test_mouse_acceleration_apply_and_undo_restore_exact_previous_tuple(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"undo.json"; undo=app.Undo(); undo.file=path; state={"value":(6,10,2)}
            def mouse(values=None):
                if values is not None: state["value"]=tuple(values); return True
                return state["value"]
            undo.begin("Mouse pointer acceleration")
            original=mouse(); undo.record({"type":"spi_mouse","old":list(original),"expected":[0,0,0]}); mouse((0,0,0)); undo.finish()
            with patch.object(app,"system_mouse_info",side_effect=mouse):
                ok,message=undo.undo_category("Mouse pointer acceleration")
            self.assertTrue(ok,message); self.assertEqual(state["value"],(6,10,2))

    def test_mouse_undo_refuses_to_overwrite_external_tuple(self):
        with tempfile.TemporaryDirectory() as temp:
            undo=app.Undo(); undo.file=Path(temp)/"undo.json"; undo.items=[{"label":"Mouse pointer acceleration","actions":[{"type":"spi_mouse","old":[6,10,2],"expected":[0,0,0]}]}]
            with patch.object(app,"system_mouse_info",return_value=(4,5,1)) as mouse:
                ok,message=undo.undo_category("Mouse pointer acceleration")
            self.assertFalse(ok); self.assertIn("newer values untouched",message); mouse.assert_called_once_with()

    def test_documented_ui_effects_reader_and_writer_use_expected_flags(self):
        calls=[]
        class User32:
            enabled=1
            def SystemParametersInfoW(self,action,param,pointer,flags):
                calls.append((action,param,flags))
                value=ctypes.cast(pointer,ctypes.POINTER(ctypes.c_int)).contents
                if action==app.SPI_GETUIEFFECTS: value.value=self.enabled
                elif action==app.SPI_SETUIEFFECTS: self.enabled=value.value
                else: return 0
                return 1
        class Windll: user32=User32()
        with patch.object(app,"WIN",True),patch.object(app.ctypes,"windll",Windll(),create=True):
            self.assertIs(app.system_ui_effects(),True)
            self.assertTrue(app.system_ui_effects(False))
            self.assertIs(app.system_ui_effects(),False)
        self.assertEqual([call[0] for call in calls],[app.SPI_GETUIEFFECTS,app.SPI_SETUIEFFECTS,app.SPI_GETUIEFFECTS])
        self.assertEqual(calls[1][2],app.SPIF_UPDATEINIFILE|app.SPIF_SENDCHANGE)

    def test_undo_restores_saved_ui_effects_value_and_skips_an_external_restore(self):
        state={"value":False}
        def reader(enabled=None):
            if enabled is not None: state["value"]=enabled; return True
            return state["value"]
        undo=app.Undo(); undo.items=[{"label":"Windows Tweaks","actions":[{"type":"spi_ui_effects","old":True,"expected":False}]}]
        with patch.object(app,"system_ui_effects",side_effect=reader):
            ok,message=undo.undo_category("Windows Tweaks")
        self.assertTrue(ok,message); self.assertTrue(state["value"])
        # If Windows already has the exact recorded original value, Undo is a no-op.
        undo.items=[{"label":"Windows Tweaks","actions":[{"type":"spi_ui_effects","old":True,"expected":False}]}]
        with patch.object(app,"system_ui_effects",side_effect=reader) as getter:
            ok,message=undo.undo_category("Windows Tweaks")
        self.assertTrue(ok,message); getter.assert_called_once_with(); self.assertTrue(state["value"])

    def test_custom_profile_schema_preserves_new_opt_in_field_and_old_profiles(self):
        import uuid
        base={"id":str(uuid.uuid4()),"name":"Windows visual profile","ui_effects_off":True}
        checked=app.validate_custom_profile(base)
        self.assertTrue(checked["ui_effects_off"])
        legacy=app.validate_custom_profile({"id":str(uuid.uuid4()),"name":"Legacy profile"})
        self.assertFalse(legacy["ui_effects_off"])

if __name__=="__main__": unittest.main(verbosity=2)
