"""'Break my lab' fault injection: IOS-style merge, built-in faults, service, API and pack lint."""
import random

import pytest
import yaml
from fastapi.testclient import TestClient

from cmllab import catalog, config, faults, history, packs, platforms, service
from cmllab.iosmerge import merge
from cmllab.schema import Lab
from cmllab.sim import SimRunner
from cmllab.web.app import create_app

from fakes import FakeClient

P = platforms.get("iol")


# ---------------------------------------------------------------- merge
def test_merge_replaces_singletons_and_removes_with_no():
    out = merge("interface E0/0\n ip address 1.1.1.1 255.0.0.0\n no shutdown\n standby 10 priority 110\n"
                "router eigrp 1\n network 10.0.0.0\n network 1.0.0.0\n",
                "interface E0/0\n shutdown\n ip address 2.2.2.2 255.0.0.0\n standby 10 priority 90\n"
                "router eigrp 1\n no network 10.0.0.0\nno ip domain lookup\n")
    assert out == ("interface E0/0\n ip address 2.2.2.2 255.0.0.0\n shutdown\n standby 10 priority 90\n"
                   "router eigrp 1\n network 1.0.0.0\nno ip domain lookup\n")


def test_merge_nested_and_block_removal():
    start = ("router eigrp X\n address-family ipv4 unicast autonomous-system 100\n  af-interface default\n"
             "   authentication mode md5\n  exit-af-interface\n  network 10.0.12.0 0.0.0.255\n  eigrp stub connected\n"
             " exit-address-family\nrouter ospf 1\n router-id 1.1.1.1\n")
    out = merge(start, "router eigrp X\n address-family ipv4 unicast autonomous-system 100\n  no eigrp stub connected\n"
                       "no router ospf 1\n")
    assert "eigrp stub" not in out and "router ospf" not in out and "  network 10.0.12.0 0.0.0.255" in out
    assert "   authentication mode md5" in out


def test_merge_isakmp_key_per_peer_and_secondary_ip():
    out = merge("crypto isakmp key A address 1.1.1.1\ncrypto isakmp key B address 2.2.2.2\n"
                "interface E0/0\n ip address 1.1.1.1 255.0.0.0\n",
                "crypto isakmp key C address 1.1.1.1\ninterface E0/0\n ip address 9.9.9.9 255.0.0.0 secondary\n")
    assert "key A" not in out and "key C address 1.1.1.1" in out and "key B address 2.2.2.2" in out
    assert " ip address 1.1.1.1 255.0.0.0" in out and "secondary" in out


# ---------------------------------------------------------------- built-in faults
BUILTIN = [lid for lid, e in catalog.entries().items() if e.source == "builtin" and not e.lab.is_walkthrough]  # walkthroughs have no faults


@pytest.mark.parametrize("lab_id", BUILTIN)
def test_every_builtin_lab_has_faults_that_are_detected_and_fixable(lab_id):
    lab = catalog.get(lab_id)
    assert len(lab.faults) >= 3, "each built-in lab ships at least 3 faults"
    sol = catalog.load_solution(lab_id)
    for plat in lab.platforms:
        assert faults.validate(lab, sol, platforms.get(plat)) == []
    for f in lab.faults:
        assert f.hints and f.ticket.strip() and "**" in f.explanation
        assert f.id not in f.ticket and "Fix" not in f.ticket   # tickets describe symptoms only


def test_pick_avoids_recent_faults():
    lab = catalog.get("06-hsrp")
    seen = []
    for i in range(len(lab.faults)):
        f = faults.pick(lab, rng=random.Random(i))
        faults.set_active(lab.id, f.id)
        seen.append(f.id)
    assert sorted(seen) == sorted(f.id for f in lab.faults)   # a full cycle without repeats
    with pytest.raises(faults.FaultError):
        faults.pick(lab, "nope")


def test_schema_rejects_bad_faults():
    data = yaml.safe_load((catalog.LABS_DIR / "eigrp-basic" / "lab.yaml").read_text(encoding="utf-8"))
    data["faults"] = [dict(data["faults"][0], device="R9"), dict(data["faults"][0])]
    data["faults"][1]["checks"] = [{"id": "r1-neighbor", "mode": "config", "device": "R1", "description": "x", "match": ["x"]}]
    with pytest.raises(ValueError) as e:
        Lab.model_validate(data)
    msg = str(e.value)
    assert "unknown device R9" in msg and "duplicate fault ids" in msg and "clashes with a lab check" in msg


# ---------------------------------------------------------------- service
class Src:
    def __init__(self, runner):
        self.r = runner

    def get_config(self, d):
        return self.r.get_config(d)


def _settings():
    return config.Settings(cml_url="https://cml.x", username="u", password="p", boot_timeout=60)


