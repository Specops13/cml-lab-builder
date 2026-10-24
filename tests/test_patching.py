"""Patchable updates: boot loader (bundle choice, rollback, runtime gating), patch build/verification, install flow."""
import hashlib
import io
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import cmlboot
import fakes
from cmllab import __version__, config, library, updates
from cmllab.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
import build_patch  # noqa: E402

PKG = "fakeapp"
RT = cmlboot.RUNTIME_VERSION


def mkbundle(d: Path, version: str, min_runtime: int = 1, broken: bool = False, pkg: str = PKG) -> Path:
    (d / pkg).mkdir(parents=True, exist_ok=True)
    (d / pkg / "__init__.py").write_text(f'__version__ = "{version}"\n' + ('raise RuntimeError("boom")\n' if broken else ""),
                                         encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps(cmlboot.build_manifest(d, version, min_runtime, package=pkg)),
                                     encoding="utf-8")
    return d


@pytest.fixture
def boot(tmp_path, monkeypatch):
    bundled = mkbundle(tmp_path / "bundled", "1.6.0")
    monkeypatch.setattr(cmlboot, "frozen", lambda: True)
    monkeypatch.setattr(cmlboot, "bundled_dir", lambda: bundled)
    monkeypatch.setattr(cmlboot, "ACTIVE", None)
    before = list(sys.path)
    yield bundled
    cmlboot.purge(PKG)
    sys.path[:] = before


def install_dir(version, **kw) -> Path:
    return mkbundle(cmlboot.app_root() / version, version, **kw)


def fresh_start(gui=True):
    """What a new process does: forget the loaded app code, then run the boot loader."""
    cmlboot.purge(PKG)
    sys.path[:] = [p for p in sys.path if "bundled" not in p and "/app/" not in p.replace("\\", "/")]
    cmlboot.ACTIVE = None
    return cmlboot.activate(gui=gui, package=PKG)


# ---------------------------------------------------------------- boot loader
def test_bundled_copy_is_used_without_patches(boot):
    c = fresh_start()
    assert (c.source, c.version) == ("bundled", "1.6.0") and sys.modules[PKG].__version__ == "1.6.0"


def test_installed_patch_is_used_then_confirmed(boot):
    install_dir("1.6.1")
    cmlboot.stage("1.6.1", PKG)
    c = fresh_start()
    assert (c.source, c.version) == ("installed", "1.6.1") and sys.modules[PKG].__version__ == "1.6.1"
    st = cmlboot.load_state()
    assert st["pending"] and st["boot_attempts"] == 1 and cmlboot.pending_active()
    cmlboot.mark_good()
    st = cmlboot.load_state()
    assert not st["pending"] and st["boot_attempts"] == 0 and not cmlboot.pending_active()
    assert fresh_start().version == "1.6.1"          # confirmed patches stay in use


def test_patch_that_never_reached_the_ui_is_rolled_back(boot):
    install_dir("1.6.1")
    cmlboot.stage("1.6.1", PKG)
    assert fresh_start().version == "1.6.1"          # first GUI start: attempt 1, then the process dies
    c = fresh_start()                                # next start: still pending -> roll back
    assert (c.source, c.version) == ("bundled", "1.6.0")
    st = cmlboot.load_state()
    assert st["failed"]["version"] == "1.6.1" and st["current"] is None and not st["pending"]


def test_cli_starts_do_not_count_as_attempts(boot):
    install_dir("1.6.1")
    cmlboot.stage("1.6.1", PKG)
    for _ in range(3):
        assert fresh_start(gui=False).version == "1.6.1"
    assert cmlboot.load_state()["boot_attempts"] == 0


def test_patch_that_fails_to_import_falls_back(boot):
    install_dir("1.6.1", broken=True)
    cmlboot.stage("1.6.1", PKG)
    c = fresh_start(gui=False)
    assert (c.source, c.version) == ("bundled", "1.6.0") and sys.modules[PKG].__version__ == "1.6.0"
    st = cmlboot.load_state()
    assert "import failed" in st["failed"]["reason"] and st["current"] is None


def test_failed_start_rolls_back_to_previous_patch(boot):
    install_dir("1.6.1")
    cmlboot.stage("1.6.1", PKG)
    fresh_start()
    cmlboot.mark_good()
    install_dir("1.6.2")
    cmlboot.stage("1.6.2", PKG)                    # running 1.6.1 becomes the fallback
    assert cmlboot.load_state()["previous"] == "1.6.1"
    assert fresh_start().version == "1.6.2"
    assert cmlboot.fail_active("exited with code 1 before the web UI started", PKG) is True
    assert PKG not in sys.modules
    c = cmlboot.activate(gui=True, package=PKG)
    assert (c.source, c.version) == ("installed", "1.6.1")
    assert cmlboot.load_state()["failed"]["version"] == "1.6.2"


