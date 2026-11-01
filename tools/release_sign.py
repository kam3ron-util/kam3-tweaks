"""Create and locally verify the signed Kam3 Tweaks update manifest."""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from github_updates import REPOSITORY
from update_security import (APPLICATION_ID, EXPECTED_EXECUTABLE, EXPECTED_UPDATER, MANIFEST_SCHEMA,
                             PUBLISHER_ID, canonical_manifest_bytes, stable_version,
                             verify_manifest)
from update_trust import PINNED_PUBLIC_KEY_B64


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sign release metadata; never uploads files.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-id", required=True, type=int, help="GitHub draft release ID")
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--updater", required=True, type=Path)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--architecture", choices=("x64", "arm64"), default="x64")
    parser.add_argument("--minimum-windows-version", default="10.0.19041")
    parser.add_argument("--minimum-application-version", default="4.6.0")
    args = parser.parse_args(argv)
    stable_version(args.version)
    stable_version(args.minimum_application_version)
    exe = args.exe.resolve(strict=True)
    updater=args.updater.resolve(strict=True)
    if exe.name != EXPECTED_EXECUTABLE:
        parser.error(f"Executable must be named {EXPECTED_EXECUTABLE}.")
    if updater.name!=EXPECTED_UPDATER:
        parser.error(f"Updater helper must be named {EXPECTED_UPDATER}.")
    size = exe.stat().st_size
    digest = _sha256(exe)
    updater_size=updater.stat().st_size
    updater_digest=_sha256(updater)
    password = getpass.getpass("Private-key passphrase: ")
    private = serialization.load_pem_private_key(args.private_key.read_bytes(), password=password.encode("utf-8"))
    if not hasattr(private, "sign"):
        parser.error("Private key is not a supported Ed25519 signing key.")
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "application_id": APPLICATION_ID,
        "publisher_id": PUBLISHER_ID,
        "version": args.version.removeprefix("v"),
        "channel": "stable",
        "architecture": args.architecture,
        "minimum_windows_version": args.minimum_windows_version,
        "minimum_application_version": args.minimum_application_version,
        "executable_filename": EXPECTED_EXECUTABLE,
        "executable_size": size,
        "sha256": digest,
        "updater_filename":EXPECTED_UPDATER,
        "updater_size":updater_size,
        "updater_sha256":updater_digest,
        "release_id": args.release_id,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "restart_required": True,
    }
    release = {"repository": REPOSITORY, "id": args.release_id, "tag": "v" + manifest["version"],
               "draft": False, "prerelease": False,
               "assets": [{"name": EXPECTED_EXECUTABLE, "size": size, "state": "uploaded"},
                          {"name": EXPECTED_UPDATER,"size":updater_size,"state":"uploaded"}]}
    signature = private.sign(canonical_manifest_bytes(manifest))
    public_raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    public_b64 = base64.b64encode(public_raw).decode("ascii")
    if not PINNED_PUBLIC_KEY_B64 or public_b64 != PINNED_PUBLIC_KEY_B64.strip():
        parser.error("Signing key does not match the public key pinned in update_trust.py. No release assets were written.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "update-manifest.json"
    signature_path = args.output_dir / "update-manifest.sig"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    signature_path.write_text(base64.b64encode(signature).decode("ascii") + "\n", encoding="ascii")
    verify_manifest(manifest_path.read_bytes(), signature_path.read_bytes(), release,
                    public_b64, architecture=args.architecture)
    print("Signed manifest and Ed25519 signature created and locally verified.")
    print("Manifest:", manifest_path)
    print("Signature:", signature_path)
    print("Executable SHA-256:", digest)
    print("Updater SHA-256:",updater_digest)
    print("Repository release API:", f"https://api.github.com/repos/{REPOSITORY}/releases/{args.release_id}")
    return 0


def _sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""): digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
