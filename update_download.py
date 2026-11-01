"""Authenticated GitHub asset downloads with private staging and cancellation."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from github_updates import REPOSITORY
from update_security import (EXPECTED_EXECUTABLE, MAX_EXECUTABLE_BYTES,
                             EXPECTED_UPDATER, UpdateVerificationError, verify_executable, verify_updater,
                             verify_manifest, verify_pe_format)

MAX_METADATA_BYTES = 128 * 1024
ALLOWED_DOWNLOAD_HOSTS = {
    "github.com", "objects.githubusercontent.com",
    "release-assets.githubusercontent.com", "github-releases.githubusercontent.com",
}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")


class _TrustedAssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,response,code,message,headers,new_url):
        parsed=urllib.parse.urlsplit(new_url)
        if (parsed.scheme!="https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS or
                parsed.port not in (None,443) or parsed.username or parsed.password):
            raise urllib.error.HTTPError(new_url,code,"untrusted release-asset redirect",headers,None)
        return super().redirect_request(request,response,code,message,headers,new_url)


class DownloadCancelled(RuntimeError):
    pass


class UpdateDownloadError(RuntimeError):
    pass


def _assets(release: dict) -> dict[str, dict]:
    result = {}
    for item in release.get("assets", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name):
            continue
        if name in result:
            raise UpdateDownloadError("GitHub release contains duplicate asset names.")
        result[name] = item
    return result


def _validated_asset_url(asset: dict, release: dict, expected_name: str) -> str:
    name, url = asset.get("name"), asset.get("url")
    if name != expected_name or not isinstance(url, str):
        raise UpdateDownloadError(f"Required release asset {expected_name} is missing.")
    parsed = urllib.parse.urlsplit(url)
    expected_path = f"/{REPOSITORY}/releases/download/{release['tag']}/{expected_name}"
    if (parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or urllib.parse.unquote(parsed.path) != expected_path):
        raise UpdateDownloadError("Release asset URL is outside the trusted GitHub release.")
    return url


def _open(url: str, timeout: float, opener=None):
    request = urllib.request.Request(url, headers={"Accept": "application/octet-stream",
                                                  "User-Agent": "Kam3Tweaks/4.6.1 (release updater)"})
    try:
        if opener is None:
            response=urllib.request.build_opener(_TrustedAssetRedirect()).open(request,timeout=timeout)
        else:
            response = opener(request, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateDownloadError(f"GitHub asset download failed: {exc}") from exc
    status = getattr(response, "status", 200)
    final = urllib.parse.urlsplit(response.geturl() if hasattr(response, "geturl") else url)
    if status != 200:
        response.close()
        raise UpdateDownloadError(f"GitHub asset returned HTTP {status}.")
    if (final.scheme != "https" or final.hostname not in ALLOWED_DOWNLOAD_HOSTS or
            final.username or final.password):
        response.close()
        raise UpdateDownloadError("GitHub redirected the download to an untrusted host.")
    return response


def _download_asset(asset: dict, release: dict, expected_name: str, destination: Path,
                    *, expected_size: int, max_size: int, cancel_event: threading.Event,
                    progress: Callable[[int, int], None] | None, opener=None,
                    timeout: float = 20.0) -> None:
    url = _validated_asset_url(asset, release, expected_name)
    if not isinstance(expected_size, int) or expected_size <= 0 or expected_size > max_size:
        raise UpdateDownloadError("GitHub release asset has an invalid or excessive size.")
    if asset.get("size") != expected_size:
        raise UpdateDownloadError("GitHub release asset size differs from the authenticated size.")
    response = _open(url, timeout, opener)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    received = 0
    try:
        header_size = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
        if header_size and header_size.isdigit() and int(header_size) != expected_size:
            raise UpdateDownloadError("GitHub download length does not match the release metadata.")
        with temporary.open("xb") as out:
            while True:
                if cancel_event.is_set():
                    raise DownloadCancelled("Update download was canceled.")
                block = response.read(256 * 1024)
                if not block:
                    break
                received += len(block)
                if received > expected_size or received > max_size:
                    raise UpdateDownloadError("GitHub returned more data than the authenticated asset size.")
                out.write(block)
                if progress:
                    progress(received, expected_size)
            out.flush()
            os.fsync(out.fileno())
        if received != expected_size:
            raise UpdateDownloadError("Downloaded release asset is incomplete or truncated.")
        temporary.replace(destination)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        response.close()


def download_verified_update(release: dict, staging_root: str | Path, *,
                             public_key_b64: str | None = None,
                             architecture: str | None = None,
                             installed_version: str | None = None,
                             cancel_event: threading.Event | None = None,
                             progress: Callable[[int, int], None] | None = None,
                             opener=None, timeout: float = 20.0) -> dict:
    """Download a signed manifest first, then the EXE, verify it, and return paths.

    The returned directory is kept only after every check passes. Callers must
    never launch its contents directly; installation is delegated to the
    separately built trusted helper.
    """
    cancel_event = cancel_event or threading.Event()
    staging_root = Path(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)
    assets = _assets(release)
    required_names = ("update-manifest.json", "update-manifest.sig", EXPECTED_EXECUTABLE, EXPECTED_UPDATER)
    for name in required_names:
        if name not in assets:
            raise UpdateDownloadError(f"Stable release is missing required asset: {name}")
    folder = Path(tempfile.mkdtemp(prefix="verified-update-", dir=staging_root))
    try:
        manifest_asset = assets["update-manifest.json"]
        signature_asset = assets["update-manifest.sig"]
        for name, asset in ((required_names[0], manifest_asset), (required_names[1], signature_asset)):
            if not isinstance(asset.get("size"), int) or not 1 <= asset["size"] <= MAX_METADATA_BYTES:
                raise UpdateDownloadError(f"Release metadata asset {name} has an invalid size.")
            _download_asset(asset, release, name, folder / name, expected_size=asset["size"],
                            max_size=MAX_METADATA_BYTES, cancel_event=cancel_event,
                            progress=None, opener=opener, timeout=timeout)
        manifest_path = folder / "update-manifest.json"
        signature_path = folder / "update-manifest.sig"
        manifest_bytes = manifest_path.read_bytes()
        signature = signature_path.read_bytes()
        manifest = verify_manifest(manifest_bytes, signature, release, public_key_b64,
                                   architecture=architecture, installed_version=installed_version)
        exe_asset = assets[EXPECTED_EXECUTABLE]
        _download_asset(exe_asset, release, EXPECTED_EXECUTABLE, folder / EXPECTED_EXECUTABLE,
                        expected_size=manifest["executable_size"], max_size=MAX_EXECUTABLE_BYTES,
                        cancel_event=cancel_event, progress=progress, opener=opener, timeout=timeout)
        verify_executable(folder / EXPECTED_EXECUTABLE, manifest)
        verify_pe_format(folder/EXPECTED_EXECUTABLE,manifest["architecture"])
        helper_asset=assets[EXPECTED_UPDATER]
        _download_asset(helper_asset,release,EXPECTED_UPDATER,folder/EXPECTED_UPDATER,
                        expected_size=manifest["updater_size"],max_size=MAX_EXECUTABLE_BYTES,
                        cancel_event=cancel_event,progress=None,opener=opener,timeout=timeout)
        verify_updater(folder/EXPECTED_UPDATER,manifest)
        verify_pe_format(folder/EXPECTED_UPDATER,manifest["architecture"])
        # Persist only the validated GitHub release identity and release assets;
        # the helper will repeat signature and digest checks before replacement.
        release_snapshot = {key: release[key] for key in
                            ("repository", "id", "tag", "url", "published_at", "draft", "prerelease", "assets")
                            if key in release}
        (folder / "release.json").write_text(json.dumps(release_snapshot, sort_keys=True), encoding="utf-8")
        return {"directory": folder, "executable": folder / EXPECTED_EXECUTABLE,
                "updater": folder / EXPECTED_UPDATER,
                "manifest": manifest_path, "signature": signature_path,
                "metadata": manifest, "release": release_snapshot}
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
