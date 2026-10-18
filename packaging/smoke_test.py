"""Smoke test for a packaged build (stdlib only; used locally, under Wine and in CI).

    python packaging/smoke_test.py <path to ENCORLab or ENCORLab.exe> --version 1.6.0 \
        --data-dir <expected user data folder> [--pack x.encorlab ...] [--runner wine] [--port 8791] [--patch-test]

Checks: CLI runs (version, list); the launcher serves the UI on 127.0.0.1 with versioned (cache-busted)
assets; /api/labs lists all built-in labs; packs import into the user data folder; the solution
endpoint works; a second launch detects the running instance; the server stops cleanly.
--patch-test also builds test patches from this source tree and checks, on the frozen build: installing a patch
(the next start runs it), the web UI on a patched build, rollback, automatic fallback from a patch that fails
to import, and refusal of a patch that needs a newer runtime. It removes the installed test patches at the end."""
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

ROOT = Path(__file__).resolve().parents[1]
BUILTIN = len([d for d in (ROOT / "encorlab" / "labs").iterdir() if (d / "lab.yaml").is_file()])


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


def make_patch(tmp: Path, version: str, broken: bool = False, min_runtime: int | None = None) -> Path:
    import shutil
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_patch
    src = tmp / f"src-{version}"
    shutil.copytree(ROOT / "encorlab", src / "encorlab", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    init = src / "encorlab" / "__init__.py"
    text = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', init.read_text(encoding="utf-8"))
    if broken:
        text += '\nraise RuntimeError("smoke test: deliberately broken patch")\n'
    init.write_text(text, encoding="utf-8")
    return build_patch.build_patch(src, tmp / "out", version, min_runtime)


def patch_tests(exe, version: str, data_dir: Path, port: int, check) -> None:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="encor-smoke-"))
    try:
        good = make_patch(tmp, "99.0.0")
        check(good.stat().st_size < 2_000_000, f"test patch built ({good.stat().st_size // 1024} KB)")
        code, out = run(exe + ["update-install", "--file", str(good)])
        check(code == 0 and "Installed 99.0.0" in out, f"update-install --file -> {out.strip()[-80:]!r}")
        check((data_dir / "app" / "99.0.0" / "encorlab" / "__init__.py").is_file(), "patch extracted to <data>/app/99.0.0")
        code, out = run(exe + ["version"])
        check(code == 0 and out.strip().endswith("99.0.0"), f"next start runs the patch: version -> {out.strip()[-20:]!r}")
        code, out = run(exe + ["update-status"])
        check(code == 0 and "Installed update: 99.0.0" in out and "(installed)" in out, "update-status shows the installed patch")
        # GUI start on the patched code: serves the UI and confirms the patch
        proc = subprocess.Popen(exe + ["--no-browser", "--port", str(port)], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        lines: list[str] = []
        threading.Thread(target=lambda: [lines.append(l) for l in proc.stdout], daemon=True).start()
        health = None
        try:
            for _ in range(240):
                m = re.search(r"Web UI:\s+(http://127\.0\.0\.1:\d+)", "".join(lines))
                if m:
                    try:
                        health = json.loads(get(m.group(1) + "/api/health", 2)[2]); break
                    except Exception:
                        pass
                time.sleep(0.5)
            check(health and health.get("version") == "99.0.0", f"patched web UI is up: {health}")
            time.sleep(1.5)
            st = json.loads((data_dir / "app" / "state.json").read_text(encoding="utf-8"))
            check(st.get("current") == "99.0.0" and not st.get("pending"), "patch marked good after the UI started")
        finally:
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            except OSError:
                proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
        code, out = run(exe + ["update-rollback"])
        check(code == 0 and "Rolled back" in out, f"update-rollback -> {out.strip()[-60:]!r}")
        code, out = run(exe + ["version"])
        check(code == 0 and out.strip().endswith(version), f"after rollback: version -> {out.strip()[-20:]!r}")
        bad = make_patch(tmp, "99.0.1", broken=True)
        code, out = run(exe + ["update-install", "--file", str(bad)])
        check(code == 0 and "Installed 99.0.1" in out, "a patch that fails to import still installs (it is valid)")
        code, out = run(exe + ["version"])
        check(code == 0 and out.strip().endswith(version), f"broken patch -> automatic fallback: version -> {out.strip()[-20:]!r}")
        st = json.loads((data_dir / "app" / "state.json").read_text(encoding="utf-8"))
        check((st.get("failed") or {}).get("version") == "99.0.1" and st.get("current") != "99.0.1",
              f"broken patch recorded as failed: {st.get('failed')}")
        newer = make_patch(tmp, "99.0.2", min_runtime=999)
        code, out = run(exe + ["update-install", "--file", str(newer)])
        check(code == 0 and "Full download needed" in out and not (data_dir / "app" / "99.0.2").exists(),
              "a patch that needs a newer runtime is refused")
    finally:
        shutil.rmtree(data_dir / "app", ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--version", required=True)
    ap.add_argument("--data-dir", required=True, help="where settings/labs must land (%%APPDATA%%\\encorlab or ~/.config/encorlab)")
    ap.add_argument("--pack", action="append", default=[])
    ap.add_argument("--runner", default="", help="e.g. 'wine'")
    ap.add_argument("--port", type=int, default=18765)
    ap.add_argument("--patch-test", action="store_true")
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
        check(len(builtin) == BUILTIN and not labs["broken"], f"/api/labs: {len(builtin)} built-in labs, broken={labs['broken']}")
        for p in a.pack:
            rep = post_file(base + "/api/import?replace=true", Path(p))
            check(rep.get("ok") and rep.get("lab_id"), f"import {Path(p).name} -> {rep.get('lab_id')}")
            lid = rep.get("lab_id")
            lab_yaml = Path(a.data_dir) / "labs" / str(lid) / "lab.yaml"
            check(lab_yaml.is_file(), f"stored in user data folder: {lab_yaml}")
            sol = json.loads(get(base + f"/api/labs/{lid}/solution")[2])
            check(sol.get("summary") and not sol.get("auto_generated"), "solution summary available")
        ids = {l["id"] for l in json.loads(get(base + "/api/labs")[2])["labs"]}
        check(len(ids) == BUILTIN + len(a.pack), f"catalog now has {len(ids)} labs")
        code, out = run(exe + ["--no-browser", "--port", base.rsplit(":", 1)[1]], timeout=60)
        check(code == 0 and "already running" in out, "second launch detects the running instance")
    finally:
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        except OSError:  # e.g. CTRL_BREAK unsupported (Wine): fall back to terminate
            proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
        time.sleep(0.5)
        out = "".join(lines)
        print(f"---- launcher output (exit {proc.returncode}) ----\n" + out.strip() + "\n-------------------------")
    check("Web UI:" in out and "127.0.0.1" in out, "launcher printed its banner")
    if a.patch_test:
        patch_tests(exe, a.version, Path(a.data_dir), a.port + 1, check)
    print("SMOKE TEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
