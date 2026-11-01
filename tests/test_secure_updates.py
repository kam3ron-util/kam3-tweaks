import base64
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import github_updates
import update_download
import update_installer
import update_security
import updater_helper
from tools import release_sign
from tools import verify_signing_key
from update_security import (APPLICATION_ID, PUBLISHER_ID, canonical_manifest_bytes,
                             UpdateVerificationError, VerificationUnavailable)


class FakeResponse:
    status = 200
    def __init__(self, data=b"", final_url=None, headers=None, chunks=None):
        self.data=data; self.final_url=final_url; self.headers=headers or {}
        self.chunks=list(chunks) if chunks is not None else None; self.closed=False
    def read(self, size=-1):
        if self.chunks is not None:
            return self.chunks.pop(0) if self.chunks else b""
        if not self.data: return b""
        if size is None or size < 0:
            out,self.data=self.data,b""
            return out
        out,self.data=self.data[:size],self.data[size:]
        return out
    def geturl(self): return self.final_url or "https://github.com/kam3ron-util/kam3-tweaks/releases/download/v4.6.1/asset"
    def close(self): self.closed=True
    def __enter__(self): return self
    def __exit__(self,*_): self.close(); return False


def fake_pe(payload):
    data=bytearray(128); data[:2]=b"MZ"; struct.pack_into("<I",data,0x3c,0x80)
    data.extend(b"PE\0\0"+struct.pack("<H",0x8664)+b"\0"*24+payload)
    return bytes(data)


def fixture_release(executable=b"harmless test app payload", *, updater=b"harmless test updater payload", version="4.6.1", release_id=461):
    executable=fake_pe(executable); updater=fake_pe(updater)
    private=Ed25519PrivateKey.generate()
    public=base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw,
        serialization.PublicFormat.Raw)).decode("ascii")
    digest=hashlib.sha256(executable).hexdigest()
    manifest={"schema_version":1,"application_id":APPLICATION_ID,"publisher_id":PUBLISHER_ID,
        "version":version,"channel":"stable","architecture":"x64",
        "minimum_windows_version":"10.0.19041","minimum_application_version":"4.5.0",
        "executable_filename":"Kam3Tweaks.exe","executable_size":len(executable),
        "sha256":digest,"updater_filename":"Kam3TweaksUpdater.exe","updater_size":len(updater),
        "updater_sha256":hashlib.sha256(updater).hexdigest(),"release_id":release_id,"published_at":"2026-10-31T12:00:00Z",
        "restart_required":True}
    signature=base64.b64encode(private.sign(canonical_manifest_bytes(manifest)))
    tag="v"+version
    names={"Kam3Tweaks.exe":executable,"Kam3TweaksUpdater.exe":updater,
           "update-manifest.json":json.dumps(manifest,sort_keys=True,separators=(",",":")).encode(),
           "update-manifest.sig":signature}
    assets=[]
    for name,data in names.items():
        url=f"https://github.com/kam3ron-util/kam3-tweaks/releases/download/{tag}/{name}"
        assets.append({"name":name,"url":url,"api_url":f"https://api.github.com/repos/kam3ron-util/kam3-tweaks/releases/assets/{len(assets)+1}",
                       "size":len(data),"id":len(assets)+1,"state":"uploaded"})
    release={"repository":"kam3ron-util/kam3-tweaks","id":release_id,"tag":tag,
        "url":f"https://github.com/kam3ron-util/kam3-tweaks/releases/tag/{tag}",
        "published_at":"2026-10-31T12:00:00Z","draft":False,"prerelease":False,
        "assets":assets,"notes":"test release notes"}
    return {"private":private,"public":public,"manifest":manifest,"signature":signature,
            "exe":executable,"updater":updater,"names":names,"release":release}


