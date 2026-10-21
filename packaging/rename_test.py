"""End-to-end test of the 2.1.0 rename on real packaged builds (stdlib only; Linux, Windows under Wine, the .deb).

    python packaging/rename_test.py --old <unpacked 2.0.x build> --patch <encorlab-patch-2.1.x.zip>
        --base <the folder that holds encorlab/ (~/.config or %APPDATA%)> [--runner wine] [--port 18820]
    python packaging/rename_test.py --exe /usr/bin/encorlab --patch ... --base ~/.config        # installed .deb

An older user (1.7-2.0; settings, an imported pack, results history, a snapshot) installs the 2.1 patch in the GUI way
(update-install). On the first 2.1 start the data moves to cml-lab-builder (checked file by file), app/ stays in
encorlab, the one-time note shows (CLI and /api/data-folder), then: next patch (2.1.99) -> restart -> roll back ->
2.1 -> roll back -> the 2.0 built-in copy, which still has its data in the old folder; a lab the 2.0 copy imports
then is picked up by the next 2.1 start. The base folder's encorlab/ and cml-lab-builder/ are wiped first."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from migration_test import start_gui, stop  # noqa: E402
from smoke_test import ROOT, get, make_patch, run  # noqa: E402


def sha_tree(root: Path, skip=("app", "MOVED.txt")) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and p.relative_to(root).parts[0] not in skip}


def post(url):
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=20) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", help="unpacked 2.0 build folder")
    ap.add_argument("--exe", help="the program to run instead (e.g. /usr/bin/encorlab of the installed .deb)")
    ap.add_argument("--patch", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--runner", default="")
    ap.add_argument("--port", type=int, default=18820)
    a = ap.parse_args()
    pre = a.runner.split() if a.runner else []
    exe_name = "ENCORLab.exe" if a.runner or os.name == "nt" else "ENCORLab"
    exe = pre + [a.exe or str(Path(a.old) / exe_name)]
    base = Path(a.base)
    old, new = base / "encorlab", base / "cml-lab-builder"
    ver = re.search(r"patch-(\d+\.\d+\.\d+)\.zip$", a.patch).group(1)
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    for k in [k for k in os.environ if k.startswith(("ENCOR_", "CMLLAB_"))]:
        del os.environ[k]
    env = dict(os.environ, ENCOR_UPDATE_URL="http://127.0.0.1:9/none")
    for d in (old, new):
        shutil.rmtree(d, ignore_errors=True)

    def version():
        code, out = run(exe + ["version"])
        return code, (out.splitlines() or [""])[0].strip(), out

    print("== 2.0 user")
    code, v0, _ = version()
    check(code == 0 and v0 < ver, f"old build is {v0}")
    code, out = run(exe + ["import", str(ROOT / "labs" / "troubleshoot-ospf-7node.encorlab")])
    check(code == 0, f"2.0 imports a pack: {out.strip()[-50:]!r}")
    (old / "settings.json").write_text(json.dumps({"_format": 2, "cml_url": "https://cml.example.ts.net",
                                                   "username": "dylan", "check_updates": False}), encoding="utf-8")
    (old / "history").mkdir(exist_ok=True)
    (old / "history" / "troubleshoot-ospf-7node.json").write_text(json.dumps([{"ts": "2026-10-01 10:00:00", "mode": "auto",
        "earned": 3, "total": 4, "score_pct": 75.0, "passed": False, "failed": []}]), encoding="utf-8")
    (old / "snapshots" / "troubleshoot-ospf-7node").mkdir(parents=True)
    (old / "snapshots" / "troubleshoot-ospf-7node" / "s1.json").write_text(json.dumps({"name": "s1", "lab_id": "troubleshoot-ospf-7node",
        "platform": "iol", "created": "2026-10-03 10:00:00", "note": "", "configs": {"R1": "hostname R1\n"}}), encoding="utf-8")
    before = sha_tree(old)

    print(f"== patch {ver} (installed by the 2.0 updater)")
    code, out = run(exe + ["update-install", "--file", a.patch])
    check(code == 0 and f"Installed {ver}" in out, f"2.0 installs the {ver} patch: {out.strip()[-60:]!r}")
    check((old / "app" / ver / "encorlab" / "__init__.py").is_file() and not new.exists(), "patch in encorlab/app, nothing moved yet")
    code, v1, out = version()
    check(code == 0 and v1 == ver, f"restart runs {v1}")
    check("data moved" in out.lower() and "cml-lab-builder" in out, f"CLI shows the one-time note: {out.strip()[-120:]!r}")   # a C:\ path under Wine
    m = json.loads((new / "migrations" / "data-folder.json").read_text(encoding="utf-8"))
    check(m.get("state") == "moved" and m.get("files") == len(before), f"moved {m.get('files')}/{len(before)} files")
    after = sha_tree(new)
    check(all(after.get(k) == h for k, h in before.items()), "every file arrived with the same sha256")
    check(sha_tree(old) == before and (old / "MOVED.txt").is_file() and (old / "app" / ver).is_dir() and not (new / "app").exists(),
          "old folder unchanged + MOVED.txt; app/ stays in encorlab")
    code, _, out = version()
    check("data moved" not in out.lower(), "the CLI note shows once")
    proc, url, lines = start_gui(exe, a.port, env)
    try:
        check(url is not None, f"web UI up: {url}")
        if url:
            h = json.loads(get(url + "/api/health")[2])
            check(h.get("version") == ver, f"/api/health version {h.get('version')}")
            d = json.loads(get(url + "/api/data-folder")[2])
            check(d.get("state") == "moved" and d.get("notified") is False
                  and str(d.get("path", "")).replace("\\", "/").endswith("/cml-lab-builder"),
                  f"/api/data-folder: toast pending, path {d.get('path')}")
            post(url + "/api/data-folder/ack")
            check(json.loads(get(url + "/api/data-folder")[2]).get("notified") is True, "toast acknowledged")
            labs = {l["id"]: l for l in json.loads(get(url + "/api/labs")[2])["labs"]}
            check(labs.get("troubleshoot-ospf-7node", {}).get("best") == 75, "imported lab and its score are there")
            html = get(url + "/")[2].decode()
            check("CML Lab Builder" in html and "ENCOR Lab Builder" not in html, "UI shows the new name")
            check(get(url + "/api/update/status")[0] == 200, "update status answers")
    finally:
        stop(proc, pre)

    print("== next patch, restart, roll back")
    with tempfile.TemporaryDirectory() as tmp:
        nxt = make_patch(Path(tmp), "2.1.99")
        code, out = run(exe + ["update-install", "--file", str(nxt)])
        check(code == 0 and "Installed 2.1.99" in out, f"2.1 installs the next patch: {out.strip()[-50:]!r}")
    check((old / "app" / "2.1.99").is_dir() and not (new / "app").exists(), "next patch also lands in encorlab/app")
    code, v2, out = version()
    check(v2 == "2.1.99" and "data moved" not in out.lower(), f"restart runs {v2}, no second move")
    check(json.loads((new / "migrations" / "data-folder.json").read_text(encoding="utf-8")).get("at") == m.get("at"), "marker unchanged")
    code, out = run(exe + ["update-rollback"])
    check(code == 0, f"roll back: {out.strip()[-60:]!r}")
    code, v3, _ = version()
    check(v3 == ver, f"after roll back: {v3}")
    code, out = run(exe + ["update-rollback"])
    code, v4, _ = version()
    check(v4 == v0, f"second roll back: the built-in {v4}")
    if v4 == v0:
        code, out = run(exe + ["list"])
        check("troubleshoot-ospf-7node" in out, "the old version still finds its data in the old folder")
        code, out = run(exe + ["import", str(ROOT / "labs" / "ospf-multiarea-stub.encorlab")])
        check(code == 0 and (old / "labs" / "ospf-multiarea-stub").is_dir(), "the old version imports another lab (old folder)")
        code, out = run(exe + ["update-install", "--file", a.patch])
        code, v5, _ = version()
        check(v5 == ver and (new / "labs" / "ospf-multiarea-stub" / "lab.yaml").is_file(),
              f"back on {v5}: the lab 2.0 imported was copied over")
        mm = json.loads((new / "migrations" / "data-folder.json").read_text(encoding="utf-8"))
        check(any(x.startswith("labs/ospf-multiarea-stub/") for x in mm.get("caught_up", [])), "recorded as caught up")
    for d in (old, new):
        shutil.rmtree(d, ignore_errors=True)
    print("RENAME TEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
