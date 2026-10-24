#!/bin/bash
# Prepares the package set for deb_chroot_inner.sh (used by deb_chroot_test.sh and deb_docker_test.sh / CI).
#   packaging/deb_test_prep.sh <cml-lab-builder_X_amd64.deb> <out-dir> [<encorlab_2.x_amd64.deb>]
# Needs python3 + dpkg-deb on the host (no root). Writes into <out-dir>: the package under test, two newer test
# packages UP1=x.y.(z+1) < UP2=x.(y+1).0 built from the same frozen runtime, a user patch PV=x.y.(z+5) between
# them, the old-name copy encorlab_X_amd64.deb a release carries, optionally old-<encorlab deb>, and env.sh with
# VER/UP1/UP2/PV for the inner script.
set -euo pipefail
DEB=$(realpath "$1"); OUT=$(realpath -m "$2"); OLDDEB=${3:+$(realpath "$3")}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VER=$(dpkg-deb -f "$DEB" Version)
IFS=. read -r X Y Z <<<"$VER"; UP1=$X.$Y.$((Z+1)); PV=$X.$Y.$((Z+5)); UP2=$X.$((Y+1)).0
WORK=$(mktemp -d /tmp/debprep-XXXX); trap 'rm -rf "$WORK"' EXIT
STAGE=$WORK/stage
mkdir -p "$STAGE" "$OUT" && dpkg-deb -x "$DEB" "$STAGE"
python3 - "$ROOT" "$WORK" "$STAGE/opt/cml-lab-builder" "$UP1" "$UP2" "$PV" "$OUT" <<'PY'
import re, shutil, subprocess, sys
from pathlib import Path
root, work, opt = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
up1, up2, pv, out = sys.argv[4], sys.argv[5], sys.argv[6], Path(sys.argv[7])
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
                    "--version", v, "--out", str(out)], check=True)
z = build_patch.build_patch(src(pv), work / "patch", pv, None)
shutil.copy(z, out / f"user-patch-{pv}.zip")
import fake_release   # 3.3.0+: patches must be signed; a throwaway key, trusted via CMLLAB_UPDATE_TEST_KEY (signing.py)
seed, pub = fake_release.test_key()
(out / f"user-patch-{pv}.zip.sig").write_bytes(fake_release.sign(seed, z.read_bytes()))
(out / "testkey.pub").write_text(pub)
PY
cp "$DEB" "$OUT/"
cp "$DEB" "$OUT/encorlab_${VER}_amd64.deb"        # the old-name copy a release carries (build_compat.py)
if [ -n "$OLDDEB" ]; then cp "$OLDDEB" "$OUT/old-$(basename "$OLDDEB")"; fi
printf 'VER=%s\nUP1=%s\nUP2=%s\nPV=%s\n' "$VER" "$UP1" "$UP2" "$PV" > "$OUT/env.sh"
echo "prepared $(ls "$OUT" | tr '\n' ' ')"
