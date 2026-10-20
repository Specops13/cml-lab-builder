"""2.0.0: the app ships without labs. First run, installing from the library (starter set, courses, updates),
offline behaviour, and keeping the labs 1.x bundled (migrate.py) without losing any user data."""
import hashlib
import io
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from encorlab import catalog, config, courses, history, library, migrate, packs, snapshots, walkthrough
from encorlab.cli import app as cli_app

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "labs"
LABSRC = ROOT / "labsrc"
INDEX = "http://127.0.0.1:8999/lib/index.json"      # a library served from this computer (http allowed)
BASE = INDEX.rsplit("/", 1)[0] + "/"


@pytest.fixture
def no_labs(tmp_path, monkeypatch):
    """The packaged app: no built-in labs at all."""
    monkeypatch.setattr(catalog, "LABS_DIR", tmp_path / "package-labs-gone")
    return tmp_path


def lib_files() -> dict:
    return {p.name: p.read_bytes() for p in LIB.iterdir()}


def fetcher(files=None, log=None, down=False):
    files = lib_files() if files is None else files

    def f(url, limit):
        if log is not None:
            log.append(url)
        if down:
            raise library.LibraryError("network error fetching %s: ConnectError: [Errno -3] name resolution failed" % url)
        assert url.startswith(BASE), url
        data = files.get(url[len(BASE):])
        if data is None:
            raise library.LibraryError(f"download failed: HTTP 404 for {url}")
        return data
    return f


def client(fetch=None, **kw):
    from encorlab.web.app import create_app
    app = create_app(config.SettingsStore(config.Settings(library_url=INDEX)), persist=False,
                     library_fetch=fetch or fetcher(), **kw)
    return TestClient(app)


