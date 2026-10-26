"""Resource pre-check before Build (3.3.0, cmllab/resources.py) against a mocked CML."""
import time

import pytest
from fastapi.testclient import TestClient

from cmllab import config, resources
from cmllab.web.app import create_app
from fakes import GIB, FakeClient, FakeLicensing
from tables import run_table


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


VERDICT_LEVELS_ROWS = [(10, "fits"), (30, "fits"), (31, "tight"), (40, "nofit")]


def _verdict_levels(need, level):
    snap = {"available_gb": 34.0, "labs": [], "running_nodes": 0}
    v = resources.verdict(snap, need, 4, headroom_gb=4)
    assert v["level"] == level
    assert v["margin_gb"] == round(34 - need, 1)
    assert bool(v["reasons"]) == (level != "fits")


def test_verdict_levels():
    run_table(_verdict_levels, VERDICT_LEVELS_ROWS)


def test_headroom_is_configurable():
    snap = {"available_gb": 20.0, "labs": [], "running_nodes": 0}
    assert resources.verdict(snap, 14, 2, headroom_gb=4)["level"] == "fits"
    assert resources.verdict(snap, 14, 2, headroom_gb=8)["level"] == "tight"
    assert resources.verdict(snap, 14, 2, headroom_gb=0)["level"] == "fits"


def test_license_and_node_limit():
    snap = {"available_gb": 100.0, "labs": [], "running_nodes": 15, "license": {"max": 20, "in_use": 15, "known": True}}
    v = resources.verdict(snap, 4, 6, node_limit=50)
    assert v["level"] == "nofit" and "Node licenses" in v["reasons"][0] and v["failed"] == ["nodes"]
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


def test_license_parsing_cases():
    def _license_parsing():
        fc = FakeClient()
        fc.licensing = FakeLicensing({"features": [{"name": "CML - Personal Edition", "description": "20 nodes",
                                                    "in_use": 1, "max": 1}]})
        lic = resources.snapshot(fc)["license"]
        assert (lic["max"], lic["in_use"], lic["known"]) == (20, 0, True)

    def _dylans_server_20_node_license_is_not_1_of_1():
        """The 3.3.0 bug: features summed -> "1 of 1 licensed nodes in use" and "won't fit" for every lab."""
        fc = FakeClient()
        fc.stats = cml29_system_stats(total_gib=90, memfree_gib=70, used_gib=12)
        fc.licensing = FakeLicensing(cml29_licensing())
        _running(fc, "colleague", 4, "iol-xe")
        sw = _running(fc, "switchy", 1, "unmanaged_switch")      # never uses a license
        assert sw
        s = resources.snapshot(fc)
        lic = s["license"]
        assert (lic["max"], lic["in_use"], lic["known"]) == (20, 4, True)
        assert lic["source"] == "licensing+labs" and lic["product"] == "CML_Enterprise"
        v = resources.verdict(s, 76, 10, headroom_gb=4)
        assert v["node_check"]["level"] == "fits" and v["failed"] == []
        assert not any("1 of 1" in r for r in v["reasons"])

    def _license_status_without_min_max_still_gives_20():
        fc = FakeClient()
        fc.licensing = FakeLicensing(cml29_licensing(with_minmax=False))
        assert resources.snapshot(fc)["license"]["max"] == 20

    def _expansion_nodes_add_their_chosen_count_not_the_300_maximum():
        fc = FakeClient()
        fc.licensing = FakeLicensing(cml29_licensing(expansion=50))
        assert resources.snapshot(fc)["license"]["max"] == 70

    def _capacity_from_product_when_features_do_not_say():
        run_table(_capacity_from_product_when_features_do_not_say_row, CAPACITY_FROM_PRODUCT_WHEN_FEATURES_DO_NOT_SAY_ROWS)

    def _screenshot_personal_user_quota_1_is_not_a_node_limit():
        """3.3.1 said "Won't fit ... your resource pool allows 1 nodes and 0 are running" for lab 21 (10 nodes, 76 GB)."""
        s = resources.snapshot(_dylan())
        assert (s["license"]["max"], s["license"]["in_use"], s["license"]["product"]) == (20, 0, "CML_Personal")
        assert s["pool"]["assigned"] is False and s["pool"]["max"] is None
        v = resources.verdict(s, 76, 10, headroom_gb=4)
        assert v["level"] == "fits" and v["failed"] == [] and v["reasons"] == []
        assert v["node_check"] == {"level": "fits", "reason": "", "note": "", "in_use": 0, "max": 20, "need": 10}
        assert "user_max" not in s["license"]

    def _personal_without_diagnostics_is_20_and_personal_plus_40():
        fc = _dylan()
        fc.diagnostics = None
        assert resources.snapshot(fc)["license"]["max"] == 20
        st = cml29_personal()
        st["product_license"]["active"] = "CML_PersonalPlus"
        assert resources._license_capacity(st)[0] == 40

    for case in (_license_parsing, _dylans_server_20_node_license_is_not_1_of_1, _license_status_without_min_max_still_gives_20, _expansion_nodes_add_their_chosen_count_not_the_300_maximum, _capacity_from_product_when_features_do_not_say, _screenshot_personal_user_quota_1_is_not_a_node_limit, _personal_without_diagnostics_is_20_and_personal_plus_40):
        case()


