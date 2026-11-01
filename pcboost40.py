"""Catalog metadata for Kam3 Tweaks 4.0.

Entries intentionally distinguish Windows Settings shortcuts from changes the
application applies itself. A shortcut never means the setting was changed.
"""
from __future__ import annotations


def _entry(key, category, name, kind, action, details, *, risk="Low", target="", state="", admin="No", restart="No"):
    return {
        "key": key, "category": category, "name": name, "kind": kind,
        "action": action, "details": details, "risk": risk, "target": target,
        "state": state, "admin": admin, "restart": restart,
    }


CATALOG = [
    _entry("game_mode", "Gaming", "Windows Game Mode", "Direct control", "mode", "Reads and changes the current-user Game Mode preference. This may help Windows prioritize game workloads on supported systems, but results vary and no FPS gain is promised.", risk="Low", state="game_mode"),
    _entry("gamedvr", "Gaming", "GameDVR background capture", "Direct control", "capture", "Changes the current-user capture preferences. Turning capture off can remove background clip recording; it does not change OBS or other capture tools.", risk="Moderate", state="capture", restart="Sometimes"),
    _entry("capture_preferences", "Gaming", "Capture preferences", "Settings shortcut", "shortcut", "Opens Windows Game DVR capture preferences. Review recording and audio choices there; nothing is changed by opening the page.", target="ms-settings:gaming-gamedvr"),
    _entry("game_bar", "Gaming", "Xbox Game Bar", "Settings shortcut", "shortcut", "Opens the Windows Game Bar page. Availability and controls vary by Windows build and installed Game Bar package.", target="ms-settings:gaming-gamebar"),
    _entry("fullscreen_compat", "Gaming", "Fullscreen compatibility properties", "Local utility", "compatibility", "Opens the selected executable's Windows Properties dialog. Compatibility flags can affect presentation or input; review the exact option before applying it.", risk="Moderate", restart="Restart game"),
    _entry("gaming_profiles", "Gaming", "Per-game reversible profiles", "Local utility", "gaming", "Edits local opt-in profiles for Game Mode, capture, power plan, and process priority. Applying a profile requires confirmation and saves prior reversible values.", risk="Moderate", restart="Sometimes"),
    _entry("game_launcher", "Gaming", "Game launcher", "Local utility", "gaming", "Launches a user-selected saved executable with shell execution disabled. Optional profile application remains a separate confirmed action."),

    _entry("process_priority", "CPU", "Process priority classes", "Direct control", "priority", "Sets High, Medium, or Below Normal for one selected process instance. High can reduce responsiveness elsewhere; Realtime is never offered.", risk="Moderate", state="priority"),
    _entry("automatic_priority", "CPU", "Automatic exact-path priority rules", "Local utility", "priority", "Matches the full executable path and applies the saved priority only while the app is open and the watcher is enabled.", risk="Moderate"),
    _entry("pause_priority", "CPU", "Pause or resume priority rules", "Local utility", "priority", "Pauses the in-app watcher without deleting saved rules. No Windows service or scheduled task is installed."),
    _entry("restore_priority", "CPU", "Restore original process priority", "Direct control", "priority", "Restores the exact saved process class while the same PID and creation time still identify the process. A closed process needs no restoration."),
    _entry("cpu_affinity_view", "CPU", "View process CPU affinity", "Read-only tool", "affinity", "Displays the selected process's current allowed logical processors. Access may be denied for protected or elevated processes."),
    _entry("cpu_affinity_set", "CPU", "Change process CPU affinity", "Direct control", "affinity", "Changes the selected process's allowed logical processors after a separate confirmation. The exact previous mask is saved for Undo; affinity changes can reduce performance or compatibility.", risk="Moderate"),
    _entry("process_search", "CPU", "Search running applications", "Read-only tool", "processes", "Filters the on-demand process list by name, PID, or executable path. Selection does not change a process."),
    _entry("process_sort", "CPU", "Sort running applications", "Read-only tool", "processes", "Sorts the current process list by name or PID; the list refresh is on demand."),
    _entry("edit_priority_rules", "CPU", "Edit, disable, or remove rules", "Local utility", "priority", "Edits saved rules by exact path, pauses individual rules, or removes a rule after confirmation."),
    _entry("protected_processes", "CPU", "Protected process safeguards", "Read-only safeguard", "processes", "Windows system locations, critical process names, and Kam3 Tweaks are excluded from priority actions."),

    _entry("per_app_gpu", "Graphics", "Per-app graphics preference", "Settings shortcut", "gpu_settings", "Opens Windows Graphics settings. Add or select an app there and choose Power saving or High performance; Kam3 Tweaks does not write undocumented GPU preference values.", target="ms-settings:display-advancedgraphics"),
    _entry("hags", "Graphics", "Hardware-accelerated GPU scheduling", "Settings shortcut", "shortcut", "Opens Windows default graphics settings. Availability depends on Windows build, GPU, and driver; a restart may be requested by Windows.", target="ms-settings:display-advancedgraphics-default", restart="Windows may request restart"),
    _entry("vrr", "Graphics", "Variable refresh rate", "Settings shortcut", "shortcut", "Opens Windows graphics settings. VRR availability depends on the display, GPU, driver, and Windows build.", target="ms-settings:display-advancedgraphics-default"),
    _entry("windowed_game_optimization", "Graphics", "Optimizations for windowed games", "Settings shortcut", "shortcut", "Opens Windows graphics settings. Windows documents this option for compatible DirectX 10/11 windowed and borderless games; effects vary by title.", target="ms-settings:display-advancedgraphics-default", restart="Restart game"),
    _entry("refresh_rate", "Graphics", "Display refresh rate", "Settings shortcut", "shortcut", "Opens Display settings. Choose only a refresh rate supported by the selected monitor and connection.", target="ms-settings:display-advanced"),
    _entry("resolution", "Graphics", "Display resolution and arrangement", "Settings shortcut", "shortcut", "Opens Display settings for resolution, scale, and monitor arrangement. Supported modes are reported by Windows and the display.", target="ms-settings:display"),
    _entry("hdr", "Graphics", "HDR", "Settings shortcut", "shortcut", "Opens Display settings. HDR appears only when the display and graphics path support it; picture quality and performance vary by hardware and content.", target="ms-settings:display"),
    _entry("auto_hdr", "Graphics", "Auto HDR", "Settings shortcut", "shortcut", "Opens Windows Display settings where Auto HDR is exposed on supported Windows 11 systems and displays.", target="ms-settings:display"),
    _entry("primary_monitor", "Graphics", "Primary monitor selection", "Settings shortcut", "shortcut", "Opens Display settings to identify and select the main display. No monitor topology is changed by Kam3 Tweaks.", target="ms-settings:display"),
    _entry("graphics_driver", "Graphics", "Graphics adapter and driver", "Settings shortcut", "shortcut", "Opens Device Manager for read-only driver review and vendor-supported update workflows. Kam3 Tweaks does not download or install drivers.", target="devmgmt.msc"),

    _entry("power_plan", "Windows", "Balanced / performance power plans", "Direct control", "power", "Lists plans reported by powercfg and switches to the selected plan. High performance can increase power use, heat, and fan noise; OEM devices may expose different plans.", risk="Moderate", state="power"),
    _entry("power_undo", "Windows", "Restore previous power plan", "Direct control", "undo", "Undo restores the exact previously active power-plan GUID saved at the time of the change. No default plan is guessed."),
    _entry("windows_ui_effects", "Windows", "Optional Windows UI effects", "Direct control", "ui_effects", "Reads and changes the documented system-wide UI-effects preference through SystemParametersInfoW. Disabling it can turn off shadows, fades, and related visual feedback. The previous boolean is saved for Undo; no FPS gain is claimed.", risk="Moderate", state="ui_effects"),
    _entry("mouse_acceleration", "Windows", "Disable pointer acceleration", "Direct control", "mouse_accel", "Optional user-selected control through documented SPI_GETMOUSE/SPI_SETMOUSE. Sets acceleration thresholds and level to zero while preserving the exact previous three values for Undo. Pointer feel changes; this is subjective and is not an FPS or latency improvement claim.", risk="Moderate", state="mouse_accel"),
    _entry("visual_effects", "Windows", "Visual effects", "Settings shortcut", "shortcut", "Opens Windows Accessibility visual-effects settings. Turning visual effects off can affect usability and accessibility.", target="ms-settings:easeofaccess-visualeffects"),
    _entry("transparency", "Windows", "Transparency effects", "Settings shortcut", "shortcut", "Opens Windows Personalization colors. Visual preference is subjective; no measurable performance benefit is claimed.", target="ms-settings:personalization-colors"),
    _entry("animations", "Windows", "Animation effects", "Settings shortcut", "shortcut", "Opens Windows visual-effects settings. Review accessibility and usability trade-offs before changing animations.", target="ms-settings:easeofaccess-visualeffects"),
    _entry("background_apps", "Windows", "Background app permissions", "Settings shortcut", "shortcut", "Opens the Windows app permissions area. Windows 11 manages many background permissions per app and may not expose the legacy page.", target="ms-settings:privacy-backgroundapps"),
    _entry("notifications", "Windows", "Notifications", "Settings shortcut", "shortcut", "Opens notification settings. Notification choices do not guarantee a performance improvement.", target="ms-settings:privacy-notifications"),
    _entry("storage_sense", "Windows", "Storage Sense", "Settings shortcut", "shortcut", "Opens Storage Sense settings. Windows controls scheduled cleanup and may delete items according to the choices you make there.", target="ms-settings:storagepolicies"),
    _entry("gaming_readiness", "Windows", "Gaming readiness recommendations", "Read-only advisor", "advisor", "Summarizes OS, CPU, RAM, GPU identification, Game Mode, capture, and current power-plan state. It does not score or promise FPS."),

    _entry("dns_flush", "Network", "Flush DNS resolver cache", "Direct utility", "dns", "Runs ipconfig /flushdns only after confirmation. This clears cached lookups, is not reversible, and is not a latency optimization.", risk="Low", admin="Sometimes"),
    _entry("adapter_info", "Network", "Network adapter information", "Read-only tool", "network", "Shows adapter state, IP addresses, driver-reported link speed, the IPv4 default-route interface, and DNS addresses using on-demand system APIs. No traffic-rate or ping polling is performed."),
    _entry("adapter_settings", "Network", "Network adapter settings", "Settings shortcut", "shortcut", "Opens Windows advanced network settings for adapters and properties.", target="ms-settings:network-advancedsettings"),
    _entry("adapter_power", "Network", "Adapter power management", "Settings shortcut", "shortcut", "Opens Device Manager. Power-management controls depend on the adapter and driver; changing them may affect battery life or wake behavior.", target="devmgmt.msc", risk="Moderate"),
    _entry("network_reset", "Network", "Network reset", "Settings shortcut", "shortcut", "Opens Windows Network reset. Windows may remove adapters and saved configuration; use only when you understand the impact.", target="ms-settings:network-reset", risk="High"),
    _entry("dns_view", "Network", "DNS configuration viewer", "Read-only tool", "network", "Displays per-adapter DNS server addresses returned by Get-DnsClientServerAddress. If Windows cannot query the DNS client, the app reports that detail as unavailable."),
    _entry("dns_manage", "Network", "DNS server configuration", "Direct control", "dns_manage", "Reads the exact per-adapter IPv4/IPv6 DNS source and addresses. Supports DHCP, Cloudflare, Google, Quad9, or custom server addresses when Windows reports a fully restorable source. One confirmation; verifies each family and detects conflicts on Undo. DNS changes may briefly interrupt connectivity and do not guarantee lower ping.", risk="Moderate", state="dns_manage", admin="Yes", restart="No; may briefly reconnect"),

    _entry("user_temp", "Cleanup", "User TEMP cleanup preview", "Direct utility", "cleanup_user", "Lists eligible files under the current user's TEMP folder and requires a second confirmation. Only unchanged files in the preview are deleted; locked and inaccessible files are skipped.", risk="Moderate"),
    _entry("windows_temp", "Cleanup", "Windows TEMP cleanup preview", "Direct utility", "cleanup_windows", "Previews regular files older than seven days directly inside Windows TEMP; it does not recurse into subfolders. Deletion requires administrator rights and confirmation; no auto-elevation.", risk="High", admin="Yes"),
    _entry("recycle_bin", "Cleanup", "Recycle Bin review and empty", "Direct utility", "recycle_bin", "Shows Windows item count and size before asking whether to empty the bin. This cannot be undone.", risk="High"),
    _entry("storage_settings", "Cleanup", "Storage settings", "Settings shortcut", "shortcut", "Opens Windows Storage Sense and storage recommendations. Review Windows' selected cleanup targets before applying.", target="ms-settings:storagerecommendations"),
    _entry("large_file_finder", "Cleanup", "Large-file finder", "Read-only tool", "large_files", "Scans eligible user-profile folders while excluding AppData and reparse points. It never deletes files; inaccessible files are skipped."),
    _entry("downloads_review", "Cleanup", "Downloads review", "Local utility", "downloads", "Opens the Downloads folder for manual review. Kam3 Tweaks does not select or delete files there."),
    _entry("edge_cache", "Cleanup", "Microsoft Edge cache review", "Settings shortcut", "browser_edge", "Opens Edge's clear-browsing-data page if Edge is registered. Review selections in the browser; no data is deleted by Kam3 Tweaks."),
    _entry("chrome_cache", "Cleanup", "Google Chrome cache review", "Settings shortcut", "browser_chrome", "Opens Chrome's clear-browsing-data page if Chrome is registered. Review selections in the browser; no data is deleted by Kam3 Tweaks."),
    _entry("firefox_cache", "Cleanup", "Mozilla Firefox cache review", "Settings shortcut", "browser_firefox", "Opens Firefox privacy settings if Firefox is registered. Review selections in the browser; no data is deleted by Kam3 Tweaks."),
    _entry("cleanup_history", "Cleanup", "Cleanup history", "Local utility", "history", "Shows cleanup-related entries from the local action history and exports them on request."),

    _entry("user_run_entries", "Startup", "Current-user Run entries", "Direct control", "startup", "Reviews HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run. Removing a selected value requires confirmation and saves its exact prior type and data for Undo.", risk="Moderate"),
    _entry("machine_run_review", "Startup", "All-users Run entries", "Read-only tool", "startup", "Reviews HKLM Software\\Microsoft\\Windows\\CurrentVersion\\Run. These entries are read-only in Kam3 Tweaks; policy and access may hide values."),
    _entry("user_startup_folder", "Startup", "Current-user Startup shortcuts", "Direct control", "startup_folder", "Reviews the current user's Start Menu Startup folder. Disabling moves the exact selected shortcut into local app data after confirmation; Undo restores it if the original path is free.", risk="Moderate"),
    _entry("common_startup_folder", "Startup", "All-users Startup shortcuts", "Read-only tool", "startup", "Reviews the common Startup folder. Entries are read-only here and may require administrator access to manage."),
    _entry("startup_folders", "Startup", "Open Startup folders", "Local utility", "startup", "Opens the selected Startup folder in File Explorer for direct inspection."),
    _entry("startup_impact", "Startup", "Startup impact guidance", "Read-only guidance", "startup", "Explains the inspected locations and limitations. Windows startup impact labels are not independently measured by this app."),
]


def validate_catalog(catalog=CATALOG):
    keys=[item["key"] for item in catalog]
    names=[item["name"].casefold() for item in catalog]
    if len(keys)!=len(set(keys)): raise ValueError("Optimization catalog keys must be unique.")
    if len(names)!=len(set(names)): raise ValueError("Optimization catalog names must be unique.")
    required={"key","category","name","kind","action","details","risk","target","state","admin","restart"}
    for item in catalog:
        if not required.issubset(item): raise ValueError(f"Incomplete optimization entry: {item.get('name','?')}")
        if item["kind"]=="Settings shortcut" and item["action"] not in {"shortcut","gpu_settings","browser_edge","browser_chrome","browser_firefox"}:
            raise ValueError(f"Shortcut must not be represented as a direct action: {item['name']}")
    return True


validate_catalog()
