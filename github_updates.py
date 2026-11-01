"""GitHub stable-release metadata discovery for Kam3 Tweaks."""
from __future__ import annotations

import json
import re
import datetime
import email.utils
import urllib.parse
import urllib.error
import urllib.request

REPOSITORY = "kam3ron-util/kam3-tweaks"
LATEST_API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases/latest"
_VERSION = re.compile(r"^[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?$")
MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024


class _GitHubApiRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        parsed=urllib.parse.urlsplit(new_url)
        if parsed.scheme!="https" or parsed.hostname!="api.github.com" or parsed.username or parsed.password:
            raise urllib.error.HTTPError(new_url,code,"untrusted GitHub API redirect",headers,None)
        return super().redirect_request(request,response,code,message,headers,new_url)


def _open_github_api(request, timeout):
    opener=urllib.request.build_opener(_GitHubApiRedirect())
    return opener.open(request,timeout=timeout)


class UpdateCheckError(RuntimeError):
    pass


def parse_version(value: str) -> tuple[int, int, int, int]:
    match = _VERSION.fullmatch(str(value).strip())
    if not match:
        raise UpdateCheckError(f"Unsupported release version: {value!r}")
    return tuple(int(part or 0) for part in match.groups())


def fetch_latest_release(timeout: float = 8.0, opener=None) -> dict:
    request = urllib.request.Request(
        LATEST_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Kam3Tweaks/4.6.1 (release updater)",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    if opener is None: opener=_open_github_api
    try:
        with opener(request, timeout=timeout) as response:
            final=urllib.parse.urlsplit(response.geturl() if hasattr(response,"geturl") else LATEST_API_URL)
            if final.scheme!="https" or final.hostname!="api.github.com":
                raise UpdateCheckError("GitHub redirected the update check to an untrusted host.")
            if getattr(response, "status", 200) != 200:
                raise UpdateCheckError(f"GitHub returned HTTP {response.status}.")
            raw=response.read(MAX_API_RESPONSE_BYTES+1)
            if len(raw)>MAX_API_RESPONSE_BYTES: raise UpdateCheckError("GitHub release response is too large.")
            payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            headers = exc.headers or {}
            retry = headers.get("Retry-After")
            reset = headers.get("X-RateLimit-Reset")
            if retry and retry.isdigit():
                suffix = f" Try again in {retry} seconds."
            elif retry:
                try:
                    retry_date=email.utils.parsedate_to_datetime(retry)
                    suffix=f" Try again in about {max(1,int((retry_date-datetime.datetime.now(datetime.timezone.utc)).total_seconds()))} seconds."
                except (TypeError,ValueError,OverflowError): suffix=" Try again later."
            elif headers.get("X-RateLimit-Remaining") == "0" and reset and reset.isdigit():
                import time
                suffix = f" Try again in about {max(1, int(reset) - int(time.time()))} seconds."
            else:
                suffix = " Try again later."
            raise UpdateCheckError("GitHub rate limit reached." + suffix) from exc
        raise UpdateCheckError(f"GitHub returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateCheckError(f"Could not reach GitHub: {exc}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateCheckError("GitHub returned an invalid release response.") from exc

    if not isinstance(payload, dict) or payload.get("draft") is True or payload.get("prerelease") is True:
        raise UpdateCheckError("GitHub response is not a stable release.")
    tag = payload.get("tag_name")
    version = parse_version(tag)
    url = payload.get("html_url")
    if not isinstance(url, str) or not url.startswith(f"https://github.com/{REPOSITORY}/releases/tag/"):
        raise UpdateCheckError("Release page URL is invalid.")
    notes = payload.get("body")
    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list):
        raise UpdateCheckError("GitHub response does not contain a valid release asset list.")
    assets = []
    for item in raw_assets:
        if not isinstance(item, dict):
            continue
        name, asset_url = item.get("name"), item.get("browser_download_url")
        api_url = item.get("url")
        size, asset_id = item.get("size"), item.get("id")
        if (isinstance(name, str) and isinstance(asset_url, str) and
                asset_url.startswith(f"https://github.com/{REPOSITORY}/releases/download/") and
                isinstance(api_url, str) and api_url.startswith(f"https://api.github.com/repos/{REPOSITORY}/releases/assets/") and
                isinstance(size, int) and size >= 0 and isinstance(asset_id, int)):
            assets.append({"name": name, "url": asset_url, "api_url": api_url,
                           "size": size, "id": asset_id,
                           "state": item.get("state", "uploaded")})
    return {"repository": REPOSITORY, "id": payload.get("id"), "tag": tag, "version": version,
            "url": url, "notes": notes if isinstance(notes, str) else "",
            "published_at": payload.get("published_at"), "assets": assets,
            "draft": False, "prerelease": False}


def compare_release(current: str, release: dict) -> int:
    """Return 1 for newer, 0 for equal, -1 for older."""
    local = parse_version(current)
    remote = release["version"] if isinstance(release.get("version"), tuple) else parse_version(release["tag"])
    return (remote > local) - (remote < local)
