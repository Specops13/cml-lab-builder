"""Library lab 20-evpn-vxlan-superspine: BGP EVPN VXLAN across two DCs joined by super spines (5-stage Clos),
NX-OS 9000v leaves with IOL spines/super spines (examples/20-evpn-vxlan-superspine)."""
import hashlib
import json
import re
from pathlib import Path

from cmllab import courses, packs, sizing
from cmllab.console import config_script

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "examples" / "20-evpn-vxlan-superspine"
LAB_ID = "20-evpn-vxlan-superspine"
LEAVES = ("DC1-LEAF1", "DC1-LEAF2", "DC2-LEAF1", "DC2-LEAF2")


def _lab():
    return packs.parse_lab_text(packs.read_dir(SRC).lab_yaml)[0]


def test_shape_platform_ram_and_license():
    lab = _lab()
    assert lab.id == LAB_ID and lab.is_walkthrough and not lab.checks and not lab.faults
    assert lab.platforms == ["iol"] and lab.node_count == 12 <= 20      # CML 20-node license
    assert {n.name for n in lab.nodes} == {"SS1", "SS2", "DC1-SPINE", "DC2-SPINE", *LEAVES, "H1", "H2", "H3", "H4"}
    assert {n.name for n in lab.nodes if n.definition == "nxosv9000"} == set(LEAVES)
    assert [s.id for s in lab.steps] == ["fabric", "underlay", "bgp-evpn", "vlan-vni", "nve", "extend-vlans", "l3vni-irb"]
    assert lab.step("l3vni-irb").optional and not any(s.optional for s in lab.steps[:-1])
    est = sizing.estimate(lab, "iol")
    assert est["gb"] == 56.0 and est["heavy"] and est["gb"] <= 90      # 4 x nxosv9000 (12) + 8 x iol-xe (1)
    assert lab.solution_summary.strip() and "Multi-Site" in lab.solution_summary


def test_five_stage_roles_super_spines_reflect_spines_transit():
    lab = _lab()
    sol = lab.step_solution()
    for ss in ("SS1", "SS2"):
        for leaf in ("111", "112", "121", "122"):
            assert f"neighbor 10.0.0.{leaf} route-reflector-client" in sol[ss]
        assert "address-family l2vpn evpn" in sol[ss] and "interface nve" not in sol[ss]
    for sp in ("DC1-SPINE", "DC2-SPINE"):                                # pure IP transit
        assert "router bgp" not in sol[sp] and "ip ospf 1 area 0" in sol[sp]
    for leaf in LEAVES:
        s = sol[leaf]
        for must in ("feature nv overlay", "feature vn-segment-vlan-based", "nv overlay evpn", "neighbor 10.0.0.1\n",
                     "neighbor 10.0.0.2\n", "send-community extended", "vn-segment 10010", "vn-segment 10020",
                     "vni 10010 l2", "host-reachability protocol bgp", "source-interface loopback1",
                     "ingress-replication protocol bgp", "member vni 50001 associate-vrf",
                     "fabric forwarding mode anycast-gateway"):
            assert must in s, (leaf, must)
        assert "route-reflector-client" not in s
    cmds = {c.command for s in lab.steps for c in s.checks} | {v.command for s in lab.steps for v in s.verify}
    for must in ("show nve peers", "show nve vni", "show bgp l2vpn evpn route-type 2", "show bgp l2vpn evpn route-type 3",
                 "show bgp l2vpn evpn summary", "ping 192.168.10.13", "ping 192.168.20.14", "show ip route vrf TENANT1"):
        assert must in cmds, must
    # the cross-DC proof: DC1-LEAF1 sees both DC2 VTEPs and learns H3's MAC behind DC2-LEAF1's VTEP
    peers = next(c for c in lab.step("nve").checks if c.id == "nve-dc1-leaf1-peers")
    assert any("10\\.0\\.1\\.121" in m for m in peers.match) and any("10\\.0\\.1\\.122" in m for m in peers.match)
    mac = next(c for c in lab.step("extend-vlans").checks if c.id == "l2-dc1-leaf1-mac")
    assert any("nve1\\(10\\.0\\.1\\.121\\)" in m for m in mac.match)


def test_lint_solved_100_blank_not_and_published():
    pack = packs.read_dir(SRC)
    rep = packs.lint(pack, strict=True)
    assert rep.ok, rep.errors
    assert {(r["mode"], r["solution_pct"]) for r in rep.results} == {("config", 100.0), ("live", 100.0)}
    assert all(r["blank_pct"] < 100 for r in rep.results)
    for folder, ext in (("library", "cmllab"), ("labs", "encorlab")):
        f = ROOT / folder / f"{LAB_ID}.{ext}"
        assert f.read_bytes() == courses.deterministic_pack(SRC)
        item = next(i for i in json.loads((ROOT / folder / "index.json").read_text())["items"] if i["id"] == LAB_ID)
        assert item["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest() and item["type"] == "walkthrough"
        assert item["ram_gb"] == 56.0 and item["nodes"] == 12


def test_apply_scripts_ios_rr_and_nxos_vtep():
    lab = _lab()
    rr = config_script(lab.step("bgp-evpn").config["SS1"])
    i = rr.index("address-family l2vpn evpn")
    assert rr[i + 1] == "neighbor 10.0.0.111 activate" and "exit-address-family" not in rr
    nve = config_script(lab.step("nve").config["DC2-LEAF1"], "nxos")
    assert nve[:4] == ["interface nve1", "no shutdown", "host-reachability protocol bgp", "source-interface loopback1"]
    j = nve.index("member vni 10010")
    assert nve[j + 1:j + 3] == ["ingress-replication protocol bgp", "exit"]
    leaf = config_script(lab.step("underlay").config["DC1-LEAF1"], "nxos")
    assert leaf[0] == "feature ospf" and "ip router ospf UNDERLAY area 0.0.0.0" in leaf
    assert not any(re.search(r"Ethernet0/", l) for l in leaf)          # NX-OS names only on the leaves
