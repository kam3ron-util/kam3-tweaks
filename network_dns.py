"""Read and change per-family Windows DNS settings with exact, conflict-aware Undo data.

DNS addresses are read using the Windows DnsClient PowerShell module. The
documented netsh interface show/set commands are used to detect and restore
the address-family source (DHCP or static), because PowerShell's reset switch
resets the interface rather than one selected address family.
"""
from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from typing import Callable


DNS_READ_SCRIPT = (
    "$ErrorActionPreference='Stop'; Get-DnsClientServerAddress | "
    "Select-Object InterfaceAlias,InterfaceIndex,AddressFamily,ServerAddresses | "
    "ConvertTo-Json -Compress -Depth 4"
)
FAMILIES = {"ipv4": "ipv4", "ipv6": "ipv6", "2": "ipv4", "23": "ipv6"}
REGISTER_VALUES = {"none": "none", "primary only": "primary", "both": "both"}
_INTERFACE_LINE = re.compile(r'^\s*Configuration for interface\s+"(.*)"\s*$', re.I)
_DHCP_LINE = re.compile(r"DNS servers configured through DHCP\s*:", re.I)
_STATIC_LINE = re.compile(r"Statically configured DNS servers\s*:", re.I)
_REGISTER_LINE = re.compile(r"Register with which suffix\s*:\s*(.*?)\s*$", re.I)
_IPV6_DEFAULT_ROUTE = re.compile(r"^\s*(\d+)\s+(\d+)\s+::/0(?:\s|$)", re.I)


class DnsConfigurationError(RuntimeError):
    pass


def validate_dns_addresses(values, family: str | None = None) -> list[str]:
    if isinstance(values, str):
        values = re.split(r"[,;\s]+", values.strip())
    if not isinstance(values, (list, tuple)):
        raise DnsConfigurationError("Enter one or more DNS server IP addresses.")
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            ip = ipaddress.ip_address(value.strip().split("%", 1)[0])
        except ValueError as exc:
            raise DnsConfigurationError(f"Not a valid DNS server IP address: {value!r}") from exc
        if ip.is_unspecified or ip.is_multicast or ip.is_loopback or ip.is_reserved:
            raise DnsConfigurationError(f"This address cannot be used as a DNS server: {value!r}")
        if family and ip.version != (4 if family == "ipv4" else 6):
            raise DnsConfigurationError(f"The address {value!r} is not an {family.upper()} server.")
        canonical = ip.compressed
        if canonical.casefold() not in {item.casefold() for item in result}:
            result.append(canonical)
    if len(result) > 4:
        raise DnsConfigurationError("Use no more than four custom DNS server addresses.")
    return result


