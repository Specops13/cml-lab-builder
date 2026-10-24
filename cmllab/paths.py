"""Where user data lives, and the one-time move from the old folder name.

Up to 2.0.0 the data folder was %APPDATA%\\encorlab (Windows) or ~/.config/encorlab (Linux). Since 2.1.0 it is
%APPDATA%\\cml-lab-builder or ~/.config/cml-lab-builder. On the first start of 2.1+ (and of 3.0 for anyone coming
straight from 2.0 or older) everything in the old folder is copied to the new one (settings, imported and library
labs, history, snapshots, walkthrough progress, faults, exams, reports, courses, update state, logs), every file is
compared by sha256, the new folder is put in place in one rename, the keyring password is copied to the new keyring
name, and MOVED.txt is written to the old folder. The old folder is never deleted.

app/ is not copied. In 2.1 it held the patches of the old program, whose boot loader only looked in the old folder.
From 3.0.0 (runtime 2) the boot loader keeps app/ in the new folder; the old app/ bundles contain the old `encorlab`
package and cannot run on runtime 2, so 3.0 starts with its own bundled code and a fresh update chain.

Safe to run on every start: the move happens once (marker migrations/data-folder.json in the new folder). If an old
version runs again later and creates files in the old folder, the next start copies the files it wrote after the move
that are missing in the new folder; existing files in the new folder are never overwritten (and a lab deleted in the
new version does not come back).

CMLLAB_DATA_DIR / CMLLAB_SETTINGS_FILE (or the pre-3.0 ENCOR_* names) pin the folder; nothing is moved then."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path

NAME = "cml-lab-builder"
LEGACY_NAME = "encorlab"
BOOT_DIRS = ("app",)                       # app updates of the old program (runtime 1): never copied
SKIP = {"MOVED.txt"}
MARKER = Path("migrations") / "data-folder.json"
_LOCK = threading.Lock()
_DONE: dict[str, dict] = {}


def env_get(name: str, env=None) -> str:
    """CMLLAB_<name>, else ENCOR_<name> (the pre-3.0 prefix), else ""."""
    e = os.environ if env is None else env
    return e.get("CMLLAB_" + name) or e.get("ENCOR_" + name) or ""


def base_dir(env=None) -> Path:
    e = os.environ if env is None else env
    if os.name == "nt" and e.get("APPDATA"):
        return Path(e["APPDATA"])
    return Path(e["XDG_CONFIG_HOME"]) if e.get("XDG_CONFIG_HOME") else Path.home() / ".config"


def default_dir(env=None) -> Path:
    return base_dir(env) / NAME


def legacy_dir(env=None) -> Path:
    return base_dir(env) / LEGACY_NAME


def pinned(env=None) -> Path | None:
    """A folder set by environment variable (then the boot loader uses it too and nothing moves)."""
    if env_get("DATA_DIR", env):
        return Path(env_get("DATA_DIR", env))
    if env_get("SETTINGS_FILE", env):
        return Path(env_get("SETTINGS_FILE", env)).parent
    return None


def data_dir(env=None, move: bool = True) -> Path:
    """The user data folder. With the default location, the first call per process runs ensure_moved()."""
    p = pinned(env)
    if p is not None:
        return p
    new = default_dir(env)
    if move and env is None and ensure_moved().get("state") == "failed" and legacy_dir().is_dir():
        return legacy_dir()          # the copy failed: keep using the old folder (nothing is lost; retried next start)
    return new


def boot_dir() -> Path:
    """The folder the boot loader keeps app updates (app/) in: the data folder (runtime 2, 3.0.0+)."""
    try:
        import cmlboot
        return cmlboot.data_dir()
    except Exception:  # pragma: no cover - cmlboot always ships with the app
        return pinned() or default_dir()


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _files(root: Path) -> list[Path]:
    """Files to move, relative to root: everything except app/ (boot loader) and MOVED.txt."""
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if rel.parts[0] in BOOT_DIRS or (len(rel.parts) == 1 and rel.name in SKIP) or p.is_symlink() or not p.is_file():
            continue
        out.append(rel)
    return out


def _marker(new: Path) -> dict | None:
    try:
        d = json.loads((new / MARKER).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write_marker(new: Path, rec: dict) -> None:
    f = new / MARKER
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    os.replace(tmp, f)


MOVED_TXT = """CML Lab Builder (formerly ENCOR Lab Builder) {version} moved your data on {when} to:

    {new}

