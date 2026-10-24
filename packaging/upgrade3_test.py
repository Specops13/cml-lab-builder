"""End-to-end test of the upgrade from ENCOR Lab Builder 1.7 - 2.1 to CML Lab Builder 3.0 on real packaged builds
(stdlib only; Linux, Windows under Wine, and the installed .deb in deb_chroot_inner.sh).

    python packaging/upgrade3_test.py --old <unpacked 1.9/2.0/2.1 build> [--old ...] --new <unpacked 3.x build>
        --base <folder that holds encorlab/ and cml-lab-builder/ (~/.config or %APPDATA%)> [--runner wine]
    python packaging/upgrade3_test.py --phase old --old-exe /usr/bin/encorlab --base ~/.config --state s.json
    python packaging/upgrade3_test.py --phase new --new-exe /usr/bin/cml-lab-builder --base ~/.config --state s.json

For every old build:
 1. its updater, pointed at a fake v<new> release on 127.0.0.1 with the same files a real release has (new names,
    the old-name copies and the manifest-only encorlab-patch from build_compat.py, SHA256SUMS.txt), finds the
    release, installs nothing and shows the "download the full release" banner that links to the old-name copy for
    its install type (zip on Windows, tar.gz on Linux, the .deb for a deb install), with "needs runtime 2";
 2. a user's data is seeded with that build (settings, an imported pack, history, walkthrough progress, a snapshot,
    an active fault; 1.9 also has its 19 built-in labs), then the 3.x build starts on it: everything is in
    cml-lab-builder (byte-identical), the imported lab, scores and settings are there, 1.9's built-in labs are
    restored from the library, the old folder is left with MOVED.txt, no app/ update of the old program is used, and
    the old updater's banner state does not come back.
At the end (phase all/new) a 3.x patch round trip: a <new>+1 patch served by a fake release is installed with
update-install, the next start runs it from cml-lab-builder/app, and update-rollback goes back to the bundled code.
The base folder's encorlab/ and cml-lab-builder/ are wiped first."""
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
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fake_release import FakeRelease  # noqa: E402
from smoke_test import ROOT, SMOKE_TOKEN, get, install_auth_opener, make_patch, run, serve_library, smoke_key  # noqa: E402

import build_compat  # noqa: E402

OLD_LIB, NEW_LIB = ROOT / "labs", ROOT / "library"
LEGACY = 19                                           # labs 1.9 had built in
DATA_DIRS = ("history", "walkthroughs", "snapshots", "faults", "labs")
EXES = ("ENCORLab.exe", "CMLLabBuilder.exe")


def vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def seed(exe, data: Path, check, version: str) -> int:
    """What an ENCOR Lab Builder user has in the data folder."""
    code, out = run(exe + ["list"])
    n = len([l for l in out.splitlines() if re.match(r"^[a-z0-9][a-z0-9-]+\s+builtin\s", l)])
    want = (LEGACY - 1 if vtuple(version) < (1, 9) else LEGACY) if vtuple(version) < (2, 0) else 0   # 1.7/1.8: 18
    check(code == 0 and n == want, f"{version} lists {n} built-in labs")
    code, out = run(exe + ["import", str(OLD_LIB / "troubleshoot-ospf-7node.encorlab")])
    check(code == 0, f"{version} imports a pack: {out.strip()[-60:]!r}")
    (data / "settings.json").write_text(json.dumps({"_format": 2, "cml_url": "https://cml.example.ts.net",
                                                    "username": "dylan", "check_updates": False}), encoding="utf-8")
    w = lambda rel, obj: ((data / rel).parent.mkdir(parents=True, exist_ok=True), (data / rel).write_text(json.dumps(obj), encoding="utf-8"))
    w("history/troubleshoot-ospf-7node.json", [{"ts": "2026-10-01 10:00:00", "mode": "auto", "earned": 9, "total": 12,
                                                "score_pct": 75.0, "passed": False, "failed": []}])
    w("history/eigrp-basic.json", [{"ts": "2026-10-02 10:00:00", "mode": "auto", "earned": 4, "total": 4,
                                    "score_pct": 100.0, "passed": True, "failed": []}])
    w("walkthroughs/18-evpn-vxlan.json", {"current": 4, "steps": {}, "started": "2026-10-19 21:00:00"})
    w("snapshots/06-hsrp/before-change.json", {"name": "before-change", "lab_id": "06-hsrp", "platform": "iol",
                                               "created": "2026-10-03 10:00:00", "note": "", "configs": {"R1": "hostname R1\n"}})
    w("faults/07-acl-nat.json", {"fault_id": "nat-acl", "started": "2026-10-04 10:00:00", "revealed": False, "recent": ["nat-acl"]})
    return n


