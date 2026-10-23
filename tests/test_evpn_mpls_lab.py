"""Library lab 19-evpn-mpls: BGP EVPN over MPLS walkthrough on IOL (examples/19-evpn-mpls)."""
import hashlib
import json
from pathlib import Path

from cmllab import courses, packs, sizing
from cmllab.console import config_script

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "examples" / "19-evpn-mpls"
LAB_ID = "19-evpn-mpls"


def _lab():
    return packs.parse_lab_text(packs.read_dir(SRC).lab_yaml)[0]


def test_shape_platform_and_ram():
    lab = _lab()
    assert lab.id == LAB_ID and lab.is_walkthrough and not lab.checks and not lab.faults
    assert lab.platforms == ["iol"] and lab.node_count == 8
    assert {n.name for n in lab.nodes} == {"P1", "RR", "PE1", "PE2", "PE3", "CE1", "CE2", "CE3"}
    assert [s.id for s in lab.steps] == ["topology", "core-igp", "core-ldp", "bgp-evpn", "evi", "bridge-domains",
                                        "verify-l2", "vpws"]
    assert lab.step("vpws").optional and not any(s.optional for s in lab.steps[:-1])
    est = sizing.estimate(lab, "iol")
    assert est["gb"] == 8.0 and est["gb"] < 16      # 8 x iol-xe: not RAM heavy
    assert lab.solution_summary.strip()


def test_covers_core_bgp_evpn_and_vlan_extension():
    lab = _lab()
    text = "\n".join(c for s in lab.steps for c in s.config.values())
    for must in ("ip ospf 1 area 0", "mpls ldp router-id Loopback0 force", "mpls ip", "address-family l2vpn evpn",
                 "route-reflector-client", "send-community both", "replication-type ingress",
                 "l2vpn evpn instance 10 vlan-based", "l2vpn evpn instance 20 vlan-based", "service instance 10 ethernet",
                 "encapsulation dot1q 20", "member evpn-instance 10", "member evpn-instance 20",
                 "l2vpn evpn instance 100 point-to-point", "service target 3 source 1"):
        assert must in text, must
    cmds = {c.command for s in lab.steps for c in s.checks} | {v.command for s in lab.steps for v in s.verify}
    for must in ("show bgp l2vpn evpn summary", "show bgp l2vpn evpn route-type 2", "show bgp l2vpn evpn route-type 3",
                 "show l2vpn evpn mac", "show l2vpn evpn evi detail", "show bridge-domain 10", "show mpls ldp neighbor",
                 "ping 192.168.10.3", "ping 192.168.20.2"):
        assert must in cmds, must
    assert "router bgp" not in lab.step_solution()["P1"]      # BGP-free core


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
        assert item["ram_gb"] == 8.0 and item["nodes"] == 8


def test_apply_script_enters_and_leaves_service_instances():
    lines = config_script(_lab().step("bridge-domains").config["PE1"].replace("%if1%", "Ethernet0/1"))
    i = lines.index("service instance 10 ethernet")
    assert lines[i + 1] == "encapsulation dot1q 10" and lines[i + 2] == "exit"
    assert "member evpn-instance 20" in lines


def test_apply_scripts_have_no_exit_address_family_and_version_bumped():
    # "Apply this step" already sends `exit` when the indentation leaves a sub-mode, so a trailing
    # `exit-address-family` would reach the device in router mode, where IOS rejects it.
    lab = _lab()
    for step in lab.steps:
        for dev, cfg in step.config.items():
            assert "exit-address-family" not in config_script(cfg), (step.id, dev)
    rr = config_script(lab.step("bgp-evpn").config["RR"])
    assert rr[-1] == "neighbor 10.0.0.3 route-reflector-client"
    assert lab.version == "2"                       # installed copies show "Update available"
    for folder in ("library", "labs"):
        item = next(i for i in json.loads((ROOT / folder / "index.json").read_text())["items"] if i["id"] == LAB_ID)
        assert item["version"] == "2"
