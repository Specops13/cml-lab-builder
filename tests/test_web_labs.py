import io
import json
import zipfile
from pathlib import Path

import httpx
import yaml

from cmllab import catalog, config, platforms, prompt
from cmllab.render import to_yaml
from cmllab.sim import SimRunner
from cmllab.web.app import create_app
from fakes import FakeClient
from test_web import wait
from fastapi.testclient import TestClient

EXAMPLE = prompt.example()
OSPF = Path(__file__).parent.parent / "examples" / "ospf-multiarea-stub"


def make(configured=True, ai_transport=None, settings=None):
    s = settings or (config.Settings(cml_url="https://cml.x", username="u", password="pw") if configured else config.Settings())
    fc = FakeClient()

    def sim(st, lab_id, test=False):
        e = catalog.entry(lab_id)
        return SimRunner(e.lab, platforms.get(st.platform), test, solution=catalog.load_solution(lab_id) if test else None)
    app = create_app(config.SettingsStore(s), client_factory=lambda st: fc, runner_factory=sim, config_factory=sim,
                     probe=lambda h, p: {"ok": True, "detail": "ok"}, persist=False, ai_transport=ai_transport)
    return TestClient(app), fc


def upload(c, name, data, replace=False):
    return c.post("/api/import" + ("?replace=true" if replace else ""), files={"file": (name, data)})


def zip_dir(d: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in d.iterdir():
            z.write(f, f.name)
    return buf.getvalue()


def test_index_has_import_and_drop_zone_and_version():
    c, _ = make()
    html = c.get("/").text
    assert 'id="import-btn"' in html and 'id="drop-overlay"' in html and "{{VERSION}}" not in html
    js = c.get("/static/app.js").text
    assert "dragenter" in js and "/api/import" in js


def test_import_yaml_then_listed_conflict_replace_delete():
    c, _ = make()
    r = upload(c, "lab.yaml", EXAMPLE.encode())
    assert r.status_code == 200, r.text
    assert r.json()["lab_id"] == "example-eigrp-pair"
    labs = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}
    assert labs["example-eigrp-pair"]["source"] == "user"
    r = upload(c, "lab.yaml", EXAMPLE.encode())
    assert r.status_code == 409 and r.json()["lab_id"] == "example-eigrp-pair"
    assert upload(c, "lab.yaml", EXAMPLE.encode(), replace=True).status_code == 200
    exp = c.get("/api/labs/example-eigrp-pair/export")
    assert exp.status_code == 200 and zipfile.ZipFile(io.BytesIO(exp.content)).read("lab.yaml")
    assert c.delete("/api/user-labs/eigrp-basic").status_code == 400
    assert c.delete("/api/user-labs/example-eigrp-pair").status_code == 200
    assert c.get("/api/labs/example-eigrp-pair").status_code == 404


def test_import_pack_with_fixtures():
    c, _ = make()
    r = upload(c, "ospf-multiarea-stub.encorlab", zip_dir(OSPF))
    assert r.status_code == 200, r.text
    rep = r.json()
    assert {x["mode"] for x in rep["results"]} == {"live", "config"}
    t = c.get("/api/labs/ospf-multiarea-stub").json()
    assert t["source"] == "user" and "%if" not in t["task"]


def test_import_errors_are_friendly():
    c, _ = make()
    r = upload(c, "lab.yaml", b"id: [oops")
    assert r.status_code == 400 and "line" in r.json()["errors"][0].lower()
    r = upload(c, "lab.encorlab", b"garbage")
    assert r.status_code == 400 and "not a valid" in r.json()["errors"][0]
    bad = EXAMPLE.replace("difficulty: 1", "difficulty: 11")
    r = upload(c, "lab.yaml", bad.encode())
    assert r.status_code == 400 and any("difficulty" in e for e in r.json()["errors"])


def test_builder_endpoints_validate_dump_parse_save():
    c, _ = make()
    obj = c.post("/api/yaml/parse", json={"yaml": EXAMPLE}).json()["obj"]
    obj["id"] = "my-copy"
    y = c.post("/api/yaml/dump", json={"obj": obj}).json()["yaml"]
    v = c.post("/api/validate", json={"yaml": y, "strict": True}).json()
    assert v["ok"], v
    assert c.post("/api/yaml/parse", json={"yaml": "a: ["}).status_code == 400
    assert not c.post("/api/validate", json={"yaml": "id: x"}).json()["ok"]
    assert c.post("/api/user-labs", json={"yaml": y}).status_code == 200
    assert c.post("/api/user-labs", json={"yaml": y}).status_code == 409
    assert c.post("/api/user-labs", json={"yaml": y, "replace": True}).status_code == 200
    src = c.get("/api/labs/my-copy/source").json()
    assert src["source"] == "user" and "solution:" in src["yaml"]
    assert "solution:" in c.get("/api/labs/eigrp-basic/source").json()["yaml"]
    tpls = c.get("/api/templates").json()
    assert {"ospf_neighbor", "config_lines"} <= {t["name"] for t in tpls}
    assert c.get("/api/schema").json()["title"]
    assert "OSPF" in c.get("/api/prompt", params={"description": "OSPF"}).json()["prompt"]


