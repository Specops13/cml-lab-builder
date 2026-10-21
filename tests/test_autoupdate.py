"""Automatic updates: scheduler, ETag + backoff, background staging, the prompt API, idle gating, Later / Skip,
no re-offer after rollback, runtime gating, and the real HTTP path against a local fake release."""
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import cmlboot
from cmllab import __version__, autoupdate, catalog, config, exam, library, updates
from cmllab.web.app import create_app
from test_patching import build_patch, make_src, mkbundle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from fake_release import FakeRelease  # noqa: E402

NEW = "9.9.9"


@pytest.fixture(scope="module")
def patches(tmp_path_factory):
    t = tmp_path_factory.mktemp("patches")
    good = build_patch.build_patch(make_src(t, NEW), t / "good").read_bytes()
    newer_rt = build_patch.build_patch(make_src(t / "rt", NEW), t / "rt-out", min_runtime=cmlboot.RUNTIME_VERSION + 1).read_bytes()
    return {"good": good, "newer_runtime": newer_rt}


@pytest.fixture
def packaged(tmp_path, monkeypatch):
    """Pretend to be the packaged app running its bundled copy of the current version."""
    bundled = mkbundle(tmp_path / "bundled", __version__, pkg="cmllab")
    monkeypatch.setattr(cmlboot, "frozen", lambda: True)
    monkeypatch.setattr(cmlboot, "bundled_dir", lambda: bundled)
    monkeypatch.setattr(cmlboot, "ACTIVE", cmlboot.Candidate("bundled", __version__, bundled))
    monkeypatch.setattr(autoupdate, "WAIT_POLL", 0.02)
    return bundled


class GitHub:
    """In-memory fake of the Releases API + asset downloads, with ETag support and failure injection."""
    BASE = f"https://github.com/{updates.REPO}/releases/download/v{NEW}/"

    def __init__(self, patch: bytes | None, version: str = NEW, sums: str | None = None):
        self.version, self.patch, self.sums_override = version, patch, sums
        self.calls: list[tuple[str, str | None]] = []
        self.fail: Exception | None = None

    def release(self) -> bytes:
        assets = [{"name": f"CMLLabBuilder-{self.version}-windows-x64.zip", "size": 26_000_000,
                   "browser_download_url": self.BASE + f"CMLLabBuilder-{self.version}-windows-x64.zip"}]
        if self.patch is not None:
            assets += [{"name": f"cml-lab-builder-patch-{self.version}.zip", "size": len(self.patch),
                        "browser_download_url": self.BASE + f"cml-lab-builder-patch-{self.version}.zip"},
                       {"name": "SHA256SUMS.txt", "size": 100, "browser_download_url": self.BASE + "SHA256SUMS.txt"}]
        return json.dumps({"tag_name": f"v{self.version}", "assets": assets,
                           "html_url": f"https://github.com/{updates.REPO}/releases/tag/v{self.version}"}).encode()

    def __call__(self, url, limit, etag=None):
        self.calls.append((url, etag))
        if self.fail:
            raise self.fail
        if url == updates.LATEST_URL:
            body = self.release()
            tag = '"' + library.sha256(body)[:16] + '"'
            return (304, b"", {"etag": tag}) if etag == tag else (200, body, {"etag": tag})
        if url.endswith("SHA256SUMS.txt"):
            text = self.sums_override if self.sums_override is not None else \
                f"{library.sha256(self.patch)}  cml-lab-builder-patch-{self.version}.zip\n"
            return 200, text.encode(), {}
        if url.endswith(".zip"):
            return 200, self.patch, {}
        raise AssertionError(url)

    def downloads(self):
        return [u for u, _ in self.calls if u != updates.LATEST_URL]


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def make(gh, busy=None, restarts=None, settings=None, clock=None):
    restarts = restarts if restarts is not None else []
    return autoupdate.Updater(settings=settings or (lambda: config.Settings()), fetch=gh, busy=busy or (lambda: []),
                              restart=lambda: restarts.append(1), now=clock or Clock())


