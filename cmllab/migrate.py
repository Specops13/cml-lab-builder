"""Keep the labs older versions bundled when a user updates to 2.0.0 or later (which ship without labs).

Up to 1.9.x the app code carried 19 labs in encorlab/labs/. From 2.0.0 every lab is a pack in the online library
and lives in the user labs folder. An existing user must not lose anything, so on the first start of 2.x:

1. run_local() (at every start, cheap; does real work once) decides whether this is an existing installation
   (settings, history, walkthrough progress, snapshots, exams, faults, courses or user labs exist, or older app
   code is still on disk) or a fresh one. Fresh: nothing to do, the first-run screen offers the library.
   Existing: it copies every formerly bundled lab that is not installed yet from older app code that is still on
   disk into the user labs folder, unchanged and under the same id:
     * <data>/app/<version>/encorlab/labs   (installed 1.x patches; the newest copy of each lab wins)
     * the runtime's bundled app code        (_internal/appcode/encorlab/labs of a 1.x install updated by patch)
2. Labs that could not be copied (e.g. a full download replaced the old files) are "pending". restore() installs
   them from the library (sha256-checked like any library install). The desktop app tries that in the background
   once per start while anything is pending; the UI shows a banner with Retry and Dismiss. Offline, nothing
   breaks: the labs stay pending and the history stays where it is.

Progress, history, reports, snapshots, faults, exams and walkthrough progress are files keyed by lab id in the
data folder. They are never moved, rewritten or deleted here; the restored labs keep the same ids, so everything
links up again. An existing user lab folder is never overwritten. State: <data>/migrations/library-labs.json."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import catalog
from .history import data_dir

# the labs 1.x bundled (encorlab/labs/ in 1.9.0); all are packs in the library now
LEGACY_IDS = ("01-vlan-trunk-stp", "02-etherchannel", "03-ospf-multiarea", "04-eigrp-named", "05-bgp-ebgp-ibgp",
              "06-hsrp", "07-acl-nat", "08-vrf-lite", "09-gre-ipsec", "10-ntp-syslog-snmp", "11-ipsla-tracking",
              "12-pbr", "13-redistribution", "14-multicast-pim-sm", "15-multicast-bsr-ssm", "16-mpls-ldp",
              "17-mpls-l3vpn", "18-evpn-vxlan", "eigrp-basic")
# per-lab user data (by lab id) in the data folder: <dir>/<lab>.json or <dir>/<lab>/
DATA_DIRS = ("history", "reports", "walkthroughs", "snapshots", "faults", "exams")


def marker() -> Path:
    return data_dir() / "migrations" / "library-labs.json"


def load() -> dict:
    try:
        d = json.loads(marker().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> dict:
    f = marker()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(f)
    return d


def _ver(s: str) -> tuple:
    import re
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?", str(s or ""))
    return (int(m[1]), int(m[2]), int(m[3] or 0)) if m else (0, 0, 0)


def legacy_sources() -> list[Path]:
    """labs/ folders of older (1.x) app code still on disk, newest version first."""
    found: list[tuple[tuple, Path]] = []
    from . import paths
    app = paths.boot_dir() / "app"     # the boot loader keeps app updates in its own (pre-2.1) folder
    if app.is_dir():
        for d in app.iterdir():
            labs = d / "encorlab" / "labs"
            if labs.is_dir():
                found.append((_ver(_manifest_version(d) or d.name), labs))
    try:
        import cmlboot   # the runtime's loader (packaged app only)
        b = cmlboot.bundled_dir()
    except Exception:
        b = None
    if b is not None and (Path(b) / "encorlab" / "labs").is_dir():
        found.append((_ver(_manifest_version(Path(b)) or "1.0.0"), Path(b) / "encorlab" / "labs"))
    own = catalog.LABS_DIR.resolve() if catalog.LABS_DIR.is_dir() else None
    found = [(v, p) for v, p in found if v < (2, 0, 0) and p.resolve() != own]
    return [p for _, p in sorted(found, key=lambda x: x[0], reverse=True)]


def _manifest_version(d: Path) -> str:
    try:
        return str(json.loads((d / "manifest.json").read_text(encoding="utf-8")).get("app_version") or "")
    except (OSError, ValueError):
        return ""


def ids_with_data() -> set[str]:
    """Lab ids that have history, progress, snapshots, ... in the data folder."""
    out = set()
    for sub in DATA_DIRS:
        d = data_dir() / sub
        if d.is_dir():
            for p in d.iterdir():
                if p.suffix == ".json" or (p.is_dir() and any(p.iterdir())):
                    out.add(p.stem if p.suffix == ".json" else p.name)
    return {x for x in out if catalog.LAB_ID_RE.match(x)}


def _existing_install(sources: list[Path]) -> bool:
    from .config import settings_file
    if sources or settings_file().is_file() or ids_with_data():
        return True
    for d in (data_dir() / "courses", catalog.user_labs_dir()):
        if d.is_dir() and any(d.iterdir()):
            return True
    return False


def _copy(src: Path, lid: str) -> bool:
    """Copy one lab folder into the user labs folder (validated first; never overwrites)."""
    dest = catalog.user_labs_dir() / lid
    if dest.exists():
        return False
    try:
        lab = catalog.load_lab_file(src / "lab.yaml")
        if lab.id != lid:
            return False
    except Exception:
        return False
    tmp = dest.with_name(dest.name + ".migrating")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    from .library import DEFAULT_INDEX, ORIGIN_FILE
    (tmp / ORIGIN_FILE).write_text(json.dumps({"index": DEFAULT_INDEX, "file": f"{lid}.cmllab", "version": lab.version,
                                               "migrated_from": str(src)}, indent=1), encoding="utf-8")
    tmp.rename(dest)
    return True


def run_local(sources: list[Path] | None = None) -> dict:
    """Decide fresh vs. existing install once, then copy formerly bundled labs from old app code on disk.
    Safe to call at every start; never raises (a failure leaves the labs pending for the library)."""
    try:
        return _run_local(sources)
    except Exception as e:   # never block the app start
        return {"state": "error", "error": f"{e.__class__.__name__}: {e}"}


def _run_local(sources: list[Path] | None) -> dict:
    st = load()
    if st.get("state") == "done":
        return st
    srcs = legacy_sources() if sources is None else sources
    if not st:
        if not _existing_install(srcs):
            return _save({"state": "done", "fresh": True, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        st = {"state": "pending", "started": time.strftime("%Y-%m-%d %H:%M:%S"), "copied": [], "restored": []}
    want = set(LEGACY_IDS) | ids_with_data()
    have = set(catalog.entries())
    for src in srcs:
        for lid in sorted(want - have):
            if (src / lid / "lab.yaml").is_file() and _copy(src / lid, lid):
                st["copied"].append(lid)
                st.setdefault("from", {})[lid] = str(src)
                have.add(lid)
    return _finish(st, want - have)


def _finish(st: dict, pending: set[str]) -> dict:
    st["pending"] = sorted(pending - set(st.get("unavailable", [])))
    st["state"] = "pending" if st["pending"] else "done"
    return _save(st)


def status() -> dict:
    st = load()
    pend = [x for x in st.get("pending", []) if x not in catalog.entries()] if st.get("state") == "pending" else []
    with_data = ids_with_data()
    return {"state": "pending" if pend else (st.get("state") or "none"), "pending": pend,
            "pending_with_data": sorted(set(pend) & with_data), "copied": st.get("copied", []),
            "restored": st.get("restored", []), "unavailable": st.get("unavailable", []),
            "last_error": st.get("last_error", ""), "fresh": bool(st.get("fresh"))}


def restore(url: str, fetch=None, node_limit: int = 20) -> dict:
    """Install pending labs from the library. Labs the library does not have are given up on (their data is kept)."""
    from . import library
    st = load()
    pend = [x for x in st.get("pending", []) if x not in catalog.entries()]
    if st.get("state") != "pending" or not pend:
        return status()
    try:
        r = library.install_many(pend, url=url, fetch=fetch or library.http_fetch, node_limit=node_limit)
    except Exception as e:
        st["last_error"] = str(e)
        st["last_try"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save(st)
        return status()
    st["restored"] = sorted(set(st.get("restored", [])) | set(r["installed"]))
    st["unavailable"] = sorted(set(st.get("unavailable", [])) | {k for k, v in r["failed"].items() if v == "not in the library"})
    errs = {k: v for k, v in r["failed"].items() if v != "not in the library"}
    st["last_error"] = "; ".join(f"{k}: {v}" for k, v in errs.items())
    st["last_try"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _finish(st, {x for x in pend if x not in catalog.entries()})
    return status()


def dismiss() -> dict:
    st = load()
    st.update(state="done", dismissed=True, pending=[])
    _save(st)
    return status()
