"""Courses (.encorcourse) and the online lab library (index + sha256 integrity)."""
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from encorlab import catalog, courses, history, library, packs
from encorlab.cli import app as cli_app
from test_web import make

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "labs"
INDEX = library.DEFAULT_INDEX
BASE = INDEX.rsplit("/", 1)[0] + "/"


def fake_fetch(files=None, log=None):
    files = files if files is not None else {p.name: p.read_bytes() for p in LIB.iterdir()}

    def f(url, limit):
        if log is not None:
            log.append(url)
        assert url.startswith(BASE), url
        data = files.get(url[len(BASE):])
        if data is None:
            raise library.LibraryError(f"download failed: HTTP 404 for {url}")
        if len(data) > limit:
            raise library.LibraryError("file is larger than the limit")
        return data
    return f


def zipped(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


def lab_files(lab_dir: Path, prefix: str) -> dict:
    return {f"{prefix}{p.name}": p.read_bytes() for p in lab_dir.iterdir() if p.name in packs.PACK_FILES}


# ---------------------------------------------------------------- repo library folder
def test_repo_library_is_up_to_date_and_consistent():
    r = subprocess.run([sys.executable, str(ROOT / "packaging" / "build_library.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    idx = json.loads((LIB / "index.json").read_text())
    files = {i["file"] for i in idx["items"]}
    assert {"ospf-mastery.encorcourse", "ospf-multiarea-stub.encorlab", "troubleshoot-ospf-7node.encorlab"} <= files
    for it in idx["items"]:
        data = (LIB / it["file"]).read_bytes()
        assert library.sha256(data) == it["sha256"] and len(data) == it["size"]
    assert courses.deterministic_pack(ROOT / "examples" / "ospf-multiarea-stub") == (LIB / "ospf-multiarea-stub.encorlab").read_bytes()


# ---------------------------------------------------------------- courses
def test_course_install_list_progress_delete():
    r = courses.install((LIB / "ospf-mastery.encorcourse").read_bytes())
    assert r["course_id"] == "ospf-mastery" and r["installed"] == ["ospf-multiarea-stub", "troubleshoot-ospf-7node"]
    assert catalog.entry("troubleshoot-ospf-7node").source == "user"
    cs = courses.list_courses({"03-ospf-multiarea": 100, "ospf-multiarea-stub": 60})
    c = cs[0]
    assert (c["solved"], c["total"], c["pct"], c["next"]) == (1, 3, 33, "ospf-multiarea-stub")
    assert c["labs"][1]["best"] == 60 and not c["labs"][1]["solved"]
    with pytest.raises(packs.LabError, match="already exists"):
        courses.install((LIB / "ospf-mastery.encorcourse").read_bytes())
    courses.install((LIB / "ospf-mastery.encorcourse").read_bytes(), overwrite=True)
    assert courses.delete("ospf-mastery", remove_labs=True) == ["ospf-multiarea-stub", "troubleshoot-ospf-7node"]
    assert courses.list_courses() == [] and "03-ospf-multiarea" in catalog.entries()
    with pytest.raises(packs.LabError, match="not installed"):
        courses.delete("ospf-mastery")


def test_course_delete_keeps_labs_used_by_another_course():
    courses.install((LIB / "ospf-mastery.encorcourse").read_bytes())
    other = zipped({"course.yaml": b"id: other\ntitle: Other course\nlabs: [ospf-multiarea-stub]\n"})
    courses.install(other)
    assert courses.delete("ospf-mastery", remove_labs=True) == ["troubleshoot-ospf-7node"]
    assert "ospf-multiarea-stub" in catalog.entries()


def test_course_only_builtin_labs():
    r = courses.install((LIB / "encor-routing.encorcourse").read_bytes())
    assert r["installed"] == [] and courses.list_courses()[0]["next"] == "eigrp-basic"
    assert courses.delete("encor-routing", remove_labs=True) == []


@pytest.mark.parametrize("files,msg", [
    ({"labs/x/lab.yaml": b"x"}, "no course.yaml"),
    ({"course.yaml": b"id: [\n"}, "YAML error"),
    ({"course.yaml": b"id: Bad Id\ntitle: Something\nlabs: [eigrp-basic]\n"}, "id"),
    ({"course.yaml": b"id: dup\ntitle: Something\nlabs: [eigrp-basic, eigrp-basic]\n"}, "listed twice"),
    ({"course.yaml": b"id: miss\ntitle: Something\nlabs: [no-such-lab]\n"}, "neither bundled nor installed"),
    ({"course.yaml": b"id: evil\ntitle: Something\nlabs: [eigrp-basic]\n", "../evil.txt": b"x"}, "unsafe path"),
])
def test_course_errors(files, msg):
    with pytest.raises(packs.LabError, match=msg):
        courses.install(zipped(files))
    assert courses.list_courses() == []


def test_course_install_is_all_or_nothing():
    ex = ROOT / "examples"
    files = {"course.yaml": b"id: mixed\ntitle: Mixed course\nlabs: [ospf-multiarea-stub, broken]\n"}
    files.update(lab_files(ex / "ospf-multiarea-stub", "labs/ospf-multiarea-stub/"))
    files["labs/broken/lab.yaml"] = b"id: broken\ntitle: x\n"
    with pytest.raises(packs.LabError, match="broken"):
        courses.install(zipped(files))
    assert "ospf-multiarea-stub" not in catalog.entries() and courses.list_courses() == []


def test_course_folder_must_match_lab_id():
    files = {"course.yaml": b"id: wrongdir\ntitle: Wrong dir\nlabs: [ospf-multiarea-stub]\n"}
    files.update(lab_files(ROOT / "examples" / "ospf-multiarea-stub", "labs/other-name/"))
    with pytest.raises(packs.LabError, match="must be named after the lab id"):
        courses.install(zipped(files))


# ---------------------------------------------------------------- library
def test_library_index_marks_installed():
    idx = library.index(fetch=fake_fetch())
    by = {i["file"]: i for i in idx["items"]}
    assert by["ospf-mastery.encorcourse"]["kind"] == "course" and not by["ospf-mastery.encorcourse"]["installed"]
    assert by["ospf-multiarea-stub.encorlab"]["nodes"] > 0 and by["ospf-multiarea-stub.encorlab"]["blueprint"]
    library.install_item("ospf-mastery.encorcourse", fetch=fake_fetch())
    by = {i["file"]: i for i in library.index(fetch=fake_fetch())["items"]}
    assert by["ospf-mastery.encorcourse"]["installed"] and by["troubleshoot-ospf-7node.encorlab"]["installed"]


def test_library_install_lab_verifies_integrity():
    files = {p.name: p.read_bytes() for p in LIB.iterdir()}
    log = []
    r = library.install_item("ospf-multiarea-stub.encorlab", fetch=fake_fetch(files, log))
    assert r["kind"] == "lab" and r["lab_id"] == "ospf-multiarea-stub"
    assert log == [INDEX, BASE + "ospf-multiarea-stub.encorlab"]
    tampered = dict(files)
    good = bytearray(files["troubleshoot-ospf-7node.encorlab"])
    good[len(good) // 2] ^= 0xFF
    tampered["troubleshoot-ospf-7node.encorlab"] = bytes(good)
    with pytest.raises(library.LibraryError, match="integrity check failed"):
        library.install_item("troubleshoot-ospf-7node.encorlab", fetch=fake_fetch(tampered))
    assert "troubleshoot-ospf-7node" not in catalog.entries()
    with pytest.raises(library.LibraryError, match="not in the library index"):
        library.install_item("nope.encorlab", fetch=fake_fetch())


def test_library_index_rejects_bad_entries_and_urls():
    bad = json.dumps({"items": [
        {"file": "../../etc/passwd.encorlab", "sha256": "0" * 64, "size": 1},
        {"file": "ok.encorlab", "sha256": "xyz", "size": 1},
        {"file": "ok.encorlab", "sha256": "a" * 64, "size": 10, "title": "Fine"}]}).encode()
    items = library.parse_index(bad)
    assert [i["file"] for i in items] == ["ok.encorlab"]
    with pytest.raises(library.LibraryError, match="valid JSON"):
        library.parse_index(b"<html>")
    with pytest.raises(library.LibraryError, match="https"):
        library.index("http://example.com/index.json", fetch=fake_fetch())
    with pytest.raises(library.LibraryError, match="https"):
        library.install_url("file:///etc/passwd.encorlab", fetch=fake_fetch())


def test_install_url_with_and_without_sha():
    data = (LIB / "ospf-multiarea-stub.encorlab").read_bytes()
    url = "https://example.org/share/ospf-multiarea-stub.encorlab"
    f = lambda u, lim: data  # noqa: E731
    with pytest.raises(library.LibraryError, match="integrity check failed"):
        library.install_url(url, "0" * 64, fetch=f)
    with pytest.raises(library.LibraryError, match="64 hex"):
        library.install_url(url, "abc", fetch=f)
    with pytest.raises(library.LibraryError, match="must point to"):
        library.install_url("https://example.org/x.exe", fetch=f)
    r = library.install_url(url, library.sha256(data).upper(), fetch=f)
    assert r["verified"] and r["lab_id"] == "ospf-multiarea-stub"
    r = library.install_url(url, "", fetch=f, overwrite=True)
    assert not r["verified"]


def test_http_fetch_size_limit_and_https_redirects(monkeypatch):
    def handler(req):
        if req.url.path == "/big":
            return httpx.Response(200, content=b"x" * 2000)
        if req.url.path == "/redir":
            return httpx.Response(302, headers={"location": "http://evil.example/x"})
        if req.url.path == "/404":
            return httpx.Response(404)
        return httpx.Response(200, content=b"hello")
    monkeypatch.setattr(library, "_TRANSPORT", httpx.MockTransport(handler))
    assert library.http_fetch("https://h.example/ok", 100) == b"hello"
    with pytest.raises(library.LibraryError, match="larger"):
        library.http_fetch("https://h.example/big", 1000)
    with pytest.raises(library.LibraryError, match="https"):
        library.http_fetch("https://h.example/redir", 1000)
    with pytest.raises(library.LibraryError, match="HTTP 404"):
        library.http_fetch("https://h.example/404", 1000)

    def boom(req):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(library, "_TRANSPORT", httpx.MockTransport(boom))
    with pytest.raises(library.LibraryError, match="network error"):
        library.http_fetch("https://h.example/ok", 100)


# ---------------------------------------------------------------- API + CLI
def _client(fetch=None):
    from fastapi.testclient import TestClient
    from encorlab import config
    from encorlab.web.app import create_app
    app = create_app(config.SettingsStore(config.Settings()), persist=False, library_fetch=fetch or fake_fetch())
    return TestClient(app)


def test_api_library_and_courses():
    c = _client()
    idx = c.get("/api/library").json()
    assert any(i["file"] == "ospf-mastery.encorcourse" for i in idx["items"])
    r = c.post("/api/library/install", json={"file": "ospf-mastery.encorcourse"})
    assert r.status_code == 200 and r.json()["kind"] == "course"
    assert c.post("/api/library/install", json={"file": "ospf-mastery.encorcourse"}).status_code == 409
    assert c.post("/api/library/install", json={"file": "ospf-mastery.encorcourse", "replace": True}).status_code == 200
    history.add("03-ospf-multiarea", {"score_pct": 100, "passed": True, "earned": 1, "total": 1, "results": []})
    cs = c.get("/api/courses").json()["courses"]
    assert cs[0]["solved"] == 1 and cs[0]["next"] == "ospf-multiarea-stub"
    labs = {l["id"] for l in c.get("/api/labs").json()["labs"]}
    assert "troubleshoot-ospf-7node" in labs
    assert c.delete("/api/courses/ospf-mastery?labs=true").json()["removed_labs"] == ["ospf-multiarea-stub", "troubleshoot-ospf-7node"]
    assert c.delete("/api/courses/ospf-mastery").status_code == 404
    assert c.post("/api/library/install", json={}).status_code == 400
    assert c.post("/api/library/install", json={"url": "http://x/y.encorlab"}).status_code == 400


def test_api_library_network_error_is_reported():
    def down(url, limit):
        raise library.LibraryError("network error fetching x: ConnectError")
    r = _client(down).get("/api/library")
    assert r.status_code == 502 and "network error" in r.json()["errors"][0]


def test_api_import_course_file():
    c, _ = make()
    data = (LIB / "ospf-mastery.encorcourse").read_bytes()
    r = c.post("/api/import", files={"file": ("ospf-mastery.encorcourse", data)})
    assert r.status_code == 200 and r.json()["course_id"] == "ospf-mastery"
    r = c.post("/api/import", files={"file": ("ospf-mastery.encorcourse", data)})
    assert r.status_code == 409
    r = c.post("/api/import", files={"file": ("x.zip", zipped({"course.yaml": b"id: q\n"}))})
    assert r.status_code == 400 and r.json()["errors"]


def test_cli_course_build_import_list_delete(tmp_path):
    out = tmp_path / "c.encorcourse"
    run = CliRunner().invoke
    r = run(cli_app, ["course", "build", str(ROOT / "examples" / "courses" / "ospf-mastery"), "-o", str(out),
                      "--labs-from", str(ROOT / "examples")])
    assert r.exit_code == 0 and "sha256" in r.output
    assert out.read_bytes() == (LIB / "ospf-mastery.encorcourse").read_bytes()
    r = run(cli_app, ["import", str(out)])
    assert r.exit_code == 0 and "installed course ospf-mastery" in r.output
    r = run(cli_app, ["course", "list"])
    assert "0/3 solved" in r.output and "next: 03-ospf-multiarea" in r.output
    r = run(cli_app, ["course", "delete", "ospf-mastery", "--labs"])
    assert r.exit_code == 0 and "troubleshoot-ospf-7node" in r.output
    r = run(cli_app, ["course", "build", str(tmp_path)])
    assert r.exit_code == 1 and "no course.yaml" in r.output


def test_cli_library_install(monkeypatch):
    monkeypatch.setattr(library, "http_fetch", fake_fetch())
    monkeypatch.setattr(library.index, "__defaults__", (INDEX, fake_fetch()))
    monkeypatch.setattr(library.install_item, "__defaults__", (INDEX, fake_fetch(), 20, False))
    r = CliRunner().invoke(cli_app, ["library", "list"])
    assert r.exit_code == 0 and "ospf-mastery.encorcourse" in r.output
    r = CliRunner().invoke(cli_app, ["library", "install", "troubleshoot-ospf-7node.encorlab"])
    assert r.exit_code == 0 and "installed lab troubleshoot-ospf-7node" in r.output