def test_memory_parsing():
    def _memory_from_computes_when_no_all():
        stats = {"computes": {"a": {"stats": {"memory": {"total": 32 * GIB, "free": 10 * GIB}}},
                              "b": {"stats": {"memory": {"total": 32 * GIB, "free": 20 * GIB}}}}}
        assert resources._memory(stats) == (64.0, 30.0)
        assert resources._memory({}) == (None, None)

    def _node_ram_units():
        assert resources._gb(2048, "mib") == 2.0
        assert resources._gb(2 * GIB, "mib") == 2.0      # some client versions report bytes
        assert resources._gb(None) is None

    def _page_cache_counts_as_free_memory():
        """MemFree leaves out the page cache; CML reclaims it when a node starts. 3.3.0 read only MemFree."""
        assert resources._memory(cml29_system_stats(total_gib=90, memfree_gib=6, used_gib=10)) == (90.0, 80.0)

    def _memory_in_kib_is_recognised():
        assert resources._memory(cml29_system_stats(total_gib=90, memfree_gib=60, used_gib=20, unit=1024 ** 2)) == (90.0, 70.0)

    def _memory_without_used_keeps_free():
        assert resources._memory({"all": {"memory": {"total": 64 * GIB, "free": 20 * GIB}}}) == (64.0, 20.0)

    for case in (_memory_from_computes_when_no_all, _node_ram_units, _page_cache_counts_as_free_memory, _memory_in_kib_is_recognised, _memory_without_used_keeps_free):
        case()


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
    fc.stats["all"]["memory"].update(free=1 * GIB, used=63 * GIB)
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


# ------------------------------------------------------------------ 3.3.1: CML 2.9 licensing + system_stats shapes
# Shapes from the CML 2.9 API schema (simple_webserver.schemas.licensing / diagnostics / system) and the virl2_client
# docs; ids, accounts and hostnames redacted. Not captured from a live server.
def _feature(fid, name, desc, in_use, mx, with_minmax=True):
    f = {"id": f"regid.2019-10.com.cisco.{fid},1.0_00000000-0000-4000-a000-000000000000", "name": name,
         "description": desc, "in_use": in_use, "status": "IN_COMPLIANCE", "version": "1.0"}
    if with_minmax:
        f.update(min=0, max=mx)
    return f


