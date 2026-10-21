"""Smoke test for a packaged build (stdlib only; used locally, under Wine and in CI).

    python packaging/smoke_test.py <path to ENCORLab or ENCORLab.exe> --version 1.6.0 \
        --data-dir <expected user data folder> [--pack x.encorlab ...] [--runner wine] [--port 8791] [--patch-test]

Checks: CLI runs (version, list); the launcher serves the UI on 127.0.0.1 with versioned (cache-busted)
assets; a first run has no labs (2.0.0 ships none) and no migration to do; the lab library is served from this
source tree's labs/ on 127.0.0.1 (ENCOR_LIBRARY_URL): the starter set and a course (with the labs it lists)
install from it; packs import into the user data folder; the solution endpoint works; a second launch detects
the running instance; the server stops cleanly.
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
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "labs"


def serve_library(folder: Path = LIBRARY):
    """Serve a library folder (index.json + packs) on 127.0.0.1; returns (server, index URL)."""
    import functools
    import http.server
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    h.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/index.json"


def post_body(url, body: dict, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode("utf-8", "replace")[:300]}


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


def patch_tests(exe, version: str, data_dir: Path, port: int, check, boot_dir: Path | None = None) -> None:
    boot_dir = boot_dir or data_dir
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="encor-smoke-"))
    try:
        good = make_patch(tmp, "99.0.0")
        check(good.stat().st_size < 2_000_000, f"test patch built ({good.stat().st_size // 1024} KB)")
        code, out = run(exe + ["update-install", "--file", str(good)])
        check(code == 0 and "Installed 99.0.0" in out, f"update-install --file -> {out.strip()[-80:]!r}")
        check((boot_dir / "app" / "99.0.0" / "encorlab" / "__init__.py").is_file(), "patch extracted to <data>/app/99.0.0")
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
            st = json.loads((boot_dir / "app" / "state.json").read_text(encoding="utf-8"))
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
        st = json.loads((boot_dir / "app" / "state.json").read_text(encoding="utf-8"))
        check((st.get("failed") or {}).get("version") == "99.0.1" and st.get("current") != "99.0.1",
              f"broken patch recorded as failed: {st.get('failed')}")
        newer = make_patch(tmp, "99.0.2", min_runtime=999)
        code, out = run(exe + ["update-install", "--file", str(newer)])
        check(code == 0 and "Full download needed" in out and not (boot_dir / "app" / "99.0.2").exists(),
              "a patch that needs a newer runtime is refused")
    finally:
        shutil.rmtree(boot_dir / "app", ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def post_json(url, timeout=15):
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def auto_update_test(exe, version: str, data_dir: Path, port: int, check, pre, boot_dir: Path | None = None) -> None:
    boot_dir = boot_dir or data_dir
    """End to end against a fake release served on 127.0.0.1: background check -> staged (not installed) -> prompt
    -> Update now waits for a running exam -> installs -> restarts on the same port -> 'Updated to' state."""
    import shutil
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fake_release import FakeRelease
    tmp = Path(tempfile.mkdtemp(prefix="encor-auto-"))
    new = "99.2.0"
    fake = FakeRelease(new, {f"encorlab-patch-{new}.zip": make_patch(tmp, new).read_bytes()}).start()
    env = dict(os.environ, ENCOR_UPDATE_URL=fake.url, ENCOR_UPDATE_DELAY="1")
    proc = subprocess.Popen(exe + ["--no-browser", "--port", str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env,
                            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    lines: list[str] = []
    threading.Thread(target=lambda: [lines.append(l) for l in proc.stdout], daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        st = None
        for _ in range(120):
            try:
                st = json.loads(get(base + "/api/update/auto", 3)[2])
                if st.get("offer"):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        check(st and st.get("enabled") and (st.get("offer") or {}).get("version") == new,
              f"background check found and staged {new}: offer={st and st.get('offer')}")
        check(not (boot_dir / "app" / new).exists() and (data_dir / "updates" / "staged" / f"encorlab-patch-{new}.zip").is_file(),
              "patch downloaded + verified into updates/staged, not installed")
        labs = json.loads(get(base + "/api/labs")[2])
        lab_id = sorted(x["id"] for x in labs["labs"] if not x.get("walkthrough"))[0]
        post_json(f"{base}/api/labs/{lab_id}/exam/start")
        a = post_json(f"{base}/api/update/apply?version={new}")
        check(a.get("state") == "waiting" and any("exam" in w for w in a.get("waiting_for", [])),
              f"Update now waits for the running exam: {a.get('waiting_for')}")
        time.sleep(3)
        h = json.loads(get(base + "/api/health")[2])
        check(h.get("version") == version and not (boot_dir / "app" / new).exists(), "nothing installed while the exam runs")
        post_json(f"{base}/api/labs/{lab_id}/exam/abort")
        health = None
        for _ in range(180):
            try:
                health = json.loads(get(base + "/api/health", 2)[2])
                if health.get("version") == new:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        check(health and health.get("version") == new, f"installed and restarted on the same port: {health}")
        st = json.loads(get(base + "/api/update/auto")[2])
        check((st.get("just_updated") or {}).get("version") == new, f"page gets 'Updated to {new}': {st.get('just_updated')}")
        time.sleep(1.5)
        boot = json.loads((boot_dir / "app" / "state.json").read_text(encoding="utf-8"))
        check(boot.get("current") == new and not boot.get("pending"), "new version confirmed by the boot loader")
        etags = [r for r in fake.requests if r[0].endswith("/releases/latest")]
        check(bool(etags) and etags[0][1] is None, f"release API polled ({len(etags)} request(s))")
    finally:
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            proc.wait(timeout=20)
        except Exception:
            proc.kill()
        if os.name == "nt" or pre:   # Windows: the restarted app runs in a new console (not our child)
            subprocess.run(pre + ["taskkill", "/F", "/IM", "ENCORLab.exe"], capture_output=True, timeout=60)
        fake.stop()
        code, out = run(exe + ["update-rollback"])
        check(code == 0 and "Rolled back" in out, "update-rollback after the auto update")
        shutil.rmtree(boot_dir / "app", ignore_errors=True)
        shutil.rmtree(data_dir / "updates", ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--version", required=True)
    ap.add_argument("--data-dir", required=True, help="where settings/labs must land (%%APPDATA%%\\cml-lab-builder or ~/.config/cml-lab-builder; "
                    "encorlab for builds before 2.1.0)")
    ap.add_argument("--boot-dir", help="where the boot loader keeps app/ (default: the encorlab folder next to a "
                    "cml-lab-builder data folder, else the data folder)")
    ap.add_argument("--pack", action="append", default=[])
    ap.add_argument("--runner", default="", help="e.g. 'wine'")
    ap.add_argument("--port", type=int, default=18765)
    ap.add_argument("--patch-test", action="store_true")
    ap.add_argument("--auto-update-test", action="store_true")
    a = ap.parse_args()
    dd = Path(a.data_dir)
    boot = Path(a.boot_dir) if a.boot_dir else (dd.with_name("encorlab") if dd.name == "cml-lab-builder" else dd)
    global LIBRARY
    new_names = tuple(int(x) for x in a.version.split(".")[:2]) >= (2, 1)
    if new_names:                     # 2.1+: the library with .cmllab/.cmlcourse files (labs/ keeps the old names)
        LIBRARY = ROOT / "library"
    pre = a.runner.split() if a.runner else []
    exe = pre + [a.exe]
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    for k in [k for k in os.environ if k.startswith(("ENCOR_", "CMLLAB_"))]:
        del os.environ[k]
    code, out = run(exe + ["version"])
    check(code == 0 and a.version in out, f"CLI 'version' -> {out.strip()[-40:]!r}")
    code, out = run(exe + ["list"])
    check(code == 0 and "no labs installed yet" in out and "eigrp-basic" not in out, "CLI 'list' on a first run: no labs, points to the library")
    lib_srv, lib_url = serve_library(LIBRARY)
    index = json.loads((LIBRARY / "index.json").read_text(encoding="utf-8"))
    packs_given = a.pack or [str(LIBRARY / ("troubleshoot-ospf-7node.cmllab" if new_names else "troubleshoot-ospf-7node.encorlab"))]

    t0 = time.time()
    proc = subprocess.Popen(exe + ["--no-browser", "--port", str(a.port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=dict(os.environ, ENCOR_LIBRARY_URL=lib_url),
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
        check(st == 200 and "CML Lab Builder" in html and f"app.js?v={a.version}" in html, "UI page served with versioned assets")
        st, ct, js = get(base + f"/static/app.js?v={a.version}")
        check(st == 200 and "javascript" in ct and len(js) > 10000, f"app.js served ({ct})")
        st, ct, _ = get(base + "/static/help.json")
        check(st == 200 and "json" in ct, "help.json served")
        labs = json.loads(get(base + "/api/labs")[2])
        check(labs["labs"] == [] and not labs["broken"], f"first run: no labs, broken={labs['broken']}")
        mig = labs.get("migration") or {}
        check(mig.get("state") == "done" and mig.get("fresh"), f"first run: nothing to migrate ({mig})")
        lib = json.loads(get(base + "/api/library", 30)[2])
        check(len(lib.get("items", [])) == len(index["items"]) and lib.get("starter") == index["starter"],
              f"library served from 127.0.0.1: {len(lib.get('items', []))} items, starter={lib.get('starter')}")
        check(all(i.get("size") and (i["kind"] == "course" or i.get("ram_gb")) for i in lib.get("items", [])),
              "library items carry sizes and RAM estimates")
        r = post_body(base + "/api/library/install-set", {"starter": True})
        check(r.get("ok") and sorted(r.get("installed", [])) == sorted(index["starter"]), f"Install starter set -> {r}")
        ids = {l["id"]: l for l in json.loads(get(base + "/api/labs")[2])["labs"]}
        check(set(ids) == set(index["starter"]) and all(l["source"] == "user" for l in ids.values()),
              f"starter labs installed into the user labs folder: {sorted(ids)}")
        check(all((Path(a.data_dir) / "labs" / lid / ".library.json").is_file() for lid in ids), "library origin recorded")
        course = next(i for i in index["items"] if i["file"] == ("data-center.cmlcourse" if new_names else "data-center.encorcourse"))
        r = post_body(base + "/api/library/install", {"file": course["file"]})
        check(r.get("kind") == "course" and set(course["labs"]) <= set(r.get("installed", [])),
              f"course Install all -> course + its labs from the library: {r.get('installed')}")
        cs = json.loads(get(base + "/api/courses")[2])["courses"]
        check(any(c["id"] == "data-center" and all(l["available"] for l in c["labs"]) for c in cs), "course listed with all labs available")
        evpn = next((l for l in json.loads(get(base + "/api/labs")[2])["labs"] if l["id"] == "18-evpn-vxlan"), {})
        check(evpn.get("ram", {}).get("heavy") and evpn.get("type") == "walkthrough", "EVPN walkthrough installed, tagged RAM heavy")
        n_before = len(json.loads(get(base + "/api/labs")[2])["labs"])
        for p in packs_given:
            rep = post_file(base + "/api/import?replace=true", Path(p))
            check(rep.get("ok") and rep.get("lab_id"), f"import {Path(p).name} -> {rep.get('lab_id')}")
            lid = rep.get("lab_id")
            lab_yaml = Path(a.data_dir) / "labs" / str(lid) / "lab.yaml"
            check(lab_yaml.is_file(), f"stored in user data folder: {lab_yaml}")
            sol = json.loads(get(base + f"/api/labs/{lid}/solution")[2])
            check(sol.get("summary") and not sol.get("auto_generated"), "solution summary available")
        ids = {l["id"] for l in json.loads(get(base + "/api/labs")[2])["labs"]}
        check(len(ids) == n_before + len(packs_given), f"catalog now has {len(ids)} labs")
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
    code, out = run(exe + ["list"])
    check(code == 0 and "eigrp-basic" in out and "18-evpn-vxlan" in out, "CLI 'list' shows the installed labs")
    lib_srv.shutdown()
    if a.patch_test:
        patch_tests(exe, a.version, Path(a.data_dir), a.port + 1, check, boot)
    if a.auto_update_test:
        auto_update_test(exe, a.version, Path(a.data_dir), a.port + 2, check, pre, boot)
    print("SMOKE TEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
