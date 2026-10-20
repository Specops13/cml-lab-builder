"""Build the ready-to-run bundle for the current OS (run with the build venv's Python):

    python packaging/build.py [--out dist] [--work build/<os>] [--smoke]

Windows -> dist/ENCORLab-<version>-windows-x64.zip     Linux -> dist/ENCORLab-<version>-linux-x64.tar.gz
Contents: ENCORLab(.exe) + _internal/ (PyInstaller one-folder runtime; the app code is in _internal/appcode/),
README-FIRST.txt, README.md, LICENSE.txt, THIRD-PARTY-NOTICES.txt, docs/ (no labs: they come from the online library). The app-code patch is built separately by build_patch.py.
--smoke runs packaging/smoke_test.py against the staged build (it imports the example packs into YOUR user
data folder, so it is meant for CI machines)."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WIN = sys.platform == "win32"


def version() -> str:
    return re.search(r'__version__ = "([^"]+)"', (ROOT / "encorlab" / "__init__.py").read_text(encoding="utf-8")).group(1)


def sh(*cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--work", default=str(ROOT / "build" / ("windows" if WIN else "linux")))
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--nopause", action="store_true", help="(used by build_exe.bat: don't wait for a key at the end)")
    a = ap.parse_args()
    v = version()
    plat = "windows" if WIN else "linux"
    name = f"ENCORLab-{v}-{plat}-x64"
    work, out = Path(a.work), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    sh(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
       "--workpath", work / "pyi", "--distpath", work / "dist", HERE / "encorlab.spec")

    stage = work / "stage" / name
    shutil.rmtree(work / "stage", ignore_errors=True)
    shutil.copytree(work / "dist" / "ENCORLab", stage)
    shutil.copytree(ROOT / "docs", stage / "docs")
    shutil.copy2(ROOT / "README.md", stage / "README.md")
    shutil.copy2(HERE / "README-BINARY.txt", stage / "README-FIRST.txt")
    # MIT license of the app + licenses of everything PyInstaller bundled (fails on an incompatible license)
    shutil.copy2(ROOT / "LICENSE", stage / "LICENSE.txt")
    sh(sys.executable, HERE / "third_party_notices.py", "--work", work / "pyi" / "encorlab", "--version", v,
       "--out", stage / "THIRD-PARTY-NOTICES.txt")
    # no labs in the download (2.0.0): they are installed from the online library (labs/ in the repo)
    if not WIN:
        shutil.copy2(HERE / "encorlab.png", stage / "_internal" / "encorlab.png")
        shutil.copy2(HERE / "install-desktop-entry.sh", stage / "install-desktop-entry.sh")
        os.chmod(stage / "install-desktop-entry.sh", 0o755)

    appcode = stage / "_internal" / "appcode"
    if not (appcode / "encorlab" / "__init__.py").is_file() or not (appcode / "manifest.json").is_file():
        raise SystemExit(f"app code missing from the bundle: {appcode}")
    # byte-compile the bundled app code (hash-checked pycs: valid whatever the file times are after unzipping)
    sh(sys.executable, "-m", "compileall", "-q", "--invalidation-mode", "checked-hash", appcode / "encorlab")

    exe = stage / ("ENCORLab.exe" if WIN else "ENCORLab")
    got = subprocess.run([str(exe), "version"], capture_output=True, text=True, timeout=120).stdout.strip()
    if got != v:
        raise SystemExit(f"frozen app reports version {got!r}, expected {v!r}")

    if WIN:
        target = out / f"{name}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in sorted(stage.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(stage.parent).as_posix())
    else:
        target = out / f"{name}.tar.gz"
        with tarfile.open(target, "w:gz") as t:
            t.add(stage, arcname=name)
    print(f"built {target} ({target.stat().st_size / 1e6:.1f} MB)")

    if a.smoke:
        data = Path(os.environ["APPDATA"]) / "encorlab" if WIN else Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "encorlab"
        sh(sys.executable, HERE / "smoke_test.py", exe, "--version", v, "--data-dir", data, "--patch-test", "--auto-update-test",
           *[x for p in sorted((ROOT / "labs").glob("*.encorlab"))[-2:] for x in ("--pack", p)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
