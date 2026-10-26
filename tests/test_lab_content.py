"""Every library lab through ONE table-driven validator (3.3.5): adding a lab to labsrc/ or examples/ needs no new
test. For each lab (one test item per lab, run in parallel by pytest-xdist):

  * sources: strict lint (solution 100% in every mode/platform, blank start not solved, live fixtures), exam tags
    (known objectives, exams.yaml step ids exist, at least one tag), versioned like the published index
  * published: library/<id>.cmllab and labs/<id>.encorlab (2.0.x) are the deterministic pack of the source, and both
    index.json entries match (sha256, size, version, type, nodes, RAM, exam tags)
  * old apps: the pack's lab.yaml has no `exams:` key (the 2.x/3.3.4 schema forbids unknown keys; tags live in
    exams.yaml, which they skip)
  * IOL day-0 rule (the iol-xe node definition ignores a day-0 config without IP config on its Ethernet ports and
    stops at the setup dialog): every library lab gets IP config on at least one port; new labs on EVERY port
    (at least `no ip address`), with descriptions and shutdown on uncabled ports
  * challenges: Markdown solution summary and 2-4 hints, at least 3 faults (labsrc/) that are detected and fixable, the
    catalog grader path (sim) scores 100% solved and fails blank on every platform and mode
  * walkthroughs: every step's checks pass when built, every step config is a valid console script for its OS
    (no `exit-address-family`, NX-OS names on NX-OS nodes), a solution summary, checks only show/ping
  * SPECS[lab id]: optional facts specific to one lab (what it must teach), as plain functions

How to add a lab: put it in labsrc/<id>/ or examples/<id>/ with exams.yaml, run packaging/build_library.py. It is
picked up here automatically; add a SPECS entry only for lab-specific content you want pinned.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from cmllab import catalog, courses, faults, grader, objectives, packs, platforms, sim, sizing, solution, walkthrough
from cmllab.console import config_script
from cmllab.render import to_yaml

ROOT = Path(__file__).resolve().parents[1]
LAB_DIRS = sorted((d for base in ("labsrc", "examples") for d in (ROOT / base).iterdir() if (d / "lab.yaml").is_file()),
                  key=lambda d: d.name)
INDEX = {f: {i["id"]: i for i in json.loads((ROOT / f / "index.json").read_text())["items"]} for f in ("library", "labs")}
IOL_PORTS = [f"Ethernet0/{p}" for p in range(4)]
# library labs from before the strict day-0 audit (3.3.1): IP config on their cabled ports only (enough for IOL to
# accept the day-0 config). Every other lab, and every new one, must configure all four Ethernet ports.
DAY0_LOOSE = {"03-ospf-multiarea", "04-eigrp-named", "05-bgp-ebgp-ibgp", "06-hsrp", "07-acl-nat", "09-gre-ipsec",
              "10-ntp-syslog-snmp", "11-ipsla-tracking", "12-pbr", "13-redistribution", "14-multicast-pim-sm",
              "15-multicast-bsr-ssm", "16-mpls-ldp", "17-mpls-l3vpn", "18-evpn-vxlan", "eigrp-basic",
              "ospf-multiarea-stub", "troubleshoot-ospf-7node"}


def _stanza(cfg: str, ifname: str) -> str | None:
    m = re.search(rf"^interface {re.escape(ifname)}\n((?:[ \t].*\n)*)", cfg, re.M)
    return m.group(1) if m else None


def sent_nodes(lab, platform: str = "iol") -> dict:
    """{label: node} exactly as the builder imports the lab into CML (node "configuration" = day-0)."""
    return {n["label"]: n for n in yaml.safe_load(to_yaml(lab, platforms.get(platform), "CLB-"))["nodes"]}


def check_day0(lab, strict: bool) -> list[str]:
    bad = []
    if "iol" not in lab.platforms:
        return bad
    nodes = sent_nodes(lab)
    cabled = {(e.node, e.port) for ln in lab.links for e in (ln.a, ln.b)}
    for n in lab.nodes:
        node, cfg = nodes[n.name], nodes[n.name]["configuration"]
        if not (cfg.strip() and (f"hostname {n.name}\n" in cfg or f"\nhostname: {n.name}\n" in cfg)):   # IOS / cloud-init
            bad.append(f"{n.name}: no day-0 hostname")
        if "%if" in cfg:
            bad.append(f"{n.name}: unrendered placeholder")
        d = node["node_definition"]
        if d == "nxosv9000":
            if strict and not ("no ip domain-lookup" in cfg and "username admin password" in cfg):
                bad.append(f"{n.name}: NX-OS day-0 without domain-lookup off / admin user")
            for p in sorted(p for nm, p in cabled if nm == n.name):
                body = _stanza(cfg, f"Ethernet1/{p + 1}") or ""
                if strict and not ("description " in body and "no shutdown" in body):
                    bad.append(f"{n.name} Ethernet1/{p + 1}: cabled NX-OS port needs a description and `no shutdown`")
            continue
        if d != "iol-xe":                    # ioll2-xe: no IP config requirement, switchports
            continue
        ip = {p: (b := _stanza(cfg, p)) is not None and bool(re.search(r"^ (no )?ip address\b", b, re.M)) for p in IOL_PORTS}
        if not any(ip.values()):
            bad.append(f"{n.name}: no IP config on any Ethernet port, IOL would start the setup dialog")
        if strict:
            for p, ifname in enumerate(IOL_PORTS):
                body = _stanza(cfg, ifname) or ""
                want = "no shutdown" if (n.name, p) in cabled else "shutdown"
                if not ip[ifname] or " description " not in body or not re.search(rf"^ {want}$", body, re.M):
                    bad.append(f"{n.name} {ifname}: needs description, `ip address`/`no ip address` and `{want}`")
            if "no ip domain lookup" not in cfg:
                bad.append(f"{n.name}: no `no ip domain lookup`")
    return bad


@pytest.mark.parametrize("src", LAB_DIRS, ids=lambda d: d.name)
def test_library_lab(src: Path):
    pack = packs.read_dir(src)
    lab = packs.pack_lab(pack)
    assert lab.id == src.name
    # --- sources: strict lint (sim grading on every platform and mode) and exam tags
    rep = packs.lint(pack, strict=True)
    assert rep.ok, rep.errors
    assert rep.results and all(r["solution_pct"] == 100.0 for r in rep.results), rep.results
    assert all(r["blank_pct"] < 100 for r in rep.results), rep.results
    assert {r["mode"] for r in rep.results} == {"config", "live"}, "live checks need fixtures (fixture_solved.yaml)"
    assert not [w for w in rep.warnings if w.startswith("no exam objectives")]
    tags = objectives.lab_tags(lab)
    assert tags and not [t for t in tags if objectives.problem(t)]
    assert len(set(tags)) == len(tags) <= objectives.MAX_TAGS * (1 + len(lab.steps))
    # --- published packs and both indexes (library/ for 2.1+, labs/ .encorlab for 2.0.x)
    data = courses.deterministic_pack(src)
    assert b"exams.yaml" in data
    old = yaml.safe_load(packs.read_upload("x.cmllab", data).lab_yaml)
    assert "exams" not in old and not any("exams" in s for s in old.get("steps", [])), "older apps reject unknown keys"
    for folder, ext in (("library", "cmllab"), ("labs", "encorlab")):
        f = ROOT / folder / f"{lab.id}.{ext}"
        assert f.read_bytes() == data, f"{f} is stale: run python packaging/build_library.py"
        it = INDEX[folder][lab.id]
        assert it["sha256"] == hashlib.sha256(data).hexdigest() and it["size"] == len(data)
        assert it["version"] == lab.version and it["nodes"] == lab.node_count
        assert it["type"] == lab.type and it["exams"] == tags
        assert it["ram_gb"] == sizing.estimate(lab, lab.platforms[0])["gb"]
    # --- every node boots with its day-0 config on CML
    assert check_day0(lab, strict=lab.id not in DAY0_LOOSE) == []
    for plat in lab.platforms:
        nodes = sent_nodes(lab, plat)
        assert set(nodes) == {n.name for n in lab.nodes}
    # --- type rules
    sol = packs.solution_of(lab, pack)
    if lab.is_walkthrough:
        _walkthrough(lab, pack)
    else:
        _challenge(lab, sol)
    for c in lab.graded_checks + [c for st in lab.steps for c in st.checks]:
        assert c.mode == "config" or re.match(r"(show|ping) ", c.command or ""), (c.id, c.command)
    # --- what this lab must teach
    if lab.id in SPECS:
        SPECS[lab.id](lab)


def _challenge(lab, sol):
    e = catalog.entries().get(lab.id)
    builtin = bool(e and e.source == "builtin")
    s = lab.solution_summary
    assert "Why it works" in s or not builtin
    assert s.strip() and "```" in s and re.search(r"\*\*(Root cause|What was missing)", s)
    assert 2 <= len(lab.hints) <= 4 and all("```" not in h and len(h) < 300 for h in lab.hints)
    P = platforms.get("iol")
    text, auto = solution.summary(lab, sol, P)
    assert not auto and "%if" not in text
    assert len(lab.faults) >= (3 if builtin else 0), "each labsrc/ challenge ships at least 3 faults"
    for f in lab.faults:
        assert f.hints and f.ticket.strip() and "**" in f.explanation
        assert f.id not in f.ticket and "Fix" not in f.ticket         # tickets describe symptoms only
    for plat in lab.platforms:
        P = platforms.get(plat)
        assert faults.validate(lab, sol, P) == []
    if builtin:                           # the catalog path (files next to lab.yaml) grades like the pack
        for plat in lab.platforms:
            P = platforms.get(plat)
            for mode in ("live", "config"):
                ok = grader.grade(e.lab, sim.SimRunner(e.lab, P, solved=True), P, mode=mode)
                assert ok.passed and ok.score_pct == 100.0, (plat, mode, [r.id for r in ok.results if not r.passed])
                bad = grader.grade(e.lab, sim.SimRunner(e.lab, P, solved=False), P, mode=mode)
                assert not bad.passed and bad.score_pct < 50, (plat, mode)


def _walkthrough(lab, pack):
    assert lab.solution_summary.strip() and not lab.checks and not lab.faults
    nxos = {n.name for n in lab.nodes if n.definition == "nxosv9000"}
    for st in lab.steps:
        for dev, cfg in st.config.items():
            script = config_script(cfg, "nxos" if dev in nxos else "ios")
            assert script and "exit-address-family" not in script, (st.id, dev)
            if dev in nxos:
                assert not re.search(r"Ethernet0/|GigabitEthernet", cfg), (st.id, dev)
                assert not any(line.startswith(" ") for line in script), (st.id, dev)
    sol = lab.step_solution()
    for plat in lab.platforms:
        P = platforms.get(plat)
        solved = sim.SimRunner(lab, P, True, solution=sol, fixtures=pack.fixtures)
        for st in lab.steps:
            if not st.checks:
                continue
            sl = walkthrough.step_lab(lab, st)
            res = [r for m in ("live", "config") for r in grader.grade(sl, solved, P, mode=m).results]
            assert res and all(r.passed for r in res), (plat, st.id, [(r.id, r.details) for r in res if not r.passed])


def test_every_lab_is_published_and_tagged():
    ids = {d.name for d in LAB_DIRS}
    for folder in INDEX:
        assert {i for i, it in INDEX[folder].items() if it["kind"] == "lab"} == ids, folder
    assert len(ids) >= 26 and set(SPECS) <= ids
    cov = objectives.coverage([packs.pack_lab(packs.read_dir(d)) for d in LAB_DIRS])
    assert all(any(v for v in cov[e].values()) for e in cov), "every exam in the registry has at least one lab"


# ------------------------------------------------------------------------------------------------------------------
# lab-specific facts (what each lab must teach). One function per lab; a new lab may add one, none is required.
def _cmds(lab) -> set[str]:
    return {c.command for s in lab.steps for c in s.checks} | {v.command for s in lab.steps for v in s.verify} | \
        {c.command for c in lab.checks}


def _explain(lab) -> str:
    return "\n".join(s.explain for s in lab.steps)


def _has_all(text, musts, what=""):
    missing = [m for m in musts if m not in text]
    assert not missing, (what, missing)


def spec_19(lab):
    assert lab.platforms == ["iol"] and lab.node_count == 8
    assert {n.name for n in lab.nodes} == {"P1", "RR", "PE1", "PE2", "PE3", "CE1", "CE2", "CE3"}
    assert [s.id for s in lab.steps] == ["topology", "core-igp", "core-ldp", "bgp-evpn", "evi", "bridge-domains",
                                        "verify-l2", "vpws"]
    assert lab.step("vpws").optional and not any(s.optional for s in lab.steps[:-1])
    assert sizing.estimate(lab, "iol")["gb"] == 8.0
    text = "\n".join(c for s in lab.steps for c in s.config.values())
    _has_all(text, ("ip ospf 1 area 0", "mpls ldp router-id Loopback0 force", "mpls ip", "address-family l2vpn evpn",
                    "route-reflector-client", "send-community both", "replication-type ingress",
                    "l2vpn evpn instance 10 vlan-based", "l2vpn evpn instance 20 vlan-based", "service instance 10 ethernet",
                    "encapsulation dot1q 20", "member evpn-instance 10", "member evpn-instance 20",
                    "l2vpn evpn instance 100 point-to-point", "service target 3 source 1"))
    _has_all(_cmds(lab), ("show bgp l2vpn evpn summary", "show bgp l2vpn evpn route-type 2", "show bgp l2vpn evpn route-type 3",
                          "show l2vpn evpn mac", "show l2vpn evpn evi detail", "show bridge-domain 10", "show mpls ldp neighbor",
                          "ping 192.168.10.3", "ping 192.168.20.2"))
    assert "router bgp" not in lab.step_solution()["P1"]      # BGP-free core
    lines = config_script(lab.step("bridge-domains").config["PE1"].replace("%if1%", "Ethernet0/1"))
    i = lines.index("service instance 10 ethernet")
    assert lines[i + 1] == "encapsulation dot1q 10" and lines[i + 2] == "exit" and "member evpn-instance 20" in lines
    assert config_script(lab.step("bgp-evpn").config["RR"])[-1] == "neighbor 10.0.0.3 route-reflector-client"
    nodes = sent_nodes(lab)                                    # customer devices are fully preconfigured
    for ce, last in (("CE1", 1), ("CE2", 2), ("CE3", 3)):
        for vlan in (10, 20):
            assert f"interface Ethernet0/0.{vlan}\n encapsulation dot1Q {vlan}\n ip address 192.168.{vlan}.{last} " \
                in nodes[ce]["configuration"]
    assert "ip address 192.168.100.1 " in nodes["CE1"]["configuration"]
    assert "ip address 192.168.100.3 " in nodes["CE3"]["configuration"]


SUPER_LEAVES = ("DC1-LEAF1", "DC1-LEAF2", "DC2-LEAF1", "DC2-LEAF2")


def spec_20(lab):
    assert lab.platforms == ["iol"] and lab.node_count == 12 <= 20
    assert {n.name for n in lab.nodes if n.definition == "nxosv9000"} == set(SUPER_LEAVES)
    assert [s.id for s in lab.steps] == ["fabric", "underlay", "bgp-evpn", "vlan-vni", "nve", "extend-vlans", "l3vni-irb"]
    assert lab.step("l3vni-irb").optional and "Multi-Site" in lab.solution_summary
    est = sizing.estimate(lab, "iol")
    assert est["gb"] == 56.0 and est["heavy"]                  # 4 x nxosv9000 (12) + 8 x iol-xe (1)
    sol = lab.step_solution()
    for ss in ("SS1", "SS2"):
        for leaf in ("111", "112", "121", "122"):
            assert f"neighbor 10.0.0.{leaf} route-reflector-client" in sol[ss]
        assert "address-family l2vpn evpn" in sol[ss] and "interface nve" not in sol[ss]
    for sp in ("DC1-SPINE", "DC2-SPINE"):                      # pure IP transit
        assert "router bgp" not in sol[sp] and "ip ospf 1 area 0" in sol[sp]
    for leaf in SUPER_LEAVES:
        _has_all(sol[leaf], ("feature nv overlay", "feature vn-segment-vlan-based", "nv overlay evpn", "neighbor 10.0.0.1\n",
                             "neighbor 10.0.0.2\n", "send-community extended", "vn-segment 10010", "vn-segment 10020",
                             "vni 10010 l2", "host-reachability protocol bgp", "source-interface loopback1",
                             "ingress-replication protocol bgp", "member vni 50001 associate-vrf",
                             "fabric forwarding mode anycast-gateway"), leaf)
        assert "route-reflector-client" not in sol[leaf]
    _has_all(_cmds(lab), ("show nve peers", "show nve vni", "show bgp l2vpn evpn route-type 2", "show bgp l2vpn evpn route-type 3",
                          "show bgp l2vpn evpn summary", "ping 192.168.10.13", "ping 192.168.20.14", "show ip route vrf TENANT1"))
    peers = next(c for c in lab.step("nve").checks if c.id == "nve-dc1-leaf1-peers")
    assert any("10\\.0\\.1\\.121" in m for m in peers.match) and any("10\\.0\\.1\\.122" in m for m in peers.match)
    mac = next(c for c in lab.step("extend-vlans").checks if c.id == "l2-dc1-leaf1-mac")
    assert any("nve1\\(10\\.0\\.1\\.121\\)" in m for m in mac.match)
    rr = config_script(lab.step("bgp-evpn").config["SS1"])
    assert rr[rr.index("address-family l2vpn evpn") + 1] == "neighbor 10.0.0.111 activate"
    nve = config_script(lab.step("nve").config["DC2-LEAF1"], "nxos")
    assert nve[:4] == ["interface nve1", "no shutdown", "host-reachability protocol bgp", "source-interface loopback1"]
    j = nve.index("member vni 10010")
    assert nve[j + 1:j + 3] == ["ingress-replication protocol bgp", "exit"]
    nodes = sent_nodes(lab)
    for h, net in (("H1", "192.168.10.11"), ("H2", "192.168.20.12"), ("H3", "192.168.10.13"), ("H4", "192.168.20.14")):
        cfg = nodes[h]["configuration"]
        assert f"ip address {net} 255.255.255.0" in cfg and "ip route 0.0.0.0 0.0.0.0 " in cfg, h


def spec_08(lab):
    for platform in ("iol", "iosv"):                           # 08-vrf-lite also runs on IOSv
        nodes = sent_nodes(lab, platform)
        assert all(f"hostname {n}\n" in c["configuration"] for n, c in nodes.items())
        for ce in ("CEA", "CEB"):
            cfg = nodes[ce]["configuration"]
            assert "ip address 10.1.1.2 255.255.255.252" in cfg and "ip address 192.168.100.1 255.255.255.0" in cfg
            assert "ip route 0.0.0.0 0.0.0.0 10.1.1.1" in cfg, ce


# NX-OS study path (21-23): six Nexus 9000v in a 5-stage Clos plus four IOL hosts, same cabling in all three labs
SERIES = ["21-nxos-ospf-multiarea", "22-nxos-bgp-over-ospf", "23-nxos-evpn-vxlan"]
NXOS = {"SS1", "SS2", "P1-SPINE", "P2-SPINE", "P1-LEAF", "P2-LEAF"}
HOSTS = {"H1", "H2", "H3", "H4"}
REAL_9000V_ROUTER_LSA = """SS1# show ip ospf database router 10.0.0.11
        OSPF Router with ID (10.0.0.1) (Process ID UNDERLAY VRF default)
                Router Link States (Area 0.0.0.0)