def wait_for(cond, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------- enabled / scheduler
def test_source_tree_never_checks():
    gh = GitHub(b"")
    u = make(gh)
    assert u.enabled()[0] is False and "source" in u.enabled()[1]
    assert u.tick() is None and gh.calls == []
    assert u.state()["enabled"] is False and u.state()["offer"] is None


def test_setting_off_disables_checks(packaged, patches):
    gh = GitHub(patches["good"])
    u = make(gh, settings=lambda: config.Settings(check_updates=False))
    assert u.enabled() == (False, "automatic update checks are turned off in Settings")
    assert u.tick() is None and gh.calls == []


def test_scheduler_checks_when_due_and_uses_etag(packaged, patches):
    gh, clock = GitHub(patches["good"]), Clock()
    u = make(gh, clock=clock)
    assert u.tick()["status"] == "staged"
    assert autoupdate.load()["next_check"] == clock.t + autoupdate.INTERVAL
    assert u.tick() is None and len(gh.calls) == 3          # not due yet: no request
    clock.t += autoupdate.INTERVAL + 1
    r = u.tick()
    assert r["status"] == "staged" and r["cached"]          # 304 + already staged: nothing downloaded again
    assert gh.calls[-1][1] and gh.calls[-1][0] == updates.LATEST_URL and len(gh.calls) == 4


def test_background_thread_runs_first_check_after_delay(packaged, patches, monkeypatch):
    monkeypatch.setenv("CMLLAB_UPDATE_DELAY", "0.05")
    gh = GitHub(patches["good"])
    u = autoupdate.Updater(settings=lambda: config.Settings(), fetch=gh)
    u.start()
    try:
        assert wait_for(lambda: (autoupdate.load().get("staged") or {}).get("version") == NEW)
    finally:
        u.stop()


# ---------------------------------------------------------------- staging
def test_check_stages_but_does_not_install(packaged, patches):
    u = make(GitHub(patches["good"]))
    assert u.check()["status"] == "staged"
    st = autoupdate.load()["staged"]
    assert st["version"] == NEW and st["size"] == len(patches["good"])
    assert (autoupdate.staged_dir() / f"cml-lab-builder-patch-{NEW}.zip").is_file()
    assert not (cmlboot.app_root() / NEW).exists() and not cmlboot.load_state().get("current")
    offer = u.state()["offer"]
    assert offer["version"] == NEW and offer["url"].endswith(f"/v{NEW}") and "CHANGELOG.md" in offer["changelog"]


def test_up_to_date_clears_old_offers(packaged, patches):
    make(GitHub(patches["good"])).check()
    u = make(GitHub(None, version=__version__))
    assert u.check()["status"] == "up_to_date"
    assert u.state()["offer"] is None and "staged" not in autoupdate.load()


def test_bad_download_is_quiet_and_backs_off(packaged, patches):
    clock = Clock()
    u = make(GitHub(patches["good"], sums="0" * 64 + f"  cml-lab-builder-patch-{NEW}.zip\n"), clock=clock)
    r = u.check()                                          # automatic: never raises
    assert r["status"] == "error" and "SHA256SUMS" in r["error"]
    st = u.state()
    assert st["offer"] is None and st["failures"] == 1 and "SHA256SUMS" in st["last_error"]
    assert autoupdate.load()["next_check"] == clock.t + autoupdate.MIN_BACKOFF
    assert not list(autoupdate.staged_dir().glob("*.zip")) if autoupdate.staged_dir().exists() else True
    assert "check failed" in (autoupdate.root() / "update.log").read_text()


def test_backoff_grows_and_honours_rate_limits(packaged, patches):
    gh, clock = GitHub(patches["good"]), Clock()
    u = make(gh, clock=clock)
    gh.fail = library.LibraryError("network error fetching x: ConnectError")
    waits = []
    for _ in range(4):
        u.check()
        waits.append(autoupdate.load()["next_check"] - clock.t)
        clock.t = autoupdate.load()["next_check"]
    assert waits == [900, 1800, 3600, 7200]
    gh.fail = updates.HTTPStatusError(403, updates.LATEST_URL,
                                      {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(clock.t + 20000))})
    u.check()
    assert autoupdate.load()["next_check"] >= clock.t + 20000
    with pytest.raises(library.LibraryError):              # a manual check does report the error
        u.check(manual=True)
    gh.fail = None
    clock.t = autoupdate.load()["next_check"]
    assert u.check()["status"] == "staged"
    st = autoupdate.load()
    assert st["failures"] == 0 and st["last_error"] is None and st["next_check"] == clock.t + autoupdate.INTERVAL


def test_runtime_gating_shows_full_download(packaged, patches):
    u = make(GitHub(patches["newer_runtime"]))
    r = u.check()
    assert r["status"] == "full_download" and f"runtime {cmlboot.RUNTIME_VERSION + 1}" in r["reason"]
    st = u.state()
    assert st["offer"] is None and st["full_download"]["version"] == NEW
    assert not list(autoupdate.staged_dir().glob("*.zip"))
    u.dismiss_full(NEW)
    assert u.state()["full_download"] is None


def test_release_without_patch_needs_full_download(packaged):
    u = make(GitHub(None))
    assert u.check()["status"] == "full_download"
    assert "no app patch" in u.state()["full_download"]["reason"]