def cml29_licensing(expansion=0, product="CML_Enterprise", with_minmax=True):
    """GET /api/v0/licensing on a registered CML 2.9 Enterprise server: the base license with 20 nodes included
    (in_use 1 of max 1, the "1 of 1" 3.3.0 showed) plus the Expansion Nodes feature (in_use = expansion count)."""
    return {
        "udi": {"hostname": "cml-controller", "product_uuid": "00000000-0000-4000-a000-000000000000"},
        "registration": {"status": "COMPLETED", "smart_account": "REDACTED", "virtual_account": "REDACTED",
                         "expires": "2027-06-10T20:17:39+00:00"},
        "authorization": {"status": "IN_COMPLIANCE", "expires": "2026-12-23T16:39:07+00:00"},
        "reservation_mode": False,
        "features": [
            _feature("CML_ENT_BASE", "CML - Enterprise License",
                     "Cisco Modeling Labs - Enterprise License with 20 nodes capacity included", 1, 1, with_minmax),
            _feature("CML_NODE_COUNT", "CML \u2013 Expansion Nodes",
                     "Cisco Modeling Labs - Expansion node capacity for CML Enterprise Servers", expansion, 300, with_minmax),
        ],
        "product_license": {"active": product, "is_enterprise": product == "CML_Enterprise"},
        "transport": {"ssms": "https://smartreceiver.cisco.com/licservice/license", "proxy": {"server": None, "port": None},
                      "default_ssms": "https://smartreceiver.cisco.com/licservice/license"},
    }


def cml29_system_stats(total_gib=90, memfree_gib=6, used_gib=10, unit=GIB):
    """GET /api/v0/system_stats, one all-in-one host: bytes; "free" is MemFree (page cache not included)."""
    mem = {"total": int(total_gib * unit), "free": int(memfree_gib * unit), "used": int(used_gib * unit)}
    host = {"cpu": {"count": 16, "percent": 3.5}, "memory": mem, "disk": {"used": 120 * GIB, "free": 380 * GIB, "total": 500 * GIB}}
    return {"computes": {"6f5c1d2e-0000-4000-a000-000000000001": {
                "hostname": "cml-controller", "is_controller": True,
                "stats": dict(host, cpu={"count": 16, "percent": 3.5, "model": "Intel Xeon", "predicted": 16,
                                         "load": [0.4, 0.5, 0.6], "hyperthreading": True},
                              dominfo={"allocated_cpus": 12, "allocated_memory": 75497472, "total_nodes": 7,
                                       "total_orphans": 0, "running_nodes": 7, "running_orphans": 0})}},
            "all": host, "controller": {"disk": {"used": 120 * GIB, "free": 380 * GIB, "total": 500 * GIB}}}


def test_diagnostics_licensing_wins_for_nodes_in_use():
    fc = FakeClient()
    fc.licensing = FakeLicensing(cml29_licensing())
    fc.diagnostics = {"quota": 20, "started": 17, "user_quota": None, "user_started": 17}
    _running(fc, "x", 2)
    lic = resources.snapshot(fc)["license"]
    assert (lic["max"], lic["in_use"], lic["source"]) == (20, 17, "diagnostics")
    v = resources.verdict({"available_gb": 80.0, "labs": [], "running_nodes": 2, "license": lic}, 10, 6)
    assert v["level"] == "nofit" and v["failed"] == ["nodes"] and v["ram"]["level"] == "fits"
    assert v["reasons"] == ["Node licenses: needs 6, but 17 of 20 are in use (3 free)."]


def test_diagnostics_error_body_falls_back():
    fc = FakeClient()
    fc.licensing = FakeLicensing(cml29_licensing())
    fc.diagnostics = {"error": "Failed to fetch licensing diagnostics"}
    assert resources.snapshot(fc)["license"]["source"] == "licensing+labs"


