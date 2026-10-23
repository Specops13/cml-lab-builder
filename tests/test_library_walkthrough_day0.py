"""Library labs: every node gets a usable day-0 config on CML (strict checks for 08-vrf-lite, 19-evpn-mpls and
20-evpn-vxlan-superspine, the IOL trigger check for every library lab).

Cisco's iol-xe node definition: "In order to avoid entering a configuration dialog on boot, please ensure that all
ethernet interfaces have some ip configuration present here". Without that, IOL ignores the whole day-0 config
(no hostname, no CE/host config) and stops at the setup dialog. These tests render the published packs exactly as
the builder imports them into CML (render.to_yaml -> node "configuration") and check every node.
"""
import re
from pathlib import Path

import pytest
import yaml

from cmllab import packs
from cmllab.platforms import get as get_platform
from cmllab.render import to_yaml

ROOT = Path(__file__).resolve().parents[1]
LABS = ["08-vrf-lite", "19-evpn-mpls", "20-evpn-vxlan-superspine"]
PACKS = [ROOT / "library" / f"{lab}.cmllab" for lab in LABS] + [ROOT / "labs" / f"{lab}.encorlab" for lab in LABS]
IOL_PORTS = [f"Ethernet0/{p}" for p in range(4)]


def _sent(pack_path: Path, platform: str = "iol"):
    """(lab, {label: node dict}) as the builder sends it to CML."""
    lab = packs.parse_lab_text(packs.read_upload(pack_path.name, pack_path.read_bytes()).lab_yaml)[0]
    topo = yaml.safe_load(to_yaml(lab, get_platform(platform), "CLB-"))
    return lab, {n["label"]: n for n in topo["nodes"]}


def _stanza(cfg: str, ifname: str) -> str | None:
    m = re.search(rf"^interface {re.escape(ifname)}\n((?:[ \t].*\n)*)", cfg, re.M)
    return m.group(1) if m else None


@pytest.mark.parametrize("pack_path", PACKS, ids=lambda p: p.name)
def test_every_node_has_a_day0_config_the_device_accepts(pack_path):
    lab, nodes = _sent(pack_path)
    assert lab.version == "2"
    assert set(nodes) == {n.name for n in lab.nodes}
    cabled = {(e.node, e.port) for ln in lab.links for e in (ln.a, ln.b)}
    for n in lab.nodes:
        node = nodes[n.name]
        cfg = node["configuration"]
        assert isinstance(cfg, str) and cfg.strip(), n.name
        assert f"hostname {n.name}\n" in cfg, n.name
        if node["node_definition"] == "nxosv9000":
            assert "no ip domain-lookup" in cfg and "username admin password" in cfg, n.name
            for p in (0, 1):
                body = _stanza(cfg, f"Ethernet1/{p + 1}")
                assert body and "description to " in body and "no shutdown" in body, (n.name, p)
            continue
        assert node["node_definition"] == "iol-xe", n.name
        assert "no ip domain lookup" in cfg, n.name
        for p, ifname in enumerate(IOL_PORTS):
            body = _stanza(cfg, ifname)
            assert body is not None, f"{n.name} has no '{ifname}' stanza: IOL would ignore its day-0 config"
            assert re.search(r"^ (no )?ip address\b", body, re.M), f"{n.name} {ifname}: no IP configuration"
            assert " description " in body, (n.name, ifname)
            want = "no shutdown" if (n.name, p) in cabled else "shutdown"
            assert re.search(rf"^ {want}$", body, re.M), (n.name, ifname, want)
        assert "%if" not in cfg


def test_customer_devices_are_fully_preconfigured():
    _, n19 = _sent(ROOT / "library" / "19-evpn-mpls.cmllab")
    for ce, last in (("CE1", 1), ("CE2", 2), ("CE3", 3)):
        cfg = n19[ce]["configuration"]
        for vlan in (10, 20):
            assert f"interface Ethernet0/0.{vlan}\n encapsulation dot1Q {vlan}\n ip address 192.168.{vlan}.{last} " in cfg
    assert "ip address 192.168.100.1 " in n19["CE1"]["configuration"]
    assert "ip address 192.168.100.3 " in n19["CE3"]["configuration"]
    _, n20 = _sent(ROOT / "library" / "20-evpn-vxlan-superspine.cmllab")
    for h, net in (("H1", "192.168.10.11"), ("H2", "192.168.20.12"), ("H3", "192.168.10.13"), ("H4", "192.168.20.14")):
        cfg = n20[h]["configuration"]
        assert f"ip address {net} 255.255.255.0" in cfg and "ip route 0.0.0.0 0.0.0.0 " in cfg, h
    _, n08 = _sent(ROOT / "library" / "08-vrf-lite.cmllab")
    for ce in ("CEA", "CEB"):
        cfg = n08[ce]["configuration"]
        assert "ip address 10.1.1.2 255.255.255.252" in cfg and "ip address 192.168.100.1 255.255.255.0" in cfg, ce
        assert "ip route 0.0.0.0 0.0.0.0 10.1.1.1" in cfg, ce
    for platform in ("iol", "iosv"):     # 08-vrf-lite also runs on IOSv: the same day-0 renders there
        _, nodes = _sent(ROOT / "library" / "08-vrf-lite.cmllab", platform)
        assert all(f"hostname {n}\n" in c["configuration"] for n, c in nodes.items())


def _library_labs(folder: str) -> list[Path]:
    import json
    idx = json.loads((ROOT / folder / "index.json").read_text())
    return [ROOT / folder / i["file"] for i in idx["items"] if i.get("kind") == "lab"]


ALL_PACKS = _library_labs("library") + _library_labs("labs")


def test_audit_covers_the_whole_library():
    assert len(_library_labs("library")) >= 23 and len(ALL_PACKS) == 2 * len(_library_labs("library"))
    assert {p.stem for p in _library_labs("library")} >= set(LABS)


@pytest.mark.parametrize("pack_path", ALL_PACKS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_library_iol_node_boots_into_the_setup_dialog(pack_path):
    """The real trigger: an iol-xe node whose day-0 config has no IP configuration on any Ethernet port.
    ioll2-xe (IOL L2 switch) is exempt: its CML node definition has no such requirement (its default config is just
    the hostname) and its switchports take no IP configuration."""
    lab = packs.parse_lab_text(packs.read_upload(pack_path.name, pack_path.read_bytes()).lab_yaml)[0]
    if "iol" not in lab.platforms:
        return
    _, nodes = _sent(pack_path)
    for name, node in nodes.items():
        cfg = node["configuration"]
        assert cfg.strip() and f"hostname {name}\n" in cfg, (lab.id, name)
        if node["node_definition"] != "iol-xe":
            continue
        with_ip = [p for p in IOL_PORTS if (b := _stanza(cfg, p)) is not None and re.search(r"^ (no )?ip address\b", b, re.M)]
        assert with_ip, f"{lab.id} {name}: no IP configuration on any Ethernet port, IOL would start the setup dialog"
