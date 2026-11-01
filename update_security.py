"""Strict signed-manifest and payload verification for Kam3 Tweaks updates."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import struct
from pathlib import Path
from typing import Any

from update_trust import PINNED_PUBLIC_KEY_B64

APPLICATION_ID = "com.kam3ron-util.kam3-tweaks"
PUBLISHER_ID = "kam3ron-util"
MANIFEST_SCHEMA = 1
EXPECTED_EXECUTABLE = "Kam3Tweaks.exe"
EXPECTED_UPDATER = "Kam3TweaksUpdater.exe"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_EXECUTABLE_BYTES = 300 * 1024 * 1024
_STABLE_VERSION = re.compile(r"^[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class UpdateVerificationError(RuntimeError):
    """The update failed an authenticity, identity, or compatibility check."""


class VerificationUnavailable(UpdateVerificationError):
    """No production trust key is pinned in this build."""


def verification_ready(public_key_b64: str | None = None) -> bool:
    value = PINNED_PUBLIC_KEY_B64 if public_key_b64 is None else public_key_b64
    try:
        _public_key(value)
        return True
    except UpdateVerificationError:
        return False


def pinned_key_fingerprint(public_key_b64: str | None = None) -> str:
    """Return SHA-256 of the raw public-key bytes for build identity checks."""
    value = PINNED_PUBLIC_KEY_B64 if public_key_b64 is None else public_key_b64
    try:
        raw = base64.b64decode(value.strip(), validate=True) if value else b""
        if len(raw) != 32:
            raise ValueError("Expected a 32-byte Ed25519 public key")
        return hashlib.sha256(raw).hexdigest()
    except Exception as exc:
        raise UpdateVerificationError("The pinned release verification key is invalid.") from exc


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    if not isinstance(manifest, dict):
        raise UpdateVerificationError("Update manifest must be a JSON object.")
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def stable_version(value: Any) -> tuple[int, int, int, int]:
    """Normalize stable three/four-part versions to a comparable 4-tuple.

    Windows file resources commonly include a fourth build component. A
    three-part release version is equivalent to that version with build 0.
    """
    if not isinstance(value, str):
        raise UpdateVerificationError("Release version is not a stable semantic version.")
    match = _STABLE_VERSION.fullmatch(value)
    if not match:
        raise UpdateVerificationError("Release version is not a stable semantic version.")
    parts = tuple(int(part) if part is not None else 0 for part in match.groups())
    return parts


def current_architecture(machine: str | None = None) -> str:
    machine = (machine or platform.machine()).lower()
    if machine in {"amd64", "x86_64", "x64"}:
        return "x64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    raise UpdateVerificationError(f"Unsupported Windows architecture: {machine}")


def _public_key(public_key_b64: str | None):
    value = PINNED_PUBLIC_KEY_B64 if public_key_b64 is None else public_key_b64
    if not value or not value.strip():
        raise VerificationUnavailable("Secure update installation is unavailable until a release verification key is pinned.")
    try:
        raw = base64.b64decode(value.strip(), validate=True)
        if len(raw) != 32:
            raise ValueError("Ed25519 public keys are 32 bytes")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception as exc:
        raise UpdateVerificationError("The pinned release verification key is invalid.") from exc


def verify_manifest(manifest_bytes: bytes, signature_bytes: bytes, release: dict,
                    public_key_b64: str | None = None, *, architecture: str | None = None,
                    installed_version: str | None = None, windows_version: str | None = None) -> dict:
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise UpdateVerificationError("Update manifest exceeds the allowed size.")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateVerificationError("Update manifest is malformed.") from exc
    required = {
        "schema_version", "application_id", "publisher_id", "version", "channel",
        "architecture", "minimum_windows_version", "minimum_application_version",
        "executable_filename", "executable_size", "sha256", "updater_filename",
        "updater_size", "updater_sha256", "release_id",
        "published_at", "restart_required",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise UpdateVerificationError("Update manifest fields do not match the supported schema.")
    try:
        signature = base64.b64decode(signature_bytes.strip(), validate=True)
        _public_key(public_key_b64).verify(signature, canonical_manifest_bytes(manifest))
    except VerificationUnavailable:
        raise
    except Exception as exc:
        raise UpdateVerificationError("Release manifest signature is invalid.") from exc

    if manifest["schema_version"] != MANIFEST_SCHEMA:
        raise UpdateVerificationError("This update uses an unsupported manifest format.")
    if manifest["application_id"] != APPLICATION_ID:
        raise UpdateVerificationError("Release is for a different application.")
    if manifest["publisher_id"] != PUBLISHER_ID:
        raise UpdateVerificationError("Release publisher does not match the trusted publisher.")
    if manifest["channel"] != "stable":
        raise UpdateVerificationError("Only stable-channel releases are accepted.")
    version = stable_version(manifest["version"])
    minimum_app = stable_version(manifest["minimum_application_version"])
    if not isinstance(manifest["minimum_windows_version"], str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", manifest["minimum_windows_version"]):
        raise UpdateVerificationError("Minimum Windows version is malformed.")
    if windows_version is None:
        windows_version = platform.version() if os.name == "nt" else "0.0.0"
    try:
        required_windows=tuple(int(x) for x in manifest["minimum_windows_version"].split("."))
        current_windows=tuple(int(x) for x in windows_version.split("."))
        width=max(len(required_windows),len(current_windows))
        if current_windows+(0,)*(width-len(current_windows)) < required_windows+(0,)*(width-len(required_windows)):
            raise UpdateVerificationError("This update requires a newer Windows version.")
    except (AttributeError,ValueError) as exc:
        raise UpdateVerificationError("Windows version could not be validated for this update.") from exc
    if manifest["executable_filename"] != EXPECTED_EXECUTABLE:
        raise UpdateVerificationError("Release executable filename is unexpected.")
    if not isinstance(manifest["executable_size"], int) or isinstance(manifest["executable_size"], bool) or not 0 < manifest["executable_size"] <= MAX_EXECUTABLE_BYTES:
        raise UpdateVerificationError("Release executable size is invalid or too large.")
    if not isinstance(manifest["sha256"], str) or not _SHA256.fullmatch(manifest["sha256"]):
        raise UpdateVerificationError("Release checksum is malformed.")
    if manifest["updater_filename"] != EXPECTED_UPDATER:
        raise UpdateVerificationError("Trusted updater helper filename is unexpected.")
    if not isinstance(manifest["updater_size"], int) or isinstance(manifest["updater_size"], bool) or not 0 < manifest["updater_size"] <= MAX_EXECUTABLE_BYTES:
        raise UpdateVerificationError("Trusted updater helper size is invalid or too large.")
    if not isinstance(manifest["updater_sha256"], str) or not _SHA256.fullmatch(manifest["updater_sha256"]):
        raise UpdateVerificationError("Trusted updater helper checksum is malformed.")
    if not isinstance(manifest["release_id"], int) or isinstance(manifest["release_id"], bool):
        raise UpdateVerificationError("Release identity is malformed.")
    if not isinstance(manifest["published_at"], str) or not manifest["published_at"].endswith("Z"):
        raise UpdateVerificationError("Release publication timestamp is invalid.")
    if manifest["restart_required"] is not True:
        raise UpdateVerificationError("Release restart policy is unsupported.")
    arch = architecture or current_architecture()
    if manifest["architecture"] != arch:
        raise UpdateVerificationError("This update does not support this Windows architecture.")
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        raise UpdateVerificationError("GitHub release is not a published stable release.")
    if manifest["release_id"] != release.get("id"):
        raise UpdateVerificationError("Signed manifest does not match the GitHub release identity.")
    if stable_version(release.get("tag", "")) != version:
        raise UpdateVerificationError("Signed manifest version does not match the GitHub release tag.")
    if release.get("repository") != "kam3ron-util/kam3-tweaks":
        raise UpdateVerificationError("Release repository identity is not trusted.")
    if installed_version is not None and version <= stable_version(installed_version):
        raise UpdateVerificationError("Release is not newer than the installed version.")
    if installed_version is not None and stable_version(installed_version) < minimum_app:
        raise UpdateVerificationError("This update requires a newer installed version before it can be applied.")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateVerificationError("GitHub release does not list its assets.")
    asset = next((item for item in assets if isinstance(item, dict) and item.get("name") == EXPECTED_EXECUTABLE), None)
    if not asset or asset.get("size") != manifest["executable_size"]:
        raise UpdateVerificationError("The executable asset is missing or its size does not match the signed manifest.")
    if asset.get("state", "uploaded") != "uploaded":
        raise UpdateVerificationError("GitHub release executable asset is not available.")
    updater = next((item for item in assets if isinstance(item, dict) and item.get("name") == EXPECTED_UPDATER), None)
    if not updater or updater.get("size") != manifest["updater_size"] or updater.get("state", "uploaded") != "uploaded":
        raise UpdateVerificationError("The trusted updater helper is missing or its size does not match the signed manifest.")
    return manifest


def verify_executable(path: str | Path, manifest: dict) -> str:
    path = Path(path)
    try:
        size = path.stat().st_size
        if size != manifest["executable_size"]:
            raise UpdateVerificationError("Downloaded executable size does not match the signed manifest.")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise UpdateVerificationError(f"Downloaded executable could not be read: {exc}") from exc
    actual = digest.hexdigest()
    if actual != manifest["sha256"]:
        raise UpdateVerificationError("Downloaded executable checksum does not match the signed manifest.")
    return actual


def verify_updater(path: str | Path, manifest: dict) -> str:
    """Verify the separately launched helper using the same signed manifest."""
    if Path(path).name != EXPECTED_UPDATER:
        raise UpdateVerificationError("Downloaded updater helper filename is unexpected.")
    proxy={"executable_size":manifest["updater_size"],"sha256":manifest["updater_sha256"]}
    return verify_executable(path,proxy)


def verify_pe_format(path: str | Path, architecture: str) -> None:
    """Reject non-PE content and binaries for the wrong Windows architecture."""
    machine_expected={"x64":0x8664,"arm64":0xAA64}.get(architecture)
    if machine_expected is None:
        raise UpdateVerificationError("Unsupported executable architecture.")
    try:
        with Path(path).open("rb") as stream:
            dos=stream.read(64)
            if len(dos)<64 or dos[:2]!=b"MZ": raise UpdateVerificationError("Release asset is not a Windows executable.")
            offset=struct.unpack_from("<I",dos,0x3c)[0]
            if offset<64 or offset>1024*1024: raise UpdateVerificationError("Windows executable header offset is invalid.")
            stream.seek(offset)
            header=stream.read(6)
        if len(header)!=6 or header[:4]!=b"PE\0\0": raise UpdateVerificationError("Release asset has an invalid Windows executable header.")
        machine=struct.unpack_from("<H",header,4)[0]
        if machine!=machine_expected: raise UpdateVerificationError("Release executable architecture does not match the signed update.")
    except OSError as exc:
        raise UpdateVerificationError(f"Release executable could not be inspected: {exc}") from exc
