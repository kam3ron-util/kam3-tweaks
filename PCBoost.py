from __future__ import annotations
import base64, csv, ctypes, json, os, platform, re, subprocess, sys, time, threading, datetime, webbrowser
import hashlib, shutil, uuid, ipaddress
import threading, subprocess
from pathlib import Path
from typing import Any
try:
    import psutil
except ImportError as exc:
    raise SystemExit("Install dependencies with: python -m pip install -r requirements.txt") from exc
try:
    import winreg
except ImportError:
    winreg = None
# PyInstaller's one-file Qt DLLs live under _MEIPASS\PySide6. Put that directory
# ahead of inherited PATH entries so an unrelated Qt/ICU install cannot shadow
# the app's matching DLLs (a common conflict when launched from developer tools).
_dll_directory_handles=[]
if os.name=="nt" and getattr(sys,"frozen",False):
    _qt_dll_dir=Path(sys._MEIPASS)/"PySide6"
    if _qt_dll_dir.is_dir():
        try: _dll_directory_handles.append(os.add_dll_directory(str(_qt_dll_dir)))
        except (AttributeError,OSError): pass
        os.environ["PATH"]=str(_qt_dll_dir)+os.pathsep+str(sys._MEIPASS)+os.pathsep+os.environ.get("PATH","")
from PySide6.QtCore import Qt, QTimer, QObject, Signal, QRectF, QThread
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QPen, QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget, QScrollArea,
    QFormLayout, QCheckBox, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox, QTabWidget, QProgressBar)

from ui_components import ResponsiveGrid, StatusLabel
from network_info import query_adapters, NetworkQueryError
from network_dns import (query_dns_adapters, make_target as make_dns_target,
                         set_dns_family, restore_dns_action, config_matches as dns_config_matches,
                         possible_write_results, DnsConfigurationError)
from pcboost21 import validate_profile
from pcboost40 import CATALOG as OPTIMIZATION_CATALOG, validate_catalog
from github_updates import fetch_latest_release, compare_release, RELEASES_URL
from update_trust import PINNED_PUBLIC_KEY_B64
from update_security import (verification_ready, pinned_key_fingerprint, VerificationUnavailable,
                             EXPECTED_UPDATER, verify_updater)
from update_download import download_verified_update, DownloadCancelled
from update_installer import create_install_request, write_startup_health

APP_NAME = "Kam3 Tweaks"
APP_VERSION = "4.7.0"
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DATA_ROOT = Path(os.environ.get("APPDATA") or Path.home())
LEGACY_APP_DATA = APP_DATA_ROOT / "PCBoost"
APP_DATA = APP_DATA_ROOT / "Kam3 Tweaks"
WIN = os.name == "nt"
PRIORITY_VALUES={"High":getattr(psutil,"HIGH_PRIORITY_CLASS",128),"Medium":getattr(psutil,"NORMAL_PRIORITY_CLASS",0),"Low":getattr(psutil,"BELOW_NORMAL_PRIORITY_CLASS",10)}
GAMEBAR = r"Software\Microsoft\GameBar"
CAPTURE = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
GAMECONFIG = r"System\GameConfigStore"
THEME_PALETTES = {
    "Violet Aurora": {"bg":"#0e0b17","sidebar":"#151020","surface":"#1c172b","raised":"#282039","input":"#120e1e","border":"#423452","text":"#f6f2ff","muted":"#bcb2ce","accent":"#b69aff","accent2":"#6944b6","accentText":"#ffffff","select":"#3c2e57"},
    "High Contrast": {"bg":"#080808","sidebar":"#080808","surface":"#101010","raised":"#161616","input":"#080808","border":"#dddddd","text":"#ffffff","muted":"#dddddd","accent":"#ffdf80","accent2":"#ffdf80","accentText":"#080808","select":"#303030"},
    "Midnight Blue": {"bg":"#10151d","sidebar":"#141d29","surface":"#1a2532","raised":"#223243","input":"#111b26","border":"#30485e","text":"#eff5fb","muted":"#a3b3c2","accent":"#79b9ee","accent2":"#3b83bd","accentText":"#071521","select":"#284259"},
    "Graphite Rose": {"bg":"#171318","sidebar":"#201820","surface":"#281e29","raised":"#342536","input":"#1c151d","border":"#483448","text":"#faf1f7","muted":"#c1aebc","accent":"#e29acb","accent2":"#a45b91","accentText":"#25131f","select":"#50334b"},
}

_STYLE_TEMPLATE = """
* { color:@TEXT@; font-family:'Inter','Segoe UI'; font-size:10pt; }
QMainWindow,QWidget#root { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 @BG@,stop:1 @SURFACE@); }
QLabel { background:transparent; }
QWidget#sidebar { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 @SIDEBAR@,stop:1 @BG@); border-right:1px solid @BORDER@; }
QLabel#brandMark { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 @ACCENT2@,stop:1 @ACCENT@); color:@ACCENTTEXT@; border:1px solid @ACCENT@; border-radius:12px; font-size:14pt; font-weight:800; }
QLabel#brand { color:@TEXT@; font-size:15pt; font-weight:750; letter-spacing:0.2px; }
QLabel#eyebrow { color:@MUTED@; font-size:8pt; font-weight:700; letter-spacing:1px; }
QLabel#pageTitle { color:@TEXT@; font-size:22pt; font-weight:750; }
QLabel#heroTitle { color:#ffffff; font-size:28pt; font-weight:800; }
QLabel#sectionTitle { color:@TEXT@; font-size:12pt; font-weight:700; }
QLabel#muted { color:@MUTED@; }
QLabel#metricValue { color:@ACCENT@; font-size:20pt; font-weight:750; }
QLabel#metricName { color:@MUTED@; font-size:8pt; font-weight:700; letter-spacing:0.7px; }
QLabel#statusPill { color:@TEXT@; background:@RAISED@; border:1px solid @BORDER@; border-radius:10px; padding:6px 10px; font-size:9pt; font-weight:700; }
QFrame#panel,QFrame#metricCard,QFrame#overviewCard { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 @SURFACE@,stop:1 @RAISED@); border:1px solid @BORDER@; border-radius:14px; }
QFrame#panel { border-top:1px solid @ACCENT@; }
QFrame#metricCard,QFrame#overviewCard { min-height:86px; }
QFrame#heroPanel { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 @ACCENT2@,stop:0.48 @SURFACE@,stop:1 @BG@); border:1px solid @ACCENT@; border-radius:22px; }
QFrame#categoryCard { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 @RAISED@,stop:1 @SURFACE@); border:1px solid @BORDER@; border-radius:16px; }
QFrame#categoryCard:hover { border:1px solid @ACCENT@; }
QPushButton { background:@RAISED@; border:1px solid @BORDER@; border-radius:9px; padding:8px 12px; font-weight:650; }
QPushButton:hover { border-color:@ACCENT@; background:@SELECT@; }
QPushButton:pressed { background:@SURFACE@; }
QPushButton:disabled { color:#777386; background:@INPUT@; border-color:@BORDER@; }
QPushButton#primary,QPushButton#categoryApply { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 @ACCENT2@,stop:1 @ACCENT2@); color:@ACCENTTEXT@; border:1px solid @ACCENT@; font-weight:750; padding:9px 14px; }
QPushButton#primary:hover,QPushButton#categoryApply:hover { border:1px solid #ffffff; }
QPushButton#nav { text-align:left; border:1px solid transparent; border-left:3px solid transparent; border-radius:10px; padding:10px 10px; color:@MUTED@; background:transparent; font-size:10pt; }
QPushButton#nav:hover { color:@TEXT@; background:@RAISED@; }
QPushButton#nav:checked { color:@TEXT@; background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 @SELECT@,stop:1 @SURFACE@); border:1px solid @BORDER@; border-left:3px solid @ACCENT@; }
QLineEdit,QComboBox,QListWidget,QTableWidget { background:@INPUT@; border:1px solid @BORDER@; border-radius:9px; padding:7px 9px; selection-background-color:@SELECT@; }
QLineEdit:focus,QComboBox:focus,QListWidget:focus,QTableWidget:focus { border:1px solid @ACCENT@; }
QComboBox QAbstractItemView { background:@SURFACE@; selection-background-color:@SELECT@; }
QListWidget::item { padding:8px; border-radius:6px; }
QListWidget::item:selected { background:@SELECT@; color:@TEXT@; }
QTableWidget { gridline-color:@BORDER@; alternate-background-color:@SURFACE@; }
QHeaderView::section { background:@RAISED@; color:@MUTED@; border:0; border-bottom:1px solid @BORDER@; padding:9px; font-weight:700; }
QTableWidget::item { padding:5px; }
QCheckBox { spacing:8px; font-weight:600; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid @BORDER@; border-radius:5px; background:@INPUT@; }
QCheckBox::indicator:checked { background:@ACCENT2@; border-color:@ACCENT@; }
QTabWidget::pane { background:@SURFACE@; border:1px solid @BORDER@; border-radius:12px; top:-1px; }
QTabBar::tab { background:@INPUT@; border:1px solid @BORDER@; border-bottom:0; padding:9px 12px; margin-right:4px; border-top-left-radius:9px; border-top-right-radius:9px; color:@MUTED@; }
QTabBar::tab:selected { color:@TEXT@; background:@SELECT@; border-color:@ACCENT@; }
QScrollArea { border:0; background:transparent; }
QScrollArea > QWidget > QWidget { background:transparent; }
QDialog,QMessageBox { background:@BG@; }
QFrame#operationPanel { background:@SIDEBAR@; border:1px solid @BORDER@; border-radius:12px; }
QPushButton:focus,QCheckBox:focus,QTabBar::tab:focus { border:2px solid @ACCENT@; }
QLabel#statusPill[severity="error"] { color:#ffb6c1; border-color:#b96983; }
QProgressBar { background:@INPUT@; border:0; border-radius:2px; }
QProgressBar::chunk { background:@ACCENT@; border-radius:2px; }
QToolTip { background:@RAISED@; color:@TEXT@; border:1px solid @ACCENT@; padding:7px; }
QFrame#separator { background:@BORDER@; max-height:1px; }
"""

def theme_stylesheet(name="Violet Aurora"):
    palette=THEME_PALETTES.get(name,THEME_PALETTES["Violet Aurora"])
    replacements={"@BG@":palette["bg"],"@SIDEBAR@":palette["sidebar"],"@SURFACE@":palette["surface"],"@RAISED@":palette["raised"],"@INPUT@":palette["input"],"@BORDER@":palette["border"],"@TEXT@":palette["text"],"@MUTED@":palette["muted"],"@ACCENT@":palette["accent"],"@ACCENT2@":palette["accent2"],"@ACCENTTEXT@":palette["accentText"],"@SELECT@":palette["select"]}
    result=_STYLE_TEMPLATE
    for key,value in replacements.items(): result=result.replace(key,value)
    return result

STYLE = theme_stylesheet("Violet Aurora")

def command(args: list[str], timeout: float = 5) -> tuple[int,str,str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, shell=False, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0) if WIN else 0)
        return p.returncode,p.stdout.strip(),p.stderr.strip()
    except (OSError,subprocess.TimeoutExpired) as e:
        return 1,"",str(e)

def reg_read(path: str, name: str) -> tuple[bool,Any,int|None]:
    if not WIN or winreg is None: raise RuntimeError("Windows settings are only available on Windows.")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_QUERY_VALUE) as k:
            v,t=winreg.QueryValueEx(k,name); return True,v,t
    except FileNotFoundError: return False,None,None

def reg_key_exists(path: str) -> bool:
    if not WIN or winreg is None: raise RuntimeError("Windows settings are only available on Windows.")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_QUERY_VALUE): return True
    except FileNotFoundError: return False

def game_mode_status():
    if not WIN: return "Unavailable outside Windows",None
    exists,value,_=reg_read(GAMEBAR,"AutoGameModeEnabled")
    if not exists: return "Not configured",None
    if value not in (0,1): return f"Unexpected value ({value!r})",None
    return ("On" if value==1 else "Off"),bool(value)

def capture_status():
    if not WIN: return "Unavailable outside Windows",None
    values=[reg_read(k,n) for k,n in ((CAPTURE,"AppCaptureEnabled"),(GAMECONFIG,"GameDVR_Enabled"))]
    configured=[(value,kind) for exists,value,kind in values if exists]
    if not configured: return "Not configured",None
    if any(value not in (0,1) for value,_ in configured): return "Unexpected value",None
    distinct={value for value,_ in configured}
    if len(distinct)>1: return "Mixed values",None
    state="On" if next(iter(distinct))==1 else "Off"
    return (state if len(configured)==2 else f"Partially configured · {state}"), (next(iter(distinct))==1 if len(configured)==2 else None)

def encode(v: Any) -> Any:
    return {"bytes":base64.b64encode(v).decode()} if isinstance(v,bytes) else v

def decode(v: Any) -> Any:
    return base64.b64decode(v["bytes"]) if isinstance(v,dict) and "bytes" in v else v

class Undo:
    def __init__(self):
        self.file=APP_DATA/"undo.json"; self.items=[]; self.current=None
        try:
            data=json.loads(self.file.read_text(encoding="utf-8"))
            if isinstance(data,list): self.items=data
        except (OSError,ValueError,TypeError): pass
    def save(self):
        self.file.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items,indent=2),encoding="utf-8")
        tmp.replace(self.file)
    def begin(self,label,metadata=None):
        self.current={"label":label,"actions":[]}
        if isinstance(metadata,dict): self.current.update(metadata)
    def record(self,action):
        if self.current is None: raise RuntimeError("Undo transaction not active.")
        if not self.current["actions"]: self.items.append(self.current)
        self.current["actions"].append(action); self.save()
    def finish(self):
        if self.current and not self.current["actions"] and self.current in self.items: self.items.remove(self.current)
        self.current=None; self.save()
    @property
    def label(self): return self.items[-1]["label"] if self.items else ""
    def undo(self):
        if not self.items: return False,"Nothing to undo."
        tx=self.items[-1]; left=[]; errors=[]
        for a in reversed(tx["actions"]):
            try:
                if a["type"]=="reg":
                    now_exists,now_value,now_kind=reg_read(a["key"],a["name"])
                    old=(bool(a["exists"]),decode(a.get("value")),a.get("kind"))
                    current=(now_exists,now_value,now_kind)
                    if "expected_exists" in a:
                        expected=(bool(a["expected_exists"]),decode(a.get("expected_value")),a.get("expected_kind"))
                        if current==old: continue
                        if current!=expected: raise RuntimeError("This registry value changed after Kam3 Tweaks applied it. Undo did not overwrite the newer value; review it in Windows and try again.")
                    if a["exists"]:
                        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,a["key"],0,winreg.KEY_SET_VALUE) as k:
                            winreg.SetValueEx(k,a["name"],0,a["kind"],decode(a["value"]))
                    else:
                        if now_exists:
                            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,a["key"],0,winreg.KEY_SET_VALUE) as k: winreg.DeleteValue(k,a["name"])
                        if not a.get("key_exists",True):
                            try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER,a["key"])
                            except FileNotFoundError: pass
                            except OSError: pass  # Preserve any unrelated values that now use the key.
                elif a["type"]=="power":
                    current,_=active_plan()
                    if not current: raise RuntimeError("Windows could not identify the active power plan; Undo left the current selection untouched.")
                    if current.casefold()==a["guid"].casefold(): continue
                    expected=a.get("expected")
                    if not expected: raise RuntimeError("This older Undo record has no verified post-change power-plan GUID; Undo cannot safely detect conflicts.")
                    if current.casefold()!=expected.casefold(): raise RuntimeError("The active power plan changed after Kam3 Tweaks switched it. Undo did not replace the newer choice.")
                    c,o,e=command(["powercfg","/setactive",a["guid"]])
                    if c: raise RuntimeError(e or o or "Power plan restore failed.")
                    restored,_=active_plan()
                    if not restored or restored.casefold()!=a["guid"].casefold(): raise RuntimeError("Windows did not verify the exact prior power plan after Undo.")
                elif a["type"]=="spi_bool":
                    current=system_menu_animation()
                    if current==bool(a["old"]): continue
                    if current!=bool(a["expected"]): raise RuntimeError("This Windows preference changed after Kam3 Tweaks applied it. Undo left the newer value untouched.")
                    system_menu_animation(bool(a["old"]))
                    if system_menu_animation()!=bool(a["old"]): raise RuntimeError("Windows menu-animation restore verification failed.")
                elif a["type"]=="spi_minimize_animation":
                    current=system_minimize_animation()
                    if current==bool(a["old"]): continue
                    if current!=bool(a["expected"]): raise RuntimeError("The minimize/restore animation preference changed after apply; Undo left the newer value untouched.")
                    system_minimize_animation(bool(a["old"]))
                    if system_minimize_animation()!=bool(a["old"]): raise RuntimeError("Minimize/restore animation restore verification failed.")
                elif a["type"]=="spi_ui_effects":
                    current=system_ui_effects()
                    if current==bool(a["old"]): continue
                    if current!=bool(a["expected"]): raise RuntimeError("The Windows UI-effects preference changed after apply; Undo left the newer value untouched.")
                    system_ui_effects(bool(a["old"]))
                    if system_ui_effects()!=bool(a["old"]): raise RuntimeError("Windows UI-effects restore verification failed.")
                elif a["type"]=="spi_mouse":
                    current=system_mouse_info()
                    old=tuple(a["old"]); expected=tuple(a["expected"])
                    if current==old: continue
                    if current!=expected: raise RuntimeError("Mouse acceleration settings changed after apply; Undo left the newer values untouched.")
                    system_mouse_info(old)
                    if system_mouse_info()!=old: raise RuntimeError("Mouse acceleration restore verification failed.")
                elif a["type"]=="dns_family":
                    ok,message=restore_dns_action(a)
                    if not ok: raise RuntimeError(message)
                elif a["type"]=="priority":
                    p=psutil.Process(a["pid"])
                    if abs(p.create_time()-a["created"])>.02: raise RuntimeError("Process closed or PID reused.")
                    current=p.nice()
                    if current==a["old"]: continue
                    if "expected" in a and current!=a["expected"]: raise RuntimeError("Process priority changed after Kam3 Tweaks applied it; Undo left the newer priority intact.")
                    p.nice(a["old"])
                elif a["type"]=="affinity":
                    p=psutil.Process(a["pid"])
                    if abs(p.create_time()-a["created"])>.02: raise RuntimeError("Process closed or PID reused.")
                    current=sorted(p.cpu_affinity())
                    if current==sorted(a["old"]): continue
                    if "expected" in a and current!=sorted(a["expected"]): raise RuntimeError("Process affinity changed after Kam3 Tweaks applied it; Undo left the newer affinity intact.")
                    p.cpu_affinity(a["old"])
                elif a["type"]=="startup_move":
                    restore_startup_shortcut(a)
            except Exception as e: left.append(a); errors.append(str(e))
        if left:
            tx["actions"]=list(reversed(left)); self.save()
            return False,"Some settings could not be restored: "+"; ".join(errors[:3])
        self.items.pop(); self.save(); return True,"Undid "+tx.get("display_label",tx["label"])+"."

    def _undo_at(self,index):
        tx=self.items.pop(index); self.items.append(tx)
        try: ok,message=self.undo()
        except Exception as exc: ok,message=False,str(exc)
        if not ok and self.items and self.items[-1] is tx:
            failed=self.items.pop(); self.items.insert(min(index,len(self.items)),failed)
        self.save()
        return ok,message

    def undo_category(self,label):
        """Undo a named transaction out of order; each action's expected value guards newer edits."""
        matches=[i for i,item in enumerate(self.items) if item.get("label")==label]
        if not matches: return False,f"No saved {label} transaction is available."
        return self._undo_at(matches[-1])

    def undo_profile(self,profile_id):
        matches=[i for i,item in enumerate(self.items) if item.get("custom_profile_id")==profile_id]
        if not matches: return False,"No saved changes are available for this profile."
        return self._undo_at(matches[-1])

def set_dword(undo: Undo,key: str,name: str,value: int) -> bool:
    exists,old,kind=reg_read(key,name)
    if exists and old==value and kind==winreg.REG_DWORD: return False
    undo.record({"type":"reg","key":key,"name":name,"exists":exists,"key_exists":reg_key_exists(key),"value":encode(old),"kind":kind,"expected_exists":True,"expected_value":value,"expected_kind":winreg.REG_DWORD})
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k,name,0,winreg.REG_DWORD,value)
    return True

def plans():
    if not WIN: return []
    c,o,_=command(["powercfg","/list"])
    if c: return []
    pat=r"([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})\s*\((.*?)\)"
    return [(m.group(1),m.group(2)) for m in re.finditer(pat,o)]

def active_plan():
    if not WIN: return None,"Unavailable outside Windows"
    c,o,e=command(["powercfg","/getactivescheme"])
    m=re.search(r"([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})\s*\((.*?)\)",o)
    return (m.group(1),m.group(2)) if not c and m else (None,e or o or "Power plan unavailable")

SPI_GETANIMATION=0x0048
SPI_SETANIMATION=0x0049
SPI_GETMENUANIMATION=0x1002
SPI_SETMENUANIMATION=0x1003
SPI_GETUIEFFECTS=0x103E
SPI_SETUIEFFECTS=0x103F
SPI_GETMOUSE=0x0003
SPI_SETMOUSE=0x0004
SPIF_UPDATEINIFILE=0x01
SPIF_SENDCHANGE=0x02

def system_menu_animation(enabled=None):
    """Read or write the documented Windows menu-animation preference."""
    if not WIN: raise RuntimeError("Windows system preferences are unavailable on this platform.")
    value=ctypes.c_int()
    if enabled is None:
        ok=ctypes.windll.user32.SystemParametersInfoW(SPI_GETMENUANIMATION,0,ctypes.byref(value),0)
        if not ok: raise ctypes.WinError()
        return bool(value.value)
    value=ctypes.c_int(1 if enabled else 0)
    ok=ctypes.windll.user32.SystemParametersInfoW(SPI_SETMENUANIMATION,0,ctypes.byref(value),SPIF_UPDATEINIFILE|SPIF_SENDCHANGE)
    if not ok: raise ctypes.WinError()
    return True

class _AnimationInfo(ctypes.Structure):
    _fields_=[("cbSize",ctypes.c_uint),("iMinAnimate",ctypes.c_int)]

def system_minimize_animation(enabled=None):
    """Read or set the documented Windows minimize/restore animation option."""
    if not WIN: raise RuntimeError("Windows system preferences are unavailable on this platform.")
    info=_AnimationInfo(ctypes.sizeof(_AnimationInfo),0 if enabled is None else (1 if enabled else 0))
    if enabled is None:
        ok=ctypes.windll.user32.SystemParametersInfoW(SPI_GETANIMATION,ctypes.sizeof(info),ctypes.byref(info),0)
        if not ok: raise ctypes.WinError()
        return bool(info.iMinAnimate)
    ok=ctypes.windll.user32.SystemParametersInfoW(SPI_SETANIMATION,ctypes.sizeof(info),ctypes.byref(info),SPIF_UPDATEINIFILE|SPIF_SENDCHANGE)
    if not ok: raise ctypes.WinError()
    return True


def system_ui_effects(enabled=None):
    """Read or set the documented Windows-wide optional UI-effects switch."""
    if not WIN: raise RuntimeError("Windows system preferences are unavailable on this platform.")
    value=ctypes.c_int()
    if enabled is None:
        ok=ctypes.windll.user32.SystemParametersInfoW(SPI_GETUIEFFECTS,0,ctypes.byref(value),0)
        if not ok: raise ctypes.WinError()
        return bool(value.value)
    value=ctypes.c_int(1 if enabled else 0)
    ok=ctypes.windll.user32.SystemParametersInfoW(SPI_SETUIEFFECTS,0,ctypes.byref(value),SPIF_UPDATEINIFILE|SPIF_SENDCHANGE)
    if not ok: raise ctypes.WinError()
    return True

def system_mouse_info(values=None):
    """Read or set the two mouse acceleration thresholds and level."""
    if not WIN: raise RuntimeError("Windows mouse preferences are unavailable on this platform.")
    if values is None:
        data=(ctypes.c_int*3)()
        ok=ctypes.windll.user32.SystemParametersInfoW(SPI_GETMOUSE,0,ctypes.byref(data),0)
        if not ok: raise ctypes.WinError()
        return tuple(int(value) for value in data)
    if not isinstance(values,(tuple,list)) or len(values)!=3 or any(not isinstance(value,int) or value<0 for value in values):
        raise ValueError("Mouse acceleration state must contain three nonnegative integers.")
    data=(ctypes.c_int*3)(*values)
    ok=ctypes.windll.user32.SystemParametersInfoW(SPI_SETMOUSE,0,ctypes.byref(data),SPIF_UPDATEINIFILE|SPIF_SENDCHANGE)
    if not ok: raise ctypes.WinError()
    return True

_GPU_DETAILS = {}

def gpu():
    """Read only the NVIDIA adapter name and driver for compatibility."""
    global _GPU_DETAILS
    if not WIN: _GPU_DETAILS={}; return None,None,None
    try:
        code,out,_=command(["nvidia-smi","--query-gpu=name,driver_version","--format=csv,noheader,nounits"],1.5)
        if code:
            # Old driver tools may expose the GPU name but not driver_version.
            code,out,_=command(["nvidia-smi","--query-gpu=name","--format=csv,noheader,nounits"],1.5)
        if code: _GPU_DETAILS={}; return None,None,None
        row=next(csv.reader(out.splitlines(),skipinitialspace=True),[])
        name=row[0].strip() if row else ""
        driver=row[1].strip() if len(row)>1 else None
        _GPU_DETAILS={"driver":driver or None}
        return (name or None),None,None
    except (ValueError,csv.Error): _GPU_DETAILS={}
    return None,None,None

def gpu_adapters():
    """Read installed display adapter names on demand; never polls sensors."""
    if not WIN:
        return []
    script = "Get-CimInstance -ClassName Win32_VideoController -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name"
    code,out,_=command(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],timeout=5)
    names=[line.strip() for line in out.splitlines() if line.strip()] if not code else []
    if not names:
        name,_,_=gpu()
        if name: names=[name]
    return list(dict.fromkeys(names))

def gpu_vendor(name: str) -> str:
    value=(name or "").casefold()
    if "nvidia" in value or "geforce" in value or "quadro" in value: return "NVIDIA"
    if "amd" in value or "radeon" in value: return "AMD"
    if "intel" in value or "arc" in value or "iris" in value: return "Intel"
    return "Other"


def processor_name():
    if WIN and winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                value=winreg.QueryValueEx(k,"ProcessorNameString")[0].strip()
                if value: return value
        except OSError: pass
    return platform.processor().strip() or os.environ.get("PROCESSOR_IDENTIFIER", "Processor information unavailable")

def temp_preview_details(limit=1000):
    """Return names and sizes for eligible TEMP files without following links."""
    folder=temp_dir(); result=[]
    def visit(root,rel=""):
        try: entries=list(os.scandir(root))
        except OSError: return
        for e in entries:
            if len(result)>=limit: return
            p=Path(e.path)
            if link(p): continue
            label=str(Path(rel)/e.name) if rel else e.name
            try:
                if e.is_file(follow_symlinks=False):
                    st=p.stat(follow_symlinks=False); result.append((label,st.st_size,st.st_dev,st.st_ino,st.st_mtime_ns))
                elif e.is_dir(follow_symlinks=False): visit(p,label)
            except OSError: pass
    visit(folder)
    return folder,result

def game_paths_file(): return APP_DATA/"games.json"
def settings_file(): return APP_DATA/"settings.json"
def activity_file(): return APP_DATA/"activity.jsonl"
def startup_profile_file(): return APP_DATA/"startup_profile.json"
def custom_profiles_file(): return APP_DATA/"custom_profiles.json"

def validate_custom_profile(profile):
    if not isinstance(profile,dict): raise ValueError("Profile data must be an object.")
    try: profile_id=str(uuid.UUID(str(profile.get("id"))))
    except (ValueError,TypeError,AttributeError): raise ValueError("Profile ID is invalid.")
    name=profile.get("name")
    if not isinstance(name,str) or not name.strip() or len(name.strip())>64: raise ValueError("Enter a profile name of 1 to 64 characters.")
    for key in ("game_mode_on","capture_off","menu_animation_off","minimize_animation_off","ui_effects_off"):
        if not isinstance(profile.get(key,False),bool): raise ValueError(f"{key} must be true or false.")
    power=profile.get("power_guid")
    if power is not None and (not isinstance(power,str) or not re.fullmatch(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}",power)):
        raise ValueError("The selected power plan ID is invalid.")
    rules=profile.get("priority_rules",[])
    if not isinstance(rules,list) or len(rules)>100: raise ValueError("A profile can include at most 100 saved priority rules.")
    checked=[]; seen=set()
    for rule in rules:
        if not isinstance(rule,dict) or not isinstance(rule.get("name"),str) or not isinstance(rule.get("path"),str): raise ValueError("A saved priority rule is malformed.")
        path=Path(rule["path"])
        if not path.is_absolute() or path.suffix.casefold()!=".exe" or rule.get("priority") not in PRIORITY_VALUES: raise ValueError("A saved priority rule has an unsupported executable or priority.")
        normalized=os.path.normcase(os.path.abspath(str(path)))
        if normalized in seen: raise ValueError("A profile cannot contain duplicate executable priority rules.")
        seen.add(normalized); checked.append({"name":rule["name"][:160],"path":normalized,"priority":rule["priority"]})
    return {"id":profile_id,"name":name.strip(),"game_mode_on":profile.get("game_mode_on",False),"capture_off":profile.get("capture_off",False),"menu_animation_off":profile.get("menu_animation_off",False),"minimize_animation_off":profile.get("minimize_animation_off",False),"ui_effects_off":profile.get("ui_effects_off",False),"power_guid":power.lower() if power else None,"priority_rules":checked}

BUILTIN_PRESET_IDS={name:str(uuid.uuid5(uuid.NAMESPACE_URL,"kam3-tweaks:4.7.0:preset:"+name.casefold())) for name in ("Gaming","Performance","Balanced")}


def build_builtin_preset(name,power_guid=None,include_capture=False,include_visuals=False,include_priority=False,saved_rules=None):
    if name not in BUILTIN_PRESET_IDS: raise ValueError("Unknown built-in preset.")
    rules=[]
    if include_priority and name in ("Gaming","Performance"):
        for rule in saved_rules or []:
            if not isinstance(rule,dict) or not rule.get("enabled",True) or rule.get("mode")!="automatic": continue
            rules.append({"name":str(rule.get("name") or Path(rule.get("path","")).name),"path":rule.get("path"),"priority":rule.get("priority")})
    return validate_custom_profile({
        "id":BUILTIN_PRESET_IDS[name],"name":name+" Preset",
        "game_mode_on":name=="Gaming",
        "capture_off":bool(include_capture) if name=="Gaming" else False,
        "menu_animation_off":bool(include_visuals) if name=="Performance" else False,
        "minimize_animation_off":bool(include_visuals) if name=="Performance" else False,
        "ui_effects_off":bool(include_visuals) if name=="Performance" else False,
        "power_guid":power_guid,"priority_rules":rules,
    })


def validate_custom_profiles(items):
    if not isinstance(items,list) or len(items)>100: return []
    valid=[]; ids=set(); names=set()
    for item in items:
        try: checked=validate_custom_profile(item)
        except (ValueError,TypeError): continue
        if checked["id"] in ids or checked["name"].casefold() in names: continue
        ids.add(checked["id"]); names.add(checked["name"].casefold()); valid.append(checked)
    return valid

def validate_startup_profile(items):
    """Accept only explicit, narrowly scoped current-user startup approvals."""
    if not isinstance(items,list) or len(items)>500: return []
    valid=[]
    for item in items:
        if not isinstance(item,dict): continue
        name=item.get("name"); kind=item.get("kind")
        if not isinstance(name,str) or not name.strip() or len(name)>260: continue
        if kind=="registry":
            value=item.get("value"); data_type=item.get("type")
            if (item.get("key")!=r"Software\Microsoft\Windows\CurrentVersion\Run" or
                item.get("id")!="run:"+name or not isinstance(value,str) or len(value)>32767 or data_type not in (1,2)):
                continue
            valid.append({"kind":"registry","id":"run:"+name,"key":r"Software\Microsoft\Windows\CurrentVersion\Run","name":name,"value":value,"type":data_type})
        elif kind=="shortcut":
            raw_path=item.get("path"); digest=item.get("sha256")
            try: path=Path(raw_path)
            except (TypeError,ValueError): continue
            if (not path.is_absolute() or path.suffix.casefold()!=".lnk" or item.get("id")!="shortcut:"+str(path) or
                not isinstance(digest,str) or not re.fullmatch(r"[0-9a-fA-F]{64}",digest)):
                continue
            valid.append({"kind":"shortcut","id":"shortcut:"+str(path),"path":str(path),"sha256":digest.lower(),"name":name})
    return valid

def migrate_legacy_pcboost_data():
    """Copy known local state forward without moving or deleting the PCBoost data."""
    if not LEGACY_APP_DATA.is_dir(): return []
    APP_DATA.mkdir(parents=True,exist_ok=True)
    copied=[]
    allowed=("settings.json","games.json","profiles.json","undo.json","benchmarks.json","priority_rules.json","custom_profiles.json","activity.jsonl")
    for name in allowed:
        old=LEGACY_APP_DATA/name; new=APP_DATA/name
        if not old.is_file() or new.exists(): continue
        try:
            import shutil
            shutil.copy2(old,new); copied.append(name)
        except OSError:
            continue
    return copied

def protected_process(name,exe):
    blocked={"system","system idle process","registry","smss.exe","csrss.exe","wininit.exe","services.exe","lsass.exe","winlogon.exe","svchost.exe","dwm.exe","fontdrvhost.exe","pcboost.exe","kam3tweaks.exe"}
    if (name or "").casefold() in blocked: return True
    root=os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if root and exe:
        try:
            if os.path.commonpath([os.path.normcase(os.path.abspath(root)),os.path.normcase(os.path.abspath(exe))])==os.path.normcase(os.path.abspath(root)): return True
        except (ValueError,OSError): pass
    return False

def load_json(path,default):
    try: value=json.loads(path.read_text(encoding="utf-8")); return value
    except (OSError,ValueError,TypeError): return default




def startup_entries():
    if not WIN or winreg is None: return []
    entries=[]
    scopes=[("Current user",winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run",True)]
    machine_root=getattr(winreg,"HKEY_LOCAL_MACHINE",None)
    if machine_root is not None: scopes.append(("All users",machine_root,r"Software\Microsoft\Windows\CurrentVersion\Run",False))
    for root_name,root,path,can_change in scopes:
        try:
            with winreg.OpenKey(root,path,0,winreg.KEY_QUERY_VALUE) as k:
                i=0
                while True:
                    try: name,value,kind=winreg.EnumValue(k,i); entries.append((root_name,path,name,value,kind,can_change)); i+=1
                    except OSError: break
        except OSError: pass
    return entries

def startup_folder_path(all_users=False):
    if all_users:
        base=Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    else:
        base=Path(os.environ.get("APPDATA") or Path.home()/"AppData/Roaming")
    return base/"Microsoft"/"Windows"/"Start Menu"/"Programs"/"Startup"

def startup_folder_entries():
    entries=[]
    for scope,all_users in (("Current user",False),("All users",True)):
        folder=startup_folder_path(all_users)
        if link(folder) or not folder.is_dir(): continue
        try: values=list(os.scandir(folder))
        except OSError: continue
        for value in values:
            path=Path(value.path)
            if link(path): continue
            try:
                if not value.is_file(follow_symlinks=False): continue
                writable=(not all_users and path.suffix.casefold()==".lnk")
                entries.append((scope,str(folder),path.name,"Shortcut target is not resolved",path,str(path.suffix),writable))
            except OSError: continue
    return entries

def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""): digest.update(chunk)
    return digest.hexdigest()

def _move_file_verify(source,destination,expected_hash):
    source=Path(source); destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    if link(source) or link(destination.parent): raise RuntimeError("Startup shortcut or destination folder is a link; move refused.")
    if not source.is_file() or file_sha256(source)!=expected_hash: raise RuntimeError("Startup shortcut changed since review; refresh the list.")
    if destination.exists(): raise RuntimeError("The destination already exists; no file was overwritten.")
    try: os.rename(source,destination)  # Windows rename fails instead of replacing a destination.
    except OSError as first:
        raise RuntimeError(f"Could not move the shortcut safely; the original was preserved: {first}") from first
    if not destination.is_file() or file_sha256(destination)!=expected_hash:
        if not source.exists() and destination.exists():
            try: os.rename(destination,source)
            except OSError: pass
        raise RuntimeError("Shortcut move verification failed; check both folders before retrying.")

def disable_startup_shortcut(source,undo):
    source=Path(source)
    root=startup_folder_path(False).resolve(strict=True)
    resolved=source.resolve(strict=True)
    if link(source) or resolved.parent!=root or source.suffix.casefold()!=".lnk":
        raise RuntimeError("Only a regular .lnk file directly inside the current-user Startup folder can be disabled.")
    digest=file_sha256(resolved)
    destination_dir=APP_DATA/"disabled_startup"
    destination=destination_dir/(uuid.uuid4().hex+"_"+resolved.name)
    action={"type":"startup_move","source":str(resolved),"destination":str(destination),"sha256":digest}
    undo.record(action)
    _move_file_verify(resolved,destination,digest)
    return destination

def restore_startup_shortcut(action):
    source=Path(action["source"]); destination=Path(action["destination"]); digest=action["sha256"]
    root=startup_folder_path(False).resolve(strict=True); data_root=(APP_DATA/"disabled_startup").resolve(strict=False)
    try: source_parent=source.parent.resolve(strict=True); destination_abs=destination.resolve(strict=False)
    except OSError as e: raise RuntimeError(f"Startup folders are unavailable: {e}") from e
    if source_parent!=root or source.suffix.casefold()!=".lnk" or destination_abs.parent!=data_root:
        raise RuntimeError("Saved startup restore paths are outside the allowed user Startup/app-data folders.")
    if source.exists() and not destination.exists(): return  # Move never occurred.
    if source.exists(): raise RuntimeError("The original Startup shortcut path is occupied; rename or review it before restoring.")
    if not destination.is_file() or link(destination): raise RuntimeError("Disabled Startup shortcut is missing or unsafe.")
    if file_sha256(destination)!=digest: raise RuntimeError("Disabled Startup shortcut changed while stored; refusing to restore unexpected contents.")
    _move_file_verify(destination,source,digest)

def remove_registry_value(undo: Undo,key: str,name: str):
    exists,value,kind=reg_read(key,name)
    if not exists: raise RuntimeError("The startup entry no longer exists; refresh the list.")
    undo.record({"type":"reg","key":key,"name":name,"exists":True,"key_exists":True,"value":encode(value),"kind":kind,"expected_exists":False,"expected_value":None,"expected_kind":None})
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_SET_VALUE) as k: winreg.DeleteValue(k,name)

def set_registry_value(undo: Undo,key: str,name: str,value: Any,kind: int):
    exists,old,old_kind=reg_read(key,name)
    if exists and old==value and old_kind==kind: return False
    undo.record({"type":"reg","key":key,"name":name,"exists":exists,"key_exists":reg_key_exists(key),"value":encode(old),"kind":old_kind,"expected_exists":True,"expected_value":value,"expected_kind":kind})
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_SET_VALUE) as k: winreg.SetValueEx(k,name,0,kind,value)
    return True