Everything was copied and checked; this folder was left as it was, so nothing is lost and an older version of the
app still finds its data here. Once you are happy with the new version you can delete this whole folder (its app
folder only holds updates for the old ENCOR Lab Builder program).
"""


def ensure_moved(env=None, now=None) -> dict:
    """Run the move once per process (and at most once per data folder). Never raises; returns the marker record
    (state: "moved", "fresh", "pinned", "failed"), with "caught_up" listing files copied on a later start."""
    if pinned(env) is not None:
        return {"state": "pinned"}
    new, old = default_dir(env), legacy_dir(env)
    key = str(new)
    with _LOCK:
        if key in _DONE:
            return _DONE[key]
        try:
            rec = _move(old, new, now or time.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:  # noqa: BLE001 - never stop the app; it runs on the new (maybe empty) folder
            rec = {"state": "failed", "error": f"{type(e).__name__}: {e}", "from": str(old), "to": str(new)}
        _DONE[key] = rec
        return rec


def _move(old: Path, new: Path, when: str) -> dict:
    from . import __version__
    rec = _marker(new)
    if rec is not None:                                   # moved (or started fresh) before: copy what is missing
        note = old / "MOVED.txt"
        try:   # the 2.1 note said to keep the old app folder; from 3.0 nothing in the old folder is needed
            if rec.get("state") == "moved" and note.is_file() and "only holds updates" not in note.read_text(encoding="utf-8"):
                note.write_text(MOVED_TXT.format(version=__version__, when=rec.get("at", when), new=new), encoding="utf-8")
        except OSError:
            pass
        if rec.get("state") == "moved" and old.is_dir():
            added, since = [], float(rec.get("at_epoch") or 0)
            for rel in _files(old):      # only files the old app wrote after the move (deleted labs stay deleted)
                if since and (old / rel).stat().st_mtime > since and not (new / rel).exists():
                    (new / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(old / rel, new / rel)
                    added.append(rel.as_posix())
            if added:
                rec["caught_up"] = sorted(set(rec.get("caught_up", [])) | set(added))
                rec["caught_up_at"] = when
                _write_marker(new, rec)
            rec = {**rec, "new_files": added}
        return rec
    files = _files(old) if old.is_dir() else []
    if not files:                                         # nothing to move: a new user (or only app/ in the old folder)
        new.mkdir(parents=True, exist_ok=True)
        rec = {"state": "fresh", "to": str(new), "at": when, "version": __version__}
        _write_marker(new, rec)
        return rec
    if new.exists() and any(new.iterdir()):
        # a new-name folder without a marker (e.g. made by hand): merge into it without overwriting anything
        target, staged = new, False
    else:
        for left in new.parent.glob(f".{NAME}.moving-*"):     # an earlier start that was interrupted
            if time.time() - left.stat().st_mtime > 600:
                shutil.rmtree(left, ignore_errors=True)
        target, staged = new.with_name(f".{NAME}.moving-{os.getpid()}"), True
    copied, skipped, total = [], [], 0
    for rel in files:
        dst = target / rel
        if dst.exists():
            skipped.append(rel.as_posix())
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old / rel, dst)
        copied.append(rel.as_posix())
        total += dst.stat().st_size
    bad = [r for r in copied if _sha(old / r) != _sha(target / r)]
    if bad:
        if staged:
            shutil.rmtree(target, ignore_errors=True)
        raise OSError(f"copy check failed for {len(bad)} file(s), e.g. {bad[0]}; the old folder is still used")
    rec = {"state": "moved", "from": str(old), "to": str(new), "at": when, "at_epoch": time.time(), "version": __version__,
           "files": len(copied), "bytes": total, "kept_existing": skipped, "boot_dirs_left": list(BOOT_DIRS),
           "keyring": _move_keyring(target), "notified": False}
    _write_marker(target, rec)                             # the marker lands together with the data
    if staged:
        try:
            if new.exists():
                new.rmdir()                                # empty folder
            os.replace(target, new)
        except OSError:
            shutil.rmtree(target, ignore_errors=True)
            done = _marker(new)
            if done is not None:                           # another process (CLI and GUI at once) finished first
                return done
            raise
    try:
        (old / "MOVED.txt").write_text(MOVED_TXT.format(version=__version__, when=when, new=new), encoding="utf-8")
    except OSError:
        pass
    return rec


def _move_keyring(new: Path) -> str:
    """Copy a keyring password stored under the old service name to the new one (the old entry stays)."""
    try:
        s = json.loads((new / "settings.json").read_text(encoding="utf-8"))
        user = s.get("username") or ""
    except (OSError, ValueError):
        return "no settings"
    if not user:
        return "no username"
    from . import config
    try:
        import keyring
        if keyring.get_password(config.KEYRING_SERVICE, user):
            return "already there"
        pw = keyring.get_password(config.LEGACY_KEYRING_SERVICE, user)
        if not pw:
            return "none stored"
        keyring.set_password(config.KEYRING_SERVICE, user, pw)
        return "copied"
    except Exception as e:  # noqa: BLE001 - no keyring backend: the password was never stored there
        return f"unavailable ({type(e).__name__})"


def status() -> dict:
    """The move record for the UI (pinned folders have none)."""
    if pinned() is not None:
        return {"state": "pinned", "to": str(pinned())}
    return _marker(default_dir()) or {"state": "unknown"}


def acknowledge(flag: str = "notified") -> dict:
    """The one-time 'Your data moved' note was shown (notified: web UI, cli_notified: command line)."""
    if pinned() is not None:
        return {}
    new = default_dir()
    rec = _marker(new)
    if rec and not rec.get(flag):
        rec[flag] = True
        _write_marker(new, rec)
    return rec or {}


def reset_cache() -> None:
    """Tests: forget that this process already ran the move."""
    with _LOCK:
        _DONE.clear()


_SAFE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def safe_name(name: str) -> str:
    """A lab id / file stem used inside a data folder: no separators, no '..' (path traversal guard, 3.3.0)."""
    if not isinstance(name, str) or not _SAFE.match(name) or ".." in name:
        raise ValueError(f"invalid name: {name!r}")
    return name
