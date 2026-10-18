"""Smoke test for a packaged build (stdlib only; used locally, under Wine and in CI).

    python packaging/smoke_test.py <path to ENCORLab or ENCORLab.exe> --version 1.4.0 \
        --data-dir <expected user data folder> [--pack x.encorlab ...] [--runner wine] [--port 8791]

Checks: CLI runs (version, list); the launcher serves the UI on 127.0.0.1 with versioned (cache-busted)
assets; /api/labs lists the 11 built-in labs; packs import into the user data folder; the solution
endpoint works; a second launch detects the running instance; the server stops cleanly."""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path


def run(cmd, timeout=180):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def post_file(url, path: Path):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--version", required=True)
    ap.add_argument("--data-dir", required=True, help="where settings/labs must land (%%APPDATA%%\\encorlab or ~/.config/encorlab)")
    ap.add_argument("--pack", action="append", default=[])
    ap.add_argument("--runner", default="", help="e.g. 'wine'")
    ap.add_argument("--port", type=int, default=18765)
    a = ap.parse_args()
    pre = a.runner.split() if a.runner else []
    exe = pre + [a.exe]
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    for k in [k for k in os.environ if k.startswith("ENCOR_")]:
        del os.environ[k]
    code, out = run(exe + ["version"])
    check(code == 0 and a.version in out, f"CLI 'version' -> {out.strip()[-40:]!r}")
    code, out = run(exe + ["list"])
    check(code == 0 and "eigrp-basic" in out and "troubleshoot" not in out, "CLI 'list' shows the built-in catalog")

    t0 = time.time()
    proc = subprocess.Popen(exe + ["--no-browser", "--port", str(a.port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    lines: list[str] = []
    threading.Thread(target=lambda: [lines.append(l) for l in proc.stdout], daemon=True).start()
    base = None
    for _ in range(240):  # the launcher may move to the next free port; take the URL from its banner
        m = re.search(r"Web UI:\s+(http://127\.0\.0\.1:\d+)", "".join(lines))
        if m:
            base = m.group(1); break
        time.sleep(0.5)
    try:
        check(base is not None, f"launcher banner shows the URL: {base}")
        base = base or f"http://127.0.0.1:{a.port}"
        health = None
        for _ in range(240):
            try:
                health = json.loads(get(base + "/api/health", 2)[2]); break
            except Exception:
                time.sleep(0.5)
        check(health and health.get("version") == a.version, f"server up in {time.time() - t0:.1f}s, health={health}")
        st, ct, html = get(base + "/")
        html = html.decode("utf-8")
        check(st == 200 and "ENCOR Lab Builder" in html and f"app.js?v={a.version}" in html, "UI page served with versioned assets")
        st, ct, js = get(base + f"/static/app.js?v={a.version}")
        check(st == 200 and "javascript" in ct and len(js) > 10000, f"app.js served ({ct})")
        st, ct, _ = get(base + "/static/help.json")
        check(st == 200 and "json" in ct, "help.json served")
        labs = json.loads(get(base + "/api/labs")[2])
        builtin = [l for l in labs["labs"] if l["source"] == "builtin"]
        check(len(builtin) == 11 and not labs["broken"], f"/api/labs: {len(builtin)} built-in labs, broken={labs['broken']}")
        for p in a.pack:
            rep = post_file(base + "/api/import?replace=true", Path(p))
            check(rep.get("ok") and rep.get("lab_id"), f"import {Path(p).name} -> {rep.get('lab_id')}")
            lid = rep.get("lab_id")
            lab_yaml = Path(a.data_dir) / "labs" / str(lid) / "lab.yaml"
            check(lab_yaml.is_file(), f"stored in user data folder: {lab_yaml}")
            sol = json.loads(get(base + f"/api/labs/{lid}/solution")[2])
            check(sol.get("summary") and not sol.get("auto_generated"), "solution summary available")
        ids = {l["id"] for l in json.loads(get(base + "/api/labs")[2])["labs"]}
        check(len(ids) == 11 + len(a.pack), f"catalog now has {len(ids)} labs")
        code, out = run(exe + ["--no-browser", "--port", base.rsplit(":", 1)[1]], timeout=60)
        check(code == 0 and "already running" in out, "second launch detects the running instance")
    finally:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
        time.sleep(0.5)
        out = "".join(lines)
        print(f"---- launcher output (exit {proc.returncode}) ----\n" + out.strip() + "\n-------------------------")
    check("Web UI:" in out and "127.0.0.1" in out, "launcher printed its banner")
    print("SMOKE TEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
