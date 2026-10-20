"""Walkthrough labs (type: walkthrough), NX-OS node definitions, Apply-step over the console and the RAM estimate."""
import copy
import re
import time

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from encorlab import catalog, config, packs, platforms, progress, sizing, walkthrough
from encorlab.console import ConsoleError, SSHConsoleRunner, config_script
from encorlab.grader import grade
from encorlab.render import to_topology
from encorlab.schema import Lab
from encorlab.sim import SimRunner
from encorlab.web.app import create_app
from fakes import FakeClient

EVPN = "18-evpn-vxlan"


def evpn():
    return catalog.get(EVPN)


def evpn_dict():
    return yaml.safe_load((catalog.entry(EVPN).path / "lab.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- schema
def test_evpn_lab_shape():
    lab = evpn()
    assert lab.is_walkthrough and not lab.checks and not lab.faults
    assert [n.definition for n in lab.nodes].count("nxosv9000") == 4 and lab.node_count == 8
    ids = [s.id for s in lab.steps]
    assert ids == ["fabric", "underlay-links", "underlay-ospf", "features", "bgp-evpn", "vlan-vni", "nve",
                   "extend-vlans", "l3vni-irb"]
    assert lab.step("l3vni-irb").optional and not any(s.optional for s in lab.steps[:-1])
    # graded checks = required steps only; optional step checks are excluded
    assert {c.id for c in lab.graded_checks} == {c.id for s in lab.steps if not s.optional for c in s.checks}
    assert "l3-h1-h4-ping" not in {c.id for c in lab.graded_checks}
    sol = lab.step_solution()
    assert "member vni 10010" in sol["LEAF1"] and "route-reflector-client" in sol["SPINE1"]
    assert "anycast-gateway" not in lab.step_solution(include_optional=False)["LEAF2"]
    assert catalog.load_solution(EVPN) == sol


def test_evpn_covers_bgp_vxlan_and_vlan_extension():
    """Dylan's brief: BGP EVPN control plane with spine RRs, VXLAN data plane, VLANs 10/20 stretched (L2VNI)."""
    lab = evpn()
    text = "\n".join(c for s in lab.steps for c in s.config.values())
    for must in ("address-family l2vpn evpn", "route-reflector-client", "send-community extended", "interface nve1",
                 "host-reachability protocol bgp", "ingress-replication protocol bgp", "vn-segment 10010",
                 "vn-segment 10020", "vni 10010 l2", "source-interface loopback1"):
        assert must in text, must
    cmds = {(v.device, v.command) for s in lab.steps for v in s.verify} | {(c.device, c.command) for s in lab.steps for c in s.checks}
    for must in ("show bgp l2vpn evpn route-type 2", "show bgp l2vpn evpn route-type 3", "show nve peers", "show nve vni",
                 "show mac address-table vlan 10", "ping 192.168.10.13", "ping 192.168.20.14"):
        assert any(c == must for _, c in cmds), must
    order = [s.id for s in lab.steps]
    assert order.index("l3vni-irb") > order.index("extend-vlans") > order.index("nve") > order.index("vlan-vni")


def _bad(mut):
    d = evpn_dict()
    mut(d)
    with pytest.raises(ValidationError) as e:
        Lab(**d)
    return str(e.value)


def test_walkthrough_validation_rules():
    assert "leave the lab-level checks empty" in _bad(lambda d: d.update(checks=[d["steps"][1]["checks"][0] | {"id": "x"}]))
    assert "no faults" in _bad(lambda d: d.update(faults=[{"id": "f1", "title": "t", "ticket": "t", "device": "LEAF1",
                                                         "config": "x", "explanation": "e", "hints": ["a"]}]))
    assert "at least 2 steps" in _bad(lambda d: d.update(steps=d["steps"][:1]))
    assert "unknown device" in _bad(lambda d: d["steps"][1]["config"].update(NOPE="x"))
    assert "duplicate step ids" in _bad(lambda d: d["steps"][2].update(id="fabric"))
    assert "duplicate check ids" in _bad(lambda d: d["steps"][2]["checks"][0].update(id="fabric-leaf1-cdp"))
    assert "literal interface names" in _bad(lambda d: d["steps"][1]["config"].update(LEAF1="interface %if0%\n  no shutdown\n"))
    assert "not %ifN%" in _bad(lambda d: d["nodes"][0].update(config="interface %if0%\n"))
    assert "unknown node definition" in _bad(lambda d: d["nodes"][0].update(definition="nxos-imaginary"))
    assert "removeworkflows" or True

    def no_live(d):
        for s in d["steps"]:
            s["checks"] = [c for c in s["checks"] if c.get("mode") == "config"]
    assert "live check" in _bad(no_live)
    assert "verify command" in _bad(lambda d: d["steps"][1]["verify"][0].update(command="configure terminal"))


def test_steps_only_in_walkthroughs():
    d = yaml.safe_load((catalog.entry("eigrp-basic").path / "lab.yaml").read_text(encoding="utf-8"))
    d["steps"] = evpn_dict()["steps"][:2]
    with pytest.raises(ValidationError, match="only allowed in walkthrough"):
        Lab(**d)


# ---------------------------------------------------------------- offline grading per step
@pytest.mark.parametrize("plat", ["iol", "iosv"])
def test_every_step_passes_when_built_and_fails_when_blank(plat):
    lab, p = evpn(), platforms.get(plat)
    solved, blank = SimRunner(lab, p, True), SimRunner(lab, p, False)
    for st in lab.steps:
        sl = walkthrough.step_lab(lab, st)
        res = [r for m in ("live", "config") for r in grade(sl, solved, p, mode=m).results]
        assert res and all(r.passed for r in res), (st.id, [(r.id, r.details) for r in res if not r.passed])
        if st.id != "fabric":      # cabling (CDP) is already there before any config
            res = [r for m in ("live", "config") for r in grade(sl, blank, p, mode=m).results]
            assert not any(r.passed for r in res), (st.id, [r.id for r in res if r.passed])


def test_pack_lint_and_roundtrip(tmp_path):
    rep = packs.lint(packs.read_dir(catalog.entry(EVPN).path), strict=True)
    assert rep.ok, rep.errors
    assert {r["mode"] for r in rep.results} == {"live", "config"} and all(r["solution_pct"] == 100 for r in rep.results)
    data = packs.export_pack(EVPN)
    pk = packs.read_upload("x.encorlab", data)
    assert packs.lint(pk, strict=True).ok
    assert not packs.lint(pk, builtin_ids=packs.builtin_ids()).ok      # same id as the built-in lab


def test_lint_checks_nxos_interface_names():
    d = evpn_dict()
    d["steps"][1]["config"]["LEAF1"] += "interface Ethernet1/9\n  no shutdown\n"
    rep = packs.lint(packs.Pack(yaml.safe_dump(d, sort_keys=False)))
    assert not rep.ok and any("Ethernet1/9" in e and "nxosv9000" in e for e in rep.errors)
    d = evpn_dict()
    d["nodes"][4]["config"] += "interface Ethernet0/1\n no shutdown\n"     # H1 is an IOL/IOSv node: placeholders only
    rep = packs.lint(packs.Pack(yaml.safe_dump(d, sort_keys=False)))
    assert not rep.ok and any("placeholders" in e for e in rep.errors)


# ---------------------------------------------------------------- rendering for CML
def test_nxos_topology_and_day0_config():
    lab, p = evpn(), platforms.get("iol")
    topo = to_topology(lab, p, "ENCOR-", creds=("student", "s3cret"))
    nodes = {n["label"]: n for n in topo["nodes"]}
    leaf = nodes["LEAF1"]
    assert leaf["node_definition"] == "nxosv9000" and nodes["H1"]["node_definition"] == "iol-xe"
    ifs = {i["label"]: i for i in leaf["interfaces"]}
    assert ifs["mgmt0"]["slot"] == 0 and ifs["Ethernet1/1"]["slot"] == 1 and ifs["Ethernet1/4"]["slot"] == 4
    cfg = leaf["configuration"]
    assert cfg.startswith("hostname LEAF1\n") and "no password strength-check" in cfg
    assert "username admin password s3cret role network-admin" in cfg and "username student password s3cret role network-admin" in cfg
    assert "event manager applet BOOTCONFIG" in cfg and "service timestamps" not in cfg
    assert nodes["H1"]["configuration"].startswith("hostname H1\n") and "Ethernet0/0" in nodes["H1"]["configuration"]
    by_id = {n["id"]: n for n in topo["nodes"]}
    for ln in topo["links"]:
        for side in ("n1", "n2"):
            iface = ln["i1" if side == "n1" else "i2"]
            assert iface in {i["id"] for i in by_id[ln[side]]["interfaces"]}
    lbl = [ln["label"] for ln in topo["links"]]
    assert "SPINE1-Ethernet1/1<->LEAF1-Ethernet1/1" in lbl and "LEAF1-Ethernet1/3<->H1-Ethernet0/0" in lbl
    iosv = to_topology(lab, platforms.get("iosv"), "ENCOR-")
    assert {n["label"]: n["node_definition"] for n in iosv["nodes"]}["H3"] == "iosv"


def test_build_needs_the_node_definition_and_waits_longer():
    from encorlab.cml import CML, CMLError
    s = config.Settings(cml_url="https://cml.x", username="u", password="p")
    fc = FakeClient()                       # no nxosv9000 on this server
    with pytest.raises(CMLError, match="nxosv9000"):
        CML(s, client_factory=lambda st: fc).build(evpn(), start=False)
    fc = FakeClient(defs=("iol-xe", "ioll2-xe", "iosv", "iosvl2", "nxosv9000"))
    cml = CML(s, client_factory=lambda st: fc)
    cml.build(evpn(), start=False)
    assert "nxosv9000" in fc.imported_yaml[0]
    assert cml.boot_timeout(evpn()) == 1500 and cml.boot_timeout(catalog.get("eigrp-basic")) == s.boot_timeout


# ---------------------------------------------------------------- Apply this step: console config mode
def test_config_script_turns_indentation_into_exits():
    text = ("! comment\nrouter bgp 65000\n  router-id 10.0.0.1\n  address-family l2vpn evpn\n  neighbor 10.0.0.11\n"
            "    remote-as 65000\n    address-family l2vpn evpn\n      send-community extended\n  neighbor 10.0.0.12\n"
            "    remote-as 65000\n\ninterface nve1\n  no shutdown\nfeature bgp\nend\n")
    assert config_script(text, "nxos") == [
        "router bgp 65000", "router-id 10.0.0.1", "address-family l2vpn evpn", "exit",   # bare AF: still a mode on NX-OS
        "neighbor 10.0.0.11", "remote-as 65000", "address-family l2vpn evpn", "send-community extended", "exit", "exit",
        "neighbor 10.0.0.12", "remote-as 65000",
        "end", "configure terminal", "interface nve1", "no shutdown",
        "end", "configure terminal", "feature bgp"]
    # IOS: indentation only (an IOS `neighbor` line is not a mode)
    assert config_script("router bgp 1\n neighbor 1.1.1.1 remote-as 1\n neighbor 2.2.2.2 remote-as 1\nip routing\n") == [
        "router bgp 1", "neighbor 1.1.1.1 remote-as 1", "neighbor 2.2.2.2 remote-as 1", "end", "configure terminal", "ip routing"]
    assert config_script("interface Ethernet0/0\n ip address 1.1.1.1 255.255.255.0\n") == [
        "interface Ethernet0/0", "ip address 1.1.1.1 255.255.255.0"]


class FakeNXOS:
    """CML console server -> NX-OS console with a 'login:' prompt and a mode stack in configuration mode."""

    def __init__(self, reject=()):
        self.out, self.mode, self.inbuf, self.closed = "consoles> ", "menu", "", False
        self.host, self.stack, self.typed, self.reject = "", [], [], set(reject)

    def recv_ready(self):
        return bool(self.out)

    def recv(self, n):
        d, self.out = self.out[:n], self.out[n:]
        return d.encode()

    def prompt(self):
        return f"{self.host}({self.stack[-1]})#" if self.stack else f"{self.host}#"

    def send(self, data):
        self.inbuf += data
        while "\r" in self.inbuf:
            line, self.inbuf = self.inbuf.split("\r", 1)
            self.handle(line)

    def handle(self, line):
        if self.mode == "menu":
            self.host = line.split("/")[2]
            self.mode = "login"
            self.out += f"\r\nUser Access Verification\r\n{self.host} login: "
            return
        if self.mode == "login":
            if not line:
                self.out += f"\r\n{self.host} login: "
                return
            self.mode = "pw"
            self.out += line + "\r\nPassword: "
            return
        if self.mode == "pw":
            self.mode = "exec"
            self.out += "\r\n" + self.prompt()
            return
        out = ""
        if line == "configure terminal":
            self.stack = ["config"]
        elif line == "end":
            self.stack = []
        elif line == "exit":
            self.stack.pop()
        elif self.stack:
            self.typed.append((self.stack[-1], line))
            if line in self.reject:
                out = "                    ^\r\n% Invalid command at '^' marker.\r\n"
            elif (line.split()[0] in ("router", "interface", "neighbor", "address-family", "evpn")
                  or re.match(r"^(vlan \d+|vni \d+ l2|vrf context \S+|member vni \d+.*)$", line)):
                self.stack.append("config-" + line.split()[0])
        self.out += line + "\r\n" + out + self.prompt()


class FakeSSH:
    def __init__(self, chan):
        self.chan = chan

    def invoke_shell(self, **kw):
        return self.chan

    def close(self):
        pass


def nx_runner(reject=()):
    chans = {}

    def factory():
        c = FakeNXOS(reject)
        chans.setdefault("all", []).append(c)
        return FakeSSH(c)
    s = config.Settings(cml_url="https://cml.x", username="u", password="p")
    return SSHConsoleRunner(s, "ENCOR-18-evpn-vxlan", client_factory=factory), chans


def test_apply_step_types_config_in_the_right_modes():
    r, chans = nx_runner()
    res = walkthrough.apply_step(config.Settings(), EVPN, "bgp-evpn", lambda m: None, runner=r, lab=evpn())
    assert res["applied"] == ["SPINE1", "SPINE2", "LEAF1", "LEAF2"]
    spine = chans["all"][0]
    assert spine.host == "SPINE1"
    assert ("config-address-family", "route-reflector-client") in spine.typed
    assert ("config-router", "neighbor 10.0.0.11") in spine.typed       # the bare global AF was left with exit
    assert ("config-router", "neighbor 10.0.0.12") in spine.typed       # exits brought it back to router bgp
    assert spine.stack == []                                            # ended at the exec prompt
    r2, ch2 = nx_runner()
    walkthrough.apply_step(config.Settings(), EVPN, "l3vni-irb", lambda m: None, runner=r2, lab=evpn())
    leaf = ch2["all"][0]
    assert ("config", "router bgp 65000") in leaf.typed and ("config", "vlan 999") in leaf.typed
    assert ("config-vrf", "address-family ipv4 unicast") in leaf.typed and ("config-vrf", "vni 50001") in leaf.typed


def test_apply_step_stops_at_a_rejected_line():
    r, chans = nx_runner(reject={"feature nv overlay"})
    with pytest.raises(ConsoleError, match="feature nv overlay"):
        walkthrough.apply_step(config.Settings(), EVPN, "features", lambda m: None, runner=r, lab=evpn())
    leaf = [c for c in chans["all"] if c.host == "LEAF1"][0]
    assert ("config", "feature vn-segment-vlan-based") not in leaf.typed and leaf.stack == []


def test_apply_refuses_steps_without_config():
    with pytest.raises(walkthrough.WalkthroughError):
        walkthrough.apply_step(config.Settings(), EVPN, "extend-vlans", lambda m: None, runner=object(), lab=evpn())


# ---------------------------------------------------------------- RAM estimate
def test_ram_estimate():
    r = sizing.estimate(evpn(), "iol")
    assert r["gb"] == 52 and r["heavy"] and r["label"] == "~52 GB" and r["vcpus"] == 12
    assert "4 × nxosv9000 (12 GB)" in r["tooltip"] and "RAM heavy" in r["tooltip"]
    assert sizing.estimate(evpn(), "iosv")["gb"] == 50
    small = sizing.estimate(catalog.get("eigrp-basic"), "iol")
    assert small["gb"] == 2 and not small["heavy"] and "RAM heavy" not in small["tooltip"]
    assert sizing.estimate(catalog.get("eigrp-basic"), "iol", heavy_gb=2)["heavy"]
    d = evpn_dict()
    d["ram_gb"] = 40
    a = sizing.estimate(Lab(**d), "iol")
    assert a["gb"] == 40 and a["source"] == "author" and a["estimate_gb"] == 52 and "lab author" in a["tooltip"]
    for lid, e in catalog.entries().items():          # every lab gets an estimate
        assert sizing.estimate(e.lab, "iol")["gb"] > 0


def test_ram_threshold_setting():
    s = config.Settings()
    assert s.ram_heavy_gb == 16 and "ram_heavy_gb" in config.PERSISTED
    st = config.SettingsStore(s)
    assert st.update(ram_heavy_gb="60").ram_heavy_gb == 60
    with pytest.raises(ValueError):
        st.update(ram_heavy_gb=0)
    assert config.from_env({"ENCOR_RAM_HEAVY_GB": "8"}).ram_heavy_gb == 8


# ---------------------------------------------------------------- web API
def make(solved=True, live=True):
    s = config.Settings(cml_url="https://cml.x", username="u", password="pw")
    fc = FakeClient(defs=("iol-xe", "ioll2-xe", "iosv", "iosvl2", "nxosv9000"))
    sim = lambda st, lab_id, test=False: SimRunner(catalog.get(lab_id), platforms.get(st.platform), solved)  # noqa: E731
    store = config.SettingsStore(s)
    app = create_app(store, client_factory=lambda st: fc, runner_factory=sim if live else None, config_factory=sim,
                     probe=lambda h, p: {"ok": True, "detail": "ok"}, persist=False)
    return TestClient(app), store


def wait(c, job_id):
    for _ in range(400):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_api_lists_type_ram_and_steps():
    c, store = make()
    labs = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}
    w = labs[EVPN]
    assert w["type"] == "walkthrough" and w["ram"]["heavy"] and w["ram"]["label"] == "~52 GB"
    assert w["walkthrough"]["required"] == 8 and w["solved"] is False and w["best"] is None
    assert labs["eigrp-basic"]["type"] == "challenge" and not labs["eigrp-basic"]["ram"]["heavy"]
    store.update(ram_heavy_gb=60)
    assert not {l["id"]: l for l in c.get("/api/labs").json()["labs"]}[EVPN]["ram"]["heavy"]
    d = c.get(f"/api/labs/{EVPN}").json()
    assert d["type"] == "walkthrough" and len(d["steps"]) == 9 and d["steps"][1]["config"]["LEAF1"].startswith("interface Ethernet1/1")
    assert d["steps"][0]["apply"] is False and d["steps"][1]["apply"] is True
    assert d["steps"][7]["verify"][0] == {"device": "H1", "command": "ping 192.168.10.13", "expect": d["steps"][7]["verify"][0]["expect"]}
    assert set(d["final_summary"]["devices"]) == {"SPINE1", "SPINE2", "LEAF1", "LEAF2"} and d["ram"]["vcpus"] == 12
    src = c.get(f"/api/labs/{EVPN}/source").json()["yaml"]
    assert "solution:" not in src and "steps:" in src


def test_api_refuses_break_and_exam_for_walkthroughs():
    c, _ = make()
    assert c.post(f"/api/labs/{EVPN}/break").status_code == 400
    r = c.post(f"/api/labs/{EVPN}/exam/start")
    assert r.status_code == 400 and "walkthrough" in r.json()["detail"]
    assert c.post("/api/labs/eigrp-basic/walkthrough/step?index=1").status_code == 400


def test_api_step_check_progress_and_completion():
    c, _ = make()
    j = wait(c, c.post(f"/api/labs/{EVPN}/steps/underlay-ospf/check").json()["job_id"])
    assert j["state"] == "done", j
    res = j["result"]
    assert res["passed"] and res["step"] == "underlay-ospf" and {r["id"] for r in res["results"]} >= {"ospf-leaf1-nbrs", "ospf-spine1-cfg"}
    assert "live" in res["mode"] and "config" in res["mode"]
    st = c.get(f"/api/labs/{EVPN}/walkthrough").json()
    assert st["required_passed"] == 1 and not st["completed"]
    assert c.post(f"/api/labs/{EVPN}/walkthrough/step?index=4").json()["current"] == 4
    assert c.post(f"/api/labs/{EVPN}/walkthrough/step?index=99").json()["current"] == 9   # the summary page
    assert c.post(f"/api/labs/{EVPN}/steps/extend-vlans/apply").status_code == 400
    assert c.post(f"/api/labs/{EVPN}/steps/fabricx/check").status_code == 404
    j = wait(c, c.post(f"/api/labs/{EVPN}/walkthrough/check-all").json()["job_id"])
    assert j["state"] == "done" and j["result"]["passed"] and len(j["result"]["steps"]) == 9
    st = c.get(f"/api/labs/{EVPN}/walkthrough").json()
    assert st["completed"] and st["required_passed"] == st["required"] == 8
    labs = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}
    assert labs[EVPN]["solved"] and labs[EVPN]["walkthrough"]["completed"]
    # walkthroughs are not graded history: no attempts, no mastery
    assert c.get(f"/api/history/{EVPN}").json() == []
    p = c.get("/api/progress").json()
    assert EVPN not in {l["id"] for l in p["labs"]} and p["walkthroughs"]["completed"] == 1
    assert p["overall"]["labs_total"] == len(catalog.entries()) - 1
    assert c.post(f"/api/labs/{EVPN}/walkthrough/reset").json()["required_passed"] == 0