def index_json() -> dict:
    return json.loads((LIB / "index.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- what ships
def test_package_ships_no_labs_and_library_has_every_former_builtin():
    assert not (ROOT / "encorlab" / "labs").exists()
    idx = index_json()
    ids = {i["id"] for i in idx["items"] if i["kind"] == "lab"}
    assert set(migrate.LEGACY_IDS) <= ids and set(migrate.LEGACY_IDS) == {d.name for d in catalog.lab_dirs(LABSRC)}
    assert idx["starter"] and set(idx["starter"]) <= ids
    for it in idx["items"]:
        data = (LIB / it["file"]).read_bytes()
        assert library.sha256(data) == it["sha256"] and len(data) == it["size"]
        if it["kind"] == "lab":
            assert it["version"] and it["ram_gb"] and it["size"] < 64 * 1024
    for c in (i for i in idx["items"] if i["kind"] == "course"):
        assert set(c["labs"]) <= ids, c["file"]          # every course lab is installable from the library


def test_every_library_pack_installs_and_validates(no_labs):
    for it in (i for i in index_json()["items"] if i["kind"] == "lab"):
        pk = packs.read_upload(it["file"], (LIB / it["file"]).read_bytes())
        rep = packs.install(pk)
        assert rep.ok, (it["file"], rep.errors)
        assert rep.results and all(r["solution_pct"] == 100 for r in rep.results), it["file"]
    assert {e.source for e in catalog.entries().values()} == {"user"}
    assert len(catalog.entries()) == len([i for i in index_json()["items"] if i["kind"] == "lab"])


def test_http_only_for_loopback():
    for ok in ("http://127.0.0.1:8000/index.json", "http://localhost/x/index.json", "https://example.com/index.json"):
        assert library._check_url(ok) == ok
    for bad in ("http://example.com/index.json", "ftp://127.0.0.1/index.json", "file:///etc/passwd"):
        with pytest.raises(library.LibraryError):
            library._check_url(bad)
    assert config.Settings(library_url="http://example.com/i.json").validate()
    assert not config.Settings(library_url="http://127.0.0.1:9/i.json").validate()
    assert config.from_env({"ENCOR_LIBRARY_URL": INDEX, "ENCOR_USE_KEYRING": "0"}).library_url == INDEX


# ---------------------------------------------------------------- first run
def test_first_run_is_empty_and_needs_no_migration(no_labs):
    c = client()
    d = c.get("/api/labs").json()
    assert d["labs"] == [] and d["broken"] == {}
    assert d["migration"]["state"] == "done" and d["migration"]["fresh"]
    r = CliRunner().invoke(cli_app, ["list"])
    assert r.exit_code == 0 and "no labs installed yet" in r.output and "library install --starter" in r.output
    config.save_settings(config.Settings(cml_url="https://cml.example"))   # saving settings later changes nothing
    assert migrate.run_local()["fresh"] and migrate.status()["state"] == "done"


def test_starter_set_one_click(no_labs):
    log = []
    c = client(fetcher(log=log))
    idx = c.get("/api/library").json()
    assert idx["starter"] == index_json()["starter"]
    assert all(i["starter"] == (i["id"] in idx["starter"]) for i in idx["items"] if i["kind"] == "lab")
    assert all(i["size"] > 0 for i in idx["items"])
    evpn = next(i for i in idx["items"] if i["id"] == "18-evpn-vxlan")
    assert evpn["ram_heavy"] and evpn["ram_gb"] >= 40 and evpn["type"] == "walkthrough"
    r = c.post("/api/library/install-set", json={"starter": True}).json()
    assert r["ok"] and sorted(r["installed"]) == sorted(idx["starter"]) and not r["failed"]
    labs = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}
    assert set(labs) == set(idx["starter"])
    assert all(l["source"] == "user" and l["library"] and not l["update_available"] for l in labs.values())
    org = library.origin("eigrp-basic")
    assert org["index"] == INDEX and org["file"] == "eigrp-basic.encorlab" and len(org["sha256"]) == 64
    again = c.post("/api/library/install-set", json={"starter": True}).json()
    assert again["installed"] == [] and sorted(again["skipped"]) == sorted(idx["starter"])
    assert all(u.startswith(BASE) for u in log)


def test_course_install_all_pulls_labs_from_library(no_labs):
    c = client()
    idx = c.get("/api/library").json()
    dc = next(i for i in idx["items"] if i["id"] == "data-center")
    assert dc["missing"] == ["08-vrf-lite", "18-evpn-vxlan"] and dc["installable"] and dc["ram_gb"] >= 40
    r = c.post("/api/library/install", json={"file": "data-center.encorcourse"}).json()
    assert r["kind"] == "course" and set(r["from_library"]) == {"08-vrf-lite", "18-evpn-vxlan"}
    cs = {x["id"]: x for x in c.get("/api/courses").json()["courses"]}
    assert all(l["available"] for l in cs["data-center"]["labs"])
    dc2 = next(i for i in c.get("/api/library").json()["items"] if i["id"] == "data-center")
    assert dc2["installed"] and dc2["missing"] == []
    # a course with bundled example labs + library labs (ospf-mastery)
    r = c.post("/api/library/install", json={"file": "ospf-mastery.encorcourse"}).json()
    assert "03-ospf-multiarea" in r["from_library"] and "troubleshoot-ospf-7node" in r["installed"]


def test_course_file_import_uses_library_and_explains_offline(no_labs):
    data = (LIB / "encor-routing.encorcourse").read_bytes()
    r = client(fetcher(down=True)).post("/api/import", files={"file": ("encor-routing.encorcourse", data)})
    assert r.status_code == 400 and "install it from the lab library first" in r.json()["errors"][0]
    r = client().post("/api/import", files={"file": ("encor-routing.encorcourse", data)})
    assert r.status_code == 200 and r.json()["from_library"]
    course, _ = courses.read_course(data)
    assert set(course.labs) <= set(catalog.entries())


def test_offline_is_graceful(no_labs):
    c = client(fetcher(down=True))
    r = c.get("/api/library")
    assert r.status_code == 502 and "network error" in r.json()["errors"][0]
    r = c.post("/api/library/install-set", json={"starter": True})
    assert r.status_code == 502 and "network error" in r.json()["errors"][0]
    assert c.get("/api/labs").status_code == 200
    rep = c.post("/api/import", files={"file": ("eigrp-basic.encorlab", (LIB / "eigrp-basic.encorlab").read_bytes())}).json()
    assert rep["ok"] and rep["lab_id"] == "eigrp-basic"            # importing a local file works offline
    assert c.post("/api/library/install-set", json={}).status_code == 400


def _bumped(files: dict, lab_id: str, version: str) -> dict:
    """A library where lab_id has a new version (lab.yaml gets version: and a changed summary)."""
    z = zipfile.ZipFile(io.BytesIO(files[f"{lab_id}.encorlab"]))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as w:
        for n in z.namelist():
            t = z.read(n)
            if n == "lab.yaml":
                d = yaml.safe_load(t)
                d["version"] = version
                d["summary"] = d["summary"] + " (revised)"
                t = yaml.safe_dump(d, sort_keys=False).encode()
            w.writestr(n, t)
    new = dict(files)
    new[f"{lab_id}.encorlab"] = out.getvalue()
    idx = json.loads(files["index.json"])
    for it in idx["items"]:
        if it["file"] == f"{lab_id}.encorlab":
            it.update(version=version, sha256=hashlib.sha256(out.getvalue()).hexdigest(), size=len(out.getvalue()))
    new["index.json"] = json.dumps(idx).encode()
    return new


def test_update_available_and_update_keeps_history(no_labs):
    files = lib_files()
    c = client(fetcher(files))
    c.post("/api/library/install-set", json={"ids": ["06-hsrp", "eigrp-basic"]})
    history.add("06-hsrp", {"score_pct": 80, "passed": False, "earned": 4, "total": 5, "results": []})
    hist = (history.data_dir() / "history" / "06-hsrp.json").read_bytes()
    assert not any(i.get("update_available") for i in c.get("/api/library").json()["items"])
    files.update(_bumped(files, "06-hsrp", "2"))
    idx = c.get("/api/library").json()
    hs = next(i for i in idx["items"] if i["id"] == "06-hsrp")
    assert hs["update_available"] and hs["installed_version"] == "1" and hs["version"] == "2" and idx["updates"] == ["06-hsrp"]
    labs = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}
    assert labs["06-hsrp"]["update_available"] and not labs["eigrp-basic"]["update_available"]
    r = c.post("/api/library/install-set", json={"updates": True}).json()
    assert r["installed"] == ["06-hsrp"]
    assert catalog.get("06-hsrp").version == "2" and "(revised)" in catalog.get("06-hsrp").summary
    assert library.origin("06-hsrp")["version"] == "2"
    assert (history.data_dir() / "history" / "06-hsrp.json").read_bytes() == hist
    labs = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}
    assert not labs["06-hsrp"]["update_available"] and labs["06-hsrp"]["best"] == 80