def test_bundled_copy_wins_when_newer(boot):
    install_dir("1.5.9")
    st = cmlboot.load_state()
    st.update(current="1.5.9")
    cmlboot.save_state(st)
    assert fresh_start().source == "bundled"         # e.g. after a full download of a newer release


def test_loader_ignores_patches_for_a_newer_runtime(boot):
    install_dir("1.7.0", min_runtime=cmlboot.RUNTIME_VERSION + 1)
    cmlboot.save_state({"current": "1.7.0"})
    assert cmlboot.candidate_at(cmlboot.app_root() / "1.7.0", "installed", PKG) is None
    assert fresh_start().version == "1.6.0"
    with pytest.raises(ValueError):
        cmlboot.stage("1.7.0", PKG)


def test_manual_rollback_and_pruning(boot):
    for v in ("1.6.1", "1.6.2", "1.6.3"):
        install_dir(v)
        cmlboot.stage(v, PKG)
        fresh_start()
        cmlboot.mark_good()
    st = cmlboot.load_state()
    assert (st["current"], st["previous"]) == ("1.6.3", "1.6.2")
    assert sorted(d.name for d in cmlboot.app_root().iterdir() if d.is_dir()) == ["1.6.2", "1.6.3"]
    r = cmlboot.rollback(PKG)
    assert r["next"]["version"] == "1.6.2"
    assert fresh_start().version == "1.6.2"
    cmlboot.rollback(PKG)
    assert fresh_start().version == "1.6.0"
    with pytest.raises(ValueError):
        cmlboot.rollback(PKG)


def test_is_gui():
    assert cmlboot.is_gui([]) and cmlboot.is_gui(["--no-browser", "--port", "9000"]) and cmlboot.is_gui(["--restarted"])
    assert not cmlboot.is_gui(["version"]) and not cmlboot.is_gui(["--help"]) and not cmlboot.is_gui(["--port=1", "list"])


def test_data_dir_matches_the_app(monkeypatch):
    from cmllab import history
    assert cmlboot.data_dir() == history.data_dir()
    monkeypatch.delenv("CMLLAB_DATA_DIR")
    assert cmlboot.data_dir() == history.data_dir() == config.settings_file().parent


# ---------------------------------------------------------------- patch build + verification
def make_src(tmp: Path, version: str) -> Path:
    src = tmp / f"src-{version}"
    shutil.copytree(ROOT / "cmllab", src / "cmllab", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    init = src / "cmllab" / "__init__.py"
    init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', init.read_text(encoding="utf-8")),
                    encoding="utf-8")
    return src


def rezip(data: bytes, edit) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(data))
    entries = {n: zin.read(n) for n in zin.namelist()}
    edit(entries)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in entries.items():
            z.writestr(n, b)
    return buf.getvalue()


def test_patch_is_deterministic_and_complete(tmp_path):
    a = build_patch.build_patch(ROOT, tmp_path / "a").read_bytes()
    b = build_patch.build_patch(ROOT, tmp_path / "b").read_bytes()
    assert a == b and len(a) < 2_000_000
    names = zipfile.ZipFile(io.BytesIO(a)).namelist()
    assert names[0] == "manifest.json" and not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    assert {"cmllab/__init__.py", "cmllab/web/static/app.js", "cmllab/migrate.py"} <= set(names)
    assert not any(n.startswith("cmllab/labs/") for n in names)    # labs come from the online library (2.0.0)
    m = updates.verify_patch(a, __version__, cmlboot.RUNTIME_VERSION)
    assert m["app_version"] == __version__ and m["min_runtime"] == cmlboot.RUNTIME_VERSION
    assert set(m["files"]) == set(names) - {"manifest.json"}


def test_runtime_lock_is_current():
    assert build_patch.lock_problem() is None


@pytest.fixture
def patch_bytes(tmp_path):
    return build_patch.build_patch(make_src(tmp_path, "9.9.9"), tmp_path / "out").read_bytes()


