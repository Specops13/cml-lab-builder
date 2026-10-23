#!/bin/bash
# The deb end-to-end test (deb_chroot_inner.sh) in a fresh, pinned Debian 12 container (CI's deb-test job).
#   packaging/deb_docker_test.sh <cml-lab-builder_X_amd64.deb> [<encorlab_2.x_amd64.deb>]
# The image is pinned by digest (DEB_TEST_IMAGE overrides it), the repo is mounted read-only at /src and the test
# packages at /tmp/debtest; the container gets nothing else. The only network use is apt (with retries).
set -euo pipefail
IMAGE=${DEB_TEST_IMAGE:-debian:12@sha256:854dd8ab51d62866dbd8f5431d15ce77b12983a2a4a1e1fe43a2395dc7ef9f61}
DEB=$(realpath "$1"); OLDDEB=${2:+$(realpath "$2")}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d /tmp/debtest-XXXX); trap 'rm -rf "$WORK"' EXIT
"$ROOT/packaging/deb_test_prep.sh" "$DEB" "$WORK/debs" ${OLDDEB:+"$OLDDEB"}
. "$WORK/debs/env.sh"
chmod -R a+rX "$WORK/debs"
for i in 1 2 3; do docker pull -q "$IMAGE" && break; sleep $((i * 10)); done
docker run --rm -v "$ROOT:/src:ro" -v "$WORK/debs:/tmp/debtest:ro" -e VER="$VER" -e UP1="$UP1" -e UP2="$UP2" -e PV="$PV" \
    "$IMAGE" bash /src/packaging/deb_chroot_inner.sh
