"""Separate trusted Kam3 Tweaks updater process; never accepts arbitrary assets."""
from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path

from update_installer import perform_install, recover_interrupted_install
from update_security import (APPLICATION_ID, PINNED_PUBLIC_KEY_B64,
                             verification_ready, pinned_key_fingerprint)


def app_data_dir() -> Path:
    root = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    return root / "Kam3 Tweaks"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Kam3 Tweaks verified updater helper")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--install-request", type=Path)
    group.add_argument("--recover", action="store_true")
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--expected-public-key-sha256", default="")
    args = parser.parse_args(argv)
    if args.self_test:
        # Confirm this helper was built with the expected valid trust anchor.
        if APPLICATION_ID != "com.kam3ron-util.kam3-tweaks" or not verification_ready(PINNED_PUBLIC_KEY_B64):
            return 2
        if args.expected_public_key_sha256 and pinned_key_fingerprint(PINNED_PUBLIC_KEY_B64) != args.expected_public_key_sha256:
            return 3
        return 0
    data = app_data_dir()
    if args.recover:
        journal_path=data/"update"/"install_journal.json"
        try:
            journal=json.loads(journal_path.read_text(encoding="utf-8"))
            # The app executable may be the missing file after an interrupted
            # replace. Resolve its owned parent, which must still exist.
            install_dir=Path(journal["target"]).parent.resolve(strict=True)
        except Exception:
            return 2
        result = recover_interrupted_install(journal_path,
                                             helper_dir=install_dir,
                                             parent_pid=args.parent_pid,
                                             launch=lambda target,token: __import__("subprocess").Popen([str(target),f"--update-health={token}"],cwd=str(target.parent),close_fds=True))
    else:
        try:
            request_data=json.loads(args.install_request.read_text(encoding="utf-8"))
            target_dir=Path(request_data["install_dir"]).resolve(strict=True)
        except Exception:
            return 2
        result = perform_install(args.install_request,
                                 helper_dir=target_dir,
                                 app_data_dir=data,
                                 public_key_b64=PINNED_PUBLIC_KEY_B64 or None,
                                 helper_binary_path=Path(sys.executable).resolve())
    if not result.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