def parse_dns_server_rows(output: str) -> dict[int, dict]:
    if not output.strip():
        return {}
    try:
        raw = json.loads(output.lstrip("\ufeff"))
    except (ValueError, TypeError) as exc:
        raise DnsConfigurationError("Windows returned unreadable DNS server details.") from exc
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise DnsConfigurationError("Windows returned an unexpected DNS data format.")
    result: dict[int, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        alias = item.get("InterfaceAlias")
        try:
            index = int(item.get("InterfaceIndex"))
        except (TypeError, ValueError):
            continue
        if not isinstance(alias, str) or not alias.strip() or index <= 0:
            continue
        family = FAMILIES.get(str(item.get("AddressFamily", "")).casefold())
        if family is None:
            continue
        entry = result.setdefault(index, {"interface_index": index, "alias": alias.strip(),
                                          "ipv4": {"servers": []}, "ipv6": {"servers": []}})
        if entry["alias"].casefold() != alias.strip().casefold():
            raise DnsConfigurationError("Windows returned conflicting names for one interface index.")
        values = item.get("ServerAddresses") or []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        entry[family]["servers"] = validate_dns_addresses([str(x) for x in values], family)
    return result


def parse_netsh_dns_report(output: str) -> dict[str, dict]:
    """Parse one `netsh interface ipv4|ipv6 show dnsservers` result.

    Unknown or localized output is intentionally left unknown; callers disable
    changes for that family instead of guessing the source or registration mode.
    """
    result: dict[str, dict] = {}
    current = None
    for line in output.splitlines():
        match = _INTERFACE_LINE.match(line)
        if match:
            current = match.group(1).strip()
            if current:
                result[current.casefold()] = {"alias": current, "source": None, "register": None}
            continue
        if current is None:
            continue
        item = result[current.casefold()]
        if _DHCP_LINE.search(line):
            item["source"] = "dhcp"
        elif _STATIC_LINE.search(line):
            item["source"] = "static"
        register = _REGISTER_LINE.search(line)
        if register:
            item["register"] = REGISTER_VALUES.get(register.group(1).strip().casefold())
    return result


def parse_ipv6_default_route_index(output: str) -> int | None:
    candidates=[]
    for line in output.splitlines():
        match=_IPV6_DEFAULT_ROUTE.match(line)
        if match:
            candidates.append((int(match.group(2)),int(match.group(1))))
    return min(candidates)[1] if candidates else None


def build_dns_adapters(server_rows: dict[int, dict], ipv4_report: dict[str, dict],
                       ipv6_report: dict[str, dict], default_route_alias: str | None = None,
                       default_route_index: int | None = None) -> list[dict]:
    rows = []
    for index, item in server_rows.items():
        alias = item["alias"]
        families = {}
        for family, report in (("ipv4", ipv4_report), ("ipv6", ipv6_report)):
            state = report.get(alias.casefold(), {})
            source = state.get("source")
            register = state.get("register")
            servers = item.get(family, {}).get("servers", [])
            supported = source in {"dhcp", "static"} and register in {"none", "primary", "both"}
            reason = "" if supported else "Windows could not reliably report this family’s DNS source and registration mode."
            if source == "static" and not isinstance(servers, list):
                supported = False
                reason = "The existing static DNS address list could not be captured."
            elif source == "static" and not servers:
                supported = False
                reason = "Windows reported a static configuration with no restorable server address; changing this family is disabled."
            families[family] = {"source": source, "servers": list(servers), "register": register,
                                "supported": supported, "reason": reason}
        rows.append({"interface_index": int(index), "alias": alias,
                     "is_default_route": bool((default_route_alias and alias.casefold() == default_route_alias.casefold()) or
                                               (default_route_index and int(index)==int(default_route_index))),
                     "families": families,
                     "supported": all(x["supported"] for x in families.values()),
                     "reason": next((x["reason"] for x in families.values() if not x["supported"]), "")})
    return sorted(rows, key=lambda x: (not x["is_default_route"], x["alias"].casefold()))


def query_dns_adapters(runner: Callable | None = None, default_route_alias: str | None = None) -> tuple[list[dict], str]:
    if runner is None:
        def runner(args, timeout=8):
            try:
                p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=timeout, shell=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return p.returncode, p.stdout.strip(), p.stderr.strip()
            except (OSError, subprocess.TimeoutExpired) as exc:
                return 1, "", str(exc)
    ps = runner(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", DNS_READ_SCRIPT], timeout=8)
    if ps[0]:
        return [], "DNS address query failed: " + (ps[2] or ps[1] or "PowerShell query failed")
    try:
        servers = parse_dns_server_rows(ps[1])
    except DnsConfigurationError as exc:
        return [], str(exc)
    reports = {}
    errors = []
    for family in ("ipv4", "ipv6"):
        result = runner(["netsh.exe", "interface", family, "show", "dnsservers"], timeout=6)
        if result[0]:
            errors.append(f"{family.upper()} DNS source is unavailable: {result[2] or result[1] or 'query failed'}")
            reports[family] = {}
        else:
            reports[family] = parse_netsh_dns_report(result[1])
    route6=runner(["route.exe","print","-6"],timeout=4)
    default_route_index=parse_ipv6_default_route_index(route6[1]) if not route6[0] else None
    adapters = build_dns_adapters(servers, reports["ipv4"], reports["ipv6"], default_route_alias,default_route_index)
    if not adapters:
        errors.append("Windows did not return a manageable DNS interface.")
    return adapters, "; ".join(errors)


def make_target(snapshot: dict, mode: str, addresses=None) -> dict[int, dict]:
    """Return exact target config by family. `dhcp` targets both families."""
    if mode == "dhcp":
        return {4: {"source": "dhcp", "servers": [], "register": snapshot["families"]["ipv4"]["register"]},
                6: {"source": "dhcp", "servers": [], "register": snapshot["families"]["ipv6"]["register"]}}
    parsed = validate_dns_addresses(addresses)
    if not parsed:
        raise DnsConfigurationError("Choose a provider or enter at least one DNS address.")
    targets = {}
    for version, family in ((4, "ipv4"), (6, "ipv6")):
        family_values = [value for value in parsed if ipaddress.ip_address(value).version == version]
        if family_values:
            targets[version] = {"source": "static", "servers": family_values,
                                "register": snapshot["families"][family]["register"]}
    return targets


def config_matches(actual: dict, expected: dict, include_dynamic=False) -> bool:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    if actual.get("source") != expected.get("source"):
        return False
    if actual.get("register") != expected.get("register"):
        return False
    if expected.get("source") == "static":
        return list(actual.get("servers", [])) == list(expected.get("servers", []))
    # A DHCP resolver can change without a local configuration edit. Its source
    # mode and DNS registration mode are the restorable configuration state.
    return not include_dynamic or list(actual.get("servers", [])) == list(expected.get("servers", []))


def possible_write_results(target: dict) -> list[dict]:
    """Exact states a static netsh update can leave if a later add fails."""
    if target.get("source") != "static":
        return [dict(target)]
    servers = list(target.get("servers", []))
    return [{"source": "static", "servers": servers[:count], "register": target.get("register")}
            for count in range(1, len(servers) + 1)]


def _run_command(args, runner=None, timeout=10):
    if runner is None:
        def runner(args, timeout=10):
            try:
                p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=timeout, shell=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return p.returncode, p.stdout.strip(), p.stderr.strip()
            except (OSError, subprocess.TimeoutExpired) as exc:
                return 1, "", str(exc)
    result = runner(args, timeout=timeout)
    if result[0]:
        message = result[2] or result[1] or "Windows rejected the DNS configuration change."
        if re.search(r"access is denied|access denied|administrator|elevation", message, re.I):
            raise PermissionError(message)
        raise DnsConfigurationError(message)
    return result[1]


def set_dns_family(interface_index: int, alias: str, family_version: int, target: dict,
                   runner: Callable | None = None) -> str:
    """Set one DNS family; no shell parsing or user-provided command text.

    Both DHCP and static changes use family-scoped netsh commands. In
    particular, avoid Set-DnsClientServerAddress here because its reset
    operation is interface-wide and could affect the other address family.
    """
    try:
        index = int(interface_index)
    except (ValueError, TypeError) as exc:
        raise DnsConfigurationError("The selected network adapter has no valid interface index.") from exc
    if index <= 0 or not isinstance(alias, str) or not alias.strip() or "\x00" in alias:
        raise DnsConfigurationError("The selected network adapter identity is invalid.")
    if family_version not in (4, 6):
        raise DnsConfigurationError("Unsupported DNS address family.")
    family = "ipv4" if family_version == 4 else "ipv6"
    source = target.get("source")
    servers = validate_dns_addresses(target.get("servers", []), family)
    register = target.get("register")
    if source not in {"dhcp", "static"} or register not in {"none", "primary", "both"}:
        raise DnsConfigurationError("The requested DNS mode is incomplete.")
    if source == "static":
        if not servers:
            raise DnsConfigurationError("Windows did not report a restorable static DNS address list; no change was made.")
        first = ["netsh.exe", "interface", family, "set", "dnsservers", f"name={alias}",
                 "source=static", f"address={servers[0]}", f"register={register}", "validate=no"]
        output = _run_command(first, runner)
        for offset, address in enumerate(servers[1:], start=2):
            add = ["netsh.exe", "interface", family, "add", "dnsservers", f"name={alias}",
                   f"address={address}", f"index={offset}", "validate=no"]
            output = _run_command(add, runner)
        return output
    argv = ["netsh.exe", "interface", family, "set", "dnsservers", f"name={alias}",
            "source=dhcp", f"register={register}", "validate=no"]
    return _run_command(argv, runner)


def restore_dns_action(action: dict, reader: Callable | None = None, runner: Callable | None = None) -> tuple[bool, str]:
    """Undo one family only after detecting conflicting changes."""
    if reader is None:
        reader = lambda: query_dns_adapters(runner=runner)[0]
    family_version = int(action.get("family"))
    family_name = "ipv4" if family_version == 4 else "ipv6" if family_version == 6 else ""
    if not family_name:
        return False, "Undo record has an invalid DNS family."
    rows = reader()
    adapter = next((row for row in rows if row.get("interface_index") == action.get("interface_index")), None)
    if adapter is None or adapter.get("alias", "").casefold() != str(action.get("alias", "")).casefold():
        return False, "The network adapter identity changed or disappeared; DNS Undo was not applied."
    current = adapter["families"][family_name]
    old = action["old"]
    expected = action["expected"]
    if config_matches(current, old):
        return True, "Original DNS configuration is already active."
    acceptable = action.get("expected_variants") or [expected]
    if not any(config_matches(current, candidate) for candidate in acceptable):
        return False, "DNS settings changed after Kam3 Tweaks applied them. Undo left the newer configuration untouched."
    try:
        set_dns_family(action["interface_index"], action["alias"], family_version, old, runner=runner)
    except Exception as exc:
        return False, f"DNS Undo failed: {exc}"
    rows = reader()
    adapter = next((row for row in rows if row.get("interface_index") == action.get("interface_index") and row.get("alias", "").casefold() == str(action.get("alias", "")).casefold()), None)
    if adapter is None or not config_matches(adapter["families"][family_name], old):
        return False, "Windows did not verify the original DNS mode and server list after Undo."
    return True, "Original DNS mode and server configuration were restored."