# ---------------------------------------------------------------- Later / Skip / rollback
def test_later_hides_until_next_launch_or_hours(packaged, patches, monkeypatch):
    clock = Clock()
    u = make(GitHub(patches["good"]), clock=clock)
    u.check()
    u.later()
    assert u.state()["offer"] is None
    clock.t += autoupdate.LATER - 60
    assert u.state()["offer"] is None
    clock.t += 120
    assert u.state()["offer"]["version"] == NEW              # after some hours
    u.later()
    monkeypatch.setattr(autoupdate, "SESSION", "next-launch")
    assert u.state()["offer"]["version"] == NEW              # on the next launch


def test_skip_suppresses_version_until_manual_check(packaged, patches):
    gh, clock = GitHub(patches["good"]), Clock()
    u = make(gh, clock=clock)
    u.check()
    u.skip(NEW)
    assert u.state()["offer"] is None
    clock.t += autoupdate.INTERVAL + 1
    assert u.tick()["status"] == "suppressed"
    assert u.state()["offer"] is None
    assert u.check(manual=True)["status"] == "staged"
    assert u.state()["offer"]["version"] == NEW and NEW not in autoupdate.load()["skipped"]


def test_rolled_back_version_is_not_offered_again(packaged, patches):
    gh, clock = GitHub(patches["good"]), Clock()
    u = make(gh, clock=clock)
    u.check()
    cmlboot.save_state({"failed": {"version": NEW, "reason": "rolled back by the user"}})
    assert u.state()["offer"] is None and NEW in autoupdate.load()["rolled_back"]
    clock.t += autoupdate.INTERVAL + 1
    n = len(gh.downloads())
    assert u.tick()["status"] == "suppressed" and len(gh.downloads()) == n
    assert u.check(manual=True)["status"] == "staged" and u.state()["offer"]["version"] == NEW


# ---------------------------------------------------------------- Update now (idle gating, install, restart)
def test_update_now_waits_for_running_work_then_installs_and_restarts(packaged, patches):
    busy, restarts = ["a lab build (01-ospf)"], []
    u = make(GitHub(patches["good"]), busy=lambda: list(busy), restarts=restarts)
    u.check()
    assert u.state()["offer"]["busy"] == ["a lab build (01-ospf)"]
    a = u.apply(NEW)
    assert a["state"] == "waiting" and a["waiting_for"] == ["a lab build (01-ospf)"]
    time.sleep(0.2)
    st = u.state()
    assert st["apply"]["state"] == "waiting" and restarts == [] and not (cmlboot.app_root() / NEW).exists()
    busy.clear()
    assert wait_for(lambda: restarts == [1])
    st = autoupdate.load()
    assert st["apply"]["state"] == "restarting" and st["applied"]["version"] == NEW and u.applying()
    b = cmlboot.load_state()
    assert b["current"] == NEW and b["pending"] and cmlboot.next_start().version == NEW


def test_update_now_can_be_cancelled_while_waiting(packaged, patches):
    restarts = []
    u = make(GitHub(patches["good"]), busy=lambda: ["an exam (03-eigrp)"], restarts=restarts)
    u.check()
    u.apply(NEW)
    assert u.cancel() == {"status": "cancelled"}
    time.sleep(0.1)
    assert restarts == [] and u.state()["apply"] is None and u.state()["offer"]["version"] == NEW


def test_update_now_needs_a_staged_patch(packaged):
    with pytest.raises(updates.UpdateError, match="not downloaded"):
        make(GitHub(None)).apply(NEW)


def test_tampered_staged_file_is_not_installed(packaged, patches):
    restarts = []
    u = make(GitHub(patches["good"]), restarts=restarts)
    u.check()
    (autoupdate.staged_dir() / f"cml-lab-builder-patch-{NEW}.zip").write_bytes(b"evil")
    assert u.state()["offer"] is None
    with pytest.raises(updates.UpdateError):
        u.apply(NEW)
    assert restarts == []


def test_after_restart_toast_and_failed_notice(packaged):
    u = make(GitHub(None))
    autoupdate.save({"applied": {"version": __version__, "from": "1.6.0"}})
    assert u.state()["just_updated"] == {"version": __version__, "from": "1.6.0"}
    u.ack()
    assert u.state()["just_updated"] is None
    autoupdate.save({"applied": {"version": NEW, "from": __version__}})
    cmlboot.save_state({"failed": {"version": NEW, "reason": "exited with code 1 before the web UI started"}})
    assert u.state()["failed_update"] == {"version": NEW}
    u.ack()
    assert u.state()["failed_update"] is None


