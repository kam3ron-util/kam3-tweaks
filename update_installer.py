"""Portable, fail-closed installer primitives used by Kam3TweaksUpdater.exe."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from update_security import (APPLICATION_ID, EXPECTED_EXECUTABLE, UpdateVerificationError,
                             EXPECTED_UPDATER, stable_version, verify_executable,
                             verify_manifest, verify_updater)

REQUEST_SCHEMA = 1
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


class InstallationError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def acquire_update_lock(app_data_dir: Path) -> tuple[Path,str]:
    """Serialize concurrent helper requests and clear only provably stale locks."""
    lock=app_data_dir/"update"/"install.lock"
    lock.parent.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex
    for _ in range(2):
        try:
            with lock.open("x",encoding="utf-8") as stream:
                json.dump({"token":token,"pid":os.getpid()},stream)
                stream.flush(); os.fsync(stream.fileno())
            return lock,token
        except FileExistsError:
            try:
                state=json.loads(lock.read_text(encoding="utf-8"))
                pid=state.get("pid")
                if not isinstance(pid,int) or pid<=0: raise InstallationError("An updater lock exists but cannot be validated; it was left untouched.")
                import psutil
                if psutil.pid_exists(pid): raise InstallationError("Another Kam3 Tweaks update is already running.")
                lock.unlink()
            except InstallationError:
                raise
            except (OSError,ValueError,ImportError) as exc:
                raise InstallationError("An updater lock could not be checked safely; it was left untouched.") from exc
    raise InstallationError("Another Kam3 Tweaks update is already running.")


def release_update_lock(lock: Path | None, token: str | None) -> None:
    if not lock or not token: return
    try:
        state=json.loads(lock.read_text(encoding="utf-8"))
        if state.get("token")==token: lock.unlink()
    except (OSError,ValueError): pass


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(parent.resolve(strict=True))
        return True
    except (ValueError, OSError):
        return False


def windows_file_metadata(path: str | Path) -> dict:
    """Read version-resource strings and file version through Windows APIs."""
    if os.name != "nt":
        raise InstallationError("Windows executable metadata is only available on Windows.")
    path = str(Path(path).resolve())
    ctypes = __import__("ctypes")
    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint)]
    version.GetFileVersionInfoSizeW.restype = ctypes.c_uint
    version.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = ctypes.c_bool
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    version.VerQueryValueW.restype = ctypes.c_bool
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        raise InstallationError("Windows could not read the executable's version metadata.")
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, buffer):
        raise InstallationError("Windows could not read the executable's version resource.")

    def query(subblock: str):
        value = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not version.VerQueryValueW(buffer, subblock, ctypes.byref(value), ctypes.byref(length)):
            return ""
        return ctypes.wstring_at(value.value, max(0, length.value - 1))

    strings = {key: query("\\StringFileInfo\\040904B0\\" + key) for key in
               ("ProductName", "OriginalFilename", "ProductVersion", "FileVersion")}
    if not strings["FileVersion"]:
        raise InstallationError("The executable has no readable file version.")
    return strings


def validate_application_file(path: str | Path, metadata_reader: Callable = windows_file_metadata, *, allow_backup: bool = False) -> dict:
    path = Path(path)
    if (not allow_backup and path.name.casefold() != EXPECTED_EXECUTABLE.casefold()) or not path.is_file():
        raise InstallationError("The selected target is not an existing Kam3Tweaks.exe.")
    metadata = metadata_reader(path)
    if (metadata.get("ProductName") != "Kam3 Tweaks" or
            metadata.get("OriginalFilename", "").casefold() != EXPECTED_EXECUTABLE.casefold()):
        raise InstallationError("Target executable metadata does not identify Kam3 Tweaks.")
    try:
        raw_version=metadata.get("ProductVersion") or metadata.get("FileVersion","")
        match=re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?",str(raw_version))
        if not match: raise UpdateVerificationError("Version resource is not a stable application version.")
        metadata["parsed_version"]=tuple(int(part) if part is not None else 0 for part in match.groups())
    except UpdateVerificationError as exc:
        raise InstallationError("Target executable version metadata is invalid.") from exc
    return metadata


def validate_updater_file(path: str | Path, metadata_reader: Callable = windows_file_metadata, *, allow_backup: bool = False) -> dict:
    path=Path(path)
    if (not allow_backup and path.name.casefold()!=EXPECTED_UPDATER.casefold()) or not path.is_file():
        raise InstallationError("Trusted updater helper is missing or has an unexpected filename.")
    metadata=metadata_reader(path)
    if metadata.get("ProductName")!="Kam3 Tweaks" or metadata.get("OriginalFilename","").casefold()!=EXPECTED_UPDATER.casefold():
        raise InstallationError("Updater helper metadata does not identify Kam3 Tweaks Updater.")
    try:
        raw_version=metadata.get("ProductVersion") or metadata.get("FileVersion","")
        match=re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?",str(raw_version))
        if not match: raise UpdateVerificationError("Invalid updater version metadata")
        metadata["parsed_version"]=tuple(int(part) if part is not None else 0 for part in match.groups())
    except UpdateVerificationError as exc:
        raise InstallationError("Updater helper version metadata is invalid.") from exc
    return metadata


def create_install_request(verified_update: dict, *, installed_version: str, parent_pid: int,
                           install_dir: str | Path,
                           staging_root: str | Path) -> Path:
    """Persist a helper request containing only staged paths and signed release data."""
    folder = Path(verified_update["directory"]).resolve(strict=True)
    root = Path(staging_root).resolve(strict=True)
    if not _within(folder, root) or folder.parent != root:
        raise InstallationError("Verified update staging directory is outside the private update cache.")
    release = verified_update.get("release")
    if not isinstance(release, dict):
        raise InstallationError("Verified release metadata is missing.")
    request = {"schema": REQUEST_SCHEMA, "application_id": APPLICATION_ID,
               "stage_dir": str(folder), "installed_version": installed_version,
               "install_dir": str(Path(install_dir).resolve(strict=True)),
               "parent_pid": int(parent_pid), "release": release,
               "health_token": uuid.uuid4().hex}
    path = folder / "install-request.json"
    atomic_json(path, request)
    return path


def _load_request(request_path: str | Path, staging_root: Path) -> dict:
    path = Path(request_path).resolve(strict=True)
    try:
        if path.name != "install-request.json" or not _within(path, staging_root):
            raise InstallationError("Updater request is outside the private update cache.")
        if path.stat().st_size > 256 * 1024:
            raise InstallationError("Updater request is too large.")
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if isinstance(exc, InstallationError):
            raise
        raise InstallationError("Updater request is missing or malformed.") from exc
    required = {"schema", "application_id", "stage_dir", "installed_version", "install_dir", "parent_pid", "release", "health_token"}
    if not isinstance(request, dict) or set(request) != required:
        raise InstallationError("Updater request fields are invalid.")
    if request["schema"] != REQUEST_SCHEMA or request["application_id"] != APPLICATION_ID:
        raise InstallationError("Updater request belongs to another application or schema.")
    if not isinstance(request["parent_pid"], int) or request["parent_pid"] <= 0:
        raise InstallationError("Updater parent process identity is invalid.")
    if not isinstance(request["health_token"], str) or not _TOKEN.fullmatch(request["health_token"]):
        raise InstallationError("Updater health token is invalid.")
    folder = Path(request["stage_dir"]).resolve(strict=True)
    if not _within(folder, staging_root) or folder.parent != staging_root:
        raise InstallationError("Staged update is outside the private update cache.")
    if path.parent != folder:
        raise InstallationError("Updater request is not located beside the staged files.")
    if not isinstance(request["install_dir"],str) or not Path(request["install_dir"]).is_absolute():
        raise InstallationError("Updater target directory is invalid.")
    return request


def wait_for_application_exit(target: Path, parent_pid: int, timeout: float = 180.0,
                              *, process_iter=None, sleep=time.sleep) -> bool:
    """Wait for every process executing this exact target path; never terminate it."""
    if process_iter is None:
        import psutil
        process_iter = psutil.process_iter
    target_key = os.path.normcase(str(target.resolve()))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        still_running = False
        try:
            for process in process_iter(["pid", "exe"]):
                try:
                    exe = process.info.get("exe")
                    if exe and os.path.normcase(str(Path(exe).resolve())) == target_key:
                        still_running = True
                        break
                except (OSError, PermissionError, AttributeError):
                    continue
        except Exception:
            return False
        if not still_running:
            return True
        sleep(min(0.25, max(0, deadline - time.monotonic())))
    return False


def _health_path(app_data_dir: Path, token: str) -> Path:
    if not _TOKEN.fullmatch(token):
        raise InstallationError("Invalid health-check token.")
    return app_data_dir / "update" / f"health_{token}.json"


def wait_for_health(app_data_dir: str | Path, token: str, version: str, process,
                    timeout: float = 35.0, *, sleep=time.sleep) -> bool:
    health = _health_path(Path(app_data_dir), token)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = json.loads(health.read_text(encoding="utf-8"))
            if state.get("token") == token and state.get("version") == version and state.get("startup_complete") is True and state.get("data_accessible") is True:
                return True
        except (OSError, ValueError):
            pass
        if process is not None and process.poll() is not None:
            return False
        sleep(0.25)
    return False


def write_startup_health(app_data_dir: str | Path, token: str, version: str,
                         *, data_accessible: bool = True) -> bool:
    if not _TOKEN.fullmatch(token):
        return False
    try:
        atomic_json(_health_path(Path(app_data_dir), token),
                    {"token": token, "version": version,
                     "startup_complete": True, "data_accessible": bool(data_accessible),
                     "timestamp": datetime.now(timezone.utc).isoformat()})
        return True
    except OSError:
        return False


def _launch_updated(target: Path, token: str):
    return subprocess.Popen([str(target), f"--update-health={token}"], cwd=str(target.parent),
                            close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _close_owned_process(process, timeout: float = 6.0) -> bool:
    if process is None or process.poll() is not None:
        return True
    if os.name == "nt":
        try:
            import ctypes
            WM_CLOSE = 0x0010
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            pid = process.pid
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def callback(hwnd, _):
                found = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(found))
                if found.value == pid:
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return True
            user32.EnumWindows(callback_type(callback), 0)
        except Exception:
            pass
    try:
        process.wait(timeout=timeout)
        return True
    except Exception:
        # This process was created by this helper. It is never an unrelated app.
        try:
            process.terminate()
            process.wait(timeout=3)
            return True
        except Exception:
            return False


def _write_result(app_data_dir: Path, status: str, version: str, details: str = "", token: str = "") -> None:
    atomic_json(app_data_dir / "update" / "result.json",
                {"status": status, "version": version, "details": details,
                 "token": token if _TOKEN.fullmatch(token) else "",
                 "timestamp": datetime.now(timezone.utc).isoformat()})


def perform_install(request_path: str | Path, *, helper_dir: str | Path,
                    app_data_dir: str | Path, public_key_b64: str | None = None,
                    metadata_reader: Callable = windows_file_metadata,
                    updater_metadata_reader: Callable = windows_file_metadata,
                    helper_binary_path: str | Path | None = None,
                    wait_exit: Callable = wait_for_application_exit,
                    launch: Callable = _launch_updated,
                    health_check: Callable = wait_for_health,
                    sleep=time.sleep) -> dict:
    """Verify, backup, replace, relaunch, health-check and rollback if needed."""
    app_data_dir = Path(app_data_dir).resolve()
    rollback_completed = False
    lock_path=None; lock_token=None
    staging_root = (app_data_dir / "update-staging")
    try:
        lock_path,lock_token=acquire_update_lock(app_data_dir)
        request = _load_request(request_path, staging_root)
        folder = Path(request["stage_dir"])
        requested_dir=Path(request["install_dir"]).resolve(strict=True)
        if Path(helper_dir).resolve(strict=True)!=requested_dir:
            raise InstallationError("Updater target folder no longer matches the approved application folder.")
        helper_dir=requested_dir
        release = request["release"]
        manifest_bytes = (folder / "update-manifest.json").read_bytes()
        signature_bytes = (folder / "update-manifest.sig").read_bytes()
        from update_security import current_architecture
        manifest = verify_manifest(manifest_bytes, signature_bytes, release, public_key_b64,
                                   architecture=current_architecture(),
                                   installed_version=request["installed_version"])
        staged_exe = folder / EXPECTED_EXECUTABLE
        verify_executable(staged_exe, manifest)
        staged_updater=folder/EXPECTED_UPDATER
        verify_updater(staged_updater,manifest)
        running_helper=Path(helper_binary_path or sys.executable).resolve(strict=True)
        verify_updater(running_helper,manifest)
        new_metadata = validate_application_file(staged_exe, metadata_reader)
        new_updater_metadata=validate_updater_file(staged_updater,updater_metadata_reader)
        if new_metadata["parsed_version"] != stable_version(manifest["version"]):
            raise InstallationError("Staged executable version does not match its signed manifest.")
        if new_updater_metadata["parsed_version"]!=stable_version(manifest["version"]):
            raise InstallationError("Staged updater helper version does not match its signed manifest.")

        helper_dir = Path(helper_dir).resolve(strict=True)
        target = helper_dir / EXPECTED_EXECUTABLE
        old_metadata = validate_application_file(target, metadata_reader)
        target_updater=helper_dir/EXPECTED_UPDATER
        old_updater_metadata=validate_updater_file(target_updater,updater_metadata_reader)
        # Windows version resources normally carry a fourth build component
        # (for example, 4.5.0.0). validate_application_file has already
        # normalized that metadata to a four-part parsed_version tuple.
        old_version = ".".join(str(part) for part in old_metadata["parsed_version"])
        if old_metadata["parsed_version"] != stable_version(request["installed_version"]):
            raise InstallationError("Installed version changed after the update was prepared. Check again before updating.")
        if old_updater_metadata["parsed_version"]!=stable_version(request["installed_version"]):
            raise InstallationError("Installed updater helper version does not match the application. Use the manual release package.")
        if not wait_exit(target, request["parent_pid"]):
            raise InstallationError("Kam3 Tweaks is still open. Close it normally and retry; no process was stopped.")

        backup_dir = helper_dir / "backup"
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix=uuid.uuid4().hex[:8]
        backup = backup_dir / f"Kam3Tweaks_pre_{old_version}_{timestamp}_{suffix}.exe"
        updater_backup=backup_dir/f"Kam3TweaksUpdater_pre_{old_version}_{timestamp}_{suffix}.exe"
        journal_path = app_data_dir / "update" / "install_journal.json"
        journal = {"schema": 1, "application_id": APPLICATION_ID, "state": "prepared",
                   "target": str(target), "backup": str(backup),
                   "updater_target":str(target_updater),"updater_backup":str(updater_backup),"stage_dir": str(folder),
                   "old_version": old_version, "new_version": manifest["version"],
                   "new_sha256": manifest["sha256"], "new_updater_sha256":manifest["updater_sha256"],
                   "token": request["health_token"]}
        shutil.copy2(target, backup)
        if sha256_file(backup) != sha256_file(target):
            backup.unlink(missing_ok=True)
            raise InstallationError("Previous executable backup could not be verified; installation was canceled.")
        shutil.copy2(target_updater,updater_backup)
        if sha256_file(updater_backup)!=sha256_file(target_updater):
            raise InstallationError("Previous updater helper backup could not be verified; installation was canceled.")
        journal["old_sha256"]=sha256_file(backup)
        journal["old_updater_sha256"]=sha256_file(updater_backup)
        atomic_json(journal_path, journal)
        temporary = helper_dir / f".Kam3Tweaks.update-{uuid.uuid4().hex}.tmp"
        updater_temporary=helper_dir/f".Kam3TweaksUpdater.update-{uuid.uuid4().hex}.tmp"
        replaced = False
        updater_replaced=False
        try:
            with staged_exe.open("rb") as source, temporary.open("xb") as destination:
                shutil.copyfileobj(source, destination, 1024 * 1024)
                destination.flush()
                os.fsync(destination.fileno())
            verify_executable(temporary, manifest)
            with staged_updater.open("rb") as source,updater_temporary.open("xb") as destination:
                shutil.copyfileobj(source,destination,1024*1024); destination.flush(); os.fsync(destination.fileno())
            if updater_temporary.stat().st_size!=manifest["updater_size"] or sha256_file(updater_temporary)!=manifest["updater_sha256"]:
                raise InstallationError("Updater helper copy did not match the signed manifest.")
            # Detect a change to the existing EXE between backup and replacement.
            if sha256_file(target) != sha256_file(backup):
                raise InstallationError("Installed executable changed during preparation; no replacement was made.")
            journal["state"] = "installing"
            atomic_json(journal_path, journal)
            os.replace(temporary, target)
            replaced = True
            os.replace(updater_temporary,target_updater)
            updater_replaced=True
            journal["state"] = "installed_waiting_health"
            atomic_json(journal_path, journal)
            installed_metadata = validate_application_file(target, metadata_reader)
            installed_updater_metadata=validate_updater_file(target_updater,updater_metadata_reader)
            if installed_metadata["parsed_version"] != stable_version(manifest["version"]):
                raise InstallationError("Replaced executable metadata does not match the signed version.")
            if installed_updater_metadata["parsed_version"]!=stable_version(manifest["version"]):
                raise InstallationError("Replaced updater helper metadata does not match the signed version.")
            process = launch(target, request["health_token"])
            if not health_check(app_data_dir, request["health_token"], manifest["version"], process):
                if not _close_owned_process(process):
                    raise InstallationError("New version failed its startup check and could not be closed safely; the recovery backup and journal were preserved.")
                raise InstallationError("New version did not complete its startup check.")
            journal["state"] = "complete"
            journal["completed_at"] = datetime.now(timezone.utc).isoformat()
            atomic_json(journal_path, journal)
            _write_result(app_data_dir, "success", manifest["version"], token=request["health_token"])
            journal_path.unlink(missing_ok=True)
            shutil.rmtree(folder, ignore_errors=True)
            return {"ok": True, "version": manifest["version"], "backup": str(backup),"updater_backup":str(updater_backup)}
        except Exception:
            temporary.unlink(missing_ok=True)
            updater_temporary.unlink(missing_ok=True)
            if replaced:
                rollback_temp = helper_dir / f".Kam3Tweaks.rollback-{uuid.uuid4().hex}.tmp"
                updater_rollback_temp=helper_dir/f".Kam3TweaksUpdater.rollback-{uuid.uuid4().hex}.tmp"
                try:
                    shutil.copy2(backup, rollback_temp)
                    if sha256_file(rollback_temp) != sha256_file(backup):
                        raise OSError("backup copy verification failed")
                    if updater_replaced:
                        shutil.copy2(updater_backup,updater_rollback_temp)
                        if sha256_file(updater_rollback_temp)!=sha256_file(updater_backup): raise OSError("updater backup copy verification failed")
                        os.replace(updater_rollback_temp,target_updater)
                    os.replace(rollback_temp, target)
                    journal["state"] = "rolled_back"
                    atomic_json(journal_path, journal)
                    _write_result(app_data_dir, "rolled_back", old_version,
                                  "The update did not pass its startup check. The previous version was restored.",
                                  token=request["health_token"])
                    rollback_completed = True
                except Exception as rollback_error:
                    updater_rollback_temp.unlink(missing_ok=True)
                    rollback_temp.unlink(missing_ok=True)
                    journal["state"] = "recovery_required"
                    journal["failure"] = str(rollback_error)[:500]
                    try:
                        atomic_json(journal_path, journal)
                    except OSError:
                        pass
                    raise InstallationError("Update failed and automatic rollback could not finish. The previous executable backup and recovery journal were preserved.") from rollback_error
            raise
    except Exception as exc:
        if not rollback_completed:
            try:
                token = request.get("health_token", "") if "request" in locals() and isinstance(request, dict) else ""
                _write_result(app_data_dir, "failed", "", str(exc)[:500], token=token)
            except OSError:
                pass
        return {"ok": False, "error": str(exc)}
    finally:
        release_update_lock(lock_path,lock_token)


def recover_interrupted_install(journal_path: str | Path, *, helper_dir: str | Path,
                                metadata_reader: Callable = windows_file_metadata,
                                updater_metadata_reader: Callable = windows_file_metadata,
                                parent_pid: int | None = None,
                                wait_exit: Callable = wait_for_application_exit,
                                launch: Callable | None = None) -> dict:
    """Restore only a journaled Kam3 Tweaks executable from its verified backup."""
    lock_path=None; lock_token=None
    try:
        journal_path = Path(journal_path).resolve(strict=True)
        lock_path,lock_token=acquire_update_lock(journal_path.parent.parent)
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        helper_dir = Path(helper_dir).resolve(strict=True)
        target = helper_dir / EXPECTED_EXECUTABLE
        if journal.get("application_id") != APPLICATION_ID or Path(journal.get("target", "")).resolve() != target:
            raise InstallationError("Recovery journal target does not match this Kam3 Tweaks folder.")
        backup_dir = (helper_dir / "backup").resolve(strict=True)
        backup = Path(journal.get("backup", "")).resolve(strict=True)
        if not _within(backup, backup_dir) or backup.parent != backup_dir or not backup.name.startswith("Kam3Tweaks_pre_"):
            raise InstallationError("Recovery backup path is outside Kam3 Tweaks backup storage.")
        validate_application_file(backup, metadata_reader, allow_backup=True)
        if journal.get("old_sha256") and sha256_file(backup)!=journal.get("old_sha256"):
            raise InstallationError("Previous executable backup checksum changed; recovery was canceled.")
        if target.exists():
            validate_application_file(target, metadata_reader)
            current_hash=sha256_file(target)
            allowed={journal.get("old_sha256"),journal.get("new_sha256")}-{None}
            if allowed and current_hash not in allowed:
                raise InstallationError("Kam3 Tweaks executable changed after the interrupted update; recovery will not overwrite it.")
        updater_target=helper_dir/EXPECTED_UPDATER
        updater_backup_value=journal.get("updater_backup")
        updater_backup=None
        if updater_backup_value:
            updater_backup=Path(updater_backup_value).resolve(strict=True)
            if not _within(updater_backup,backup_dir) or updater_backup.parent!=backup_dir or not updater_backup.name.startswith("Kam3TweaksUpdater_pre_"):
                raise InstallationError("Recovery updater backup path is outside Kam3 Tweaks backup storage.")
            validate_updater_file(updater_backup,updater_metadata_reader,allow_backup=True)
            if journal.get("old_updater_sha256") and sha256_file(updater_backup)!=journal.get("old_updater_sha256"):
                raise InstallationError("Previous updater backup checksum changed; recovery was canceled.")
            if updater_target.exists():
                current_updater_hash=sha256_file(updater_target)
                updater_allowed={journal.get("old_updater_sha256"),journal.get("new_updater_sha256")}-{None}
                if updater_allowed and current_updater_hash not in updater_allowed:
                    raise InstallationError("Kam3 Tweaks updater changed after the interrupted update; recovery will not overwrite it.")
        if parent_pid is not None and not wait_exit(target,parent_pid):
            raise InstallationError("Kam3 Tweaks is still open. Close it normally before recovery; no process was stopped.")
        if parent_pid is None and not wait_exit(target,0,timeout=0.01):
            raise InstallationError("Kam3 Tweaks appears to be running. Close it normally before recovery.")
        recovery_temp = helper_dir / f".Kam3Tweaks.recovery-{uuid.uuid4().hex}.tmp"
        shutil.copy2(backup, recovery_temp)
        if sha256_file(recovery_temp) != sha256_file(backup):
            recovery_temp.unlink(missing_ok=True)
            raise InstallationError("Recovery backup copy did not verify.")
        if updater_backup:
            updater_recovery_temp=helper_dir/f".Kam3TweaksUpdater.recovery-{uuid.uuid4().hex}.tmp"
            shutil.copy2(updater_backup,updater_recovery_temp)
            if sha256_file(updater_recovery_temp)!=sha256_file(updater_backup):
                updater_recovery_temp.unlink(missing_ok=True); recovery_temp.unlink(missing_ok=True)
                raise InstallationError("Recovery updater backup copy did not verify.")
            os.replace(updater_recovery_temp,updater_target)
        os.replace(recovery_temp, target)
        restored=validate_application_file(target,metadata_reader)
        if launch:
            launch(target,journal.get("token",""))
        _write_result(journal_path.parent.parent,"rolled_back",restored.get("ProductVersion",""),
                      "Kam3 Tweaks restored the previous version from its verified local backup.",
                      token=journal.get("token",""))
        journal_path.unlink(missing_ok=True)
        return {"ok": True, "target": str(target), "restored_version": restored.get("ProductVersion")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        release_update_lock(lock_path,lock_token)