def test_resource_pools():
    def _resource_pool_node_limit():
        lic = {"max": 100, "in_use": 10, "known": True}
        pool = {"assigned": True, "label": "students", "max": 12, "in_use": 10}
        v = resources.verdict({"available_gb": 80.0, "labs": [], "running_nodes": 10, "license": lic, "pool": pool}, 4, 3)
        assert v["failed"] == ["nodes"] and "resource pool 'students' allows 12 nodes" in v["reasons"][0]
        assert v["node_check"]["pool"] == {"label": "students", "max": 12, "in_use": 10}

    def _assigned_pool_with_null_licenses_is_unlimited():
        fc = _dylan({"admin": False, "resource_pool": "pool-1"},
                    {"id": "pool-1", "label": "lab users", "limit": {"licenses": None, "ram": None, "cpus": None,
                                                                    "disk_space": None, "external_connectors": None},
                     "usage": {"licenses": 4, "ram": 8192, "cpus": 400, "disk_space": 0, "external_connectors": []}})
        s = resources.snapshot(fc)
        assert s["pool"]["assigned"] is True and s["pool"]["max"] is None
        assert resources.verdict(s, 10, 10)["node_check"]["level"] == "fits"

    def _assigned_pool_with_a_node_limit_blocks():
        fc = _dylan({"admin": False, "resource_pool": "pool-1"},
                    {"id": "pool-1", "label": "lab users", "limit": {"licenses": 8}, "usage": {"licenses": 2}})
        s = resources.snapshot(fc)
        assert (s["pool"]["max"], s["pool"]["in_use"]) == (8, 2)
        v = resources.verdict(s, 10, 10)
        assert v["failed"] == ["nodes"] and "allows 8 nodes and 2 are in use; this lab needs 10" in v["reasons"][0]

    def _pool_that_cannot_be_read_never_blocks():
        fc = _dylan({"admin": False, "resource_pool": "pool-9"})     # usage GET fails
        s = resources.snapshot(fc)
        assert s["pool"]["assigned"] is True and s["pool"]["max"] is None and s["pool"]["error"]
        assert resources.verdict(s, 10, 10)["level"] == "fits"

    for case in (_resource_pool_node_limit, _assigned_pool_with_null_licenses_is_unlimited, _assigned_pool_with_a_node_limit_blocks, _pool_that_cannot_be_read_never_blocks):
        case()


CAPACITY_FROM_PRODUCT_WHEN_FEATURES_DO_NOT_SAY_ROWS = [("CML_Personal", 20), ("CML_Personal40", 40), ("CML_Enterprise", 20)]


def _capacity_from_product_when_features_do_not_say_row(product, cap):
    status = {"features": [{"id": "regid.x,1.0_y", "name": "CML - License", "in_use": 1, "max": 1}],
              "product_license": {"active": product}}
    assert resources._license_capacity(status)[0] == cap


def test_ambiguous_license_means_cant_tell_for_nodes_not_wont_fit():
    fc = FakeClient()
    fc.licensing = FakeLicensing({"features": [{"id": "regid.x,1.0_y", "name": "CML - Education", "in_use": 1, "max": 1}],
                                  "product_license": {"active": "CML_Education"}})
    s = resources.snapshot(fc)
    assert s["license"]["known"] is False and s["license"]["max"] is None
    v = resources.verdict(s, 10, 10)
    assert v["level"] == "fits" and v["node_check"]["level"] == "unknown" and "can't tell" in v["node_check"]["note"]


def test_non_admin_no_license_is_cant_tell():
    fc = FakeClient()
    fc.licensing = FakeLicensing(error=PermissionError("403"))
    s = resources.snapshot(fc)
    assert s["license"] is None
    v = resources.verdict(s, 10, 10)
    assert v["level"] == "fits" and v["node_check"]["level"] == "unknown" and v["reasons"] == []


def test_ram_failure_is_named_as_memory():
    v = resources.verdict({"available_gb": 50.0, "labs": [], "running_nodes": 0,
                           "license": {"max": 20, "in_use": 0, "known": True}}, 76, 10)
    assert v["failed"] == ["memory"] and v["node_check"]["level"] == "fits" and v["reasons"][0].startswith("Memory:")


def test_dylans_lab21_fits_on_90_gb():
    """Lab 21 (6 x nxosv9000 at 12 GB + 4 x iol-xe at 1 GB = 76 GB, 10 nodes) on an idle 90 GB / 20-node server."""
    fc = FakeClient()
    fc.stats = cml29_system_stats(total_gib=90, memfree_gib=9, used_gib=6)
    fc.licensing = FakeLicensing(cml29_licensing())
    s = resources.snapshot(fc)
    v = resources.verdict(s, 76, 10, headroom_gb=4)
    assert s["available_gb"] == 84.0 and v["level"] == "fits" and v["failed"] == []


