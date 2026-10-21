"""Render a Lab into a CML lab topology YAML (schema version 0.2.2, accepted by
CML 2.9; same shape as Cisco's own cml-community lab files)."""
from __future__ import annotations

import yaml

from .platforms import MAX_PORTS, Platform, node_def, render
from .schema import Lab

SCHEMA_VERSION = "0.2.2"
TAG = "cml-lab-builder"            # CML lab tag (encorlab up to 2.1.0)


def lab_title(lab: Lab, prefix: str) -> str:
    return f"{prefix}{lab.id}"


DEFAULT_CREDS = ("cisco", "cisco")

# CML's own nxosv9000 day-0 workaround: after the first boot, set the boot variable so that a later stop/start
# (without wipe) boots NX-OS instead of the loader> prompt. Copied from the CML reference node definition.
NXOS_BOOT_FIX = """\
echo 'from cli import cli' > set_boot.py
echo 'import json' >> set_boot.py
echo 'import os' >> set_boot.py
echo 'import time' >> set_boot.py
echo 'bootimage = json.loads(cli("show version | json"))["kick_file_name"]' >> set_boot.py
echo 'set_boot = cli("conf t ; boot nxos {} ; no event manager applet BOOTCONFIG".format(bootimage))' >> set_boot.py
echo 'i = 0' >> set_boot.py
echo 'while i < 10:' >> set_boot.py
echo '    try:' >> set_boot.py
echo '        save_config = cli("copy running-config startup-config")' >> set_boot.py
echo '        break' >> set_boot.py
echo '    except Exception:' >> set_boot.py
echo '        i += 1' >> set_boot.py
echo '        time.sleep(1)' >> set_boot.py
echo 'os.remove("/bootflash/set_boot.py")' >> set_boot.py
event manager applet BOOTCONFIG
  event syslog pattern "Configured from vty"
  action 1.0 cli python bootflash:set_boot.py
"""


def nxos_base_config(name: str, creds: tuple[str, str] | None = None) -> str:
    user, pw = creds or DEFAULT_CREDS
    users = [u for u in dict.fromkeys(["admin", user]) if u]
    return (f"hostname {name}\n" + NXOS_BOOT_FIX +
            "no password strength-check\n" +
            "".join(f"username {u} password {pw} role network-admin\n" for u in users) +
            "no ip domain-lookup\n"
            "line console\n"
            "  exec-timeout 0\n")


def base_config(name: str) -> str:
    return (
        f"hostname {name}\n"
        "no ip domain lookup\n"
        "no logging console\n"
        "service timestamps log datetime msec\n"
        "line con 0\n"
        " exec-timeout 0 0\n"
        " logging synchronous\n"
    )


def node_config(lab: Lab, node_name: str, platform: Platform, creds: tuple[str, str] | None = None) -> str:
    n = lab.node(node_name)
    nd = node_def(n.definition)
    head = nxos_base_config(n.name, creds) if nd and nd.os == "nxos" else base_config(n.name)
    cfg = head + render(n.config, platform).rstrip() + "\nend\n"
    return cfg


def full_config(lab: Lab, node_name: str, platform: Platform, extra: dict | None = None,
                creds: tuple[str, str] | None = None) -> str:
    """Day-0 config: starting config, plus extra lines (solution, fault, snapshot) when given."""
    base = node_config(lab, node_name, platform, creds)
    if not (extra and extra.get(node_name)):
        return base
    return base.replace("\nend\n", "\n") + render(extra[node_name], platform).rstrip() + "\nend\n"


def ifname(lab: Lab, node: str, port: int, platform: Platform, short: bool = False) -> str:
    nd = node_def(lab.node(node).definition)
    return nd.ifname(port, short) if nd else platform.ifname(port, short)


def _iface_id(lab: Lab, node: str, port: int) -> str:
    return f"i{port + (2 if node_def(lab.node(node).definition) else 1)}"


def to_topology(lab: Lab, platform: Platform, prefix: str, solution: dict | None = None,
                title: str | None = None, creds: tuple[str, str] | None = None) -> dict:
    """solution: device -> extra config appended to the starting config (used by 'test live')."""
    if platform.name not in lab.platforms:
        raise ValueError(f"lab {lab.id} does not support platform {platform.name}")
    nodes = []
    node_ids = {}
    for i, n in enumerate(lab.nodes):
        nid = f"n{i}"
        node_ids[n.name] = nid
        nd = node_def(n.definition)
        ifaces = [{"id": "i0", "label": "Loopback0", "type": "loopback"}]
        if nd:
            if nd.mgmt:
                ifaces.append({"id": "i1", "label": nd.mgmt, "type": "physical", "slot": 0})
            for p in range(MAX_PORTS):
                ifaces.append({"id": _iface_id(lab, n.name, p), "label": nd.ifname(p), "type": "physical",
                               "slot": p + nd.first_slot})
        else:
            for p in range(MAX_PORTS):
                ifaces.append({"id": f"i{p + 1}", "label": platform.ifname(p), "type": "physical", "slot": p})
        nodes.append({
            "id": nid,
            "label": n.name,
            "node_definition": nd.id if nd else platform.node_definition(n.kind),
            "x": n.x,
            "y": n.y,
            "tags": [TAG],
            "configuration": full_config(lab, n.name, platform, solution, creds),
            "interfaces": ifaces,
        })
    links = []
    for i, ln in enumerate(lab.links):
        links.append({
            "id": f"l{i}",
            "n1": node_ids[ln.a.node],
            "n2": node_ids[ln.b.node],
            "i1": _iface_id(lab, ln.a.node, ln.a.port),
            "i2": _iface_id(lab, ln.b.node, ln.b.port),
            "label": f"{ln.a.node}-{ifname(lab, ln.a.node, ln.a.port, platform)}<->"
                     f"{ln.b.node}-{ifname(lab, ln.b.node, ln.b.port, platform)}",
        })
    return {
        "lab": {
            "version": SCHEMA_VERSION,
            "title": title or lab_title(lab, prefix),
            "description": f"CML Lab Builder lab: {lab.title} ({', '.join(lab.blueprint)})",
            "notes": render(lab.task, platform),
        },
        "nodes": nodes,
        "links": links,
    }


class _Literal(str):
    pass


def _lit(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(_Literal, _lit)


def to_yaml(lab: Lab, platform: Platform, prefix: str, solution: dict | None = None, title: str | None = None,
            creds: tuple[str, str] | None = None) -> str:
    topo = to_topology(lab, platform, prefix, solution=solution, title=title, creds=creds)
    for n in topo["nodes"]:
        n["configuration"] = _Literal(n["configuration"])
    topo["lab"]["notes"] = _Literal(topo["lab"]["notes"])
    return yaml.dump(topo, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1000)
