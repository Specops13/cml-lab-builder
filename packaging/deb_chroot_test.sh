#!/bin/bash
# End-to-end test of the .deb in a clean Debian chroot (run on the host with sudo available).
#   packaging/deb_chroot_test.sh <debian-12-chroot> <cml-lab-builder_X_amd64.deb> [<encorlab_2.x_amd64.deb>]
# CI runs the same checks (deb_chroot_inner.sh) in a pinned debian:12 container: packaging/deb_docker_test.sh.
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
cleanup() { set +e; for m in src tmp/debtest dev/pts dev sys proc; do sudo umount -l "$CHROOT/$m" 2>/dev/null; done; rm -rf "$WORK"; }
trap cleanup EXIT
"$ROOT/packaging/deb_test_prep.sh" "$DEB" "$WORK/debs" ${OLDDEB:+"$OLDDEB"}
. "$WORK/debs/env.sh"
sudo mkdir -p "$CHROOT/src" "$CHROOT/tmp/debtest"
sudo mount -t proc proc "$CHROOT/proc"; sudo mount --rbind /sys "$CHROOT/sys"; sudo mount --bind /dev "$CHROOT/dev"; sudo mount --bind /dev/pts "$CHROOT/dev/pts"
sudo mount --bind "$ROOT" "$CHROOT/src"; sudo mount -o remount,bind,ro "$CHROOT/src"
sudo mount --bind "$WORK/debs" "$CHROOT/tmp/debtest"
sudo cp /etc/resolv.conf "$CHROOT/etc/resolv.conf"
sudo chroot "$CHROOT" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root VER="$VER" UP1="$UP1" UP2="$UP2" PV="$PV" bash /src/packaging/deb_chroot_inner.sh
