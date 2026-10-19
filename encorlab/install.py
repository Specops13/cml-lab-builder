"""How this copy of the app was installed, and which release asset is its full download.

    deb          /opt/encorlab from encorlab_<v>_amd64.deb (marker file /opt/encorlab/install-type = "deb")
    linux-tar    unpacked ENCORLab-<v>-linux-x64.tar.gz
    windows-zip  unpacked ENCORLab-<v>-windows-x64.zip
    source       running from a source checkout (pip install -e . / run.sh)

App-code patches always go to the user data folder (<data>/app/<version>), never into the install folder, so a
deb install updates without root just like the zip and tar.gz builds."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MARKER = "install-type"
KINDS = ("deb", "linux-tar", "windows-zip", "source")


def app_dir() -> Path | None:
    """Folder of the packaged app (where ENCORLab / ENCORLab.exe and _internal/ live), None from source."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def install_type(base: Path | None = None, platform: str | None = None) -> str:
    base = base if base is not None else app_dir()
    if base is None:
        return "source"
    try:
        kind = (Path(base) / MARKER).read_text(encoding="utf-8").strip().lower()
        if kind in KINDS:
            return kind
    except OSError:
        pass
    return "windows-zip" if (platform or os.name) == "nt" else "linux-tar"


def asset_name(kind: str, version: str) -> str | None:
    return {"deb": f"encorlab_{version}_amd64.deb",
            "linux-tar": f"ENCORLab-{version}-linux-x64.tar.gz",
            "windows-zip": f"ENCORLab-{version}-windows-x64.zip"}.get(kind)


def full_download(assets: list[dict], version: str, kind: str | None = None) -> dict | None:
    """The asset a user of this install type should download for a full update, e.g. the new .deb for deb installs."""
    kind = kind or install_type()
    want = asset_name(kind, version)
    if not want:
        return None
    for a in assets or []:
        if a.get("name") == want and a.get("url"):
            return {"name": want, "url": a["url"], "size": a.get("size"), "kind": kind}
    if kind == "deb":   # a release without a .deb: any encorlab_<version>_*.deb
        for a in assets or []:
            if re.fullmatch(rf"encorlab_{re.escape(version)}_[a-z0-9]+\.deb", str(a.get("name", ""))) and a.get("url"):
                return {"name": a["name"], "url": a["url"], "size": a.get("size"), "kind": kind}
    return None


def how_to_install(kind: str, name: str | None) -> str:
    """What to do after downloading the full release (shown after the download link)."""
    if kind == "deb":
        return f"install it with: sudo apt install ./{name or 'encorlab_<version>_amd64.deb'}"
    if kind == "windows-zip":
        return "unzip it and start ENCORLab.exe from the new folder"
    if kind == "linux-tar":
        return "unpack it and start ./ENCORLab from the new folder"
    return "update the source checkout (git pull)"