def test_version_ordering():
    from encorlab.schema import version_key
    assert version_key("2") > version_key("1.10") > version_key("1.9") > version_key("1") == version_key("1.0") > version_key("0.9")


def test_build_library_refuses_a_changed_pack_without_a_version_bump(tmp_path):
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_library
    prev = index_json()
    for it in prev["items"]:
        if it["file"] == "06-hsrp.encorlab":
            it["sha256"] = "0" * 64
    with pytest.raises(SystemExit, match="raise `version:`"):
        build_library.build(tmp_path / "out", prev)
    build_library.build(tmp_path / "ok", index_json())
    assert (tmp_path / "ok" / "index.json").read_bytes() == (LIB / "index.json").read_bytes()


def test_delete_keeps_history_unless_asked(no_labs):
    c = client()
    c.post("/api/library/install-set", json={"ids": ["eigrp-basic", "06-hsrp"]})
    for lid in ("eigrp-basic", "06-hsrp"):
        history.add(lid, {"score_pct": 100, "passed": True, "earned": 1, "total": 1, "results": []})
    assert c.delete("/api/user-labs/eigrp-basic").json()["history_cleared"] is False
    assert history.load("eigrp-basic")
    c.post("/api/library/install-set", json={"ids": ["eigrp-basic"]})
    assert {l["id"]: l for l in c.get("/api/labs").json()["labs"]}["eigrp-basic"]["solved"]
    assert c.delete("/api/user-labs/06-hsrp?clear_history=true").json()["history_cleared"]
    assert history.load("06-hsrp") == []


