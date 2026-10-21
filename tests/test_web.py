import time

from fastapi.testclient import TestClient

from cmllab import catalog, config, platforms
from cmllab.sim import SimRunner
from cmllab.web.app import create_app
from fakes import FakeClient


def make(solved=True, configured=True, live=True, console_ok=True):
    s = config.Settings(cml_url="https://cml.x", username="u", password="pw") if configured else config.Settings()
    fc = FakeClient()
    sim = lambda st, lab_id, test=False: SimRunner(catalog.get(lab_id), platforms.get(st.platform), solved)  # noqa: E731
    app = create_app(config.SettingsStore(s), client_factory=lambda st: fc,
                     runner_factory=sim if live else None, config_factory=sim,
                     probe=lambda h, p: {"ok": console_ok, "detail": "ok" if console_ok else "TCP connect failed"},
                     persist=False)
    return TestClient(app), fc


def wait(c, job_id):
    for _ in range(200):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_index_and_static():
    c, _ = make()
    assert "CML Lab Builder" in c.get("/").text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/api/health").json()["ok"]


def test_labs_and_task():
    c, _ = make()
    data = c.get("/api/labs").json()
    ids = [l["id"] for l in data["labs"]]
    assert "eigrp-basic" in ids and len(ids) == 19 and data["broken"] == {}
    assert all(l["source"] == "builtin" for l in data["labs"])
    t = c.get("/api/labs/eigrp-basic").json()
    assert "Ethernet0/0" in t["task"] and "%if" not in t["task"]
    assert c.get("/api/labs/nope").status_code == 404


def test_settings_roundtrip_hides_password():
    c, _ = make(configured=False)
    r = c.post("/api/settings", json={"cml_url": "https://cml.ts.net", "username": "dylan", "password": "pw", "platform": "iosv"})
    assert r.status_code == 200
    body = r.json()
    assert body["password"] == "" and body["password_set"] and body["platform"] == "iosv"
    assert "pw" not in c.get("/api/settings").text.replace("password", "")
    assert c.post("/api/settings", json={"platform": "junos"}).status_code == 400


def test_actions_require_settings():
    c, _ = make(configured=False)
    assert c.post("/api/labs/eigrp-basic/build").status_code == 400


def test_build_check_reset_destroy_flow():
    c, fc = make(solved=True)
    j = wait(c, c.post("/api/labs/eigrp-basic/build").json()["job_id"])
    assert j["state"] == "done", j
    st = c.get("/api/labs/eigrp-basic/status").json()
    assert st["exists"] and st["nodes"] == {"R1": "BOOTED", "R2": "BOOTED"}
    j = wait(c, c.post("/api/labs/eigrp-basic/check").json()["job_id"])
    assert j["result"]["score_pct"] == 100.0 and j["result"]["passed"]
    j = wait(c, c.post("/api/labs/eigrp-basic/reset").json()["job_id"])
    assert j["state"] == "done"
    j = wait(c, c.post("/api/labs/eigrp-basic/destroy").json()["job_id"])
    assert j["result"] == {"destroyed": True}
    assert c.get("/api/labs/eigrp-basic/status").json()["exists"] is False


def test_check_blank_fails():
    c, _ = make(solved=False)
    j = wait(c, c.post("/api/labs/eigrp-basic/check").json()["job_id"])
    assert j["result"]["passed"] is False and j["result"]["score_pct"] == 0
    assert all(r["hint"] for r in j["result"]["results"] if r["device"] and not r["passed"] and r["id"] != "r1-ping")


def test_job_error_reported():
    c, _ = make()
    j = wait(c, c.post("/api/labs/eigrp-basic/reset").json()["job_id"])  # not built yet
    assert j["state"] == "error" and "not built" in j["error"]


def test_check_modes_via_api():
    c, _ = make()
    j = wait(c, c.post("/api/labs/eigrp-basic/check?mode=config").json()["job_id"])
    assert j["result"]["mode"] == "config" and j["result"]["passed"] and "cannot verify" in j["result"]["notes"][0]
    j = wait(c, c.post("/api/labs/eigrp-basic/check?mode=live").json()["job_id"])
    assert j["result"]["mode"] == "live"
    assert c.post("/api/labs/eigrp-basic/check?mode=bogus").status_code == 400


def test_auto_fallback_visible_via_api():
    c, _ = make(live=False, console_ok=False)
    j = wait(c, c.post("/api/labs/eigrp-basic/check?mode=auto").json()["job_id"])
    assert j["result"]["mode"] == "config" and "fell back" in j["result"]["notes"][0]


def test_settings_page_has_console_fields():
    c, _ = make()
    html = c.get("/").text
    assert "Console server FQDN (port 22 proxy)" in html and 'name="console_port"' in html and 'name="grading_mode"' in html
    r = c.post("/api/settings", json={"console_host": "ssh.example.net", "console_port": 22, "grading_mode": "auto"})
    assert r.json()["console_host"] == "ssh.example.net" and r.json()["grading_mode"] == "auto"


def test_settings_persist_to_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CMLLAB_SETTINGS_FILE", str(tmp_path / "s.json"))
    app = create_app(config.SettingsStore(config.Settings()), persist=True)
    r = TestClient(app).post("/api/settings", json={"cml_url": "https://cml.x", "username": "d", "password": "pw",
                                                    "console_host": "ssh.x", "console_port": 22})
    assert r.json()["settings_file"].endswith("s.json")
    text = (tmp_path / "s.json").read_text(encoding="utf-8")
    assert "ssh.x" in text and "pw" not in text.replace('"password', "")
