"""Resource pre-check before Build (3.3.0, cmllab/resources.py) against a mocked CML."""
import time

import pytest
from fastapi.testclient import TestClient

from cmllab import config, resources
from cmllab.web.app import create_app
from fakes import GIB, FakeClient, FakeLicensing


def _running(fc, title, n, definition="iol-xe", ram_mib=None):
    lab = fc.add_foreign_running_lab(n, title=title)
    for node in lab._nodes:
        node.node_definition = definition
        node.ram = ram_mib
    return lab


# ------------------------------------------------------------------ snapshot + verdict
def test_snapshot_reads_memory_labs_and_ram():
    fc = FakeClient(total_gb=64, free_gb=40)
    _running(fc, "CML-big", 2, "nxosv9000")                 # 2 x 12 GB (definition default)
    _running(fc, "someone", 3, "iol-xe", ram_mib=2048)      # 3 x 2 GB (node setting)
    s = resources.snapshot(fc)
    assert (s["total_gb"], s["free_gb"]) == (64.0, 40.0)
    assert [x["title"] for x in s["labs"]] == ["CML-big", "someone"]       # biggest first
    assert s["labs"][0]["ram_gb"] == 24 and s["labs"][0]["ours"] and not s["labs"][1]["ours"]
    assert s["labs"][1]["ram_gb"] == 6
    assert s["committed_gb"] == 30 and s["available_gb"] == 34            # min(free 40, total 64 - 30)
    assert s["running_nodes"] == 5 and s["ok"] and not s["errors"]


def test_stopped_labs_are_not_listed():
    fc = FakeClient()
    _running(fc, "CML-x", 2).stop()
    assert resources.snapshot(fc)["labs"] == []


@pytest.mark.parametrize("need,level", [(10, "fits"), (30, "fits"), (31, "tight"), (40, "nofit")])
def test_verdict_levels(need, level):
    snap = {"available_gb": 34.0, "labs": [], "running_nodes": 0}
    v = resources.verdict(snap, need, 4, headroom_gb=4)
    assert v["level"] == level
    assert v["margin_gb"] == round(34 - need, 1)
    assert bool(v["reasons"]) == (level != "fits")


def test_headroom_is_configurable():
    snap = {"available_gb": 20.0, "labs": [], "running_nodes": 0}
    assert resources.verdict(snap, 14, 2, headroom_gb=4)["level"] == "fits"
    assert resources.verdict(snap, 14, 2, headroom_gb=8)["level"] == "tight"
    assert resources.verdict(snap, 14, 2, headroom_gb=0)["level"] == "fits"


def test_license_and_node_limit():
    snap = {"available_gb": 100.0, "labs": [], "running_nodes": 15, "license": {"max": 20, "in_use": 15}}
    v = resources.verdict(snap, 4, 6, node_limit=50)
    assert v["level"] == "nofit" and "licensed nodes" in v["reasons"][0]
    snap["license"] = None
    assert resources.verdict(snap, 4, 6, node_limit=20)["level"] == "nofit"
    assert resources.verdict(snap, 4, 5, node_limit=20)["level"] == "fits"


def test_rebuild_counts_the_running_copy_as_free():
    snap = {"available_gb": 5.0, "running_nodes": 10,
            "labs": [{"id": "x", "title": "CML-ospf", "ram_gb": 10.0, "counted_nodes": 10, "running_nodes": 10}]}
    v = resources.verdict(snap, 12, 10, headroom_gb=4, node_limit=12, own_title="CML-ospf")
    assert v["need_gb"] == 2 and v["level"] == "tight" and v["running_copy"]["id"] == "x"


def test_failures_make_unknown_never_raise():
    fc = FakeClient()
    fc.stats_error = PermissionError("403 Forbidden: admin only")
    fc.licensing = FakeLicensing(error=PermissionError("nope"))
    _running(fc, "CML-a", 1)
    s = resources.snapshot(fc)
    assert s["available_gb"] is None and not s["ok"] and "system stats" in s["errors"][0]
    assert len(s["labs"]) == 1
    v = resources.verdict(s, 4, 1)
    assert v["level"] == "unknown" and "Could not read" in v["reasons"][0]

    class Broken:
        def get_system_stats(self):
            raise ConnectionError("down")
        licensing = None

        def all_labs(self, show_all=False):
            raise ConnectionError("down")
    s = resources.snapshot(Broken())
    assert s["available_gb"] is None and len(s["errors"]) == 2


def test_license_parsing():
    fc = FakeClient()
    fc.licensing = FakeLicensing({"features": [{"name": "CML - Personal Edition", "in_use": 7, "max": 20}]})
    assert resources.snapshot(fc)["license"] == {"max": 20, "in_use": 7}


def test_memory_from_computes_when_no_all():
    stats = {"computes": {"a": {"stats": {"memory": {"total": 32 * GIB, "free": 10 * GIB}}},
                          "b": {"stats": {"memory": {"total": 32 * GIB, "free": 20 * GIB}}}}}
    assert resources._memory(stats) == (64.0, 30.0)
    assert resources._memory({}) == (None, None)


def test_node_ram_units():
    assert resources._gb(2048, "mib") == 2.0
    assert resources._gb(2 * GIB, "mib") == 2.0      # some client versions report bytes
    assert resources._gb(None) is None


def test_cache():
    t = [0.0]
    c = resources.Cache(ttl=30, clock=lambda: t[0])
    calls = []
    f = lambda: calls.append(1) or {"n": len(calls)}
    assert c.get("k", f) == {"n": 1, "cached": False}
    t[0] = 10
    assert c.get("k", f)["cached"] and len(calls) == 1
    assert not c.get("k", f, fresh=True)["cached"] and len(calls) == 2
    t[0] = 100
    assert not c.get("k", f)["cached"]


