"""End-to-end test of the 1.x -> 2.x lab migration on real packaged builds (stdlib only; Linux, or Windows under Wine).

    python packaging/migration_test.py --old <unpacked 1.9.x build> --new <unpacked 2.x build> --patch <2.x patch zip>
        --data-dir <user data folder the builds use> [--runner wine] [--port 18800]

The data folder must be empty (or absent); it is wiped between the scenarios.
A) Update by patch: a 1.9 user (settings, results history, a walkthrough in progress, a snapshot, an active fault, an
   imported pack) installs the 2.x patch into the 1.9 build. On the first 2.x start every formerly bundled lab is copied
   from the old program files into the user labs folder; nothing in the data folder changes; scores link up by lab id.
B) Update by full download: the same user starts a fresh 2.x build (no old program files). The labs are restored from
   a library served on 127.0.0.1 in the background; until then the app runs normally and nothing is lost."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from smoke_test import LIBRARY, get, run, serve_library  # noqa: E402

LEGACY = 19
DATA_DIRS = ("history", "walkthroughs", "snapshots", "faults")


def seed(exe, data: Path, check) -> dict:
    """What a 1.9 user has in the data folder."""
    code, out = run(exe + ["list"])
    n = len([l for l in out.splitlines() if re.match(r"^[a-z0-9][a-z0-9-]+\s+builtin\s", l)])
    check(code == 0 and n == LEGACY, f"old build lists {n} built-in labs")
    code, out = run(exe + ["import", str(LIBRARY / "troubleshoot-ospf-7node.encorlab")])
    check(code == 0, f"old build imports a pack: {out.strip()[-60:]!r}")
    (data / "settings.json").write_text(json.dumps({"_format": 2, "cml_url": "https://cml.example.ts.net",
                                                    "username": "dylan", "check_updates": False}), encoding="utf-8")
    w = lambda rel, obj: ((data / rel).parent.mkdir(parents=True, exist_ok=True), (data / rel).write_text(json.dumps(obj), encoding="utf-8"))
    w("history/03-ospf-multiarea.json", [{"ts": "2026-10-01 10:00:00", "mode": "auto", "earned": 9, "total": 12,
                                          "score_pct": 75.0, "passed": False, "failed": []}])
    w("history/eigrp-basic.json", [{"ts": "2026-10-02 10:00:00", "mode": "auto", "earned": 4, "total": 4,
                                    "score_pct": 100.0, "passed": True, "failed": []}])
    w("walkthroughs/18-evpn-vxlan.json", {"current": 4, "steps": {}, "started": "2026-10-19 21:00:00"})
    w("snapshots/06-hsrp/before-change.json", {"name": "before-change", "lab_id": "06-hsrp", "platform": "iol",
                                               "created": "2026-10-03 10:00:00", "note": "", "configs": {"R1": "hostname R1\n"}})
    w("faults/07-acl-nat.json", {"fault_id": "nat-acl", "started": "2026-10-04 10:00:00", "revealed": False, "recent": ["nat-acl"]})
    return digest(data)


def digest(data: Path) -> dict:
    return {str(p.relative_to(data)): hashlib.sha256(p.read_bytes()).hexdigest()
            for d in DATA_DIRS if (data / d).is_dir() for p in sorted((data / d).rglob("*")) if p.is_file()}


def start_gui(exe, port: int, env: dict):
    proc = subprocess.Popen(exe + ["--no-browser", "--port", str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env,
                            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    lines: list[str] = []
    threading.Thread(target=lambda: [lines.append(l) for l in proc.stdout], daemon=True).start()
    base = None
    for _ in range(240):
        m = re.search(r"Web UI:\s+(http://127\.0\.0\.1:\d+)", "".join(lines))
        if m:
            base = m.group(1)
            try:
                get(base + "/api/health", 2)
                break
            except Exception:
                pass
        time.sleep(0.5)
    return proc, base, lines


def stop(proc, pre):
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        proc.wait(timeout=20)
    except Exception:
        proc.kill()
    if pre:
        subprocess.run(pre + ["taskkill", "/F", "/IM", "ENCORLab.exe"], capture_output=True, timeout=60)


def verify_linked(base: str, check, label: str) -> None:
    d = json.loads(get(base + "/api/labs")[2])
    labs = {l["id"]: l for l in d["labs"]}
    check(len(labs) == LEGACY + 1 and not d["broken"], f"{label}: {len(labs)} labs (19 kept + the imported pack), broken={d['broken']}")
    check(all(l["source"] == "user" for l in labs.values()), f"{label}: all labs live in the user labs folder")
    check(labs.get("03-ospf-multiarea", {}).get("best") == 75 and labs.get("eigrp-basic", {}).get("solved"),
          f"{label}: scores linked by lab id (03 best={labs.get('03-ospf-multiarea', {}).get('best')})")
    check((labs.get("18-evpn-vxlan", {}).get("walkthrough") or {}).get("current") == 4, f"{label}: walkthrough progress kept")
    check(labs.get("07-acl-nat", {}).get("fault_active") is True, f"{label}: active Break-my-lab fault kept")
    snaps = json.loads(get(base + "/api/labs/06-hsrp/snapshots")[2])
    names = [s["name"] for s in (snaps.get("snapshots", snaps) if isinstance(snaps, dict) else snaps)]
    check("before-change" in names, f"{label}: snapshot kept ({names})")
    check(labs.get("troubleshoot-ospf-7node", {}).get("source") == "user", f"{label}: imported pack kept")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--patch", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--runner", default="")
    ap.add_argument("--port", type=int, default=18800)
    a = ap.parse_args()
    pre = a.runner.split() if a.runner else []
    exe_name = "ENCORLab.exe" if a.runner or os.name == "nt" else "ENCORLab"
    old, new = pre + [str(Path(a.old) / exe_name)], pre + [str(Path(a.new) / exe_name)]
    data = Path(a.data_dir)
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    for k in [k for k in os.environ if k.startswith(("ENCOR_", "CMLLAB_"))]:
        del os.environ[k]
    env = dict(os.environ, ENCOR_UPDATE_URL="http://127.0.0.1:9/none")      # never ask GitHub during the test
    patch_ver = re.search(r"patch-(\d+\.\d+\.\d+)\.zip$", a.patch).group(1)
    # 2.1+ moves the data folder (encorlab -> cml-lab-builder) on its first start; app/ stays in the old folder
    renamed = tuple(int(x) for x in patch_ver.split(".")[:2]) >= (2, 1) and data.name == "encorlab"
    cur = data.with_name("cml-lab-builder") if renamed else data

    def moved_ok(label):
        if not renamed:
            return
        m = json.loads((cur / "migrations" / "data-folder.json").read_text(encoding="utf-8"))
        check(m.get("state") == "moved" and (data / "MOVED.txt").is_file() and (data / "settings.json").is_file()
              and not (cur / "app").exists(), f"{label}: data moved to {cur.name} ({m.get('files')} files), old folder kept with MOVED.txt")

    print("== A) update by patch")
    shutil.rmtree(data, ignore_errors=True)
    shutil.rmtree(cur, ignore_errors=True)
    before = seed(old, data, check)
    code, out = run(old + ["update-install", "--file", a.patch])
    check(code == 0 and f"Installed {patch_ver}" in out, f"patch {patch_ver} installed into the 1.9 build: {out.strip()[-60:]!r}")
    code, out = run(old + ["version"])
    check(code == 0 and out.splitlines()[0].strip() == patch_ver, f"next start runs {patch_ver}")
    moved_ok("A")
    code, out = run(old + ["list"])
    rows = [l for l in out.splitlines() if re.match(r"^[a-z0-9][a-z0-9-]+\s+user\s", l)]
    check(code == 0 and len(rows) == LEGACY + 1, f"CLI list after the update: {len(rows)} labs")
    st = json.loads((cur / "migrations" / "library-labs.json").read_text(encoding="utf-8"))
    check(st.get("state") == "done" and len(st.get("copied", [])) == LEGACY, f"migration: copied {len(st.get('copied', []))} labs from the old program files")
    check(all((cur / "labs" / lid / "lab.yaml").is_file() for lid in st.get("copied", [])), "copies are in the user labs folder")
    check(digest(cur) == before, "history, walkthrough progress, snapshots and faults unchanged")
    proc, base, lines = start_gui(old, a.port, env)
    try:
        check(base is not None, f"web UI up on the patched build: {base}")
        if base:
            verify_linked(base, check, "A")
            check(json.loads(get(base + "/api/migration")[2]).get("state") == "done", "A: nothing pending")
    finally:
        stop(proc, pre)

    print("== B) update by full download (old program files gone)")
    shutil.rmtree(data, ignore_errors=True)
    shutil.rmtree(cur, ignore_errors=True)
    before = seed(old, data, check)
    shutil.rmtree(data / "app", ignore_errors=True)
    srv, url = serve_library()
    code, out = run(new + ["version"])
    check(code == 0 and out.splitlines()[0].strip() == patch_ver, f"new build is {patch_ver} (then a note about the labs to restore)")
    moved_ok("B")
    st = json.loads((cur / "migrations" / "library-labs.json").read_text(encoding="utf-8"))
    check(st.get("state") == "pending" and len(st.get("pending", [])) == LEGACY, f"no old files: {len(st.get('pending', []))} labs pending")
    code, out = run(new + ["list"])
    check(code == 0 and "library restore" in out, "CLI says how to restore")
    proc, base, lines = start_gui(new, a.port + 1, dict(env, ENCOR_LIBRARY_URL=url))
    try:
        check(base is not None, f"web UI up on the new build: {base}")
        m = {}
        for _ in range(120):
            m = json.loads(get(base + "/api/migration")[2])
            if m.get("state") == "done":
                break
            time.sleep(0.5)
        check(m.get("state") == "done" and len(m.get("restored", [])) == LEGACY,
              f"labs restored from the library in the background: {len(m.get('restored', []))}")
        verify_linked(base, check, "B")
    finally:
        stop(proc, pre)
        srv.shutdown()
    check(digest(cur) == before, "B: history, walkthrough progress, snapshots and faults unchanged")
    shutil.rmtree(data, ignore_errors=True)
    shutil.rmtree(cur, ignore_errors=True)
    print("MIGRATION TEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