def test_startup_tidies_an_earlier_process(packaged, patches):
    u = make(GitHub(patches["good"]))
    u.check()
    st = autoupdate.load()
    st["apply"] = {"version": NEW, "state": "restarting", "session": "old"}
    autoupdate.save(st)
    assert not u.applying()                                  # another process's state never blocks this one
    assert u.startup() is False and "apply" not in autoupdate.load()
    st = autoupdate.load()
    st["apply"] = {"version": NEW, "state": "waiting", "session": "old"}
    autoupdate.save(st)
    assert u.startup() is True and autoupdate.load()["apply"]["session"] == autoupdate.SESSION
    st = autoupdate.load()
    st["staged"]["version"] = __version__                    # we are now running what was staged
    autoupdate.save(st)
    u.startup()
    assert "staged" not in autoupdate.load()


# ---------------------------------------------------------------- web API
def test_prompt_api_and_idle_gating(packaged, patches):
    restarts = []
    c = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False, update_http=GitHub(patches["good"]),
                              restart=lambda: restarts.append(1)))
    assert c.get("/api/update/auto").json()["offer"] is None
    r = c.post("/api/update/check").json()
    assert r["status"] == "staged" and r["state"]["offer"]["version"] == NEW
    lab_id = sorted(catalog.entries())[0]
    exam.start(catalog.entry(lab_id).lab)                    # an exam on the clock blocks the install
    assert c.get("/api/update/auto").json()["offer"]["busy"] == [f"an exam ({lab_id})"]
    a = c.post(f"/api/update/apply?version={NEW}").json()
    assert a["state"] == "waiting" and a["waiting_for"] == [f"an exam ({lab_id})"]
    time.sleep(0.15)
    assert restarts == [] and c.get("/api/update/auto").json()["apply"]["state"] == "waiting"
    exam.clear(lab_id)
    assert wait_for(lambda: restarts == [1])
    r = c.post(f"/api/labs/{lab_id}/build")                 # no new work while the app is about to restart
    assert r.status_code == 409 and "update" in r.json()["detail"]
    assert c.post(f"/api/labs/{lab_id}/exam/start").status_code == 409


def test_prompt_api_answers(packaged, patches):
    c = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False, update_http=GitHub(patches["good"])))
    c.post("/api/update/check")
    assert c.post("/api/update/later").json()["status"] == "later"
    assert c.get("/api/update/auto").json()["offer"] is None
    assert c.post(f"/api/update/skip?version={NEW}").json()["status"] == "skipped"
    assert c.post("/api/update/check").json()["state"]["offer"]["version"] == NEW   # manual check re-offers
    assert c.post("/api/update/apply?version=1.2.3").status_code == 400
    assert c.post("/api/update/ack").json() == {"status": "ok"}


def test_manual_check_from_source_reports_only():
    gh = lambda url, limit: json.dumps({"tag_name": "v99.0.0", "assets": []}).encode()  # noqa: E731
    c = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False, update_fetch=gh))
    r = c.post("/api/update/check").json()
    assert r["status"] == "source" and r["info"]["update_available"] and r["state"]["enabled"] is False


def test_settings_toggle_wakes_the_updater(packaged, monkeypatch):
    woken = []
    monkeypatch.setattr(autoupdate.Updater, "wake", lambda self: woken.append(1))
    c = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False))
    c.post("/api/settings", json={"check_updates": False})
    assert woken == [1] and c.get("/api/update/auto").json()["enabled"] is False


# ---------------------------------------------------------------- real HTTP against a local fake release
def test_url_rules(monkeypatch):
    assert updates.allowed_url("https://api.github.com/x") and updates.allowed_url("http://127.0.0.1:9/x")
    assert not updates.allowed_url("http://example.com/x") and not updates.allowed_url("file:///etc/passwd")
    monkeypatch.setenv("CMLLAB_UPDATE_URL", "http://example.com/latest")
    assert updates.release_url() == updates.LATEST_URL
    monkeypatch.setenv("CMLLAB_UPDATE_URL", "http://127.0.0.1:8000/repos/x/releases/latest")
    assert updates.release_url().startswith("http://127.0.0.1:8000/")
    assert updates.asset_prefixes() == ("https://github.com/", "http://127.0.0.1:8000/")


def test_http_end_to_end_with_etag(packaged, patches, monkeypatch):
    fake = FakeRelease(NEW, {f"cml-lab-builder-patch-{NEW}.zip": patches["good"]}).start()
    try:
        monkeypatch.setenv("CMLLAB_UPDATE_URL", fake.url)
        clock = Clock()
        u = autoupdate.Updater(settings=lambda: config.Settings(), now=clock)   # the real http_get
        assert u.check()["status"] == "staged"
        clock.t += autoupdate.INTERVAL + 1
        assert u.tick()["cached"]
        latest = [r for r in fake.requests if r[0].endswith("/releases/latest")]
        assert latest[0][1] is None and latest[1][1] and latest[1][2] == 304     # conditional request answered 304
        with pytest.raises(library.LibraryError):
            updates.http_get(fake.base + "/download/nope", 1024)
    finally:
        fake.stop()
