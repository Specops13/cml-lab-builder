"""Automatic patch updates for the packaged app (Windows and Linux).

A background thread checks the GitHub Releases API shortly after startup and then every ~6 hours (conditional
requests with ETag, so an unchanged release costs nothing against the rate limit). If a newer release carries an
app-code patch that fits this runtime, the patch is downloaded and verified in the background (SHA256SUMS, manifest
hashes, safe paths, version, min_runtime) and kept in <data>/updates/staged/. It is NOT installed: the web UI asks
"Update now / Later / Skip this version". Update now waits until no lab build, grading, snapshot, fault injection or
exam is running, installs the staged patch, restarts the app and the page reconnects.

Failures (offline, rate limits, bad downloads) are logged to <data>/updates/update.log and retried with backoff;
they never pop up. A version that was rolled back (automatically or by the user) or skipped is not offered again
unless the user checks manually. Running from source disables all of this (use git pull)."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from . import __version__, library, updates

log = logging.getLogger("encorlab.update")

INTERVAL = 6 * 3600          # between successful checks
FIRST_DELAY = 45             # after startup, so the first check never slows the start
LATER = 4 * 3600             # "Later" hides the prompt this long (or until the next launch)
MIN_BACKOFF = 15 * 60        # after a failure: 15 min, 30 min, 1 h ... capped at MAX_BACKOFF
MAX_BACKOFF = 12 * 3600
WAIT_POLL = 2.0              # Update now: how often to look whether the running work has finished
SESSION = uuid.uuid4().hex   # this process: "Later" lasts until the next launch
RELEASE_LIMIT = 512 * 1024
SUMS_LIMIT = 1024 * 1024
LOG_LIMIT = 256 * 1024
KEEP_LIST = 20

_LOCK = threading.RLock()


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "")) if os.environ.get(name) else default
    except ValueError:
        return default


def interval() -> float:
    return _env_num("ENCOR_UPDATE_INTERVAL", INTERVAL)


def first_delay() -> float:
    return _env_num("ENCOR_UPDATE_DELAY", FIRST_DELAY)


def root() -> Path:
    from .history import data_dir
    return data_dir() / "updates"


def staged_dir() -> Path:
    return root() / "staged"


# ------------------------------------------------------------------ state + log
def load() -> dict:
    try:
        d = json.loads((root() / "auto.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(st: dict) -> None:
    r = root()
    r.mkdir(parents=True, exist_ok=True)
    tmp = r / f".auto.json.{os.getpid()}.{threading.get_ident()}"
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, r / "auto.json")


def note(msg: str, level: int = logging.INFO) -> None:
    """Quiet log: Python logging plus <data>/updates/update.log (truncated when it grows past 256 KB)."""
    log.log(level, msg)
    try:
        r = root()
        r.mkdir(parents=True, exist_ok=True)
        f = r / "update.log"
        if f.exists() and f.stat().st_size > LOG_LIMIT:
            f.write_text(f.read_text(encoding="utf-8", errors="replace")[-LOG_LIMIT // 2:], encoding="utf-8")
        with f.open("a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def _newer(v: str | None, than: str = __version__) -> bool:
    a, b = updates.parse_version(v or ""), updates.parse_version(than)
    return bool(a and b and a > b)


def _add(st: dict, key: str, version: str) -> None:
    lst = [x for x in st.get(key) or [] if x != version] + [version]
    st[key] = lst[-KEEP_LIST:]


def _sync_rollbacks(st: dict) -> None:
    """A version the boot loader rolled back (it failed to start, or the user clicked Roll back) is never offered
    again automatically."""
    b = updates._boot()
    if b is None:
        return
    try:
        rec = b.load_state().get("failed") or {}
    except Exception:
        rec = {}
    failed = rec.get("version")
    key = f"{failed}@{rec.get('at')}"
    if not failed or st.get("seen_failed") == key:   # each rollback is counted once (a manual check may undo it)
        return
    st["seen_failed"] = key
    if failed != __version__:
        _add(st, "rolled_back", str(failed))
        if st.get("manual") == failed:
            st.pop("manual", None)
        note(f"version {failed} was rolled back; it will not be offered again automatically")


# ------------------------------------------------------------------ the updater
class Updater:
    """One per web app. fetch(url, limit, etag) -> (status, body, headers) like updates.http_get; busy() -> list of
    human-readable reasons why an update must wait; restart() restarts the app (launcher.request_restart);
    settings() -> current Settings."""

    def __init__(self, settings=None, fetch=None, busy=None, restart=None, now=time.time, sleep=None):
        self.settings = settings or (lambda: None)
        self.fetch = fetch or updates.http_get
        self.busy = busy or (lambda: [])
        self.restart = restart or _restart
        self.now = now
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._sleep = sleep or (lambda s: self._stop.wait(s))
        self._check_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self.checking = False

    # -------------------------------------------------------------- enabled?
    def enabled(self) -> tuple[bool, str]:
        ok, why = updates.patchable()
        if not ok:
            return False, why
        s = self.settings()
        if s is not None and not getattr(s, "check_updates", True):
            return False, "automatic update checks are turned off in Settings"
        return True, ""

    # -------------------------------------------------------------- background loop
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        resume = self.startup()
        self._thread = threading.Thread(target=self._loop, name="encorlab-updater", daemon=True)
        self._thread.start()
        if resume:
            self._spawn_worker()

    def startup(self) -> bool:
        """Tidy the state of an earlier process. Returns True when an Update now is still waiting."""
        with _LOCK:
            st = load()
            a = st.get("apply") or {}
            resume = a.get("state") == "waiting" and _newer(a.get("version"))
            if a and not resume:
                st.pop("apply", None)
            elif resume:
                st["apply"] = {**a, "session": SESSION}
            staged = st.get("staged") or {}
            if staged and not _newer(staged.get("version")):
                (staged_dir() / str(staged.get("file") or "x")).unlink(missing_ok=True)
                st.pop("staged", None)
            save(st)
        return resume

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        """Settings changed: re-evaluate soon."""
        self._wake.set()

    def _loop(self) -> None:
        if self._stop.wait(first_delay()):
            return
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:  # never let the updater take the app down
                note(f"updater error: {type(e).__name__}: {e}", logging.WARNING)
            st = load()
            wait = max(5.0, float(st.get("next_check") or 0) - self.now())
            self._wake.wait(min(wait, interval()))
            self._wake.clear()

    def tick(self) -> dict | None:
        """One scheduler step: check if enabled and due."""
        ok, _ = self.enabled()
        if not ok:
            return None
        st = load()
        if self.now() < float(st.get("next_check") or 0):
            return None
        return self.check(manual=False)

    # -------------------------------------------------------------- check + stage
    def check(self, manual: bool = False) -> dict:
        """Ask GitHub for the latest release; download, verify and stage its patch when it is newer.
        Automatic checks never raise; manual ones raise library.LibraryError / updates.UpdateError."""
        with self._check_lock:
            self.checking = True
            try:
                return self._check(manual)
            finally:
                self.checking = False

    def _check(self, manual: bool) -> dict:
        now = self.now()
        with _LOCK:
            st = load()
            _sync_rollbacks(st)
        etag = st.get("etag") if st.get("release") else None
        try:
            code, body, hdrs = self.fetch(updates.release_url(), RELEASE_LIMIT, etag)
            if code == 304:
                rel = st["release"]
            else:
                info = updates.parse_release(body, __version__)
                rel = {k: info[k] for k in ("latest", "tag", "url", "name", "published_at", "assets")}
                etag = hdrs.get("etag")
        except library.LibraryError as e:
            self._failed(e, now)
            if manual:
                raise
            return {"status": "error", "error": str(e)}
        with _LOCK:
            st = load()
            _sync_rollbacks(st)
            st.update(release=rel, etag=etag, last_check=now, last_ok=now)
            latest = rel["latest"]
            if manual:   # an explicit check may offer a skipped or rolled-back version again
                for key in ("skipped", "rolled_back"):
                    st[key] = [v for v in st.get(key) or [] if v != latest]
                if _newer(latest):
                    st["manual"] = latest
                st.pop("later", None)
            save(st)
        if not _newer(latest):
            self._done(now, clear=True)
            return {"status": "up_to_date", "latest": latest}
        if not manual and latest in set(st.get("skipped") or []) | set(st.get("rolled_back") or []):
            self._done(now)
            return {"status": "suppressed", "latest": latest}
        try:
            res = self._stage(rel)
        except (updates.UpdateError, library.LibraryError) as e:
            self._failed(e, now)
            if manual:
                raise
            return {"status": "error", "error": str(e)}
        self._done(now)
        return res

    def _stage(self, rel: dict) -> dict:
        latest = rel["latest"]
        by_name = {a["name"]: a for a in rel.get("assets") or []}
        pname = updates.patch_name(latest)
        st = load()
        staged = st.get("staged") or {}
        if staged.get("version") == latest and _staged_ok(staged):
            return {"status": "staged", "version": latest, "cached": True}
        patch = by_name.get(pname)
        if not patch:
            return self._full(latest, rel["url"], f"release {rel['tag']} has no app patch")
        sums = next((by_name[n] for n in updates.SUMS_NAMES if n in by_name), None)
        if not sums:
            raise updates.UpdateError(f"release {rel['tag']} has no SHA256SUMS.txt; the patch cannot be verified")
        expected = updates.parse_sums(self.fetch(sums["url"], SUMS_LIMIT, None)[1].decode("utf-8", "replace")).get(pname)
        if not expected:
            raise updates.UpdateError(f"SHA256SUMS of {rel['tag']} has no entry for {pname}")
        data = self.fetch(patch["url"], updates.MAX_PATCH_BYTES, None)[1]
        got = library.sha256(data)
        if got != expected:
            raise updates.UpdateError(f"downloaded patch {pname} does not match SHA256SUMS ({got[:12]}…)")
        b = updates._boot()
        try:
            m = updates.verify_patch(data, latest, getattr(b, "RUNTIME_VERSION", None))
        except updates.RuntimeTooOld as e:
            return self._full(latest, rel["url"], str(e), needed=e.needed)
        d = staged_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{pname}.{os.getpid()}"
        tmp.write_bytes(data)
        os.replace(tmp, d / pname)
        for old in d.glob(updates.PATCH_PREFIX + "*.zip"):
            if old.name != pname:
                old.unlink(missing_ok=True)
        with _LOCK:
            st = load()
            st["staged"] = {"version": latest, "file": pname, "sha256": got, "size": len(data), "url": rel["url"],
                            "min_runtime": m["min_runtime"], "staged_at": self.now()}
            st.pop("full_download", None)
            save(st)
        note(f"staged {pname} ({len(data)} bytes, verified); waiting for the user")
        return {"status": "staged", "version": latest, "size": len(data)}

    def _full(self, version: str, url: str, reason: str, needed: int | None = None) -> dict:
        with _LOCK:
            st = load()
            st["full_download"] = {"version": version, "url": url, "reason": reason, "needed_runtime": needed}
            st.pop("staged", None)
            save(st)
        note(f"{version} needs a full download: {reason}")
        return {"status": "full_download", "version": version, "reason": reason, "url": url}

    def _done(self, now: float, clear: bool = False) -> None:
        with _LOCK:
            st = load()
            st.update(failures=0, last_error=None, next_check=now + interval())
            if clear:
                for k in ("staged", "full_download", "manual"):
                    st.pop(k, None)
            save(st)

    def _failed(self, e: Exception, now: float) -> None:
        with _LOCK:
            st = load()
            n = int(st.get("failures") or 0) + 1
            wait = min(MAX_BACKOFF, MIN_BACKOFF * 2 ** (n - 1))
            hdrs = getattr(e, "headers", {}) or {}
            status = getattr(e, "status", None)
            if status in (403, 429):   # GitHub rate limit: wait for the reset time it tells us
                try:
                    if hdrs.get("retry-after"):
                        wait = max(wait, float(hdrs["retry-after"]))
                    elif hdrs.get("x-ratelimit-remaining") == "0" and hdrs.get("x-ratelimit-reset"):
                        wait = max(wait, float(hdrs["x-ratelimit-reset"]) - now + 5)
                except ValueError:
                    pass
                wait = min(wait, 24 * 3600)
            st.update(failures=n, last_error=str(e)[:300], last_error_at=now, next_check=now + wait)
            save(st)
        note(f"update check failed ({n} in a row), next try in {int(wait // 60)} min: {e}", logging.WARNING)

    # -------------------------------------------------------------- what the web UI shows
    def state(self) -> dict:
        ok, why = self.enabled()
        with _LOCK:
            st = load()
            before = dict(st)
            _sync_rollbacks(st)
            if st != before:
                save(st)
        now = self.now()
        out = {"version": __version__, "enabled": ok, "reason": why, "patchable": updates.patchable()[0],
               "checking": self.checking, "last_check": st.get("last_check"), "next_check": st.get("next_check"),
               "last_error": st.get("last_error"), "failures": int(st.get("failures") or 0),
               "offer": None, "full_download": None, "just_updated": None, "apply": None, "failed_update": None}
        staged = st.get("staged") or {}
        v = staged.get("version")
        if v and _newer(v) and _staged_ok(staged):
            hidden = v in set(st.get("skipped") or []) | set(st.get("rolled_back") or []) and st.get("manual") != v
            later = st.get("later") or {}
            if later.get("version") == v and later.get("session") == SESSION and now < float(later.get("until") or 0):
                hidden = True
            apply = st.get("apply") or {}
            if apply.get("version") == v:
                hidden = False
                out["apply"] = apply
            if not hidden:
                out["offer"] = {"version": v, "size": staged.get("size"), "url": staged.get("url"),
                                "changelog": f"https://github.com/{updates.REPO}/blob/v{v}/CHANGELOG.md",
                                "busy": self.busy()}
        fd = st.get("full_download") or {}
        if fd.get("version") and _newer(fd["version"]) and st.get("dismissed_full") != fd["version"]:
            out["full_download"] = fd
        applied = st.get("applied") or {}
        if applied.get("version") == __version__ and st.get("acked") != __version__:
            out["just_updated"] = {"version": __version__, "from": applied.get("from")}
        elif applied.get("version") and applied["version"] in (st.get("rolled_back") or []) \
                and st.get("acked_failed") != applied["version"]:
            out["failed_update"] = {"version": applied["version"]}
        return out

    # -------------------------------------------------------------- user answers
    def later(self) -> dict:
        with _LOCK:
            st = load()
            v = (st.get("staged") or {}).get("version")
            st["later"] = {"version": v, "until": self.now() + LATER, "session": SESSION}
            save(st)
        return {"status": "later", "version": v}

    def skip(self, version: str) -> dict:
        with _LOCK:
            st = load()
            _add(st, "skipped", version)
            if st.get("manual") == version:
                st.pop("manual", None)
            if (st.get("apply") or {}).get("version") == version:
                st.pop("apply", None)
            save(st)
        note(f"user skipped version {version}")
        return {"status": "skipped", "version": version}

    def dismiss_full(self, version: str) -> dict:
        with _LOCK:
            st = load()
            st["dismissed_full"] = version
            save(st)
        return {"status": "dismissed", "version": version}

    def ack(self) -> dict:
        with _LOCK:
            st = load()
            applied = (st.get("applied") or {}).get("version")
            if applied == __version__:
                st["acked"] = __version__
            elif applied:
                st["acked_failed"] = applied
            save(st)
        return {"status": "ok"}

    def apply(self, version: str) -> dict:
        """Update now: install the staged patch as soon as nothing is running, then restart."""
        ok, why = updates.patchable()
        if not ok:
            raise updates.UpdateError(f"updates are not available: {why}")
        with _LOCK:
            st = load()
            staged = st.get("staged") or {}
            if staged.get("version") != version or not _staged_ok(staged):
                raise updates.UpdateError(f"version {version} is not downloaded (check for updates again)")
            cur = st.get("apply") or {}
            if cur.get("version") == version and cur.get("session") == SESSION \
                    and cur.get("state") in ("waiting", "installing", "restarting"):
                return cur
            st["apply"] = {"version": version, "state": "waiting", "requested_at": self.now(), "waiting_for": self.busy(),
                           "session": SESSION}
            save(st)
        note(f"user chose Update now for {version}")
        self._spawn_worker()
        return load()["apply"]

    def cancel(self) -> dict:
        with _LOCK:
            st = load()
            a = st.get("apply") or {}
            if a.get("state") == "waiting":
                st.pop("apply", None)
                save(st)
                return {"status": "cancelled"}
        return {"status": a.get("state") or "idle"}

    def applying(self) -> bool:
        """True while the staged patch is being installed / the app restarts: new work must not start now."""
        a = load().get("apply") or {}
        return a.get("state") in ("installing", "restarting") and a.get("session") == SESSION

    def _spawn_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._apply_worker, name="encorlab-update-apply", daemon=True)
        self._worker.start()

    def _apply_worker(self) -> None:
        while True:
            st = load()
            a = st.get("apply") or {}
            if a.get("state") != "waiting":
                return
            reasons = self.busy()
            if not reasons:
                with _LOCK:
                    st = load()
                    a = st.get("apply") or {}
                    if a.get("state") != "waiting":
                        return
                    a.update(state="installing", waiting_for=[])
                    st["apply"] = a
                    save(st)
                # last look: work started between the check and the state change waits for us (jobs are gated)
                if self.busy():
                    with _LOCK:
                        st = load()
                        st["apply"] = {**a, "state": "waiting"}
                        save(st)
                    self._sleep(WAIT_POLL)
                    continue
                break
            if a.get("waiting_for") != reasons:
                with _LOCK:
                    st = load()
                    if (st.get("apply") or {}).get("state") == "waiting":
                        st["apply"]["waiting_for"] = reasons
                        save(st)
            if self._sleep(WAIT_POLL):
                return
        v = a["version"]
        try:
            staged = load().get("staged") or {}
            if staged.get("version") != v or not _staged_ok(staged):
                raise updates.UpdateError("the downloaded patch is missing or changed; check for updates again")
            data = (staged_dir() / staged["file"]).read_bytes()
            updates.install_bytes(data, expected_version=v)
            with _LOCK:
                st = load()
                st["applied"] = {"version": v, "from": __version__, "at": self.now()}
                st["apply"] = {**a, "state": "restarting"}
                st.pop("later", None)
                save(st)
            note(f"installed {v}; restarting")
        except Exception as e:
            with _LOCK:
                st = load()
                st["apply"] = {**a, "state": "error", "error": str(e)[:300]}
                save(st)
            note(f"installing {v} failed: {e}", logging.WARNING)
            return
        try:
            self.restart()
        except Exception as e:
            with _LOCK:
                st = load()
                st["apply"] = {**a, "state": "installed", "error": f"restart the app to finish: {e}"}
                save(st)
            note(f"{v} installed but the app could not restart itself: {e}", logging.WARNING)


def _staged_ok(staged: dict) -> bool:
    try:
        f = staged_dir() / str(staged.get("file") or "")
        return f.is_file() and f.name.startswith(updates.PATCH_PREFIX) and library.sha256(f.read_bytes()) == staged.get("sha256")
    except OSError:
        return False


def _restart() -> None:
    from . import launcher
    launcher.request_restart()
