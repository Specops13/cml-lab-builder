"""Build the Debian package cml-lab-builder_<version>_amd64.deb from the frozen Linux build.

    python3 packaging/build_deb.py [--tar dist/CMLLabBuilder-<v>-linux-x64.tar.gz | --stage <unpacked folder>] [--out dist]

Layout:  /opt/cml-lab-builder/      the PyInstaller one-folder app (same files as the tar.gz) + install-type marker "deb"
         /usr/bin/cml-lab-builder   wrapper: exec /opt/cml-lab-builder/cml-lab-builder "$@"
         /usr/bin/cmllab            symlink to it (and /usr/bin/encorlab, the old command, until 4.0)
         /usr/share/applications/cml-lab-builder.desktop, /usr/share/icons/hicolor/<size>/apps/cml-lab-builder.png
         /usr/share/man/man1/cml-lab-builder.1.gz (+ cmllab.1.gz, encorlab.1.gz symlinks),
         /usr/share/doc/cml-lab-builder/{copyright,changelog.gz,LICENSE.txt,THIRD-PARTY-NOTICES.txt}
The package was called encorlab up to 2.1.0; this one Replaces/Breaks/Conflicts with it and Provides it, so
`sudo apt install ./cml-lab-builder_<v>_amd64.deb` swaps the old package out in one step.
The runtime is not rebuilt: the .deb carries exactly the frozen build that was smoke-tested, so the boot loader,
patch updates (into ~/.config/cml-lab-builder/app/<version>, never into /opt) and rollback behave as in the tar.gz.
Needs dpkg-deb (no root: --root-owner-group). --app-src <dir with cmllab/> swaps in other app code (tests)."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PACKAGE = "cml-lab-builder"
OLD_PACKAGE = "encorlab"                   # the package name up to 2.1.0
EXE = "cml-lab-builder"                    # the program in /opt/cml-lab-builder (ENCORLab up to 2.1.0)
MAINTAINER = "Specops13 <Specops13@users.noreply.github.com>"
HOMEPAGE = "https://github.com/Specops13/cml-lab-builder"
DEPENDS = "libc6 (>= 2.28), libgcc-s1 | libgcc1, zlib1g"
RECOMMENDS = "xdg-utils"
EPOCH = int(os.environ.get("SOURCE_DATE_EPOCH") or 1792368000)   # fixed file times: reproducible packages

DESKTOP = """[Desktop Entry]
Type=Application
Version=1.4
Name=CML Lab Builder
GenericName=Cisco lab trainer
Comment=Build and grade CCNP ENCOR and other labs in Cisco Modeling Labs
Exec=cml-lab-builder
TryExec=cml-lab-builder
Icon=cml-lab-builder
Terminal=true
Categories=Education;ComputerScience;
Keywords=CCNP;ENCOR;Cisco;CML;lab;network;cmllab;
StartupNotify=false
"""

WRAPPER = """#!/bin/sh
# CML Lab Builder (Debian package). Starts the web UI and opens the browser, or just opens the browser when it is
# already running; with a command (e.g. `cmllab list`) it runs the CLI. User data and app updates:
# ~/.config/cml-lab-builder. /usr/bin/cmllab (and the old /usr/bin/encorlab) are symlinks to this file.
exec /opt/cml-lab-builder/cml-lab-builder "$@"
"""

POSTINST = """#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
fi
exit 0
"""

PRERM = """#!/bin/sh
set -e
# Nothing to stop: the app runs per user. Updates the user installed (~/.config/cml-lab-builder/app) stay with the user and
# are only used while they are newer than the packaged app, so upgrading or removing this package needs no cleanup.
case "$1" in
    remove|deconfigure)
        if command -v pgrep >/dev/null 2>&1 && pgrep -f /opt/cml-lab-builder/cml-lab-builder >/dev/null 2>&1; then
            echo "cml-lab-builder: CML Lab Builder is still running; close it to finish." >&2
        fi
        ;;
esac
exit 0
"""

POSTRM = """#!/bin/sh
set -e
case "$1" in
    remove|purge)
        # files the app or Python created next to the package files (never user data)
        rm -rf /opt/cml-lab-builder
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database -q /usr/share/applications || true
        fi
        if command -v gtk-update-icon-cache >/dev/null 2>&1; then
            gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
        fi
        ;;
esac
if [ "$1" = "purge" ]; then
    echo "cml-lab-builder: user data in ~/.config/cml-lab-builder (settings, labs, history, app updates) is kept; so is ~/.config/encorlab (ENCOR Lab Builder, if present)." >&2