def test_break_check_fix_cycle_with_fake_cml():
    fc = FakeClient()
    lab = catalog.get("06-hsrp")
    sol = catalog.load_solution(lab.id)
    rep = service.do_break(_settings(), lab.id, lambda m: None, fault_id="r2-wrong-auth", client_factory=lambda s: fc)
    assert "Active" in rep["ticket"] and rep["faults_total"] == 3
    topo = yaml.safe_load(fc.imported_yaml[-1])
    r2 = next(n for n in topo["nodes"] if n["label"] == "R2")["configuration"]
    assert "standby 10 authentication md5 key-string ENC0R" in r2 and "standby 10 ip 192.168.10.254" in r2
    assert faults.active(lab.id)["fault_id"] == "r2-wrong-auth"

    f = faults.get(lab, "r2-wrong-auth")
    gl = faults.grading_lab(lab, f)
    broken = SimRunner(gl, P, True, solution=sol, fixtures={}, extra={"R2": f.config})
    d = service.do_check(_settings(), lab.id, lambda m: None, config_source=Src(broken), mode="config", hints_used=1)
    assert not d["passed"] and d["fault"] == "r2-wrong-auth" and "f-r2-cfg-auth" in [r["id"] for r in d["results"]]
    assert d["hints_total"] == len(f.hints) and "fault_fixed" not in d

    # reset during fault practice rebuilds the *broken* lab
    service.do_reset(_settings(), lab.id, lambda m: None, client_factory=lambda s: fc)
    node = fc.labs[-1].get_node_by_label("R2")
    assert "key-string ENC0R" in node.configuration

    fixed = SimRunner(gl, P, True, solution=sol, fixtures={}, extra={"_": ""})
    d = service.do_check(_settings(), lab.id, lambda m: None, config_source=Src(fixed), mode="config")
    assert d["passed"] and d["fault_fixed"]["id"] == "r2-wrong-auth" and "ENCOR" in d["fault_fixed"]["explanation"]
    assert "solution_summary" not in d
    assert faults.active(lab.id) is None
    assert history.load(lab.id)[-1]["fault"] == "r2-wrong-auth"


def test_test_live_ignores_fault_state():
    faults.set_active("eigrp-basic", "r2-wrong-as")
    lab = catalog.get("eigrp-basic")
    solved = SimRunner(lab, P, True)
    d = service.do_check(_settings(), lab.id, lambda m: None, config_source=Src(solved), mode="config",
                         fault_aware=False, record=False)
    assert d["passed"] and "fault" not in d and faults.active(lab.id)


# ---------------------------------------------------------------- web API
def test_api_fault_endpoints_hide_the_answer_until_revealed():
    c = TestClient(create_app(config.SettingsStore(_settings()), persist=False, client_factory=lambda s: FakeClient()))
    lab = c.get("/api/labs/eigrp-basic").json()
    assert lab["faults"] == 3 and lab["fault"] is None
    assert c.post("/api/labs/eigrp-basic/fault/reveal").status_code == 400
    faults.set_active("eigrp-basic", "r1-passive-link")
    lab = c.get("/api/labs/eigrp-basic").json()
    assert lab["fault"]["ticket"].startswith("The EIGRP neighborship")
    text = str(lab)
    assert "r1-passive-link" not in text and "passive-interface" not in text
    assert lab["hints"] == lab["fault"]["hints"]
    assert c.get("/api/labs").json()["labs"][0]["faults"] >= 3
    ans = c.post("/api/labs/eigrp-basic/fault/reveal").json()
    assert ans["id"] == "r1-passive-link" and "passive-interface" in ans["config"] and faults.active("eigrp-basic")["revealed"]
    assert c.post("/api/labs/eigrp-basic/break?fault=nope").status_code == 400
    assert c.post("/api/labs/eigrp-basic/fault/end").json()["ended"] and faults.active("eigrp-basic") is None


def test_api_break_runs_as_job():
    fc = FakeClient()
    c = TestClient(create_app(config.SettingsStore(_settings()), persist=False, client_factory=lambda s: fc))
    job = c.post("/api/labs/02-etherchannel/break").json()["job_id"]
    import time
    for _ in range(100):
        j = c.get(f"/api/jobs/{job}").json()
        if j["state"] != "running":
            break
        time.sleep(0.05)
    assert j["state"] == "done", j
    assert j["result"]["ticket"] and faults.active("02-etherchannel")


# ---------------------------------------------------------------- packs
def test_pack_lint_rejects_undetectable_fault():
    d = catalog.entry("eigrp-basic").path
    data = yaml.safe_load((d / "lab.yaml").read_text(encoding="utf-8"))
    data["id"] = "eigrp-faulty"
    data["faults"] = [{"id": "noop", "title": "x", "ticket": "Something is off.", "device": "R1",
                       "config": "interface Loopback0\n description harmless\n", "explanation": "**x**", "hints": ["x"]}]
    pk = packs.Pack(yaml.safe_dump(data, sort_keys=False), (d / "solution.cfg").read_text(encoding="utf-8"))
    rep = packs.lint(pk)
    assert not rep.ok and any("fault noop: no config check detects it" in e for e in rep.errors)