def test_licensed_nodes_skip_unmanaged_switch_and_external_connector():
    from types import SimpleNamespace as NS
    lab = NS(platforms=["iol"], node_count=4, nodes=[NS(definition=d, kind="router") for d in
                                                     ("iol-xe", "iol-xe", "unmanaged_switch", "external_connector")])
    assert resources.licensed_nodes(lab, "iol") == 2


# ------------------------------------------------------------------ 3.3.2: Dylan's CML 2.9.1 Personal server
class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url):
        self.calls.append(url)
        if url not in self.routes:
            raise RuntimeError(f"404 {url}")
        return _Resp(self.routes[url])


class _Users:
    def __init__(self, user):
        self.user = user

    def user_id(self, username):
        return "00000000-0000-4000-a000-0000000000aa"

    def get_user(self, uid):
        return self.user


def cml29_personal():
    """GET /licensing on a CML 2.9.1 Personal server (shape per the 2.9 schema; ids redacted)."""
    return {"udi": {"hostname": "cml-controller", "product_uuid": "00000000-0000-4000-a000-000000000000"},
            "registration": {"status": "COMPLETED", "smart_account": "REDACTED", "virtual_account": "REDACTED"},
            "authorization": {"status": "IN_COMPLIANCE"}, "reservation_mode": False,
            "features": [{"id": "regid.2019-10.com.cisco.CML_PERS,1.0_00000000-0000-4000-a000-000000000001",
                          "name": "CML - Personal License", "description": "Cisco Modeling Labs - Personal",
                          "in_use": 1, "status": "IN_COMPLIANCE", "version": "1.0"}],
            "product_license": {"active": "CML_Personal", "is_enterprise": False},
            "transport": {"ssms": "https://smartreceiver.cisco.com/licservice/license"}}


def _dylan(user=None, pool_usage=None):
    fc = FakeClient()
    fc.stats = cml29_system_stats(total_gib=125, memfree_gib=97, used_gib=28)
    fc.licensing = FakeLicensing(cml29_personal())
    # what his server answered: user_quota 1 / user_started 0 is NOT a node limit
    fc.diagnostics = {"quota": 20, "started": 0, "user_quota": 1, "user_started": 0}
    fc.username = "admin"
    fc.user_management = _Users(user if user is not None else {"username": "admin", "admin": True, "resource_pool": None})
    fc._session = _Session({"resource_pool_usage/pool-1": pool_usage} if pool_usage else {})
    return fc


def test_debug_dump_is_redacted_and_has_the_raw_data():
    import json
    from cmllab import config
    fc = _dylan()
    fc.stats["computes"]["6f5c1d2e-0000-4000-a000-000000000001"]["stats"]["note"] = "mgmt 192.168.11.96 token=abc123"
    d = resources.debug_dump(fc)
    text = json.dumps(d)
    assert d["cml"]["diagnostics_licensing"]["licensing"]["user_quota"] == 1
    assert d["cml"]["licensing"]["product_license"]["active"] == "CML_Personal"
    assert d["cml"]["licensing"]["udi"] == "***" and d["cml"]["licensing"]["registration"]["smart_account"] == "***"
    assert "192.168.11.96" not in text and "abc123" not in text and "cml-controller" not in text
    assert "00000000-0000-4000-a000" not in text and "smartreceiver" not in text
    assert d["app_view"]["license"]["max"] == 20 and d["app_version"]


def test_resource_diagnostics_endpoint_and_cli(monkeypatch, tmp_path):
    fc = _dylan()
    c = _app(fc)
    d = c.get("/api/resources/debug").json()
    assert d["configured"] and d["dump"]["cml"]["system_stats"]
    from typer.testing import CliRunner
    from cmllab import cli, service

    class _C:
        client = fc
    monkeypatch.setattr(service, "make_cml", lambda s, *a, **k: _C())
    monkeypatch.setattr(cli, "_settings", lambda: config.Settings(cml_url="https://x", username="u", password="p"))
    out = tmp_path / "diag.json"
    r = CliRunner().invoke(cli.app, ["resource-diagnostics", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert '"CML_Personal"' in out.read_text()