fi
exit 0
"""

MANPAGE = r""".TH CML-LAB-BUILDER 1 "{date}" "cml-lab-builder {version}" "User Commands"
.SH NAME
cml-lab-builder, cmllab \- CML Lab Builder: build and grade CCNP ENCOR and other labs in Cisco Modeling Labs
.SH SYNOPSIS
.B cml-lab-builder
[\fB\-\-port\fR \fIN\fR] [\fB\-\-no\-browser\fR]
.br
.B cmllab
\fIcommand\fR [\fIoptions\fR]
.SH DESCRIPTION
Without a command, \fBcml-lab-builder\fR (or \fBcmllab\fR) starts the local web UI on http://127.0.0.1:8765 (or the
next free port) and opens the default browser. If it is already running, it only opens the browser. Stop it with
Ctrl+C or by closing its terminal window.
.PP
With a command it runs the CLI, for example \fBcmllab list\fR, \fBcmllab check\fR \fIlab\fR,
\fBcmllab update\-status\fR or \fBcmllab \-\-help\fR.
.PP
Up to 2.1.0 the app was called ENCOR Lab Builder (package and command \fBencorlab\fR). \fBencorlab\fR still works as
an alias until 4.0.
.SH UPDATES
The app checks GitHub Releases in the background and asks before installing an update. Updates are small app\-code
patches installed into \fI~/.config/cml-lab-builder/app/\fR (no root needed); a release that needs a new runtime asks
you to install the new .deb with \fBsudo apt install ./cml-lab-builder_\fIversion\fB_amd64.deb\fR.
.SH FILES
.TP
.I /opt/cml-lab-builder/
the application
.TP
.I ~/.config/cml-lab-builder/
settings, imported labs, history, installed app updates (app/) and their rollback copies; kept when the package is
removed or purged
.TP
.I ~/.config/encorlab/
the data folder of ENCOR Lab Builder (up to 2.0.0), copied to ~/.config/cml-lab-builder on the first start and left
as it was; it can be deleted once you are happy with the new version
.SH SEE ALSO
{homepage}
"""

DOC_FILES = ("LICENSE.txt", "THIRD-PARTY-NOTICES.txt")

COPYRIGHT = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: CML Lab Builder
Upstream-Contact: {maintainer}
Source: {homepage}

Files: *
Copyright: 2026 Dylan Vaughan (Specops13)
License: MIT

Files: opt/cml-lab-builder/_internal/*
Copyright: the respective authors, see /usr/share/doc/cml-lab-builder/THIRD-PARTY-NOTICES.txt
License: bundled-third-party
 The frozen runtime in /opt/cml-lab-builder/_internal bundles CPython (PSF-2.0), the
 PyInstaller bootloader (GPL-2.0-or-later WITH Bootloader-exception) and
 run-time hooks (Apache-2.0), and third-party Python packages under MIT, BSD,
 Apache-2.0, ISC, PSF-2.0, MPL-2.0 (certifi) and LGPL-2.1 (paramiko) licenses,
 all unmodified. The full list with versions, project pages and complete
 license texts is in /usr/share/doc/cml-lab-builder/THIRD-PARTY-NOTICES.txt.

Files: opt/cml-lab-builder/_internal/appcode/*
Copyright: 2026 Dylan Vaughan (Specops13)
License: MIT

License: MIT
 Permission is hereby granted, free of charge, to any person obtaining a copy
 of this software and associated documentation files (the "Software"), to deal
 in the Software without restriction, including without limitation the rights
 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the Software is
 furnished to do so, subject to the following conditions:
 .
 The above copyright notice and this permission notice shall be included in all
 copies or substantial portions of the Software.
 .
 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 SOFTWARE.
"""

CHANGELOG = """cml-lab-builder ({version}) stable; urgency=medium

  * CML Lab Builder {version}.
  * Release notes: {homepage}/releases

 -- {maintainer}  {date}
"""

LINTIAN_OVERRIDES = """# CML Lab Builder is a PyInstaller one-folder application: a self-contained frozen Python runtime with its own
# libraries, installed as a unit under /opt/cml-lab-builder (it is not built from Debian sources).
cml-lab-builder: dir-or-file-in-opt
# bundled wheels' and CPython's libraries ship exactly as built and smoke-tested (stripping changes the tested files)
cml-lab-builder: embedded-library
cml-lab-builder: unstripped-binary-or-object
cml-lab-builder: binary-has-unneeded-section
cml-lab-builder: hardening-no-pie
cml-lab-builder: hardening-no-bindnow
cml-lab-builder: hardening-no-fortify-functions
# hash-checked .pyc of the bundled app code, compiled at build time (/opt is read-only for the user at run time)
cml-lab-builder: package-installs-python-pycache-dir
# license files and docs of the bundled packages and of the app, inside the application folder
cml-lab-builder: extra-license-file
cml-lab-builder: package-contains-documentation-outside-usr-share-doc
# the app-code bundle is <appcode>/cmllab/ inside /opt/cml-lab-builder (the boot loader's layout)
cml-lab-builder: repeated-path-segment
"""


