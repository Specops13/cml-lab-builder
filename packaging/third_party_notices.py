"""Write THIRD-PARTY-NOTICES.txt for a PyInstaller build: every Python distribution whose files actually went into
the bundle (from PyInstaller's PYZ/COLLECT tables), its version, license and full license texts, plus the Python
runtime and the PyInstaller bootloader. Run it with the build's Python (build.py does):
    python packaging/third_party_notices.py --work <pyinstaller workpath>/cmllab --out THIRD-PARTY-NOTICES.txt
--json prints the inventory (name, version, license) instead, for checks."""
from __future__ import annotations

import argparse
import ast
import importlib.metadata as md
import json
import os
import re
import sys
import sysconfig
from pathlib import Path

SKIP = {"cml-lab-builder", "cml_lab_builder", "encorlab"}   # this app (MIT, see LICENSE)
# PyInstaller: only the bootloader/loader (GPL-2.0-or-later WITH Bootloader-exception) and the run-time hooks
# (Apache-2.0) are embedded in the executable; its GPL build tooling is not shipped.
OVERRIDE = {
    "pyinstaller": "GPL-2.0-or-later WITH Bootloader-exception (bootloader, loader); Apache-2.0 (run-time hooks)",
    "pyinstaller-hooks-contrib": "Apache-2.0 (the embedded run-time hooks)",
}
LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS", "COPYRIGHT")
HEADER = """THIRD-PARTY NOTICES for CML Lab Builder {version} ({platform})
=================================================================================

CML Lab Builder itself is licensed under the MIT License (see LICENSE).
This download also contains the Python runtime and the third-party Python packages listed below, each under its
own license. They are included unmodified. Their source code is available from the project pages listed (and from
PyPI). The full license texts follow the summary.

Summary
-------
"""


def _toc_paths(work: Path) -> set[str]:
    out = set()
    for name in ("PYZ-00.toc", "COLLECT-00.toc", "Analysis-00.toc"):
        f = work / name
        if not f.is_file():
            continue
        def walk(x):
            if isinstance(x, (list, tuple)):
                if len(x) >= 2 and isinstance(x[1], str) and isinstance(x[0], str) and (os.sep in x[1] or "/" in x[1]):
                    out.add(os.path.normcase(os.path.abspath(x[1])))
                else:
                    for y in x:
                        walk(y)
        walk(ast.literal_eval(f.read_text(encoding="utf-8")))
    return out


def _license(d: md.Distribution) -> str:
    m = d.metadata
    key = (m["Name"] or "").lower().replace("_", "-")
    if key in OVERRIDE:
        return OVERRIDE[key]
    expr = (m.get("License-Expression") or "").strip()
    if expr:
        return expr
    lic = (m.get("License") or "").strip()
    if lic and len(lic) < 80 and "\n" not in lic:
        return lic
    cls = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
    if cls:
        return " / ".join(cls)
    return (lic.splitlines()[0][:80] + " …") if lic else "UNKNOWN"


def _license_files(d: md.Distribution) -> list[tuple[str, str]]:
    seen, out = set(), []
    for f in d.files or []:
        parts = Path(str(f)).parts
        base = parts[-1].upper()
        in_meta = any(p.endswith(".dist-info") for p in parts[:-1])
        if in_meta and (base.startswith(LICENSE_NAMES) or "licenses" in parts):
            p = Path(d.locate_file(f))
            if p.is_file() and p.name not in seen:
                seen.add(p.name)
                out.append((p.name, p.read_text(encoding="utf-8", errors="replace").strip()))
    return out


def bundled(work: Path) -> list[md.Distribution]:
    used = _toc_paths(work)
    hits = {}
    for d in md.distributions():
        name = (d.metadata["Name"] or "").lower().replace("_", "-")
        if not name or name in SKIP or name in hits:
            continue
        for f in d.files or []:
            if os.path.normcase(os.path.abspath(str(d.locate_file(f)))) in used:
                hits[name] = d
                break
    return sorted(hits.values(), key=lambda d: d.metadata["Name"].lower())