def test_cli_starter_updates_and_list(no_labs, monkeypatch):
    monkeypatch.setattr(library, "http_fetch", fetcher())
    monkeypatch.setattr(library.install_many, "__kwdefaults__", {**library.install_many.__kwdefaults__, "fetch": fetcher()})
    monkeypatch.setattr(library.index, "__defaults__", (INDEX, fetcher()))
    monkeypatch.setenv("ENCOR_LIBRARY_URL", INDEX)
    r = CliRunner().invoke(cli_app, ["library", "install", "--starter"])
    assert r.exit_code == 0 and "installed: " in r.output and "eigrp-basic" in r.output, r.output
    r = CliRunner().invoke(cli_app, ["library", "list"])
    assert r.exit_code == 0 and "RAM heavy ~52 GB" in r.output and "installed" in r.output and "starter set" in r.output
    r = CliRunner().invoke(cli_app, ["library", "install", "--updates"])
    assert r.exit_code == 0 and "installed: -" in r.output
    r = CliRunner().invoke(cli_app, ["list"])
    assert "eigrp-basic" in r.output and "no labs installed" not in r.output


# ---------------------------------------------------------------- migration from 1.x
def _old_app_code(root: Path, version: str, labs=migrate.LEGACY_IDS, tweak: str = "") -> Path:
    """What a 1.x patch / bundle looks like on disk: <root>/encorlab/labs/<id>/ + manifest.json."""
    for lid in labs:
        dst = root / "encorlab" / "labs" / lid
        shutil.copytree(LABSRC / lid, dst)
        if tweak:
            f = dst / "lab.yaml"
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
            d["summary"] = d["summary"] + tweak
            f.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    (root / "encorlab" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (root / "manifest.json").write_text(json.dumps({"format": 1, "app_version": version, "min_runtime": 1, "files": {}}))
    return root / "encorlab" / "labs"


def _user_data():
    """A 1.9 user: settings, history, a walkthrough in progress, a snapshot, a fault, an own lab."""
    config.save_settings(config.Settings(cml_url="https://cml.example", username="dylan"))
    history.add("03-ospf-multiarea", {"score_pct": 75, "passed": False, "earned": 3, "total": 4, "results": []})
    history.add("eigrp-basic", {"score_pct": 100, "passed": True, "earned": 2, "total": 2, "results": []})
    walkthrough._save("18-evpn-vxlan", {"current": 4, "steps": {"fabric": {"passed": True}}, "started": "2026-10-19"})
    snapshots.save("06-hsrp", "before-change", {"R1": "hostname R1\n"}, "iol")
    (history.data_dir() / "faults").mkdir(parents=True, exist_ok=True)
    (history.data_dir() / "faults" / "07-acl-nat.json").write_text(json.dumps({"fault_id": "x", "recent": ["x"]}))
    pk = packs.read_upload("t.encorlab", (LIB / "troubleshoot-ospf-7node.encorlab").read_bytes())
    assert packs.install(pk).ok


def _data_digest() -> dict:
    d = history.data_dir()
    return {str(p.relative_to(d)): p.read_bytes() for sub in migrate.DATA_DIRS if (d / sub).is_dir()
            for p in sorted((d / sub).rglob("*")) if p.is_file()}


def test_patch_update_copies_bundled_labs_and_keeps_everything(no_labs):
    """1.9.0 install updated by patch: the old patch dir (and bundle) is still on disk."""
    _user_data()
    before = _data_digest()
    _old_app_code(history.data_dir() / "app" / "1.8.1", "1.8.1", tweak=" OLD-1.8.1")
    _old_app_code(history.data_dir() / "app" / "1.9.0", "1.9.0")
    st = migrate.run_local()
    assert st["state"] == "done" and sorted(st["copied"]) == sorted(migrate.LEGACY_IDS)
    es = catalog.entries()
    assert set(migrate.LEGACY_IDS) | {"troubleshoot-ospf-7node"} == set(es)
    assert all(e.source == "user" for e in es.values())
    assert "OLD-1.8.1" not in es["03-ospf-multiarea"].lab.summary          # the newest copy won
    assert (catalog.user_labs_dir() / "03-ospf-multiarea" / "lab.yaml").read_bytes() == (LABSRC / "03-ospf-multiarea" / "lab.yaml").read_bytes()
    assert _data_digest() == before                                          # no user data touched
    # everything links up by id
    c = client()
    labs = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}
    assert labs["03-ospf-multiarea"]["best"] == 75 and labs["eigrp-basic"]["solved"] and labs["03-ospf-multiarea"]["library"]
    assert labs["18-evpn-vxlan"]["walkthrough"]["current"] == 4
    assert [s["name"] for s in snapshots.list_snapshots("06-hsrp")] == ["before-change"]
    assert c.get("/api/labs/07-acl-nat").status_code == 200 and labs["07-acl-nat"]["fault_active"]
    assert c.get("/api/history/03-ospf-multiarea").json()[-1]["score_pct"] == 75
    # idempotent; a lab the user deletes later is not brought back
    assert migrate.run_local()["state"] == "done"
    packs.delete_user_lab("12-pbr")
    assert migrate.run_local()["state"] == "done" and "12-pbr" not in catalog.entries()


