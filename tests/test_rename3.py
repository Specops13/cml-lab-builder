"""3.0.0 full rename: package cmllab, runtime 2, new program/asset names, CML- lab titles (ENCOR- labs still work),
CMLLAB_* env vars (ENCOR_* still read), data + app updates in cml-lab-builder, transition assets for 1.7 - 2.1."""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import cmlboot
from cmllab import __version__, catalog, config, install, paths, render, updates
from cmllab.cml import CML, CMLError, LEGACY_PREFIXES
from fakes import FakeClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
import build_compat  # noqa: E402

LAB = catalog.get("eigrp-basic")


def test_runtime_2_and_package_name():
    assert cmlboot.RUNTIME_VERSION == 2 and cmlboot.PACKAGE == "cmllab"
    assert not (ROOT / "encorlab").exists() and (ROOT / "cmllab" / "__init__.py").is_file()
    assert updates.PATCH_PREFIX == "cml-lab-builder-patch-"
    lock = json.loads((ROOT / "packaging" / "runtime.lock.json").read_text())
    assert lock["runtime_version"] == 2


def test_boot_loader_data_dir_is_the_new_folder(tmp_path):
    assert cmlboot.data_dir({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "cml-lab-builder"
    assert cmlboot.data_dir({"CMLLAB_DATA_DIR": str(tmp_path / "a"), "ENCOR_DATA_DIR": str(tmp_path / "b")}) == tmp_path / "a"
    assert cmlboot.data_dir({"ENCOR_DATA_DIR": str(tmp_path / "b")}) == tmp_path / "b"
    assert cmlboot.data_dir({"CMLLAB_SETTINGS_FILE": str(tmp_path / "s" / "settings.json")}) == tmp_path / "s"
    if os.name != "nt":
        assert cmlboot.data_dir({"HOME": str(tmp_path)}) == Path.home() / ".config" / "cml-lab-builder"


def test_app_updates_live_in_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CMLLAB_DATA_DIR", str(tmp_path / "d"))
    assert paths.boot_dir() == paths.data_dir() == tmp_path / "d"


def test_old_env_names_are_copied_to_the_new_ones():
    env = dict(os.environ, ENCOR_LAB_PREFIX="OLD-", ENCOR_NODE_LIMIT="7", CMLLAB_NODE_LIMIT="9")
    code = "import os, cmllab; print(os.environ['CMLLAB_LAB_PREFIX'], os.environ['CMLLAB_NODE_LIMIT'])"
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=ROOT, check=True)
    assert out.stdout.split() == ["OLD-", "9"]                       # the new name wins when both are set


def test_new_identity_strings():
    assert config.Settings().lab_prefix == "CML-" and render.TAG == "cml-lab-builder"
    assert render.lab_title(LAB, "CML-") == "CML-eigrp-basic"
    assert config.KEYRING_SERVICE == "cml-lab-builder"
    assert install.asset_name("deb", "3.0.0") == "cml-lab-builder_3.0.0_amd64.deb"
    assert install.asset_name("linux-tar", "3.0.0") == "CMLLabBuilder-3.0.0-linux-x64.tar.gz"
    assert install.asset_name("windows-zip", "3.0.0") == "CMLLabBuilder-3.0.0-windows-x64.zip"
    assert "CMLLabBuilder.exe" in install.how_to_install("windows-zip", None)
    assert "./cml-lab-builder" in install.how_to_install("linux-tar", None)
    assert "sudo apt install ./cml-lab-builder_<version>_amd64.deb" in install.how_to_install("deb", None)


def _cml(settings, client):
    return CML(settings, client_factory=lambda s: client, sleep=lambda s: None)


def _legacy_lab(c):
    from cmllab.render import to_yaml
    from cmllab import platforms
    return c.import_lab(to_yaml(LAB, platforms.get("iol"), "ENCOR-"), title="ENCOR-eigrp-basic")


def test_labs_built_by_2x_are_found_checked_and_destroyed(settings):
    assert "ENCOR-" in LEGACY_PREFIXES
    c = FakeClient()
    old = _legacy_lab(c)
    m = _cml(settings, c)
    assert m.find(LAB) is old                                        # status / check / console use the running lab
    st = m.status(LAB)
    assert st.exists and st.title == "ENCOR-eigrp-basic"
    assert m.build(LAB) is old and len(c.all_labs()) == 1             # no second copy next to it
    m.reset(LAB)
    assert m.destroy(LAB) and old.removed and m.find(LAB) is None


def test_new_title_wins_and_foreign_labs_are_never_deleted(settings):
    c = FakeClient()
    _legacy_lab(c)
    new = _cml(settings, c).build(LAB, rebuild=True)                 # rebuild replaces the old lab with CML-<id>
    assert new.title == "CML-eigrp-basic" and [l.title for l in c.all_labs()] == ["CML-eigrp-basic"]
    foreign = c.add_foreign_running_lab(1, title="Prod lab")
    with pytest.raises(CMLError, match="not created by CML Lab Builder"):
        _cml(settings, c)._destroy(foreign)


def test_consoles_use_the_real_title_of_a_legacy_lab(settings):
    from cmllab import service
    c = FakeClient()
    _legacy_lab(c)
    st = service.do_status(settings, LAB.id, client_factory=lambda s: c)
    assert st["cml_title"] == "ENCOR-eigrp-basic" and all("/ENCOR-eigrp-basic/" in x["path"] for x in st["consoles"])


def test_compat_patch_makes_old_apps_offer_the_full_download(tmp_path):
    data = build_compat.old_patch_bytes("3.0.0", 2)
    m = json.loads(zipfile.ZipFile(__import__("io").BytesIO(data)).read("manifest.json"))
    assert m["package"] == "encorlab" and m["min_runtime"] == 2 and m["files"] == {} and m["format"] == 1
    # the 1.7 - 2.1 updater code is the same as today's verify_patch with package="encorlab", runtime 1
    with pytest.raises(updates.RuntimeTooOld) as e:
        updates.verify_patch(data, "3.0.0", 1, package="encorlab")
    assert (e.value.needed, e.value.have) == (2, 1)
    with pytest.raises(SystemExit):
        build_compat.old_patch_bytes("3.0.0", 1)                   # would be installable by an old app
    assert build_compat.old_patch_bytes("3.0.0", 2) == data          # reproducible


def test_compat_copies_are_identical(tmp_path):
    for new in build_compat.copies("3.0.0"):
        (tmp_path / new).write_bytes(new.encode() * 3)
    out = {p.name for p in build_compat.build(tmp_path, "3.0.0")}
    assert out == {"encorlab-patch-3.0.0.zip", "ENCORLab-3.0.0-windows-x64.zip", "ENCORLab-3.0.0-linux-x64.tar.gz",
                   "encorlab_3.0.0_amd64.deb"}
    for new, old in build_compat.copies("3.0.0").items():
        assert (tmp_path / old).read_bytes() == (tmp_path / new).read_bytes()
    (tmp_path / "x").mkdir()
    with pytest.raises(SystemExit):
        build_compat.build(tmp_path / "x", "3.0.0")


def test_new_updater_ignores_the_old_names():
    assets = [{"name": n, "url": f"https://github.com/x/releases/download/v3.0.1/{n}", "size": 1}
              for n in ("ENCORLab-3.0.1-windows-x64.zip", "encorlab_3.0.1_amd64.deb", "encorlab-patch-3.0.1.zip")]
    for kind in ("deb", "windows-zip", "linux-tar"):
        assert install.full_download(assets, "3.0.1", kind) is None


def test_moved_note_from_2_1_is_refreshed(tmp_path, monkeypatch):
    home = tmp_path / "cfg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.setenv("APPDATA", str(home))
    for k in ("CMLLAB_DATA_DIR", "ENCOR_DATA_DIR", "CMLLAB_SETTINGS_FILE", "ENCOR_SETTINGS_FILE"):
        monkeypatch.delenv(k, raising=False)
    old, new = home / "encorlab", home / "cml-lab-builder"
    (old / "app").mkdir(parents=True)
    (old / "settings.json").write_text("{}")
    paths._DONE.clear()
    rec = paths.ensure_moved()
    assert rec["state"] == "moved" and (new / "settings.json").is_file() and not (new / "app").exists()
    (old / "MOVED.txt").write_text("2.1 note: the app folder is still used\n")
    paths._DONE.clear()                                               # a new process
    paths.ensure_moved()
    assert "only holds updates" in (old / "MOVED.txt").read_text()


def test_no_old_names_left_in_the_program():
    """ENCOR stays only as a track/course name and in lab content; old names only where they are read for upgrades."""
    allowed = {"paths.py", "packs.py", "courses.py", "library.py", "migrate.py", "cli.py", "config.py", "__init__.py",
               "cml.py", "render.py", "updates.py", "build_compat.py"}
    hits = []
    for p in list((ROOT / "cmllab").rglob("*.py")) + list((ROOT / "cmllab" / "web").rglob("*.*")):
        if p.suffix in (".png", ".ico", ".woff2"):
            continue
        if "__pycache__" in p.parts or p.name in allowed:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        t = t.replace(".encorlab", "").replace(".encorcourse", "")   # old pack/course extensions are still imported
        for bad in ("encorlab", "ENCORLab", "ENCOR Lab Builder", "ENCOR_"):
            if bad in t:
                hits.append(f"{p.relative_to(ROOT)}: {bad}")
    assert not hits, hits