def test_test_live_uses_test_copy_and_cleans_up():
    c, fc = make()
    j = wait(c, c.post("/api/labs/eigrp-basic/test-live").json()["job_id"])
    assert j["state"] == "done", j
    assert j["result"]["passed"]
    assert fc.labs and all(l.removed for l in fc.labs) and fc.labs[0].title.startswith("CML-TEST-")


def test_history_recorded_after_check():
    c, _ = make()
    wait(c, c.post("/api/labs/eigrp-basic/build").json()["job_id"])
    wait(c, c.post("/api/labs/eigrp-basic/check?mode=config").json()["job_id"])
    h = c.get("/api/history/eigrp-basic").json()
    assert len(h) == 1 and h[0]["mode"] == "config"
    assert c.get("/api/labs").json()["labs"][[l["id"] for l in c.get("/api/labs").json()["labs"]].index("eigrp-basic")]["best"] is not None
    c.delete("/api/history/eigrp-basic")
    assert c.get("/api/history/eigrp-basic").json() == []


def test_cml_labs_and_draft():
    c, fc = make()
    lab = catalog.get("eigrp-basic")
    fc.import_lab(to_yaml(lab, platforms.get("iol"), "CML-"), title="My lab")
    labs = c.get("/api/cml/labs").json()
    assert labs[0]["title"] == "My lab"
    d = c.post("/api/cml/draft", json={"lab_id": labs[0]["id"]}).json()
    assert d["obj"]["id"] == "my-lab" and len(d["obj"]["nodes"]) == 2 and d["warnings"]
    assert c.post("/api/cml/draft", json={"lab_id": "nope"}).status_code == 400


def test_ai_endpoint_mocked_and_key_never_returned():
    ex = yaml.safe_load(EXAMPLE)

    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(ex)}}]})
    c, _ = make(ai_transport=httpx.MockTransport(handler))
    assert c.post("/api/ai/generate", json={"description": "x"}).status_code == 400  # not configured
    r = c.post("/api/settings", json={"ai_base_url": "https://api.x.ai/v1", "ai_model": "grok-4", "ai_api_key": "SECRETKEY"})
    assert r.status_code == 200 and "SECRETKEY" not in r.text and r.json()["ai_api_key_set"]
    assert "SECRETKEY" not in c.get("/api/settings").text
    assert set(c.get("/api/ai/presets").json()) >= {"xai", "openai", "ollama", "lmstudio"}
    j = wait(c, c.post("/api/ai/generate", json={"description": "eigrp"}).json()["job_id"])
    assert j["state"] == "done" and j["result"]["ok"] and "SECRETKEY" not in json.dumps(j)


def test_builder_save_keeps_fixtures_until_they_stop_matching():
    c, _ = make()
    assert upload(c, "o.encorlab", zip_dir(OSPF)).status_code == 200
    y = c.get("/api/labs/ospf-multiarea-stub/source").json()["yaml"]
    v = c.post("/api/validate", json={"yaml": y, "fixtures_from": "ospf-multiarea-stub"}).json()
    assert v["ok"] and "live" in {r["mode"] for r in v["results"]}
    r = c.post("/api/user-labs", json={"yaml": y, "replace": True, "fixtures_from": "ospf-multiarea-stub"})
    assert r.status_code == 200
    d = catalog.entry("ospf-multiarea-stub").path
    assert (d / "fixture_solved.yaml").is_file() and (d / "README.md").is_file()
    # change a live check so the recorded output no longer fits -> fixtures dropped with a warning, save succeeds
    obj = yaml.safe_load(y)
    obj["checks"][0]["params"]["neighbor_id"] = "9.9.9.9"
    y2 = c.post("/api/yaml/dump", json={"obj": obj}).json()["yaml"]
    r = c.post("/api/user-labs", json={"yaml": y2, "replace": True, "fixtures_from": "ospf-multiarea-stub"})
    assert r.status_code == 200 and any("fixtures" in w for w in r.json()["warnings"])
    assert not (d / "fixture_solved.yaml").exists()