def test_bundled_runtime_copy_is_a_source(no_labs, tmp_path, monkeypatch):
    """A 1.x frozen install patched to 2.x: the labs are in the runtime's bundled app code (_internal/appcode)."""
    import encorboot
    appcode = tmp_path / "_internal" / "appcode"
    _old_app_code(appcode, "1.9.0")
    monkeypatch.setattr(encorboot, "bundled_dir", lambda: appcode)
    history.add("05-bgp-ebgp-ibgp", {"score_pct": 50, "passed": False, "earned": 1, "total": 2, "results": []})
    st = migrate.run_local()
    assert st["state"] == "done" and len(st["copied"]) == len(migrate.LEGACY_IDS)
    assert all(v.endswith(str(Path("appcode") / "encorlab" / "labs")) for v in st["from"].values())
    # a 2.x bundle is never a legacy source
    assert migrate.legacy_sources() == [appcode / "encorlab" / "labs"]
    _old_app_code(tmp_path / "new", "2.0.0", labs=["eigrp-basic"])
    monkeypatch.setattr(encorboot, "bundled_dir", lambda: tmp_path / "new")
    assert migrate.legacy_sources() == []


def test_existing_user_lab_is_never_overwritten(no_labs):
    _user_data()
    mine = catalog.user_labs_dir() / "eigrp-basic"
    shutil.copytree(LABSRC / "eigrp-basic", mine)
    (mine / "lab.yaml").write_text((mine / "lab.yaml").read_text(encoding="utf-8").replace("title:", "# my edit\ntitle:", 1), encoding="utf-8")
    mine_bytes = (mine / "lab.yaml").read_bytes()
    _old_app_code(history.data_dir() / "app" / "1.9.0", "1.9.0")
    st = migrate.run_local()
    assert "eigrp-basic" not in st["copied"] and (mine / "lab.yaml").read_bytes() == mine_bytes and st["state"] == "done"