class UpdateSecurityTests(unittest.TestCase):
    def setUp(self): self.fx=fixture_release()
    def verify(self, manifest=None, signature=None, release=None, public=None, **kwargs):
        return update_security.verify_manifest(
            json.dumps(manifest or self.fx["manifest"],sort_keys=True,separators=(",",":")).encode(),
            signature or self.fx["signature"],release or self.fx["release"],
            public or self.fx["public"],architecture="x64",**kwargs)

    def test_valid_signed_update_and_sha256(self):
        parsed=self.verify(installed_version="4.5.0")
        self.assertEqual(parsed["version"],"4.6.1")
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/"Kam3Tweaks.exe"; exe.write_bytes(self.fx["exe"])
            self.assertEqual(update_security.verify_executable(exe,parsed),self.fx["manifest"]["sha256"])
            helper=Path(temp)/"Kam3TweaksUpdater.exe"; helper.write_bytes(self.fx["updater"])
            self.assertEqual(update_security.verify_updater(helper,parsed),self.fx["manifest"]["updater_sha256"])

    def test_modified_executable_and_wrong_signed_sha256_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/"Kam3Tweaks.exe"
            modified=bytearray(self.fx["exe"]); modified[0]^=1; exe.write_bytes(modified)
            with self.assertRaisesRegex(UpdateVerificationError,"checksum"):
                update_security.verify_executable(exe,self.fx["manifest"])
        manifest=dict(self.fx["manifest"],sha256="0"*64)
        signature=base64.b64encode(self.fx["private"].sign(canonical_manifest_bytes(manifest)))
        verified=update_security.verify_manifest(json.dumps(manifest).encode(),signature,self.fx["release"],self.fx["public"],architecture="x64")
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/"Kam3Tweaks.exe"; exe.write_bytes(self.fx["exe"])
            with self.assertRaisesRegex(UpdateVerificationError,"checksum"):
                update_security.verify_executable(exe,verified)

    def test_invalid_signature_modified_manifest_and_key_mismatch_are_rejected(self):
        with self.assertRaisesRegex(UpdateVerificationError,"signature"):
            self.verify(signature=base64.b64encode(b"x"*64))
        modified=dict(self.fx["manifest"],version="4.6.2")
        with self.assertRaisesRegex(UpdateVerificationError,"signature"):
            self.verify(manifest=modified)
        other=fixture_release()
        with self.assertRaisesRegex(UpdateVerificationError,"signature"):
            self.verify(public=other["public"])

    def test_no_production_key_fails_closed(self):
        with patch.object(update_security,"PINNED_PUBLIC_KEY_B64",""):
            with self.assertRaises(VerificationUnavailable):
                update_security.verify_manifest(self.fx["names"]["update-manifest.json"],self.fx["signature"],self.fx["release"],None,architecture="x64")
            self.assertFalse(update_security.verification_ready())

    def test_production_trust_anchor_is_pinned_and_valid(self):
        from update_trust import PINNED_PUBLIC_KEY_B64
        self.assertEqual(PINNED_PUBLIC_KEY_B64,"tcZIHqXTLlMqZHOKTeTefcVuJ4h8pce5C6BvxLJLIz0=")
        self.assertTrue(update_security.verification_ready())
        self.assertFalse(update_security.verification_ready("not-a-base64-key"))
        self.assertEqual(update_security.pinned_key_fingerprint(),hashlib.sha256(base64.b64decode(PINNED_PUBLIC_KEY_B64)).hexdigest())

    def test_rejects_wrong_application_publisher_schema_architecture_and_path(self):
        cases=[("application_id","other.application"),("publisher_id","other-publisher"),
               ("schema_version",99),("architecture","arm64"),("executable_filename","../evil.exe")]
        for key,value in cases:
            fx=fixture_release(); m=dict(fx["manifest"],**{key:value})
            sig=base64.b64encode(fx["private"].sign(canonical_manifest_bytes(m)))
            with self.subTest(key=key), self.assertRaises(UpdateVerificationError):
                update_security.verify_manifest(json.dumps(m).encode(),sig,fx["release"],fx["public"],architecture="x64")

    def test_rejects_wrong_release_id_tag_untrusted_repository_and_unstable_channel(self):
        changes=[{"id":9},{"tag":"v4.6.2"},{"repository":"attacker/repo"}]
        for change in changes:
            release={**self.fx["release"],**change}
            with self.subTest(change=change), self.assertRaises(UpdateVerificationError): self.verify(release=release)
        m=dict(self.fx["manifest"],channel="beta")
        sig=base64.b64encode(self.fx["private"].sign(canonical_manifest_bytes(m)))
        with self.assertRaisesRegex(UpdateVerificationError,"stable"):
            update_security.verify_manifest(json.dumps(m).encode(),sig,self.fx["release"],self.fx["public"],architecture="x64")

    def test_semantic_versions_reject_invalid_older_same_and_accept_newer(self):
        self.assertGreater(update_security.stable_version("v4.7.0"),update_security.stable_version("4.6.9"))
        self.assertEqual(update_security.stable_version("V4.7.0"),(4,7,0,0))
        self.assertEqual(update_security.stable_version("4.7.0.0"),(4,7,0,0))
        self.assertEqual(update_security.stable_version("v4.7.0.1"),(4,7,0,1))
        self.assertEqual(update_security.stable_version("4.7.0"),update_security.stable_version("4.7.0.0"))
        with self.assertRaises(UpdateVerificationError): update_security.stable_version("4.7.0-beta")
        with self.assertRaises(UpdateVerificationError): update_security.stable_version("4.7.0.0.0")
        with self.assertRaises(UpdateVerificationError): self.verify(installed_version="4.6.1")
        with self.assertRaises(UpdateVerificationError): self.verify(installed_version="4.6.1.0")
        with self.assertRaises(UpdateVerificationError): self.verify(installed_version="4.6.1.1")
        with self.assertRaises(UpdateVerificationError): self.verify(installed_version="4.7.0")
        with self.assertRaisesRegex(UpdateVerificationError,"newer Windows"):
            update_security.verify_manifest(json.dumps(self.fx["manifest"]).encode(),self.fx["signature"],self.fx["release"],self.fx["public"],architecture="x64",windows_version="10.0.18000")

    def test_legitimate_update_from_four_part_installed_version_and_zero_tag_suffix(self):
        fx=fixture_release(version="4.6.2")
        release={**fx["release"],"tag":"v4.6.2.0"}
        parsed=update_security.verify_manifest(
            json.dumps(fx["manifest"],sort_keys=True,separators=(",",":")).encode(),
            fx["signature"],release,fx["public"],architecture="x64",installed_version="4.6.1.0")
        self.assertEqual(parsed["version"],"4.6.2")

    def test_application_and_updater_metadata_accept_three_or_four_components(self):
        with tempfile.TemporaryDirectory() as temp:
            app=Path(temp)/"Kam3Tweaks.exe"; app.write_bytes(b"metadata-only test file")
            helper=Path(temp)/"Kam3TweaksUpdater.exe"; helper.write_bytes(b"metadata-only updater file")
            def metadata(product,original,version):
                return {"ProductName":product,"OriginalFilename":original,
                        "ProductVersion":version,"FileVersion":version}
            three=update_installer.validate_application_file(
                app,lambda _:metadata("Kam3 Tweaks","Kam3Tweaks.exe","4.6.1"))
            four=update_installer.validate_application_file(
                app,lambda _:metadata("Kam3 Tweaks","Kam3Tweaks.exe","4.6.1.0"))
            build=update_installer.validate_updater_file(
                helper,lambda _:metadata("Kam3 Tweaks","Kam3TweaksUpdater.exe","4.6.1.7"))
            self.assertEqual(three["parsed_version"],(4,6,1,0))
            self.assertEqual(four["parsed_version"],(4,6,1,0))
            self.assertEqual(build["parsed_version"],(4,6,1,7))

    def test_asset_missing_size_limit_malformed_manifest_and_checksum_rejected(self):
        release={**self.fx["release"],"assets":[]}
        with self.assertRaisesRegex(UpdateVerificationError,"asset"):
            self.verify(release=release)
        bad_size={**self.fx["manifest"],"executable_size":-1}
        sig=base64.b64encode(self.fx["private"].sign(canonical_manifest_bytes(bad_size)))
        with self.assertRaises(UpdateVerificationError): update_security.verify_manifest(json.dumps(bad_size).encode(),sig,self.fx["release"],self.fx["public"],architecture="x64")
        with tempfile.TemporaryDirectory() as temp:
            exe=Path(temp)/"Kam3Tweaks.exe"; exe.write_bytes(self.fx["exe"]+b"tamper")
            with self.assertRaisesRegex(UpdateVerificationError,"size"):
                update_security.verify_executable(exe,self.fx["manifest"])
        with self.assertRaises(UpdateVerificationError): update_security.verify_manifest(b"{"+b" "*update_security.MAX_MANIFEST_BYTES,self.fx["signature"],self.fx["release"],self.fx["public"],architecture="x64")


