"""A fake GitHub release on 127.0.0.1, for tests and the smoke test of the automatic updater.

    python packaging/fake_release.py --version 9.9.9 --file dist/cml-lab-builder-patch-9.9.9.zip [--port 0]

Serves /repos/<repo>/releases/latest (GitHub's JSON shape, with an ETag and 304 answers to If-None-Match) and
/download/<asset>; SHA256SUMS.txt is generated from the files, and signed (SHA256SUMS.txt.sig, see cmllab/signing.py)
when a test key is given (test_key() makes one; the app trusts it via CMLLAB_UPDATE_TEST_KEY while CMLLAB_UPDATE_URL
points at 127.0.0.1). Point the app at it with
CMLLAB_UPDATE_URL=http://127.0.0.1:<port>/repos/Specops13/cml-lab-builder/releases/latest."""
from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = "Specops13/cml-lab-builder"   # renamed from encore-lab-app in 2.1.0 (GitHub redirects the old name)


# ---- Ed25519 signing in pure Python (RFC 8032), so the test machines need no extra package (the deb test chroot has a
# bare python3). For throwaway test keys only: real releases are signed by release.py with the `cryptography` package.
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A, B = (y1 - x1) * (y2 - x2) % _P, (y1 + x1) * (y2 + x2) % _P
    C, D = 2 * t1 * t2 * _D % _P, 2 * z1 * z2 % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s, pt):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, pt)
        pt, s = _add(pt, pt), s >> 1
    return q


def _enc(pt) -> bytes:
    x, y, z, _ = pt
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX2 = (_GY * _GY - 1) * pow(_D * _GY * _GY + 1, _P - 2, _P) % _P
_GX = pow(_GX2, (_P + 3) // 8, _P)
if (_GX * _GX - _GX2) % _P:
    _GX = _GX * pow(2, (_P - 1) // 4, _P) % _P
if _GX & 1:
    _GX = _P - _GX
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _expand(seed: bytes):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a = (a & ((1 << 254) - 8)) | (1 << 254)
    return a, h[32:]


def public_key(seed: bytes) -> bytes:
    return _enc(_mul(_expand(seed)[0], _G))


def sign(seed: bytes, data: bytes) -> bytes:
    """Detached signature file (the format of cmllab/signing.py) for data, with the 32-byte private seed."""
    import base64
    a, prefix = _expand(seed)
    pub = _enc(_mul(a, _G))
    r = int.from_bytes(hashlib.sha512(prefix + data).digest(), "little") % _L
    R = _enc(_mul(r, _G))
    k = int.from_bytes(hashlib.sha512(R + pub + data).digest(), "little") % _L
    sig = R + int.to_bytes((r + k * a) % _L, 32, "little")
    return (json.dumps({"format": 1, "alg": "ed25519", "key_id": hashlib.sha256(pub).hexdigest()[:16],
                        "sig": base64.b64encode(sig).decode()}, indent=1) + "\n").encode()


def test_key() -> tuple[bytes, str]:
    """A throwaway key: (32-byte private seed, public key hex for CMLLAB_UPDATE_TEST_KEY)."""
    import os
    seed = os.urandom(32)
    return seed, public_key(seed).hex()


class FakeRelease:
    def __init__(self, version: str, files: dict[str, bytes], port: int = 0, sums: bool = True,
                 key: bytes | None = None):
        self.version, self.files, self.port, self.with_sums = version, dict(files), port, sums
        self.key = key   # private seed (test_key()): adds SHA256SUMS.txt.sig
        self.requests: list[tuple[str, str | None, int]] = []   # (path, if-none-match, status)
        self.published_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())   # fixed: stable ETag
        self._srv: ThreadingHTTPServer | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self._srv.server_address[1]}"

    @property
    def url(self) -> str:
        return f"{self.base}/repos/{REPO}/releases/latest"

    def assets(self) -> dict[str, bytes]:
        out = dict(self.files)
        if self.with_sums:
            out["SHA256SUMS.txt"] = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in self.files.items()).encode()
            if self.key:
                out["SHA256SUMS.txt.sig"] = sign(self.key, out["SHA256SUMS.txt"])
        return out

    def release_json(self) -> bytes:
        a = self.assets()
        return json.dumps({
            "tag_name": f"v{self.version}", "name": f"CML Lab Builder {self.version}",
            "html_url": f"https://github.com/{REPO}/releases/tag/v{self.version}",
            "published_at": self.published_at, "body": "fake release",
            "assets": [{"name": n, "size": len(b), "browser_download_url": f"{self.base}/download/{n}"} for n, b in a.items()],
        }, sort_keys=True).encode()

    def start(self) -> "FakeRelease":
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, body: bytes = b"", headers: dict | None = None):
                fake.requests.append((self.path, self.headers.get("If-None-Match"), code))
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_GET(self):
                if self.path == f"/repos/{REPO}/releases/latest":
                    body = fake.release_json()
                    etag = '"' + hashlib.sha256(body).hexdigest()[:20] + '"'
                    if self.headers.get("If-None-Match") == etag:
                        return self._send(304, headers={"ETag": etag})
                    return self._send(200, body, {"ETag": etag, "Content-Type": "application/json"})
                if self.path.startswith("/download/"):
                    a = fake.assets().get(self.path[len("/download/"):])
                    if a is not None:
                        return self._send(200, a, {"Content-Type": "application/octet-stream"})
                return self._send(404)

        self._srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()
    f = FakeRelease(a.version, {Path(p).name: Path(p).read_bytes() for p in a.file}, a.port).start()
    print(f"CMLLAB_UPDATE_URL={f.url}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        f.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
