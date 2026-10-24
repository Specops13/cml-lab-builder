"""Library labs 21-23, the NX-OS study path (OSPF -> BGP -> BGP EVPN VXLAN): six Nexus 9000v in a 5-stage Clos
(SS1/SS2 super spines, one spine and one leaf per pod) plus four IOL hosts, same topology in all three labs.
Each lab is its own CML lab; lab N boots with lab N-1's day-0 plus lab N-1's required steps (no drift)."""
import hashlib
import subprocess
import sys
import json
import re
from pathlib import Path

import pytest

from cmllab import courses, packs, sizing
from cmllab.console import config_script

ROOT = Path(__file__).resolve().parents[1]
SERIES = ["21-nxos-ospf-multiarea", "22-nxos-bgp-over-ospf", "23-nxos-evpn-vxlan"]
NXOS = {"SS1", "SS2", "P1-SPINE", "P2-SPINE", "P1-LEAF", "P2-LEAF"}
HOSTS = {"H1", "H2", "H3", "H4"}


def _lab(lab_id):
    return packs.parse_lab_text(packs.read_dir(ROOT / "examples" / lab_id).lab_yaml)[0]


@pytest.mark.parametrize("lab_id", SERIES)
def test_shape_topology_and_ram(lab_id):
    lab = _lab(lab_id)
    assert lab.id == lab_id and lab.is_walkthrough and not lab.checks and not lab.faults and not lab.solution
    assert {n.name for n in lab.nodes} == NXOS | HOSTS and lab.node_count == 10 <= 20     # CML 20-node license
    assert {n.name for n in lab.nodes if n.definition == "nxosv9000"} == NXOS
    est = sizing.estimate(lab, "iol")
    assert est["gb"] == 76.0 == lab.ram_gb and est["heavy"] and est["gb"] <= 90         # 6 x 12 GB + 4 x 1 GB
    assert len(lab.steps) >= 10 and lab.solution_summary.strip()
    assert "starts from its own baseline" in lab.steps[0].explain                      # never reuses an earlier lab
    first = _lab(SERIES[0])                                                             # same cabling in all three
    assert sorted(map(str, lab.links)) == sorted(map(str, first.links))
    for st in lab.steps:                                                                # depth: every step inspects
        assert st.verify, st.id
        assert len(st.explain) > 600, st.id


