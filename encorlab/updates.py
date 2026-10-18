"""Update check against GitHub Releases. Only runs when the user clicks "Check for updates" or has turned on
the (off by default) automatic check. It sends one anonymous GET to api.github.com; nothing is downloaded or installed."""
from __future__ import annotations

import json
import re

from . import __version__, library

REPO = "Specops13/encore-lab-app"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
_VER = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(v: str) -> tuple[int, int, int] | None:
    m = _VER.match(str(v).strip())
    return (int(m[1]), int(m[2]), int(m[3] or 0)) if m else None


def check(current: str = __version__, fetch=library.http_fetch, url: str = LATEST_URL) -> dict:
    """Compare the running version with the latest published release. Raises library.LibraryError on failure."""
    raw = fetch(url, 512 * 1024)
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise library.LibraryError("GitHub returned an invalid response")
    tag = str(d.get("tag_name") or "")
    latest = parse_version(tag)
    if not latest:
        raise library.LibraryError(f"latest release has no version tag ({tag!r})")
    cur = parse_version(current)
    html = str(d.get("html_url") or RELEASES_PAGE)
    if not html.startswith("https://github.com/"):
        html = RELEASES_PAGE
    assets = [{"name": str(a.get("name", "")), "size": a.get("size"), "url": str(a.get("browser_download_url", ""))}
              for a in d.get("assets", []) if isinstance(a, dict)
              and str(a.get("browser_download_url", "")).startswith("https://github.com/")]
    return {"current": current, "latest": ".".join(map(str, latest)), "tag": tag,
            "update_available": bool(cur and latest > cur), "newer_than_latest": bool(cur and cur > latest),
            "url": html, "name": str(d.get("name") or tag), "published_at": d.get("published_at"),
            "notes": str(d.get("body") or "")[:4000], "assets": assets}
