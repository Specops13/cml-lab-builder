"""Boot loader of the packaged app. It is frozen into the runtime (ENCORLab.exe + _internal/) and is NOT part of
app patches, so keep it small, stdlib-only and backwards compatible.

The packaged app has two layers:
  * the runtime: Python, the third-party libraries and this loader, built by PyInstaller. It only changes with a full
    download, and its version is RUNTIME_VERSION.
  * the app code: the `encorlab` package (Python files, web UI, built-in labs). A copy is bundled in
    _internal/appcode/, and newer copies can be installed as patches into <data dir>/app/<version>/.

At start the loader picks the newest valid app code (an installed patch, or the bundled copy if that is newer). It
puts it first on sys.path and imports it. A patch whose manifest needs a newer runtime (min_runtime) is never used.
Rollback:
  * if importing an installed patch fails, the loader falls back to the previous bundle, then to the bundled copy;
  * a freshly installed patch is "pending" until the web UI has started once (mark_good()). If a GUI start of a
    pending patch exits with an error before that, or the next start finds it still pending after one attempt, it
    is rolled back automatically.
State lives in <data dir>/app/state.json."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

RUNTIME_VERSION = 1          # bump when Python, a dependency, the PyInstaller spec or this file changes
PACKAGE = "encorlab"
MANIFEST = "manifest.json"
MANIFEST_FORMAT = 1
_VER = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")
_SKIP_DIRS = {"__pycache__"}
_SKIP_SUFFIXES = (".pyc", ".pyo")

ACTIVE: "Candidate | None" = None   # what this process is running (set by activate())


@dataclass(frozen=True)
class Candidate:
    source: str          # "installed" | "bundled"
    version: str
    path: Path           # directory that contains the package folder and manifest.json
    min_runtime: int = 1

    def to_dict(self) -> dict:
        return {"source": self.source, "version": self.version, "path": str(self.path), "min_runtime": self.min_runtime}


# ------------------------------------------------------------------ locations
def data_dir(env=None) -> Path:
    """Same rules as encorlab.history.data_dir() / config.settings_file()."""
    e = os.environ if env is None else env
    if e.get("ENCOR_DATA_DIR"):
        return Path(e["ENCOR_DATA_DIR"])
    if e.get("ENCOR_SETTINGS_FILE"):
        return Path(e["ENCOR_SETTINGS_FILE"]).parent
    if os.name == "nt" and e.get("APPDATA"):
        return Path(e["APPDATA"]) / "encorlab"
    base = Path(e["XDG_CONFIG_HOME"]) if e.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return base / "encorlab"


def app_root() -> Path:
    return data_dir() / "app"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundled_dir() -> Path | None:
    """_internal/appcode in the packaged app; None when running from source."""
    if not frozen():
        return None
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    d = base / "appcode"
    return d if d.is_dir() else None


# ------------------------------------------------------------------ versions, manifests, files
def parse_version(v) -> tuple[int, int, int] | None:
    m = _VER.match(str(v or "").strip())
    return (int(m[1]), int(m[2]), int(m[3] or 0)) if m else None


def iter_app_files(src: Path, package: str = PACKAGE):
    """(relative posix path, absolute path) of every app-code file under src/<package>, sorted."""
    pkg = Path(src) / package
    out = []
    for root, dirs, files in os.walk(pkg):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
        for f in sorted(files):
            if f.endswith(_SKIP_SUFFIXES) or f.startswith("."):
                continue
            p = Path(root) / f
            out.append((p.relative_to(src).as_posix(), p))
    return sorted(out)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(src: Path, app_version: str, min_runtime: int = RUNTIME_VERSION, package: str = PACKAGE) -> dict:
    return {"format": MANIFEST_FORMAT, "package": package, "app_version": app_version, "min_runtime": int(min_runtime),
            "files": {rel: sha256_file(p) for rel, p in iter_app_files(src, package)}}


def read_manifest(d: Path) -> dict | None:
    try:
        m = json.loads((Path(d) / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or not parse_version(m.get("app_version")):
        return None
    try:
        m["min_runtime"] = int(m.get("min_runtime", 1))
    except (TypeError, ValueError):
        return None
    return m


def candidate_at(d: Path | None, source: str, package: str = PACKAGE) -> Candidate | None:
    """A usable bundle: manifest present, package present, runtime new enough."""
    if d is None:
        return None
    m = read_manifest(d)
    if not m or not (Path(d) / package / "__init__.py").is_file():
        return None
    if m["min_runtime"] > RUNTIME_VERSION:
        return None
    return Candidate(source, str(m["app_version"]), Path(d), m["min_runtime"])


# ------------------------------------------------------------------ state
def load_state() -> dict:
    try:
        st = json.loads((app_root() / "state.json").read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    root = app_root()
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".state.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, root / "state.json")


def _installed(version, package: str = PACKAGE) -> Candidate | None:
    if not version or not parse_version(version):
        return None
    return candidate_at(app_root() / str(version), "installed", package)


def candidates(st: dict | None = None, package: str = PACKAGE) -> list[Candidate]:
    """Bundles in the order they should be tried."""
    st = load_state() if st is None else st
    bundled = candidate_at(bundled_dir(), "bundled", package)
    cur, prev = _installed(st.get("current"), package), _installed(st.get("previous"), package)
    bver = parse_version(bundled.version) if bundled else (0, 0, 0)
    newer = [c for c in (cur, prev) if c and parse_version(c.version) > bver]
    rest = [c for c in (cur, prev) if c and c not in newer]
    out: list[Candidate] = []
    for c in newer + ([bundled] if bundled else []) + rest:
        if c not in out:
            out.append(c)
    return out


def _rollback(st: dict, reason: str) -> dict:
    bad = st.get("current")
    st["failed"] = {"version": bad, "reason": reason, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    prev = st.get("previous")
    st["current"] = prev if prev and prev != bad else None
    st["previous"] = None
    st["pending"] = False
    st["boot_attempts"] = 0
    save_state(st)
    return st


def purge(package: str = PACKAGE) -> None:
    for name in [m for m in sys.modules if m == package or m.startswith(package + ".")]:
        del sys.modules[name]
    importlib.invalidate_caches()


def _import_from(c: Candidate, package: str):
    sys.path.insert(0, str(c.path))
    try:
        mod = importlib.import_module(package)
        where = Path(mod.__file__).resolve()
        if Path(c.path).resolve() not in where.parents:
            raise ImportError(f"{package} was imported from {where}, not from {c.path}")
        return mod
    except BaseException:
        try:
            sys.path.remove(str(c.path))
        except ValueError:
            pass
        purge(package)
        raise


def activate(gui: bool = True, package: str = PACKAGE) -> Candidate:
    """Pick and import the app code. Raises RuntimeError when nothing usable is left."""
    global ACTIVE
    st = load_state()
    if gui and st.get("pending") and int(st.get("boot_attempts", 0)) >= 1:
        st = _rollback(st, "the previous start did not reach the web UI")
    errors = []
    for c in candidates(st, package):
        try:
            _import_from(c, package)
        except Exception as e:  # broken patch: fall back
            errors.append(f"{c.source} {c.version}: {type(e).__name__}: {e}")
            if c.source == "installed" and c.version == st.get("current"):
                st = _rollback(st, f"import failed: {type(e).__name__}: {e}")
            continue
        ACTIVE = c
        if gui and c.source == "installed" and st.get("pending") and st.get("current") == c.version:
            st["boot_attempts"] = int(st.get("boot_attempts", 0)) + 1
            save_state(st)
        return c
    raise RuntimeError("no usable app code found" + (": " + "; ".join(errors) if errors else ""))


def pending_active() -> bool:
    """True while the running code is a freshly installed patch that has not reached the web UI yet."""
    st = load_state()
    return bool(ACTIVE and ACTIVE.source == "installed" and st.get("pending") and st.get("current") == ACTIVE.version)


def mark_good() -> None:
    """Called by the app once the web UI is up: the running patch is now trusted."""
    if not pending_active():
        return
    st = load_state()
    st["pending"] = False
    st["boot_attempts"] = 0
    save_state(st)


def fail_active(reason: str, package: str = PACKAGE) -> bool:
    """The running pending patch failed before the web UI came up: roll back and unload it.
    Returns True if there is something else to try."""
    global ACTIVE
    if not pending_active():
        return False
    st = _rollback(load_state(), reason)
    try:
        sys.path.remove(str(ACTIVE.path))
    except ValueError:
        pass
    purge(package)
    ACTIVE = None
    return bool(candidates(st, package))


# ------------------------------------------------------------------ install / rollback (used by encorlab.updates)
def stage(version: str, package: str = PACKAGE) -> dict:
    """Make an extracted bundle in app_root()/<version> the one to use on the next start."""
    if not _installed(version, package):
        raise ValueError(f"no valid bundle for {version} in {app_root()}")
    st = load_state()
    keep_prev = ACTIVE.version if ACTIVE and ACTIVE.source == "installed" and ACTIVE.version != version else None
    st.update({"current": version, "previous": keep_prev, "pending": True, "boot_attempts": 0, "failed": None,
               "installed_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    save_state(st)
    prune(st)
    return st


def prune(st: dict | None = None) -> None:
    """Delete installed bundles other than current/previous (and the running one)."""
    st = load_state() if st is None else st
    keep = {str(st.get("current")), str(st.get("previous"))}
    if ACTIVE and ACTIVE.source == "installed":
        keep.add(ACTIVE.version)
    root = app_root()
    if not root.is_dir():
        return
    for d in root.iterdir():
        if d.is_dir() and parse_version(d.name) and d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)


def rollback(package: str = PACKAGE) -> dict:
    """User-requested rollback: use the previous bundle (or the bundled copy) from the next start on."""
    st = load_state()
    if not st.get("current"):
        raise ValueError("no installed update to roll back")
    st = _rollback(st, "rolled back by the user")
    nxt = candidates(st, package)
    return {"state": st, "next": nxt[0].to_dict() if nxt else None}


def next_start(package: str = PACKAGE) -> Candidate | None:
    c = candidates(None, package)
    return c[0] if c else None


# ------------------------------------------------------------------ command line helpers
def is_gui(argv: list[str]) -> bool:
    """Mirror of encorlab.launcher._parse: no sub-command left after the launcher options means 'start the web UI'."""
    rest = list(argv)
    while rest and rest[0].startswith("--"):
        a = rest.pop(0)
        if a in ("--no-browser", "--restarted") or a.startswith("--port="):
            continue
        if a == "--port" and rest:
            rest.pop(0)
            continue
        return False
    return not rest
