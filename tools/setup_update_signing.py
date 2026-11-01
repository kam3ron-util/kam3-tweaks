"""Create an encrypted local Ed25519 release signing key pair."""
from __future__ import annotations

import argparse
import base64
import getpass
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def secure_windows_acl(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
        return
    user_name = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    user = f"{domain}\\{user_name}" if domain and user_name else user_name
    if not user:
        raise RuntimeError("Could not determine the current Windows user for key-file permissions.")
    completed = subprocess.run(["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
                               capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError("Windows could not restrict the private key file permissions. Key setup was not completed.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create encrypted Kam3 Tweaks release-signing keys.")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Kam3TweaksDeveloper" / "signing")
    args = parser.parse_args(argv)
    output = args.output_dir.expanduser().resolve()
    if any(part.casefold() in {"pcboost", "kam3-tweaks", "kam3 tweaks"} for part in output.parts):
        parser.error("Choose a private signing directory outside the project and repository.")
    output.mkdir(parents=True, exist_ok=True)
    private_path = output / "kam3tweaks-release-ed25519-private.pem"
    public_path = output / "kam3tweaks-release-ed25519-public.txt"
    if private_path.exists() or public_path.exists():
        parser.error("Key files already exist. Refusing to overwrite them.")
    first = getpass.getpass("Choose a strong encryption passphrase for the private signing key: ")
    second = getpass.getpass("Re-enter passphrase: ")
    if not first or first != second:
        parser.error("Passphrases were empty or did not match; no key was generated.")
    private = Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.BestAvailableEncryption(first.encode("utf-8")))
    public_raw = private.public_key().public_bytes(serialization.Encoding.Raw,
                                                  serialization.PublicFormat.Raw)
    try:
        with private_path.open("xb") as stream:
            stream.write(private_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        secure_windows_acl(private_path)
        public_path.write_text(base64.b64encode(public_raw).decode("ascii") + "\n", encoding="ascii")
    except Exception:
        private_path.unlink(missing_ok=True)
        public_path.unlink(missing_ok=True)
        raise
    # Public material is safe to show; private bytes are never printed.
    print("Encrypted private key created outside the project:", private_path)
    print("Back this file up offline in a secure password manager or encrypted vault.")
    print("Public verification key (safe to pin in update_trust.py):", base64.b64encode(public_raw).decode("ascii"))
    print("The key is not active in a release until both executables are rebuilt with the public key pinned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