def test_broken_source_lab_is_skipped_then_restored_from_library(no_labs):
    _user_data()
    src = _old_app_code(history.data_dir() / "app" / "1.9.0", "1.9.0")
    (src / "12-pbr" / "lab.yaml").write_text("id: [broken", encoding="utf-8")
    st = migrate.run_local()
    assert st["state"] == "pending" and st["pending"] == ["12-pbr"]
    assert migrate.restore(INDEX, fetcher())["state"] == "done" and "12-pbr" in catalog.entries()


def test_full_download_update_restores_from_library(no_labs):
    """Updated with a full download: the old program files are gone, so the labs come from the library."""
    _user_data()
    before = _data_digest()
    st = migrate.run_local()
    assert st["state"] == "pending" and sorted(st["pending"]) == sorted(migrate.LEGACY_IDS)
    s = migrate.status()
    assert {"03-ospf-multiarea", "eigrp-basic", "18-evpn-vxlan", "06-hsrp", "07-acl-nat"} <= set(s["pending_with_data"])
    # offline: nothing breaks, nothing is lost, still pending
    r = migrate.restore(INDEX, fetcher(down=True))
    assert r["state"] == "pending" and "network error" in r["last_error"] and _data_digest() == before
    c = client(fetcher())
    assert c.get("/api/labs").json()["migration"]["state"] == "pending"
    r = c.post("/api/migration/restore").json()
    assert r["state"] == "done" and sorted(r["restored"]) == sorted(migrate.LEGACY_IDS)
    labs = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}
    assert labs["03-ospf-multiarea"]["best"] == 75 and labs["18-evpn-vxlan"]["walkthrough"]["current"] == 4
    assert _data_digest() == before and migrate.run_local()["state"] == "done"


def test_auto_restore_in_background_and_dismiss(no_labs):
    _user_data()
    migrate.run_local()
    c = client(fetcher(), auto_restore=True)
    for _ in range(100):
        if migrate.status()["state"] == "done":
            break
        time.sleep(0.1)
    assert migrate.status()["state"] == "done" and set(migrate.LEGACY_IDS) <= set(catalog.entries())
    assert c.get("/api/migration").json()["state"] == "done"


def test_dismiss_and_data_only_ids(no_labs):
    config.save_settings(config.Settings(cml_url="https://cml.example"))
    history.add("my-deleted-lab", {"score_pct": 10, "passed": False, "earned": 0, "total": 1, "results": []})
    st = migrate.run_local()
    assert "my-deleted-lab" in st["pending"]
    r = migrate.restore(INDEX, fetcher())
    assert r["state"] == "done" and "my-deleted-lab" in r["unavailable"] and history.load("my-deleted-lab")
    assert migrate.dismiss()["state"] == "done"


def test_cli_restore_and_start_note(no_labs, monkeypatch):
    _user_data()
    r = CliRunner().invoke(cli_app, ["version"])
    assert "still need to be restored" in r.output and "library restore" in r.output
    monkeypatch.setattr(library, "http_fetch", fetcher())
    monkeypatch.setenv("ENCOR_LIBRARY_URL", INDEX)
    r = CliRunner().invoke(cli_app, ["library", "restore"])
    assert r.exit_code == 0 and "nothing to restore" in r.output and "eigrp-basic" in r.output


def test_ui_strings_for_first_run_and_updates():
    js = (ROOT / "encorlab" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    for s in ("Install recommended starter set", "Browse library", "Import a .encorlab file", "Update all", "Install all",
              "update available", "/api/migration/restore", "Could not reach the lab library", "clear_history"):
        assert s in js, s
    html = (ROOT / "encorlab" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'name="library_url"' in html and 'id="mig-banner"' in html
