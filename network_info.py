"""Read-only Windows network details with fallbacks that avoid NetAdapter CIM."""
from __future__ import annotations

import json
import re
import ipaddress
import subprocess
from typing import Callable

DNS_QUERY = "Get-DnsClientServerAddress | Select-Object InterfaceAlias,ServerAddresses | ConvertTo-Json -Compress -Depth 3"
DEFAULT_ROUTE_RE = re.compile(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+\S+\s+(\S+)\s+(\d+)\s*$")


class NetworkQueryError(RuntimeError):
    pass


def parse_dns_records(output: str) -> dict[str, list[str]]:
    if not output.strip():
        return {}
    try:
        raw = json.loads(output.lstrip("\ufeff"))
    except (ValueError, TypeError) as exc:
        raise NetworkQueryError("Windows returned unreadable DNS information.") from exc
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise NetworkQueryError("Windows returned an unexpected DNS data format.")
    result: dict[str, list[str]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("InterfaceAlias"), str):
            continue
        name = item["InterfaceAlias"].strip()
        values = item.get("ServerAddresses") or []
        if isinstance(values, str):
            values = [values]
        if name and isinstance(values, list):
            entries = result.setdefault(name.casefold(), [])
            entries.extend(str(value).strip() for value in values if str(value).strip())
    return {name: list(dict.fromkeys(values)) for name, values in result.items()}


def parse_default_route_interface(output: str) -> str | None:
    """Return the interface IPv4 address for the lowest-metric default route."""
    candidates = []
    for line in output.splitlines():
        match = DEFAULT_ROUTE_RE.match(line)
        if match:
            candidates.append((int(match.group(2)), match.group(1)))
    return min(candidates)[1] if candidates else None


def build_adapter_records(addresses: dict, stats: dict, dns_by_alias: dict[str, list[str]], route_ip: str | None) -> list[dict]:
    rows = []
    for name, state in stats.items():
        ips = []
        for address in addresses.get(name, []):
            value = address.address.split("%", 1)[0]
            try: ipaddress.ip_address(value); ips.append(value)
            except ValueError: pass
        speed = getattr(state, "speed", 0)
        if not getattr(state, "isup", False) or name.casefold().startswith("loopback"):
            speed = 0
        rows.append({
            "name": name,
            "status": "Up" if getattr(state, "isup", False) else "Down / unavailable",
            "link_speed": f"{int(speed)} Mbps" if isinstance(speed, (int, float)) and speed > 0 else "Unavailable",
            "has_default_route": route_ip in ips if route_ip else None,
            "dns_servers": dns_by_alias.get(name.casefold(), []),
        })
    return sorted(rows, key=lambda row: (row["has_default_route"] is not True, row["status"].casefold() != "up", row["name"].casefold()))


def query_adapters(addresses: dict, stats: dict, runner: Callable | None = None) -> tuple[list[dict], str]:
    """Read DNS/default IPv4 route and combine them with psutil status/link speed."""
    if runner is None:
        def runner(args, timeout=6):
            try:
                proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=timeout, shell=False,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
            except (OSError, subprocess.TimeoutExpired) as exc:
                return 1, "", str(exc)
    errors = []
    code, output, error = runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", DNS_QUERY], timeout=6)
    dns = {}
    if code:
        errors.append("DNS detail unavailable: " + (error or output or "query failed"))
    else:
        try: dns = parse_dns_records(output)
        except NetworkQueryError as exc: errors.append(str(exc))
    route_code, route_output, route_error = runner(["route.exe", "print", "-4"], timeout=4)
    route_ip = None
    if route_code:
        errors.append("Default-route detail unavailable: " + (route_error or route_output or "query failed"))
    else:
        route_ip = parse_default_route_interface(route_output)
        if not route_ip: errors.append("No IPv4 default route could be identified.")
    return build_adapter_records(addresses, stats, dns, route_ip), "; ".join(errors)
