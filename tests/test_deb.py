"""Debian package: install-type detection, the right full-download asset per install type, bundled-vs-patch
precedence across .deb upgrades, and the package itself (layout, control, maintainer scripts, desktop file)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import encorboot
from encorlab import __version__, autoupdate, config, install, updates
from test_autoupdate import GitHub, make, packaged, patches  # noqa: F401  (fixtures)
from test_patching import mkbundle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
import build_deb  # noqa: E402

ASSETS = [{"name": n, "url": f"https://github.com/x/releases/download/v2.0.0/{n}", "size": 1}
          for n in ("ENCORLab-2.0.0-windows-x64.zip", "ENCORLab-2.0.0-linux-x64.tar.gz", "encorlab_2.0.0_amd64.deb",
                    "encorlab-patch-2.0.0.zip", "SHA256SUMS.txt")]


# ---------------------------------------------------------------- install type + asset choice
def test_install_type_detection(tmp_path):
    assert install.install_type() == "source"                       # tests run from the source tree
    (tmp_path / "install-type").write_text("deb\n")
    assert install.install_type(tmp_path) == "deb"
    (tmp_path / "install-type").write_text("nonsense")
    assert install.install_type(tmp_path, "posix") == "linux-tar"
    (tmp_path / "install-type").unlink()
    assert install.install_type(tmp_path, "posix") == "linux-tar" and install.install_type(tmp_path, "nt") == "windows-zip"


@pytest.mark.parametrize("kind,name", [("deb", "encorlab_2.0.0_amd64.deb"), ("linux-tar", "ENCORLab-2.0.0-linux-x64.tar.gz"),
                                       ("windows-zip", "ENCORLab-2.0.0-windows-x64.zip")])
def test_full_download_picks_the_asset_for_the_install_type(kind, name):
    d = install.full_download(ASSETS, "2.0.0", kind)
    assert d["name"] == name and d["url"].endswith(name) and d["kind"] == kind
    assert install.full_download([a for a in ASSETS if a["name"] != name], "2.0.0", kind) is None
    assert install.full_download(ASSETS, "2.0.0", "source") is None
    assert "sudo apt install ./encorlab_2.0.0_amd64.deb" in install.how_to_install("deb", "encorlab_2.0.0_amd64.deb")


def test_check_reports_the_download_for_this_install(monkeypatch):
    monkeypatch.setattr(install, "install_type", lambda *a, **k: "deb")
    rel = json.dumps({"tag_name": "v2.0.0", "assets": [{"name": a["name"], "size": 1,
                      "browser_download_url": f"https://github.com/{updates.REPO}/releases/download/v2.0.0/{a['name']}"}
                     for a in ASSETS]}).encode()
    r = updates.check("1.8.0", fetch=lambda u, n: rel)
    assert r["install_type"] == "deb" and r["download"]["name"] == "encorlab_2.0.0_amd64.deb"


def test_deb_banner_points_to_the_new_deb(packaged, patches, monkeypatch):  # noqa: F811
    monkeypatch.setattr(install, "install_type", lambda *a, **k: "deb")

    class DebRelease(GitHub):
        def release(self):
            d = json.loads(super().release())
            d["assets"].append({"name": f"encorlab_{self.version}_amd64.deb", "size": 27_000_000,
                                "browser_download_url": self.BASE + f"encorlab_{self.version}_amd64.deb"})
            return json.dumps(d).encode()
    u = make(DebRelease(patches["newer_runtime"]))
    assert u.check()["status"] == "full_download"
    fd = u.state()["full_download"]
    assert fd["install_type"] == "deb" and fd["asset"] == "encorlab_9.9.9_amd64.deb" and fd["url"].endswith("_amd64.deb")
    assert "sudo apt install ./encorlab_9.9.9_amd64.deb" in fd["how"] and fd["page"].endswith("/v9.9.9")
    monkeypatch.setattr(install, "install_type", lambda *a, **k: "windows-zip")
    u.check(manual=True)
    assert u.state()["full_download"]["asset"] == "ENCORLab-9.9.9-windows-x64.zip"


def test_status_reports_install_type():
    st = updates.status()
    assert st["install_type"] == "source" and st["app_dir"] == ""


# ---------------------------------------------------------------- precedence across .deb upgrades
@pytest.fixture
def deb_boot(tmp_path, monkeypatch):
    """/opt/encorlab/_internal/appcode is the bundled copy; `apt install ./newer.deb` replaces it in place."""
    bundled = tmp_path / "opt" / "encorlab" / "_internal" / "appcode"
    monkeypatch.setattr(encorboot, "frozen", lambda: True)
    monkeypatch.setattr(encorboot, "bundled_dir", lambda: bundled)
    before = list(sys.path)
    yield bundled
    encorboot.purge("fakeapp")
    sys.path[:] = before


def apt_install(bundled: Path, version: str) -> None:
    shutil.rmtree(bundled, ignore_errors=True)
    mkbundle(bundled, version)


def start():
    encorboot.purge("fakeapp")
    encorboot.ACTIVE = None
    return encorboot.activate(gui=False, package="fakeapp")


def test_user_patch_wins_until_a_newer_deb_arrives(deb_boot):
    apt_install(deb_boot, "1.8.0")
    assert start().version == "1.8.0"
    mkbundle(encorboot.app_root() / "1.8.5", "1.8.5")                 # patch installed by the user, no root
    encorboot.stage("1.8.5", "fakeapp")
    assert (start().source, start().version) == ("installed", "1.8.5")
    apt_install(deb_boot, "1.8.1")                                    # older deb upgrade: the newer patch still wins
    assert (start().source, start().version) == ("installed", "1.8.5")
    apt_install(deb_boot, "1.9.0")                                    # newer deb: its bundled copy wins
    assert (start().source, start().version) == ("bundled", "1.9.0")
    assert (encorboot.app_root() / "1.8.5").is_dir()                  # nothing in the user folder was touched


def test_deb_needing_newer_runtime_patch_is_ignored(deb_boot):
    apt_install(deb_boot, "1.8.0")
    mkbundle(encorboot.app_root() / "1.9.9", "1.9.9", min_runtime=encorboot.RUNTIME_VERSION + 1)
    encorboot.save_state({"current": "1.9.9"})
    assert start().version == "1.8.0"


def test_staged_patch_older_than_new_bundled_is_dropped(packaged, patches, monkeypatch):  # noqa: F811
    u = make(GitHub(patches["good"]))
    u.check()
    assert autoupdate.load()["staged"]["version"] == "9.9.9"
    monkeypatch.setattr(autoupdate, "__version__", "10.0.0")           # a newer .deb is now running
    monkeypatch.setattr(autoupdate, "_newer", lambda v, than="10.0.0": updates.parse_version(v or "") > (10, 0, 0))
    u.startup()
    assert "staged" not in autoupdate.load() and not list(autoupdate.staged_dir().glob("*.zip"))


# ---------------------------------------------------------------- the package itself
def fake_stage(tmp: Path, version: str = "1.8.0") -> Path:
    s = tmp / f"ENCORLab-{version}-linux-x64"
    (s / "_internal").mkdir(parents=True)
    (s / "ENCORLab").write_text("#!/bin/sh\necho fake\n")
    (s / "README.md").write_text("readme\n")
    (s / "install-desktop-entry.sh").write_text("#!/bin/sh\n")
    mkbundle(s / "_internal" / "appcode", version, pkg="encorlab")
    return s


def deb_contents(deb: Path) -> dict[str, str]:
    out = subprocess.run(["dpkg-deb", "-c", str(deb)], capture_output=True, text=True, check=True).stdout
    files = {}
    for line in out.splitlines():
        parts = line.split()
        files[parts[5].lstrip(".")] = parts[0]
    return files


def deb_file(deb: Path, path: str) -> str:
    tar = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(deb)], capture_output=True, check=True).stdout
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        return t.extractfile("." + path).read().decode()


needs_dpkg = pytest.mark.skipif(not shutil.which("dpkg-deb"), reason="dpkg-deb not installed")


@needs_dpkg
def test_build_deb_layout_and_metadata(tmp_path):
    deb = build_deb.build(fake_stage(tmp_path), tmp_path / "out")
    assert deb.name == "encorlab_1.8.0_amd64.deb"
    info = subprocess.run(["dpkg-deb", "-f", str(deb)], capture_output=True, text=True, check=True).stdout
    for want in ("Package: encorlab", "Version: 1.8.0", "Architecture: amd64", "Depends: libc6 (>= 2.28)",
                 "Recommends: xdg-utils", "Maintainer: ", "Homepage: https://github.com/Specops13/cml-lab-builder",
                 "Description: build and grade practice labs in Cisco Modeling Labs"):
        assert want in info, want
    files = deb_contents(deb)
    assert files["/opt/encorlab/ENCORLab"].startswith("-rwxr-xr-x") and files["/usr/bin/encorlab"].startswith("-rwxr-xr-x")
    assert files["/opt/encorlab/README.md"].startswith("-rw-r--r--")
    listing = subprocess.run(["dpkg-deb", "-c", str(deb)], capture_output=True, text=True, check=True).stdout
    assert files["/usr/bin/cmllab"].startswith("l") and "./usr/bin/cmllab -> encorlab\n" in listing   # 2.1.0 command name
    assert "./usr/share/man/man1/cmllab.1.gz -> encorlab.1.gz\n" in listing
    assert "/opt/encorlab/install-desktop-entry.sh" not in files            # the tar.gz-only helper
    for p in ("/opt/encorlab/install-type", "/usr/share/applications/encorlab.desktop", "/usr/share/man/man1/encorlab.1.gz",
              "/usr/share/doc/encorlab/copyright", "/usr/share/doc/encorlab/changelog.gz",
              "/usr/share/icons/hicolor/48x48/apps/encorlab.png", "/usr/share/icons/hicolor/256x256/apps/encorlab.png"):
        assert p in files, p
    assert deb_file(deb, "/opt/encorlab/install-type").strip() == "deb"
    assert "exec /opt/encorlab/ENCORLab" in deb_file(deb, "/usr/bin/encorlab")
    desk = deb_file(deb, "/usr/share/applications/encorlab.desktop")
    assert "Exec=encorlab\n" in desk and "Icon=encorlab\n" in desk and "Terminal=true" in desk
    if shutil.which("desktop-file-validate"):
        f = tmp_path / "encorlab.desktop"
        f.write_text(desk)
        r = subprocess.run(["desktop-file-validate", str(f)], capture_output=True, text=True)
        assert r.returncode == 0 and "error" not in r.stdout.lower(), r.stdout


@needs_dpkg
def test_maintainer_scripts_never_touch_user_data(tmp_path):
    deb = build_deb.build(fake_stage(tmp_path), tmp_path / "out")
    ctl = tmp_path / "ctl"
    subprocess.run(["dpkg-deb", "-e", str(deb), str(ctl)], check=True)
    for name in ("postinst", "prerm", "postrm"):
        text = (ctl / name).read_text()
        assert (ctl / name).stat().st_mode & 0o111 and text.startswith("#!/bin/sh\nset -e")
        assert "$HOME" not in text and "/home" not in text and "rm -rf ~" not in text
        code_lines = [l for l in text.splitlines() if not l.strip().startswith(("#", "echo"))]
        assert not any(".config" in l for l in code_lines), name
    assert "update-desktop-database" in (ctl / "postinst").read_text() and "gtk-update-icon-cache" in (ctl / "postrm").read_text()
    assert "is kept" in (ctl / "postrm").read_text()
    for name in ("postinst", "prerm", "postrm"):
        assert subprocess.run(["sh", "-n", str(ctl / name)]).returncode == 0


@needs_dpkg
def test_build_deb_from_tar_and_with_other_app_code(tmp_path):
    import tarfile
    stage = fake_stage(tmp_path / "s")
    tar = tmp_path / "ENCORLab-1.8.0-linux-x64.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(stage, arcname=stage.name)
    unpacked = build_deb.unpack_tar(tar, tmp_path / "u")
    src = tmp_path / "src"
    shutil.copytree(ROOT / "encorlab", src / "encorlab", ignore=shutil.ignore_patterns("__pycache__"))
    init = src / "encorlab" / "__init__.py"
    init.write_text(init.read_text().replace(f'"{__version__}"', '"1.8.1"'))
    deb = build_deb.build(unpacked, tmp_path / "out", "1.8.1", app_src=src)
    m = json.loads(deb_file(deb, "/opt/encorlab/_internal/appcode/manifest.json"))
    assert deb.name == "encorlab_1.8.1_amd64.deb" and m["app_version"] == "1.8.1" and "encorlab/autoupdate.py" in m["files"]


@needs_dpkg
def test_deb_license_files_and_dep5_copyright(tmp_path):
    s = fake_stage(tmp_path)
    (s / "LICENSE.txt").write_text((build_deb.ROOT / "LICENSE").read_text())
    (s / "THIRD-PARTY-NOTICES.txt").write_text("THIRD-PARTY NOTICES\n paramiko LGPL-2.1\n")
    (s / "_internal" / "click-8.5.0.dist-info" / "licenses").mkdir(parents=True)     # same names deeper: kept in /opt
    (s / "_internal" / "click-8.5.0.dist-info" / "licenses" / "LICENSE.txt").write_text("BSD\n")
    deb = build_deb.build(s, tmp_path / "out")
    files = deb_contents(deb)
    assert "/usr/share/doc/encorlab/LICENSE.txt" in files and "/usr/share/doc/encorlab/THIRD-PARTY-NOTICES.txt" in files
    assert "/opt/encorlab/LICENSE.txt" not in files and "/opt/encorlab/THIRD-PARTY-NOTICES.txt" not in files
    assert "/opt/encorlab/_internal/click-8.5.0.dist-info/licenses/LICENSE.txt" in files
    assert "MIT License" in deb_file(deb, "/usr/share/doc/encorlab/LICENSE.txt")
    cr = deb_file(deb, "/usr/share/doc/encorlab/copyright")
    assert cr.startswith("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n")
    assert "Copyright: 2026 Dylan Vaughan (Specops13)\nLicense: MIT\n" in cr and "\nLicense: MIT\n Permission is hereby" in cr
    assert "THIRD-PARTY-NOTICES.txt" in cr and "all rights" not in cr.lower()
    for para in cr.split("\n\n"):                  # DEP-5: continuation lines start with a space, "." for blank lines
        for line in para.splitlines()[1:]:
            assert line.startswith((" ", "Files:", "Copyright:", "License:", "Upstream", "Source:")), line
