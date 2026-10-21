#!/bin/bash
# End-to-end test of the .deb in a clean Debian chroot (run on the host with sudo available).
#   packaging/deb_chroot_test.sh <debian-12-chroot> <cml-lab-builder_X_amd64.deb> [<encorlab_2.x_amd64.deb>]
# With an old ENCOR Lab Builder package it first tests the upgrade from it (upgrade3_test.py): the old app's updater
# sees X and links to encorlab_X_amd64.deb (the old-name copy of the new package), `apt install` of that file swaps
# the encorlab package for cml-lab-builder, and the data moves on the first start.
# Make the chroot once with:  sudo debootstrap --variant=minbase bookworm /path/deb12
# Checks: apt install, desktop-file-validate, launch + single instance, smoke test with patch and
# auto-update tests as a normal user (/opt untouched), deb upgrades vs. a user-dir patch, remove/purge.
set -euo pipefail
CHROOT=$(realpath "$1"); DEB=$(realpath "$2"); OLDDEB=${3:+$(realpath "$3")}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d /tmp/debtest-XXXX)
VER=$(dpkg-deb -f "$DEB" Version)
# test versions around VER=x.y.z: newer package UP1=x.y.(z+1) < user patch PV=x.y.(z+5) < newer package UP2=x.(y+1).0
IFS=. read -r X Y Z <<<"$VER"; UP1=$X.$Y.$((Z+1)); PV=$X.$Y.$((Z+5)); UP2=$X.$((Y+1)).0
STAGE=$WORK/stage
mkdir -p "$STAGE" && dpkg-deb -x "$DEB" "$STAGE"

# test packages: same frozen runtime with app code A.B.C, plus a user patch
python3 - "$ROOT" "$WORK" "$STAGE/opt/cml-lab-builder" "$UP1" "$UP2" "$PV" <<'PY'
import re, shutil, subprocess, sys
from pathlib import Path
root, work, opt = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
up1, up2, pv = sys.argv[4:7]
sys.path.insert(0, str(root / "packaging")); sys.path.insert(0, str(root))
import build_patch
def src(v):
    s = work / f"src-{v}"
    shutil.copytree(root / "cmllab", s / "cmllab", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    i = s / "cmllab" / "__init__.py"
    i.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{v}"', i.read_text()))
    return s
for v in (up1, up2):
    subprocess.run([sys.executable, str(root / "packaging/build_deb.py"), "--stage", opt, "--app-src", str(src(v)),
                    "--version", v, "--out", str(work / "debs")], check=True)
print(build_patch.build_patch(src(pv), work / "patch", pv, None))
PY
mkdir -p "$WORK/debs"; cp "$DEB" "$WORK/debs/"
cp "$WORK"/patch/*.zip "$WORK/debs/user-patch-$PV.zip"
cp "$DEB" "$WORK/debs/encorlab_${VER}_amd64.deb"        # the old-name copy a release carries (build_compat.py)
if [ -n "$OLDDEB" ]; then cp "$OLDDEB" "$WORK/debs/old-$(basename "$OLDDEB")"; fi

cleanup() { set +e; for m in src tmp/debtest dev/pts dev sys proc; do sudo umount -l "$CHROOT/$m" 2>/dev/null; done; rm -rf "$WORK"; }
trap cleanup EXIT
sudo mkdir -p "$CHROOT/src" "$CHROOT/tmp/debtest"
sudo mount -t proc proc "$CHROOT/proc"; sudo mount --rbind /sys "$CHROOT/sys"; sudo mount --bind /dev "$CHROOT/dev"; sudo mount --bind /dev/pts "$CHROOT/dev/pts"
sudo mount --bind "$ROOT" "$CHROOT/src"; sudo mount -o remount,bind,ro "$CHROOT/src"
sudo mount --bind "$WORK/debs" "$CHROOT/tmp/debtest"
sudo cp /etc/resolv.conf "$CHROOT/etc/resolv.conf"
sudo chroot "$CHROOT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root VER="$VER" UP1="$UP1" UP2="$UP2" PV="$PV" bash /src/packaging/deb_chroot_inner.sh