Link ID         ADV Router      Age        Seq#       Checksum Link Count
10.0.0.11       10.0.0.11       608        0x80000003 0xc0c7   3
"""                                                            # captured on a real Nexus 9000v (CML)


def _series(lab):
    assert not lab.solution and {n.name for n in lab.nodes} == NXOS | HOSTS and lab.node_count == 10 <= 20
    assert {n.name for n in lab.nodes if n.definition == "nxosv9000"} == NXOS
    est = sizing.estimate(lab, "iol")
    assert est["gb"] == 76.0 == lab.ram_gb and est["heavy"]   # 6 x 12 GB + 4 x 1 GB
    assert len(lab.steps) >= 10 and "starts from its own baseline" in lab.steps[0].explain
    for st in lab.steps:                                       # depth: every step explains and inspects
        assert st.verify and len(st.explain) > 600, st.id
        assert all(dev in NXOS for dev in st.config), st.id
    # standard Clos: links only between adjacent stages, no SS1-SS2 link, SS Eth1/3 unused
    stage = {"SS1": 0, "SS2": 0, "P1-SPINE": 1, "P2-SPINE": 1, "P1-LEAF": 2, "P2-LEAF": 2}
    fabric = [(ln.a.node, ln.b.node) for ln in lab.links if ln.a.node in stage and ln.b.node in stage]
    assert len(fabric) == 6 and all(abs(stage[a] - stage[b]) == 1 for a, b in fabric), fabric
    for ss in ("SS1", "SS2"):
        cfg = lab.node(ss).config
        assert re.search(r"^interface Ethernet1/3\n\s+description unused.*\n\s+shutdown$", cfg, re.M), ss
        assert "to SS1" not in cfg and "to SS2" not in cfg, ss
    every = lab.task + "\n".join(s.explain + str(s.config) + " ".join(v.expect + v.command for v in s.verify)
                                  + " ".join((c.command or "") + " ".join(c.match) + (c.hint or "") for c in s.checks)
                                  for s in lab.steps) + lab.solution_summary
    assert "SS1-SS2 link" not in every.replace("no SS1-SS2 link", "").replace("A lateral SS1-SS2 link", "")
    assert "no SS1-SS2 link" in every and not re.search(r"10\.0\.0\.2\s+\S*\s*FULL.*Eth1/3|Eth1/3 SS[12]\b", every)
    # NX-OS `show ip ospf database <type> [id]` prints only the summary table; LSA fields need `... detail`
    fields = r"Neighboring Router ID|Link Data|Router Interface address|Number of links|Network Mask|Metric Type|" \
             r"Forward(ing)? Address|TOS 0 Metric|Attached Router|LS Seq Number|Advertising Router"
    for s in lab.steps:
        for c in s.checks:
            if (c.command or "").startswith("show ip ospf database") and \
                    re.search(fields, " ".join(c.match + (c.absent or [])).replace("\\", "")):
                assert c.command.endswith(" detail"), c.id
        for v in s.verify:
            if v.command.startswith("show ip ospf database") and not v.command.endswith(" detail"):
                assert not re.search(r"a Router \(point-to-point\)|Link Data|Neighboring Router ID|Metric Type: 2|"
                                     r"forwarding address|mask 255", v.expect), (s.id, v.command)
    nodes = sent_nodes(lab)
    for n in NXOS:                                             # NX-OS day-0: both cabled fabric ports up
        for p in (1, 2):
            body = _stanza(nodes[n]["configuration"], f"Ethernet1/{p}")
            assert body and "description to " in body and "no shutdown" in body, (n, p)


def spec_21(lab):
    _series(lab)
    assert [s.id for s in lab.steps] == ["design", "links", "area0", "lsdb-area0", "interfaces", "pods", "summarize",
                                         "nssa", "stub", "spf", "vtep-path", "break-fix"]
    assert lab.step("break-fix").optional and not lab.step("break-fix").config
    sol = lab.step_solution()
    for ss in ("SS1", "SS2"):
        assert sol[ss].count("ip router ospf UNDERLAY area 0.0.0.0") == 3 and "area 0.0.0.1" not in sol[ss]
        assert "Ethernet1/3" not in sol[ss], ss
    assert "ip ospf priority" not in sol["SS1"] and "ip address 10.0.12" not in sol["SS1"]
    assert "ip router ospf UNDERLAY area 0.0.0.1" in sol["P1-SPINE"] and "area 0.0.0.1 range 10.1.0.0/16" in sol["P1-SPINE"]
    assert "area 0.0.0.1 nssa default-information-originate" in sol["P1-SPINE"]
    assert "area 0.0.0.2 range 10.2.0.0/16" in sol["P2-SPINE"] and "area 0.0.0.2 stub" in sol["P2-SPINE"]
    assert "redistribute direct route-map RM-EXT" in sol["P1-LEAF"] and "area 0.0.0.1 nssa\n" in sol["P1-LEAF"]
    assert "area 0.0.0.2 stub" in sol["P2-LEAF"] and "no-summary" not in sol["P2-LEAF"] + sol["P2-SPINE"]
    for n in NXOS:                                             # IP unnumbered fabric links
        s = sol[n]
        assert s.count("mtu 9216") == s.count("no switchport") == s.count("medium p2p") == \
            s.count("ip unnumbered loopback0") >= 1, n
        assert not re.search(r"^\s+ip address 10\.\d+\.\d+\.\d+/(?!32\b)", s, re.M), n
        assert s.index("interface loopback0") < s.index("ip unnumbered loopback0"), n
        eths = re.findall(r"^interface (Ethernet1/\d)\n", lab.step("links").config[n], re.M)
        assert s.count("ip ospf network point-to-point") == len(eths), n
    rids = [re.search(r"router-id (\S+)", sol[n]).group(1) for n in NXOS]
    los = [re.search(r"interface loopback0\n(?:[ \t]+.*\n)*?[ \t]+ip address (\S+)/32", sol[n]).group(1) for n in NXOS]
    assert len(set(rids)) == 6 and sorted(rids) == sorted(los)
    checks = {c.id: c for s in lab.steps for c in s.checks}
    assert checks["lsdb-ss1-router-lsas-only"].absent
    for c in checks.values():                                  # no /30 link addresses left
        text = ((c.command or "") + " " + " ".join(c.match)).replace("\\", "")
        assert not re.search(r"10\.0\.[1-4]\.[12]\b|10\.0\.12\.|10\.[12]\.10\.", text), c.id
    _has_all(_explain(lab), ("debug logfile", "debug-filter", "undebug all", "event-history adjacency", "show debug logfile"))
    _has_all(_cmds(lab), ("show ip ospf database nssa-external", "show ip ospf database external", "show ip ospf database summary",
                          "show ip ospf database asbr-summary", "show ip ospf event-history adjacency", "show ip ospf"))
    for must in ("Why the super spines do not interconnect", "up-down", "Uniform hop count", "Predictable ECMP", "No extra ports"):
        assert must in lab.step("design").explain, must
    c = next(c for c in lab.step("area0").checks if c.command == "show ip route 10.0.0.2")   # SS1 -> SS2 over both spines
    assert c.device == "SS1" and "ubest/mbest: 2/0" in c.match and len(c.match) == 3
    ss1 = next(c for c in lab.step("area0").checks if c.id == "area0-ss1-neighbors")
    assert ss1.absent and not any(r"10\.0\.0\.2\s" in m for m in ss1.match)
    c = checks["lsdb-p1-spine-link-count"]                     # the summary check matches real 9000v output
    assert c.command == "show ip ospf database router 10.0.0.11"
    assert all(re.search(m, REAL_9000V_ROUTER_LSA, re.M) for m in c.match)
    assert "needs `detail`" in lab.step("lsdb-area0").explain and "unlike IOS" in lab.step("lsdb-area0").explain
    assert not any(re.search(m, REAL_9000V_ROUTER_LSA, re.M) for m in checks["lsdb-p1-spine-unnumbered-links"].match)


def spec_22(lab):
    _series(lab)
    assert [s.id for s in lab.steps] == ["baseline", "rr", "leaf-peering", "transport", "advertise", "bestpath",
                                         "bgp-free-core", "policy", "ebgp", "bfd", "convergence", "wrap-up"]
    assert lab.step("policy").optional and lab.step("bfd").optional and not lab.step("bfd").config
    assert not lab.step("ebgp").config and not lab.step("baseline").config
    for n in NXOS:                                             # inherited lab 21 underlay
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
    _has_all(_explain(lab), ("debug logfile", "debug-filter", "undebug all", "event-history", "show debug logfile", "BFD"))
    _has_all(_cmds(lab), ("show bgp ipv4 unicast summary", "show bgp ipv4 unicast 172.16.2.0/24", "show ip route 172.16.2.0/24"))
    c = next(c for c in lab.step("baseline").checks if c.command == "show ip route 10.0.0.2")
    assert c.device == "SS1" and "ubest/mbest: 2/0" in c.match and len(c.match) == 3
    rr = lab.step("bestpath").explain
    assert "No RR-to-RR session here" in rr and "loopback to loopback through the spines" in rr
    assert "SS2 -> P2-SPINE -> SS1" in lab.step("convergence").explain


def spec_23(lab):
    _series(lab)
    assert [s.id for s in lab.steps] == ["baseline", "design", "features", "evpn-af", "vni", "nve", "access", "l2-test",
                                         "bum", "l3vni", "anycast-gw", "irb", "type5", "retain-rt", "suppress-arp",
                                         "troubleshoot", "wrap-up"]
    assert not lab.step("retain-rt").optional and lab.step("retain-rt").checks
    for st in ("suppress-arp", "troubleshoot"):
        assert lab.step(st).optional and not lab.step(st).config and not lab.step(st).checks, st
    for n in NXOS:                                             # inherited labs 21 + 22
        cfg = lab.node(n).config
        assert "router ospf UNDERLAY" in cfg and "router bgp 65000" in cfg and "evpn" not in cfg, n
    assert "set local-preference" not in lab.node("P1-LEAF").config
    sol = lab.step_solution()
    retain = re.compile(r"^router bgp 65000\n  address-family l2vpn evpn\n    retain route-target all$", re.M)
    for sw in ("SS1", "SS2", "P1-SPINE", "P2-SPINE"):
        assert retain.search(lab.step("retain-rt").config[sw]), sw
    for spine in ("P1-SPINE", "P2-SPINE"):
        assert "nv overlay evpn" in sol[spine] and "feature nv overlay" not in sol[spine] and "vn-segment" not in sol[spine]
    explain = lab.step("retain-rt").explain
    assert "does not remove BGP path hunting" in explain.replace("**", "").replace("NOT", "not") and "same ASN" in explain
    for ss in ("SS1", "SS2"):
        assert "nv overlay evpn" in sol[ss] and sol[ss].count("route-reflector-client") == 4
        assert "nve" not in sol[ss].replace("nv overlay evpn", "") and "vn-segment" not in sol[ss]
    for leaf in ("P1-LEAF", "P2-LEAF"):
        s = sol[leaf]
        assert "retain route-target" not in s and "mcast-group" not in s and "suppress-arp" not in s
        _has_all(s, ("feature nv overlay", "feature vn-segment-vlan-based", "vn-segment 10010", "vn-segment 10020",
                     "vn-segment 50001", "source-interface loopback1", "host-reachability protocol bgp",
                     "ingress-replication protocol bgp", "member vni 50001 associate-vrf",
                     "fabric forwarding anycast-gateway-mac 2020.0000.00aa", "fabric forwarding mode anycast-gateway",
                     "route-target both auto evpn", "redistribute direct route-map PERMIT-ALL",
                     "spanning-tree port type edge"), leaf)
    _has_all(_explain(lab), ("debug logfile", "debug-filter", "undebug all", "ethanalyzer", "mcast-group", "ip pim",
                             "Route type", "symmetric", "suppress-arp", "show debug logfile"))
    _has_all(_cmds(lab), ("show nve peers", "show nve vni", "show bgp l2vpn evpn route-type 2", "show bgp l2vpn evpn route-type 3",
                          "show bgp l2vpn evpn route-type 5", "show l2route evpn mac all", "show nve vni ingress-replication"))


# 3.3.5 walkthroughs chosen from the exam coverage gaps (IOL only, small enough for any CML 2.9.1 licence)
def _small_iol(lab, nodes: set, ids: list):
    assert lab.platforms == ["iol"] and {n.name for n in lab.nodes} == nodes
    assert [s.id for s in lab.steps] == ids and lab.solution_summary
    assert sizing.estimate(lab, "iol")["gb"] <= len(nodes) + 1
    return {s.id: s for s in lab.steps}


def spec_24(lab):
    st = _small_iol(lab, {"INET", "HUB", "SPOKE1", "SPOKE2", "SPOKE3"},
                    ["design", "underlay", "hub-mgre", "spokes-register", "routing", "phase3", "summarize", "troubleshoot"])
    hub = st["hub-mgre"].config["HUB"]
    assert "ip nhrp map multicast dynamic" in hub and "ip nhrp map 172" not in hub   # dynamic spokes, no static maps
    assert "ip nhrp redirect" in st["phase3"].config["HUB"]
    assert all("ip nhrp shortcut" in st["phase3"].config[s] and "ip nhrp nhs 172.16.0.1 nbma 203.0.113.2 multicast"
               in st["spokes-register"].config[s] and "eigrp stub connected" in st["routing"].config[s]
               for s in ("SPOKE1", "SPOKE2", "SPOKE3"))
    assert "tunnel protection" not in "".join(c for s in lab.steps for c in s.config.values())   # no IPsec data plane on IOL


def spec_25(lab):
    st = _small_iol(lab, {"R1", "R2", "ADMIN", "USER"},
                    ["baseline", "local-users", "aaa", "ssh-vty", "copp", "urpf", "ipv6-filter", "audit"])
    aaa = st["aaa"].config["R1"]
    # the app grades over the console: its own list (none) must be applied before 'default local' exists
    assert aaa.index("login authentication CONSOLE") < aaa.index("aaa authentication login default local")
    assert not any("enable secret" in c for s in lab.steps for c in s.config.values())
    assert "transport input ssh" in st["ssh-vty"].config["R1"] and "modulus 2048" in st["ssh-vty"].config["R1"]


def spec_26(lab):
    st = _small_iol(lab, {"SRV", "R1", "CLIENT1", "CLIENT2", "BR"},
                    ["design", "addressing", "static", "dhcpv4", "slaac", "stateful", "prefix-delegation", "troubleshoot"])
    assert lab.track == "CCNA"
    hosts = "".join(c for s in lab.steps for n, c in s.config.items() if n.startswith("CLIENT"))
    assert "ipv6 unicast-routing" not in hosts                 # hosts must process RAs (SLAAC, default router)
    assert "ipv6 route ::/0 %if3% FE80::2 200" in st["static"].config["R1"]      # floating static, link-local next hop
    assert "ip helper-address 10.20.0.1" in st["dhcpv4"].config["R1"]
    assert "ipv6 dhcp relay destination 2001:DB8:0:1::1" in st["stateful"].config["R1"]


SPECS = {"08-vrf-lite": spec_08, "19-evpn-mpls": spec_19, "20-evpn-vxlan-superspine": spec_20,
         "21-nxos-ospf-multiarea": spec_21, "22-nxos-bgp-over-ospf": spec_22, "23-nxos-evpn-vxlan": spec_23,
         "24-dmvpn-phase3": spec_24, "25-infra-security": spec_25, "26-ipv6-dhcp-services": spec_26}


def _strip(cfg):
    return [ln.rstrip() for ln in cfg.splitlines() if ln.strip() and not ln.lstrip().startswith("!")]


def test_nxos_study_path_baselines_and_course():
    """Skippable labs, no drift: lab N boots with lab N-1's day-0 + lab N-1's required steps; the course orders them."""
    labs = [packs.pack_lab(packs.read_dir(ROOT / "examples" / i)) for i in SERIES]
    for prev, lab in zip(labs, labs[1:]):
        assert sorted(map(str, lab.links)) == sorted(map(str, labs[0].links))
        sol = prev.step_solution(include_optional=False)
        for node in lab.nodes:
            before = prev.node(node.name)
            if node.name in HOSTS:
                assert node.config == before.config, node.name
            else:
                assert _strip(node.config) == _strip(before.config) + _strip(sol[node.name]), node.name
                assert node.config.startswith(f"! Lab {lab.id[:2]} baseline"), node.name
    r = subprocess.run([sys.executable, str(ROOT / "packaging" / "nxos_study_baseline.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for folder, ext in (("library", "cmlcourse"), ("labs", "encorcourse")):
        course, bundled = courses.read_course((ROOT / folder / f"nxos-study-path.{ext}").read_bytes())
        assert course.labs == SERIES and set(bundled) == set(SERIES)
        assert course.title == "NX-OS study path: OSPF \u2192 BGP \u2192 BGP EVPN VXLAN"
        it = INDEX[folder]["nxos-study-path"]
        assert it["kind"] == "course" and it["labs"] == SERIES and it["ram_gb"] == 76.0
