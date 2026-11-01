# Kam3 Tweaks 4.7.0

Kam3 Tweaks is a Windows desktop utility for reviewing and safely changing selected Windows settings. The 4.7.0 source candidate keeps the existing purple bento interface and seven sidebar pages: Home, Quick Tweaks, Optimizations, Gaming, Network, Cleanup, and Settings.

This branch is a source-sync candidate. Its executables are built separately; they are not signed, installed, or published by the build step.

## Safety model

- Direct changes require explicit review or confirmation. The app does not silently apply presets.
- Reversible changes save the original state before writing, verify the result, and check for conflicts before Undo.
- Unknown or unsupported states fail closed. Registry Undo preserves original value type and absence.
- The app does not auto-elevate, change CPU/GPU clocks or voltages, disable security protections, modify game files, or interfere with anti-cheat software.
- FPS gains are not promised. DNS changes do not promise lower ping.
- Settings shortcuts open Windows or vendor settings; opening them does not mean Kam3 Tweaks applied a change.

## 4.7.0 changes and controls

- **DNS configuration:** choose a specific adapter and configure IPv4/IPv6 with DHCP, Cloudflare, Google, Quad9, or validated custom addresses. Apply requires administrator rights, warns about temporary connectivity interruption, records exact prior supported family states, verifies changes, and detects Undo conflicts. DNS is excluded from presets.
- **Pointer acceleration:** an optional Windows mouse setting control, separate from presets. It saves and restores the exact original three-value state; mouse feel changes, with no FPS or latency claim.
- **Windows effects and presets:** the existing menu/minimize animation controls and documented system-wide UI-effects control remain reversible. Gaming, Performance, and Balanced presets include only explicitly supported choices; the user reviews one confirmation before changes.
- **Network information:** adapter, route, DNS, and available link information are read on demand. Unavailable values are reported as unavailable.
- **Undo safety:** power-plan restoration verifies the saved GUID and refuses unknown or externally changed state. Other reversible controls use the same conflict-aware restore journal.

The catalog distinguishes direct controls, utilities, read-only information, and Settings shortcuts. Direct GPU driver changes, direct HAGS/VRR and per-app graphics preference writes, adapter power-management writes, direct transparency/background-app permission writes, and several other requested Windows controls are not implemented where reliable detection and exact restoration are unavailable.

## Requirements

- Windows 10 or Windows 11 for the desktop application and Windows-specific controls.
- Python 3.13 was used for the validated 4.7.0 Windows build. The application dependencies are `PySide6-Essentials`, `psutil`, and `cryptography`; exact package ranges are in `requirements.txt`.
- Packaging adds PyInstaller from `requirements-build.txt`.

## Run from source

In PowerShell, from the repository directory:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python PCBoost.py
```

The application normally runs as a standard user. DNS configuration requires an already elevated session. Kam3 Tweaks never elevates itself. Some process and Windows TEMP operations can be unavailable due to permissions; the app reports those failures.

## Test and build on Windows

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest discover -s tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
```

`build_windows.ps1` compiles source, runs the regression suite, packages the app and updater, verifies version resources and icons, and runs isolated packaged smoke checks. It writes a timestamped `candidate_Kam3Tweaks_4.7.0_*` directory and leaves `dist` untouched. Promotion is a separate step and should only follow review of a passing candidate:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1 -Promote -CandidateDir .\candidate_Kam3Tweaks_4.7.0_YYYYMMDD_HHMMSS
```

Qt component tests can run headlessly with `QT_QPA_PLATFORM=offscreen`. The test suite mocks Windows-changing operations and uses temporary directories; it must not be used to alter a real adapter or user profile.

## Secure release preparation

The updater accepts stable GitHub Releases only after verifying the Ed25519 manifest signature with the pinned public verification key, the manifest's release ID/tag, and both executable hashes. The encrypted production private key and its passphrase must remain outside this repository. Never commit keys, passphrases, signed release files, or generated binaries.

Before signing a release, push the reviewed source commit only after owner approval, update the existing GitHub draft's target to that exact commit, and verify the draft ID, tag, target commit, and draft status. Then, on the trusted local machine, prepare signed files with the existing encrypted key and release ID:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\publish_release.ps1 `
  -Version 4.7.0 `
  -ReleaseId <DRAFT_RELEASE_ID> `
  -SourceCommit <FULL_40_CHARACTER_COMMIT_SHA> `
  -PrivateKeyPath "$env:LOCALAPPDATA\Kam3TweaksDeveloper\signing\kam3tweaks-release-ed25519-private.pem"
```

The passphrase is requested through a local non-echoing prompt; never put it in a command, chat, or log. Review the locally generated manifest and signature, then independently verify the signature, release ID/tag, and SHA-256 values. Upload exactly these four assets to the still-unpublished draft:

1. `Kam3Tweaks.exe`
2. `Kam3TweaksUpdater.exe`
3. `update-manifest.json`
4. `update-manifest.sig`

Download the uploaded files to a separate verification directory and repeat the hash and signature checks before considering publication. `RELEASE_NOTES.md` is a local copy/paste aid for the draft body, not a fifth release asset. `SHA256SUMS.txt` is a local convenience and does not replace the signed manifest. The release script does not push source. Do not pass `-Publish` unless publication is separately approved.

## Project files

- `PCBoost.py`: PySide6 application entry point.
- `network_dns.py`, `network_info.py`, `pcboost40.py`, `pcboost21.py`, `ui_components.py`: network controls, optimization catalog, and supporting UI/features.
- `github_updates.py`, `update_*.py`, `updater_helper.py`, `update_trust.py`: stable-release checking and signed update verification/installation.
- `tests/`: automated regression, mocked Windows operation, updater, and offscreen Qt tests.
- `build_windows.ps1`, `version_info.txt`, `updater_version_info.txt`, and `Kam3Tweaks.ico`: Windows packaging inputs.

See `release_notes.md` for the concise 4.7.0 notes. Existing published v4.6.1 release assets are not modified by this source branch.