def test_stop_and_wipe():
    fc = FakeClient()
    ours = _running(fc, "CML-mine", 2)
    other = _running(fc, "colleague", 2)
    log = []
    with pytest.raises(RuntimeError, match="refusing to wipe"):
        resources.stop_lab(fc, other.id, log.append, wipe=True)
    assert "stop" not in other.calls
    resources.stop_lab(fc, other.id, log.append)
    assert other.calls[-1] == "stop" and "wipe" not in other.calls
    resources.stop_lab(fc, ours.id, log.append, wipe=True)
    assert ours.calls[-2:] == ["stop", "wipe"]
    with pytest.raises(RuntimeError, match="no CML lab"):
        resources.stop_lab(fc, "nope", log.append)


# ------------------------------------------------------------------ web API
def _app(fc, **kw):
    s = config.Settings(cml_url="https://cml.example", username="u", password="p", **kw)
    return TestClient(create_app(config.SettingsStore(s), client_factory=lambda st: fc, persist=False))


def _lab_id(c):
    return next(l["id"] for l in c.get("/api/labs").json()["labs"] if l["nodes"] <= 4) if isinstance(
        c.get("/api/labs").json(), dict) else next(l["id"] for l in c.get("/api/labs").json() if l["nodes"] <= 4)


def test_precheck_endpoint_fits_and_nofit():
    fc = FakeClient(total_gb=64, free_gb=60)
    c = _app(fc)
    lab = _lab_id(c)
    d = c.get(f"/api/labs/{lab}/precheck").json()
    assert d["enabled"] and d["verdict"]["level"] == "fits" and d["snapshot"]["total_gb"] == 64
    fc.stats["all"]["memory"]["free"] = 1 * GIB
    _running(fc, "CML-hog", 4, "nxosv9000")
    d = c.get(f"/api/labs/{lab}/precheck").json()       # always fresh
    assert d["verdict"]["level"] == "nofit"
    assert d["snapshot"]["labs"][0]["title"] == "CML-hog"


def test_precheck_off_and_unconfigured():
    c = _app(FakeClient(), resource_check=False)
    lab = _lab_id(c)
    assert c.get(f"/api/labs/{lab}/precheck").json() == {"configured": True, "enabled": False}
    c2 = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False))
    assert c2.get(f"/api/labs/{lab}/precheck").json()["configured"] is False
    assert c2.get("/api/resources").json()["configured"] is False


def test_precheck_connection_failure_is_graceful():
    def boom(st):
        raise ConnectionError("cml.example: connection refused")
    s = config.Settings(cml_url="https://cml.example", username="u", password="secretpw")
    c = TestClient(create_app(config.SettingsStore(s), client_factory=boom, persist=False))
    lab = _lab_id(c)
    r = c.get(f"/api/labs/{lab}/precheck")
    assert r.status_code == 200
    d = r.json()
    assert d["verdict"]["level"] == "unknown" and "connection refused" in d["snapshot"]["errors"][0]


def test_resources_endpoint_cached():
    fc = FakeClient()
    calls = []
    orig = fc.get_system_stats
    fc.get_system_stats = lambda: calls.append(1) or orig()
    c = _app(fc, resource_headroom_gb=6)
    a = c.get("/api/resources").json()
    b = c.get("/api/resources").json()
    assert not a["cached"] and b["cached"] and len(calls) == 1 and a["headroom_gb"] == 6
    assert not c.get("/api/resources?fresh=true").json()["cached"] and len(calls) == 2


def test_stop_endpoint_needs_confirm_and_runs_job():
    fc = FakeClient()
    other = _running(fc, "colleague", 2)
    c = _app(fc)
    assert c.post(f"/api/cml/labs/{other.id}/stop", json={}).status_code == 400
    job = c.post(f"/api/cml/labs/{other.id}/stop", json={"confirm": True}).json()["job_id"]
    for _ in range(100):
        j = c.get(f"/api/jobs/{job}").json()
        if j["state"] != "running":
            break
        time.sleep(0.02)
    assert j["state"] == "done" and other.calls[-1] == "stop"
    job = c.post(f"/api/cml/labs/{other.id}/stop", json={"confirm": True, "wipe": True}).json()["job_id"]
    for _ in range(100):
        j = c.get(f"/api/jobs/{job}").json()
        if j["state"] != "running":
            break
        time.sleep(0.02)
    assert j["state"] == "error" and "refusing to wipe" in j["error"]


def test_settings_roundtrip_headroom():
    c = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False))
    r = c.post("/api/settings", json={"resource_headroom_gb": 8.5, "resource_check": False})
    assert r.status_code == 200 and r.json()["resource_headroom_gb"] == 8.5 and r.json()["resource_check"] is False
    assert c.post("/api/settings", json={"resource_headroom_gb": -1}).status_code == 400
    assert config.from_env({"CMLLAB_RESOURCE_HEADROOM_GB": "2", "CMLLAB_RESOURCE_CHECK": "0",
                            "CMLLAB_SETTINGS_FILE": "/nonexistent/x.json", "CMLLAB_USE_KEYRING": "0"}).resource_headroom_gb == 2


def test_ui_has_precheck_and_fit_tags():
    js = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False)).get("/static/app.js").text
    for s in ("renderPrecheck", "/precheck", "fit-slot", "libFitTags", "stopCmlLab", "Build anyway"):
        assert s in js
