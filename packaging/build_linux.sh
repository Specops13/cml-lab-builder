#!/usr/bin/env bash
# Build the Linux x64 bundle: dist/CMLLabBuilder-<version>-linux-x64.tar.gz      Usage: packaging/build_linux.sh [--smoke]
# With uv (recommended) it uses python-build-standalone CPython 3.12 (glibc 2.17 baseline) and manylinux_2_28 wheels,
# so the result runs on glibc 2.28+ (Debian 10+, Ubuntu 20.04+) even when built on a newer distro.
# Without uv it falls back to python3 -m venv (the binary then needs the build host's glibc or newer).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${BUILD_DIR:-$ROOT/build/linux}"
mkdir -p "$BUILD"
if command -v uv >/dev/null 2>&1; then
  uv python install 3.12 >/dev/null
  rm -rf "$BUILD/venv"; uv venv -q -p "$(uv python find 3.12)" "$BUILD/venv"
  uv pip install -q --python "$BUILD/venv/bin/python" --python-platform x86_64-manylinux_2_28 "$ROOT" "pyinstaller>=6.22,<7"
else
  rm -rf "$BUILD/venv"; python3 -m venv "$BUILD/venv"
  "$BUILD/venv/bin/pip" install -q "$ROOT" "pyinstaller>=6.22,<7"
fi
cd "$ROOT"
"$BUILD/venv/bin/python" packaging/build.py --work "$BUILD" --out "${OUT_DIR:-$ROOT/dist}" "$@"
