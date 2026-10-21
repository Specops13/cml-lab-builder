"""A fake GitHub release on 127.0.0.1, for tests and the smoke test of the automatic updater.

    python packaging/fake_release.py --version 9.9.9 --file dist/cml-lab-builder-patch-9.9.9.zip [--port 0]

Serves /repos/<repo>/releases/latest (GitHub's JSON shape, with an ETag and 304 answers to If-None-Match) and
/download/<asset>; SHA256SUMS.txt is generated from the files. Point the app at it with
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


class FakeRelease:
    def __init__(self, version: str, files: dict[str, bytes], port: int = 0, sums: bool = True):
        self.version, self.files, self.port, self.with_sums = version, dict(files), port, sums
        self.requests: list[tuple[str, str | None, int]] = []   # (path, if-none-match, status)
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
        return out

    def release_json(self) -> bytes:
        a = self.assets()
        return json.dumps({
            "tag_name": f"v{self.version}", "name": f"CML Lab Builder {self.version}",
            "html_url": f"https://github.com/{REPO}/releases/tag/v{self.version}",
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "body": "fake release",
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
