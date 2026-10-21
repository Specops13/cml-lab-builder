#!/usr/bin/env bash
# CML Lab Builder launcher for Debian/Ubuntu (and macOS).
#   ./run.sh              -> start the web UI on http://127.0.0.1:8765
#   ./run.sh <command>    -> run a CLI command, e.g. ./run.sh list | ./run.sh check eigrp-basic
# Supported Python: 3.10 - 3.13.
set -euo pipefail
cd "$(dirname "$0")"
VENV=.venv

in_range() { "$1" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)' >/dev/null 2>&1; }

venv_version() {
  [ -f "$VENV/pyvenv.cfg" ] && [ -x "$VENV/bin/python" ] || return 1
  sed -n -E 's/^[[:space:]]*(version|version_info)[[:space:]]*=[[:space:]]*([0-9]+\.[0-9]+).*/\2/p' "$VENV/pyvenv.cfg" | head -n1
}

find_python() {
  for c in ${PYTHON:-} python3.13 python3.12 python3.11 python3.10 python3; do
    [ -n "$c" ] && command -v "$c" >/dev/null 2>&1 && in_range "$c" && { echo "$c"; return 0; }
  done
  return 1
}

fail() { echo; echo "ERROR: $*" >&2; exit 1; }

VV="$(venv_version || true)"
if [ -n "$VV" ]; then
  case "$VV" in 3.10|3.11|3.12|3.13) ;; *) echo "Existing .venv uses Python $VV (unsupported). Recreating it..."; rm -rf "$VENV"; VV="";; esac
elif [ -d "$VENV" ]; then
  echo "Existing .venv is incomplete. Recreating it..."; rm -rf "$VENV"
fi

if [ -z "$VV" ]; then
  PY="$(find_python)" || fail "No supported Python (3.10-3.13) found.
  Debian/Ubuntu: sudo apt install python3 python3-venv   (Debian 12 = 3.11, Ubuntu 24.04 = 3.12)
  Or install Python 3.13 from https://www.python.org/downloads/ and run again."
  echo "Creating .venv with $PY ($("$PY" --version 2>&1)) ..."
  if ! "$PY" -m venv "$VENV"; then
    rm -rf "$VENV"
    fail "Could not create a virtual environment. On Debian/Ubuntu run: sudo apt install python3-venv"
  fi
  "$VENV/bin/python" -m pip install --upgrade pip || { rm -rf "$VENV"; fail "pip upgrade failed (see output above)."; }
  "$VENV/bin/python" -m pip install --prefer-binary -e . || { rm -rf "$VENV"; fail "Installing dependencies failed (see output above). The .venv was removed."; }
fi

[ -f .env ] && set -a && . ./.env && set +a
if [ $# -eq 0 ]; then
  exec "$VENV/bin/python" -m cmllab web
else
  exec "$VENV/bin/python" -m cmllab "$@"
fi