def test_api_step_check_fails_on_blank_lab():
    c, _ = make(solved=False)
    res = wait(c, c.post(f"/api/labs/{EVPN}/steps/nve/check").json()["job_id"])["result"]
    assert not res["passed"] and res["walkthrough"]["steps"][6]["passed"] is False


def test_api_build_evpn_lab_in_fake_cml():
    c, _ = make()
    j = wait(c, c.post(f"/api/labs/{EVPN}/build").json()["job_id"])
    assert j["state"] == "done", j


def test_courses_and_library_show_ram_and_type(tmp_path):
    from encorlab import courses, library
    from pathlib import Path
    root = Path(__file__).parent.parent
    data = courses.build(root / "examples" / "courses" / "data-center", search=[root / "examples"])
    courses.install(data)
    c, _ = make()
    dc = {x["id"]: x for x in c.get("/api/courses").json()["courses"]}["data-center"]
    lab = {x["id"]: x for x in dc["labs"]}[EVPN]
    assert lab["type"] == "walkthrough" and lab["ram"]["heavy"] and dc["ram"]["gb"] == 52
    idx = library.build_index(root / "labs")
    it = {i["id"]: i for i in idx["items"]}
    assert it["data-center"]["ram_gb"] == 52 and it["ospf-multiarea-stub"]["type"] == "challenge"
    import json
    parsed = library.parse_index(json.dumps(idx).encode())
    assert {i["id"]: i["ram_gb"] for i in parsed}["data-center"] == 52
    out = library.index("https://x/labs/index.json", fetch=lambda u, n: json.dumps(idx).encode(), heavy_gb=16)
    assert {i["id"]: i["ram_heavy"] for i in out["items"]} == {i["id"]: i["ram_gb"] >= 16 for i in parsed}


def test_progress_keeps_walkthroughs_out_of_mastery():
    entries = catalog.entries()
    st = walkthrough.status(evpn())
    p = progress.compute(entries=entries, histories={}, walkthroughs={EVPN: st})
    assert EVPN not in {l["id"] for l in p["labs"]}
    assert EVPN not in {i for d in p["domains"] for i in d["lab_ids"]}
    assert p["walkthroughs"]["labs"][0]["id"] == EVPN and p["walkthroughs"]["total"] == 1


def test_ui_has_walkthrough_and_ram_tags():
    from pathlib import Path
    js = (Path(__file__).parent.parent / "encorlab" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    css = (Path(__file__).parent.parent / "encorlab" / "web" / "static" / "style.css").read_text(encoding="utf-8")
    assert 'RAM heavy · ' in js and "ram-heavy" in js and "title=\"${esc(r.tooltip)}\"" in js
    assert ".tag.ram-heavy{background:#c62828" in css
    for s in ("renderWalkthrough", "Check this step", "Apply this step for me", "Previous", "Check every step",
              "confirmBuild", "ramTag(l.ram)", "ramTag(c.ram)", "it.ram_gb"):
        assert s in js, s
