"""Pure, side-effect limited helpers introduced for PCBoost 2.1."""
from __future__ import annotations

import csv
import math
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


def import_presentmon_csv(path, game_filter=""):
    """Import Intel PresentMon CSV without launching a capture or touching a game."""
    source = Path(path)
    with source.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = {name.casefold(): name for name in (reader.fieldnames or [])}
        app_col = fields.get("application") or fields.get("processname") or fields.get("process_name")
        pid_col = fields.get("processid") or fields.get("process_id")
        frame_col = fields.get("msbetweendisplaychange") or fields.get("msbetweendisplaychanges")
        metric_method = "display interval"
        if not frame_col:
            frame_col = fields.get("msbetweenpresents")
            metric_method = "present interval"
        if not frame_col:
            raise ValueError("CSV has no supported PresentMon frame-time column.")
        dropped_col = fields.get("dropped")
        times = []
        apps = set()
        pids = set()
        target = game_filter.strip().casefold()
        for row in reader:
            app = (row.get(app_col, "") if app_col else "").strip()
            if target and target not in app.casefold():
                continue
            dropped = (row.get(dropped_col, "") if dropped_col else "").strip().casefold()
            if dropped in {"1", "true", "yes"}:
                continue
            try:
                ms = float(row.get(frame_col, ""))
                if not math.isfinite(ms) or ms <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            times.append(ms)
            if app:
                apps.add(app)
            if pid_col and row.get(pid_col, "").strip():
                pids.add(row[pid_col].strip())
    if not times:
        raise ValueError("No valid frame-time rows matched the selected game.")
    if len(pids) > 1:
        raise ValueError("CSV contains multiple process IDs; import one process at a time.")
    average = 1000.0 / (sum(times) / len(times))
    slow = sorted(times, reverse=True)[:max(1, math.ceil(len(times) * 0.01))]
    low_1 = 1000.0 / (sum(slow) / len(slow))
    return {"avg_fps": round(average, 2), "low_1_fps": round(low_1, 2),
            "source": "PresentMon CSV (imported)", "method": metric_method,
            "game": next(iter(apps), source.stem), "frames": len(times)}


def compare_benchmark_rows(before, after):
    """Return a descriptive comparison; only aligned conditions count as matched."""
    mismatches = []
    for key, label in (("game", "game names differ"), ("resolution", "resolutions differ"),
                       ("settings", "graphics settings differ"), ("duration", "durations differ"),
                       ("method", "measurement methods differ")):
        if str(before.get(key, "")).strip().casefold() != str(after.get(key, "")).strip().casefold():
            mismatches.append(label)
    a, b = float(before["avg_fps"]), float(after["avg_fps"])
    return {"matched": not mismatches, "mismatches": mismatches,
            "delta": round(b-a, 2), "percent": round((b-a)/a*100, 1) if a else None}


class MonitoringHistory:
    """Bounded in-memory history. Values can be None when a sensor is unavailable."""
    FIELDS = ("timestamp", "cpu", "ram", "gpu", "network_down_kbps", "network_up_kbps", "disk_read_mbps", "disk_write_mbps")

    def __init__(self, maximum=3600):
        self.rows = deque(maxlen=maximum)

    def add(self, values, timestamp=None):
        row = {key: values.get(key) for key in self.FIELDS if key != "timestamp"}
        row["timestamp"] = timestamp or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        self.rows.append(row)
        return row

    def export_csv(self, path):
        with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDS)
            writer.writeheader()
            writer.writerows(self.rows)
        return len(self.rows)


def validate_profile(data):
    """Validate local opt-in profile config; applying still requires UI confirmation."""
    if not isinstance(data, dict):
        raise ValueError("Profile data must be an object.")
    allowed = {"game_mode": "unchanged", "background_capture": "unchanged", "power_plan": "unchanged", "priority": "unchanged"}
    result = {key: data.get(key, default) for key, default in allowed.items()}
    if result["game_mode"] not in ("unchanged", "on", "off") or result["background_capture"] not in ("unchanged", "on", "off"):
        raise ValueError("Game Mode and capture values must be unchanged, on, or off.")
    legacy_priority={"Normal":"Medium","Below Normal":"Low","Above Normal":"High"}
    result["priority"]=legacy_priority.get(result["priority"],result["priority"])
    if isinstance(result["priority"], str):
        result["priority"] = result["priority"].casefold().title()
    if result["priority"] not in ("Unchanged", "Medium", "High", "Low"):
        raise ValueError("Process priority must be unchanged, Medium, High, or Low.")
    import re
    if result["power_plan"]!="unchanged" and (not isinstance(result["power_plan"],str) or not re.fullmatch(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}",result["power_plan"])):
        raise ValueError("Invalid power plan identifier.")
    return result
