"""Transition assets for ENCOR Lab Builder 1.7 - 2.1 (runtime 1), which look for the old file names.

    python packaging/build_compat.py --dist dist [--version 3.0.0]

Writes into --dist, next to the real assets of the same release:
  encorlab-patch-<v>.zip              manifest only (package "encorlab", min_runtime 2, no files). An old updater
                                      downloads it, checks it against SHA256SUMS.txt, sees "needs runtime 2" and
                                      shows its "download the full release" banner instead of installing anything.
  ENCORLab-<v>-windows-x64.zip        byte-identical copies of CMLLabBuilder-<v>-windows-x64.zip,
  ENCORLab-<v>-linux-x64.tar.gz       CMLLabBuilder-<v>-linux-x64.tar.gz and cml-lab-builder_<v>_amd64.deb under
  encorlab_<v>_amd64.deb              the names the old banner links to (and its "sudo apt install
                                      ./encorlab_<v>_amd64.deb" hint), so the link downloads the new release.
New versions (3.0.0+) only read the new names; these files can stop being published once nobody runs 2.x."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_RUNTIME = 1


def version() -> str:
    return re.search(r'__version__ = "([^"]+)"', (ROOT / "cmllab" / "__init__.py").read_text(encoding="utf-8"))[1]


def runtime() -> int:
    return int(re.search(r"^RUNTIME_VERSION = (\d+)", (ROOT / "cmlboot.py").read_text(encoding="utf-8"), re.M)[1])


def copies(v: str) -> dict[str, str]:
    return {f"CMLLabBuilder-{v}-windows-x64.zip": f"ENCORLab-{v}-windows-x64.zip",
            f"CMLLabBuilder-{v}-linux-x64.tar.gz": f"ENCORLab-{v}-linux-x64.tar.gz",
            f"cml-lab-builder_{v}_amd64.deb": f"encorlab_{v}_amd64.deb"}


def old_patch_bytes(v: str, min_runtime: int) -> bytes:
    if min_runtime <= OLD_RUNTIME:
        raise SystemExit("the stub would be installable by an old app: min_runtime must be above 1")
    m = {"format": 1, "package": "encorlab", "app_version": v, "min_runtime": min_runtime, "files": {},
         "note": f"CML Lab Builder {v} needs the full download (new program and runtime); see the release page."}
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("manifest.json", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, json.dumps(m, indent=1, sort_keys=True) + "\n")
    return buf.getvalue()


def build(dist: Path, v: str, need_all: bool = True) -> list[Path]:
    out = []
    p = dist / f"encorlab-patch-{v}.zip"
    p.write_bytes(old_patch_bytes(v, runtime()))
    out.append(p)
    for new, old in copies(v).items():
        if not (dist / new).is_file():
            if need_all:
                raise SystemExit(f"{dist / new} is missing")
            continue
        shutil.copyfile(dist / new, dist / old)
        out.append(dist / old)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(ROOT / "dist"))
    ap.add_argument("--version", default="")
    ap.add_argument("--partial", action="store_true", help="skip copies whose new-name file is not in --dist")
    a = ap.parse_args()
    for p in build(Path(a.dist), a.version or version(), not a.partial):
        print(f"wrote {p} ({p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
