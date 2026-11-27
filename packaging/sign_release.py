"""Sign a release (3.3.9+): detached Ed25519 signatures for SHA256SUMS.txt and the app patch (see SECURITY.md).

    python packaging/sign_release.py --dist DIR [--optional]

The private key (PEM) comes from the RELEASE_SIGNING_KEY environment variable (the GitHub Actions secret of the same
name), never from a file in the repository. Before writing DIR/SHA256SUMS.txt.sig and DIR/cml-lab-builder-patch-<v>.zip.sig
it checks that the patch matches SHA256SUMS.txt and that every new signature verifies against the keys the app trusts
(cmllab.signing.TRUSTED_KEYS), so a wrong or retired key fails the release instead of shipping updates nobody can
install. --optional: no key set -> print a warning and exit 0 (forks and repos without the secret still release).
Needs the `cryptography` package."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cmllab import signing  # noqa: E402

KEY_ENV = "RELEASE_SIGNING_KEY"


def _sums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            out[parts[1].lstrip("*")] = parts[0].lower()
    return out


def public_hex(private_pem: bytes) -> str:
    """The raw Ed25519 public key of a PEM private key (safe to print: it is what TRUSTED_KEYS holds)."""
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(private_pem, None)
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def sign_dist(dist: Path, private_pem: bytes) -> list[Path]:
    """Sign SHA256SUMS.txt and the patch zip(s) in dist; returns the .sig files written."""
    sums_file = dist / "SHA256SUMS.txt"
    if not sums_file.is_file():
        raise SystemExit(f"{sums_file} not found")
    sums_data = sums_file.read_bytes()
    sums = _sums(sums_data.decode("utf-8"))
    patches = sorted(dist.glob("cml-lab-builder-patch-*.zip"))
    if not patches:
        raise SystemExit(f"no cml-lab-builder-patch-*.zip in {dist}")
    targets = [(sums_file, sums_data)]
    for p in patches:
        data = p.read_bytes()
        if sums.get(p.name) != hashlib.sha256(data).hexdigest():
            raise SystemExit(f"{p.name} does not match SHA256SUMS.txt")
        targets.append((p, data))
    written = []
    for path, data in targets:
        sig = signing.sign(private_pem, data)
        try:
            kid = signing.verify(data, sig, path.name)
        except signing.SignatureError as e:
            raise SystemExit(f"refusing to sign with a key the app does not trust: {e}\n"
                             f"public key of RELEASE_SIGNING_KEY (raw Ed25519, hex): {public_hex(private_pem)}\n"
                             "add it to TRUSTED_KEYS in cmllab/signing.py (key rotation, SECURITY.md)") from None
        out = path.with_name(path.name + signing.SIG_SUFFIX)
        out.write_bytes(sig)
        written.append(out)
        print(f"signed {path.name} (key {kid})")
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", required=True, type=Path)
    ap.add_argument("--optional", action="store_true", help="no key: warn and exit 0")
    a = ap.parse_args(argv)
    pem = os.environ.get(KEY_ENV, "").strip()
    if not pem:
        msg = f"{KEY_ENV} is not set: the release is NOT signed and installed apps will not install it as an update"
        if a.optional:
            print(f"::warning::{msg}")
            return 0
        raise SystemExit(msg)
    sign_dist(a.dist, (pem + "\n").encode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