def app_version_of(stage: Path) -> str:
    m = json.loads((stage / "_internal" / "appcode" / "manifest.json").read_text(encoding="utf-8"))
    return str(m["app_version"])


def unpack_tar(tar: Path, into: Path) -> Path:
    with tarfile.open(tar) as t:
        t.extractall(into, filter="tar") if sys.version_info >= (3, 12) else t.extractall(into)
    dirs = [d for d in into.iterdir() if d.is_dir()]
    if len(dirs) != 1:
        raise SystemExit(f"{tar}: expected one top-level folder, found {[d.name for d in dirs]}")
    return dirs[0]


def swap_app_code(opt: Path, src: Path) -> str:
    """Replace the bundled app code with the cmllab/ package from src (used to build test packages)."""
    sys.path.insert(0, str(ROOT))
    import cmlboot
    dest = opt / "_internal" / "appcode"
    shutil.rmtree(dest)
    shutil.copytree(src / "cmllab", dest / "cmllab", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    ver = re.search(r'__version__ = "([^"]+)"', (dest / "cmllab" / "__init__.py").read_text(encoding="utf-8"))[1]
    (dest / "manifest.json").write_text(json.dumps(cmlboot.build_manifest(dest, ver), indent=1, sort_keys=True),
                                        encoding="utf-8")
    return ver


def _gz(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0, filename="") as g:
        g.write(data)
    return buf.getvalue()


def build(stage: Path, out: Path, version: str | None = None, app_src: Path | None = None) -> Path:
    version = version or app_version_of(stage)
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[~+.][0-9A-Za-z.~+]+)?", version):
        raise SystemExit(f"not a Debian-friendly version: {version!r}")
    work = Path(tempfile.mkdtemp(prefix="cml-lab-builder-deb-"))
    try:
        root = work / f"{PACKAGE}_{version}_amd64"
        opt = root / "opt" / PACKAGE
        top = {"install-desktop-entry.sh", "README-FIRST.txt", *DOC_FILES}    # only at the top of the bundle
        shutil.copytree(stage, opt, symlinks=True,
                        ignore=lambda d, names: [n for n in names if n in top and Path(d) == Path(stage)])
        if app_src is not None:
            swap_app_code(opt, app_src)
        (opt / "install-type").write_text("deb\n", encoding="utf-8")
        files = {
            f"usr/bin/{PACKAGE}": (WRAPPER.encode(), 0o755),
            f"usr/share/applications/{PACKAGE}.desktop": (DESKTOP.encode(), 0o644),
            f"usr/share/man/man1/{PACKAGE}.1.gz": (_gz(MANPAGE.format(
                version=version, homepage=HOMEPAGE, date=time.strftime("%B %Y", time.gmtime(EPOCH))).encode()), 0o644),
            f"usr/share/doc/{PACKAGE}/copyright": (COPYRIGHT.format(maintainer=MAINTAINER, homepage=HOMEPAGE).encode(), 0o644),
            f"usr/share/doc/{PACKAGE}/changelog.gz": (_gz(CHANGELOG.format(
                version=version, homepage=HOMEPAGE, maintainer=MAINTAINER,
                date=time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(EPOCH))).encode()), 0o644),
            f"usr/share/lintian/overrides/{PACKAGE}": (LINTIAN_OVERRIDES.encode(), 0o644),
        }
        # LICENSE.txt and THIRD-PARTY-NOTICES.txt of the bundle go to the package's doc folder
        for name in DOC_FILES:
            src = stage / name if (stage / name).is_file() else (ROOT / "LICENSE" if name == "LICENSE.txt" else None)
            if src is None or not src.is_file():
                print(f"warning: {name} is not in the build (built before 1.8.1?)", file=sys.stderr)
                continue
            files[f"usr/share/doc/{PACKAGE}/{name}"] = (src.read_bytes(), 0o644)
        for icon in sorted((HERE / "icons" / "hicolor").glob(f"*/apps/{PACKAGE}.png")):
            files[f"usr/share/icons/hicolor/{icon.parent.parent.name}/apps/{PACKAGE}.png"] = (icon.read_bytes(), 0o644)
        for rel, (data, mode) in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            p.chmod(mode)
        # the short command, and the old one (temporary alias, removed in 4.0)
        for alias in ("cmllab", OLD_PACKAGE):
            (root / "usr/bin" / alias).symlink_to(PACKAGE)
            (root / "usr/share/man/man1" / f"{alias}.1.gz").symlink_to(f"{PACKAGE}.1.gz")
        # permissions: directories 0755, files 0644, the launcher binary 0755
        for p in root.rglob("*"):
            if p.is_symlink():
                continue
            if p.is_dir():
                p.chmod(0o755)
            elif str(p.relative_to(root)) not in (f"usr/bin/{PACKAGE}",):
                p.chmod(0o644)
        if not (opt / EXE).is_file():
            raise SystemExit(f"{stage}: no {EXE} program (an ENCOR Lab Builder 2.x build?)")
        (opt / EXE).chmod(0o755)
        size_kb = sum((p.stat().st_size + 1023) // 1024 for p in root.rglob("*") if p.is_file() and not p.is_symlink())
        md5 = []
        for p in sorted(x for x in root.rglob("*") if x.is_file() and not x.is_symlink()):
            md5.append(f"{hashlib.md5(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}")
        deb = root / "DEBIAN"
        deb.mkdir()
        control = f"""Package: {PACKAGE}
Version: {version}
Architecture: amd64
Maintainer: {MAINTAINER}
Installed-Size: {size_kb}
Depends: {DEPENDS}
Recommends: {RECOMMENDS}
Provides: {OLD_PACKAGE} (= {version})
Conflicts: {OLD_PACKAGE} (<< 3.0.0~)
Breaks: {OLD_PACKAGE} (<< 3.0.0~)
Replaces: {OLD_PACKAGE} (<< 3.0.0~)
Section: education
Priority: optional
Homepage: {HOMEPAGE}
Description: build and grade practice labs in Cisco Modeling Labs
 CML Lab Builder (formerly ENCOR Lab Builder) builds practice labs
 (CCNP ENCOR and other tracks) in Cisco Modeling
 Labs (CML) and grades them with read-only show commands over the
 console, or offline from the configs. It offers hints, solutions,
 fault-injection practice, an exam mode and progress tracking,
 as a local web UI on 127.0.0.1 plus a command-line interface.
 .
 The package contains the self-contained application (frozen Python
 runtime) in /opt/cml-lab-builder. After asking, the app updates itself
 with small verified app-code patches stored per user in
 ~/.config/cml-lab-builder, next to the user data. Commands:
 cml-lab-builder, cmllab. It replaces the encorlab package (ENCOR Lab
 Builder up to 2.1.0). Removing or purging the package keeps user data.
"""
        for name, text, mode in (("control", control, 0o644), ("md5sums", "\n".join(md5) + "\n", 0o644),
                                 ("postinst", POSTINST, 0o755), ("prerm", PRERM, 0o755), ("postrm", POSTRM, 0o755)):
            (deb / name).write_text(text, encoding="utf-8")
            (deb / name).chmod(mode)
        for p in [root, *root.rglob("*")]:
            os.utime(p, (EPOCH, EPOCH), follow_symlinks=False)
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"{PACKAGE}_{version}_amd64.deb"
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(EPOCH))
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(root), str(target)], check=True,
                       env=env, stdout=subprocess.DEVNULL)
        return target
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tar", help="CMLLabBuilder-<v>-linux-x64.tar.gz (default: newest in dist/)")
    ap.add_argument("--stage", help="an unpacked Linux build folder instead of --tar")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--version", help="package version (default: the bundled app version)")
    ap.add_argument("--app-src", help="folder with a cmllab/ package to bundle instead (test packages)")
    a = ap.parse_args()
    if not shutil.which("dpkg-deb"):
        print("ERROR: dpkg-deb not found (apt install dpkg)", file=sys.stderr)
        return 1
    tmp = None
    try:
        if a.stage:
            stage = Path(a.stage)
        else:
            tar = Path(a.tar) if a.tar else max((ROOT / "dist").glob("CMLLabBuilder-*-linux-x64.tar.gz"), key=os.path.getmtime)
            tmp = Path(tempfile.mkdtemp(prefix="cml-lab-builder-tar-"))
            stage = unpack_tar(tar, tmp)
        t = build(stage, Path(a.out), a.version, Path(a.app_src) if a.app_src else None)
        print(f"built {t} ({t.stat().st_size / 1048576:.1f} MB)")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