@pytest.mark.parametrize("edit,msg", [
    (lambda e: e.__setitem__("cmllab/cli.py", e["cmllab/cli.py"] + b"\n# tampered"), "checksum mismatch"),
    (lambda e: e.__setitem__("cmllab/extra.py", b"x = 1"), "do not match its manifest"),
    (lambda e: e.__setitem__("../evil.py", b"x = 1"), "outside cmllab"),
    (lambda e: e.__setitem__("cmllab/../../evil.py", b"x = 1"), "outside cmllab"),
    (lambda e: e.pop("manifest.json"), "no manifest"),
    (lambda e: e.__setitem__("manifest.json", b"{nope"), "not valid JSON"),
])
def test_verify_rejects_bad_patches(patch_bytes, edit, msg):
    with pytest.raises(updates.UpdateError, match=msg):
        updates.verify_patch(rezip(patch_bytes, edit), "9.9.9", RT)


def test_verify_rejects_non_zip():
    with pytest.raises(updates.UpdateError):
        updates.verify_patch(b"not a zip", "9.9.9", RT)


def test_verify_checks_version_and_runtime(patch_bytes, tmp_path):
    assert updates.verify_patch(patch_bytes, "9.9.9", RT)["app_version"] == "9.9.9"
    with pytest.raises(updates.UpdateError, match="expected 9.9.8"):
        updates.verify_patch(patch_bytes, "9.9.8", RT)
    newer = build_patch.build_patch(make_src(tmp_path, "9.9.7"), tmp_path / "n", min_runtime=RT + 1).read_bytes()
    with pytest.raises(updates.RuntimeTooOld) as e:
        updates.verify_patch(newer, "9.9.7", RT)
    assert (e.value.needed, e.value.have) == (RT + 1, RT)

    def lie(e):   # manifest says 9.9.9 but the code declares another version
        e["cmllab/__init__.py"] = e["cmllab/__init__.py"].replace(b'"9.9.9"', b'"1.0.0"')
        m = json.loads(e["manifest.json"])
        m["files"]["cmllab/__init__.py"] = hashlib.sha256(e["cmllab/__init__.py"]).hexdigest()
        e["manifest.json"] = json.dumps(m).encode()
    with pytest.raises(updates.UpdateError, match="does not declare version"):
        updates.verify_patch(rezip(patch_bytes, lie), "9.9.9", RT)


# ---------------------------------------------------------------- install flow against a fake GitHub release
def fake_github(patch: bytes | None, sums_text: str | None, tag="v9.9.9", sig=None):
    base = f"https://github.com/{updates.REPO}/releases/download/{tag}/"
    assets = [{"name": "CMLLabBuilder-9.9.9-windows-x64.zip", "size": 40_000_000,
               "browser_download_url": base + "CMLLabBuilder-9.9.9-windows-x64.zip"}]
    files = {}
    if patch is not None:
        assets.append({"name": "cml-lab-builder-patch-9.9.9.zip", "size": len(patch),
                       "browser_download_url": base + "cml-lab-builder-patch-9.9.9.zip"})
        files[base + "cml-lab-builder-patch-9.9.9.zip"] = patch
    if sums_text is not None:
        assets.append({"name": "SHA256SUMS.txt", "size": len(sums_text), "browser_download_url": base + "SHA256SUMS.txt"})
        files[base + "SHA256SUMS.txt"] = sums_text.encode()
        if sig is not False:
            assets.append({"name": "SHA256SUMS.txt.sig", "size": 200, "browser_download_url": base + "SHA256SUMS.txt.sig"})
            files[base + "SHA256SUMS.txt.sig"] = sig if sig is not None else fakes.sign(sums_text.encode())
    rel = json.dumps({"tag_name": tag, "html_url": f"https://github.com/{updates.REPO}/releases/tag/{tag}",
                      "assets": assets}).encode()
    calls = []

    def fetch(url, limit):
        calls.append(url)
        return rel if url == updates.LATEST_URL else files[url]
    fetch.calls = calls
    return fetch


@pytest.fixture
def packaged(boot, monkeypatch):
    """Pretend we run in the packaged app on the bundled 1.6.0 code."""
    (boot / "cmllab").mkdir()
    (boot / "cmllab" / "__init__.py").write_text('__version__ = "1.6.0"\n', encoding="utf-8")
    monkeypatch.setattr(cmlboot, "ACTIVE", cmlboot.Candidate("bundled", "1.6.0", boot))
    return boot


