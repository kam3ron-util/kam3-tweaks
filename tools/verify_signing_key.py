"""Check that an encrypted Ed25519 private key matches the pinned public key."""
from __future__ import annotations

import argparse
import base64
import getpass
import hmac
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from update_trust import PINNED_PUBLIC_KEY_B64


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify a local encrypted release key without printing key material.")
    parser.add_argument("--private-key", required=True, type=Path)
    args = parser.parse_args(argv)
    if not PINNED_PUBLIC_KEY_B64:
        parser.error("No public key is pinned in update_trust.py.")
    try:
        encrypted_pem = args.private_key.read_bytes()
        if not encrypted_pem.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----"):
            parser.error("The selected key is not an encrypted PKCS#8 private-key file.")
        password = getpass.getpass("Private-key passphrase (input is not echoed): ")
        private = serialization.load_pem_private_key(encrypted_pem, password=password.encode("utf-8"))
        if not isinstance(private, Ed25519PrivateKey):
            parser.error("The selected encrypted key is not an Ed25519 key.")
        raw_public = private.public_key().public_bytes(serialization.Encoding.Raw,
                                                      serialization.PublicFormat.Raw)
        derived = base64.b64encode(raw_public).decode("ascii")
        if not hmac.compare_digest(derived, PINNED_PUBLIC_KEY_B64.strip()):
            print("Mismatch: the encrypted private key does not match update_trust.py.")
            return 2
    except (OSError, ValueError, TypeError) as exc:
        print(f"Could not verify the encrypted signing key ({type(exc).__name__}). Check the path and passphrase.")
        return 2
    print("Match: the encrypted Ed25519 private key corresponds to the pinned public key.")
    print("No private key material or passphrase was displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
