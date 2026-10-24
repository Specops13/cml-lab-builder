"""Update authenticity: detached Ed25519 signatures (since 3.3.0).

Every release carries SHA256SUMS.txt (sha256 of every asset) and SHA256SUMS.txt.sig, a detached Ed25519 signature of
that file made with the project's release key; the app patch also gets <patch>.zip.sig. The app trusts only the public
keys embedded below, so a patch is installed only if SHA256SUMS.txt is signed by a trusted key AND the patch matches it.
Apps before 3.3.0 keep using SHA256SUMS.txt alone (the .sig files are extra assets they ignore).

Signature file format (UTF-8 JSON): {"format": 1, "alg": "ed25519", "key_id": "<16 hex>", "sig": "<base64, 64 bytes>"}.
key_id = first 16 hex digits of sha256(raw 32-byte public key).

Key rotation (see SECURITY.md): ship a release signed with the current key that adds the new public key to
TRUSTED_KEYS, then sign later releases with the new key; remove a retired key in a later release. A compromised key
is removed in the next release (signed by a key that is still trusted).

Verification is pure Python (RFC 8032), so it needs nothing from the frozen runtime (patches stay on runtime 2)."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from urllib.parse import urlparse

FORMAT = 1
# raw Ed25519 public keys (hex) trusted for releases; the private key never leaves the maintainer's machine
TRUSTED_KEYS = {
    "release-2026": "48f799c3e8938c8be616cde0c4c8bf1927aeea8ab9f5b8cd310efa04e294c6be",
}
SIG_SUFFIX = ".sig"
MAX_SIG_BYTES = 4096
# Test key for the packaged smoke tests only: honoured solely while CMLLAB_UPDATE_URL points at this computer
# (a fake release on 127.0.0.1); real update checks against GitHub only trust TRUSTED_KEYS.
TEST_KEY_ENV = "CMLLAB_UPDATE_TEST_KEY"


class SignatureError(ValueError):
    pass


def key_id(pub: bytes) -> str:
    return hashlib.sha256(pub).hexdigest()[:16]


def _loopback_update_url() -> bool:
    from . import paths
    u = paths.env_get("UPDATE_URL") or ""
    try:
        return urlparse(u).hostname in ("127.0.0.1", "localhost", "::1")
    except ValueError:
        return False


def trusted_keys() -> dict[str, bytes]:
    keys = {key_id(bytes.fromhex(h)): bytes.fromhex(h) for h in TRUSTED_KEYS.values()}
    test = os.environ.get(TEST_KEY_ENV, "").strip()
    if test and _loopback_update_url():
        try:
            raw = bytes.fromhex(test)
            if len(raw) == 32:
                keys[key_id(raw)] = raw
        except ValueError:
            pass
    return keys


# ------------------------------------------------------------------ Ed25519 verification (RFC 8032, section 5.1.7)
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A = (y1 - x1) * (y2 - x2) % _P
    B = (y1 + x1) * (y2 + x2) % _P
    C = 2 * t1 * t2 * _D % _P
    D = 2 * z1 * z2 % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s: int, pt):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


def _decompress(b: bytes):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _compress(pt) -> bytes:
    x, y, z, _ = pt
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_recover_x(_GY, 0), _GY, 1, _recover_x(_GY, 0) * _GY % _P)


def ed25519_verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    if len(pub) != 32 or len(sig) != 64:
        return False
    A = _decompress(pub)
    R = _decompress(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(), "little") % _L
    return _compress(_mul(s, _G)) == _compress(_add(R, _mul(h, A)))


# ------------------------------------------------------------------ signature files
def parse_sig(raw: bytes) -> tuple[str, bytes]:
    if len(raw) > MAX_SIG_BYTES:
        raise SignatureError("signature file is too large")
    try:
        d = json.loads(raw.decode("utf-8"))
        if not isinstance(d, dict) or d.get("format") != FORMAT or d.get("alg") != "ed25519":
            raise ValueError
        sig = base64.b64decode(str(d["sig"]), validate=True)
        kid = str(d["key_id"])
    except (ValueError, KeyError, UnicodeDecodeError):
        raise SignatureError("signature file has an unknown format")
    if len(sig) != 64:
        raise SignatureError("signature has the wrong length")
    return kid, sig


def verify(data: bytes, sig_raw: bytes | None, what: str = "file") -> str:
    """Raise SignatureError unless sig_raw is a valid signature of data by a trusted key; returns the key id."""
    if not sig_raw:
        raise SignatureError(f"{what} is not signed: since 3.3.0 only updates signed with the project's release key "
                             "are installed. Download the full release from the GitHub release page instead.")
    kid, sig = parse_sig(sig_raw)
    pub = trusted_keys().get(kid)
    if pub is None:
        raise SignatureError(f"{what} is signed with an unknown key ({kid}); nothing was installed")
    if not ed25519_verify(pub, data, sig):
        raise SignatureError(f"the signature of {what} is not valid (tampered or corrupted download); nothing was installed")
    return kid


def sign(private_pem: bytes, data: bytes) -> bytes:
    """Release tooling only (needs the `cryptography` package and the private key, which the app never has)."""
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(private_pem, None)
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return (json.dumps({"format": FORMAT, "alg": "ed25519", "key_id": key_id(pub),
                        "sig": base64.b64encode(key.sign(data)).decode()}, indent=1) + "\n").encode()