def test_install_from_release(packaged, patch_bytes):
    f = fake_github(patch_bytes, f"{library.sha256(patch_bytes)}  cml-lab-builder-patch-9.9.9.zip\nabc  other\n")
    r = updates.install("1.6.0", fetch=f)
    assert r["status"] == "installed" and r["version"] == "9.9.9" and r["restart_required"] and r["size"] == len(patch_bytes)
    d = cmlboot.app_root() / "9.9.9"
    assert (d / "cmllab" / "__init__.py").is_file() and (d / "manifest.json").is_file()
    st = cmlboot.load_state()
    assert st["current"] == "9.9.9" and st["pending"] and st["previous"] is None
    assert cmlboot.next_start().version == "9.9.9"
    s = updates.status()
    assert s["patchable"] and s["installed"] == "9.9.9" and s["restart_needed"] and s["can_rollback"]
    assert f.calls[0] == updates.LATEST_URL and f.calls[-1].endswith("cml-lab-builder-patch-9.9.9.zip")


def test_install_refuses_checksum_mismatch(packaged, patch_bytes):
    f = fake_github(patch_bytes, "0" * 64 + "  cml-lab-builder-patch-9.9.9.zip\n")
    with pytest.raises(updates.UpdateError, match="checksum mismatch"):
        updates.install("1.6.0", fetch=f)
    assert not (cmlboot.app_root() / "9.9.9").exists() and not cmlboot.load_state().get("current")


def test_install_needs_sums_entry(packaged, patch_bytes):
    with pytest.raises(updates.UpdateError, match="no SHA256SUMS"):
        updates.install("1.6.0", fetch=fake_github(patch_bytes, None))
    with pytest.raises(updates.UpdateError, match="no entry"):
        updates.install("1.6.0", fetch=fake_github(patch_bytes, "abc  x\n"))


def test_install_without_patch_or_with_newer_runtime_means_full_download(packaged, tmp_path):
    r = updates.install("1.6.0", fetch=fake_github(None, ""))
    assert r["status"] == "full_download" and "no app patch" in r["reason"]
    newer = build_patch.build_patch(make_src(tmp_path, "9.9.9"), tmp_path / "n",
                                    min_runtime=cmlboot.RUNTIME_VERSION + 1).read_bytes()
    r = updates.install("1.6.0", fetch=fake_github(newer, f"{library.sha256(newer)}  cml-lab-builder-patch-9.9.9.zip\n"))
    assert r["status"] == "full_download" and r["needed_runtime"] == cmlboot.RUNTIME_VERSION + 1
    assert not (cmlboot.app_root() / "9.9.9").exists()


def test_install_up_to_date(packaged, patch_bytes):
    assert updates.install("9.9.9", fetch=fake_github(patch_bytes, ""))["status"] == "up_to_date"


def test_install_file_and_rollback(packaged, tmp_path, patch_bytes):
    p = tmp_path / "cml-lab-builder-patch-9.9.9.zip"
    p.write_bytes(patch_bytes)
    with pytest.raises(updates.UpdateError, match="not signed"):
        updates.install_file(p)
    (tmp_path / "cml-lab-builder-patch-9.9.9.zip.sig").write_bytes(fakes.sign(patch_bytes))
    with pytest.raises(updates.UpdateError, match="checksum mismatch"):
        updates.install_file(p, "0" * 64)
    assert updates.install_file(p)["version"] == "9.9.9"
    r = updates.rollback()
    assert r["status"] == "rolled_back" and r["next"]["source"] == "bundled"
    with pytest.raises(updates.UpdateError, match="no installed update"):
        updates.rollback()


def test_not_patchable_from_source():
    ok, why = updates.patchable()
    assert not ok and "source" in why
    with pytest.raises(updates.UpdateError, match="not available"):
        updates.install("1.0.0", fetch=lambda u, l: b"")


def test_web_endpoints_from_source():
    c = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False))
    st = c.get("/api/update/status").json()
    assert st["version"] == __version__ and st["patchable"] is False and st["runtime"] == cmlboot.RUNTIME_VERSION
    r = c.post("/api/update/install")
    assert r.status_code == 400 and "not available" in r.json()["error"]
    assert c.post("/api/update/rollback").status_code == 400
    r = c.post("/api/update/restart")
    assert r.status_code == 400 and "packaged app" in r.json()["error"]


def test_web_install_and_status_packaged(packaged, patch_bytes):
    f = fake_github(patch_bytes, f"{library.sha256(patch_bytes)}  cml-lab-builder-patch-9.9.9.zip\n")
    c = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False, update_fetch=f))
    r = c.post("/api/update/install").json()
    assert r["status"] == "installed" and r["version"] == "9.9.9"
    st = c.get("/api/update/status").json()
    assert st["installed"] == "9.9.9" and st["active"] == {"version": "1.6.0", "source": "bundled"} and st["restart_needed"]
    assert c.post("/api/update/rollback").json()["next"]["version"] == "1.6.0"