@pytest.mark.parametrize("lab_id", SERIES)
def test_lint_solved_100_blank_not_and_published(lab_id):
    src = ROOT / "examples" / lab_id
    rep = packs.lint(packs.read_dir(src), strict=True)
    assert rep.ok, rep.errors
    assert {(r["mode"], r["solution_pct"]) for r in rep.results} == {("config", 100.0), ("live", 100.0)}
    assert all(r["blank_pct"] < 100 for r in rep.results)
    for folder, ext in (("library", "cmllab"), ("labs", "encorlab")):
        f = ROOT / folder / f"{lab_id}.{ext}"
        assert f.read_bytes() == courses.deterministic_pack(src)
        item = next(i for i in json.loads((ROOT / folder / "index.json").read_text())["items"] if i["id"] == lab_id)
        assert item["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest() and item["type"] == "walkthrough"
        assert item["ram_gb"] == 76.0 and item["nodes"] == 10


@pytest.mark.parametrize("lab_id", SERIES)
def test_every_step_applies_as_an_nxos_console_script(lab_id):
    lab = _lab(lab_id)
    for st in lab.steps:
        for dev, text in st.config.items():
            assert dev in NXOS, (st.id, dev)
            script = config_script(text, "nxos")
            assert script and not any(l.startswith(" ") for l in script), (st.id, dev)
            assert not re.search(r"Ethernet0/|GigabitEthernet", text), (st.id, dev)


def test_lab21_ospf_design():
    lab = _lab("21-nxos-ospf-multiarea")
    assert [s.id for s in lab.steps] == ["design", "links", "area0", "lsdb-area0", "interfaces", "pods", "summarize",
                                         "nssa", "stub", "spf", "vtep-path", "break-fix"]
    assert lab.step("break-fix").optional and not lab.step("break-fix").config
    sol = lab.step_solution()
    for ss in ("SS1", "SS2"):
        assert sol[ss].count("ip router ospf UNDERLAY area 0.0.0.0") == 4 and "area 0.0.0.1" not in sol[ss]
    assert "ip ospf priority 100" in sol["SS1"]
    assert "ip router ospf UNDERLAY area 0.0.0.1" in sol["P1-SPINE"] and "area 0.0.0.1 range 10.1.0.0/16" in sol["P1-SPINE"]
    assert "area 0.0.0.1 nssa default-information-originate" in sol["P1-SPINE"]
    assert "area 0.0.0.2 range 10.2.0.0/16" in sol["P2-SPINE"] and "area 0.0.0.2 stub" in sol["P2-SPINE"]
    assert "redistribute direct route-map RM-EXT" in sol["P1-LEAF"] and "area 0.0.0.1 nssa\n" in sol["P1-LEAF"]
    assert "area 0.0.0.2 stub" in sol["P2-LEAF"] and "no-summary" not in sol["P2-LEAF"] + sol["P2-SPINE"]
    for n in NXOS:
        assert sol[n].count("mtu 9216") == sol[n].count("no switchport") >= 1, n
    text = "\n".join(s.explain for s in lab.steps)
    for must in ("debug logfile", "debug-filter", "undebug all", "event-history adjacency", "show debug logfile"):
        assert must in text, must
    cmds = {c.command for s in lab.steps for c in s.checks} | {v.command for s in lab.steps for v in s.verify}
    for must in ("show ip ospf database nssa-external", "show ip ospf database external", "show ip ospf database summary",
                 "show ip ospf database asbr-summary", "show ip ospf event-history adjacency", "show ip ospf"):
        assert must in cmds, must


def _strip(cfg):
    return [l.rstrip() for l in cfg.splitlines() if l.strip() and not l.lstrip().startswith("!")]


@pytest.mark.parametrize("prev_id,lab_id", list(zip(SERIES, SERIES[1:])))
def test_baseline_is_previous_baseline_plus_its_required_steps(prev_id, lab_id):
    """Skippable labs, no drift: lab N boots with lab N-1's day-0 + lab N-1's required (non-optional) steps."""
    prev, lab = _lab(prev_id), _lab(lab_id)
    sol = prev.step_solution(include_optional=False)
    for node in lab.nodes:
        before = next(n for n in prev.nodes if n.name == node.name)
        if node.name in HOSTS:
            assert node.config == before.config, node.name
        else:
            assert _strip(node.config) == _strip(before.config) + _strip(sol[node.name]), node.name
            assert node.config.startswith(f"! Lab {lab_id[:2]} baseline"), node.name
    r = subprocess.run([sys.executable, str(ROOT / "packaging" / "nxos_study_baseline.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_lab22_bgp_design():
    lab = _lab("22-nxos-bgp-over-ospf")
    assert [s.id for s in lab.steps] == ["baseline", "rr", "leaf-peering", "transport", "advertise", "bestpath",
                                         "bgp-free-core", "policy", "ebgp", "bfd", "convergence", "wrap-up"]
    assert lab.step("policy").optional and lab.step("bfd").optional and not lab.step("bfd").config
    assert not lab.step("ebgp").config and not lab.step("baseline").config
    for n in NXOS:                                                                  # inherited lab 21 underlay
        assert "router ospf UNDERLAY" in lab.node(n).config and "router bgp" not in lab.node(n).config, n
    sol = lab.step_solution()
    for ss in ("SS1", "SS2"):
        assert "router bgp 65000" in sol[ss] and "route-reflector-client" in sol[ss]
        for peer in ("10.0.0.11", "10.0.0.21", "10.1.0.111", "10.2.0.121"):
            assert f"neighbor {peer}" in sol[ss], (ss, peer)
    for leaf in ("P1-LEAF", "P2-LEAF"):
        assert "update-source loopback0" in sol[leaf] and "route-reflector-client" not in sol[leaf]
        assert "neighbor 10.0.0.1" in sol[leaf] and "neighbor 10.0.0.2" in sol[leaf]
    assert "set local-preference 200" in sol["P1-LEAF"] and "set community 65000:200" in sol["P2-LEAF"]
    text = "\n".join(s.explain for s in lab.steps)
    for must in ("debug logfile", "debug-filter", "undebug all", "event-history", "show debug logfile", "BFD"):
        assert must in text, must
    cmds = {c.command for s in lab.steps for c in s.checks} | {v.command for s in lab.steps for v in s.verify}
    for must in ("show bgp ipv4 unicast summary", "show bgp ipv4 unicast 172.16.2.0/24", "show ip route 172.16.2.0/24"):
        assert must in cmds, must


def test_lab23_evpn_vxlan_design():
    lab = _lab("23-nxos-evpn-vxlan")
    assert [s.id for s in lab.steps] == ["baseline", "design", "features", "evpn-af", "vni", "nve", "access", "l2-test",
                                         "bum", "l3vni", "anycast-gw", "irb", "type5", "suppress-arp", "troubleshoot",
                                         "wrap-up"]
    for st in ("suppress-arp", "troubleshoot"):
        assert lab.step(st).optional and not lab.step(st).config and not lab.step(st).checks, st
    for n in NXOS:                                                                  # inherited labs 21 + 22
        cfg = lab.node(n).config
        assert "router ospf UNDERLAY" in cfg and "router bgp 65000" in cfg and "evpn" not in cfg, n
    assert "set local-preference" not in lab.node("P1-LEAF").config                 # lab 22's optional policy: not carried
    sol = lab.step_solution()
    for spine in ("P1-SPINE", "P2-SPINE"):                                          # pure underlay transit
        assert spine not in sol, spine
    for ss in ("SS1", "SS2"):
        assert "nv overlay evpn" in sol[ss] and sol[ss].count("route-reflector-client") == 2
        assert "nve" not in sol[ss].replace("nv overlay evpn", "") and "vn-segment" not in sol[ss]
    for leaf, vtep in (("P1-LEAF", "loopback1"), ("P2-LEAF", "loopback1")):
        s = sol[leaf]
        for must in ("feature nv overlay", "feature vn-segment-vlan-based", "vn-segment 10010", "vn-segment 10020",
                     "vn-segment 50001", f"source-interface {vtep}", "host-reachability protocol bgp",
                     "ingress-replication protocol bgp", "member vni 50001 associate-vrf",
                     "fabric forwarding anycast-gateway-mac 2020.0000.00aa", "fabric forwarding mode anycast-gateway",
                     "route-target both auto evpn", "redistribute direct route-map PERMIT-ALL",
                     "spanning-tree port type edge"):
            assert must in s, (leaf, must)
        assert "mcast-group" not in s and "suppress-arp" not in s
    text = "\n".join(s.explain for s in lab.steps)
    for must in ("debug logfile", "debug-filter", "undebug all", "ethanalyzer", "mcast-group", "ip pim",
                 "Route type", "symmetric", "suppress-arp", "show debug logfile"):
        assert must in text, must
    cmds = {c.command for s in lab.steps for c in s.checks} | {v.command for s in lab.steps for v in s.verify}
    for must in ("show nve peers", "show nve vni", "show bgp l2vpn evpn route-type 2", "show bgp l2vpn evpn route-type 3",
                 "show bgp l2vpn evpn route-type 5", "show l2route evpn mac all", "show nve vni ingress-replication"):
        assert must in cmds, must