class UpdateDownloadTests(unittest.TestCase):
    def setUp(self): self.fx=fixture_release()
    def opener_for(self, fx=None, *, redirect=None, truncate=None):
        fx=fx or self.fx
        def open_asset(request, timeout):
            url=request.full_url; name=url.rsplit("/",1)[-1]; data=fx["names"].get(name,b"")
            if truncate is not None and name=="Kam3Tweaks.exe": data=data[:truncate]
            return FakeResponse(data,final_url=redirect or url,headers={"Content-Length":str(len(data))})
        return open_asset

    def test_downloads_signed_assets_then_verifies_executable_and_reports_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            progress=[]
            result=update_download.download_verified_update(self.fx["release"],temp,public_key_b64=self.fx["public"],architecture="x64",installed_version="4.5.0",opener=self.opener_for(),progress=lambda done,total:progress.append((done,total)))
            self.assertEqual(Path(result["executable"]).read_bytes(),self.fx["exe"])
            self.assertTrue(progress)
            self.assertEqual(json.loads((result["directory"]/"release.json").read_text())["id"],461)

    def test_rejects_missing_assets_unexpected_filename_and_asset_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            incomplete={**self.fx["release"],"assets":self.fx["release"]["assets"][:-1]}
            with self.assertRaises(update_download.UpdateDownloadError): update_download.download_verified_update(incomplete,temp,public_key_b64=self.fx["public"],opener=self.opener_for())
            renamed={**self.fx["release"],"assets":[{**a,"name":"../Kam3Tweaks.exe"} if a["name"]=="Kam3Tweaks.exe" else a for a in self.fx["release"]["assets"]]}
            with self.assertRaises(update_download.UpdateDownloadError): update_download.download_verified_update(renamed,temp,public_key_b64=self.fx["public"],opener=self.opener_for())
            bad={**self.fx["release"],"assets":[{**a,"url":a["url"].replace("Kam3Tweaks.exe","%2e%2e/evil.exe")} if a["name"]=="Kam3Tweaks.exe" else a for a in self.fx["release"]["assets"]]}
            with self.assertRaises(update_download.UpdateDownloadError): update_download.download_verified_update(bad,temp,public_key_b64=self.fx["public"],opener=self.opener_for())

    def test_rejects_redirect_to_untrusted_host_and_untrusted_download_host(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(update_download.UpdateDownloadError,"untrusted host"):
                update_download.download_verified_update(self.fx["release"],temp,public_key_b64=self.fx["public"],opener=self.opener_for(redirect="https://evil.example/payload"))
            bad={**self.fx["release"],"assets":[{**a,"url":a["url"].replace("https://github.com/","https://evil.example/")} if a["name"]=="update-manifest.json" else a for a in self.fx["release"]["assets"]]}
            with self.assertRaises(update_download.UpdateDownloadError): update_download.download_verified_update(bad,temp,public_key_b64=self.fx["public"],opener=self.opener_for())

    def test_truncated_and_modified_downloads_are_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(update_download.UpdateDownloadError,"length|incomplete"):
                update_download.download_verified_update(self.fx["release"],temp,public_key_b64=self.fx["public"],opener=self.opener_for(truncate=2))
            self.assertEqual(list(Path(temp).iterdir()),[])
            altered={**self.fx,"names":dict(self.fx["names"])}; altered["names"]["Kam3Tweaks.exe"]=self.fx["exe"]+b"changed"
            # API size must still match the signed expected size; the extra byte is rejected before hashing.
            with self.assertRaises(update_download.UpdateDownloadError):
                update_download.download_verified_update(self.fx["release"],temp,public_key_b64=self.fx["public"],opener=self.opener_for(altered))

    def test_cancellation_and_missing_verification_key_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            canceled=threading.Event(); canceled.set()
            with self.assertRaises(update_download.DownloadCancelled):
                update_download.download_verified_update(self.fx["release"],temp,public_key_b64=self.fx["public"],cancel_event=canceled,opener=self.opener_for())
            self.assertEqual(list(Path(temp).iterdir()),[])
            with self.assertRaises(VerificationUnavailable):
                update_download.download_verified_update(self.fx["release"],temp,public_key_b64="",opener=self.opener_for())


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.app=self.root/"Application Folder Ω"; self.app.mkdir()
        self.data=self.root/"user data"; self.data.mkdir()
        (self.data/"custom_profiles.json").write_text('[{"name":"preserve"}]',encoding="utf-8")
        self.stage_root=self.data/"update-staging"; self.stage_root.mkdir()
        self.stage=self.stage_root/"verified-update-case"; self.stage.mkdir()
        self.fx=fixture_release(); self.target=self.app/"Kam3Tweaks.exe"; self.old=b"current harmless dummy executable"
        self.target.write_bytes(self.old)
        self.target_updater=self.app/"Kam3TweaksUpdater.exe"; self.old_updater=b"current harmless dummy helper"; self.target_updater.write_bytes(self.old_updater)
        self._write_stage()
        self.request=update_installer.create_install_request({"directory":self.stage,"release":self.fx["release"]},
            installed_version="4.5.0",parent_pid=123,install_dir=self.app,staging_root=self.stage_root)
        # Real Windows version resources use four numeric components.
        self.meta={hashlib.sha256(self.old).hexdigest():"4.5.0.0",hashlib.sha256(self.fx["exe"]).hexdigest():"4.6.1.0"}
        self.updater_meta={hashlib.sha256(self.old_updater).hexdigest():"4.5.0.0",hashlib.sha256(self.fx["updater"]).hexdigest():"4.6.1.0"}
    def tearDown(self): self.temp.cleanup()
    def _write_stage(self):
        (self.stage/"Kam3Tweaks.exe").write_bytes(self.fx["exe"])
        (self.stage/"Kam3TweaksUpdater.exe").write_bytes(self.fx["updater"])
        (self.stage/"update-manifest.json").write_bytes(self.fx["names"]["update-manifest.json"])
        (self.stage/"update-manifest.sig").write_bytes(self.fx["signature"])
    def metadata_reader(self,path):
        digest=update_installer.sha256_file(path)
        version=self.meta.get(digest,"0.0.0")
        return {"ProductName":"Kam3 Tweaks","OriginalFilename":"Kam3Tweaks.exe","ProductVersion":version,"FileVersion":version}
    def updater_metadata_reader(self,path):
        digest=update_installer.sha256_file(path); version=self.updater_meta.get(digest,"0.0.0")
        return {"ProductName":"Kam3 Tweaks","OriginalFilename":"Kam3TweaksUpdater.exe","ProductVersion":version,"FileVersion":version}
    def run_install(self, *, wait=True, health=True, launch=None, copy_patch=None, replace_patch=None, request=None):
        kwargs={"helper_dir":self.app,"app_data_dir":self.data,"public_key_b64":self.fx["public"],
                "metadata_reader":self.metadata_reader,"updater_metadata_reader":self.updater_metadata_reader,
                "helper_binary_path":self.stage/"Kam3TweaksUpdater.exe","wait_exit":lambda target,pid:wait,
                "launch":launch or (lambda target,token:DummyProcess()),
                "health_check":lambda data,token,version,proc:health}
        if copy_patch:
            with patch.object(update_installer.shutil,"copy2",side_effect=copy_patch): return update_installer.perform_install(request or self.request,**kwargs)
        if replace_patch:
            with patch.object(update_installer.os,"replace",side_effect=replace_patch): return update_installer.perform_install(request or self.request,**kwargs)
        return update_installer.perform_install(request or self.request,**kwargs)

    def test_successful_replacement_backup_health_handshake_and_user_data_preserved(self):
        result=self.run_install()
        self.assertTrue(result["ok"],result)
        self.assertEqual(self.target.read_bytes(),self.fx["exe"])
        self.assertEqual(self.target_updater.read_bytes(),self.fx["updater"])
        self.assertEqual(Path(result["backup"]).read_bytes(),self.old)
        self.assertEqual(Path(result["updater_backup"]).read_bytes(),self.old_updater)
        self.assertEqual((self.data/"custom_profiles.json").read_text(encoding="utf-8"),'[{"name":"preserve"}]')
        self.assertFalse(self.stage.exists())
        self.assertFalse((self.data/"update"/"install_journal.json").exists())
        self.assertEqual(json.loads((self.data/"update"/"result.json").read_text())["status"],"success")

    def test_failed_startup_health_rolls_back_exact_previous_executable(self):
        result=self.run_install(health=False)
        self.assertFalse(result["ok"])
        self.assertEqual(self.target.read_bytes(),self.old)
        self.assertEqual(self.target_updater.read_bytes(),self.old_updater)
        state=json.loads((self.data/"update"/"result.json").read_text())
        self.assertEqual(state["status"],"rolled_back")
        self.assertTrue(list((self.app/"backup").glob("Kam3Tweaks_pre_*.exe")))

    def test_existing_or_multiple_instances_block_replacement_without_force_close(self):
        result=self.run_install(wait=False)
        self.assertFalse(result["ok"]); self.assertIn("still open",result["error"])
        self.assertEqual(self.target.read_bytes(),self.old)
        processes=[SimpleProcess(str(self.target)),SimpleProcess(str(self.target))]
        self.assertFalse(update_installer.wait_for_application_exit(self.target,123,timeout=0,
            process_iter=lambda attrs:iter(processes),sleep=lambda _:None))

    def test_duplicate_active_installer_request_is_serialized(self):
        lock=self.data/"update"/"install.lock"; lock.parent.mkdir(parents=True,exist_ok=True)
        lock.write_text(json.dumps({"pid":os.getpid(),"token":"another-active-update"}))
        result=self.run_install()
        self.assertFalse(result["ok"]); self.assertIn("already running",result["error"])
        self.assertEqual(self.target.read_bytes(),self.old)
        self.assertTrue(lock.exists())

    def test_backup_permission_denied_and_locked_target_preserve_old_version(self):
        def deny_backup(src,dst):
            if Path(src)==self.target: raise PermissionError("denied")
            return __import__("shutil").copy2(src,dst)
        result=self.run_install(copy_patch=deny_backup)
        self.assertFalse(result["ok"]); self.assertEqual(self.target.read_bytes(),self.old)
        original_replace=os.replace
        def locked(src,dst):
            if Path(dst)==self.target: raise PermissionError("target locked")
            return original_replace(src,dst)
        result=self.run_install(replace_patch=locked)
        self.assertFalse(result["ok"]); self.assertEqual(self.target.read_bytes(),self.old)

    def test_updater_replace_failure_rolls_back_app_and_keeps_both_backups(self):
        original_replace=os.replace
        def locked_updater(src,dst):
            if Path(dst)==self.target_updater: raise PermissionError("updater held by scanner")
            return original_replace(src,dst)
        result=self.run_install(replace_patch=locked_updater)
        self.assertFalse(result["ok"])
        self.assertEqual(self.target.read_bytes(),self.old)
        self.assertEqual(self.target_updater.read_bytes(),self.old_updater)
        self.assertTrue(list((self.app/"backup").glob("Kam3Tweaks_pre_*.exe")))
        self.assertTrue(list((self.app/"backup").glob("Kam3TweaksUpdater_pre_*.exe")))

    def test_permission_denied_without_elevation_and_missing_install_target(self):
        target=self.target; self.target.unlink()
        result=self.run_install()
        self.assertFalse(result["ok"]); self.assertIn("existing",result["error"])
        self.assertFalse(self.target.exists())
        self.target=target

    def test_invalid_signed_request_and_path_traversal_are_rejected(self):
        request=json.loads(self.request.read_text())
        request["stage_dir"]=str(self.root)
        bad=self.stage/"install-request.json"; bad.write_text(json.dumps(request))
        result=self.run_install(request=bad)
        self.assertFalse(result["ok"]); self.assertEqual(self.target.read_bytes(),self.old)

    def test_unrelated_target_metadata_is_rejected(self):
        result=update_installer.perform_install(self.request,helper_dir=self.app,app_data_dir=self.data,
            public_key_b64=self.fx["public"],metadata_reader=lambda path:{"ProductName":"Other app","OriginalFilename":"Kam3Tweaks.exe","ProductVersion":"4.5.0"},
            wait_exit=lambda *args:True)
        self.assertFalse(result["ok"]); self.assertEqual(self.target.read_bytes(),self.old)

    def test_cancelled_or_crashed_new_process_rolls_back(self):
        result=self.run_install(health=False,launch=lambda *args:DummyProcess())
        self.assertFalse(result["ok"]); self.assertEqual(self.target.read_bytes(),self.old)

    def test_interrupted_install_journal_restores_only_its_verified_backup(self):
        backup_dir=self.app/"backup"; backup_dir.mkdir(); backup=backup_dir/"Kam3Tweaks_pre_4.5.0_interrupted.exe"; backup.write_bytes(self.old)
        self.target.write_bytes(self.fx["exe"])
        journal=self.data/"update"/"install_journal.json"
        journal.parent.mkdir(parents=True)
        updater_backup=backup_dir/"Kam3TweaksUpdater_pre_4.5.0_interrupted.exe"; updater_backup.write_bytes(self.old_updater)
        self.target_updater.write_bytes(self.fx["updater"])
        journal.write_text(json.dumps({"application_id":APPLICATION_ID,"state":"installing","target":str(self.target),"backup":str(backup),"updater_target":str(self.target_updater),"updater_backup":str(updater_backup),"old_sha256":hashlib.sha256(self.old).hexdigest(),"new_sha256":hashlib.sha256(self.fx["exe"]).hexdigest(),"old_updater_sha256":hashlib.sha256(self.old_updater).hexdigest(),"new_updater_sha256":hashlib.sha256(self.fx["updater"]).hexdigest()}))
        result=update_installer.recover_interrupted_install(journal,helper_dir=self.app,metadata_reader=self.metadata_reader,updater_metadata_reader=self.updater_metadata_reader)
        self.assertTrue(result["ok"],result); self.assertEqual(self.target.read_bytes(),self.old)
        self.assertEqual(self.target_updater.read_bytes(),self.old_updater)
        self.assertTrue(backup.exists())

    def test_recovery_refuses_backup_outside_owned_directory(self):
        outside=self.root/"Kam3Tweaks_pre_evil.exe"; outside.write_bytes(self.old)
        journal=self.data/"update"/"install_journal.json"; journal.parent.mkdir(parents=True,exist_ok=True)
        journal.write_text(json.dumps({"application_id":APPLICATION_ID,"target":str(self.target),"backup":str(outside)}))
        result=update_installer.recover_interrupted_install(journal,helper_dir=self.app,metadata_reader=self.metadata_reader)
        self.assertFalse(result["ok"]); self.assertEqual(self.target.read_bytes(),self.old)

    def test_request_rejects_missing_and_untrusted_staging_locations(self):
        with self.assertRaises(update_installer.InstallationError):
            update_installer.create_install_request({"directory":self.root,"release":self.fx["release"]},installed_version="4.5.0",parent_pid=2,install_dir=self.app,staging_root=self.stage_root)

    def test_health_handshake_requires_matching_token_version_and_data_access(self):
        token="a"*32
        self.assertTrue(update_installer.write_startup_health(self.data,token,"4.6.1",data_accessible=True))
        fake=DummyProcess()
        self.assertTrue(update_installer.wait_for_health(self.data,token,"4.6.1",fake,timeout=0.01))
        self.assertFalse(update_installer.wait_for_health(self.data,"b"*32,"4.6.1",fake,timeout=0.01))


class DummyProcess:
    pid=998877
    def poll(self): return None
    def wait(self,timeout=None): return 0
    def terminate(self): pass


class SimpleProcess:
    def __init__(self,exe): self.info={"exe":exe,"pid":22}


class UpdateApiAndHelperTests(unittest.TestCase):
    def test_github_headers_and_asset_identity_are_constrained(self):
        data={"id":12,"tag_name":"v4.6.1","draft":False,"prerelease":False,
              "html_url":"https://github.com/kam3ron-util/kam3-tweaks/releases/tag/v4.6.1",
              "published_at":"2026-10-31T12:00:00Z","body":"notes",
              "assets":[{"id":1,"name":"Kam3Tweaks.exe","size":9,"state":"uploaded",
                         "url":"https://api.github.com/repos/kam3ron-util/kam3-tweaks/releases/assets/1",
                         "browser_download_url":"https://github.com/kam3ron-util/kam3-tweaks/releases/download/v4.6.1/Kam3Tweaks.exe"},
                        {"id":2,"name":"bad.exe","size":5,"state":"uploaded","url":"https://evil/api","browser_download_url":"https://evil/file"}]}
        captured={}
        def opener(request,timeout): captured.update(headers=dict(request.header_items()),timeout=timeout); return FakeResponse(json.dumps(data).encode(),final_url="https://api.github.com/repos/kam3ron-util/kam3-tweaks/releases/latest")
        release=github_updates.fetch_latest_release(opener=opener)
        self.assertEqual(len(release["assets"]),1)
        self.assertTrue(any(k.casefold()=="x-github-api-version" and v=="2022-11-28" for k,v in captured["headers"].items()))
        self.assertTrue(any(k.casefold()=="user-agent" and "Kam3Tweaks" in v for k,v in captured["headers"].items()))

    def test_github_handles_403_429_server_errors_and_offline_without_false_success(self):
        for code in (403,429):
            headers={"Retry-After":"60"}
            def limited(*args,**kwargs): raise urllib.error.HTTPError("url",code,"limited",headers,io.BytesIO())
            with self.subTest(code=code),self.assertRaisesRegex(github_updates.UpdateCheckError,"60 seconds"):
                github_updates.fetch_latest_release(opener=limited)
        def server(*args,**kwargs): raise urllib.error.HTTPError("url",503,"service unavailable",{},io.BytesIO())
        with self.assertRaisesRegex(github_updates.UpdateCheckError,"503"): github_updates.fetch_latest_release(opener=server)
        def offline(*args,**kwargs): raise urllib.error.URLError("offline")
        with self.assertRaisesRegex(github_updates.UpdateCheckError,"Could not reach GitHub"): github_updates.fetch_latest_release(opener=offline)

    def test_updater_helper_packaged_self_test_is_noninteractive(self):
        expected=update_security.pinned_key_fingerprint()
        self.assertEqual(updater_helper.main(["--self-test","--expected-public-key-sha256="+expected]),0)
        self.assertEqual(updater_helper.main(["--self-test","--expected-public-key-sha256="+"0"*64]),3)
        with patch.object(updater_helper,"PINNED_PUBLIC_KEY_B64",""):
            self.assertEqual(updater_helper.main(["--self-test"]),2)

    def test_recovery_helper_can_start_when_interrupted_target_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp)/"appdata"; (data/"update").mkdir(parents=True)
            install=Path(temp)/"portable install"; install.mkdir()
            journal=data/"update"/"install_journal.json"
            journal.write_text(json.dumps({"target":str(install/"Kam3Tweaks.exe")}),encoding="utf-8")
            captured={}
            def recovery(path,**kwargs):
                captured.update(kwargs); return {"ok":True}
            with patch.object(updater_helper,"app_data_dir",return_value=data),patch.object(updater_helper,"recover_interrupted_install",side_effect=recovery):
                self.assertEqual(updater_helper.main(["--recover"]),0)
            self.assertEqual(captured["helper_dir"],install.resolve())

    def test_release_signer_uses_encrypted_key_and_requires_matching_pinned_public_key(self):
        fx=fixture_release()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); exe=root/"Kam3Tweaks.exe"; helper=root/"Kam3TweaksUpdater.exe"
            exe.write_bytes(fx["exe"]); helper.write_bytes(fx["updater"])
            key=root/"signing.pem"
            encrypted=fx["private"].private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(b"test passphrase"))
            key.write_bytes(encrypted)
            out=root/"release"
            argv=["release_sign.py","--version","4.6.1","--release-id","461","--exe",str(exe),
                  "--updater",str(helper),"--private-key",str(key),"--output-dir",str(out),
                  "--minimum-application-version","4.5.0"]
            with patch.object(release_sign,"PINNED_PUBLIC_KEY_B64",fx["public"]),patch.object(release_sign.getpass,"getpass",return_value="test passphrase"),patch.object(sys,"argv",argv):
                self.assertEqual(release_sign.main(),0)
            self.assertTrue((out/"update-manifest.json").is_file())
            self.assertTrue((out/"update-manifest.sig").is_file())
            with patch.object(release_sign,"PINNED_PUBLIC_KEY_B64","") ,patch.object(release_sign.getpass,"getpass",return_value="test passphrase"),patch.object(sys,"argv",argv),self.assertRaises(SystemExit):
                release_sign.main()

    def test_encrypted_signing_key_verification_never_prints_key_or_passphrase(self):
        fx=fixture_release()
        with tempfile.TemporaryDirectory() as temp:
            key=Path(temp)/"encrypted-signing-key.pem"
            key.write_bytes(fx["private"].private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(b"private phrase")))
            output=io.StringIO()
            with patch.object(verify_signing_key,"PINNED_PUBLIC_KEY_B64",fx["public"]),\
                 patch.object(verify_signing_key.getpass,"getpass",return_value="private phrase"),\
                 patch.object(sys,"stdout",output):
                self.assertEqual(verify_signing_key.main(["--private-key",str(key)]),0)
            rendered=output.getvalue()
            self.assertIn("Match",rendered)
            self.assertNotIn("private phrase",rendered)
            self.assertNotIn("BEGIN ENCRYPTED PRIVATE KEY",rendered)
            with patch.object(verify_signing_key,"PINNED_PUBLIC_KEY_B64","A"*44),\
                 patch.object(verify_signing_key.getpass,"getpass",return_value="private phrase"),\
                 patch.object(sys,"stdout",io.StringIO()):
                self.assertEqual(verify_signing_key.main(["--private-key",str(key)]),2)


if __name__=="__main__": unittest.main()
