"""Library labs 21-23, the NX-OS study path (OSPF -> BGP -> BGP EVPN VXLAN): six Nexus 9000v in a 5-stage Clos
(SS1/SS2 super spines, one spine and one leaf per pod) plus four IOL hosts, same topology in all three labs.
Each lab is its own CML lab; lab N boots with lab N-1's day-0 plus lab N-1's required steps (no drift)."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from cmllab import courses, packs, sizing
from cmllab.console import config_script

ROOT = Path(__file__).resolve().parents[1]
SERIES = ["21-nxos-ospf-multiarea"]
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
