"""Build the app-code patch of a release (platform independent, stdlib only):

    python packaging/build_patch.py [--out dist]          -> dist/cml-lab-builder-patch-<version>.zip
    python packaging/build_patch.py --check-lock          fail if the runtime changed without a RUNTIME_VERSION bump
    python packaging/build_patch.py --update-lock         record the current runtime fingerprint

The patch holds manifest.json (format, package, app_version, min_runtime, sha256 of each file) and the cmllab/
package exactly as cmlboot.iter_app_files() lists it (no __pycache__). Zip entries use fixed timestamps, so the
same source always gives the same bytes. min_runtime is cmlboot.RUNTIME_VERSION: bump it (and run --update-lock)
whenever Python, a dependency, the PyInstaller spec, cmlboot.py or cmllab_launcher.py changes. Otherwise a patch
could need something the installed runtime doesn't have."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import cmlboot  # noqa: E402

LOCK = HERE / "runtime.lock.json"
RUNTIME_INPUTS = ["cmlboot.py", "cmllab_launcher.py", "packaging/cmllab.spec", "packaging/build_linux.sh"]
_FIXED = (1980, 1, 1, 0, 0, 0)


def version(src: Path = ROOT) -> str:
    return re.search(r'__version__ = "([^"]+)"', (src / "cmllab" / "__init__.py").read_text(encoding="utf-8")).group(1)


def runtime_fingerprint(root: Path = ROOT) -> str:
    """Hash of everything that ends up in the frozen runtime: dependency pins, Python range, loader, spec."""
    py = (root / "pyproject.toml").read_text(encoding="utf-8")
    deps = re.search(r"(?ms)^requires-python.*?^\]", py)
    h = hashlib.sha256((deps.group(0) if deps else py).replace("\r\n", "\n").encode())
    for rel in RUNTIME_INPUTS:
        h.update(b"\0" + rel.encode() + b"\0" + (root / rel).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def lock_problem(root: Path = ROOT) -> str | None:
    try:
        lock = json.loads((root / "packaging" / "runtime.lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "packaging/runtime.lock.json is missing; run python packaging/build_patch.py --update-lock"
    if lock.get("runtime_version") != cmlboot.RUNTIME_VERSION:
        return (f"runtime.lock.json records runtime {lock.get('runtime_version')} but cmlboot.RUNTIME_VERSION is "
                f"{cmlboot.RUNTIME_VERSION}; run python packaging/build_patch.py --update-lock")
    if lock.get("fingerprint") != runtime_fingerprint(root):
        return ("the runtime changed (dependencies, Python range, cmlboot.py, cmllab_launcher.py or the spec). Bump "
                "RUNTIME_VERSION in cmlboot.py if the frozen runtime is affected, then run "
                "python packaging/build_patch.py --update-lock")
    return None


def write_lock() -> None:
    LOCK.write_text(json.dumps({"runtime_version": cmlboot.RUNTIME_VERSION, "fingerprint": runtime_fingerprint()},
                               indent=1) + "\n", encoding="utf-8")


def _entry(name: str) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(name, _FIXED)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    return zi


def build_patch(src: Path, out_dir: Path, app_version: str | None = None, min_runtime: int | None = None) -> Path:
    """src = a folder that contains cmllab/ (the repo root)."""
    v = app_version or version(src)
    m = cmlboot.build_manifest(src, v, cmlboot.RUNTIME_VERSION if min_runtime is None else min_runtime)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"cml-lab-builder-patch-{v}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(_entry("manifest.json"), json.dumps(m, indent=1, sort_keys=True) + "\n")
        for rel, p in cmlboot.iter_app_files(src):
            z.writestr(_entry(rel), p.read_bytes())
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="output folder (default: dist/)")
    ap.add_argument("--check-lock", action="store_true")
    ap.add_argument("--update-lock", action="store_true")
    a = ap.parse_args()
    if a.update_lock:
        write_lock()
        print(f"wrote {LOCK} (runtime {cmlboot.RUNTIME_VERSION})")
        return 0
    problem = lock_problem()
    if problem:
        print("ERROR: " + problem, file=sys.stderr)
        return 1
    if a.check_lock and a.out is None:   # --check-lock alone: only check
        print(f"runtime {cmlboot.RUNTIME_VERSION} fingerprint is current")
        return 0
    t = build_patch(ROOT, Path(a.out or ROOT / "dist"))
    print(f"built {t} ({t.stat().st_size / 1024:.0f} KB, min_runtime {cmlboot.RUNTIME_VERSION})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