def windows_temp_dir():
    """Resolve exactly the Windows system TEMP directory without traversing links."""
    if not WIN: raise RuntimeError("Windows TEMP cleanup is available only on Windows.")
    root=Path(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows").resolve(strict=True)
    candidate=root/"Temp"
    if link(candidate): raise RuntimeError("Windows TEMP is a link or junction; cleanup is disabled.")
    folder=candidate.resolve(strict=True)
    if folder!=candidate or folder.parent!=root or folder.name.casefold()!="temp" or not folder.is_dir():
        raise RuntimeError("Windows TEMP path did not resolve to the expected system directory.")
    return folder

def windows_temp_preview_details(limit=5000,minimum_age_seconds=7*24*60*60,folder_override=None,now=None):
    """Preview old regular files directly in Windows TEMP; never recurse into subfolders."""
    folder=windows_temp_dir() if folder_override is None else Path(folder_override).resolve(strict=True)
    now=time.time() if now is None else float(now); result=[]
    with os.scandir(folder) as entries:
        for entry in entries:
            if len(result)>=limit: break
            path=Path(entry.path)
            if link(path): continue
            try:
                if not entry.is_file(follow_symlinks=False): continue
                st=entry.stat(follow_symlinks=False)
                if now-st.st_mtime<minimum_age_seconds: continue
                result.append((entry.name,st.st_size,st.st_dev,st.st_ino,st.st_mtime_ns))
            except OSError: continue
    return folder,result

def clean_temp_selected(expected,relative_files,system_temp=False,report=False):
    """Delete only unchanged files shown in a safe TEMP preview; skip races and links."""
    folder=(windows_temp_dir() if system_temp else temp_dir()).resolve(strict=True)
    if folder!=expected.resolve(strict=True): raise RuntimeError("TEMP changed after preview; preview again.")
    removed=freed=skipped=0; deleted=[]
    for item in relative_files:
        rel=item[0] if isinstance(item,(tuple,list)) else item
        candidate=(folder/rel).absolute()
        try: candidate.relative_to(folder)
        except ValueError: skipped+=1; continue
        current=folder
        unsafe=False
        for part in Path(rel).parts:
            if part in (".",".."):
                unsafe=True; break
            current=current/part
            if link(current): unsafe=True; break
        if unsafe: skipped+=1; continue
        try:
            if not candidate.is_file(): skipped+=1; continue
            st=candidate.stat(follow_symlinks=False)
            if isinstance(item,(tuple,list)) and len(item)>=5 and (st.st_size,st.st_dev,st.st_ino,st.st_mtime_ns)!=tuple(item[1:5]):
                skipped+=1; continue
            size=st.st_size
            candidate.unlink(); removed+=1; freed+=size; deleted.append(rel)
        except OSError: skipped+=1
    return (removed,freed,skipped,deleted) if report else (removed,freed,skipped)

def recycle_bin_summary():
    if not WIN: raise RuntimeError("Recycle Bin cleanup is available only on Windows.")
    class Info(ctypes.Structure):
        _fields_=[("cbSize",ctypes.c_ulong),("i64Size",ctypes.c_longlong),("i64NumItems",ctypes.c_longlong)]
    info=Info(); info.cbSize=ctypes.sizeof(Info)
    result=ctypes.windll.shell32.SHQueryRecycleBinW(None,ctypes.byref(info))
    if result: raise OSError(result,"Windows could not inspect the Recycle Bin.")
    return int(info.i64NumItems),int(info.i64Size)

def empty_recycle_bin():
    if not WIN: raise RuntimeError("Recycle Bin cleanup is available only on Windows.")
    flags=0x00000001|0x00000004  # SHERB_NOCONFIRMATION, SHERB_NOSOUND; UI confirmation is shown by this app first.
    result=ctypes.windll.shell32.SHEmptyRecycleBinW(None,None,flags)
    if result: raise OSError(result,"Windows could not empty the Recycle Bin.")

def write_activity(action,result,status="success",details=""):
    try:
        APP_DATA.mkdir(parents=True,exist_ok=True)
        record={"timestamp":datetime.datetime.now().astimezone().isoformat(timespec="seconds"),"action":str(action),"status":str(status),"result":str(result),"details":str(details)}
        with activity_file().open("a",encoding="utf-8") as stream: stream.write(json.dumps(record,ensure_ascii=False)+"\n")
    except OSError: pass

LOCAL_BACKUP_FORMAT = "Kam3Tweaks-local-backup-v2"
PROFILE_NAMES = ("Fortnite", "Project Retrac", "Minecraft")

def validate_local_backup(payload):
    """Validate user-selected local backup data without applying Windows settings."""
    if not isinstance(payload,dict) or payload.get("format") not in (LOCAL_BACKUP_FORMAT,"Kam3Tweaks-settings-v1","PCBoost-settings-v1"):
        raise ValueError("This is not a supported Kam3 Tweaks backup.")
    settings=payload.get("settings",{})
    if not isinstance(settings,dict): raise ValueError("Backup preferences must be an object.")
    # Only preferences this release actually uses are restored. The watcher is
    # deliberately forced off so importing a file cannot change process priority.
    known_settings={"welcome_seen","priority_rules_enabled","theme","gpu_enabled","io_enabled","refresh_seconds","dashboard_cpu_ram","dashboard_gpu","dashboard_network","dashboard_disk","last_update_check_epoch","auto_check_updates","auto_download_updates","auto_install_updates"}
    if any(key not in known_settings for key in settings): raise ValueError("Backup contains unknown preference keys.")
    restored_settings={}
    if "welcome_seen" in settings:
        if not isinstance(settings["welcome_seen"],bool): raise ValueError("welcome_seen must be true or false.")
        restored_settings["welcome_seen"]=settings["welcome_seen"]
    for key in ("auto_check_updates","auto_download_updates","auto_install_updates"):
        if key in settings:
            if not isinstance(settings[key],bool): raise ValueError(f"{key} must be true or false.")
            # Automatic installation remains disabled regardless
            # of imported backup contents; installing always needs a click.
            restored_settings[key]=False if key=="auto_install_updates" else settings[key]
    if "theme" in settings:
        if settings["theme"] not in THEME_PALETTES: raise ValueError("Backup contains an unsupported theme.")
        restored_settings["theme"]=settings["theme"]
    incoming_profiles=payload.get("profiles",{})
    if not isinstance(incoming_profiles,dict) or any(name not in PROFILE_NAMES for name in incoming_profiles):
        raise ValueError("Backup contains unsupported game profiles.")
    profiles={name:validate_profile(incoming_profiles.get(name,{})) for name in PROFILE_NAMES}
    games=payload.get("games",[] if payload.get("format")==LOCAL_BACKUP_FORMAT else None)
    if games is not None and (not isinstance(games,list) or len(games)>500): raise ValueError("Game library must be a list of at most 500 entries.")
    checked_games=[]
    for game in games or []:
        if not isinstance(game,dict): raise ValueError("Game library entry must be an object.")
        name=game.get("name"); raw_path=game.get("path")
        if not isinstance(name,str) or not name.strip() or len(name)>160 or not isinstance(raw_path,str): raise ValueError("Game library entry has an invalid name or path.")
        path=Path(raw_path)
        if not path.is_absolute() or path.suffix.casefold()!=".exe": raise ValueError("Game executable paths must be absolute .exe paths.")
        priority={"Normal":"Medium","Below Normal":"Low","Above Normal":"High"}.get(game.get("priority","Medium"),game.get("priority","Medium"))
        if priority not in PRIORITY_VALUES: raise ValueError("Game priority must be High, Medium, or Low.")
        item={"name":name.strip(),"path":str(path),"priority":priority}
        profile_key=game.get("profile_key")
        if profile_key is not None:
            if profile_key not in PROFILE_NAMES: raise ValueError("Game entry references an unknown profile.")
            item["profile_key"]=profile_key
        checked_games.append(item)
    rules=payload.get("priority_rules",[] if payload.get("format")==LOCAL_BACKUP_FORMAT else None)
    if rules is not None and (not isinstance(rules,list) or len(rules)>1000): raise ValueError("Priority rules must be a list of at most 1,000 entries.")
    checked_rules=[]
    for rule in rules or []:
        if not isinstance(rule,dict): raise ValueError("Priority rule must be an object.")
        name=rule.get("name"); raw_path=rule.get("path"); mode=rule.get("mode"); enabled=rule.get("enabled",True)
        priority={"Normal":"Medium","Below Normal":"Low","Above Normal":"High"}.get(rule.get("priority"),rule.get("priority"))
        if not isinstance(name,str) or not name.strip() or len(name)>160 or not isinstance(raw_path,str): raise ValueError("Priority rule has an invalid name or path.")
        path=Path(raw_path)
        if not path.is_absolute() or path.suffix.casefold()!=".exe": raise ValueError("Priority rule paths must be absolute .exe paths.")
        if priority not in PRIORITY_VALUES or mode not in ("once","automatic") or not isinstance(enabled,bool): raise ValueError("Priority rule has an invalid priority, mode, or enabled state.")
        checked_rules.append({"name":name.strip(),"path":os.path.normcase(os.path.abspath(str(path))),"priority":priority,"mode":mode,"enabled":enabled,"last_result":"Imported; not applied"})
    startup=payload.get("startup_profile")
    if startup is not None:
        if not isinstance(startup,list) or len(startup)>500: raise ValueError("Startup profile must be a list of at most 500 approved entries.")
        checked_startup=validate_startup_profile(startup)
        if len(checked_startup)!=len(startup): raise ValueError("Startup profile contains an invalid or unsupported approval.")
    else: checked_startup=None
    custom=payload.get("custom_profiles")
    if custom is not None:
        if not isinstance(custom,list) or len(custom)>100: raise ValueError("Custom profiles must be a list of at most 100 profiles.")
        checked_custom=validate_custom_profiles(custom)
        if len(checked_custom)!=len(custom): raise ValueError("Backup contains an invalid or duplicate custom profile.")
    else: checked_custom=None
    return {"settings":restored_settings,"profiles":profiles,"games":checked_games if games is not None else None,"priority_rules":checked_rules if rules is not None else None,"startup_profile":checked_startup,"custom_profiles":checked_custom}

def atomic_write_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
        tmp.replace(path)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass

def temp_dir():
    raw=os.environ.get("TEMP")
    if not raw: raise RuntimeError("Current user's TEMP folder is not configured.")
    raw_path=Path(raw)
    if link(raw_path): raise RuntimeError("TEMP is a link or junction; cleanup through it is disabled.")
    p=raw_path.resolve(strict=True)
    home=Path.home().resolve(strict=True)
    try: relative=p.relative_to(home)
    except ValueError: raise RuntimeError("Cleanup is limited to TEMP folders inside the current user's profile.")
    if not relative.parts or p.name.casefold() not in ("temp","tmp"):
        raise RuntimeError("Cleanup requires a folder named Temp or TMP inside the current user's profile.")
    if not p.is_dir(): raise RuntimeError("TEMP path is not a folder.")
    return p

def link(path: Path) -> bool:
    try:
        attrs=getattr(path.lstat(),"st_file_attributes",0)
        f=getattr(os.path,"isjunction",None)
        return path.is_symlink() or bool(attrs & 0x400) or bool(f(path) if f else False)
    except OSError: return True





def admin():
    try: return WIN and bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError,OSError): return False



def panel(title,subtitle=""):
    f=QFrame(); f.setObjectName("panel"); v=QVBoxLayout(f); v.setContentsMargins(20,18,20,18); v.setSpacing(12)
    t=QLabel(title); t.setObjectName("sectionTitle"); v.addWidget(t)
    if subtitle:
        s=QLabel(subtitle); s.setObjectName("muted"); s.setWordWrap(True); v.addWidget(s)
    return f,v

# The UI uses a permanent sidebar and a stacked page area; Windows changes use
# the existing confirmation and Undo backend above.
class StorageSignals(QObject):
    finished=Signal(list,str)


def icon_for(kind,active=False):
    """Small consistent line icons drawn locally; no external icon service."""
    pix=QPixmap(20,20); pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#c7adff" if active else "#9ba4ac"),1.65,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    if kind=="home":
        p.drawRoundedRect(3,3,14,14,2,2); p.drawLine(6,7,9,7); p.drawLine(6,10,14,10); p.drawLine(6,13,12,13)
    elif kind=="game":
        p.drawRoundedRect(2,5,16,10,3,3); p.drawLine(6,8,6,12); p.drawLine(4,10,8,10); p.drawPoint(13,9); p.drawPoint(15,11)
    elif kind=="process":
        p.drawRoundedRect(3,3,14,14,2,2); p.drawLine(6,7,8,7); p.drawLine(6,10,14,10); p.drawLine(6,13,11,13)
    elif kind=="tune":
        for y,x in ((5,8),(10,13),(15,6)):
            p.drawLine(3,y,17,y); p.drawEllipse(x-1.5,y-1.5,3,3)
    elif kind=="library":
        p.drawRoundedRect(3,3,14,14,3,3); p.drawLine(6,7,14,7); p.drawLine(6,10,14,10); p.drawLine(6,13,11,13)
    elif kind=="startup":
        p.drawRoundedRect(3,4,14,12,2,2); p.drawLine(6,7,14,7); p.drawLine(6,10,12,10); p.drawLine(6,13,10,13)
    elif kind=="chart":
        p.drawLine(3,16,17,16); p.drawLine(4,14,8,10); p.drawLine(8,10,11,12); p.drawLine(11,12,16,5); p.drawEllipse(14.5,3.5,3,3)
    elif kind=="network":
        p.drawEllipse(3,4,14,12); p.drawLine(3,10,17,10); p.drawLine(10,4,10,16); p.drawArc(6,4,8,12,90*16,180*16); p.drawArc(6,4,8,12,270*16,180*16)
    elif kind=="windows":
        p.drawLine(3,4,9,3); p.drawLine(11,3,17,2); p.drawLine(3,6,9,6); p.drawLine(11,6,17,6); p.drawLine(3,8,9,8); p.drawLine(11,8,17,8); p.drawLine(3,10,9,10); p.drawLine(11,10,17,10)
    elif kind=="cleanup":
        p.drawLine(5,6,15,6); p.drawLine(7,6,7,16); p.drawLine(13,6,13,16); p.drawLine(5,16,15,16); p.drawLine(8,4,12,4)
    elif kind=="log":
        p.drawRoundedRect(4,2,12,16,2,2); p.drawLine(7,7,13,7); p.drawLine(7,10,13,10); p.drawLine(7,13,11,13)
    elif kind=="system":
        p.drawRoundedRect(2,3,16,11,2,2); p.drawLine(8,14,8,17); p.drawLine(12,14,12,17); p.drawLine(6,17,14,17)
    elif kind=="check":
        p.drawEllipse(3,3,14,14); p.drawLine(6,10,9,13); p.drawLine(9,13,14,7)
    elif kind=="settings":
        p.drawEllipse(4,4,12,12); p.drawEllipse(8,8,4,4)
    elif kind=="help":
        p.drawEllipse(3,3,14,14); p.drawText(7,14,"?")
    p.end(); return QIcon(pix)

class UpdateCheckWorker(QObject):
    completed=Signal(object)
    def run(self):
        try: self.completed.emit({"ok":True,"release":fetch_latest_release()})
        except Exception as exc: self.completed.emit({"ok":False,"error":str(exc)})


class NetworkDetailsWorker(QObject):
    completed=Signal(object)
    def run(self):
        try:
            interfaces=psutil.net_if_addrs(); stats=psutil.net_if_stats()
            try: adapters,detail_error=query_adapters(interfaces,stats)
            except Exception as exc: adapters=[]; detail_error=str(exc)
            route_adapter=next((item.get("name") for item in adapters if item.get("has_default_route") is True),None)
            try: dns_configs,dns_config_error=query_dns_adapters(default_route_alias=route_adapter)
            except Exception as exc: dns_configs=[]; dns_config_error=str(exc)
            self.completed.emit({"ok":True,"interfaces":interfaces,"stats":stats,"adapters":adapters,
                                 "detail_error":detail_error,"dns_configs":dns_configs,"dns_config_error":dns_config_error})
        except Exception as exc:
            self.completed.emit({"ok":False,"error":str(exc)})


class UpdateDownloadWorker(QObject):
    progress=Signal(int,int)
    completed=Signal(object)
    def __init__(self,release,staging_root,installed_version):
        super().__init__(); self.release=release; self.staging_root=staging_root
        self.installed_version=installed_version; self.cancel_event=threading.Event()
    def run(self):
        try:
            result=download_verified_update(self.release,self.staging_root,
                public_key_b64=PINNED_PUBLIC_KEY_B64 or None,installed_version=self.installed_version,
                cancel_event=self.cancel_event,progress=lambda done,total:self.progress.emit(done,total))
            self.completed.emit({"ok":True,"update":result})
        except DownloadCancelled as exc:
            self.completed.emit({"ok":False,"cancelled":True,"error":str(exc)})
        except Exception as exc:
            self.completed.emit({"ok":False,"error":str(exc)})