def digest(data: Path) -> dict:
    out = {str(p.relative_to(data).as_posix()): hashlib.sha256(p.read_bytes()).hexdigest()
           for d in DATA_DIRS if (data / d).is_dir() for p in sorted((data / d).rglob("*")) if p.is_file()}
    out["settings.json"] = hashlib.sha256((data / "settings.json").read_bytes()).hexdigest()
    return out


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
        for n in EXES:
            subprocess.run(pre + ["taskkill", "/F", "/IM", n], capture_output=True, timeout=60)


def release_files(v: str) -> dict[str, bytes]:
    """What a real release carries (full downloads as small stand-ins: old apps only link to them)."""
    files = {n: f"stand-in for {n}\n".encode() for n in build_compat.copies(v)}
    files.update({old: files[new] for new, old in build_compat.copies(v).items()})
    files[f"cml-lab-builder-patch-{v}.zip"] = b"PK stand-in"
    files[f"encorlab-patch-{v}.zip"] = build_compat.old_patch_bytes(v, 2)
    return files


def env_for(**kw) -> dict:
    """Both prefixes: 1.7 - 2.0 read only ENCOR_*, 3.x reads CMLLAB_* (and ENCOR_*)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CMLLAB_", "ENCOR_"))}
    for k, v in kw.items():
        env["ENCOR_" + k] = env["CMLLAB_" + k] = v
    env["CMLLAB_ACCESS_TOKEN"] = SMOKE_TOKEN            # 3.3.0+ (web/security.py); older versions ignore both
    env["CMLLAB_UPDATE_TEST_KEY"] = smoke_key()[1]      # trusted only while UPDATE_URL is on 127.0.0.1 (signing.py)
    return env


def expected_asset(install_type: str, v: str) -> str:
    return {"deb": f"encorlab_{v}_amd64.deb", "linux-tar": f"ENCORLab-{v}-linux-x64.tar.gz",
            "windows-zip": f"ENCORLab-{v}-windows-x64.zip"}[install_type]


def old_phase(old, base: Path, new_version: str, port: int, pre, check) -> dict:
    """Run one old build: its updater sees the new release, then seed its data. Returns what phase new needs."""
    olddir, newdir = base / "encorlab", base / "cml-lab-builder"
    shutil.rmtree(olddir, ignore_errors=True)
    shutil.rmtree(newdir, ignore_errors=True)
    olddir.mkdir(parents=True)      # a user who started on ENCOR Lab Builder (2.1 moves this on its first start)
    (olddir / "settings.json").write_text(json.dumps({"_format": 2, "check_updates": True}), encoding="utf-8")
    code, out = run(old + ["version"])
    ver = out.strip().splitlines()[0].strip() if code == 0 and out.strip() else "?"
    check(code == 0 and vtuple(ver) < (3, 0), f"old build is {ver}")
    print(f"== {ver}: the old updater sees {new_version}")
    fake = FakeRelease(new_version, release_files(new_version)).start()
    proc, url, _ = start_gui(old, port, env_for(UPDATE_URL=fake.url, UPDATE_DELAY="1", LIBRARY_URL="http://127.0.0.1:9/x"))
    kind = None
    try:
        check(url is not None, f"{ver} web UI up: {url}")
        st = {}
        for _ in range(120):
            try:
                st = json.loads(get(url + "/api/update/auto", 3)[2])
                if st.get("full_download") or st.get("offer"):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        fd = st.get("full_download") or {}
        try:
            kind = json.loads(get(url + "/api/update/status", 5)[2]).get("install_type")
        except Exception:
            kind = None
        kind = kind or fd.get("install_type")
        check(fd.get("version") == new_version and not st.get("offer"),
              f"{ver}: banner 'full download needed' for {new_version}, no patch offered ({fd.get('reason')!r})")
        check("runtime 2" in str(fd.get("reason")), f"{ver}: reason names the new runtime")
        if kind in ("deb", "linux-tar", "windows-zip"):
            want = expected_asset(kind, new_version)
            check(fd.get("asset") == want and str(fd.get("url", "")).endswith("/" + want),
                  f"{ver} ({kind}): the banner links straight to {want} -> {fd.get('url')}")
            print(f"   how: {fd.get('how')}")
        else:
            check(str(fd.get("url", "")).endswith(f"/v{new_version}") or "releases" in str(fd.get("url")),
                  f"{ver}: no install type, the banner links to the release page: {fd.get('url')}")
        got = [r[0] for r in fake.requests]
        check(any(p.endswith(f"encorlab-patch-{new_version}.zip") for p in got) and any("SHA256SUMS" in p for p in got),
              f"{ver}: downloaded the stub patch and SHA256SUMS.txt (checked, then refused)")
        check(not any(re.search(r"(ENCORLab-|CMLLabBuilder-|_amd64\.deb)", p) for p in got),
              f"{ver}: no full download fetched in the background")
        apps = sorted(p.name for p in (olddir / "app").iterdir()) if (olddir / "app").is_dir() else []
        check(new_version not in apps, f"{ver}: nothing installed into encorlab/app ({apps})")
    finally:
        stop(proc, pre)
        fake.stop()
    data = newdir if vtuple(ver) >= (2, 1) else olddir
    print(f"== {ver}: seed the user's data ({data.name})")
    for rel in ("updates/auto.json",):                     # keep the old banner state: 3.x must not show it again
        check((data / rel).is_file(), f"{ver}: has {rel} with the banner state")
    builtins = seed(old, data, check, ver)
    nlabs = len([d for d in (data / "labs").iterdir() if (d / "lab.yaml").is_file()]) if (data / "labs").is_dir() else 0
    return {"version": ver, "digest": digest(data), "data": data.name, "install_type": kind, "labs": nlabs,
            "builtins": builtins}


def new_phase(new, base: Path, port: int, pre, check, prev: dict) -> None:
    olddir, newdir = base / "encorlab", base / "cml-lab-builder"
    ov = prev["version"]
    srv, lib = serve_library(NEW_LIB)
    try:
        code, out = run(new + ["version"])
        nv = out.strip().splitlines()[0].strip() if out.strip() else "?"
        check(code == 0 and vtuple(nv) >= (3, 0), f"new build {nv} starts on the {ov} data")
        m = json.loads((newdir / "migrations" / "data-folder.json").read_text(encoding="utf-8"))
        check(m.get("state") == "moved", f"data folder: {m.get('state')} (from {m.get('from', '?')}, version {m.get('version')})")
        note = (olddir / "MOVED.txt").read_text(encoding="utf-8") if (olddir / "MOVED.txt").is_file() else ""
        check("cml-lab-builder" in note and "only holds updates" in note, "old folder kept with an up-to-date MOVED.txt")
        check(digest(newdir) == prev["digest"], f"settings, labs, history, walkthroughs, snapshots, faults byte-identical in "
              f"cml-lab-builder ({len(prev['digest'])} files)")
        check(not (newdir / "app").exists() or not any(p.name.startswith(("1.", "2.")) for p in (newdir / "app").iterdir()),
              "no app/ update of the old program copied or used")
        proc, url, lines = start_gui(new, port, env_for(UPDATE_URL="http://127.0.0.1:9/none", LIBRARY_URL=lib))
        try:
            check(url is not None, f"{nv} web UI up: {url}")
            if not url:
                print("".join(lines)[-2000:])
                return
            h = json.loads(get(url + "/api/health")[2])
            check(h.get("version") == nv, f"health says {h.get('version')}")
            if vtuple(ov) < (2, 0):
                mg = {}
                for _ in range(120):
                    mg = json.loads(get(url + "/api/migration")[2])
                    if mg.get("state") == "done":
                        break
                    time.sleep(0.5)
                nb = LEGACY                 # 2.0's move restores all 19 former built-ins (1.7/1.8 had 18 of them)
                check(mg.get("state") == "done" and len(mg.get("restored", [])) == nb,
                      f"{ov}'s {nb} built-in labs restored from the library: {len(mg.get('restored', []))}")
            d = json.loads(get(url + "/api/labs")[2])
            labs = {l["id"]: l for l in d["labs"]}
            want = LEGACY + 1 if vtuple(ov) < (2, 0) else prev["labs"]     # 1.9: built-ins restored; else what it had
            # 2.x: at least what it had (a pending 1.x lab restore it started may add more in the background)
            check((len(labs) == want if vtuple(ov) < (2, 0) else len(labs) >= want) and not d["broken"],
                  f"{len(labs)} labs (want {want}), broken={d['broken']}")
            t = labs.get("troubleshoot-ospf-7node", {})
            check(t.get("source") == "user" and t.get("best") == 75, f"imported pack kept with its score (best={t.get('best')})")
            if vtuple(ov) < (2, 0):
                check(labs.get("eigrp-basic", {}).get("solved") and
                      (labs.get("18-evpn-vxlan", {}).get("walkthrough") or {}).get("current") == 4 and
                      labs.get("07-acl-nat", {}).get("fault_active") is True,
                      "scores, walkthrough progress and the active fault link up with the restored labs")
            s = json.loads(get(url + "/api/settings")[2])
            check(s.get("cml_url") == "https://cml.example.ts.net" and s.get("username") == "dylan", "settings kept")
            au = json.loads(get(url + "/api/update/auto")[2])
            check(not au.get("full_download") and not au.get("offer"), "the old 'download 3.0' banner does not come back")
        finally:
            stop(proc, pre)
    finally:
        srv.shutdown()


def patch_round_trip(new, base: Path, check) -> None:
    newdir = base / "cml-lab-builder"
    code, out = run(new + ["version"])
    cur = out.strip().splitlines()[0].strip()
    x, y, z = vtuple(cur)
    nxt = f"{x}.{y}.{z + 1}"
    print(f"== patch round trip on {cur}: {nxt} from a fake release")
    tmp = Path(tempfile.mkdtemp(prefix="cmllab-up3-"))
    try:
        p = make_patch(tmp, nxt)
        check(p.name == f"cml-lab-builder-patch-{nxt}.zip", f"patch built: {p.name}")
        files = {p.name: p.read_bytes(), f"encorlab-patch-{nxt}.zip": build_compat.old_patch_bytes(nxt, 2)}
        fake = FakeRelease(nxt, files, key=smoke_key()[0]).start()
        env = env_for(UPDATE_URL=fake.url)
        try:
            r = subprocess.run(new + ["update-install"], capture_output=True, text=True, env=env, timeout=300,
                               encoding="utf-8", errors="replace")
            check(r.returncode == 0 and f"Installed {nxt}" in r.stdout + r.stderr,
                  f"update-install from the release -> {(r.stdout + r.stderr).strip()[-80:]!r}")
        finally:
            fake.stop()
        check((newdir / "app" / nxt / "cmllab" / "__init__.py").is_file(), f"installed into cml-lab-builder/app/{nxt}/cmllab")
        check(not (base / "encorlab" / "app" / nxt).exists(), "nothing written to the old encorlab/app")
        code, out = run(new + ["version"])
        check(code == 0 and out.strip().splitlines()[0].strip() == nxt, f"next start runs {nxt}")
        code, out = run(new + ["update-status"])
        check(code == 0 and f"Installed update: {nxt}" in out, "update-status shows the patch")
        code, out = run(new + ["update-rollback"])
        check(code == 0 and "Rolled back" in out, f"update-rollback -> {out.strip()[-60:]!r}")
        code, out = run(new + ["version"])
        check(code == 0 and out.strip().splitlines()[0].strip() == cur, f"back on the bundled {cur}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(newdir / "app", ignore_errors=True)
        shutil.rmtree(newdir / "updates", ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", action="append", default=[], help="unpacked old build folder (repeatable)")
    ap.add_argument("--old-exe", help="an installed old program (e.g. /usr/bin/encorlab)")
    ap.add_argument("--new", help="unpacked 3.x build folder")
    ap.add_argument("--new-exe", help="an installed 3.x program (e.g. /usr/bin/cml-lab-builder)")
    ap.add_argument("--new-version", default="", help="version of the fake release in step 1 (default: the source's)")
    ap.add_argument("--base", required=True)
    ap.add_argument("--phase", choices=("all", "old", "new"), default="all")
    ap.add_argument("--state", help="file that carries phase old's result to phase new")
    ap.add_argument("--runner", default="")
    ap.add_argument("--port", type=int, default=18840)
    a = ap.parse_args()
    pre = a.runner.split() if a.runner else []
    win = bool(pre) or os.name == "nt"
    olds = [pre + [a.old_exe]] if a.old_exe else [pre + [str(Path(o) / ("ENCORLab.exe" if win else "ENCORLab"))] for o in a.old]
    new = pre + [a.new_exe] if a.new_exe else (pre + [str(Path(a.new) / ("CMLLabBuilder.exe" if win else "cml-lab-builder"))] if a.new else None)
    base = Path(a.base)
    nv = a.new_version or build_compat.version()
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    for k in [k for k in os.environ if k.startswith(("CMLLAB_", "ENCOR_"))]:
        del os.environ[k]
    os.environ["CMLLAB_UPDATE_URL"] = os.environ["ENCOR_UPDATE_URL"] = "http://127.0.0.1:9/none"   # CLI runs: no GitHub
    os.environ["CMLLAB_ACCESS_TOKEN"] = SMOKE_TOKEN
    os.environ["CMLLAB_UPDATE_TEST_KEY"] = smoke_key()[1]
    install_auth_opener()
    if a.phase == "old":
        st = old_phase(olds[0], base, nv, a.port, pre, check)
        Path(a.state).write_text(json.dumps(st), encoding="utf-8")
    elif a.phase == "new":
        new_phase(new, base, a.port + 1, pre, check, json.loads(Path(a.state).read_text(encoding="utf-8")))
        patch_round_trip(new, base, check)
    else:
        for i, old in enumerate(olds):
            st = old_phase(old, base, nv, a.port + 2 * i, pre, check)
            new_phase(new, base, a.port + 2 * i + 1, pre, check, st)
        patch_round_trip(new, base, check)
    print("UPGRADE TEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
