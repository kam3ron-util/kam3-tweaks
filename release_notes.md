# Kam3 Tweaks 4.7.0 release notes

## Interface and presets

- Retains the purple bento layout and seven-page navigation: Home, Quick Tweaks, Optimizations, Gaming, Network, Cleanup, and Settings.
- Keeps the Gaming, Performance, and Balanced preset choices. Each preset lists supported changes for review, asks for confirmation, skips settings already at their target, and records reversible changes for Undo. DNS and pointer acceleration are opt-in controls outside presets.
- Windows UI effects include the documented system-wide effects switch alongside the existing menu and minimize/restore animation controls. These affect visual presentation; no performance gain is claimed.

## Reversible controls and network information

- Adds per-adapter IPv4/IPv6 DNS configuration for Automatic (DHCP), Cloudflare, Google, Quad9, and validated custom addresses. Apply requires an administrator session and confirmation. Kam3 Tweaks records the original supported state before writing, verifies each changed address family, and detects conflicts before Undo. Network traffic may briefly reconnect; DNS changes do not guarantee lower ping.
- Adds an optional pointer acceleration control using the documented Windows mouse settings API. It saves the exact original three-value state, verifies the new state, and restores only if no external change conflicts. Mouse feel changes; no FPS or latency improvement is claimed.
- Network information reports available adapters, link details, default routes, and DNS information on demand; unavailable fields are not invented.
- Power-plan Undo verifies the original saved plan GUID and leaves unknown or newer selections untouched. Reversible setting controls preserve original values and fail closed on unreadable or conflicting state.

## Limitations and permissions

- DNS changes require an administrator session, which the app never starts automatically. Some adapter/address-family configurations cannot be changed when their original state cannot be captured exactly. Connectivity can be interrupted briefly.
- Settings shortcuts open native Windows or vendor pages; they are not direct optimizations applied by Kam3 Tweaks.
- Direct GPU vendor-driver changes, direct HAGS/VRR/per-app graphics writes, adapter power-management writes, direct transparency/background-app permission changes, and per-app Windows power policies are not included where documented APIs and reliable exact Undo are unavailable.
- No FPS gain or ping reduction is promised. No clocks, voltages, security protections, game files, or anti-cheat components are changed.

This source candidate was validated with the automated test suite and isolated packaged smoke checks. Release executables must be built from the reviewed source commit, signed with the existing production key, and independently verified before they are uploaded to the v4.7.0 draft. This file supplies draft-body text and is not a release asset.