class Window(QMainWindow):
    PAGE_NAMES=["Home","Quick Tweaks","Optimizations","Gaming","Network","Cleanup","Settings"]
    PAGE_ICONS=["home","tune","library","game","network","cleanup","settings"]
    QUICK_TAB_NAMES=["Windows Tweaks","Startup Tweaks","CPU Tweaks","GPU Tweaks","NVIDIA Tweaks","AMD Tweaks","Intel Tweaks"]
    def __init__(self):
        super().__init__(); self.setWindowTitle(APP_NAME)
        self.setMinimumSize(900,620); self.resize(1280,800)
        self._operation_busy=False
        self.category_undo_buttons={}; self.category_undo_labels={}
        self._dns_adapters=[]; self._dns_query_error=""
        self.migrated_files=migrate_legacy_pcboost_data()
        icon_path=APP_DIR/"Kam3Tweaks.ico"
        if icon_path.exists(): self.setWindowIcon(QIcon(str(icon_path)))
        self.undo=Undo(); self.gpu_name=None
        self.settings=load_json(settings_file(),{}); self.settings=self.settings if isinstance(self.settings,dict) else {}
        self.apply_theme(self.settings.get("theme","Violet Aurora"),persist=False)
        self.games=load_json(game_paths_file(),[]); self.games=self.games if isinstance(self.games,list) else []
        profile_defaults={name:validate_profile({}) for name in ("Fortnite","Project Retrac","Minecraft")}
        self.profiles=load_json(APP_DATA/"profiles.json",profile_defaults); self.profiles=self.profiles if isinstance(self.profiles,dict) else profile_defaults
        self.profiles={name:validate_profile(self.profiles.get(name,{})) for name in profile_defaults}
        self.priority_rules=load_json(APP_DATA/"priority_rules.json",[]); self.priority_rules=self.priority_rules if isinstance(self.priority_rules,list) else []
        self.startup_profile=validate_startup_profile(load_json(startup_profile_file(),[]))
        self.custom_profiles=validate_custom_profiles(load_json(custom_profiles_file(),[]))
        self.priority_rules=[r for r in self.priority_rules if isinstance(r,dict) and isinstance(r.get("path"),str) and r.get("priority") in PRIORITY_VALUES and r.get("mode") in ("once","automatic")]
        self._priority_applied={}
        self._profile_sessions={}
        self._game_sessions={}
        self._storage_thread=None; self._process_rows=[]; self._game_rows=[]; self._activity_rows=[]; self._game_sessions={}
        self._update_thread=None; self._update_worker=None; self._latest_release_url=RELEASES_URL; self.latest_release=None
        self._download_thread=None; self._download_worker=None; self._verified_update=None; self._update_prompt=None
        root=QWidget(); root.setObjectName("root"); outer=QHBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        self.sidebar=QWidget(); self.sidebar.setObjectName("sidebar"); self.sidebar.setFixedWidth(212); side=QVBoxLayout(self.sidebar); side.setContentsMargins(16,18,14,14); side.setSpacing(5)
        brandrow=QHBoxLayout(); logo=QLabel(); logo.setObjectName("brandMark"); logo.setFixedSize(40,40); logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if icon_path.exists(): logo.setPixmap(QIcon(str(icon_path)).pixmap(28,28))
        else: logo.setText("K3")
        brandrow.addWidget(logo); brandnames=QVBoxLayout(); brand=QLabel(APP_NAME); brand.setObjectName("brand"); version=QLabel(f"CONTROL CENTER  ·  {APP_VERSION}"); version.setObjectName("eyebrow"); brandnames.addWidget(brand); brandnames.addWidget(version); brandrow.addLayout(brandnames); brandrow.addStretch(); side.addLayout(brandrow); side.addSpacing(20)
        self.nav_search=QLineEdit(); self.nav_search.setPlaceholderText("Find a page…"); self.nav_search.setClearButtonEnabled(True); self.nav_search.textChanged.connect(self.filter_nav); side.addWidget(self.nav_search); side.addSpacing(8)
        self.nav_buttons=[]
        for i,(title,icon) in enumerate(zip(self.PAGE_NAMES,self.PAGE_ICONS)):
            btn=QPushButton("  "+title.replace("&","&&")); btn.setObjectName("nav"); btn.setIcon(icon_for(icon,i==0)); btn.setIconSize(__import__('PySide6.QtCore',fromlist=['QSize']).QSize(17,17)); btn.setCheckable(True); btn.clicked.connect(lambda checked=False,index=i:self.select_page(index)); side.addWidget(btn); self.nav_buttons.append(btn)
        side.addStretch(); self.sidebar_note=QLabel("✦  LOCAL-FIRST\nReviewed changes · no silent presets"); self.sidebar_note.setObjectName("eyebrow"); self.sidebar_note.setWordWrap(True); side.addWidget(self.sidebar_note)
        outer.addWidget(self.sidebar)
        content=QWidget(); cv=QVBoxLayout(content); cv.setContentsMargins(22,16,22,12); cv.setSpacing(12)
        top=QHBoxLayout(); self.top_title=QLabel("Home"); self.top_title.setObjectName("pageTitle"); top.addWidget(self.top_title); top.addStretch()
        self.admin=QLabel("ADMINISTRATOR" if admin() else "STANDARD USER"); self.admin.setObjectName("statusPill"); top.addWidget(self.admin)
        self.undo_btn=QPushButton("Nothing to undo"); self.undo_btn.setToolTip("Restore the most recent reversible change"); self.undo_btn.clicked.connect(self.undo_last); top.addWidget(self.undo_btn); cv.addLayout(top)
        self.stack=QStackedWidget(); self.pages=[]
        builders=[self.home_page,self.quick_tweaks_page,self.optimization,self.games_page,self.network_page,self.cleanup_page,self.settings_page]
        for builder in builders:
            page=builder(); self.pages.append(page); self.stack.addWidget(self.make_scroll(page))
        cv.addWidget(self.stack,1)
        operation=QFrame(); operation.setObjectName("operationPanel"); operation_layout=QVBoxLayout(operation); operation_layout.setContentsMargins(12,8,12,8); operation_layout.setSpacing(5)
        operation_row=QHBoxLayout(); self.operation_state=QLabel("Ready"); self.operation_state.setObjectName("statusPill"); operation_row.addWidget(self.operation_state)
        self.status=StatusLabel("Ready · changes require review and confirmation"); self.status.setObjectName("muted"); self.status.setWordWrap(True); self.status.setMaximumHeight(52); self.status.setAccessibleName("Operation status"); self.status.text_changed.connect(self.on_operation_text_changed); operation_row.addWidget(self.status,1)
        self.operation_details_btn=QPushButton("Details"); self.operation_details_btn.setAccessibleName("Read full operation result"); self.operation_details_btn.clicked.connect(self.show_operation_details); operation_row.addWidget(self.operation_details_btn); operation_layout.addLayout(operation_row)
        self.operation_progress=QProgressBar(); self.operation_progress.setAccessibleName("Operation in progress"); self.operation_progress.setTextVisible(False); self.operation_progress.setFixedHeight(4); self.operation_progress.hide(); operation_layout.addWidget(self.operation_progress); cv.addWidget(operation)
        if self.migrated_files: self.status.setText(f"Imported PCBoost local data: {', '.join(self.migrated_files)} · original data retained")
        outer.addWidget(content,1); self.setCentralWidget(root)
        self.action_buttons=[getattr(self,name) for name in ("gaming_apply_btn","gaming_undo_btn","custom_profile_create_btn","custom_profile_edit_btn","custom_profile_duplicate_btn","custom_profile_delete_btn","custom_profile_apply_btn","custom_profile_undo_btn","mode_btn","capture_btn","plan_btn","clean_btn","windows_temp_btn","recycle_btn","dns_btn","priority_btn","affinity_btn","startup_disable_btn","startup_profile_apply_btn","game_launch_btn","game_profile_btn","profile_apply_btn","optimization_apply_btn","optimization_refresh_btn","storage_btn") if hasattr(self,name)]
        self.refresh_all(); self.refresh_undo(); self.refresh_startup(); self.refresh_games(); self.refresh_activity()
        self.load_profile_editor()
        for i in range(1,len(self.PAGE_NAMES)+1):
            shortcut=QShortcut(QKeySequence(f"Ctrl+{i}"),self); shortcut.activated.connect(lambda page=i-1:self.select_page(page))
        undo_shortcut=QShortcut(QKeySequence("Ctrl+Z"),self); undo_shortcut.activated.connect(self.undo_last)
        self.game_timer=QTimer(self); self.game_timer.timeout.connect(self.cleanup_profile_sessions)
        self.priority_timer=QTimer(self); self.priority_timer.timeout.connect(self.scan_priority_rules)
        if self.settings.get("priority_rules_enabled",False) and any(r.get("enabled",True) and r.get("mode")=="automatic" for r in self.priority_rules): self.priority_timer.start(5000)
        self.configure_accessibility()
        self.select_page(0)
        if not self.settings.get("welcome_seen",False) and "--smoke-test" not in sys.argv:
            QTimer.singleShot(0,self.show_welcome)
        if self.settings.get("auto_check_updates",True) and "--smoke-test" not in sys.argv:
            QTimer.singleShot(1500,self.check_for_updates)
        if "--smoke-test" not in sys.argv:
            QTimer.singleShot(1000,self.check_update_result)
            QTimer.singleShot(20000,self.cleanup_stale_update_run_dirs)

    def make_scroll(self,page):
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame); scroll.setWidget(page); scroll.setAccessibleName("Scrollable page content"); return scroll

    def apply_theme(self,name,persist=True):
        if name not in THEME_PALETTES: name="Violet Aurora"
        self.current_theme=name
        stylesheet=theme_stylesheet(name)
        if self.styleSheet()!=stylesheet: self.setStyleSheet(stylesheet)
        if hasattr(self,"theme_combo") and self.theme_combo.currentText()!=name:
            self.theme_combo.blockSignals(True); self.theme_combo.setCurrentText(name); self.theme_combo.blockSignals(False)
        if hasattr(self,"theme_description"):
            descriptions={"High Contrast":"Opaque near-black surfaces, bright text and strong focus outlines.","Violet Aurora":"Layered plum surfaces with a soft violet highlight.","Midnight Blue":"Cool slate panels with a restrained sky-blue accent.","Graphite Rose":"Warm graphite surfaces with a muted rose accent."}
            self.theme_description.setText(descriptions[name])
        if persist:
            self.settings["theme"]=name
            saved=self.save_settings_file()
            if hasattr(self,"status"): self.status.setText(f"Theme changed to {name}." if saved else "Theme changed for this session; saving preferences failed.")
        for i,button in enumerate(getattr(self,"nav_buttons",[])):
            button.setIcon(icon_for(self.PAGE_ICONS[i],i==self.stack.currentIndex()))

    def on_theme_changed(self,name):
        self.apply_theme(name,persist=True)

    def add_page_heading(self,layout,title,subtitle=""):
        kicker=QLabel(f"KAM3 TWEAKS  /  {title.upper()}"); kicker.setObjectName("eyebrow"); layout.addWidget(kicker)
        heading=QLabel(title); heading.setObjectName("pageTitle"); layout.addWidget(heading)
        if subtitle:
            note=QLabel(subtitle); note.setObjectName("muted"); note.setWordWrap(True); layout.addWidget(note)

    def make_overview_card(self,value,title,detail):
        card=QFrame(); card.setObjectName("overviewCard"); layout=QVBoxLayout(card); layout.setContentsMargins(16,14,16,14); layout.setSpacing(4)
        value_label=QLabel(str(value)); value_label.setObjectName("metricValue"); title_label=QLabel(title.upper()); title_label.setObjectName("metricName")
        detail_label=QLabel(detail); detail_label.setObjectName("muted"); detail_label.setWordWrap(True)
        layout.addWidget(value_label); layout.addWidget(title_label); layout.addWidget(detail_label)
        return card,value_label

    def home_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(3,5,10,12); v.setSpacing(14)
        hero=QFrame(); hero.setObjectName("heroPanel"); hero_layout=QVBoxLayout(hero); hero_layout.setContentsMargins(24,22,24,22); hero_row=ResponsiveGrid(340,2); hero_layout.addWidget(hero_row)
        hero_main=QWidget(); left=QVBoxLayout(hero_main); left.setContentsMargins(0,0,0,0); eyebrow=QLabel("KAM3 TWEAKS  /  WINDOWS CONTROL CENTER"); eyebrow.setObjectName("eyebrow"); left.addWidget(eyebrow)
        title=QLabel("Small changes. Clear choices."); title.setObjectName("heroTitle"); title.setWordWrap(True); left.addWidget(title)
        summary=QLabel("Explore practical Windows settings, review each change, and restore reversible actions when needed."); summary.setObjectName("muted"); summary.setWordWrap(True); left.addWidget(summary)
        actions=QVBoxLayout(); quick=QPushButton("Explore Quick Tweaks"); quick.setObjectName("primary"); quick.clicked.connect(lambda:self.select_page(1)); library=QPushButton("Browse optimization library"); library.clicked.connect(lambda:self.select_page(2)); actions.addWidget(quick); actions.addWidget(library); left.addLayout(actions); hero_row.add_card(hero_main)
        aside=QFrame(); aside.setObjectName("overviewCard"); aside_layout=QVBoxLayout(aside); aside_layout.setContentsMargins(18,16,18,16)
        symbol=QLabel("✦"); symbol.setStyleSheet("color:#d8c9ff;font-size:24pt;font-weight:700;"); aside_layout.addWidget(symbol)
        manual=QLabel("YOU ARE IN CONTROL"); manual.setObjectName("sectionTitle"); aside_layout.addWidget(manual)
        policy=QLabel("No recommendation is applied automatically. Direct changes ask first; Windows shortcuts open native controls."); policy.setObjectName("muted"); policy.setWordWrap(True); aside_layout.addWidget(policy); hero_row.add_card(aside); v.addWidget(hero)

        overview=ResponsiveGrid(210,3); self.home_overview_grid=overview
        card,self.home_undo_metric=self.make_overview_card("—","Undo queue","Most recent reversible action")
        overview.add_card(card)
        card,self.home_rules_metric=self.make_overview_card("—","Priority rules","Exact-path rules run only while enabled")
        overview.add_card(card)
        card,self.home_games_metric=self.make_overview_card("—","Game library","Saved executable paths on this PC")
        overview.add_card(card); v.addWidget(overview)

        f,panel_layout=panel("Jump back in","Choose a toolset. Each opens the existing functional page; these are shortcuts, not preset changes.")
        grid=ResponsiveGrid(300,2); self.home_links_grid=grid
        links=[("Quick Tweaks","Windows, startup, process and graphics controls.",1,"tune"),
               ("Optimizations","Search settings, risk and current state.",2,"check"),
               ("Gaming","Profiles, Game Mode and capture preferences.",3,"game"),
               ("Cleanup","Preview eligible files before cleanup.",5,"cleanup")]
        for n,(name,description,target,icon_kind) in enumerate(links):
            card=QFrame(); card.setObjectName("categoryCard"); layout=QVBoxLayout(card); layout.setContentsMargins(14,12,14,12); layout.setSpacing(6)
            head=QHBoxLayout(); icon=QLabel(); icon.setPixmap(icon_for(icon_kind,True).pixmap(22,22)); head.addWidget(icon)
            label=QLabel(name); label.setObjectName("sectionTitle"); head.addWidget(label); head.addStretch(); layout.addLayout(head)
            text=QLabel(description); text.setObjectName("muted"); text.setWordWrap(True); layout.addWidget(text)
            button=QPushButton("Open section"); button.clicked.connect(lambda checked=False,i=target:self.select_page(i)); layout.addWidget(button,alignment=Qt.AlignmentFlag.AlignLeft)
            grid.add_card(card)
        panel_layout.addWidget(grid); v.addWidget(f)

        row=ResponsiveGrid(360,2)
        f,p=panel("Recommended to review","Suggestions are compatibility notes, not automatic changes or promises of performance improvement.")
        self.advisor_summary=QLabel("Reading system compatibility…"); self.advisor_summary.setWordWrap(True); self.advisor_summary.setObjectName("muted"); p.addWidget(self.advisor_summary)
        self.advisor_table=QTableWidget(0,3); self.advisor_table.setHorizontalHeaderLabels(["Setting","Detected state","Why review it"])
        for c,width in ((0,QHeaderView.ResizeMode.ResizeToContents),(1,QHeaderView.ResizeMode.ResizeToContents),(2,QHeaderView.ResizeMode.Stretch)): self.advisor_table.horizontalHeader().setSectionResizeMode(c,width)
        self.advisor_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.advisor_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection); self.advisor_table.setMaximumHeight(220); self.advisor_table.setAlternatingRowColors(True); p.addWidget(self.advisor_table); row.add_card(f)
        f,p=panel("Current settings","Read on demand. Unknown or unconfigured values stay explicit.")
        self.home_active=QTableWidget(0,2); self.home_active.setHorizontalHeaderLabels(["Control","Current value"]); self.home_active.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents); self.home_active.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch); self.home_active.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.home_active.setMaximumHeight(220); self.home_active.setAlternatingRowColors(True); p.addWidget(self.home_active); row.add_card(f); v.addWidget(row)

        row=ResponsiveGrid(360,2)
        f,p=panel("Recently changed","Local activity. Detailed entries are available in Settings.")
        self.home_recent=QLabel("No recent actions recorded."); self.home_recent.setObjectName("muted"); self.home_recent.setWordWrap(True); p.addWidget(self.home_recent)
        history=QPushButton("Open Activity History"); history.clicked.connect(self.open_activity_history); p.addWidget(history,alignment=Qt.AlignmentFlag.AlignLeft); row.add_card(f)
        f,p=panel("Restore","Undo uses the exact saved previous values where supported. It never writes guessed defaults.")
        self.home_restore_label=QLabel("No reversible action is queued."); self.home_restore_label.setObjectName("muted"); self.home_restore_label.setWordWrap(True); p.addWidget(self.home_restore_label)
        self.home_restore_btn=QPushButton("Restore latest change…"); self.home_restore_btn.clicked.connect(self.undo_last); p.addWidget(self.home_restore_btn,alignment=Qt.AlignmentFlag.AlignLeft); row.add_card(f); v.addWidget(row)
        v.addStretch(); return w

    def quick_tweaks_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(3,5,10,12); v.setSpacing(14)
        self.add_page_heading(v,"Quick Tweaks","Preview the scope and trade-offs. Review & apply checks current values and asks before changing anything.")
        presets=ResponsiveGrid(320,2)
        gaming,p=panel("Gaming Tweaks","Game Mode on; Windows background recording off. Keep capture enabled if you use background clips. No FPS gain is promised.")
        row=QHBoxLayout(); self.gaming_apply_btn=QPushButton("Review & apply…"); self.gaming_apply_btn.setObjectName("primary"); self.gaming_apply_btn.clicked.connect(self.apply_gaming_tweaks); row.addWidget(self.gaming_apply_btn)
        preview=QPushButton("Preview"); preview.clicked.connect(lambda:self.preview_quick_category("Gaming Tweaks")); preview.setAccessibleName("Preview Gaming Tweaks"); row.addWidget(preview); p.addLayout(row)
        self.gaming_undo_btn=QPushButton("Undo Gaming Tweaks"); self.gaming_undo_btn.clicked.connect(lambda:self.undo_quick_category("Gaming Tweaks")); p.addWidget(self.gaming_undo_btn)
        self.add_category_undo_status("Gaming Tweaks",p,self.gaming_undo_btn); presets.add_card(gaming)
        power,p=panel("Power Tweaks","Optional switch to an installed High performance plan. May increase power use, heat and fan noise. Your current plan stays selected until you confirm.")
        row=QHBoxLayout(); self.power_apply_btn=QPushButton("Review & apply…"); self.power_apply_btn.setObjectName("primary"); self.power_apply_btn.clicked.connect(lambda:self.apply_quick_category("Power Tweaks")); row.addWidget(self.power_apply_btn)
        preview=QPushButton("Preview"); preview.clicked.connect(lambda:self.preview_quick_category("Power Tweaks")); preview.setAccessibleName("Preview Power Tweaks"); row.addWidget(preview); p.addLayout(row)
        self.power_undo_btn=QPushButton("Undo Power Tweaks"); self.power_undo_btn.clicked.connect(lambda:self.undo_quick_category("Power Tweaks")); p.addWidget(self.power_undo_btn)
        self.add_category_undo_status("Power Tweaks",p,self.power_undo_btn); presets.add_card(power); v.addWidget(presets)
        preset,p=panel("One-click presets","Presets use the same current-state checks, one confirmation, verification and exact Undo as custom profiles. Optional changes are off unless you select them.")
        row=QHBoxLayout(); self.builtin_preset_combo=QComboBox(); self.builtin_preset_combo.addItem("Gaming Preset","Gaming"); self.builtin_preset_combo.addItem("Performance Preset","Performance"); self.builtin_preset_combo.addItem("Balanced Preset","Balanced"); self.builtin_preset_combo.setAccessibleName("Built-in optimization preset"); row.addWidget(self.builtin_preset_combo)
        self.preset_power_combo=QComboBox(); self.preset_power_combo.setAccessibleName("Optional power plan for the selected preset"); row.addWidget(self.preset_power_combo,1); p.addLayout(row)
        row=QHBoxLayout(); row.addStretch(); self.preset_refresh_plans_btn=QPushButton("Refresh power plans"); self.preset_refresh_plans_btn.setAccessibleName("Refresh installed power plans for presets"); self.preset_refresh_plans_btn.clicked.connect(self.refresh_preset_plans); row.addWidget(self.preset_refresh_plans_btn); p.addLayout(row)
        self.preset_capture_check=QCheckBox("Disable recording"); self.preset_capture_check.setAccessibleName("Gaming preset: turn off Windows background game recording"); self.preset_capture_check.setToolTip("Turns off Windows background GameDVR recording only. It does not affect third-party capture tools."); p.addWidget(self.preset_capture_check)
        self.preset_visuals_check=QCheckBox("Disable optional visual effects"); self.preset_visuals_check.setAccessibleName("Performance preset: turn off menu/window animations and system UI effects"); self.preset_visuals_check.setToolTip("Turns off optional menu/window animations and the system-wide UI-effects preference. Visual feedback changes; no FPS improvement is promised."); p.addWidget(self.preset_visuals_check)
        self.preset_priority_check=QCheckBox("Apply saved priority rules"); self.preset_priority_check.setAccessibleName("Include eligible saved automatic application priority rules in preset"); self.preset_priority_check.setToolTip("Only exact executable-path matches among enabled saved automatic rules are considered. Each eligible running process is listed before confirmation."); p.addWidget(self.preset_priority_check)
        row=QHBoxLayout(); self.preset_apply_btn=QPushButton("Review & apply preset…"); self.preset_apply_btn.setObjectName("primary"); self.preset_apply_btn.clicked.connect(self.apply_selected_preset); row.addWidget(self.preset_apply_btn); self.preset_undo_btn=QPushButton("Undo preset"); self.preset_undo_btn.clicked.connect(self.undo_selected_preset); row.addWidget(self.preset_undo_btn); row.addStretch(); p.addLayout(row)
        self.preset_status=QLabel("Choose a preset and review its exact proposed changes before applying."); self.preset_status.setObjectName("muted"); self.preset_status.setWordWrap(True); p.addWidget(self.preset_status)
        self.builtin_preset_combo.currentIndexChanged.connect(self.on_builtin_preset_changed); v.addWidget(preset)
        custom,p=panel("My Profiles","Save a group of supported reversible settings once, then apply or undo it together. Cleanup and other destructive actions cannot be included.")
        row=QHBoxLayout(); self.custom_profile_combo=QComboBox(); self.custom_profile_combo.setAccessibleName("Saved one-click profiles"); self.custom_profile_combo.setMinimumContentsLength(12); self.custom_profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); self.custom_profile_combo.currentIndexChanged.connect(self.refresh_custom_profile_controls); p.addWidget(self.custom_profile_combo)
        self.custom_profile_create_btn=QPushButton("Create"); self.custom_profile_create_btn.clicked.connect(self.create_custom_profile)
        self.custom_profile_edit_btn=QPushButton("Edit"); self.custom_profile_edit_btn.clicked.connect(self.edit_custom_profile)
        self.custom_profile_duplicate_btn=QPushButton("Duplicate"); self.custom_profile_duplicate_btn.clicked.connect(self.duplicate_custom_profile)
        self.custom_profile_delete_btn=QPushButton("Delete"); self.custom_profile_delete_btn.clicked.connect(self.delete_custom_profile)
        for button in (self.custom_profile_create_btn,self.custom_profile_edit_btn,self.custom_profile_duplicate_btn,self.custom_profile_delete_btn): row.addWidget(button)
        p.addLayout(row)
        self.custom_profile_summary=QLabel("Create a profile by choosing only settings you want it to apply."); self.custom_profile_summary.setObjectName("muted"); self.custom_profile_summary.setWordWrap(True); p.addWidget(self.custom_profile_summary)
        row=QHBoxLayout(); self.custom_profile_apply_btn=QPushButton("Apply Profile"); self.custom_profile_apply_btn.setObjectName("primary"); self.custom_profile_apply_btn.clicked.connect(self.apply_custom_profile)
        self.custom_profile_undo_btn=QPushButton("Undo Profile"); self.custom_profile_undo_btn.clicked.connect(self.undo_custom_profile)
        row.addWidget(self.custom_profile_apply_btn); row.addWidget(self.custom_profile_undo_btn); row.addStretch(); p.addLayout(row); v.addWidget(custom)
        self.refresh_custom_profiles()
        info=QLabel("Undo below restores the latest saved change in that category. Profiles keep their own Undo. Deleted files and native Settings changes have no app-side Undo."); info.setObjectName("muted"); info.setWordWrap(True); v.addWidget(info)
        self.quick_category_cards={}; self.quick_card_status={}; self.quick_card_support={}; self.quick_restore_buttons=[]; self.quick_view_buttons=[]; self.quick_apply_buttons=[]; self.inline_undo_buttons=self.quick_restore_buttons
        self.quick_grid=ResponsiveGrid(330,2)
        descriptions={"Windows Tweaks":"Optional menu and minimize/restore animations plus the documented Windows UI-effects switch. Disabling these changes visual feedback; choose what feels comfortable.","Startup Tweaks":"Disable only current-user entries in your saved approved selection. Security and driver entries remain protected.","CPU Tweaks":"Apply saved, enabled exact-path priority rules to matching processes. High priority can reduce responsiveness elsewhere.","GPU Tweaks":"Review native graphics and display controls. Availability depends on your Windows build, display and driver.","NVIDIA Tweaks":"Read adapter identity and open supported Windows tools. No vendor preset is applied.","AMD Tweaks":"Read adapter identity and open supported Windows tools. No vendor preset is applied.","Intel Tweaks":"Read adapter identity and open supported Windows tools. No vendor preset is applied."}
        for index,name in enumerate(self.QUICK_TAB_NAMES):
            direct=index<3
            frame,p=panel(name,descriptions[name]); frame.setObjectName("categoryCard")
            support=QLabel("Reversible controls · confirmation required" if direct and WIN else "Windows only" if direct else "Read-only tools / native Settings"); support.setObjectName("eyebrow"); support.setWordWrap(True); p.addWidget(support); self.quick_card_support[name]=support
            state=QLabel(); state.setObjectName("muted"); state.setWordWrap(True); p.addWidget(state); self.quick_card_status[name]=state
            row=QHBoxLayout(); apply_btn=QPushButton("Review & apply…" if direct else "Open tools"); apply_btn.setObjectName("categoryApply" if direct else "categoryView"); apply_btn.setAccessibleName(("Review and apply " if direct else "Open tools for ")+name)
            apply_btn.clicked.connect(lambda checked=False,n=name:self.apply_quick_category(n)); row.addWidget(apply_btn)
            preview=QPushButton("Preview"); preview.setAccessibleName("Preview "+name); preview.clicked.connect(lambda checked=False,n=name:self.preview_quick_category(n)); row.addWidget(preview); p.addLayout(row)
            row=QHBoxLayout(); restore_btn=QPushButton("Undo category"); restore_btn.clicked.connect(lambda checked=False,n=name:self.undo_quick_category(n)); row.addWidget(restore_btn)
            view_btn=QPushButton("View controls"); view_btn.setAccessibleName("View controls for "+name); view_btn.clicked.connect(lambda checked=False,i=index:self.view_quick_category(i)); row.addWidget(view_btn); p.addLayout(row)
            self.add_category_undo_status(name,p,restore_btn)
            self.quick_apply_buttons.append(apply_btn); self.quick_restore_buttons.append(restore_btn); self.quick_view_buttons.append(view_btn); self.quick_category_cards[name]=frame; self.quick_grid.add_card(frame)
        self.one_click_category_apply_buttons=[self.quick_apply_buttons[0],self.quick_apply_buttons[2],self.power_apply_btn,self.quick_apply_buttons[1]]
        v.addWidget(self.quick_grid)
        self.quick_tabs=QTabWidget(); self.quick_tabs.setAccessibleName("Quick Tweaks sections"); self.quick_tabs.setUsesScrollButtons(True); self.quick_tabs.tabBar().setExpanding(False)
        sections=[self.windows_tweaks_page,self.startup_tweaks_page,self.cpu_tweaks_page,self.gpu_tweaks_page,lambda:self.vendor_tweaks_page("NVIDIA"),lambda:self.vendor_tweaks_page("AMD"),lambda:self.vendor_tweaks_page("Intel")]
        for title,builder in zip(self.QUICK_TAB_NAMES,sections): self.quick_tabs.addTab(self.make_scroll(builder()),title)
        self.quick_tabs.setMinimumHeight(520)
        self.quick_tabs.setVisible(False); self.quick_tabs.currentChanged.connect(self.refresh_quick_section); v.addWidget(self.quick_tabs,1)
        self.refresh_quick_category_cards(); return w

    def add_category_undo_status(self,name,layout,button):
        status=QLabel(); status.setObjectName("muted"); status.setWordWrap(True); status.setAccessibleName(name+" Undo availability"); layout.addWidget(status)
        self.category_undo_buttons.setdefault(name,[]).append(button); self.category_undo_labels.setdefault(name,[]).append(status)

    def category_transactions(self,name):
        labels={"Gaming Tweaks":{"Gaming Tweaks","gaming preferences","Game Mode","background capture"},"Windows Tweaks":{"Windows Tweaks"},"Power Tweaks":{"Power Tweaks","power plan"},"Startup Tweaks":{"Startup Tweaks","startup entry","startup shortcut"},"CPU Tweaks":{"CPU Tweaks"}}
        matches=[]
        for index,tx in enumerate(self.undo.items):
            if tx.get("custom_profile_id") or tx.get("label","").endswith(" game profile"): continue
            types={action.get("type") for action in tx.get("actions",[])}
            cpu=name=="CPU Tweaks" and bool(types) and types<={"priority","affinity"}
            if tx.get("label") in labels.get(name,set()) or cpu: matches.append((index,tx))
        return matches

    def undo_quick_category(self,name):
        if self._operation_busy: return
        matches=self.category_transactions(name)
        if not matches:
            QMessageBox.information(self,name+" Undo","No saved changes are available in this category."); return
        index,tx=matches[-1]; label=tx.get("display_label",tx.get("label",name))
        watcher_note="\n\nAutomatic priority rules remain enabled and can reapply a saved priority. Pause the watcher before Undo if you want priorities to stay restored." if name=="CPU Tweaks" and self.settings.get("priority_rules_enabled",False) else ""
        if not self.ask("Undo "+name+"?",f"Restore the saved previous values for “{label}”?\n\nOnly this transaction will be restored. Settings changed afterward are left untouched; conflicts remain in Undo for review.{watcher_note}"): return
        self.set_busy(True,"Restoring "+label+"…")
        try:
            ok,message=self.undo._undo_at(index)
            if ok:
                for key,entry in list(self._priority_applied.items()):
                    if entry.get("tx") is tx: self._priority_applied.pop(key,None)
            write_activity("Undo "+name,message,"success" if ok else "conflict")
            self.set_operation_result("Complete" if ok else "Needs attention",message)
            (QMessageBox.information if ok else QMessageBox.warning)(self,name+" Undo",message)
        except Exception as exc:
            self.set_operation_result("Error",f"Undo could not be completed: {exc}"); QMessageBox.warning(self,name+" Undo",self.status.text())
        finally:
            self.set_busy(False)
            self.refresh_undo(); self.refresh_settings(); self.refresh_plans(); self.refresh_startup(); self.refresh_activity()

    def quick_preview_text(self,name):
        notes={
            "Gaming Tweaks":"Game Mode → On; Windows GameDVR recording → Off. Current values are checked again before confirmation. Background clips will stop; third-party capture is unchanged. No power or process-priority changes.",
            "Windows Tweaks":"Optional menu animations, minimize/restore animations, and the documented global UI-effects switch → Off when currently on. The UI-effects switch affects shadows, fades, and related presentation; it does not change transparency, accessibility client-area animation, or power plans. Visual feedback changes; no performance improvement is assumed.",
            "Power Tweaks":"Switch to an installed plan named High performance, only if available and not already active. This may increase power use, heat and fan noise. The final confirmation names the current and target plans; Undo saves the previous GUID.",
            "Startup Tweaks":f"Disable only {len(self.startup_profile)} saved approved current-user startup entry/entries. Changed, protected and all-users entries are skipped. Undo restores exact registry values or verified shortcuts.",
            "CPU Tweaks":f"{sum(1 for rule in self.priority_rules if rule.get('enabled',True) and rule.get('mode')=='automatic')} saved automatic priority rule(s); watcher {'enabled' if self.settings.get('priority_rules_enabled',False) else 'paused'}. Requires an enabled watcher and exact executable-path match. The final review lists eligible running processes. High priority may reduce responsiveness elsewhere. No Realtime, affinity or system-process changes."
        }
        text=notes.get(name,"Read-only adapter information and native Windows settings shortcuts. No direct preset is supported and opening this category does not modify Windows. Changes made in native Settings must be restored there.")
        matches=self.category_transactions(name)
        undo=f"{len(matches)} saved transaction(s). Latest: {matches[-1][1].get('label',name)}." if matches else "No saved transaction in this category."
        if name=="CPU Tweaks": text+=" Pause automatic rules before Undo if you want priorities to stay restored; an enabled watcher can reapply them."
        return text+"\n\nUndo: "+undo+"\n\nThis preview does not apply changes. Review & apply reads current values and asks for confirmation."

    def preview_quick_category(self,name):
        QMessageBox.information(self,name+" preview",self.quick_preview_text(name))

    def refresh_preset_plans(self):
        if not hasattr(self,"preset_power_combo"): return
        current=self.preset_power_combo.currentData(); preset=self.builtin_preset_combo.currentData() if hasattr(self,"builtin_preset_combo") else "Gaming"
        self.preset_power_combo.blockSignals(True); self.preset_power_combo.clear(); self.preset_power_combo.addItem("Leave power plan unchanged",None)
        try: available=plans() if WIN else []
        except Exception: available=[]
        for guid,title in available: self.preset_power_combo.addItem(title,guid)
        index=self.preset_power_combo.findData(current)
        if index<0:
            target="balanced" if preset=="Balanced" else "high performance" if preset=="Performance" else ""
            index=next((i for i in range(self.preset_power_combo.count()) if target and target in self.preset_power_combo.itemText(i).casefold()),0)
        self.preset_power_combo.setCurrentIndex(max(0,index)); self.preset_power_combo.blockSignals(False)
        self.update_builtin_preset_controls()

    def on_builtin_preset_changed(self,*_):
        if not hasattr(self,"builtin_preset_combo"): return
        selected=self.builtin_preset_combo.currentData()
        target="balanced" if selected=="Balanced" else "high performance" if selected=="Performance" else ""
        if target and hasattr(self,"preset_power_combo"):
            match=next((i for i in range(self.preset_power_combo.count()) if target in self.preset_power_combo.itemText(i).casefold()),0)
            self.preset_power_combo.setCurrentIndex(match)
        elif hasattr(self,"preset_power_combo"):
            self.preset_power_combo.setCurrentIndex(0)
        self.update_builtin_preset_controls()

    def update_builtin_preset_controls(self):
        if not hasattr(self,"builtin_preset_combo"): return
        selected=self.builtin_preset_combo.currentData()
        self.preset_capture_check.setVisible(selected=="Gaming")
        self.preset_visuals_check.setVisible(selected=="Performance")
        self.preset_priority_check.setVisible(selected in ("Gaming","Performance"))
        self.refresh_preset_controls()
        if hasattr(self,"preset_status"):
            description={"Gaming":"Turns on Game Mode. Background recording, power plan and saved automatic priorities are optional and require your review.","Performance":"Selects an installed High performance plan when available. Visual effects and saved priorities remain optional and require your review.","Balanced":"Selects an installed Balanced plan when available; it does not change capture, graphics, or priorities."}.get(selected,"Choose a preset.")
            self.preset_status.setText(description)

    def refresh_preset_controls(self):
        if not hasattr(self,"preset_undo_btn"): return
        preset=self.builtin_preset_combo.currentData() if hasattr(self,"builtin_preset_combo") else None
        preset_id=BUILTIN_PRESET_IDS.get(preset)
        pending=bool(preset_id and any(tx.get("custom_profile_id")==preset_id for tx in self.undo.items))
        self.preset_undo_btn.setEnabled(pending)
        if pending:
            tx=next(tx for tx in reversed(self.undo.items) if tx.get("custom_profile_id")==preset_id)
            self.preset_undo_btn.setText("Undo "+str(preset)+" Preset")
        else: self.preset_undo_btn.setText("Undo preset")

    def apply_selected_preset(self):
        if not hasattr(self,"builtin_preset_combo"): return
        name=self.builtin_preset_combo.currentData()
        saved_rules=[rule for rule in self.priority_rules if isinstance(rule,dict)]
        try:
            profile=build_builtin_preset(name,power_guid=self.preset_power_combo.currentData(),
                include_capture=self.preset_capture_check.isChecked(),include_visuals=self.preset_visuals_check.isChecked(),
                include_priority=self.preset_priority_check.isChecked(),saved_rules=saved_rules)
        except (ValueError,TypeError) as exc:
            QMessageBox.warning(self,"Preset unavailable",str(exc)); return
        if not any((profile["game_mode_on"],profile["capture_off"],profile["menu_animation_off"],profile["minimize_animation_off"],profile["ui_effects_off"],profile["power_guid"],profile["priority_rules"])):
            QMessageBox.information(self,"No preset changes selected","This preset has no compatible direct changes selected. Choose an installed power plan or an optional supported setting, then review again."); return
        self.apply_profile_definition(profile,preset=True)
        self.refresh_preset_controls()

    def undo_selected_preset(self):
        name=self.builtin_preset_combo.currentData() if hasattr(self,"builtin_preset_combo") else None
        preset_id=BUILTIN_PRESET_IDS.get(name)
        if not preset_id or not any(tx.get("custom_profile_id")==preset_id for tx in self.undo.items):
            QMessageBox.information(self,"Preset Undo","No saved changes are available for this preset."); return
        if not self.ask("Undo "+name+" Preset?","Restore the exact previous values saved by this preset? Settings changed afterward will be left untouched."): return
        ok,message=self.undo.undo_profile(preset_id)
        write_activity("Undo "+name+" Preset",message,"success" if ok else "conflict")
        self.set_operation_result("Complete" if ok else "Needs attention",message)
        (QMessageBox.information if ok else QMessageBox.warning)(self,"Preset Undo",message)
        self.refresh_undo(); self.refresh_settings(); self.refresh_plans(); self.refresh_startup(); self.refresh_activity(); self.refresh_preset_controls()

    def selected_custom_profile(self):
        profile_id=self.custom_profile_combo.currentData() if hasattr(self,"custom_profile_combo") else None
        return next((item for item in self.custom_profiles if item["id"]==profile_id),None)

    def refresh_custom_profiles(self,*_):
        if not hasattr(self,"custom_profile_combo"): return
        current=self.custom_profile_combo.currentData(); self.custom_profile_combo.blockSignals(True); self.custom_profile_combo.clear()
        for profile in self.custom_profiles: self.custom_profile_combo.addItem(profile["name"],profile["id"])
        index=self.custom_profile_combo.findData(current)
        if index<0 and self.custom_profile_combo.count(): index=0
        self.custom_profile_combo.setCurrentIndex(index); self.custom_profile_combo.blockSignals(False); self.refresh_custom_profile_controls()

    def refresh_custom_profile_controls(self,*_):
        if not hasattr(self,"custom_profile_combo"): return
        profile=self.selected_custom_profile(); enabled=profile is not None
        for button in (getattr(self,"custom_profile_edit_btn",None),getattr(self,"custom_profile_duplicate_btn",None),getattr(self,"custom_profile_delete_btn",None),getattr(self,"custom_profile_apply_btn",None)):
            if button: button.setEnabled(enabled)
        pending=bool(profile and any(tx.get("custom_profile_id")==profile["id"] for tx in self.undo.items))
        if hasattr(self,"custom_profile_undo_btn"): self.custom_profile_undo_btn.setEnabled(pending)
        if hasattr(self,"custom_profile_summary"):
            if not profile: self.custom_profile_summary.setText("No saved profiles. Create one and choose the reversible settings it should apply.")
            else:
                items=[]
                if profile["game_mode_on"]: items.append("Game Mode On")
                if profile["capture_off"]: items.append("background game recording Off")
                if profile["power_guid"]: items.append("selected power plan")
                if profile["menu_animation_off"]: items.append("menu animations Off")
                if profile["minimize_animation_off"]: items.append("minimize/restore animations Off")
                if profile.get("ui_effects_off",False): items.append("Windows UI effects Off")
                items.extend("priority: "+rule["name"] for rule in profile["priority_rules"])
                self.custom_profile_summary.setText(("Includes: "+", ".join(items)) if items else "This profile has no changes selected.")

    def save_custom_profile(self,profile):
        checked=validate_custom_profile(profile)
        if not any((checked["game_mode_on"],checked["capture_off"],checked["power_guid"],checked["menu_animation_off"],checked["minimize_animation_off"],checked["ui_effects_off"],checked["priority_rules"])):
            raise ValueError("Select at least one supported setting or saved priority rule.")
        for existing in self.custom_profiles:
            if existing["id"]!=checked["id"] and existing["name"].casefold()==checked["name"].casefold():
                raise ValueError("A profile with that name already exists.")
        updated=[item for item in self.custom_profiles if item["id"]!=checked["id"]]
        if not any(item["id"]==checked["id"] for item in self.custom_profiles) and len(updated)>=100: raise ValueError("You can save up to 100 profiles.")
        updated.append(checked); atomic_write_json(custom_profiles_file(),updated); self.custom_profiles=updated; self.refresh_custom_profiles()
        index=self.custom_profile_combo.findData(checked["id"]); self.custom_profile_combo.setCurrentIndex(index)
        return checked["id"]

    def custom_profile_dialog(self,existing=None):
        existing=existing or {}; dialog=QDialog(self); dialog.setWindowTitle("Edit profile" if existing else "Create profile"); dialog.setMinimumWidth(530)
        layout=QVBoxLayout(dialog); form=QFormLayout(); name=QLineEdit(existing.get("name","")); name.setMaxLength(64); name.setPlaceholderText("e.g. Fortnite Evening")
        form.addRow("Profile name",name); layout.addLayout(form)
        intro=QLabel("Choose supported changes. The profile only applies selected items and skips settings already at their target."); intro.setWordWrap(True); intro.setObjectName("muted"); layout.addWidget(intro)
        game=QCheckBox("Turn on Windows Game Mode"); game.setChecked(bool(existing.get("game_mode_on",False))); layout.addWidget(game)
        capture=QCheckBox("Turn off Windows background game recording"); capture.setChecked(bool(existing.get("capture_off",False))); layout.addWidget(capture)
        animation=QCheckBox("Turn off optional Windows menu animations"); animation.setChecked(bool(existing.get("menu_animation_off",False))); layout.addWidget(animation)
        minimize_animation=QCheckBox("Turn off minimize and restore window animations"); minimize_animation.setChecked(bool(existing.get("minimize_animation_off",False))); layout.addWidget(minimize_animation)
        ui_effects=QCheckBox("Turn off Windows UI effects (shadows, fades, and related effects)"); ui_effects.setToolTip("Changes the documented system-wide UI-effects preference. It can change visual feedback and is reversible."); ui_effects.setChecked(bool(existing.get("ui_effects_off",False))); layout.addWidget(ui_effects)
        plan=QComboBox(); plan.addItem("Leave power plan unchanged",None)
        available=plans() if WIN else []
        for guid,title in available: plan.addItem(title,guid)
        saved_guid=existing.get("power_guid")
        if saved_guid and plan.findData(saved_guid)<0: plan.addItem("Saved plan unavailable on this PC",saved_guid)
        if saved_guid: plan.setCurrentIndex(plan.findData(saved_guid))
        form.addRow("Power plan",plan)
        layout.addWidget(QLabel("Saved application priority rules"))
        rules=QListWidget(); rules.setAccessibleName("Priority rules included in this custom profile")
        selected={(item["path"],item["priority"]) for item in existing.get("priority_rules",[])}
        seen=set()
        for rule in self.priority_rules:
            if not isinstance(rule,dict) or not rule.get("enabled",True) or not isinstance(rule.get("path"),str) or rule.get("priority") not in PRIORITY_VALUES: continue
            path=os.path.normcase(os.path.abspath(rule["path"])); key=(path,rule["priority"])
            if key in seen: continue
            seen.add(key); row=QListWidgetItem(f"{rule.get('name',Path(path).name)} · {rule['priority']} · {path}")
            row.setFlags(row.flags()|Qt.ItemFlag.ItemIsUserCheckable); row.setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked); row.setData(Qt.ItemDataRole.UserRole,{"name":str(rule.get("name",Path(path).name)),"path":path,"priority":rule["priority"]}); rules.addItem(row)
        if not rules.count():
            empty=QListWidgetItem("No enabled saved priority rules are available."); empty.setFlags(Qt.ItemFlag.NoItemFlags); rules.addItem(empty)
        rules.setMaximumHeight(150); layout.addWidget(rules)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted: return None
        selected_rules=[]
        for index in range(rules.count()):
            item=rules.item(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.checkState()==Qt.CheckState.Checked: selected_rules.append(item.data(Qt.ItemDataRole.UserRole))
        return {"id":existing.get("id") or str(uuid.uuid4()),"name":name.text().strip(),"game_mode_on":game.isChecked(),"capture_off":capture.isChecked(),"menu_animation_off":animation.isChecked(),"minimize_animation_off":minimize_animation.isChecked(),"ui_effects_off":ui_effects.isChecked(),"power_guid":plan.currentData(),"priority_rules":selected_rules}

    def create_custom_profile(self):
        profile=self.custom_profile_dialog()
        if profile is None: return
        try: self.save_custom_profile(profile); QMessageBox.information(self,"Profile saved",f"{profile['name']} is ready to apply.")
        except (OSError,ValueError) as exc: QMessageBox.warning(self,"Could not save profile",str(exc))

    def edit_custom_profile(self):
        existing=self.selected_custom_profile()
        if not existing: return
        profile=self.custom_profile_dialog(existing)
        if profile is None: return
        try: self.save_custom_profile(profile); QMessageBox.information(self,"Profile updated",f"{profile['name']} was saved.")
        except (OSError,ValueError) as exc: QMessageBox.warning(self,"Could not update profile",str(exc))

    def duplicate_custom_profile(self):
        existing=self.selected_custom_profile()
        if not existing: return
        duplicate={**existing,"id":str(uuid.uuid4()),"name":existing["name"]+" Copy"}
        profile=self.custom_profile_dialog(duplicate)
        if profile is None: return
        try: self.save_custom_profile(profile); QMessageBox.information(self,"Profile duplicated",f"Saved {profile['name']}.")
        except (OSError,ValueError) as exc: QMessageBox.warning(self,"Could not duplicate profile",str(exc))

    def delete_custom_profile(self):
        profile=self.selected_custom_profile()
        if not profile: return
        if any(tx.get("custom_profile_id")==profile["id"] for tx in self.undo.items):
            QMessageBox.information(self,"Undo profile changes first","This profile has reversible changes. Undo them before deleting the profile so its restore control remains available."); return
        if not self.ask("Delete profile?",f"Delete {profile['name']}? This removes only the saved profile definition; no Windows settings are changed."): return
        updated=[item for item in self.custom_profiles if item["id"]!=profile["id"]]
        try: atomic_write_json(custom_profiles_file(),updated); self.custom_profiles=updated; self.refresh_custom_profiles()
        except OSError as exc: QMessageBox.warning(self,"Could not delete profile",str(exc))

    def apply_custom_profile(self):
        profile=self.selected_custom_profile()
        if not profile: QMessageBox.information(self,"Choose a profile","Create or select a saved profile first."); return
        self.apply_profile_definition(profile,preset=False)

    def apply_profile_definition(self,profile,preset=False):
        if not WIN or winreg is None: QMessageBox.information(self,"Windows-only profile","These profile settings are available only on Windows."); return
        proposed=[]; failures=[]; snapshots={}
        registry_targets=[]
        if profile["game_mode_on"]: registry_targets.append((GAMEBAR,"AutoGameModeEnabled",1,"Turn on Windows Game Mode"))
        if profile["capture_off"]:
            registry_targets.extend(((CAPTURE,"AppCaptureEnabled",0,"Turn off background game recording"),(GAMECONFIG,"GameDVR_Enabled",0,"Turn off Windows game recording")))
        for key,name,target,title in registry_targets:
            try:
                snap=reg_read(key,name); snapshots[(key,name)]=snap
                if snap[0] and snap[1]==target and snap[2]==winreg.REG_DWORD: continue
                proposed.append({"type":"reg","key":key,"name":name,"target":target,"snapshot":snap,"title":title})
            except Exception as exc: failures.append(f"{title}: unable to read setting ({exc})")
        if profile["menu_animation_off"]:
            try:
                state=system_menu_animation(); snapshots["menu_animation"]=state
                if state: proposed.append({"type":"animation","snapshot":state,"title":"Turn off optional Windows menu animations"})
            except Exception as exc: failures.append(f"Windows menu animations: unavailable ({exc})")
        if profile["minimize_animation_off"]:
            try:
                state=system_minimize_animation(); snapshots["minimize_animation"]=state
                if state: proposed.append({"type":"minimize_animation","snapshot":state,"title":"Turn off minimize and restore window animations"})
            except Exception as exc: failures.append(f"Minimize/restore animations: unavailable ({exc})")
        if profile.get("ui_effects_off",False):
            try:
                state=system_ui_effects(); snapshots["ui_effects"]=state
                if state: proposed.append({"type":"ui_effects","snapshot":state,"title":"Turn off Windows UI effects (shadows, fades, and related effects)"})
            except Exception as exc: failures.append(f"Windows UI effects: unavailable ({exc})")
        if profile["power_guid"]:
            try:
                choices=plans(); match=next(((g,t) for g,t in choices if g.casefold()==profile["power_guid"].casefold()),None)
                if not match: failures.append("Selected power plan is not available on this PC.")
                else:
                    old,old_title=active_plan(); target,title=match
                    if not old: failures.append(f"Unable to read the active power plan: {old_title}")
                    elif old.casefold()!=target.casefold(): proposed.append({"type":"power","old":old,"target":target,"title":f"Switch power plan to {title}"})
            except Exception as exc: failures.append(f"Power plan: unavailable ({exc})")
        if profile["priority_rules"]:
            targets={}
            try:
                for info in self._enumerate_priority_targets(): targets.setdefault(info[2],[]).append(info)
            except Exception as exc: failures.append(f"Could not inspect running apps for saved priority rules ({exc})")
            for saved in profile["priority_rules"]:
                rule=next((r for r in self.priority_rules if isinstance(r,dict) and os.path.normcase(os.path.abspath(r.get("path","")))==saved["path"] and r.get("priority")==saved["priority"] and r.get("enabled",True)),None)
                if not rule: failures.append(f"{saved['name']}: saved priority rule was removed, disabled, or changed."); continue
                matched=False
                for info in targets.get(saved["path"],[]):
                    matched=True; pid,name,exe,created=info
                    try:
                        process=psutil.Process(pid)
                        if abs(process.create_time()-created)>.02 or protected_process(name,exe): raise RuntimeError("process is no longer eligible or is protected")
                        old=process.nice(); target=PRIORITY_VALUES[saved["priority"]]
                        if old!=target: proposed.append({"type":"priority","info":info,"old":old,"target":target,"title":f"Set {name} priority to {saved['priority']}"})
                    except Exception as exc: failures.append(f"{saved['name']}: {exc}")
                if not matched: failures.append(f"{saved['name']}: no running app matched the saved executable path.")
        if not proposed:
            message="No changes are needed." if not failures else "No compatible changes were applied."
            if failures: message+="\n\nSkipped / unavailable:\n"+"\n".join("• "+item for item in failures)
            QMessageBox.information(self,"Profile status",message); return
        details="\n".join("• "+item["title"] for item in proposed)
        if failures: details+="\n\nThese items will be skipped:\n"+"\n".join("• "+item for item in failures)
        if not self.ask(f"Apply {profile['name']}?",f"Kam3 Tweaks will apply {len(proposed)} setting(s). Already-correct settings are skipped. Changes can be undone.\n\n{details}"): return

        def run():
            applied=[]; errors=list(failures)
            for operation in proposed:
                try:
                    if operation["type"]=="reg":
                        key,name,target=operation["key"],operation["name"],operation["target"]
                        if reg_read(key,name)!=operation["snapshot"]:
                            now=reg_read(key,name)
                            if now[0] and now[1]==target and now[2]==winreg.REG_DWORD: continue
                            raise RuntimeError("setting changed after confirmation; left untouched")
                        set_dword(self.undo,key,name,target)
                        if reg_read(key,name)!=(True,target,winreg.REG_DWORD): raise RuntimeError("verification failed")
                    elif operation["type"]=="animation":
                        if system_menu_animation()!=operation["snapshot"]:
                            if system_menu_animation() is False: continue
                            raise RuntimeError("setting changed after confirmation; left untouched")
                        self.undo.record({"type":"spi_bool","old":operation["snapshot"],"expected":False}); system_menu_animation(False)
                        if system_menu_animation() is not False: raise RuntimeError("verification failed")
                    elif operation["type"]=="minimize_animation":
                        if system_minimize_animation()!=operation["snapshot"]:
                            if system_minimize_animation() is False: continue
                            raise RuntimeError("setting changed after confirmation; left untouched")
                        self.undo.record({"type":"spi_minimize_animation","old":operation["snapshot"],"expected":False}); system_minimize_animation(False)
                        if system_minimize_animation() is not False: raise RuntimeError("verification failed")
                    elif operation["type"]=="ui_effects":
                        if system_ui_effects()!=operation["snapshot"]:
                            if system_ui_effects() is False: continue
                            raise RuntimeError("setting changed after confirmation; left untouched")
                        self.undo.record({"type":"spi_ui_effects","old":operation["snapshot"],"expected":False}); system_ui_effects(False)
                        if system_ui_effects() is not False: raise RuntimeError("verification failed")
                    elif operation["type"]=="power":
                        now,_=active_plan()
                        if now and now.casefold()==operation["target"].casefold(): continue
                        if not now or now.casefold()!=operation["old"].casefold(): raise RuntimeError("active power plan changed after confirmation; left untouched")
                        self.undo.record({"type":"power","guid":operation["old"],"expected":operation["target"]})
                        code,out,err=command(["powercfg","/setactive",operation["target"]])
                        if code: raise RuntimeError(err or out or "Windows rejected the power-plan change")
                        current,_=active_plan()
                        if not current or current.casefold()!=operation["target"].casefold(): raise RuntimeError("verification failed")
                    elif operation["type"]=="priority":
                        pid,name,exe,created=operation["info"]; process=psutil.Process(pid)
                        if abs(process.create_time()-created)>.02 or protected_process(name,exe): raise RuntimeError("process changed or is protected")
                        current=process.nice()
                        if current==operation["target"]: continue
                        if current!=operation["old"]: raise RuntimeError("priority changed after confirmation; left untouched")
                        self.undo.record({"type":"priority","pid":pid,"created":created,"old":operation["old"],"expected":operation["target"]})
                        process.nice(operation["target"])
                        if process.nice()!=operation["target"]: raise RuntimeError("verification failed")
                        self._priority_applied[(exe,pid,created)]={"old":operation["old"],"target":operation["target"],"tx":self.undo.current,"name":name,"created":created}
                    applied.append(operation["title"])
                except Exception as exc: errors.append(f"{operation['title']}: {exc}")
            result=[f"{len(applied)} change(s) applied and verified for {profile['name']}; {max(0,len(proposed)-len(applied))} skipped."]
            result.extend("Applied: "+item for item in applied)
            if errors: result.append("\nFailed:"); result.extend(errors)
            return "\n".join(result)
        if preset:
            label=f"Built-in Preset {profile['id']}"
            metadata={"custom_profile_id":profile["id"],"builtin_preset":profile["name"],"display_label":profile["name"]}
        else:
            label=f"Custom Profile {profile['id']}"
            metadata={"custom_profile_id":profile["id"],"display_label":f"Profile: {profile['name']}"}
        self.finish_change(label,run,transaction_metadata=metadata)

    def undo_custom_profile(self):
        profile=self.selected_custom_profile()
        if not profile: return
        matches=[tx for tx in self.undo.items if tx.get("custom_profile_id")==profile["id"]]
        if not matches: QMessageBox.information(self,"Profile Undo",f"No saved changes are available for {profile['name']}."); return
        if not self.ask(f"Undo {profile['name']}?","Restore the exact values saved by the latest application of this profile? Settings changed afterward will be left untouched."): return
        category_txs=matches
        ok,message=self.undo.undo_profile(profile["id"])
        if ok:
            for key,entry in list(self._priority_applied.items()):
                if any(entry.get("tx") is tx for tx in category_txs): self._priority_applied.pop(key,None)
        self.status.setText(message); write_activity(f"Undo profile {profile['name']}",message,"success" if ok else "conflict")
        (QMessageBox.information if ok else QMessageBox.warning)(self,"Profile Undo",message)
        self.refresh_custom_profile_controls(); self.refresh_undo(); self.refresh_activity()

    def apply_gaming_tweaks(self):
        if not WIN or winreg is None:
            QMessageBox.information(self,"Gaming Tweaks unavailable","These Windows settings are available only on Windows."); return
        specs=[(GAMEBAR,"AutoGameModeEnabled",1,"Turn on Windows Game Mode"),
               (CAPTURE,"AppCaptureEnabled",0,"Turn off background gameplay recording"),
               (GAMECONFIG,"GameDVR_Enabled",0,"Turn off Windows game recording")]
        changes=[]; errors=[]
        for key,name,target,label in specs:
            try:
                exists,value,kind=reg_read(key,name)
                if exists and value==target and kind==winreg.REG_DWORD: continue
                changes.append((key,name,target,label))
            except Exception as exc: errors.append(f"{label}: unable to read current setting ({exc})")
        plan_guid,plan_name=active_plan()
        plan_note=f"Current power plan: {plan_name}. It will not be changed because no gaming power plan was explicitly selected."
        if not changes:
            msg="No Game Mode or background recording changes are needed." if not errors else "No changes could be safely planned.\n"+"\n".join(errors)
            QMessageBox.information(self,"Gaming Tweaks",msg+"\n\n"+plan_note); return
        listing="\n".join("• "+item[3] for item in changes)
        read_note=("\n\nCould not inspect:\n"+"\n".join("• "+item for item in errors)) if errors else ""
        if not self.ask("Apply Gaming Tweaks?",f"Kam3 Tweaks will apply {len(changes)} reversible change(s):\n\n{listing}{read_note}\n\n{plan_note}\n\nNo process priorities will be changed."): return
        def run():
            succeeded=[]; failed=list(errors)
            for key,name,target,label in changes:
                try:
                    set_dword(self.undo,key,name,target)
                    exists,value,kind=reg_read(key,name)
                    if not exists or value!=target or kind!=winreg.REG_DWORD: raise RuntimeError("Verification did not match the requested value.")
                    succeeded.append(label)
                except Exception as exc: failed.append(f"{label}: {exc}")
            summary=[f"{len(succeeded)} change(s) verified."]
            if succeeded: summary.extend("Applied: "+item for item in succeeded)
            if failed: summary.extend("Failed: "+item for item in failed)
            if not succeeded and not failed: summary.append("All requested settings were already configured correctly.")
            return "\n".join(summary)
        self.finish_change("Gaming Tweaks",run)

    def undo_gaming_tweaks(self):
        self.undo_named_category("Gaming Tweaks")

    def undo_named_category(self,label):
        if not any(item.get("label")==label for item in self.undo.items):
            QMessageBox.information(self,f"{label} Undo",f"No saved {label} changes are available."); return
        if not self.ask(f"Undo {label}?",f"Restore the original settings recorded by {label}? If any setting changed afterward, that setting will be left untouched."): return
        category_txs=[item for item in self.undo.items if item.get("label")==label]
        ok,message=self.undo.undo_category(label)
        if ok and label=="CPU Tweaks":
            for key,entry in list(self._priority_applied.items()):
                if any(entry.get("tx") is tx for tx in category_txs): self._priority_applied.pop(key,None)
        self.status.setText(message); write_activity("Undo "+label,message,"success" if ok else "conflict")
        (QMessageBox.information if ok else QMessageBox.warning)(self,f"{label} Undo",message)
        self.refresh_undo(); self.refresh_settings(); self.refresh_plans(); self.refresh_startup(); self.refresh_activity()

    def explain_windows_tweaks(self,name="Windows Tweaks"):
        QMessageBox.information(self,name,"The one-click category covers optional menu/window animations and the documented UI-effects switch. Mouse pointer acceleration is a separate opt-in control because pointer feel is personal and should not change silently. Transparency, taskbar behavior, and per-app background permissions remain Windows Settings shortcuts because this app does not write unsupported preference values.")

    def apply_mouse_acceleration(self):
        if not WIN:
            QMessageBox.information(self,"Mouse acceleration","This control is available on Windows only."); return
        try: original=system_mouse_info()
        except Exception as exc:
            QMessageBox.warning(self,"Mouse settings unavailable",f"Windows did not return the current mouse thresholds and acceleration level. No change was made.\n\n{exc}"); return
        target=(0,0,0)
        if original==target:
            QMessageBox.information(self,"Mouse acceleration","Pointer acceleration thresholds and level are already zero."); return
        detail=(f"Current SPI_GETMOUSE values: {original}.\nProposed values: {target}.\n\n"
                "This disables Windows pointer acceleration by setting both thresholds and acceleration level to zero. Mouse feel will change; no FPS, ping, or latency improvement is claimed. Undo restores all three exact original values. No administrator permission or restart is normally required.")
        if not self.ask("Disable pointer acceleration?",detail): return
        def run():
            current=system_mouse_info()
            if current==target: return "Pointer acceleration was already disabled before applying."
            if current!=original: raise RuntimeError("Mouse settings changed after review; the newer values were left untouched.")
            self.undo.record({"type":"spi_mouse","old":list(original),"expected":list(target)})
            system_mouse_info(target)
            if system_mouse_info()!=target: raise RuntimeError("Windows did not verify the requested mouse acceleration values.")
            return "Pointer acceleration thresholds and level were set to zero and verified. Exact prior values are saved for Undo."
        self.finish_change("Mouse pointer acceleration",run)

    def apply_ui_effects_direct(self):
        if not WIN:
            QMessageBox.information(self,"Windows UI effects","This direct preference is available on Windows only."); return
        try: original=system_ui_effects()
        except Exception as exc:
            QMessageBox.warning(self,"Windows UI effects unavailable",f"Could not read the current preference. No change was made.\n\n{exc}"); return
        if not original:
            QMessageBox.information(self,"Windows UI effects","The supported UI-effects preference is already disabled."); return
        if self._batch_running:
            confirmed=True
        else:
            confirmed=self.ask("Disable Windows UI effects?","This changes the system-wide optional UI-effects preference, including shadows, fades, and related visual feedback. It may reduce visual cues; no FPS improvement is promised. Undo restores the saved original value.")
        if not confirmed: return
        def run():
            current=system_ui_effects()
            if current is False: return "Windows UI effects were already disabled before applying; no change was made."
            if current is not original: raise RuntimeError("The setting changed after review; no newer value was overwritten.")
            self.undo.record({"type":"spi_ui_effects","old":original,"expected":False})
            system_ui_effects(False)
            if system_ui_effects() is not False: raise RuntimeError("Windows did not verify the requested UI-effects state.")
            return "Windows UI effects disabled and verified. The exact previous state is saved for Undo."
        self.finish_change("Windows Tweaks",run)

    def apply_windows_tweaks(self,name="Windows Tweaks"):
        changes=[]; failures=[]
        for kind,title,reader in (("menu","Turn off optional Windows menu animations",system_menu_animation),("minimize","Turn off minimize and restore window animations",system_minimize_animation),("ui_effects","Turn off Windows UI effects (shadows, fades, and related effects)",system_ui_effects)):
            try:
                current=reader()
                if current: changes.append((kind,title,current))
            except Exception as exc: failures.append(f"{title}: {exc}")
        if not changes:
            if failures: QMessageBox.warning(self,"Windows Tweaks unavailable","No changes were made.\n\n"+"\n".join(failures))
            else: QMessageBox.information(self,"Windows Tweaks","Supported optional menu and minimize/restore animations are already disabled.")
            return
        details="\n".join("• "+title for _,title,_ in changes)
        if failures: details+="\n\nUnavailable (will be skipped):\n"+"\n".join("• "+error for error in failures)
        if not self.ask("Apply Windows Tweaks?",f"Disable the listed supported preferences? The UI-effects switch affects system-wide shadows, fades, and related visual feedback. These changes are reversible; they do not change transparency or the accessibility client-area animation setting. No FPS improvement is promised.\n\n{details}"): return
        def run():
            applied=[]; errors=list(failures)
            for kind,title,old in changes:
                try:
                    reader={"menu":system_menu_animation,"minimize":system_minimize_animation,"ui_effects":system_ui_effects}[kind]
                    current=reader()
                    if current!=old:
                        if current is False: continue
                        raise RuntimeError("setting changed after confirmation; left untouched")
                    action_type={"menu":"spi_bool","minimize":"spi_minimize_animation","ui_effects":"spi_ui_effects"}[kind]
                    self.undo.record({"type":action_type,"old":old,"expected":False}); reader(False)
                    if reader() is not False: raise RuntimeError("verification failed")
                    applied.append(title)
                except Exception as exc: errors.append(f"{title}: {exc}")
            result=[f"{len(applied)} Windows preference(s) applied and verified."]
            result.extend("Applied: "+title for title in applied)
            if errors: result.append("\nFailed:"); result.extend(errors)
            return "\n".join(result)
        self.finish_change("Windows Tweaks",run)

    def explain_no_direct_tweaks(self,name):
        QMessageBox.information(self,name,"No compatible direct changes are currently supported in this category. View Changes may show read-only information or Windows shortcuts; those are not applied optimizations.")

    def apply_power_tweaks(self):
        if not WIN: QMessageBox.information(self,"Power Tweaks","Power-plan controls are available on Windows only."); return
        available=plans(); target=next(((guid,title) for guid,title in available if title.strip().casefold()=="high performance"),None)
        current,current_title=active_plan()
        if not current or not target: QMessageBox.information(self,"Power Tweaks","High performance is not available or Windows could not read the active plan. No change was made."); return
        guid,title=target
        if current.casefold()==guid.casefold(): QMessageBox.information(self,"Power Tweaks","High performance is already active."); return
        if not self.ask("Apply Power Tweaks?",f"Switch from {current_title} to {title}? This is reversible and may increase power use, heat, and fan noise."): return
        def run():
            self.undo.record({"type":"power","guid":current,"expected":guid}); code,out,err=command(["powercfg","/setactive",guid])
            if code: raise RuntimeError(err or out or "Windows rejected the power-plan change.")
            actual,_=active_plan()
            if not actual or actual.casefold()!=guid.casefold(): raise RuntimeError("Power-plan verification failed.")
            return f"Power Tweaks applied. Active plan verified: {title}."
        self.finish_change("Power Tweaks",run)

    def apply_cpu_tweaks(self):
        rules=[r for r in self.priority_rules if r.get("enabled",True) and r.get("mode")=="automatic"]
        if not WIN or not self.settings.get("priority_rules_enabled",False) or not rules:
            QMessageBox.information(self,"CPU Tweaks","No enabled saved automatic priority rules are available. CPU affinity and system processes will not be changed."); return
        targets=self._enumerate_priority_targets(); operations=[]
        for rule in rules:
            path=os.path.normcase(os.path.abspath(rule["path"]))
            for info in targets:
                if info[2]==path and (path,info[0],info[3]) not in self._priority_applied:
                    operations.append((rule,info))
        if not operations: QMessageBox.information(self,"CPU Tweaks","No eligible running applications matched the saved rules."); return
        summary="\n".join(f"{info[1]} → {rule['priority']}" for rule,info in operations)
        if not self.ask("Apply CPU Tweaks?",f"Apply these saved priorities? Only exact executable-path matches are included. No affinity or Realtime changes will be made.\n\n{summary}"): return
        def run():
            changed=[]; failed=[]
            for rule,info in operations:
                pid,name,exe,created=info
                try:
                    process=psutil.Process(pid)
                    if abs(process.create_time()-created)>.02 or protected_process(name,exe): raise RuntimeError("Process changed or is protected.")
                    old=process.nice(); target=PRIORITY_VALUES[rule["priority"]]
                    if old==target: continue
                    self.undo.record({"type":"priority","pid":pid,"created":created,"old":old,"expected":target})
                    process.nice(target)
                    if process.nice()!=target: raise RuntimeError("Priority verification failed.")
                    self._priority_applied[(exe,pid,created)]={"old":old,"target":target,"tx":self.undo.current,"name":name,"created":created}
                    changed.append(name)
                except Exception as exc: failed.append(f"{name}: {exc}")
            result=[f"{len(changed)} application(s) verified."]
            result.extend("Applied: "+n for n in changed); result.extend("Failed: "+n for n in failed)
            return "\n".join(result)
        self.finish_change("CPU Tweaks",run)

    def refresh_quick_category_cards(self):
        if not hasattr(self,"quick_card_status"): return
        rules=[r for r in self.priority_rules if r.get("enabled",True) and r.get("mode")=="automatic"]
        states={"Windows Tweaks":"Animation and UI-effects state · refresh in the section below",
                "Startup Tweaks":"Review entries on request",
                "CPU Tweaks":f"{len(rules)} automatic rules enabled" if self.settings.get("priority_rules_enabled",False) else "Priority watcher paused",
                "GPU Tweaks":"Native Windows graphics options",
                "NVIDIA Tweaks":"Adapter detection on request","AMD Tweaks":"Adapter detection on request","Intel Tweaks":"Adapter detection on request"}
        for name,value in states.items(): self.quick_card_status[name].setText(f"Current status: {value}")

    def view_quick_category(self,index):
        self.quick_tabs.setVisible(True); self.quick_tabs.setCurrentIndex(index)
        self.stack.widget(1).ensureWidgetVisible(self.quick_tabs)
        self.refresh_quick_section(index)

    def apply_quick_category(self,name):
        if self._operation_busy: return
        actions={"Windows Tweaks":self.apply_windows_tweaks,"Startup Tweaks":self.apply_startup_profile,"CPU Tweaks":self.apply_cpu_tweaks,"Power Tweaks":self.apply_power_tweaks,"Gaming Tweaks":self.apply_gaming_tweaks}
        if name in actions:
            actions[name](); return
        if name in self.QUICK_TAB_NAMES:
            self.view_quick_category(self.QUICK_TAB_NAMES.index(name))
            return
        self.explain_no_direct_tweaks(name)

    def refresh_quick_section(self,index):
        self.refresh_quick_category_cards()
        if index==0: self.refresh_settings(); self.refresh_plans(); self.refresh_windows_status(); self.refresh_preset_plans()
        elif index==1: self.refresh_startup()
        elif index==2: self.refresh_processes(); self.refresh_priority_rules()
        elif index==3: self.refresh_hardware_summary()
        else: self.refresh_vendor_summary(index-4)

    def open_quick_tab(self,title):
        try: index=self.QUICK_TAB_NAMES.index(title)
        except ValueError: index=0
        self.select_page(self.PAGE_NAMES.index("Quick Tweaks")); self.view_quick_category(index)

    def vendor_tweaks_page(self,vendor):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(10,10,10,10); v.setSpacing(10)
        self.add_page_heading(v,f"{vendor} graphics compatibility", "Read-only adapter detection and documented Windows controls. Kam3 Tweaks does not install drivers or write vendor-specific registry settings.")
        f,p=panel("Detected adapters", "Adapter names are read on request. No sensor polling is performed.")
        label=QLabel("Select Refresh to inspect available display adapters."); label.setObjectName("muted"); label.setWordWrap(True); setattr(self,f"{vendor.casefold()}_adapter_text",label); p.addWidget(label)
        row=QHBoxLayout(); refresh=QPushButton("Refresh adapter information"); refresh.clicked.connect(lambda _=False,i=self.QUICK_TAB_NAMES.index(f"{vendor} Tweaks"):self.refresh_vendor_summary(i-4)); row.addWidget(refresh)
        graphics=QPushButton("Open Windows Graphics settings"); graphics.clicked.connect(self.open_gpu_settings); row.addWidget(graphics)
        driver=QPushButton("Open Device Manager"); driver.clicked.connect(lambda:self.open_settings_uri("devmgmt.msc","Device Manager")); row.addWidget(driver); row.addStretch(); p.addLayout(row); v.addWidget(f)
        v.addStretch(); return w

    def refresh_vendor_summary(self,vendor_index):
        if not 0<=vendor_index<3: return
        vendor=("NVIDIA","AMD","Intel")[vendor_index]; label=getattr(self,f"{vendor.casefold()}_adapter_text",None)
        if label is None: return
        try:
            names=gpu_adapters(); matching=[name for name in names if gpu_vendor(name)==vendor]
            if matching: text="\n".join(matching)+"\n\nUse Windows Graphics settings for per-app preference. Driver configuration remains in the vendor's supported tools."
            elif names: text=f"No {vendor} adapter detected. Detected: {', '.join(names)}."
            else: text="Adapter information is unavailable. Check Device Manager; this is not a hardware telemetry reading."
            label.setText(text)
        except Exception as e: label.setText(f"Adapter information unavailable: {e}")


    def games_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(2,6,10,8); v.setSpacing(12)
        self.add_page_heading(v,"Gaming","Manage game-specific profiles and Windows capture preferences. Profiles are opt-in and never touch game files or anti-cheat software.")
        f,p=panel("Windows gaming preferences","These direct controls change current-user settings. Windows policy may override them; changes require confirmation and can be undone.")
        self.mode=QComboBox(); self.mode.addItems(["On","Off"]); self.mode.setCurrentIndex(-1); self.mode.setAccessibleName("Game Mode preference")
        self.capture=QComboBox(); self.capture.addItems(["Off","On"]); self.capture.setCurrentIndex(-1); self.capture.setAccessibleName("Background capture preference")
        for label,combo,text,slot in (("Game Mode",self.mode,"Apply Game Mode",self.apply_mode),("GameDVR background capture",self.capture,"Apply capture setting",self.apply_capture)):
            row=QHBoxLayout(); row.addWidget(QLabel(label)); row.addStretch(); row.addWidget(combo); btn=QPushButton(text); btn.clicked.connect(slot); row.addWidget(btn); p.addLayout(row)
            if label=="Game Mode": self.mode_btn=btn
            else: self.capture_btn=btn
        self.profile_status=QLabel("Settings have not been read yet."); self.profile_status.setObjectName("muted"); p.addWidget(self.profile_status)
        self.profile_btn=QPushButton("Apply common gaming preferences…"); self.profile_btn.setObjectName("primary"); self.profile_btn.clicked.connect(self.apply_profile); p.addWidget(self.profile_btn,alignment=Qt.AlignmentFlag.AlignLeft); v.addWidget(f)
        f,p=panel("Game library","Saved executable paths and profiles stay in local app data. Launch and apply actions always use the selected exact path.")
        self.game_list=QListWidget(); self.game_list.setMaximumHeight(150); self.game_list.currentRowChanged.connect(self.game_selected); p.addWidget(self.game_list)
        row=QHBoxLayout(); self.game_add_btn=QPushButton("Add executable…"); self.game_add_btn.clicked.connect(self.add_game); self.game_remove_btn=QPushButton("Remove from library"); self.game_remove_btn.clicked.connect(self.remove_game); self.game_launch_btn=QPushButton("Launch selected"); self.game_launch_btn.clicked.connect(self.launch_selected_game); row.addWidget(self.game_add_btn); row.addWidget(self.game_remove_btn); row.addWidget(self.game_launch_btn); p.addLayout(row)
        self.game_selected_path=QLabel("Select a saved game to view its executable path."); self.game_selected_path.setObjectName("muted"); self.game_selected_path.setWordWrap(True); p.addWidget(self.game_selected_path)
        self.game_profile=QComboBox(); self.game_profile.addItem("Medium",PRIORITY_VALUES["Medium"]); self.game_profile.addItem("High",PRIORITY_VALUES["High"]); self.game_profile.addItem("Low",PRIORITY_VALUES["Low"]); self.game_profile.currentIndexChanged.connect(self.save_game_profile)
        row=QHBoxLayout(); row.addWidget(QLabel("Selected game's saved priority")); row.addStretch(); row.addWidget(self.game_profile); self.game_profile_btn=QPushButton("Apply to running instance…"); self.game_profile_btn.clicked.connect(self.apply_game_profile); row.addWidget(self.game_profile_btn); p.addLayout(row); v.addWidget(f)
        f,p=panel("Profiles for Fortnite, Project Retrac, and Minecraft","Each profile is a saved template. Pick only the changes you want; applying requires an exact running executable, confirmation, and available permissions.")
        row=QHBoxLayout(); self.profile_key_combo=QComboBox(); self.profile_key_combo.addItems(["Fortnite","Project Retrac","Minecraft"]); self.profile_key_combo.setAccessibleName("Game profile to edit"); self.profile_key_combo.currentTextChanged.connect(self.load_profile_editor); row.addWidget(QLabel("Profile")); row.addWidget(self.profile_key_combo); self.profile_assign_btn=QPushButton("Assign to selected game"); self.profile_assign_btn.clicked.connect(self.assign_game_profile); row.addWidget(self.profile_assign_btn); p.addLayout(row)
        self.profile_mode=QComboBox(); self.profile_mode.addItems(["Unchanged","On","Off"]); self.profile_capture=QComboBox(); self.profile_capture.addItems(["Unchanged","On","Off"]); self.profile_plan=QComboBox(); self.profile_priority=QComboBox(); self.profile_priority.addItems(["Unchanged","Medium","High","Low"])
        for title,widget in (("Game Mode",self.profile_mode),("Background capture",self.profile_capture),("Power plan",self.profile_plan),("Process priority",self.profile_priority)):
            line=QHBoxLayout(); line.addWidget(QLabel(title)); line.addStretch(); line.addWidget(widget); p.addLayout(line)
        row=QHBoxLayout(); self.profile_save_btn=QPushButton("Save profile locally"); self.profile_save_btn.clicked.connect(self.save_profile_editor); self.profile_apply_btn=QPushButton("Apply profile to running game…"); self.profile_apply_btn.clicked.connect(self.apply_game_profile); row.addWidget(self.profile_save_btn); row.addWidget(self.profile_apply_btn); p.addLayout(row); v.addWidget(f)
        f,p=panel("Xbox Game Bar","Game Bar behavior is managed by Windows and may vary by Windows version.")
        self.gamebar_settings_btn=QPushButton("Open Game Bar settings"); self.gamebar_settings_btn.clicked.connect(lambda:self.open_settings_uri("ms-settings:gaming-gamebar","Game Bar")); p.addWidget(self.gamebar_settings_btn,alignment=Qt.AlignmentFlag.AlignLeft); v.addWidget(f)
        v.addStretch(); return w

    def cpu_tweaks_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(2,6,8,8); v.setSpacing(10)
        self.add_page_heading(v,"CPU Tweaks","Inspect running applications on demand. Rules match exact executable paths and run only while Kam3 Tweaks is open.")
        f,p=panel("Running processes","Select a process to inspect it. Selection alone never changes priority; one-time changes require confirmation. Protected Windows processes are blocked.")
        self.search=QLineEdit(); self.search.setPlaceholderText("Filter process name, executable path, or PID…"); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.refresh_processes); p.addWidget(self.search)
        self.proc_list=QListWidget(); self.proc_list.setMinimumHeight(230); p.addWidget(self.proc_list,1)
        self.proc_list.currentItemChanged.connect(lambda *_:self.process_selected())
        row=QHBoxLayout(); row.addWidget(QLabel("Sort by")); self.process_sort=QComboBox(); self.process_sort.addItems(["Name A–Z","Name Z–A","PID low to high","PID high to low"]); self.process_sort.currentIndexChanged.connect(self.refresh_processes); row.addWidget(self.process_sort); row.addWidget(QLabel("Priority")); self.priority=QComboBox(); self.priority.setToolTip("High may reduce responsiveness of other applications. Medium is standard Windows priority. Low is intended for background applications. No Realtime option is offered."); self.priority.addItem("High",PRIORITY_VALUES["High"]); self.priority.addItem("Medium",PRIORITY_VALUES["Medium"]); self.priority.addItem("Low",PRIORITY_VALUES["Low"]); row.addWidget(self.priority); self.priority_btn=QPushButton("Apply once…"); self.priority_btn.clicked.connect(self.apply_priority); row.addWidget(self.priority_btn); self.affinity_btn=QPushButton("CPU affinity…"); self.affinity_btn.clicked.connect(self.apply_affinity); row.addWidget(self.affinity_btn); refresh=QPushButton("Refresh"); refresh.clicked.connect(self.refresh_processes); row.addWidget(refresh); p.addLayout(row)
        self.process_details=QLabel("Select a row to inspect process details."); self.process_details.setObjectName("muted"); self.process_details.setWordWrap(True); p.addWidget(self.process_details); v.addWidget(f,1)
        if not WIN: self.priority_btn.setEnabled(False)
        f,p=panel("Saved priority rules","High maps to HIGH_PRIORITY_CLASS; Medium to NORMAL_PRIORITY_CLASS; Low to BELOW_NORMAL_PRIORITY_CLASS. High priority can harm overall responsiveness. Higher priority does not imply higher FPS.")
        row=QHBoxLayout(); self.priority_master=QCheckBox("Enable automatic rules while this app is open"); self.priority_master.setChecked(bool(self.settings.get("priority_rules_enabled",False))); self.priority_master.toggled.connect(self.toggle_priority_master); row.addWidget(self.priority_master); self.apply_rules_btn=QPushButton("Apply Rules Now…"); self.apply_rules_btn.clicked.connect(self.apply_rules_now); row.addWidget(self.apply_rules_btn); v.addWidget(f); p.addLayout(row)
        self.rule_search=QLineEdit(); self.rule_search.setPlaceholderText("Search rules by application or executable path…"); self.rule_search.setClearButtonEnabled(True); self.rule_search.textChanged.connect(self.filter_priority_rules); p.addWidget(self.rule_search)
        self.rules_table=QTableWidget(0,6); self.rules_table.setHorizontalHeaderLabels(["Application","Executable path","Priority","Mode","Enabled","Last result"]); self.rules_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents); self.rules_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch); self.rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); p.addWidget(self.rules_table,1); self.rules_table.itemSelectionChanged.connect(self.load_selected_rule)
        form=QFormLayout(); self.rule_name=QLineEdit(); self.rule_name.setPlaceholderText("Application name"); pathrow=QHBoxLayout(); self.rule_path=QLineEdit(); self.rule_path.setPlaceholderText("Exact executable path"); browse=QPushButton("Browse…"); browse.clicked.connect(self.browse_priority_executable); add_selected=QPushButton("Use selected process"); add_selected.clicked.connect(self.use_selected_process_for_rule); pathrow.addWidget(self.rule_path,1); pathrow.addWidget(browse); pathrow.addWidget(add_selected); pathwrap=QWidget(); pathwrap.setLayout(pathrow)
        self.rule_priority=QComboBox(); self.rule_priority.addItems(["High","Medium","Low"]); self.rule_mode=QComboBox(); self.rule_mode.addItem("Apply once", "once"); self.rule_mode.addItem("Automatically on launch", "automatic"); form.addRow("Application",self.rule_name); form.addRow("Executable",pathwrap); form.addRow("Target priority",self.rule_priority); form.addRow("Rule type",self.rule_mode); p.addLayout(form)
        buttons=QHBoxLayout(); self.rule_save_btn=QPushButton("Save rule"); self.rule_save_btn.clicked.connect(self.save_priority_rule); self.rule_enable_btn=QPushButton("Enable / disable selected"); self.rule_enable_btn.clicked.connect(self.toggle_selected_rule); self.rule_delete_btn=QPushButton("Delete selected"); self.rule_delete_btn.clicked.connect(self.delete_priority_rule); self.rule_restore_btn=QPushButton("Restore prior priority"); self.rule_restore_btn.clicked.connect(self.restore_rule_priority); buttons.addWidget(self.rule_save_btn); buttons.addWidget(self.rule_enable_btn); buttons.addWidget(self.rule_delete_btn); buttons.addWidget(self.rule_restore_btn); p.addLayout(buttons); self.rule_status=QLabel("No saved rules."); self.rule_status.setObjectName("muted"); p.addWidget(self.rule_status); self.refresh_priority_rules(); v.addWidget(f,1)
        return w

    def optimization(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(3,5,10,12); v.setSpacing(12)
        self.add_page_heading(v,"Optimizations","Browse each control, inspect its current state and risk, then apply only what you select.")
        f,p=panel("Find a setting","Direct controls ask before changing Windows. Settings shortcuts open native Windows pages and are not marked as app-side changes.")
        row=QHBoxLayout(); self.optimization_search=QLineEdit(); self.optimization_search.setPlaceholderText("Search tweaks, categories, or explanations…"); self.optimization_search.setClearButtonEnabled(True); self.optimization_search.setAccessibleName("Search optimizations"); self.optimization_search.textChanged.connect(self.filter_optimizations)
        self.optimization_category=QComboBox(); self.optimization_category.addItems(["All categories",*sorted({x["category"] for x in OPTIMIZATION_CATALOG})]); self.optimization_category.setAccessibleName("Filter by category"); self.optimization_category.currentTextChanged.connect(self.filter_optimizations)
        self.optimization_risk=QComboBox(); self.optimization_risk.addItems(["Any risk","Low","Moderate","High"]); self.optimization_risk.setAccessibleName("Filter by risk"); self.optimization_risk.currentTextChanged.connect(self.filter_optimizations)
        self.optimization_status_filter=QComboBox(); self.optimization_status_filter.addItems(["Any state","Active / applied","Not active","No app-side state"]); self.optimization_status_filter.setAccessibleName("Filter by current state"); self.optimization_status_filter.currentTextChanged.connect(self.filter_optimizations)
        self.optimization_sort=QComboBox(); self.optimization_sort.addItem("Catalog order","default"); self.optimization_sort.addItem("Name A–Z","name"); self.optimization_sort.addItem("Category","category"); self.optimization_sort.addItem("Risk","risk"); self.optimization_sort.currentIndexChanged.connect(self.refresh_optimization_library); self.optimization_sort.setAccessibleName("Sort optimizations")
        for widget in (self.optimization_search,self.optimization_category,self.optimization_risk,self.optimization_status_filter,self.optimization_sort): row.addWidget(widget)
        p.addLayout(row)
        self.optimization_table=QTableWidget(0,7); self.optimization_table.setHorizontalHeaderLabels(["Category","Tweak","Type","Current state","Risk","Restart","Actions"])
        for col,mode in ((0,QHeaderView.ResizeMode.ResizeToContents),(1,QHeaderView.ResizeMode.Stretch),(2,QHeaderView.ResizeMode.ResizeToContents),(3,QHeaderView.ResizeMode.ResizeToContents),(4,QHeaderView.ResizeMode.ResizeToContents),(5,QHeaderView.ResizeMode.ResizeToContents),(6,QHeaderView.ResizeMode.ResizeToContents)): self.optimization_table.horizontalHeader().setSectionResizeMode(col,mode)
        self.optimization_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.optimization_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); self.optimization_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.optimization_table.setAlternatingRowColors(True); self.optimization_table.setShowGrid(False); self.optimization_table.verticalHeader().setVisible(False); p.addWidget(self.optimization_table,1); v.addWidget(f,1)
        f,p=panel("Selected tweak","Benefits, drawbacks, compatibility, restart and privilege requirements are shown here.")
        self.optimization_explanation=QLabel("Select a row to read its explanation and compatibility notes."); self.optimization_explanation.setObjectName("muted"); self.optimization_explanation.setWordWrap(True); p.addWidget(self.optimization_explanation); v.addWidget(f)
        row=QHBoxLayout(); self.optimization_apply_btn=QPushButton("Review selected…"); self.optimization_apply_btn.setObjectName("primary"); self.optimization_apply_btn.clicked.connect(self.apply_selected_optimization); self.optimization_restore_btn=QPushButton("Restore latest reversible change…"); self.optimization_restore_btn.setToolTip("Restores the latest transaction in the shared Undo queue; confirmation names the exact action."); self.optimization_restore_btn.clicked.connect(self.undo_last); self.optimization_refresh_btn=QPushButton("Refresh current state"); self.optimization_refresh_btn.clicked.connect(self.refresh_optimization_library); row.addWidget(self.optimization_apply_btn); row.addWidget(self.optimization_restore_btn); row.addWidget(self.optimization_refresh_btn); row.addStretch(); v.addLayout(row)
        self.optimization_table.itemSelectionChanged.connect(self.optimization_selected); self._optimization_restore_rows=[]; self.refresh_optimization_library(); return w

    def refresh_optimization_library(self):
        if not hasattr(self,"optimization_table"): return
        entries=list(OPTIMIZATION_CATALOG); sort=self.optimization_sort.currentData() if hasattr(self,"optimization_sort") else "default"
        risk_order={"Low":0,"Moderate":1,"High":2}
        if sort=="name": entries.sort(key=lambda item:item["name"].casefold())
        elif sort=="category": entries.sort(key=lambda item:(item["category"].casefold(),item["name"].casefold()))
        elif sort=="risk": entries.sort(key=lambda item:(risk_order.get(item["risk"],9),item["name"].casefold()))
        self._optimization_entries=entries; table=self.optimization_table; table.setRowCount(len(entries)); self._optimization_states={}; self._optimization_restore_rows=[]
        for r,entry in enumerate(entries):
            state,applied=self.optimization_state(entry); self._optimization_states[entry["key"]]=(state,applied)
            for c,value in enumerate((entry["category"],entry["name"],entry["kind"],state,entry["risk"],entry["restart"])):
                item=QTableWidgetItem(str(value)); item.setData(Qt.ItemDataRole.UserRole,entry["key"]); table.setItem(r,c,item)
            actions=QWidget(); action_row=QHBoxLayout(actions); action_row.setContentsMargins(3,2,3,2); action_row.setSpacing(5)
            apply_title="Configure" if entry.get("action")=="dns_manage" else "Apply"
            apply_button=QPushButton(apply_title); apply_button.setObjectName("rowApply"); apply_button.setToolTip("Open the exact adapter controls and review the proposed DNS change." if entry.get("action")=="dns_manage" else "Review this tweak, then confirm before it runs."); apply_button.clicked.connect(lambda checked=False,key=entry["key"]:self.apply_optimization_key(key))
            restore_button=QPushButton("Restore"); restore_button.setToolTip("Restore the most recent reversible transaction in the shared Undo queue; review its label in the confirmation."); restore_button.clicked.connect(lambda checked=False,key=entry["key"]:self.restore_optimization_key(key)); self._optimization_restore_rows.append(restore_button)
            action_row.addWidget(apply_button); action_row.addWidget(restore_button); table.setCellWidget(r,6,actions); table.setRowHeight(r,46)
        self.filter_optimizations(); self.refresh_undo()

    def apply_optimization_key(self,key):
        index=next((i for i,item in enumerate(self._optimization_entries) if item["key"]==key),-1)
        if index<0: return
        self.optimization_table.clearSelection(); self.optimization_table.selectRow(index); self.apply_selected_optimization()

    def restore_optimization_key(self,key):
        if not self.undo.items:
            QMessageBox.information(self,"Nothing to restore","No reversible change is currently queued."); return
        self.undo_last()

    def optimization_state(self,entry):
        key=entry.get("state"); applied=None
        if key=="game_mode":
            try: return game_mode_status()
            except Exception as e: return f"Unreadable: {e}",None
        if key=="capture":
            try: return capture_status()
            except Exception as e: return f"Unreadable: {e}",None
        if key=="mouse_accel":
            try:
                values=system_mouse_info(); active=any(values[:2]) and values[2]>0
                return (f"Thresholds {values[0]}, {values[1]} · level {values[2]} · "+("acceleration active" if active else "no acceleration")),not active
            except Exception as e: return f"Unreadable: {e}",None
        if key=="dns_manage":
            if not self._dns_adapters: return "Refresh Network for per-adapter state",None
            adapter=next((row for row in self._dns_adapters if row.get("is_default_route")),self._dns_adapters[0])
            families=adapter.get("families",{})
            return f"{adapter.get('alias')} · IPv4 {families.get('ipv4',{}).get('source','unknown')} · IPv6 {families.get('ipv6',{}).get('source','unknown')}",None
        if key=="ui_effects":
            try:
                enabled=system_ui_effects()
                return ("Enabled · shadows/fades/related effects" if enabled else "Disabled"),bool(enabled)
            except Exception as e: return f"Unreadable: {e}",None
        if key=="power":
            current,name=active_plan(); return (f"Active · {name}" if current else name),None
        if key=="priority": return ("Tracked process priority" if self._priority_applied else "Ready · select process in CPU Tweaks",bool(self._priority_applied))
        if key in ("automatic_priority","pause_priority","edit_priority_rules"):
            enabled=bool(self.settings.get("priority_rules_enabled",False)) and any(r.get("enabled",True) and r.get("mode")=="automatic" for r in self.priority_rules)
            return ("Watcher enabled" if enabled else "Paused / no enabled rules"),enabled
        if key in ("user_run_entries","machine_run_review","user_startup_folder","common_startup_folder","startup_enable_disable"):
            try: return f"{len(startup_entries())} readable Run entries · folders on request",None
            except Exception: return "State unavailable · refresh Startup",None
        labels={"windows_temp":"Preview first · admin needed to delete","recycle_bin":"Review count before emptying","user_temp":"Preview first · confirmation required","dns_flush":"Ready · one-time action","cpu_affinity_set":"Per-process · no global state"}
        if key in labels: return labels[key],None
        if entry["kind"]=="Settings shortcut": return "Managed by Windows · shortcut only",None
        if entry["kind"] in ("Local utility","Read-only tool","Read-only safeguard","Read-only advisor","Read-only guidance"): return "Available · open tool",None
        return "Not tracked by this app",None

    def filter_optimizations(self,*_):
        if not hasattr(self,"optimization_table"): return
        query=self.optimization_search.text().casefold().strip(); category=self.optimization_category.currentText(); risk=self.optimization_risk.currentText(); state_filter=self.optimization_status_filter.currentText()
        for row,entry in enumerate(getattr(self,"_optimization_entries",[])):
            text=" ".join(str(x) for x in entry.values()).casefold(); applied=self._optimization_states.get(entry["key"],("",None))[1]
            hidden=(category!="All categories" and entry["category"]!=category) or bool(query and query not in text) or (risk!="Any risk" and entry["risk"]!=risk)
            if state_filter=="Active / applied": hidden=hidden or applied is not True
            elif state_filter=="Not active": hidden=hidden or applied is not False
            elif state_filter=="No app-side state": hidden=hidden or applied is not None
            self.optimization_table.setRowHidden(row,bool(hidden))

    def optimization_selected(self):
        selected=self.optimization_table.selectionModel().selectedRows()
        if not selected: return
        entry=self._optimization_entries[selected[0].row()]
        self.optimization_explanation.setText(f"{entry['details']}\n\nType: {entry['kind']} · Risk: {entry['risk']} · Administrator: {entry['admin']} · Restart: {entry['restart']}")
        self.optimization_restore_btn.setEnabled(bool(self.undo.items))

    def apply_selected_optimization(self):
        selected=self.optimization_table.selectionModel().selectedRows()
        if not selected: QMessageBox.information(self,"Choose an optimization","Select an optimization from the library first."); return
        entries=[self._optimization_entries[item.row()] for item in selected]
        special=[item for item in entries if item.get("action") in ("dns_manage","mouse_accel")]
        if special:
            if len(entries)>1:
                QMessageBox.information(self,"Configure these controls separately","DNS provider/adapter choices and mouse preferences require their own exact state review. No selected actions were run; configure one of these controls at a time."); return
            if special[0]["action"]=="dns_manage":
                self.select_page(self.PAGE_NAMES.index("Network")); self.status.setText("Choose an adapter and DNS mode in Network. No DNS settings were changed."); return
            self.apply_mouse_acceleration(); return
        detail="\n\n".join(f"• {x['name']} — {x['kind']} · risk {x['risk']}\n{x['details']}\nAdministrator: {x['admin']} · Restart: {x['restart']}" for x in entries)
        if not self.ask("Review selected actions",detail+"\n\nDirect controls may change Windows or process settings after this confirmation. Settings shortcuts only open Windows; local utilities show their own preview and confirmation before changes."): return
        self._batch_running=True; results=[]
        try:
            for entry in entries:
                try: results.append(f"{entry['name']}: {self.dispatch_optimization(entry)}")
                except Exception as e: results.append(f"{entry['name']}: ERROR — {e}")
        finally: self._batch_running=False
        self.refresh_optimization_library(); self.refresh_undo(); self.refresh_home(); self.refresh_activity()
        QMessageBox.information(self,"Selection processed","\n".join(results)[:6000] or "No actions were processed.")

    def dispatch_optimization(self,entry):
        action=entry["action"]
        if action=="mode": self.apply_mode(); return "Game Mode action processed."
        if action=="capture": self.apply_capture(); return "GameDVR action processed."
        if action=="power": self.apply_plan(); return "Power-plan action processed."
        if action=="dns": self.flush_dns(); return "DNS cache action processed."
        if action=="ui_effects": self.apply_ui_effects_direct(); return "Windows UI-effects preference processed."
        if action=="mouse_accel": self.apply_mouse_acceleration(); return "Mouse acceleration control processed."
        if action=="dns_manage": self.select_page(self.PAGE_NAMES.index("Network")); return "Opened the DNS adapter controls in Network."
        if action=="undo": self.undo_last(); return "Undo control opened."
        if action=="shortcut": return "Opened Windows settings." if self.open_settings_uri(entry["target"],entry["name"]) else "Windows settings could not be opened."
        if action.startswith("browser_"):
            target={"browser_edge":"edge://settings/clearBrowserData","browser_chrome":"chrome://settings/clearBrowserData","browser_firefox":"about:preferences#privacy"}[action]; self.open_browser_cache(target); return "Browser page opened for manual review; no files deleted."
        if action=="gpu_settings": self.open_gpu_settings(); return "Opened Windows Graphics settings; no preference applied."
        if action=="compatibility": self.open_quick_tab("GPU Tweaks"); self.open_settings_uri("compatibility",entry["name"]); return "Opened Windows file properties if an executable is selected."
        page={"gaming":"Gaming","network":"Network","cleanup_user":"Cleanup","cleanup_windows":"Cleanup","recycle_bin":"Cleanup","large_files":"Cleanup","downloads":"Cleanup","advisor":"Home"}.get(action)
        quick={"priority":"CPU Tweaks","affinity":"CPU Tweaks","processes":"CPU Tweaks","startup":"Startup Tweaks","startup_folder":"Startup Tweaks","power":"Windows Tweaks"}.get(action)
        if action=="history": self.open_activity_history(); return "Opened Settings activity history."
        if quick: self.open_quick_tab(quick); return f"Opened Quick Tweaks · {quick}."
        if page: self.select_page(self.PAGE_NAMES.index(page)); return f"Opened {page}."
        return "No action is available for this entry."

    def startup_tweaks_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(2,6,10,8); v.setSpacing(12)
        self.add_page_heading(v,"Startup Tweaks","Review only the locations listed here. Startup impact is guidance based on entry type, not a measured boot-time score.")
        f,p=panel("Inspected locations","Registry: HKCU and HKLM Software\\Microsoft\\Windows\\CurrentVersion\\Run. Folders: current-user and all-users Start Menu\\Programs\\Startup. Scheduled tasks, services, and other autorun locations are not scanned.")
        self.startup_table=QTableWidget(0,5); self.startup_table.setHorizontalHeaderLabels(["Scope","Location","Name","Command / target","State"])
        self.startup_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents); self.startup_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents); self.startup_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents); self.startup_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch); self.startup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.startup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); p.addWidget(self.startup_table,1)
        row=QHBoxLayout(); self.startup_disable_btn=QPushButton("Disable selected user entry…"); self.startup_disable_btn.clicked.connect(self.disable_startup); self.startup_folder_btn=QPushButton("Open user Startup folder"); self.startup_folder_btn.clicked.connect(lambda:self.open_startup_folder(False)); all_folder=QPushButton("Open all-users Startup folder"); all_folder.clicked.connect(lambda:self.open_startup_folder(True)); row.addWidget(self.startup_disable_btn); row.addWidget(self.startup_folder_btn); row.addWidget(all_folder); row.addStretch(); p.addLayout(row); v.addWidget(f,1)
        f,p=panel("My approved startup profile","Select only applications you recognize. Saving this list does not change startup; Apply disables only these exact entries.")
        self.startup_profile_list=QListWidget(); self.startup_profile_list.setAccessibleName("Approved startup entries to disable"); p.addWidget(self.startup_profile_list)
        row=QHBoxLayout(); save_profile=QPushButton("Save approved selection"); save_profile.clicked.connect(self.save_startup_profile); self.startup_profile_apply_btn=QPushButton("Apply Startup Tweaks"); self.startup_profile_apply_btn.setObjectName("primary"); self.startup_profile_apply_btn.clicked.connect(self.apply_startup_profile); self.startup_profile_undo_btn=QPushButton("Undo Startup Tweaks"); self.startup_profile_undo_btn.clicked.connect(lambda:self.undo_named_category("Startup Tweaks")); row.addWidget(save_profile); row.addWidget(self.startup_profile_apply_btn); row.addWidget(self.startup_profile_undo_btn); row.addStretch(); p.addLayout(row); v.addWidget(f)
        f,p=panel("Impact guidance","Startup entries can delay sign-in and add background work, but impact is not measured by Kam3 Tweaks. Security and Windows-owned entries are excluded. All-users entries are read-only."); v.addWidget(f)
        return w

    @staticmethod
    def _startup_protected_label(name,value):
        text=(str(name)+" "+str(value)).casefold()
        return any(token in text for token in ("defender","antivirus","anti-virus","securityhealth","windows security","driver","realtek","nvidia","amd software"))

    def refresh_startup_profile_list(self):
        if not hasattr(self,"startup_profile_list"): return
        candidates=[]
        for scope,key,name,value,kind,can_change in startup_entries():
            if scope=="Current user" and can_change and not self._startup_protected_label(name,value):
                candidates.append({"kind":"registry","id":"run:"+name,"key":key,"name":name,"value":encode(value),"type":kind})
        for scope,folder,name,target,path,suffix,can_change in startup_folder_entries():
            if scope=="Current user" and can_change and not self._startup_protected_label(name,target):
                try: digest=file_sha256(path)
                except OSError: continue
                candidates.append({"kind":"shortcut","id":"shortcut:"+str(path),"path":str(path),"sha256":digest,"name":name})
        self.startup_profile_list.clear()
        selected={item.get("id") for item in self.startup_profile if isinstance(item,dict)}
        for candidate in candidates:
            row=QListWidgetItem(candidate["name"]+" · "+("Current-user Run" if candidate["kind"]=="registry" else "Startup shortcut"))
            row.setFlags(row.flags()|Qt.ItemFlag.ItemIsUserCheckable); row.setCheckState(Qt.CheckState.Checked if candidate["id"] in selected else Qt.CheckState.Unchecked); row.setData(Qt.ItemDataRole.UserRole,candidate); self.startup_profile_list.addItem(row)
        self.startup_profile_apply_btn.setEnabled(bool(self.startup_profile))

    def save_startup_profile(self):
        chosen=[]
        for index in range(self.startup_profile_list.count()):
            item=self.startup_profile_list.item(index)
            if item.checkState()==Qt.CheckState.Checked: chosen.append(item.data(Qt.ItemDataRole.UserRole))
        try:
            startup_profile_file().parent.mkdir(parents=True,exist_ok=True)
            tmp=startup_profile_file().with_suffix(".tmp"); tmp.write_text(json.dumps(chosen,indent=2),encoding="utf-8"); tmp.replace(startup_profile_file())
            self.startup_profile=validate_startup_profile(chosen); self.startup_profile_apply_btn.setEnabled(bool(self.startup_profile))
            QMessageBox.information(self,"Startup profile saved",f"Saved {len(chosen)} explicitly approved startup item(s). No startup entries were changed.")
        except OSError as exc: QMessageBox.warning(self,"Could not save startup profile",str(exc))

    def apply_startup_profile(self):
        if not self.startup_profile:
            self.open_quick_tab("Startup Tweaks")
            QMessageBox.information(self,"Set up Startup Tweaks","Review the current-user entries, check only applications you recognize, then choose Save approved selection."); return
        if not WIN: QMessageBox.information(self,"Startup Tweaks","Startup changes are available on Windows only."); return
        self.startup_profile=validate_startup_profile(self.startup_profile)
        lines=[item["name"] for item in self.startup_profile]
        if not lines: QMessageBox.information(self,"Startup Tweaks","The saved profile is empty."); return
        if not self.ask("Apply Startup Tweaks?","Disable only these previously approved current-user entries? Security-related entries and Windows-owned locations are never changed.\n\n"+"\n".join("• "+name for name in lines)): return
        def run():
            done=[]; failed=[]
            for saved in self.startup_profile:
                try:
                    if saved.get("kind")=="registry":
                        if saved.get("key")!=r"Software\Microsoft\Windows\CurrentVersion\Run" or self._startup_protected_label(saved.get("name",""),decode(saved.get("value"))): raise RuntimeError("Saved entry is outside the allowed current-user startup set or is protected.")
                        exists,value,kind=reg_read(saved["key"],saved["name"])
                        if not exists: continue
                        if value!=decode(saved["value"]) or kind!=saved["type"]: raise RuntimeError("Entry changed since profile was saved; refresh and review it.")
                        remove_registry_value(self.undo,saved["key"],saved["name"])
                        if reg_read(saved["key"],saved["name"])[0]: raise RuntimeError("Registry removal verification failed.")
                    elif saved.get("kind")=="shortcut":
                        path=Path(saved["path"])
                        if not path.exists(): continue
                        disable_startup_shortcut(path,self.undo)
                        if path.exists(): raise RuntimeError("Shortcut move verification failed.")
                    else: raise RuntimeError("Unknown saved startup item type.")
                    done.append(saved.get("name","Startup item"))
                except Exception as exc: failed.append(f"{saved.get('name','Startup item')}: {exc}")
            result=[f"{len(done)} startup item(s) disabled and verified."]
            result.extend("Disabled: "+name for name in done); result.extend("\nFailed: "+message for message in failed)
            return "\n".join(result)
        self.finish_change("Startup Tweaks",run)

    def gpu_tweaks_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(2,6,10,8); v.setSpacing(12)
        self.add_page_heading(v,"GPU Tweaks","Hardware identification is read on demand. Display configuration itself remains under Windows control.")
        f,p=panel("Detected hardware","No continuous sensor polling is used. GPU name and driver are shown only when the installed NVIDIA utility exposes them.")
        self.hardware_text=QLabel("Select Refresh to read hardware details."); self.hardware_text.setWordWrap(True); self.hardware_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); p.addWidget(self.hardware_text)
        refresh=QPushButton("Refresh compatibility details"); refresh.clicked.connect(self.refresh_hardware_summary); p.addWidget(refresh,alignment=Qt.AlignmentFlag.AlignLeft); v.addWidget(f)
        f,p=panel("Graphics preferences","Per-app graphics preference is controlled in Windows. Kam3 Tweaks opens the documented settings page and does not write GPU preference registry values.")
        row=QHBoxLayout(); self.gpu_app_path=QLineEdit(); self.gpu_app_path.setPlaceholderText("Optional game or application .exe path"); self.gpu_app_path.setAccessibleName("Executable for Windows graphics preferences"); browse=QPushButton("Browse…"); browse.clicked.connect(self.browse_gpu_app); row.addWidget(self.gpu_app_path,1); row.addWidget(browse); p.addLayout(row)
        btn=QPushButton("Open Windows Graphics settings"); btn.clicked.connect(self.open_gpu_settings); p.addWidget(btn,alignment=Qt.AlignmentFlag.AlignLeft); v.addWidget(f)
        f,p=panel("Display settings shortcuts","These buttons open Windows pages. Selecting a value there applies it through Windows and cannot be undone from Kam3 Tweaks.")
        self.add_shortcut_rows(p,[
            ("Display resolution and scale","ms-settings:display","Display"),
            ("Refresh rate and advanced display","ms-settings:display-advanced","Advanced display"),
            ("HDR and Auto HDR","ms-settings:display","Display"),
            ("Variable refresh rate and windowed game options","ms-settings:display-advancedgraphics","Graphics settings"),
            ("Hardware-accelerated GPU scheduling","ms-settings:display-advancedgraphics-default","Default graphics settings"),
            ("Per-app graphics preference","ms-settings:display-advancedgraphics","Graphics settings"),
            ("Graphics driver and adapter properties","devmgmt.msc","Device Manager"),
            ("Fullscreen and compatibility properties","compatibility","Application properties")])
        v.addWidget(f); v.addStretch(); return w

    def network_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(2,6,10,8); v.setSpacing(12)
        self.add_page_heading(v,"Network","Adapter details are read on request. DNS changes are opt-in, family-scoped, verified, and reversible when Windows reports an exact prior state.")
        f,p=panel("Network adapters","Read-only adapter names, link state, addresses, and DNS servers. This page does not run ping tests or poll throughput.")
        self.adapter_text=QLabel("Select Refresh to inspect available adapters."); self.adapter_text.setObjectName("muted"); self.adapter_text.setWordWrap(True); self.adapter_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); p.addWidget(self.adapter_text)
        row=QHBoxLayout(); refresh=QPushButton("Refresh adapter and DNS details"); refresh.clicked.connect(self.refresh_network_details); self.adapter_refresh_btn=refresh; row.addWidget(refresh); self.dns_btn=QPushButton("Flush DNS cache…"); self.dns_btn.clicked.connect(self.flush_dns); row.addWidget(self.dns_btn); row.addStretch(); p.addLayout(row); v.addWidget(f)
        f,p=panel("DNS configuration","Choose the exact adapter and a provider or custom addresses. Applying may briefly disconnect the adapter; DNS changes do not guarantee lower ping. Apply requires an administrator session. Kam3 Tweaks never auto-elevates.")
        row=QHBoxLayout(); row.addWidget(QLabel("Adapter")); self.dns_adapter_combo=QComboBox(); self.dns_adapter_combo.setAccessibleName("Network adapter for DNS configuration"); self.dns_adapter_combo.currentIndexChanged.connect(self.update_dns_controls); row.addWidget(self.dns_adapter_combo,1)
        row.addWidget(QLabel("DNS")); self.dns_mode_combo=QComboBox(); self.dns_mode_combo.addItem("Automatic (DHCP)","dhcp"); self.dns_mode_combo.addItem("Cloudflare","cloudflare"); self.dns_mode_combo.addItem("Google","google"); self.dns_mode_combo.addItem("Quad9","quad9"); self.dns_mode_combo.addItem("Custom addresses","custom"); self.dns_mode_combo.setAccessibleName("DNS provider or automatic mode"); self.dns_mode_combo.currentIndexChanged.connect(self.update_dns_controls); row.addWidget(self.dns_mode_combo); p.addLayout(row)
        self.dns_custom_input=QLineEdit(); self.dns_custom_input.setPlaceholderText("Custom IP addresses, separated by commas or spaces"); self.dns_custom_input.setAccessibleName("Custom DNS server IP addresses"); self.dns_custom_input.textChanged.connect(self.update_dns_controls); p.addWidget(self.dns_custom_input)
        self.dns_state_label=QLabel("Select Refresh to read each adapter's current IPv4 and IPv6 DNS mode and server addresses."); self.dns_state_label.setObjectName("muted"); self.dns_state_label.setWordWrap(True); p.addWidget(self.dns_state_label)
        row=QHBoxLayout(); self.dns_apply_config_btn=QPushButton("Review and apply DNS…"); self.dns_apply_config_btn.setObjectName("primary"); self.dns_apply_config_btn.clicked.connect(self.apply_dns_configuration); row.addWidget(self.dns_apply_config_btn); self.dns_undo_config_btn=QPushButton("Undo DNS configuration"); self.dns_undo_config_btn.clicked.connect(lambda:self.undo_named_category("DNS configuration")); row.addWidget(self.dns_undo_config_btn); row.addStretch(); p.addLayout(row); v.addWidget(f)
        f,p=panel("Windows network controls","Settings shortcuts do not make changes. Network reset may remove adapters and saved configuration; review the Windows confirmation carefully.")
        self.add_shortcut_rows(p,[
            ("Adapter properties and advanced network settings","ms-settings:network-advancedsettings","Advanced network settings"),
            ("Adapter power management","devmgmt.msc","Device Manager"),
            ("Network reset","ms-settings:network-reset","Network reset")])
        v.addWidget(f); v.addStretch(); return w

    def add_shortcut_rows(self,layout,items):
        for title,target,destination in items:
            row=QWidget(); h=QHBoxLayout(row); h.setContentsMargins(0,2,0,2); label=QLabel(title); label.setWordWrap(True); h.addWidget(label,1)
            button=QPushButton("Open Windows" if str(target).startswith("ms-settings:") or target=="devmgmt.msc" else "Open")
            button.setAccessibleName(f"{button.text()}: {title}"); button.setToolTip(f"Opens {destination}. Kam3 Tweaks does not change the setting.")
            button.clicked.connect(lambda checked=False,t=target,d=destination:self.open_settings_uri(t,d))
            h.addWidget(button); layout.addWidget(row)

    def open_settings_uri(self,target,destination="Windows settings"):
        if not WIN or not hasattr(os,"startfile"):
            QMessageBox.warning(self,"Windows-only control",f"{destination} is available through Windows only."); return False
        if target=="compatibility":
            path=Path(self.gpu_app_path.text().strip()) if hasattr(self,"gpu_app_path") else Path()
            if not path.is_file():
                QMessageBox.information(self,"Choose an application","Select an existing executable first. Compatibility properties are opened for that file; Kam3 Tweaks does not edit game files."); return False
            try: os.startfile(str(path),"properties")
            except OSError as e: QMessageBox.warning(self,"Could not open file properties",str(e)); return False
            return True
        try:
            os.startfile(target)
            self.status.setText(f"Opened {destination}. Make and review any changes in Windows.")
            write_activity("Settings shortcut",f"Opened {destination}","success",target)
            return True
        except OSError as e:
            QMessageBox.warning(self,"Could not open settings",f"Windows could not open {destination}. The page may not exist on this Windows version.\n\n{e}")
            write_activity("Settings shortcut",str(e),"error",target); return False

    def browse_gpu_app(self):
        path,_=QFileDialog.getOpenFileName(self,"Choose game or application","","Windows applications (*.exe)")
        if path: self.gpu_app_path.setText(str(Path(path).resolve()))

    def open_gpu_settings(self):
        path=self.gpu_app_path.text().strip()
        opened=self.open_settings_uri("ms-settings:display-advancedgraphics","Windows Graphics settings")
        if opened and path:
            QMessageBox.information(self,"Choose the application in Windows",f"Windows Graphics settings opened. Add this executable there if it is not listed, then choose its graphics preference:\n\n{path}\n\nKam3 Tweaks did not apply a GPU preference.")

    def refresh_hardware_summary(self):
        if not hasattr(self,"hardware_text"): return
        try:
            memory=psutil.virtual_memory(); self.gpu_name,_,_=gpu()
            driver=_GPU_DETAILS.get("driver") or "Unavailable via nvidia-smi"
            lines=[f"Windows: {platform.platform()}",f"Processor: {processor_name()} · {psutil.cpu_count(logical=False) or '?'} physical / {psutil.cpu_count() or '?'} logical cores",f"Memory: {memory.total/(1024**3):.1f} GB installed · {memory.available/(1024**3):.1f} GB currently available",f"NVIDIA GPU: {self.gpu_name or 'Not exposed by nvidia-smi; check Windows Device Manager for other vendors'}",f"NVIDIA driver: {driver}","No clock, voltage, temperature, or utilization polling is performed."]
            self.hardware_text.setText("\n".join(lines))
        except Exception as e: self.hardware_text.setText(f"Compatibility details unavailable: {e}")

    def refresh_network_details(self):
        if not hasattr(self,"adapter_text"): return
        if getattr(self,"_network_query_thread",None) is not None and self._network_query_thread.isRunning(): return
        if not WIN:
            self._render_network_details({"ok":True,"interfaces":psutil.net_if_addrs(),"stats":psutil.net_if_stats(),"adapters":[],"detail_error":"Windows adapter metadata is unavailable outside Windows."})
            return
        self.adapter_text.setText("Reading adapter state, route, negotiated link speed, and DNS…")
        if hasattr(self,"adapter_refresh_btn"): self.adapter_refresh_btn.setEnabled(False)
        thread=QThread(self); worker=NetworkDetailsWorker(); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.completed.connect(self._render_network_details)
        worker.completed.connect(thread.quit); worker.completed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: setattr(self,"_network_query_thread",None))
        self._network_query_thread=thread; self._network_query_worker=worker; thread.start()

    def _render_network_details(self,result):
        if hasattr(self,"adapter_refresh_btn"): self.adapter_refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self.adapter_text.setText("Adapter information unavailable: "+str(result.get("error","unknown error"))); return
        self._dns_adapters=list(result.get("dns_configs",[]))
        self._dns_query_error=str(result.get("dns_config_error", ""))
        lines=[]; adapters={item["name"].casefold():item for item in result.get("adapters",[]) if isinstance(item,dict) and item.get("name")}
        addresses=result.get("interfaces",{}); stats=result.get("stats",{})
        for name,items in sorted(addresses.items(),key=lambda item:item[0].casefold()):
            state=stats.get(name); status="Up" if state and state.isup else "Down / unavailable"
            vals=[]
            for item in items:
                value=str(item.address).split("%",1)[0]
                try: ipaddress.ip_address(value); vals.append(item.address)
                except ValueError: pass
            detail=adapters.get(name.casefold()); parts=[f"{name} · {status}"]
            if detail:
                if detail.get("has_default_route") is True: parts.append("active IPv4 default-route adapter")
                speed=detail.get("link_speed")
                if speed and speed.casefold() not in ("unavailable","unknown"): parts.append("reported link speed "+speed)
            if vals: parts.append("IP "+", ".join(vals))
            else: parts.append("no IP address reported")
            if detail and detail.get("dns_servers"): parts.append("DNS "+", ".join(detail["dns_servers"]))
            lines.append(" · ".join(parts))
        if not lines: lines.append("No network adapters were returned by the local system API.")
        if result.get("detail_error"):
            lines.extend(["", str(result["detail_error"]),"Adapter status, IP addresses, and reported link speed come from the local system API."])
        self.adapter_text.setText("\n".join(lines))
        self.update_dns_adapter_list()
        if hasattr(self,"optimization_table"):
            self.refresh_optimization_library()

    @staticmethod
    def _dns_config_description(config):
        source=config.get("source")
        mode="Automatic (DHCP)" if source=="dhcp" else "Manual" if source=="static" else "Unknown"
        servers=config.get("servers",[])
        address_text=", ".join(servers) if servers else ("addresses supplied by DHCP" if source=="dhcp" else "no static server reported")
        return f"{mode} · {address_text}"

    def update_dns_adapter_list(self):
        if not hasattr(self,"dns_adapter_combo"): return
        previous=self.dns_adapter_combo.currentData()
        self.dns_adapter_combo.blockSignals(True); self.dns_adapter_combo.clear()
        for item in self._dns_adapters:
            marker=" · active route" if item.get("is_default_route") else ""
            self.dns_adapter_combo.addItem(f"{item.get('alias','Adapter')} · index {item.get('interface_index')}{marker}",item.get("interface_index"))
        row=next((i for i,item in enumerate(self._dns_adapters) if item.get("interface_index")==previous),0)
        if self._dns_adapters: self.dns_adapter_combo.setCurrentIndex(row)
        self.dns_adapter_combo.blockSignals(False)
        self.update_dns_controls()

    def update_dns_controls(self,*_):
        if not hasattr(self,"dns_adapter_combo"): return
        custom=self.dns_mode_combo.currentData()=="custom"
        self.dns_custom_input.setVisible(custom)
        index=self.dns_adapter_combo.currentData()
        snapshot=next((item for item in self._dns_adapters if item.get("interface_index")==index),None)
        if snapshot:
            fam=snapshot.get("families",{})
            lines=[f"IPv4: {self._dns_config_description(fam.get('ipv4',{}))}",f"IPv6: {self._dns_config_description(fam.get('ipv6',{}))}"]
            if snapshot.get("is_default_route"): lines.append("This adapter carries the active IPv4 default route.")
            if not snapshot.get("supported"): lines.append("One or more address-family states are not fully supported: "+(snapshot.get("reason") or "unknown source or registration mode"))
            status="\n".join(lines)
        else:
            status="No adapter has a fully readable DNS configuration yet. Select Refresh adapter and DNS details."
        if self._dns_query_error: status+="\nRead warning: "+self._dns_query_error
        is_admin=bool(WIN and admin())
        if WIN and not is_admin: status+="\nApplying DNS requires Kam3 Tweaks to be started in an administrator session. It will not elevate itself."
        eligible=False
        if snapshot and is_admin and WIN:
            mode=self.dns_mode_combo.currentData()
            try:
                if mode=="dhcp": target=make_dns_target(snapshot,"dhcp")
                elif mode=="custom": target=make_dns_target(snapshot,"static",self.dns_custom_input.text())
                else:
                    addresses={"cloudflare":["1.1.1.1","1.0.0.1","2606:4700:4700::1111","2606:4700:4700::1001"],
                               "google":["8.8.8.8","8.8.4.4","2001:4860:4860::8888","2001:4860:4860::8844"],
                               "quad9":["9.9.9.9","149.112.112.112","2620:fe::fe","2620:fe::9"]}[mode]
                    target=make_dns_target(snapshot,"static",addresses)
                eligible=bool(target) and all(snapshot.get("families",{}).get({4:"ipv4",6:"ipv6"}[version],{}).get("supported") for version in target)
            except (DnsConfigurationError,KeyError,TypeError): eligible=False
        self.dns_state_label.setText(status)
        self.dns_apply_config_btn.setEnabled(bool(eligible and not self._operation_busy))
        if not snapshot: self.dns_apply_config_btn.setToolTip("Refresh adapter DNS details before applying.")
        elif not is_admin: self.dns_apply_config_btn.setToolTip("Administrator permission is required. No automatic elevation is used.")
        elif not eligible: self.dns_apply_config_btn.setToolTip("This mode is disabled because one or more affected address families cannot be restored exactly, or the custom address is invalid.")
        else: self.dns_apply_config_btn.setToolTip("Review exact current and proposed DNS settings. No changes occur until you confirm.")
        has_undo=any(item.get("label")=="DNS configuration" for item in self.undo.items)
        self.dns_undo_config_btn.setEnabled(bool(has_undo and not self._operation_busy))

    def apply_dns_configuration(self):
        if self._operation_busy: return
        if not WIN:
            QMessageBox.information(self,"DNS configuration","DNS controls are available on Windows only."); return
        if not admin():
            QMessageBox.warning(self,"Administrator required","Windows requires an administrator session to change adapter DNS. Close Kam3 Tweaks and start it manually with Run as administrator. Kam3 Tweaks will not elevate itself; no settings were changed."); return
        index=self.dns_adapter_combo.currentData()
        snapshot=next((item for item in self._dns_adapters if item.get("interface_index")==index),None)
        if not snapshot:
            QMessageBox.information(self,"Adapter details unavailable","Refresh adapter and DNS details before applying."); return
        mode=self.dns_mode_combo.currentData()
        try:
            if mode=="dhcp": target=make_dns_target(snapshot,"dhcp")
            elif mode=="custom": target=make_dns_target(snapshot,"static",self.dns_custom_input.text())
            else:
                addresses={"cloudflare":["1.1.1.1","1.0.0.1","2606:4700:4700::1111","2606:4700:4700::1001"],
                           "google":["8.8.8.8","8.8.4.4","2001:4860:4860::8888","2001:4860:4860::8844"],
                           "quad9":["9.9.9.9","149.112.112.112","2620:fe::fe","2620:fe::9"]}[mode]
                target=make_dns_target(snapshot,"static",addresses)
        except (DnsConfigurationError,KeyError,TypeError) as exc:
            QMessageBox.warning(self,"DNS configuration unavailable",str(exc)); return
        changes=[]
        for version,new in target.items():
            family="ipv4" if version==4 else "ipv6"; old=snapshot.get("families",{}).get(family,{})
            if not old.get("supported"):
                QMessageBox.warning(self,"Exact restore is unavailable",f"Kam3 Tweaks cannot fully read the original {family.upper()} DNS mode and addresses for this adapter. Apply is disabled to avoid a change that could not be safely undone.\n\n{old.get('reason') or snapshot.get('reason')}"); return
            if not dns_config_matches(old,new): changes.append((version,old,new))
        if not changes:
            QMessageBox.information(self,"DNS already configured","The selected adapter already matches this DNS mode. No change was made."); return
        family_names={4:"IPv4",6:"IPv6"}
        details=[f"Adapter: {snapshot['alias']} (index {snapshot['interface_index']})"]
        for version,old,new in changes:
            details.extend([f"{family_names[version]} now: {self._dns_config_description(old)}",f"{family_names[version]} proposed: {self._dns_config_description(new)}"])
        details.append("This may briefly interrupt network connectivity. DNS changes do not guarantee lower ping. Kam3 Tweaks saves the exact prior per-family state, verifies each result, and will refuse Undo if a newer configuration is detected.")
        if not self.ask("Review DNS configuration", "\n\n".join(details)): return
        def run():
            fresh_rows,query_error=query_dns_adapters()
            fresh=next((item for item in fresh_rows if item.get("interface_index")==snapshot["interface_index"] and str(item.get("alias","")).casefold()==snapshot["alias"].casefold()),None)
            if not fresh: raise RuntimeError("The selected network adapter changed or disappeared after review. No DNS commands were run. "+(query_error or ""))
            for version,old,new in changes:
                family="ipv4" if version==4 else "ipv6"
                now=fresh.get("families",{}).get(family,{})
                if not now.get("supported") or not dns_config_matches(now,old):
                    raise RuntimeError(f"The {family.upper()} DNS configuration changed after review or is no longer readable. No DNS commands were run.")
            for version,old,new in changes:
                self.undo.record({"type":"dns_family","interface_index":snapshot["interface_index"],"alias":snapshot["alias"],"family":version,
                                  "old":{k:old[k] for k in ("source","servers","register")},"expected":new,
                                  "expected_variants":possible_write_results(new)})
            succeeded=[]; failed=[]
            for version,old,new in changes:
                family="ipv4" if version==4 else "ipv6"
                try:
                    set_dns_family(snapshot["interface_index"],snapshot["alias"],version,new)
                    verified_rows,verify_error=query_dns_adapters()
                    verified=next((item for item in verified_rows if item.get("interface_index")==snapshot["interface_index"] and str(item.get("alias","")).casefold()==snapshot["alias"].casefold()),None)
                    if not verified or not dns_config_matches(verified.get("families",{}).get(family,{}),new):
                        raise RuntimeError("Windows did not report the requested mode and server addresses after the write. "+(verify_error or ""))
                    succeeded.append(family_names[version]+" verified")
                except Exception as exc: failed.append(f"{family_names[version]}: {exc}")
            result=[f"{len(succeeded)} address family change(s) verified."]
            result.extend("Applied: "+item for item in succeeded)
            if failed: result.append("Failed:"); result.extend(failed)
            if failed and self.undo.items: result.append("Undo is available; it will restore only recorded states and reject external conflicts.")
            return "\n".join(result)
        self.finish_change("DNS configuration",run)
        self.refresh_network_details()

    def refresh_windows_status(self):
        if not hasattr(self,"windows_effect_status"): return
        if not WIN:
            self.windows_effect_status.setText("Windows animation and UI-effects controls are unavailable on this platform."); return
        entries=(("Menu animations",system_menu_animation),("Minimize/restore animations",system_minimize_animation),("System UI effects",system_ui_effects))
        lines=[]
        for title,reader in entries:
            try: lines.append(f"{title}: {'Enabled' if reader() else 'Disabled'}")
            except Exception as exc: lines.append(f"{title}: unavailable · {exc}")
        try:
            values=system_mouse_info(); active=any(values[:2]) and values[2]>0
            lines.append(f"Pointer acceleration: {'Active' if active else 'Disabled'} · thresholds {values[0]}, {values[1]} · level {values[2]}")
        except Exception as exc: lines.append(f"Pointer acceleration: unavailable · {exc}")
        self.windows_effect_status.setText("\n".join(lines)+"\nUI-effects control is system-wide and may change shadows, fades, and visual feedback. Pointer acceleration is a separate opt-in control; neither setting promises FPS gains.")

    def open_downloads(self):
        folder=Path.home()/"Downloads"
        try:
            if not folder.is_dir(): raise FileNotFoundError(f"Downloads folder does not exist: {folder}")
            if hasattr(os,"startfile"): os.startfile(str(folder)); self.status.setText("Opened Downloads for manual review; no files were changed.")
            else: raise OSError("File Explorer is available on Windows only.")
        except OSError as e: QMessageBox.warning(self,"Could not open Downloads",str(e))

    def open_browser_cache(self,target):
        if not hasattr(os,"startfile"):
            QMessageBox.information(self,"Browser settings",f"Open your browser and navigate to {target}."); return
        host=target.split(":",1)[0].casefold(); browser={"edge":"msedge.exe","chrome":"chrome.exe","about":"firefox.exe"}.get(host)
        if not browser: QMessageBox.warning(self,"Unsupported browser page","This browser cleanup page is not on the supported allowlist."); return
        candidates=[]; local=Path(os.environ.get("LOCALAPPDATA") or Path.home()/"AppData/Local"); pf=Path(os.environ.get("ProgramFiles") or r"C:\Program Files"); pf86=Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")
        if browser=="msedge.exe": candidates=[pf86/"Microsoft/Edge/Application/msedge.exe",pf/"Microsoft/Edge/Application/msedge.exe",local/"Microsoft/Edge/Application/msedge.exe"]
        elif browser=="chrome.exe": candidates=[pf/"Google/Chrome/Application/chrome.exe",pf86/"Google/Chrome/Application/chrome.exe",local/"Google/Chrome/Application/chrome.exe"]
        else: candidates=[pf/"Mozilla Firefox/firefox.exe",pf86/"Mozilla Firefox/firefox.exe",local/"Mozilla Firefox/firefox.exe"]
        exe=next((candidate for candidate in candidates if candidate.is_file()),None)
        if exe is None:
            QMessageBox.information(self,"Browser not found",f"Kam3 Tweaks did not find {browser}. Install it from its publisher or use the browser's own menu. No cache files were changed."); return
        try:
            subprocess.Popen([str(exe),target],shell=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); self.status.setText("Opened browser cleanup settings. Review items in the browser; Kam3 Tweaks does not delete browser data.")
        except OSError as e: QMessageBox.warning(self,"Could not open browser settings",str(e))

    def open_startup_folder(self,all_users=False):
        if all_users:
            raw=os.environ.get("PROGRAMDATA")
            folder=Path(raw or r"C:\ProgramData")/"Microsoft/Windows/Start Menu/Programs/Startup"
        else:
            raw=os.environ.get("APPDATA")
            folder=Path(raw or Path.home()/"AppData/Roaming")/"Microsoft/Windows/Start Menu/Programs/Startup"
        try:
            if not folder.is_dir(): raise FileNotFoundError(f"Startup folder is not available: {folder}")
            os.startfile(str(folder))
        except OSError as e: QMessageBox.warning(self,"Could not open Startup folder",str(e))

    def refresh_home(self):
        if not hasattr(self,"home_active"): return
        rows=[]; recs=[]
        if WIN:
            try:
                mode,_=game_mode_status()
                rows.append(("Game Mode",mode))
                if mode!="On": recs.append(("Game Mode",mode,"Review the Windows Game Mode preference. Its effect varies by title; no FPS gain is assumed."))
            except Exception as e: rows.append(("Game Mode",f"Unavailable · {e}"))
            try:
                capture,_=capture_status()
                rows.append(("GameDVR capture",capture))
                recs.append(("GameDVR",capture,"If you rely on background clips, leave capture enabled. Otherwise review capture options in Gaming."))
            except Exception as e: rows.append(("GameDVR capture",f"Unavailable · {e}"))
            current,power=active_plan(); rows.append(("Power plan",power if current else "Unavailable"))
            if current and "high performance" in power.casefold(): recs.append(("Power use",power,"High performance can increase energy use, fan noise, and heat; choose a plan for your usage."))
            try: rows.append(("Windows UI effects","Enabled" if system_ui_effects() else "Disabled"))
            except Exception: rows.append(("Windows UI effects","Unavailable"))
        else: rows.extend((("Game Mode","Windows only"),("GameDVR capture","Windows only"),("Power plan","Windows only")))
        auto=bool(self.settings.get("priority_rules_enabled",False)) and any(r.get("enabled",True) and r.get("mode")=="automatic" for r in self.priority_rules)
        rows.append(("Automatic priority rules","Enabled" if auto else "Paused / none"))
        if not auto: recs.append(("Priority rules","Paused","Optional automatic rules are exact-path matched and run only while Kam3 Tweaks is open."))
        self.home_active.setRowCount(len(rows))
        for r,(key,value) in enumerate(rows):
            self.home_active.setItem(r,0,QTableWidgetItem(key)); self.home_active.setItem(r,1,QTableWidgetItem(value))
        try:
            memory=psutil.virtual_memory(); self.gpu_name,_,_=gpu()
            gpu_label=self.gpu_name or "Unavailable via nvidia-smi"
            self.advisor_summary.setText(f"{platform.platform()} · {processor_name()} · {psutil.cpu_count(logical=False) or '?'} physical cores · {memory.total/(1024**3):.1f} GB RAM · GPU: {gpu_label}. Hardware compatibility is read on demand, not continuously monitored.")
        except Exception as e: self.advisor_summary.setText(f"Compatibility data is partly unavailable: {e}")
        recs.extend([("Graphics settings","Check Windows availability","HAGS, VRR, Auto HDR, and per-app graphics options depend on your Windows build, GPU driver, and display. Review them under Quick Tweaks → GPU Tweaks."),("Windows visual effects","Optional","Review transparency, animations, and background-app settings in Windows. Trade-offs are subjective; no FPS claim is made.")])
        self.advisor_table.setRowCount(min(6,len(recs)))
        for r,(name,state,text) in enumerate(recs[:6]):
            for c,val in enumerate((name,state,text)): self.advisor_table.setItem(r,c,QTableWidgetItem(str(val)))
        recent=[]
        try:
            for line in activity_file().read_text(encoding="utf-8").splitlines()[-3:]:
                try: item=json.loads(line); recent.append(f"{item.get('timestamp','')}  ·  {item.get('action','')}: {item.get('result','')}")
                except ValueError: pass
        except OSError: pass
        self.home_recent.setText("\n".join(reversed(recent)) if recent else "No recent changes recorded.")
        pending=bool(self.undo.items)
        if hasattr(self,"home_undo_metric"): self.home_undo_metric.setText("Ready" if pending else "Clear")
        if hasattr(self,"home_restore_label"): self.home_restore_label.setText(f"Latest change: {self.undo.label}. Undo will check the exact saved prior state." if pending else "No reversible action is queued.")
        if hasattr(self,"home_restore_btn"): self.home_restore_btn.setEnabled(pending)
        if hasattr(self,"home_rules_metric"):
            enabled_rules=sum(1 for rule in self.priority_rules if rule.get("enabled",True) and rule.get("mode")=="automatic")
            self.home_rules_metric.setText(str(enabled_rules) if self.settings.get("priority_rules_enabled",False) else "Paused")
        if hasattr(self,"home_games_metric"): self.home_games_metric.setText(str(len(self.games)))
        self.refresh_quick_category_cards()

    def windows_tweaks_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(2,6,10,8); v.setSpacing(12)
        self.add_page_heading(v,"Windows Tweaks","Direct controls are confirmed and reversible where Windows exposes a readable prior state. Other items open Windows Settings.")
        f,p=panel("Windows visual effects","Current values are read from the documented Windows API. Disabling UI effects changes shadows, fades and related visual feedback; no FPS improvement is assumed. No administrator access or restart is normally required.")
        self.windows_effect_status=QLabel("Select Refresh to read current Windows preferences."); self.windows_effect_status.setObjectName("muted"); self.windows_effect_status.setWordWrap(True); p.addWidget(self.windows_effect_status)
        row=QHBoxLayout(); self.windows_effect_refresh_btn=QPushButton("Refresh Windows preference status"); self.windows_effect_refresh_btn.clicked.connect(self.refresh_windows_status); row.addWidget(self.windows_effect_refresh_btn)
        self.mouse_accel_btn=QPushButton("Disable pointer acceleration…"); self.mouse_accel_btn.clicked.connect(self.apply_mouse_acceleration); row.addWidget(self.mouse_accel_btn); row.addStretch(); p.addLayout(row); v.addWidget(f)
        f,p=panel("Power plan","Kam3 Tweaks reads the active GUID and installed plans, then uses powercfg to switch plans. Undo uses the exact previous GUID.")
        row=QHBoxLayout(); self.plan=QComboBox(); self.plan.setMinimumWidth(280); self.plan.setAccessibleName("Available Windows power plans"); self.plan_btn=QPushButton("Apply selected plan…"); self.plan_btn.setObjectName("primary"); self.plan_btn.clicked.connect(self.apply_plan); row.addWidget(self.plan,1); row.addWidget(self.plan_btn); p.addLayout(row); self.plan_current=QLabel("Current plan: reading Windows state…"); self.plan_current.setObjectName("muted"); p.addWidget(self.plan_current); v.addWidget(f)
        f,p=panel("Windows preferences","These are Windows Settings shortcuts. Kam3 Tweaks does not silently toggle broad OS preferences or claim they improve FPS.")
        self.add_shortcut_rows(p,[
            ("Transparency effects","ms-settings:personalization-colors","Personalization colors"),
            ("Animation and visual effects","ms-settings:easeofaccess-visualeffects","Visual effects"),
            ("Background app permissions","ms-settings:privacy-backgroundapps","Background app permissions"),
            ("Notifications","ms-settings:privacy-notifications","Notifications"),
            ("Storage Sense","ms-settings:storagepolicies","Storage Sense"),
            ("Startup applications","ms-settings:startupapps","Startup apps"),
            ("Power and battery","ms-settings:powersleep","Power and battery")])
        v.addWidget(f); v.addStretch(); return w

    def cleanup_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(2,6,10,8); v.setSpacing(12)
        self.add_page_heading(v,"Cleanup","Review targets before deleting. User TEMP cleanup is preview-based and irreversible; other utilities open Windows or browser cleanup settings.")
        f,p=panel("User temporary files","Only files in the current user's TEMP directory are listed and eligible. Links, directories, changed files, locked files, and inaccessible files are skipped.")
        self.clean_btn=QPushButton("Preview user TEMP files…"); self.clean_btn.setObjectName("primary"); self.clean_btn.clicked.connect(self.cleanup); p.addWidget(self.clean_btn,alignment=Qt.AlignmentFlag.AlignLeft); v.addWidget(f)
        f,p=panel("Review storage","Large-file scans are read-only and limited to user-selected locations. Downloads opens the folder for manual review.")
        row=QHBoxLayout(); self.storage_btn=QPushButton("Find large files…"); self.storage_btn.clicked.connect(self.scan_storage); downloads=QPushButton("Review Downloads"); downloads.clicked.connect(self.open_downloads); storage=QPushButton("Open Storage settings"); storage.clicked.connect(lambda:self.open_settings_uri("ms-settings:storagesense","Storage settings")); row.addWidget(self.storage_btn); row.addWidget(downloads); row.addWidget(storage); row.addStretch(); p.addLayout(row)
        self.storage_status=QLabel("Large-file scan has not run."); self.storage_status.setObjectName("muted"); self.storage_status.setWordWrap(True); p.addWidget(self.storage_status); v.addWidget(f)
        self.storage_table=QTableWidget(0,3); self.storage_table.setHorizontalHeaderLabels(["Size","File","Folder"]); self.storage_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents); self.storage_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents); self.storage_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch); self.storage_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.storage_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.storage_table.cellDoubleClicked.connect(lambda *_:self.storage_open_selected()); v.addWidget(self.storage_table)
        open_folder=QPushButton("Open selected file's folder"); open_folder.clicked.connect(self.storage_open_selected); v.addWidget(open_folder,alignment=Qt.AlignmentFlag.AlignLeft)
        f,p=panel("Windows TEMP and Recycle Bin","System-wide cleanup needs administrator rights and explicit confirmation. Recycle Bin emptying cannot be undone. These actions are disabled on unsupported systems.")
        row=QHBoxLayout(); self.windows_temp_btn=QPushButton("Preview Windows TEMP…"); self.windows_temp_btn.clicked.connect(self.cleanup_windows_temp); self.recycle_btn=QPushButton("Review / empty Recycle Bin…"); self.recycle_btn.clicked.connect(self.cleanup_recycle_bin); row.addWidget(self.windows_temp_btn); row.addWidget(self.recycle_btn); row.addStretch(); p.addLayout(row); v.addWidget(f)
        f,p=panel("Browser cache","Opening browser privacy settings leaves file selection and deletion under your browser's control.")
        row=QHBoxLayout()
        for label,uri in (("Edge","edge://settings/clearBrowserData"),("Chrome","chrome://settings/clearBrowserData"),("Firefox","about:preferences#privacy")):
            b=QPushButton(label+" cleanup settings"); b.clicked.connect(lambda checked=False,u=uri:self.open_browser_cache(u)); row.addWidget(b)
        row.addStretch(); p.addLayout(row); v.addWidget(f); v.addStretch(); return w








    def backup_settings(self):
        path,_=QFileDialog.getSaveFileName(self,"Export Kam3 Tweaks settings",str(Path.home()/"Kam3Tweaks-settings.json"),"JSON files (*.json)")
        if not path: return
        destination=Path(path)
        if destination.exists() and not self.ask("Replace backup file?",f"Overwrite this existing file?\n\n{destination}"): return
        payload={"format":LOCAL_BACKUP_FORMAT,"settings":{"welcome_seen":bool(self.settings.get("welcome_seen",False)),"priority_rules_enabled":False,"theme":self.settings.get("theme","Violet Aurora"),"auto_check_updates":bool(self.settings.get("auto_check_updates",True)),"auto_download_updates":bool(self.settings.get("auto_download_updates",False)),"auto_install_updates":False},"profiles":self.profiles,"games":self.games,"priority_rules":self.priority_rules,"startup_profile":self.startup_profile,"custom_profiles":self.custom_profiles}
        try:
            # Validate the exact payload before writing a user-selected file.
            validate_local_backup(payload); atomic_write_json(destination,payload)
            QMessageBox.information(self,"Backup complete",f"Exported game profiles, {len(self.custom_profiles)} custom profile(s), {len(self.games)} saved game path(s), {len(self.priority_rules)} priority rule(s), and {len(self.startup_profile)} approved startup item(s). The automatic watcher preference is not exported as enabled.")
        except (OSError,ValueError,TypeError) as e: QMessageBox.warning(self,"Backup failed",str(e))

    def restore_settings(self):
        path,_=QFileDialog.getOpenFileName(self,"Restore Kam3 Tweaks settings",str(Path.home()),"JSON files (*.json)")
        if not path: return
        try:
            backup=json.loads(Path(path).read_text(encoding="utf-8")); incoming=validate_local_backup(backup)
        except (OSError,ValueError,TypeError,AttributeError) as e: QMessageBox.warning(self,"Restore failed",str(e)); return
        summary=[f"{len(incoming['profiles'])} game profiles"]
        if incoming["games"] is not None: summary.append(f"{len(incoming['games'])} saved game paths")
        if incoming["priority_rules"] is not None: summary.append(f"{len(incoming['priority_rules'])} priority rules")
        if incoming["startup_profile"] is not None: summary.append(f"{len(incoming['startup_profile'])} approved startup items")
        if incoming["custom_profiles"] is not None: summary.append(f"{len(incoming['custom_profiles'])} custom profiles")
        if not self.ask("Restore local data?","Replace the selected local profiles, game paths, and priority rules?\n\n"+"\n".join(summary)+"\n\nNo Windows settings will be changed. Automatic priority rules will remain paused until you enable them manually."): return
        new_settings=dict(self.settings); new_settings.update(incoming["settings"]); new_settings["priority_rules_enabled"]=False
        new_profiles=incoming["profiles"]
        new_games=self.games if incoming["games"] is None else incoming["games"]
        new_rules=self.priority_rules if incoming["priority_rules"] is None else incoming["priority_rules"]
        try:
            # Each file is atomically replaced. Existing source data is retained
            # until the user explicitly approves this restore operation.
            atomic_write_json(settings_file(),new_settings)
            atomic_write_json(APP_DATA/"profiles.json",new_profiles)
            if incoming["games"] is not None: atomic_write_json(game_paths_file(),new_games)
            if incoming["priority_rules"] is not None: atomic_write_json(APP_DATA/"priority_rules.json",new_rules)
            if incoming["startup_profile"] is not None: atomic_write_json(startup_profile_file(),incoming["startup_profile"])
            if incoming["custom_profiles"] is not None: atomic_write_json(custom_profiles_file(),incoming["custom_profiles"])
        except OSError as e:
            QMessageBox.warning(self,"Restore incomplete",f"Some local files may already have been restored, but no Windows settings were changed. Review the files in %APPDATA%\\Kam3 Tweaks.\n\n{e}"); return
        self.settings=new_settings; self.profiles=new_profiles; self.games=new_games; self.priority_rules=new_rules; self._priority_applied.clear()
        if hasattr(self,"update_auto_check"):
            self.update_auto_check.blockSignals(True); self.update_auto_check.setChecked(bool(self.settings.get("auto_check_updates",True))); self.update_auto_check.blockSignals(False)
            self.update_auto_download.blockSignals(True); self.update_auto_download.setChecked(bool(self.settings.get("auto_download_updates",False))); self.update_auto_download.blockSignals(False)
        if incoming["startup_profile"] is not None: self.startup_profile=incoming["startup_profile"]
        if incoming["custom_profiles"] is not None: self.custom_profiles=incoming["custom_profiles"]
        self.apply_theme(self.settings.get("theme","Violet Aurora"),persist=False)
        if hasattr(self,"priority_timer"): self.priority_timer.stop()
        if hasattr(self,"priority_master"):
            self.priority_master.blockSignals(True); self.priority_master.setChecked(False); self.priority_master.blockSignals(False)
        self.refresh_games(); self.load_profile_editor(); self.refresh_priority_rules(); self.refresh_startup(); self.refresh_custom_profiles(); self.refresh_undo(); self.refresh_home(); self.refresh_activity()
        QMessageBox.information(self,"Restore complete","Local data restored. Windows settings were not changed. Automatic priority rules remain paused; enable them manually from Quick Tweaks → CPU Tweaks when ready.")

    def export_system_report(self):
        path,_=QFileDialog.getSaveFileName(self,"Export system report",str(Path.home()/"Kam3Tweaks-system-report.json"),"JSON files (*.json)")
        if not path: return
        try:
            mem=psutil.virtual_memory(); gpu_name,_,_=gpu(); current,power=active_plan() if WIN else (None,"Unavailable outside Windows")
            try:
                mode_exists,mode_value,_=reg_read(GAMEBAR,"AutoGameModeEnabled") if WIN else (False,None,None)
                game_mode=("On" if mode_value==1 else "Off") if mode_exists else "Not configured"
                capture_values=[reg_read(k,n) for k,n in ((CAPTURE,"AppCaptureEnabled"),(GAMECONFIG,"GameDVR_Enabled"))] if WIN else []
                capture_set=[v for exists,v,_ in capture_values if exists]
                capture=("On" if any(v==1 for v in capture_set) else "Off") if capture_set else ("Not configured" if WIN else "Unavailable outside Windows")
            except (OSError,RuntimeError) as e: game_mode=capture=f"Unavailable: {e}"
            report={"generated_at":datetime.datetime.now().astimezone().isoformat(timespec="seconds"),"application":{"name":APP_NAME,"version":APP_VERSION},"operating_system":{"name":platform.system(),"release":platform.release(),"version":platform.version(),"architecture":platform.machine()},"hardware":{"processor":processor_name(),"physical_cores":psutil.cpu_count(logical=False),"logical_cores":psutil.cpu_count(),"memory_total_bytes":mem.total,"gpu_name":gpu_name,"gpu_telemetry":"not polled by Kam3 Tweaks 4.2"},"windows_preferences":{"game_mode":game_mode,"background_capture":capture,"active_power_plan":power if current else "Unavailable"},"monitoring":{"history":"Not collected in 4.2; hardware compatibility data is read on demand."},"privacy":{"excluded":["user name","home folder path","process list","game executable paths","device serial numbers"]}}
            atomic_write_json(Path(path),report); QMessageBox.information(self,"Report exported","System report exported. It contains Windows version and general hardware details, but no username, home path, process list, executable paths, or serial numbers.")
        except (OSError,psutil.Error,RuntimeError) as e: QMessageBox.warning(self,"Report export failed",str(e))

    def show_safety_notes(self):
        QMessageBox.information(self,"Safety and limitations","Kam3 Tweaks does not promise FPS gains. Direct controls require confirmation and save exact prior values for Undo where supported. Windows Settings shortcuts only open the relevant page; make and review changes there. Some controls require administrator rights and may be denied by policy. The app never self-elevates, changes clocks or voltages, modifies security software, edits game files, or interacts with anti-cheat software.")

    def show_welcome(self):
        QMessageBox.information(self,"Welcome to Kam3 Tweaks","Kam3 Tweaks helps review and configure selected Windows settings. Direct changes require confirmation; Windows Settings shortcuts do not apply changes themselves. Review the explanation and Undo availability before each action. No FPS improvement is promised.")
        self.settings["welcome_seen"]=True; self.save_settings_file()



    def save_settings_file(self):
        try:
            APP_DATA.mkdir(parents=True,exist_ok=True); temp=settings_file().with_suffix(".tmp"); temp.write_text(json.dumps(self.settings,indent=2),encoding="utf-8"); temp.replace(settings_file()); return True
        except OSError as e: self.status.setText(f"Could not save preferences: {e}"); return False





    def settings_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(3,5,10,12); v.setSpacing(13)
        self.add_page_heading(v,"Settings","Shape the app, manage local data, and review what Kam3 Tweaks has changed.")
        f,p=panel("Appearance","Choose an accent palette. Your theme is saved locally and does not change Windows personalization.")
        row=QHBoxLayout(); theme_note=QLabel("Interface theme"); theme_note.setObjectName("sectionTitle"); row.addWidget(theme_note); row.addStretch()
        self.theme_combo=QComboBox(); self.theme_combo.setObjectName("themeSelector"); self.theme_combo.addItems(list(THEME_PALETTES)); self.theme_combo.setCurrentText(self.current_theme); self.theme_combo.setAccessibleName("Application theme"); self.theme_combo.currentTextChanged.connect(self.on_theme_changed); row.addWidget(self.theme_combo); p.addLayout(row)
        swatches=QHBoxLayout()
        for theme_name,palette in THEME_PALETTES.items():
            swatch=QFrame(); swatch.setFixedSize(34,8); swatch.setStyleSheet(f"background:{palette['accent']};border:1px solid {palette['border']};border-radius:4px;")
            label=QLabel(theme_name); label.setObjectName("muted"); swatches.addWidget(swatch); swatches.addWidget(label); swatches.addSpacing(10)
        swatches.addStretch(); p.addLayout(swatches)
        self.theme_description=QLabel("Violet Aurora is the default. Palette changes apply immediately."); self.theme_description.setObjectName("muted"); p.addWidget(self.theme_description); v.addWidget(f)

        f,p=panel("Updates","Stable releases are checked over HTTPS. Downloads are accepted only after signed metadata and the executable hash verify. Installation is handled by the separate adjacent updater helper.")
        self.update_status=QLabel(f"Installed version: {APP_VERSION} · Latest stable release has not been checked."); self.update_status.setObjectName("muted"); self.update_status.setWordWrap(True); p.addWidget(self.update_status)
        self.update_last_check=QLabel("Last successful check: "+str(self.settings.get("last_update_check_iso","Never"))); self.update_last_check.setObjectName("muted"); p.addWidget(self.update_last_check)
        self.update_notes=QLabel("Release notes will appear here after a successful check."); self.update_notes.setObjectName("muted"); self.update_notes.setWordWrap(True); self.update_notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); p.addWidget(self.update_notes)
        self.update_progress=QProgressBar(); self.update_progress.setObjectName("updateProgress"); self.update_progress.setRange(0,1000); self.update_progress.setValue(0); self.update_progress.setVisible(False); p.addWidget(self.update_progress)
        update_row=QHBoxLayout(); self.update_check_btn=QPushButton("Check for Updates"); self.update_check_btn.clicked.connect(self.check_for_updates); self.update_open_btn=QPushButton("View Releases"); self.update_open_btn.clicked.connect(self.open_update_page); self.update_now_btn=QPushButton("Update Now"); self.update_now_btn.setObjectName("primary"); self.update_now_btn.clicked.connect(self.start_update_download); self.update_now_btn.setEnabled(False); self.update_later_btn=QPushButton("Remind Me Later"); self.update_later_btn.clicked.connect(self.defer_update); self.update_later_btn.setEnabled(False); self.update_view_changes_btn=QPushButton("View Changes"); self.update_view_changes_btn.clicked.connect(self.show_release_notes); self.update_view_changes_btn.setEnabled(False); update_row.addWidget(self.update_check_btn); update_row.addWidget(self.update_now_btn); update_row.addWidget(self.update_later_btn); update_row.addWidget(self.update_view_changes_btn); update_row.addWidget(self.update_open_btn); update_row.addStretch(); p.addLayout(update_row)
        self.update_cancel_btn=QPushButton("Cancel Download"); self.update_cancel_btn.clicked.connect(self.cancel_update_download); self.update_cancel_btn.setVisible(False); p.addWidget(self.update_cancel_btn,alignment=Qt.AlignmentFlag.AlignLeft)
        self.update_install_btn=QPushButton("Install & Restart"); self.update_install_btn.setObjectName("primary"); self.update_install_btn.clicked.connect(self.install_verified_update); self.update_install_btn.setEnabled(False); p.addWidget(self.update_install_btn,alignment=Qt.AlignmentFlag.AlignLeft)
        self.update_retry_btn=QPushButton("Retry Download"); self.update_retry_btn.clicked.connect(self.start_update_download); self.update_retry_btn.setVisible(False); p.addWidget(self.update_retry_btn,alignment=Qt.AlignmentFlag.AlignLeft)
        self.update_source=QLabel(f"Release page: {RELEASES_URL}"); self.update_source.setObjectName("muted"); self.update_source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); p.addWidget(self.update_source)
        self.update_key_note=QLabel("Secure installation is not yet enabled in this build because no publisher verification key has been pinned. Use View Releases for the initial manual upgrade."); self.update_key_note.setObjectName("muted"); self.update_key_note.setWordWrap(True); self.update_key_note.setVisible(not verification_ready()); p.addWidget(self.update_key_note)
        self.update_auto_check=QCheckBox("Automatically check for stable updates at startup"); self.update_auto_check.setChecked(bool(self.settings.get("auto_check_updates",True))); self.update_auto_check.toggled.connect(lambda value:self.set_update_preference("auto_check_updates",value)); p.addWidget(self.update_auto_check)
        self.update_auto_download=QCheckBox("Automatically download verified updates (never install automatically)"); self.update_auto_download.setChecked(bool(self.settings.get("auto_download_updates",False))); self.update_auto_download.toggled.connect(lambda value:self.set_update_preference("auto_download_updates",value)); p.addWidget(self.update_auto_download)
        self.update_auto_install=QCheckBox("Automatically install verified updates"); self.update_auto_install.setChecked(False); self.update_auto_install.setEnabled(False); self.update_auto_install.setToolTip("Unavailable: this release always requires a separate Install & Restart confirmation."); self.update_auto_install.setAccessibleDescription("Unavailable; installation always requires a separate confirmation."); p.addWidget(self.update_auto_install)
        self.update_preferences_note=QLabel("Automatic installation is unavailable. Kam3 Tweaks will never close or replace itself without your explicit Install & Restart confirmation."); self.update_preferences_note.setObjectName("muted"); self.update_preferences_note.setWordWrap(True); p.addWidget(self.update_preferences_note)
        self.update_history_toggle=QCheckBox("Show update history"); self.update_history_toggle.setChecked(False); p.addWidget(self.update_history_toggle)
        self.update_history_label=QLabel("No update operations recorded."); self.update_history_label.setObjectName("muted"); self.update_history_label.setWordWrap(True); self.update_history_label.setVisible(False); self.update_history_toggle.toggled.connect(self.update_history_label.setVisible); p.addWidget(self.update_history_label)
        self.update_recovery_status=QLabel(self._update_recovery_summary()); self.update_recovery_status.setObjectName("muted"); self.update_recovery_status.setWordWrap(True); p.addWidget(self.update_recovery_status)
        self.update_recover_btn=QPushButton("Restore Previous Version…"); self.update_recover_btn.clicked.connect(self.recover_previous_version); self.update_recover_btn.setEnabled((APP_DATA/"update"/"install_journal.json").is_file()); p.addWidget(self.update_recover_btn,alignment=Qt.AlignmentFlag.AlignLeft)
        v.addWidget(f)

        f,p=panel("Start with Windows","Off by default. Enabling adds one current-user Run value after confirmation. It never requests elevation.")
        self.autostart=QCheckBox("Start Kam3 Tweaks when I sign in"); self.autostart.setToolTip("Adds or removes a current-user Windows Run value after confirmation."); self.autostart.setChecked(self.autostart_enabled()); self.autostart.stateChanged.connect(self.toggle_autostart); p.addWidget(self.autostart); v.addWidget(f)
        f,p=panel("Priority automation","Automatic rules use exact executable paths and run only while this app is open. No service or scheduled task is installed.")
        self.settings_priority_summary=QLabel("Priority rules are managed in Quick Tweaks → CPU Tweaks."); self.settings_priority_summary.setObjectName("muted"); self.settings_priority_summary.setWordWrap(True); p.addWidget(self.settings_priority_summary)
        open_cpu=QPushButton("Open CPU Tweaks"); open_cpu.clicked.connect(lambda:self.open_quick_tab("CPU Tweaks")); p.addWidget(open_cpu,alignment=Qt.AlignmentFlag.AlignLeft); v.addWidget(f)
        f,p=panel("Backup and restore","Export or restore Kam3 Tweaks data. Local restore never applies Windows settings and keeps automatic priority rules paused.")
        row=QHBoxLayout(); backup=QPushButton("Export settings backup…"); backup.clicked.connect(self.backup_settings); restore=QPushButton("Restore settings backup…"); restore.clicked.connect(self.restore_settings); report=QPushButton("Export system report…"); report.clicked.connect(self.export_system_report); safety=QPushButton("Safety and limitations"); safety.clicked.connect(self.show_safety_notes); row.addWidget(backup); row.addWidget(restore); row.addWidget(report); row.addWidget(safety); row.addStretch(); p.addLayout(row); v.addWidget(f)
        history_toggle=QCheckBox("Activity History"); history_toggle.setObjectName("historyToggle"); history_toggle.setAccessibleName("Expand Activity History"); history_toggle.setChecked(False); history_toggle.setToolTip("Expand the locally stored action history."); v.addWidget(history_toggle)
        self.activity_panel=QWidget(); history_layout=QVBoxLayout(self.activity_panel); history_layout.setContentsMargins(0,2,0,4)
        f,p=panel("Recent activity",r"The local action log is stored in %APPDATA%\Kam3 Tweaks\activity.jsonl. Export a copy to a location you choose.")
        row=QHBoxLayout(); refresh=QPushButton("Refresh history"); refresh.clicked.connect(self.refresh_activity); export=QPushButton("Export CSV…"); export.clicked.connect(self.export_activity); row.addWidget(refresh); row.addWidget(export); row.addStretch(); p.addLayout(row)
        self.activity_table=QTableWidget(0,4); self.activity_table.setHorizontalHeaderLabels(["Timestamp","Action","Result","Details"])
        for col,mode in ((0,QHeaderView.ResizeMode.ResizeToContents),(1,QHeaderView.ResizeMode.ResizeToContents),(2,QHeaderView.ResizeMode.ResizeToContents),(3,QHeaderView.ResizeMode.Stretch)): self.activity_table.horizontalHeader().setSectionResizeMode(col,mode)
        self.activity_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.activity_table.setMinimumHeight(220); self.activity_table.setAlternatingRowColors(True); p.addWidget(self.activity_table); history_layout.addWidget(f); self.activity_panel.setVisible(False); v.addWidget(self.activity_panel)
        self.activity_history_toggle=history_toggle; history_toggle.toggled.connect(self.activity_panel.setVisible); history_toggle.toggled.connect(lambda visible:self.refresh_activity() if visible else None)

        f,p=panel("About Kam3 Tweaks","A local Windows utility for reviewable settings. It does not promise FPS gains, modify security software, change clocks or voltages, or edit game files.")
        about=QLabel(f"Kam3 Tweaks {APP_VERSION}  ·  Windows 10/11  ·  PySide6"); about.setObjectName("sectionTitle"); p.addWidget(about)
        self.add_shortcut_rows(p,[("Windows version and device details","ms-settings:about","About your PC")]); v.addWidget(f)
        v.addStretch(); return w

    def check_for_updates(self):
        if self._download_thread and self._download_thread.isRunning():
            self.update_status.setText("An update operation is already running."); return
        if self._update_thread and self._update_thread.isRunning(): return
        now=time.time()
        try: last=float(self.settings.get("last_update_check_epoch",0) or 0)
        except (TypeError,ValueError): last=0
        if now-last<60:
            self.update_status.setText("Please wait before checking again. GitHub requests are rate limited."); return
        self.settings["last_update_check_epoch"]=now; self.save_settings_file()
        self.update_check_btn.setEnabled(False); self.update_status.setText("Checking GitHub for the latest stable release…")
        self._update_thread=QThread(self); self._update_worker=UpdateCheckWorker(); self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.completed.connect(self.on_update_check_complete)
        self._update_worker.completed.connect(self._update_thread.quit,Qt.ConnectionType.DirectConnection)
        self._update_thread.finished.connect(self._update_worker.deleteLater)
        self._update_thread.finished.connect(self.clear_update_worker)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.start()

    def clear_update_worker(self):
        self._update_worker=None; self._update_thread=None

    def on_update_check_complete(self,result):
        self.update_check_btn.setEnabled(True)
        if not result.get("ok"):
            cached=self._load_cached_release()
            last=self.settings.get("last_update_check_iso")
            suffix=f" Last successful check: {last}." if last else ""
            self.update_status.setText("Unable to check for updates. Your installed version will continue working."+suffix)
            self.update_notes.setText(str(result.get("error","Unknown error"))+"\n\nYou can retry later or view the GitHub releases page.")
            if cached: self.update_notes.setText(self.update_notes.text()+f"\n\nCached release details for reference: {cached.get('tag','unknown')}. This cache is not treated as a current update check.")
            self.update_now_btn.setEnabled(False); self.update_later_btn.setEnabled(False); self.update_view_changes_btn.setEnabled(False)
            return
        release=result["release"]; self.latest_release=release; self._latest_release_url=release["url"]
        comparison=compare_release(APP_VERSION,release)
        latest=release["tag"]
        if comparison>0: status=f"Update Available · {latest} (installed: {APP_VERSION})"
        elif comparison==0: status=f"Up to date · installed {APP_VERSION}; latest stable is {latest}."
        else: status=f"Installed version {APP_VERSION} is newer than GitHub's latest stable release {latest}."
        asset_size=next((a.get("size") for a in release.get("assets",[]) if a.get("name")=="Kam3Tweaks.exe"),None)
        if comparison>0 and isinstance(asset_size,int): status+=f" · Download size: {asset_size/1024/1024:.1f} MB"
        self.update_status.setText(status)
        self.update_notes.setText(release["notes"].strip() or "No release notes were provided.")
        self.update_source.setText("Release page: "+self._latest_release_url)
        self.settings["last_update_check_iso"]=datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        self.update_last_check.setText("Last successful check: "+self.settings["last_update_check_iso"])
        try: atomic_write_json(APP_DATA/"update"/"latest_release.json",{"checked_at":self.settings["last_update_check_iso"],"release":release})
        except OSError: pass
        self.save_settings_file()
        self.update_view_changes_btn.setEnabled(True)
        self.update_later_btn.setEnabled(comparison>0)
        secure_ready=verification_ready() and self._update_assets_complete(release)
        self.update_now_btn.setEnabled(comparison>0 and secure_ready and not self._download_thread)
        if comparison>0 and not verification_ready():
            self.update_key_note.setText("This release has no publisher verification key pinned in the application. Secure installation is disabled. Use View Releases for a manual update; do not run an unverified file.")
            self.update_key_note.setVisible(True)
        elif comparison>0 and not self._update_assets_complete(release):
            self.update_key_note.setText("This GitHub release does not contain the required signed update assets. Automatic installation is unavailable; use View Releases.")
            self.update_key_note.setVisible(True)
        if comparison>0:
            self._record_update_history("detected",latest,"Stable release metadata checked; no file was downloaded.")
            if self.settings.get("auto_download_updates",False) and secure_ready:
                self.start_update_download()
            elif self.isVisible():
                QTimer.singleShot(0,self.show_update_notification)
        self.refresh_update_history()

    @staticmethod
    def _update_assets_complete(release):
        names={item.get("name") for item in release.get("assets",[]) if isinstance(item,dict)}
        return {"Kam3Tweaks.exe",EXPECTED_UPDATER,"update-manifest.json","update-manifest.sig"}.issubset(names)

    def _load_cached_release(self):
        try:
            payload=json.loads((APP_DATA/"update"/"latest_release.json").read_text(encoding="utf-8"))
            release=payload.get("release")
            return release if isinstance(release,dict) else None
        except (OSError,ValueError): return None

    def set_update_preference(self,key,value):
        if key not in ("auto_check_updates","auto_download_updates"): return
        self.settings[key]=bool(value)
        if not self.save_settings_file(): self.update_status.setText("The preference changed for this session but could not be saved.")

    def defer_update(self):
        if not self.latest_release: return
        self.settings["update_deferred_version"]=self.latest_release.get("tag","")
        self.settings["update_deferred_until"]=time.time()+7*86400
        self.save_settings_file(); self.update_status.setText(f"Reminder postponed for {self.latest_release.get('tag')} for seven days.")
        self._record_update_history("later",self.latest_release.get("tag",""),"User selected Remind Me Later.")

    def show_release_notes(self):
        notes=self.latest_release.get("notes","") if self.latest_release else self.update_notes.text()
        QMessageBox.information(self,"Release changes",notes.strip() or "No release notes were provided.")

    def show_update_notification(self):
        release=self.latest_release
        if not release or compare_release(APP_VERSION,release)<=0 or self._update_prompt is not None: return
        tag=release.get("tag","")
        try: deferred=(self.settings.get("update_deferred_version")==tag and float(self.settings.get("update_deferred_until",0))>time.time())
        except (TypeError,ValueError): deferred=False
        if deferred or self.settings.get("update_prompted_version")==tag: return
        box=QMessageBox(self); box.setWindowTitle("Kam3 Tweaks update available")
        size=next((a.get("size") for a in release.get("assets",[]) if a.get("name")=="Kam3Tweaks.exe"),None)
        size_line=f"\nDownload size: {size/1024/1024:.1f} MB" if isinstance(size,int) else ""
        box.setText(f"Kam3 Tweaks {tag} is available.\nInstalled: {APP_VERSION}\nAvailable: {tag}{size_line}")
        box.setInformativeText("What's New\n"+(release.get("notes","").strip() or "No release notes were provided."))
        update=box.addButton("Update Now",QMessageBox.ButtonRole.AcceptRole)
        update.setEnabled(verification_ready() and self._update_assets_complete(release))
        later=box.addButton("Remind Me Later",QMessageBox.ButtonRole.DestructiveRole)
        changes=box.addButton("View Changes",QMessageBox.ButtonRole.ActionRole)
        box.setDefaultButton(later); self._update_prompt=box; box.exec(); clicked=box.clickedButton(); self._update_prompt=None
        if clicked is update:
            self.settings["update_prompted_version"]=tag; self.save_settings_file(); self.start_update_download()
        elif clicked is later: self.defer_update()
        else:
            self.settings["update_prompted_version"]=tag; self.save_settings_file()
            if clicked is changes: self.show_release_notes()

    def _record_update_history(self,action,version,details=""):
        try:
            path=APP_DATA/"update"/"history.jsonl"; path.parent.mkdir(parents=True,exist_ok=True)
            row={"timestamp":datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                 "action":str(action),"version":str(version),"details":str(details)[:500]}
            with path.open("a",encoding="utf-8") as stream: stream.write(json.dumps(row,ensure_ascii=False)+"\n")
        except OSError: pass

    def refresh_update_history(self):
        if not hasattr(self,"update_history_label"): return
        try:
            rows=[]
            for line in (APP_DATA/"update"/"history.jsonl").read_text(encoding="utf-8").splitlines()[-10:]:
                try:
                    row=json.loads(line); rows.append(f"{row.get('timestamp','')} · {row.get('action','')} · {row.get('version','')}: {row.get('details','')}")
                except ValueError: continue
            self.update_history_label.setText("\n".join(rows) if rows else "No update operations recorded.")
        except OSError: self.update_history_label.setText("No update operations recorded.")

    def start_update_download(self):
        if self._update_thread and self._update_thread.isRunning():
            self.update_status.setText("Wait for the release check to finish before downloading."); return
        if self._download_thread and self._download_thread.isRunning(): return
        if not self.latest_release or compare_release(APP_VERSION,self.latest_release)<=0: return
        if not verification_ready():
            self.update_status.setText("Secure installation is unavailable because this build has no pinned publisher verification key. Use View Releases for a manual update.")
            return
        if not self._update_assets_complete(self.latest_release):
            self.update_status.setText("The release is missing signed update assets. Use View Releases for a manual update."); return
        self._verified_update=None; self.update_progress.setVisible(True); self.update_progress.setRange(0,1000); self.update_progress.setValue(0)
        self.update_cancel_btn.setVisible(True)
        self.update_status.setText(f"Downloading and verifying Kam3 Tweaks {self.latest_release['tag']}…")
        self.update_now_btn.setEnabled(False); self.update_install_btn.setEnabled(False); self.update_retry_btn.setVisible(False)
        self._download_thread=QThread(self); self._download_worker=UpdateDownloadWorker(self.latest_release,APP_DATA/"update-staging",APP_VERSION)
        self._download_worker.moveToThread(self._download_thread)
        self._download_thread.started.connect(self._download_worker.run)
        self._download_worker.progress.connect(self.on_update_download_progress)
        self._download_worker.completed.connect(self.on_update_download_complete)
        self._download_worker.completed.connect(self._download_thread.quit,Qt.ConnectionType.DirectConnection)
        self._download_thread.finished.connect(self._download_worker.deleteLater)
        self._download_thread.finished.connect(self.clear_download_worker)
        self._download_thread.finished.connect(self._download_thread.deleteLater)
        self._download_thread.start()

    def on_update_download_progress(self,done,total):
        if total>0:
            self.update_progress.setRange(0,1000); self.update_progress.setValue(min(1000,int(done*1000/total)))
            self.update_status.setText(f"Downloading update · {done/1024/1024:.1f} MB / {total/1024/1024:.1f} MB")
        else:
            self.update_progress.setRange(0,0); self.update_status.setText(f"Downloading update · {done/1024/1024:.1f} MB")

    def on_update_download_complete(self,result):
        self.update_progress.setVisible(False); self.update_progress.setValue(0); self.update_cancel_btn.setVisible(False)
        if not result.get("ok"):
            if result.get("cancelled"):
                self.update_status.setText("Update download canceled. Your current version was not changed.")
            else:
                self.update_status.setText("Download or verification failed. Your current version was not changed.")
                self.update_notes.setText(str(result.get("error","Unknown error"))+"\n\nUse View Releases for troubleshooting or retry later.")
                self.update_retry_btn.setVisible(True)
                self._record_update_history("download failed",self.latest_release.get("tag","") if self.latest_release else "",str(result.get("error","")))
            self.update_now_btn.setEnabled(bool(self.latest_release and verification_ready()))
            return
        self._verified_update=result["update"]
        self.update_status.setText(f"Kam3 Tweaks {self._verified_update['metadata']['version']} was downloaded and verified. No file has been installed.")
        self.update_now_btn.setEnabled(False); self.update_install_btn.setEnabled(bool(self._helper_path()))
        if not self.update_install_btn.isEnabled():
            self.update_notes.setText(self.update_notes.text()+"\n\nInstall & Restart is available only from the packaged app folder with Kam3TweaksUpdater.exe beside it.")
        self._record_update_history("download verified",self._verified_update["metadata"]["version"],"Signed manifest and executable SHA-256 verified.")
        self.refresh_update_history()

    def clear_download_worker(self):
        self._download_worker=None; self._download_thread=None

    def cancel_update_download(self):
        if self._download_worker:
            self._download_worker.cancel_event.set(); self.update_status.setText("Canceling download…")

    def _helper_path(self):
        return bool(getattr(sys,"frozen",False) and self._verified_update and self._verified_update.get("updater",Path()).is_file())

    def _update_recovery_summary(self):
        journal=APP_DATA/"update"/"install_journal.json"
        if journal.is_file(): return "An update operation was interrupted. Restore Previous Version can restore only the Kam3 Tweaks files recorded in its local recovery journal."
        backup_dir=Path(sys.executable).resolve().parent/"backup" if getattr(sys,"frozen",False) else None
        backups=list(backup_dir.glob("Kam3Tweaks_pre_*.exe")) if backup_dir and backup_dir.is_dir() else []
        if backups: return f"Previous-version recovery is available ({len(backups)} preserved backup executable(s)). No recovery action is pending."
        return "No interrupted update or previous-version backup is currently recorded."

    def recover_previous_version(self):
        journal=APP_DATA/"update"/"install_journal.json"
        helper=Path(sys.executable).resolve().parent/"Kam3TweaksUpdater.exe" if getattr(sys,"frozen",False) else None
        if not journal.is_file():
            QMessageBox.information(self,"No recovery pending","There is no interrupted update journal to recover."); self.update_recover_btn.setEnabled(False); return
        if not helper or not helper.is_file():
            QMessageBox.warning(self,"Updater unavailable","Kam3TweaksUpdater.exe is not beside the packaged application. Use the documented manual recovery steps and preserve the backup executable."); return
        if self._profile_sessions:
            QMessageBox.information(self,"Game session active","Close active profiled game sessions before restoring the previous application version."); return
        if QMessageBox.question(self,"Restore previous version?","The trusted updater will wait for Kam3 Tweaks to close normally, restore only the executable and updater recorded in the recovery journal, then restart the previous version. Your profiles and preferences are not changed.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes: return
        try:
            from update_installer import sha256_file
            run_dir=APP_DATA/"update-run"/("run-"+uuid.uuid4().hex); run_dir.mkdir(parents=True,exist_ok=False)
            copied=run_dir/"Kam3TweaksUpdater.exe"; shutil.copy2(helper,copied)
            if sha256_file(copied)!=sha256_file(helper): raise OSError("Updater helper copy verification failed.")
            subprocess.Popen([str(copied),"--recover","--parent-pid",str(os.getpid())],cwd=str(run_dir),close_fds=True,
                             creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            self.close()
        except Exception as exc:
            QMessageBox.warning(self,"Recovery could not start","Your files have not been changed.\n\n"+str(exc))

    def install_verified_update(self):
        if not self._verified_update or not verification_ready(): return
        if self._profile_sessions:
            QMessageBox.information(self,"Game session active","Close the profiled game session and restore its temporary settings before installing an update."); return
        if not getattr(sys,"frozen",False) or not self._helper_path():
            QMessageBox.warning(self,"Updater unavailable","The verified updater helper is unavailable. Use View Releases for a manual update."); return
        answer=QMessageBox.question(self,"Install update and restart?",
            f"Install Kam3 Tweaks {self._verified_update['metadata']['version']} and restart the application?\n\nThe updater will close Kam3 Tweaks normally, create a versioned backup, verify the signed file again, and preserve your profiles and settings. It will not request administrator permission.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes: return
        try:
            staging=APP_DATA/"update-staging"
            run_dir=APP_DATA/"update-run"/("run-"+uuid.uuid4().hex); run_dir.mkdir(parents=True,exist_ok=False)
            helper=run_dir/EXPECTED_UPDATER
            shutil.copy2(self._verified_update["updater"],helper)
            verify_updater(helper,self._verified_update["metadata"])
            request=create_install_request(self._verified_update,installed_version=APP_VERSION,parent_pid=os.getpid(),
                                           install_dir=Path(sys.executable).resolve().parent,staging_root=staging)
            subprocess.Popen([str(helper),"--install-request",str(request)],cwd=str(run_dir),close_fds=True,
                             creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            self._record_update_history("installation started",self._verified_update["metadata"]["version"],"User confirmed Install & Restart.")
            self.status.setText("The trusted updater is waiting for Kam3 Tweaks to close normally.")
            self.close()
        except Exception as exc:
            QMessageBox.warning(self,"Unable to start update","Windows could not start the trusted updater. Your current version is unchanged.\n\n"+str(exc))

    def check_update_result(self):
        token=next((arg.split("=",1)[1] for arg in sys.argv if arg.startswith("--update-health=")),"")
        try: result=json.loads((APP_DATA/"update"/"result.json").read_text(encoding="utf-8"))
        except (OSError,ValueError): return False
        if token and result.get("token")!=token: return False
        status=result.get("status")
        if status not in ("success","rolled_back","failed"): return False
        result_token=result.get("token") or (status+str(result.get("timestamp","")))
        if self.settings.get("last_update_result_token_shown")==result_token: return True
        self.settings["last_update_result_token_shown"]=result_token; self.save_settings_file()
        if status=="success": text=f"Kam3 Tweaks {result.get('version')} started successfully. Your previous executable backup is preserved."
        elif status=="rolled_back": text="The new version failed its startup check, so the previous Kam3 Tweaks version was restored.\n\n"+str(result.get("details",""))
        else: text="The update could not be completed. Your current installation was preserved where possible.\n\n"+str(result.get("details",""))
        QTimer.singleShot(350,lambda:QMessageBox.information(self,"Update status",text) if status=="success" else QMessageBox.warning(self,"Update status",text))
        self._record_update_history(status,result.get("version",""),result.get("details",""))
        self.refresh_update_history()
        if hasattr(self,"update_recovery_status"):
            self.update_recovery_status.setText(self._update_recovery_summary())
            self.update_recover_btn.setEnabled((APP_DATA/"update"/"install_journal.json").is_file())
        return True

    def cleanup_stale_update_run_dirs(self):
        root=APP_DATA/"update-run"
        if not root.is_dir() or root.is_symlink(): return
        try: entries=list(root.iterdir())
        except OSError: return
        for folder in entries:
            if not re.fullmatch(r"run-[0-9a-f]{32}",folder.name) or folder.is_symlink() or not folder.is_dir(): continue
            try:
                for child in folder.iterdir():
                    if child.name==EXPECTED_UPDATER and child.is_file() and not child.is_symlink(): child.unlink()
                folder.rmdir()
            except OSError: continue

    def open_update_page(self):
        url=self._latest_release_url if self._latest_release_url.startswith("https://github.com/kam3ron-util/kam3-tweaks/releases/") else RELEASES_URL
        try:
            if not webbrowser.open(url): raise OSError("No browser accepted the request.")
        except Exception as exc:
            QMessageBox.warning(self,"Could not open release page",str(exc))

    def open_activity_history(self):
        self.select_page(self.PAGE_NAMES.index("Settings"))
        self.activity_history_toggle.setChecked(True)
        self.activity_panel.setVisible(True)
        self.refresh_activity()

    def select_page(self,index):
        if self._operation_busy: return
        if not 0<=index<len(self.pages): return
        self.stack.setCurrentIndex(index); self.top_title.setText(self.PAGE_NAMES[index])
        for i,button in enumerate(self.nav_buttons):
            button.setChecked(i==index); button.setIcon(icon_for(self.PAGE_ICONS[i],i==index))
        if index==0: self.refresh_home()
        elif index==1: self.refresh_quick_section(self.quick_tabs.currentIndex())
        elif index==2: self.refresh_optimization_library()
        elif index==3: self.refresh_games()
        elif index==4: self.refresh_network_details()
        elif index==6 and self.activity_history_toggle.isChecked(): self.refresh_activity()

    def filter_nav(self,text):
        query=text.casefold().strip()
        for button,title in zip(self.nav_buttons,self.PAGE_NAMES): button.setVisible(not query or query in title.casefold())


    def refresh_all(self):
        self.refresh_settings(); self.refresh_plans(); self.refresh_home()


    def refresh_plans(self):
        if not WIN:
            self.plan.clear(); self.plan.addItem("Windows only"); self.plan.setEnabled(False); self.plan_btn.setEnabled(False); self.plan_current.setText("Windows power plans unavailable."); return
        current,name=active_plan(); self.plan.clear()
        for guid,title in plans(): self.plan.addItem(title,guid)
        idx=self.plan.findData(current)
        if idx>=0: self.plan.setCurrentIndex(idx)
        if hasattr(self,"profile_plan"):
            previous=self.profile_plan.currentData(); self.profile_plan.blockSignals(True); self.profile_plan.clear(); self.profile_plan.addItem("Unchanged","unchanged")
            for guid,title in plans(): self.profile_plan.addItem(title,guid)
            if previous is not None: self.profile_plan.setCurrentIndex(max(0,self.profile_plan.findData(previous)))
            self.profile_plan.blockSignals(False)
        self.plan_btn.setEnabled(bool(self.plan.count())); self.plan_current.setText(f"Current plan: {name or 'unavailable'}")

    def refresh_settings(self):
        if not WIN:
            for name in ("profile_btn","mode_btn","capture_btn","plan_btn","dns_btn","windows_temp_btn","recycle_btn"):
                widget=getattr(self,name,None)
                if widget: widget.setEnabled(False)
            if hasattr(self,"profile_status"): self.profile_status.setText("Windows controls are unavailable on this operating system.")
            return
        mode_state="Not configured"; capture_state="Not configured"
        try:
            mode_state,mode_value=game_mode_status(); capture_state,capture_value=capture_status()
            if hasattr(self,"mode"): self.mode.setCurrentIndex(0 if mode_value is True else 1 if mode_value is False else -1)
            if hasattr(self,"capture"): self.capture.setCurrentIndex(1 if capture_value is True else 0 if capture_value is False else -1)
        except (OSError,RuntimeError) as e:
            mode_state=capture_state=f"Unreadable: {e}"
            if hasattr(self,"mode"): self.mode.setCurrentIndex(-1)
            if hasattr(self,"capture"): self.capture.setCurrentIndex(-1)
        if hasattr(self,"profile_status"): self.profile_status.setText(f"Game Mode: {mode_state} · Background capture: {capture_state}")
        if hasattr(self,"settings_priority_summary"):
            enabled=bool(self.settings.get("priority_rules_enabled",False)) and any(r.get("enabled",True) and r.get("mode")=="automatic" for r in self.priority_rules)
            self.settings_priority_summary.setText("Automatic watcher is enabled while this app is open." if enabled else "Automatic watcher is paused or has no enabled automatic rules.")
        self.refresh_optimization_library()

    def refresh_processes(self,*_):
        if not hasattr(self,"proc_list"): return
        query=self.search.text().casefold().strip(); selected=self.proc_list.currentItem().data(Qt.ItemDataRole.UserRole) if self.proc_list.currentItem() else None
        try:
            found=[]
            for p in psutil.process_iter(["pid","name","exe","create_time"]):
                try:
                    pid=p.info["pid"]; name=p.info.get("name") or "Unknown"; exe=p.info.get("exe") or ""; created=float(p.info.get("create_time") or p.create_time())
                    if query and query not in name.casefold() and query not in exe.casefold() and query not in str(pid): continue
                    found.append((pid,name,exe,created,False))
                except (psutil.NoSuchProcess,psutil.AccessDenied,OSError,TypeError,ValueError): pass
            self._process_rows=found; self.proc_list.clear(); sort_index=self.process_sort.currentIndex() if hasattr(self,"process_sort") else 0
            sort_key=(lambda item:item[1].casefold()) if sort_index<2 else (lambda item:item[0])
            found=sorted(found,key=sort_key,reverse=sort_index in (1,3))
            for pid,name,exe,created,isgame in found[:800]:
                mark="  ·  possible game" if isgame else ""; item=QListWidgetItem(f"{name}    PID {pid}{mark}"); item.setData(Qt.ItemDataRole.UserRole,(pid,name,created,exe)); self.proc_list.addItem(item)
                if selected and selected[0]==pid and abs(selected[2]-created)<.02: self.proc_list.setCurrentItem(item)
            if not self.proc_list.count(): self.proc_list.addItem("No accessible processes match this filter.")
        except Exception as e: self.status.setText(f"Could not refresh process list: {e}")

    def process_selected(self):
        item=self.proc_list.currentItem() if hasattr(self,"proc_list") else None
        if not item: return None
        data=item.data(Qt.ItemDataRole.UserRole)
        if data and hasattr(self,"process_details"):
            exe=data[3] if len(data)>3 else ""
            current="unavailable"
            affinity="unavailable"
            try:
                process=psutil.Process(data[0]); value=process.nice(); current=next((k for k,v in PRIORITY_VALUES.items() if v==value),str(value))
                affinity=", ".join(str(cpu) for cpu in process.cpu_affinity())
            except (psutil.NoSuchProcess,psutil.AccessDenied,OSError): pass
            self.process_details.setText(f"Application: {data[1]}\nExecutable: {exe or 'unavailable'}\nPID: {data[0]}\nCurrent priority: {current}\nAllowed logical CPUs: {affinity}\nSelecting a process never changes its settings.")
            self.affinity_btn.setEnabled(bool(data and data[0]!=os.getpid() and WIN))
            self.priority_btn.setEnabled(bool(data and data[0]!=os.getpid() and WIN))
        return data

    def refresh_priority_rules(self):
        if not hasattr(self,"rules_table"): return
        self.rules_table.setRowCount(len(self.priority_rules))
        for row,rule in enumerate(self.priority_rules):
            vals=(rule.get("name",Path(rule["path"]).stem),rule["path"],rule["priority"],"Automatic" if rule["mode"]=="automatic" else "Once","Yes" if rule.get("enabled",True) else "No",rule.get("last_result","Not applied"))
            for col,value in enumerate(vals):
                cell=QTableWidgetItem(str(value)); cell.setData(Qt.ItemDataRole.UserRole,row); self.rules_table.setItem(row,col,cell)
        self.filter_priority_rules(self.rule_search.text() if hasattr(self,"rule_search") else "")
        if not WIN:
            for widget in (self.priority_master,self.apply_rules_btn,self.rule_save_btn,self.rule_enable_btn,self.rule_delete_btn,self.rule_restore_btn): widget.setEnabled(False)
            self.rule_status.setText("Process priority rules are available only on Windows.")
        else: self.rule_status.setText(f"{len(self.priority_rules)} saved rule(s) · watcher runs only while this app is open.")

    def filter_priority_rules(self,text):
        if not hasattr(self,"rules_table"): return
        query=text.casefold().strip()
        for row in range(self.rules_table.rowCount()):
            name=self.rules_table.item(row,0).text().casefold(); path=self.rules_table.item(row,1).text().casefold()
            self.rules_table.setRowHidden(row,bool(query and query not in name and query not in path))

    def load_selected_rule(self):
        if not hasattr(self,"rules_table"): return
        row=self.rules_table.currentRow()
        if row<0 or row>=len(self.priority_rules): return
        rule=self.priority_rules[row]; self.rule_name.setText(rule.get("name",Path(rule["path"]).stem)); self.rule_path.setText(rule["path"])
        self.rule_priority.setCurrentText(rule["priority"]); self.rule_mode.setCurrentIndex(self.rule_mode.findData(rule["mode"]))

    def save_priority_rules(self):
        try:
            APP_DATA.mkdir(parents=True,exist_ok=True); target=APP_DATA/"priority_rules.json"; temp=target.with_suffix(".tmp"); temp.write_text(json.dumps(self.priority_rules,indent=2),encoding="utf-8"); temp.replace(target); return True
        except OSError as e: self.rule_status.setText(f"Could not save priority rules: {e}"); return False

    def browse_priority_executable(self):
        path,_=QFileDialog.getOpenFileName(self,"Choose application executable",str(Path.home()),"Windows applications (*.exe)")
        if path: self.rule_path.setText(str(Path(path).resolve())); self.rule_name.setText(Path(path).stem)

    def use_selected_process_for_rule(self):
        data=self.process_selected()
        if not data or not data[3]: QMessageBox.information(self,"Choose a process","Select a process with an accessible executable path first."); return
        if protected_process(data[1],data[3]): QMessageBox.warning(self,"Protected process","This Windows or Kam3 Tweaks process is protected from priority rules."); return
        self.rule_name.setText(data[1]); self.rule_path.setText(os.path.normcase(os.path.abspath(data[3])))

    def save_priority_rule(self):
        raw=self.rule_path.text().strip(); path=Path(raw)
        if path.suffix.casefold()!=".exe" or not path.is_file(): QMessageBox.warning(self,"Invalid executable","Choose an existing executable path. The rule is matched by exact full path."); return
        if protected_process(self.rule_name.text().strip() or path.name,str(path)): QMessageBox.warning(self,"Protected application","Rules cannot target protected Windows or Kam3 Tweaks processes."); return
        normalized=os.path.normcase(os.path.abspath(str(path))); rule={"name":self.rule_name.text().strip() or path.stem,"path":normalized,"priority":self.rule_priority.currentText(),"mode":self.rule_mode.currentData(),"enabled":True,"last_result":"Saved; not applied"}
        if rule["mode"]=="automatic" and self.settings.get("priority_rules_enabled",False):
            if not self.ask("Save active automatic rule?",f"Save {rule['priority']} for this exact executable path? The enabled watcher may change matching running processes within a few seconds while Kam3 Tweaks is open. Priorities can be restored.\n\n{normalized}"): return
        existing=next((i for i,r in enumerate(self.priority_rules) if os.path.normcase(os.path.abspath(r["path"]))==normalized),None)
        if existing is None: self.priority_rules.append(rule)
        else:
            rule["enabled"]=self.priority_rules[existing].get("enabled",True); rule["last_result"]=self.priority_rules[existing].get("last_result","Updated")
            self.priority_rules[existing]=rule
        if not self.save_priority_rules(): return
        self.refresh_priority_rules(); self.rule_status.setText(f"Saved exact-path {rule['mode']} rule for {path.name}. Select Apply Rules Now for a running process.")

    def toggle_priority_master(self,enabled):
        if not WIN:
            self.priority_master.blockSignals(True); self.priority_master.setChecked(False); self.priority_master.blockSignals(False); return
        previous=bool(self.settings.get("priority_rules_enabled",False))
        if enabled and not self.ask("Enable automatic priority rules?","Enabled exact-path rules may change matching running process priorities while Kam3 Tweaks is open. The original priority is saved for Undo. No Windows service is installed."):
            self.priority_master.blockSignals(True); self.priority_master.setChecked(previous); self.priority_master.blockSignals(False); return
        self.settings["priority_rules_enabled"]=bool(enabled)
        if not self.save_settings_file():
            self.settings["priority_rules_enabled"]=previous; self.priority_master.blockSignals(True); self.priority_master.setChecked(previous); self.priority_master.blockSignals(False); return
        if enabled and any(r.get("enabled",True) and r.get("mode")=="automatic" for r in self.priority_rules): self.priority_timer.start(5000)
        else: self.priority_timer.stop()
        self.rule_status.setText("Automatic watcher enabled while Kam3 Tweaks is open." if enabled else "Automatic watcher paused; saved rules remain on disk.")

    def toggle_selected_rule(self):
        row=self.rules_table.currentRow()
        if row<0 or row>=len(self.priority_rules): return
        rule=self.priority_rules[row]; enabling=not rule.get("enabled",True)
        if enabling and self.settings.get("priority_rules_enabled",False) and rule.get("mode")=="automatic":
            if not self.ask("Enable automatic priority rule?",f"Allow the watcher to apply {rule['priority']} priority to processes matching this exact path? Original priority is saved for Undo.\n\n{rule['path']}"): return
        rule["enabled"]=enabling
        if self.save_priority_rules(): self.refresh_priority_rules()

    def delete_priority_rule(self):
        row=self.rules_table.currentRow()
        if row<0 or row>=len(self.priority_rules): return
        rule=self.priority_rules[row]
        if not self.ask("Delete priority rule?",f"Delete the saved rule for {rule['path']}? Any active process priority remains until restored, the process exits, or you use Undo."): return
        key=os.path.normcase(os.path.abspath(rule["path"]))
        self.priority_rules.pop(row)
        if self.save_priority_rules():
            for tracking_key,entry in list(self._priority_applied.items()):
                if tracking_key[0]==key: entry["rule_deleted"]=True
            self.refresh_priority_rules()

    def _enumerate_priority_targets(self):
        found=[]
        for proc in psutil.process_iter(["pid","name","exe","create_time"]):
            try:
                pid=int(proc.info["pid"]); name=proc.info.get("name") or "Unknown"; exe=proc.info.get("exe") or ""; created=float(proc.info.get("create_time") or proc.create_time())
                if pid!=os.getpid() and exe and not protected_process(name,exe): found.append((pid,name,os.path.normcase(os.path.abspath(exe)),created))
            except (psutil.NoSuchProcess,psutil.AccessDenied,OSError,TypeError,ValueError): continue
        return found

    def _priority_transaction(self,proc,pid,created,old,target,label):
        tx_label=f"{label} · PID {pid}"
        self.undo.begin(tx_label)
        try:
            self.undo.record({"type":"priority","pid":pid,"created":created,"old":old,"expected":target})
            proc.nice(target); self.undo.finish()
            return self.undo.items[-1] if self.undo.items and self.undo.items[-1].get("label")==tx_label else None
        except Exception:
            try:
                if abs(proc.create_time()-created)<.02 and proc.nice()!=old: proc.nice(old)
            except (psutil.NoSuchProcess,psutil.AccessDenied,OSError): pass
            tx=self.undo.current
            if tx and tx in self.undo.items: self.undo.items.remove(tx)
            self.undo.current=None
            try: self.undo.save()
            except OSError: pass
            raise

    def apply_priority_rule(self,rule,target_info,automatic=False):
        pid,name,exe,created=target_info; rule_path=os.path.normcase(os.path.abspath(rule["path"]))
        if exe!=rule_path or protected_process(name,exe): return False,"Protected or nonmatching executable; skipped."
        key=(rule_path,pid,created)
        if key in self._priority_applied: return False,"Already tracked for this process instance."
        proc=psutil.Process(pid)
        if abs(proc.create_time()-created)>.02: raise RuntimeError("Process ended or PID was reused.")
        old=proc.nice(); target=PRIORITY_VALUES[rule["priority"]]
        if old==target:
            self._priority_applied[key]={"old":old,"target":target,"tx":None,"name":name,"created":created}
            result=f"{name} already has {rule['priority']} priority."
        else:
            tx=self._priority_transaction(proc,pid,created,old,target,f"Priority rule: {rule.get('name',name)}")
            self._priority_applied[key]={"old":old,"target":target,"tx":tx,"name":name,"created":created}
            result=f"Applied {rule['priority']} priority to {name} (PID {pid})."
        rule["last_result"]=datetime.datetime.now().astimezone().isoformat(timespec="seconds")+" · "+result
        write_activity("Automatic priority" if automatic else "Priority rule",result,"success",exe); self.save_priority_rules(); self.refresh_undo()
        return True,result

    def apply_rules_now(self):
        targets=self._enumerate_priority_targets(); operations=[]
        for rule in self.priority_rules:
            if not rule.get("enabled",True): continue
            path=os.path.normcase(os.path.abspath(rule["path"]))
            for item in targets:
                if item[2]==path and (path,item[0],item[3]) not in self._priority_applied: operations.append((rule,item))
        if not operations: QMessageBox.information(self,"No matching processes","No enabled exact-path rules match an untracked running process."); return
        lines=[f"{info[1]} · PID {info[0]} → {rule['priority']} ({rule['path']})" for rule,info in operations]
        if not self.ask("Apply saved priority rules?","Apply these priorities now? The original priority is saved for Undo.\n\n"+"\n".join(lines)): return
        results=[]
        for rule,info in operations:
            try: _,msg=self.apply_priority_rule(rule,info,False); results.append(msg)
            except (psutil.NoSuchProcess,psutil.AccessDenied,OSError,RuntimeError) as e:
                msg=f"{info[1]} (PID {info[0]}): {e}"; rule["last_result"]="Error · "+str(e); write_activity("Priority rule",str(e),"error",info[2]); results.append(msg)
        self.save_priority_rules(); self.refresh_priority_rules(); self.refresh_activity()
        QMessageBox.information(self,"Priority rules processed","\n".join(results))

    def scan_priority_rules(self):
        if self._operation_busy: return
        if not WIN or not self.settings.get("priority_rules_enabled",False): return
        rules=[r for r in self.priority_rules if r.get("enabled",True) and r.get("mode")=="automatic"]
        if not rules: self.priority_timer.stop(); return
        targets=self._enumerate_priority_targets(); live=set(); changed=False
        for rule in rules:
            expected=os.path.normcase(os.path.abspath(rule["path"]))
            for info in targets:
                pid,name,exe,created=info
                if exe!=expected: continue
                key=(expected,pid,created); live.add(key)
                if key in self._priority_applied: continue
                try: self.apply_priority_rule(rule,info,True); changed=True
                except (psutil.NoSuchProcess,psutil.AccessDenied,OSError,RuntimeError) as e:
                    rule["last_result"]="Error · "+str(e); write_activity("Automatic priority",str(e),"error",exe); changed=True
        for key,entry in list(self._priority_applied.items()):
            if key in live: continue
            tx=entry.get("tx")
            if tx and tx in self.undo.items:
                tx["actions"][:]=[a for a in tx["actions"] if not (a.get("type")=="priority" and a.get("pid")==key[1] and abs(a.get("created",-1)-key[2])<.02)]
                if not tx["actions"]: self.undo.items.remove(tx)
                try: self.undo.save()
                except OSError: pass
            del self._priority_applied[key]
        if changed: self.save_priority_rules(); self.refresh_priority_rules(); self.refresh_activity(); self.refresh_undo()

    def restore_rule_priority(self):
        row=self.rules_table.currentRow()
        if row<0 or row>=len(self.priority_rules): return
        rule=self.priority_rules[row]; path=os.path.normcase(os.path.abspath(rule["path"]))
        targets=[(key,value) for key,value in self._priority_applied.items() if key[0]==path]
        if not targets: QMessageBox.information(self,"No active priority","No tracked process instance for this rule is still running."); return
        if not self.ask("Restore original priority?",f"Restore the exact prior priority for {len(targets)} tracked process instance(s)?"): return
        results=[]
        for key,entry in targets:
            try:
                proc=psutil.Process(key[1])
                if abs(proc.create_time()-key[2])>.02: raise RuntimeError("PID was reused.")
                current=proc.nice()
                if current not in (entry["old"],entry["target"]):
                    raise RuntimeError("Priority was changed outside this rule; the newer value was left intact.")
                if current!=entry["old"]: proc.nice(entry["old"])
                results.append(f"Restored {entry['name']} PID {key[1]}.")
                tx=entry.get("tx")
                if tx and tx in self.undo.items:
                    tx["actions"][:]=[a for a in tx["actions"] if not (a.get("type")=="priority" and a.get("pid")==key[1] and abs(a.get("created",-1)-key[2])<.02)]
                    if not tx["actions"]: self.undo.items.remove(tx)
                del self._priority_applied[key]
            except (psutil.NoSuchProcess,psutil.AccessDenied,OSError,RuntimeError) as e: results.append(f"PID {key[1]}: {e}")
        self.undo.save(); self.refresh_undo(); self.refresh_activity(); QMessageBox.information(self,"Priority restore results","\n".join(results))



    def ask(self,title,text):
        return QMessageBox.question(self,title,text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

    def finish_change(self,label,fn,transaction_metadata=None):
        if self._operation_busy: return
        self.set_busy(True,f"Applying {label}…")
        try:
            self.undo.begin(label,transaction_metadata)
            result=fn(); partial=bool(re.search(r"(?im)^\s*Failed:",result)); self.undo.finish()
            write_activity(label,result,"partial" if partial else "success")
            self.set_operation_result("Needs attention" if partial else "Complete",result)
            (QMessageBox.warning if partial else QMessageBox.information)(self,"Some changes need attention" if partial else "Kam3 Tweaks change complete",result)
        except Exception as exc:
            try: self.undo.finish()
            except OSError: pass
            suffix=" Any completed part may have applied; use Undo if available." if self.undo.items else ""
            message=f"Could not apply change: {exc}{suffix}"; self.set_operation_result("Error",message); write_activity(label,str(exc),"error"); QMessageBox.warning(self,"Kam3 Tweaks could not apply the change",message)
        finally: self.set_busy(False)
        try: self.refresh_undo(); self.refresh_settings(); self.refresh_plans(); self.refresh_startup(); self.refresh_custom_profile_controls(); self.refresh_activity(); self.refresh_preset_controls()
        except Exception as exc: self.set_operation_result("Needs attention",f"Change finished, but status refresh failed: {exc}")

    def on_operation_text_changed(self,text):
        self.operation_state.setText("Working" if self._operation_busy else "Status")
        self.operation_state.setProperty("severity","normal")
        self.operation_state.style().unpolish(self.operation_state); self.operation_state.style().polish(self.operation_state)

    def set_operation_result(self,state,message):
        self.status.setText(message); self.operation_state.setText(state)
        self.operation_state.setProperty("severity","error" if state in ("Error","Needs attention") else "normal")
        self.operation_state.style().unpolish(self.operation_state); self.operation_state.style().polish(self.operation_state)

    def show_operation_details(self):
        QMessageBox.information(self,"Operation details",self.status.text())

    def closeEvent(self,event):
        thread=getattr(self,"_network_query_thread",None)
        if thread is not None and thread.isRunning():
            thread.quit(); thread.wait(7000)
        super().closeEvent(event)

    def configure_accessibility(self):
        self.nav_search.setAccessibleName("Find a navigation page")
        for index,button in enumerate(self.nav_buttons):
            button.setAccessibleName(self.PAGE_NAMES[index]); button.setAccessibleDescription(f"Open {self.PAGE_NAMES[index]}. Shortcut Ctrl+{index+1}.")
        for widget in self.findChildren(QWidget):
            if isinstance(widget,(QPushButton,QCheckBox)):
                widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                if not widget.accessibleName(): widget.setAccessibleName(widget.text().replace("&",""))
            if isinstance(widget,QLabel):
                widget.setTextFormat(Qt.TextFormat.PlainText)
                if len(widget.text())>38: widget.setWordWrap(True)
        self.undo_btn.setAccessibleName("Undo latest reversible change")
        self.operation_state.setAccessibleName("Operation outcome")

    def set_busy(self,busy,label=""):
        if busy:
            if self._operation_busy: return
            self._operation_busy=True
            self._busy_enable_states={widget:widget.isEnabled() for widget in self.findChildren(QWidget) if isinstance(widget,(QPushButton,QComboBox,QLineEdit,QCheckBox,QTableWidget,QListWidget)) and widget is not self.operation_details_btn}
            for widget in self._busy_enable_states: widget.setEnabled(False)
            self.operation_progress.setRange(0,0); self.operation_progress.show()
            self.status.setText(label); self.operation_state.setText("Working")
        else:
            for widget,enabled in (getattr(self,"_busy_enable_states",None) or {}).items(): widget.setEnabled(enabled)
            self._busy_enable_states=None; self._operation_busy=False; self.operation_progress.hide()
            if self.operation_state.text()=="Working": self.operation_state.setText("Status")
        QApplication.processEvents()

    def apply_profile(self):
        if not WIN: return
        if not self.ask("Apply Windows gaming preferences?","Enable Game Mode and disable Windows background capture? These reversible preferences may need sign-out or restart. FPS gains are not guaranteed."): return
        def run():
            n=0
            for k,name,val in ((GAMEBAR,"AutoGameModeEnabled",1),(CAPTURE,"AppCaptureEnabled",0),(GAMECONFIG,"GameDVR_Enabled",0)): n+=set_dword(self.undo,k,name,val)
            return "Gaming preferences applied." if n else "Gaming preferences are already set."
        self.finish_change("gaming preferences",run)

    def apply_mode(self):
        if self.mode.currentText() not in ("On","Off"):
            QMessageBox.information(self,"Choose a Game Mode value","The current value is not fully configured or could not be read. Choose On or Off explicitly before applying."); return
        value=int(self.mode.currentText()=="On")
        if not self.ask("Change Game Mode?",f"Set current-user Game Mode preference to {'On' if value else 'Off'}? The change is reversible."): return
        self.finish_change("Game Mode",lambda:(set_dword(self.undo,GAMEBAR,"AutoGameModeEnabled",value),f"Game Mode set to {'On' if value else 'Off'}.")[-1])

    def apply_capture(self):
        if self.capture.currentText() not in ("On","Off"):
            QMessageBox.information(self,"Choose a capture value","Capture settings are mixed, partial, or unavailable. Choose On or Off explicitly before applying."); return
        value=int(self.capture.currentText()=="On")
        if not self.ask("Change background capture?",f"Set Windows background capture to {'On' if value else 'Off'}? The change is reversible."): return
        self.finish_change("background capture",lambda:(set_dword(self.undo,CAPTURE,"AppCaptureEnabled",value),set_dword(self.undo,GAMECONFIG,"GameDVR_Enabled",value),f"Background capture set to {'On' if value else 'Off'}.")[-1])

    def apply_plan(self):
        guid=self.plan.currentData(); name=self.plan.currentText()
        if not guid or not self.ask("Change power plan?",f"Switch to {name}? Power use and heat may change. Undo restores the previous plan GUID."): return
        def run():
            old,title=active_plan()
            if not old: raise RuntimeError(f"Could not read current plan: {title}")
            if old.casefold()==guid.casefold(): return f"{name} is already active."
            self.undo.record({"type":"power","guid":old,"expected":guid}); c,o,e=command(["powercfg","/setactive",guid])
            if c: raise RuntimeError(e or o or "Windows could not change plan.")
            return f"Power plan changed to {name}."
        self.finish_change("power plan",run)

    def cleanup(self):
        self.set_busy(True,"Previewing eligible TEMP files…")
        try:
            folder,items=temp_preview_details(limit=20000)
            if len(items)>=20000: raise RuntimeError("More than 20,000 eligible files were found. Nothing was deleted; reduce the TEMP folder and preview again.")
        except Exception as e: self.set_busy(False); QMessageBox.warning(self,"TEMP preview unavailable",str(e)); return
        self.set_busy(False)
        if not items: QMessageBox.information(self,"Temporary files",f"No eligible files found in {folder}"); return
        size=sum(item[1] for item in items); shown="\n".join(f"{item[0]}  ({item[1] / 1024:.0f} KB)" for item in items)
        dialog=QMessageBox(self); dialog.setWindowTitle("Review temporary files"); dialog.setIcon(QMessageBox.Icon.Warning); dialog.setText(f"Delete {len(items)} files from your user TEMP folder?\n{folder}\nEstimated {size/(1024**2):.1f} MB. Locked or changed files will be skipped. This cannot be undone."); dialog.setDetailedText(shown); dialog.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No); dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec()!=QMessageBox.StandardButton.Yes: return
        self.set_busy(True,"Deleting only the files listed in the preview…")
        try:
            n,b,s,deleted=clean_temp_selected(folder,items,report=True); msg=f"Cleanup complete: {n} files removed, ~{b/(1024**2):.1f} MB freed, {s} skipped."; self.status.setText(msg); write_activity("TEMP cleanup",msg,"success",str(folder)+"\n"+"\n".join(deleted[:100])); done=QMessageBox(self); done.setWindowTitle("Cleanup complete"); done.setIcon(QMessageBox.Icon.Information); done.setText(msg); done.setDetailedText("Removed files:\n"+"\n".join(deleted[:500])+(f"\n… and {len(deleted)-500} more" if len(deleted)>500 else "") if deleted else "No files were removed."); done.exec()
        except Exception as e: self.status.setText(f"Cleanup failed: {e}"); write_activity("TEMP cleanup",str(e),"error"); QMessageBox.warning(self,"Cleanup failed",str(e))
        finally: self.set_busy(False); self.refresh_activity()

    def cleanup_windows_temp(self):
        if not WIN: QMessageBox.information(self,"Windows-only cleanup","Windows TEMP cleanup is available only on Windows."); return
        if not admin():
            QMessageBox.information(self,"Administrator rights required","Windows TEMP preview may be available, but deletion requires administrator rights for some files. Kam3 Tweaks will not elevate itself. If you choose, close the app and relaunch it manually as administrator, then preview again."); return
        self.set_busy(True,"Previewing eligible Windows TEMP files…")
        try:
            folder,items=windows_temp_preview_details(limit=5001)
            if len(items)>=5001: raise RuntimeError("More than 5,000 eligible files were found. Nothing was deleted; review the folder in File Explorer.")
        except Exception as e: self.set_busy(False); QMessageBox.warning(self,"Windows TEMP preview unavailable",str(e)); return
        self.set_busy(False)
        if not items: QMessageBox.information(self,"Windows TEMP",f"No regular files older than 7 days were found in {folder}. Subfolders are not scanned."); return
        size=sum(item[1] for item in items); listing="\n".join(f"{item[0]}  ({item[1]/1024:.0f} KB)" for item in items[:250])
        dialog=QMessageBox(self); dialog.setWindowTitle("Review Windows TEMP files"); dialog.setIcon(QMessageBox.Icon.Warning); dialog.setText(f"Delete {len(items)} unchanged regular files older than 7 days from Windows TEMP?\n{folder}\nEstimated {size/(1024**2):.1f} MB. Subfolders are not traversed. Locked, changed, or inaccessible files are skipped. This cannot be undone."); dialog.setDetailedText(listing); dialog.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No); dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec()!=QMessageBox.StandardButton.Yes: return
        self.set_busy(True,"Deleting only the Windows TEMP preview files…")
        try:
            removed,freed,skipped,deleted=clean_temp_selected(folder,items,system_temp=True,report=True); msg=f"Windows TEMP cleanup: {removed} files removed, ~{freed/(1024**2):.1f} MB freed, {skipped} skipped."
            self.status.setText(msg); write_activity("Windows TEMP cleanup",msg,"success",str(folder)+"\n"+"\n".join(deleted[:100])); done=QMessageBox(self); done.setWindowTitle("Cleanup complete"); done.setIcon(QMessageBox.Icon.Information); done.setText(msg); done.setDetailedText("Removed files:\n"+"\n".join(deleted[:500])+(f"\n… and {len(deleted)-500} more" if len(deleted)>500 else "") if deleted else "No files were removed."); done.exec()
        except Exception as e: self.status.setText(f"Windows TEMP cleanup failed: {e}"); write_activity("Windows TEMP cleanup",str(e),"error"); QMessageBox.warning(self,"Windows TEMP cleanup failed",str(e))
        finally: self.set_busy(False); self.refresh_activity(); self.refresh_home()

    def cleanup_recycle_bin(self):
        if not WIN: QMessageBox.information(self,"Windows-only cleanup","Recycle Bin controls are available only on Windows."); return
        try: count,size=recycle_bin_summary()
        except Exception as e: QMessageBox.warning(self,"Could not inspect Recycle Bin",str(e)); return
        if count<=0: QMessageBox.information(self,"Recycle Bin","Windows reports no items in the Recycle Bin."); return
        if not self.ask("Empty the Recycle Bin?",f"Windows reports {count:,} items totaling {size/(1024**3):.2f} GB. Emptying is permanent and cannot be undone. Continue?"): return
        self.set_busy(True,"Emptying Recycle Bin…")
        try:
            empty_recycle_bin(); msg=f"Recycle Bin emptied ({count:,} items, previously {size/(1024**3):.2f} GB)."; self.status.setText(msg); write_activity("Recycle Bin cleanup",msg); QMessageBox.information(self,"Recycle Bin cleanup",msg)
        except Exception as e: self.status.setText(f"Recycle Bin cleanup failed: {e}"); write_activity("Recycle Bin cleanup",str(e),"error"); QMessageBox.warning(self,"Recycle Bin cleanup failed",str(e))
        finally: self.set_busy(False); self.refresh_activity(); self.refresh_home()

    def flush_dns(self):
        if not self.ask("Flush DNS cache?","Run ipconfig /flushdns? This clears cached name lookups. It is not reversible and does not guarantee an FPS change."): return
        self.set_busy(True,"Flushing DNS cache…")
        try:
            c,o,e=command(["ipconfig","/flushdns"],15)
            if c: msg=e or o or f"Exit code {c}"; self.status.setText("DNS flush failed."); write_activity("DNS flush",msg,"error"); QMessageBox.warning(self,"DNS flush failed",msg)
            else: msg=o or "DNS cache flushed."; self.status.setText(msg); write_activity("DNS flush",msg); QMessageBox.information(self,"DNS cache",msg)
        finally: self.set_busy(False); self.refresh_activity()

    def apply_priority(self):
        item=self.proc_list.currentItem()
        if not item or not item.data(Qt.ItemDataRole.UserRole): QMessageBox.information(self,"Choose a process","Select a running process first."); return
        data=item.data(Qt.ItemDataRole.UserRole); pid,name,created=data[:3]; value=self.priority.currentData(); label=self.priority.currentText()
        exe=data[3] if len(data)>3 else ""
        if pid==os.getpid() or protected_process(name,exe): QMessageBox.warning(self,"Protected process","Windows and Kam3 Tweaks processes cannot be changed."); return
        if not self.ask("Change process priority?",f"Set {name} (PID {pid}) to {label}? This affects CPU scheduling only and can be undone while the same process is open."): return
        def run():
            p=psutil.Process(pid)
            if abs(p.create_time()-created)>.02: raise RuntimeError("Process ended or PID was reused; refresh the list.")
            old=p.nice()
            if old==value: return f"{name} is already {label}."
            self.undo.record({"type":"priority","pid":pid,"created":created,"old":old,"expected":value}); p.nice(value); return f"{name} priority set to {label}."
        self.finish_change(f"{name} priority",run)

    def apply_affinity(self):
        data=self.process_selected()
        if not data: QMessageBox.information(self,"Choose a process","Select an application first."); return
        pid,name,created,exe=data[:4]
        if pid==os.getpid() or protected_process(name,exe): QMessageBox.warning(self,"Protected process","Windows and Kam3 Tweaks processes cannot be changed."); return
        try:
            process=psutil.Process(pid)
            if abs(process.create_time()-created)>.02: raise RuntimeError("Process ended or PID was reused; refresh the list.")
            previous=sorted(process.cpu_affinity()); count=max(psutil.cpu_count() or 1,max(previous,default=0)+1)
        except (psutil.NoSuchProcess,psutil.AccessDenied,OSError,RuntimeError) as e: QMessageBox.warning(self,"Affinity unavailable",str(e)); return
        dialog=QDialog(self); dialog.setWindowTitle(f"CPU affinity · {name}"); dialog.setMinimumWidth(340); layout=QVBoxLayout(dialog)
        note=QLabel("Select the logical processors this process may use. Affinity can reduce performance or cause compatibility issues."); note.setWordWrap(True); layout.addWidget(note)
        checks=[]
        for cpu in range(count):
            check=QCheckBox(f"CPU {cpu}"); check.setChecked(cpu in previous); checks.append(check); layout.addWidget(check)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted: return
        target=[i for i,check in enumerate(checks) if check.isChecked()]
        if not target: QMessageBox.warning(self,"Invalid affinity","At least one logical processor must remain selected."); return
        if target==previous: QMessageBox.information(self,"No change","The selected process already uses this CPU affinity."); return
        if not self.ask("Change CPU affinity?",f"Set {name} (PID {pid}) to use logical CPUs {', '.join(map(str,target))}? Undo saves the exact previous set."): return
        def run():
            process=psutil.Process(pid)
            if abs(process.create_time()-created)>.02: raise RuntimeError("Process ended or PID was reused.")
            old=sorted(process.cpu_affinity())
            if old==target: return f"{name} already has the selected CPU affinity."
            self.undo.record({"type":"affinity","pid":pid,"created":created,"old":old,"expected":target}); process.cpu_affinity(target)
            return f"CPU affinity changed for {name} (PID {pid})."
        self.finish_change(f"{name} CPU affinity",run)

    def undo_last(self):
        if self._operation_busy: return
        if not self.undo.items: return
        if not self.ask("Undo last change?",f"Restore settings saved by “{self.undo.label}”? Windows may need sign-out or restart for some changes."): return
        try: ok,msg=self.undo.undo()
        except Exception as e: ok,msg=False,f"Undo could not be saved or completed: {e}"
        self.status.setText(msg); write_activity("Undo",msg,"success" if ok else "error")
        if not ok: QMessageBox.warning(self,"Undo incomplete",msg)
        else: QMessageBox.information(self,"Undo complete",msg)
        self.refresh_undo(); self.refresh_settings(); self.refresh_plans(); self.refresh_startup(); self.refresh_activity()

    def refresh_undo(self):
        enabled=bool(self.undo.items); text="Undo: "+self.undo.label if enabled else "Nothing to undo"
        if hasattr(self,"gaming_undo_btn"): self.gaming_undo_btn.setEnabled(any(item.get("label")=="Gaming Tweaks" for item in self.undo.items))
        if hasattr(self,"startup_profile_undo_btn"): self.startup_profile_undo_btn.setEnabled(any(item.get("label")=="Startup Tweaks" for item in self.undo.items))
        self.undo_btn.setEnabled(enabled); self.undo_btn.setText("Undo latest…" if enabled else "Nothing to undo"); self.undo_btn.setToolTip(text); self.undo_btn.setAccessibleDescription(text)
        for name,buttons in self.category_undo_buttons.items():
            matches=self.category_transactions(name); count=len(matches)
            detail=f"Undo available · {count} saved transaction(s). Latest: {matches[-1][1].get('label',name)}" if matches else "No saved category changes to undo."
            for button in buttons:
                button.setEnabled(bool(count) and not self._operation_busy); button.setText(f"Undo category ({count})" if count else "Undo unavailable"); button.setToolTip(detail); button.setAccessibleName("Undo "+name); button.setAccessibleDescription(detail)
            for status in self.category_undo_labels.get(name,[]): status.setText(detail)
        for button in getattr(self,"_optimization_restore_rows",[]): button.setEnabled(enabled)
        if hasattr(self,"optimization_restore_btn"): self.optimization_restore_btn.setEnabled(enabled)
        if hasattr(self,"home_restore_btn"): self.home_restore_btn.setEnabled(enabled)
        if hasattr(self,"home_undo_metric"): self.home_undo_metric.setText("Ready" if enabled else "Clear")
        if hasattr(self,"home_restore_label"): self.home_restore_label.setText(f"Latest change: {self.undo.label}. Undo will verify the saved prior value." if enabled else "No reversible action is queued.")
        if hasattr(self,"custom_profile_combo"): self.refresh_custom_profile_controls()
        if hasattr(self,"dns_undo_config_btn"): self.update_dns_controls()

    def closeEvent(self,event):
        if self._operation_busy:
            event.ignore(); return
        if self._profile_sessions:
            answer=QMessageBox.question(self,"Game profiles are active",f"{len(self._profile_sessions)} profiled game session(s) are still active. If you close Kam3 Tweaks now, its exit monitor stops and temporary global profile settings may remain until you use Undo. Close anyway?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes: event.ignore(); return
        if self._download_thread and self._download_thread.isRunning():
            if self._download_worker: self._download_worker.cancel_event.set()
            if not self._download_thread.wait(7000):
                event.ignore(); self.status.setText("The update download is canceling. Close Kam3 Tweaks again in a moment."); return
        if self._update_thread and self._update_thread.isRunning():
            self._update_thread.quit()
            if not self._update_thread.wait(9000):
                event.ignore(); self.status.setText("The GitHub check is still finishing. Please close the app again in a moment."); return
        if hasattr(self,"game_timer"): self.game_timer.stop()
        event.accept()

    def refresh_games(self):
        if not hasattr(self,"game_list"): return
        selected=self.game_list.currentRow(); self.game_list.clear()
        valid=[]
        for game in self.games:
            if isinstance(game,dict) and game.get("path"): valid.append(game)
        self.games=valid
        for game in self.games:
            priority={"Normal":"Medium","Below Normal":"Low","Above Normal":"High"}.get(game.get("priority"),game.get("priority","Medium"))
            self.game_list.addItem(f"{game.get('name',Path(game['path']).name)}   ·   {priority}")
        if self.games: self.game_list.setCurrentRow(min(max(selected,0),len(self.games)-1))
        self.game_selected()


    def game_selected(self,*_):
        if not hasattr(self,"game_list"): return
        i=self.game_list.currentRow()
        if i<0 or i>=len(self.games): self.game_selected_path.setText("Select a saved game to see its path."); return
        game=self.games[i]; self.game_selected_path.setText(game["path"])
        priority={"Normal":"Medium","Below Normal":"Low","Above Normal":"High"}.get(game.get("priority"),game.get("priority","Medium"))
        self.game_profile.blockSignals(True); self.game_profile.setCurrentIndex(max(0,self.game_profile.findText(priority))); self.game_profile.blockSignals(False)
        profile_key=game.get("profile_key",game.get("name",""))
        found=self.profile_key_combo.findText(profile_key)
        if found>=0: self.profile_key_combo.setCurrentIndex(found)


    def save_games(self):
        APP_DATA.mkdir(parents=True,exist_ok=True); temp=game_paths_file().with_suffix(".tmp"); temp.write_text(json.dumps(self.games,indent=2),encoding="utf-8"); temp.replace(game_paths_file())

    def add_game(self):
        path,_=QFileDialog.getOpenFileName(self,"Choose a game executable",str(Path.home()),"Windows programs (*.exe)")
        if not path: return
        p=Path(path)
        if p.suffix.casefold()!=".exe" or not p.is_file(): QMessageBox.warning(self,"Invalid executable","Choose an existing .exe file."); return
        if any(Path(g["path"]).resolve()==p.resolve() for g in self.games): return
        self.games.append({"name":p.stem,"path":str(p),"priority":"Medium"})
        try: self.save_games()
        except OSError as e: self.games.pop(); QMessageBox.warning(self,"Could not save game",str(e)); return
        self.refresh_games(); self.game_list.setCurrentRow(len(self.games)-1); write_activity("Game library","Added game path",details=str(p)); self.refresh_activity()


    def remove_game(self):
        i=self.game_list.currentRow()
        if i<0 or i>=len(self.games): return
        game=self.games[i]
        if not self.ask("Remove saved game?",f"Remove {game['name']} from the local library? This does not delete its executable."): return
        removed=self.games.pop(i)
        try: self.save_games()
        except OSError as e: self.games.insert(i,removed); QMessageBox.warning(self,"Could not save game library",str(e)); return
        self.refresh_games(); write_activity("Game library","Removed saved game",details=game["path"]); self.refresh_activity()

    def save_game_profile(self,*_):
        i=self.game_list.currentRow()
        if i<0 or i>=len(self.games): return
        old=self.games[i].get("priority","Medium"); self.games[i]["priority"]=self.game_profile.currentText().replace(" priority","")
        try: self.save_games()
        except OSError as e: self.games[i]["priority"]=old; QMessageBox.warning(self,"Could not save game profile",str(e)); return
        self.refresh_games()

    def load_profile_editor(self,*_):
        if not hasattr(self,"profile_mode"): return
        profile=self.profiles.get(self.profile_key_combo.currentText(),validate_profile({}))
        self.profile_mode.setCurrentIndex({"unchanged":0,"on":1,"off":2}.get(profile["game_mode"],0))
        self.profile_capture.setCurrentIndex({"unchanged":0,"on":1,"off":2}.get(profile["background_capture"],0))
        self.profile_plan.setCurrentIndex(max(0,self.profile_plan.findData(profile["power_plan"])))
        self.profile_priority.setCurrentIndex(max(0,self.profile_priority.findText(profile["priority"])))

    def save_profile_editor(self):
        name=self.profile_key_combo.currentText()
        values={"game_mode":("unchanged","on","off")[self.profile_mode.currentIndex()],"background_capture":("unchanged","on","off")[self.profile_capture.currentIndex()],"power_plan":self.profile_plan.currentData() or "unchanged","priority":self.profile_priority.currentText()}
        try:
            self.profiles[name]=validate_profile(values); APP_DATA.mkdir(parents=True,exist_ok=True); temp=(APP_DATA/"profiles.json").with_suffix(".tmp"); temp.write_text(json.dumps(self.profiles,indent=2),encoding="utf-8"); temp.replace(APP_DATA/"profiles.json")
            QMessageBox.information(self,"Profile saved",f"{name} profile saved locally. It will not apply until you select a game and confirm Apply.")
        except (OSError,ValueError) as e: QMessageBox.warning(self,"Could not save profile",str(e))

    def assign_game_profile(self):
        i=self.game_list.currentRow()
        if i<0 or i>=len(self.games): QMessageBox.information(self,"Choose a game","Select a saved game first."); return
        old=self.games[i].get("profile_key"); self.games[i]["profile_key"]=self.profile_key_combo.currentText()
        try: self.save_games(); self.status.setText(f"{self.games[i]['name']} uses the {self.games[i]['profile_key']} profile.")
        except OSError as e:
            if old is None: self.games[i].pop("profile_key",None)
            else: self.games[i]["profile_key"]=old
            QMessageBox.warning(self,"Could not save game profile",str(e))

    def launch_selected_game(self):
        i=self.game_list.currentRow()
        if i<0 or i>=len(self.games): QMessageBox.information(self,"Choose a game","Select a saved game first."); return
        path=Path(self.games[i]["path"])
        try:
            if not path.is_file(): raise RuntimeError("The saved executable is missing. Remove or update this library entry.")
            p=subprocess.Popen([str(path)],cwd=str(path.parent),shell=False)
            self.status.setText(f"Launched {path.name} (PID {p.pid}).")
            write_activity("Game launch",f"Launched with PID {p.pid}",details=str(path)); self.refresh_activity()
            profile={"Normal":"Medium","Below Normal":"Low","Above Normal":"High"}.get(self.games[i].get("priority"),self.games[i].get("priority","Medium"))
            if profile!="Medium": self.status.setText(f"Launched {path.name}. Apply its saved {profile} priority from Quick Tweaks → CPU Tweaks if desired.")
        except Exception as e: self.status.setText(f"Could not launch game: {e}"); write_activity("Game launch",str(e),"error",str(path)); QMessageBox.warning(self,"Could not launch game",str(e))

    def apply_game_profile(self):
        i=self.game_list.currentRow()
        if i<0 or i>=len(self.games): QMessageBox.information(self,"Choose a game","Select a saved game first."); return
        game=self.games[i]; path=os.path.normcase(os.path.abspath(game["path"])); matches=[]
        if protected_process(Path(path).name,path): QMessageBox.warning(self,"Protected process","Windows and critical processes cannot receive a game profile."); return
        for proc in psutil.process_iter(["pid","exe","create_time"]):
            try:
                exe=proc.info.get("exe")
                if exe and os.path.normcase(os.path.abspath(exe))==path: matches.append((proc.info["pid"],float(proc.info.get("create_time") or proc.create_time())))
            except (psutil.NoSuchProcess,psutil.AccessDenied,OSError,TypeError,ValueError): pass
        if len(matches)!=1:
            msg="No accessible running instance of this exact executable was found." if not matches else "More than one instance is running; select the intended process from the Processes page and change only that instance."
            QMessageBox.information(self,"Game is not uniquely running",msg); return
        pid,created=matches[0]; profile_key=game.get("profile_key",self.profile_key_combo.currentText()); profile=self.profiles.get(profile_key,validate_profile({})); label=profile["priority"] if game.get("profile_key") else game.get("priority",profile["priority"])
        label={"Normal":"Medium","Below Normal":"Low","Above Normal":"High"}.get(label,label)
        target=None if str(label).casefold()=="unchanged" else PRIORITY_VALUES.get(label)
        if target is None and str(label).casefold()!="unchanged": raise RuntimeError(f"Unsupported game-profile priority: {label}")
        plan_guid=profile["power_plan"]
        changes=[]
        if profile["game_mode"]!="unchanged": changes.append(f"Game Mode {profile['game_mode']}")
        if profile["background_capture"]!="unchanged": changes.append(f"background capture {profile['background_capture']}")
        if plan_guid!="unchanged": changes.append("selected power plan")
        if target is not None: changes.append(f"process priority {label}")
        if not changes: QMessageBox.information(self,"No profile changes selected","This profile is set to Unchanged for every supported setting."); return
        restore_note="Game Mode, capture, and power plan are restored when the process exits while Kam3 Tweaks is running, provided those values have not changed externally." if plan_guid!="unchanged" or profile["game_mode"]!="unchanged" or profile["background_capture"]!="unchanged" else ""
        if target is not None: restore_note+=(" " if restore_note else "")+"Process priority is scoped to the running process and ends when it exits."
        if not self.ask("Apply game profile?",f"Apply {profile_key} settings to {Path(path).name} (PID {pid})?\n\n"+"\n".join("• "+item for item in changes)+("\n\n"+restore_note if restore_note else "")): return
        label_tx=f"{profile_key} game profile"
        def run():
            process=psutil.Process(pid)
            if abs(process.create_time()-created)>.02: raise RuntimeError("Game ended or PID was reused; refresh and try again.")
            expected=[]
            for key,name,value in ((GAMEBAR,"AutoGameModeEnabled",profile["game_mode"]),(CAPTURE,"AppCaptureEnabled",profile["background_capture"]),(GAMECONFIG,"GameDVR_Enabled",profile["background_capture"])):
                if value=="unchanged": continue
                set_dword(self.undo,key,name,int(value=="on")); expected.append((key,name,int(value=="on")))
            old_plan=None
            if plan_guid!="unchanged":
                old_plan,title=active_plan()
                if not old_plan: raise RuntimeError(f"Could not read current power plan: {title}")
                if old_plan.casefold()!=str(plan_guid).casefold():
                    self.undo.record({"type":"power","guid":old_plan,"expected":str(plan_guid)}); code,out,err=command(["powercfg","/setactive",str(plan_guid)])
                    if code: raise RuntimeError(err or out or "Windows could not change the power plan.")
            old=process.nice()
            if target is not None and old!=target: self.undo.record({"type":"priority","pid":pid,"created":created,"old":old,"expected":target}); process.nice(target)
            return f"Applied profile {profile_key} to {Path(path).name}; global profile changes are temporary while Kam3 Tweaks monitors this running process."
        start_count=len(self.undo.items); self.finish_change(label_tx,run)
        if len(self.undo.items)>start_count:
            tx=self.undo.items[-1]; expected_reg=[]
            for key,name,_ in ((GAMEBAR,"AutoGameModeEnabled",0),(CAPTURE,"AppCaptureEnabled",0),(GAMECONFIG,"GameDVR_Enabled",0)):
                for action in tx["actions"]:
                    if action.get("type")=="reg" and action.get("key")==key and action.get("name")==name:
                        exists,val,kind=reg_read(key,name); expected_reg.append((key,name,exists,val,kind)); break
            expected_power=active_plan()[0] if plan_guid!="unchanged" else None
            self._profile_sessions[(pid,created)]={"tx":tx,"registry":expected_reg,"power_old":next((a["guid"] for a in tx["actions"] if a.get("type")=="power"),None),"power_expected":expected_power}
            # Poll only while at least one confirmed profile has temporary
            # global changes to restore. No game or sensor scan runs otherwise.
            if self._profile_sessions and not self.game_timer.isActive(): self.game_timer.start(2000)

    def cleanup_profile_sessions(self):
        if self._operation_busy: return
        if not WIN or not self._profile_sessions: return
        for identity,session in list(self._profile_sessions.items()):
            pid,created=identity
            try:
                process=psutil.Process(pid)
                if abs(process.create_time()-created)<.02: continue
            except psutil.NoSuchProcess: pass
            except (psutil.AccessDenied,OSError): continue
            tx=session["tx"]; still_needed=[]; changed=[]
            for key,name,expected_exists,expected_value,expected_kind in session["registry"]:
                try: exists,value,kind=reg_read(key,name)
                except (OSError,RuntimeError): still_needed.append((key,name)); continue
                if exists!=expected_exists or (exists and (value!=expected_value or kind!=expected_kind)):
                    changed.append(f"{key}\\{name}"); still_needed.append((key,name)); continue
                action=next((a for a in tx["actions"] if a.get("type")=="reg" and a.get("key")==key and a.get("name")==name),None)
                if not action: continue
                try:
                    if action["exists"]:
                        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_SET_VALUE) as regkey: winreg.SetValueEx(regkey,name,0,action["kind"],decode(action["value"]))
                    else:
                        try:
                            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_SET_VALUE) as regkey: winreg.DeleteValue(regkey,name)
                        except FileNotFoundError: pass
                        if not action.get("key_exists",True):
                            try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER,key)
                            except FileNotFoundError: pass
                    tx["actions"].remove(action)
                except OSError: still_needed.append((key,name))
            if session.get("power_old"):
                current=active_plan()[0]
                if current and session.get("power_expected") and current.casefold()==session["power_expected"].casefold():
                    code,out,err=command(["powercfg","/setactive",session["power_old"]])
                    if code: changed.append("power plan restore failed")
                    else:
                        action=next((a for a in tx["actions"] if a.get("type")=="power"),None)
                        if action: tx["actions"].remove(action)
                elif current and current.casefold()!=session["power_old"].casefold(): changed.append("power plan changed externally")
            tx["actions"][:]=[a for a in tx["actions"] if a.get("type")!="priority"]
            if not still_needed and not changed and not tx["actions"] and tx in self.undo.items: self.undo.items.remove(tx)
            try: self.undo.save()
            except OSError as e: self.status.setText(f"Game profile cleanup could not save Undo state: {e}")
            write_activity("Game profile cleanup","Restored temporary settings" if not changed else "Some settings changed externally or could not be restored","success" if not changed else "warning",", ".join(changed))
            del self._profile_sessions[identity]; self.refresh_undo(); self.refresh_activity()
        if not self._profile_sessions and self.game_timer.isActive(): self.game_timer.stop()

    def refresh_startup(self):
        if not hasattr(self,"startup_table"): return
        rows=[]
        for item in startup_entries():
            scope,path,name,value,kind,can_change=item; rows.append((scope,"Run registry",name,str(value),("registry",item),can_change))
        for item in startup_folder_entries():
            scope,folder,name,target,path,suffix,can_change=item; rows.append((scope,"Startup folder",name,str(path), ("shortcut",item),can_change))
        self.startup_table.setRowCount(len(rows))
        for r,(scope,location,name,value,data,can_change) in enumerate(rows):
            vals=(scope,location,name,value,"Disable available" if can_change else "Read only")
            for c,text in enumerate(vals): self.startup_table.setItem(r,c,QTableWidgetItem(str(text)))
            self.startup_table.item(r,0).setData(Qt.ItemDataRole.UserRole,data)
        self.startup_disable_btn.setEnabled(any(row[-1] for row in rows) and WIN)
        if not rows: self.startup_table.setRowCount(1); self.startup_table.setItem(0,0,QTableWidgetItem("No readable Run entries or Startup shortcuts found."))
        self.refresh_startup_profile_list()

    def disable_startup(self):
        row=self.startup_table.currentRow(); item=self.startup_table.item(row,0) if row>=0 else None; data=item.data(Qt.ItemDataRole.UserRole) if item else None
        if not data: QMessageBox.information(self,"Select a current-user entry","Only current-user Run values and user .lnk shortcuts can be disabled."); return
        kind,entry=data
        if kind=="registry":
            scope,key,name,value,reg_type,can_change=entry
            if not can_change: QMessageBox.information(self,"Read-only startup entry","All-users Run entries are read-only in Kam3 Tweaks."); return
            if not self.ask("Disable startup entry?",f"Remove {name} from the current-user Run list?\n\nCommand:\n{value}\n\nUndo restores the exact original value and type."): return
            self.finish_change("startup entry",lambda:(remove_registry_value(self.undo,key,name),f"Disabled current-user Run value {name}.")[1])
        elif kind=="shortcut":
            scope,folder,name,target,path,suffix,can_change=entry
            if not can_change: QMessageBox.information(self,"Read-only startup shortcut","All-users shortcuts and non-.lnk files are read-only here."); return
            if not self.ask("Disable Startup shortcut?",f"Move this shortcut out of the current-user Startup folder? The shortcut will be stored under %APPDATA%\\Kam3 Tweaks\\disabled_startup and can be restored with Undo.\n\n{path}\n\nTarget resolution is not performed."): return
            def move_shortcut():
                destination=disable_startup_shortcut(path,self.undo)
                return f"Disabled Startup shortcut {name}; stored at {destination.name}."
            self.finish_change("startup shortcut",move_shortcut)
        self.refresh_startup()

    def autostart_enabled(self):
        if not WIN: return False
        try:
            key=r"Software\Microsoft\Windows\CurrentVersion\Run"
            return reg_read(key,"Kam3Tweaks")[0] or reg_read(key,"PCBoost")[0]
        except OSError: return False

    def toggle_autostart(self,state):
        enabled=bool(state)
        if not WIN:
            self.autostart.blockSignals(True); self.autostart.setChecked(False); self.autostart.blockSignals(False); return
        if not self.ask("Change Windows startup?",("Add Kam3 Tweaks to your current-user startup list? It will run only after you sign in." if enabled else "Remove Kam3 Tweaks startup entries, including a legacy PCBoost entry if present?")):
            self.autostart.blockSignals(True); self.autostart.setChecked(not enabled); self.autostart.blockSignals(False); return
        key=r"Software\Microsoft\Windows\CurrentVersion\Run"
        if enabled:
            exe=Path(sys.executable).resolve()
            if getattr(sys,"frozen",False): value=f'"{exe}"'
            else: value=f'"{exe}" "{Path(__file__).resolve()}"'
            self.finish_change("Kam3 Tweaks startup",lambda:(set_registry_value(self.undo,key,"Kam3Tweaks",value,winreg.REG_SZ),"Kam3 Tweaks will start when you sign in.")[1])
        else:
            def remove_startup_entries():
                removed=[]
                for value_name in ("Kam3Tweaks","PCBoost"):
                    if reg_read(key,value_name)[0]: remove_registry_value(self.undo,key,value_name); removed.append(value_name)
                return "Removed startup entries: " + (", ".join(removed) if removed else "none")
            self.finish_change("Kam3 Tweaks startup",remove_startup_entries)
        self.autostart.blockSignals(True); self.autostart.setChecked(self.autostart_enabled()); self.autostart.blockSignals(False)



    def scan_storage(self):
        if self._storage_thread and self._storage_thread.is_alive(): return
        selected=QFileDialog.getExistingDirectory(self,"Choose a folder for a read-only large-file scan",str(Path.home()))
        if not selected: return
        root=Path(selected)
        if link(root) or not root.is_dir(): QMessageBox.warning(self,"Invalid scan folder","Choose an existing folder that is not a link or junction."); return
        self.storage_btn.setEnabled(False); self.storage_status.setText("Scanning up to 100,000 files in the selected folder…")
        self.storage_signals=StorageSignals(); self.storage_signals.finished.connect(self.storage_scan_done)
        def worker():
            rows=[]; errors=[]; scanned=0; truncated=False
            try:
                for current,dirs,files in os.walk(root,followlinks=False):
                    base=Path(current); dirs[:]=[d for d in dirs if not link(base/d)]
                    for name in files:
                        fp=base/name
                        if link(fp): continue
                        try:
                            st=fp.stat(follow_symlinks=False); scanned+=1
                            if st.st_size>=256*1024**2: rows.append((str(fp),st.st_size))
                        except OSError: continue
                        if scanned>=100000: truncated=True; break
                    if truncated: break
            except OSError as e: errors.append(str(e))
            rows=sorted(rows,key=lambda row:row[1],reverse=True)[:100]
            note=f"Scanned {scanned:,} files · showing up to 100 files at least 256 MB · read-only."
            if truncated: note+=" Scan limit reached; results may be incomplete."
            if errors: note+=" Some folders could not be read: "+"; ".join(errors[:3])
            self.storage_signals.finished.emit(rows,note)
        self._storage_thread=threading.Thread(target=worker,daemon=True); self._storage_thread.start()

    def storage_scan_done(self,rows,summary):
        self.storage_btn.setEnabled(True)
        self.storage_table.setRowCount(len(rows))
        for row,(path,size) in enumerate(rows):
            self.storage_table.setItem(row,0,QTableWidgetItem(f"{size/1024**3:.2f} GB")); self.storage_table.setItem(row,1,QTableWidgetItem(Path(path).name)); self.storage_table.setItem(row,2,QTableWidgetItem(str(Path(path).parent)))
            self.storage_table.item(row,1).setData(Qt.ItemDataRole.UserRole,path)
        self.storage_status.setText(summary+("\nNo files at least 256 MB were found." if not rows else "")); write_activity("Large-file scan","Read-only folder scan completed",details=summary)

    def storage_open_selected(self):
        row=self.storage_table.currentRow() if hasattr(self,"storage_table") else -1
        item=self.storage_table.item(row,1) if row>=0 else None; path=item.data(Qt.ItemDataRole.UserRole) if item else None
        if not path: QMessageBox.information(self,"Choose a file","Select a result first."); return
        try:
            folder=Path(path).parent
            if not folder.is_dir(): raise FileNotFoundError("The result folder no longer exists.")
            os.startfile(str(folder)); self.status.setText("Opened the selected file's folder. No file was changed.")
        except (OSError,AttributeError) as e: QMessageBox.warning(self,"Could not open folder",str(e))





    def refresh_activity(self):
        if not hasattr(self,"activity_table"): return
        rows=[]
        try:
            for line in activity_file().read_text(encoding="utf-8").splitlines()[-1000:]:
                try: rows.append(json.loads(line))
                except ValueError: continue
        except OSError: pass
        self._activity_rows=rows; self.activity_table.setRowCount(len(rows))
        for r,item in enumerate(rows):
            vals=(item.get("timestamp",""),item.get("action",""),f"{item.get('status','')}: {item.get('result','')}",item.get("details",""))
            for c,value in enumerate(vals): self.activity_table.setItem(r,c,QTableWidgetItem(str(value)))

    def export_activity(self):
        path,_=QFileDialog.getSaveFileName(self,"Export activity log",str(Path.home()/"Kam3Tweaks-activity.csv"),"CSV files (*.csv)")
        if not path: return
        records=[]
        try:
            for line in activity_file().read_text(encoding="utf-8").splitlines():
                try: records.append(json.loads(line))
                except ValueError: continue
        except OSError: pass
        try:
            with open(path,"w",newline="",encoding="utf-8-sig") as f:
                writer=csv.DictWriter(f,fieldnames=["timestamp","action","status","result","details"]); writer.writeheader(); writer.writerows(records)
            QMessageBox.information(self,"Export complete",f"Exported {len(records)} activity entries.")
        except OSError as e: QMessageBox.warning(self,"Export failed",str(e))


def main():
    app=QApplication(sys.argv); app.setApplicationName(APP_NAME); app.setOrganizationName("Kam3")
    app.setStyleSheet(STYLE); app.setFont(QFont("Inter",10))
    icon_path=APP_DIR/"Kam3Tweaks.ico"
    if icon_path.exists(): app.setWindowIcon(QIcon(str(icon_path)))
    w=Window()
    if "--smoke-test" in sys.argv:
        expected_key_hash=next((arg.split("=",1)[1] for arg in sys.argv if arg.startswith("--expected-public-key-sha256=")),"")
        expected=["Home","Quick Tweaks","Optimizations","Gaming","Network","Cleanup","Settings"]
        expected_quick=["Windows Tweaks","Startup Tweaks","CPU Tweaks","GPU Tweaks","NVIDIA Tweaks","AMD Tweaks","Intel Tweaks"]
        if (w.windowTitle()!=APP_NAME or w.windowIcon().isNull() or len(w.pages)!=7 or
            w.PAGE_NAMES!=expected or len(w.nav_buttons)!=7 or
            APP_VERSION!="4.7.0" or not verification_ready() or
            (expected_key_hash and pinned_key_fingerprint()!=expected_key_hash) or
            [w.quick_tabs.tabText(i) for i in range(w.quick_tabs.count())]!=expected_quick or
            set(w.quick_category_cards)!=set(expected_quick) or
            w.activity_table is None or w.theme_combo is None or
            not hasattr(w,"update_now_btn") or not hasattr(w,"update_install_btn") or
            any(not hasattr(w,name) for name in ("custom_profile_combo","custom_profile_create_btn","custom_profile_apply_btn","custom_profile_undo_btn","builtin_preset_combo","preset_apply_btn","preset_undo_btn"))): return 2
        w.show(); app.processEvents()
        for width,height in ((900,620),(1280,720),(1920,1080)):
            w.resize(width,height)
            for page in (0,1):
                w.select_page(page)
                for _ in range(5): app.processEvents()
                if w.stack.currentWidget().horizontalScrollBar().maximum()!=0:
                    w.close(); return 3
        for index in range(7):
            w.select_page(index); app.processEvents()
            if w.stack.currentIndex()!=index:
                w.close(); return 4
        if w.quick_grid.columns!=2 or bool(w.category_transactions("Power Tweaks"))!=w.power_undo_btn.isEnabled() or w._operation_busy:
            w.close(); return 5
        w.close(); return 0
    w.show()
    health_token=next((arg.split("=",1)[1] for arg in sys.argv if arg.startswith("--update-health=")),"")
    if health_token:
        write_startup_health(APP_DATA,health_token,APP_VERSION,data_accessible=APP_DATA.is_dir())
        poll=QTimer(w); poll.setInterval(500); poll.timeout.connect(w.check_update_result); poll.start()
        QTimer.singleShot(15000,poll.stop)
    return app.exec()

if __name__=="__main__": raise SystemExit(main())