def _home(d: md.Distribution) -> str:
    m = d.metadata
    for u in m.get_all("Project-URL") or []:
        k, _, v = u.partition(",")
        if k.strip().lower() in ("source", "source code", "repository", "homepage", "home", "code"):
            return v.strip()
    return (m.get("Home-page") or f"https://pypi.org/project/{m['Name']}/").strip()


def _python_license() -> str:
    for p in (Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"):
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace").strip()
    return "PSF-2.0: see https://docs.python.org/3/license.html"


def inventory(work: Path) -> list[dict]:
    rows = [{"name": "Python (CPython runtime)", "version": sys.version.split()[0], "license": "PSF-2.0",
             "url": "https://www.python.org/", "texts": [("LICENSE.txt", _python_license())]}]
    for d in bundled(work):
        rows.append({"name": d.metadata["Name"], "version": d.version, "license": _license(d), "url": _home(d),
                     "texts": _license_files(d)})
    return rows


def concerns(rows: list[dict]) -> list[str]:
    """Licenses that would not allow shipping the bundle with an MIT app: strong copyleft (GPL/AGPL without the
    PyInstaller bootloader exception), unknown licenses, or packages without any license text."""
    out = []
    for r in rows:
        lic = r["license"]
        strong = re.search(r"\bA?GPL|General Public License", lic) and not re.search(r"LGPL|Lesser|Bootloader-exception", lic)
        if strong or "UNKNOWN" in lic.upper():
            out.append(f"{r['name']} {r['version']}: {lic}")
        elif not r["texts"]:
            out.append(f"{r['name']} {r['version']}: no license text in the package")
    return out


def render(rows: list[dict], version: str, platform: str) -> str:
    out = [HEADER.format(version=version, platform=platform)]
    w = max(len(r["name"]) for r in rows)
    for r in rows:
        out.append(f"  {r['name']:<{w}}  {r['version']:<12} {r['license']}\n")
    out.append("\nSource / project pages\n----------------------\n")
    for r in rows:
        out.append(f"  {r['name']}: {r['url']}\n")
    if platform == "windows":
        out.append("\nThe Windows build also contains the Microsoft Visual C++ runtime (vcruntime140.dll and related\n"
                   "files) that ships with Python for Windows, redistributed under Microsoft's redistribution terms.\n")
    out.append("\nThe Python runtime embeds OpenSSL (Apache-2.0), libffi (MIT), zlib (Zlib), bzip2, xz/liblzma, expat,\n"
               "SQLite (public domain), mpdecimal and (on Linux) libedit/ncurses, as described in the Python license below.\n"
               "\nThe Bootloader exception of PyInstaller (see its COPYING.txt below) allows distributing the executable\n"
               "stub with any program; the GPL does not extend to CML Lab Builder or the other packages.\n")
    for r in rows:
        out.append("\n\n" + "=" * 100 + f"\n{r['name']} {r['version']}  ({r['license']})\n" + "=" * 100 + "\n")
        if not r["texts"]:
            out.append(f"(no license file in the package metadata; license: {r['license']}; see {r['url']})\n")
        for name, text in r["texts"]:
            out.append(f"\n--- {name} ---\n\n{text}\n")
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="PyInstaller workpath for the spec (contains PYZ-00.toc)")
    ap.add_argument("--out")
    ap.add_argument("--version", default="")
    ap.add_argument("--platform", default="windows" if os.name == "nt" else "linux")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows = inventory(Path(a.work))
    if len(rows) < 10:
        raise SystemExit(f"only {len(rows)} bundled packages found in {a.work}: wrong --work?")
    if a.json:
        print(json.dumps([{k: r[k] for k in ("name", "version", "license")} | {"license_files": len(r["texts"])}
                          for r in rows], indent=1))
    bad = concerns(rows)
    if bad:
        print("license check FAILED (not shippable with an MIT app without review):\n  " + "\n  ".join(bad), file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(render(rows, a.version, a.platform), encoding="utf-8", newline="\n")
        print(f"wrote {a.out} ({len(rows)} components)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
