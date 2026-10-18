"""Render a Lab into a CML lab topology YAML (schema version 0.2.2, accepted by
CML 2.9; same shape as Cisco's own cml-community lab files)."""
from __future__ import annotations

import yaml

from .platforms import MAX_PORTS, Platform, render
from .schema import Lab

SCHEMA_VERSION = "0.2.2"
TAG = "encorlab"


def lab_title(lab: Lab, prefix: str) -> str:
    return f"{prefix}{lab.id}"


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


def node_config(lab: Lab, node_name: str, platform: Platform) -> str:
    n = lab.node(node_name)
    cfg = base_config(n.name) + render(n.config, platform).rstrip() + "\nend\n"
    return cfg


def to_topology(lab: Lab, platform: Platform, prefix: str, solution: dict | None = None,
                title: str | None = None) -> dict:
    """solution: device -> extra config appended to the starting config (used by 'test live')."""
    if platform.name not in lab.platforms:
        raise ValueError(f"lab {lab.id} does not support platform {platform.name}")
    nodes = []
    node_ids = {}
    for i, n in enumerate(lab.nodes):
        nid = f"n{i}"
        node_ids[n.name] = nid
        ifaces = [{"id": "i0", "label": "Loopback0", "type": "loopback"}]
        for p in range(MAX_PORTS):
            ifaces.append({"id": f"i{p + 1}", "label": platform.ifname(p), "type": "physical", "slot": p})
        nodes.append({
            "id": nid,
            "label": n.name,
            "node_definition": platform.node_definition(n.kind),
            "x": n.x,
            "y": n.y,
            "tags": [TAG],
            "configuration": node_config(lab, n.name, platform) if not (solution and solution.get(n.name)) else
            node_config(lab, n.name, platform).replace("\nend\n", "\n") + render(solution[n.name], platform).rstrip() + "\nend\n",
            "interfaces": ifaces,
        })
    links = []
    for i, ln in enumerate(lab.links):
        links.append({
            "id": f"l{i}",
            "n1": node_ids[ln.a.node],
            "n2": node_ids[ln.b.node],
            "i1": f"i{ln.a.port + 1}",
            "i2": f"i{ln.b.port + 1}",
            "label": f"{ln.a.node}-{platform.ifname(ln.a.port)}<->{ln.b.node}-{platform.ifname(ln.b.port)}",
        })
    return {
        "lab": {
            "version": SCHEMA_VERSION,
            "title": title or lab_title(lab, prefix),
            "description": f"ENCOR practice lab: {lab.title} ({', '.join(lab.blueprint)})",
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


def to_yaml(lab: Lab, platform: Platform, prefix: str, solution: dict | None = None, title: str | None = None) -> str:
    topo = to_topology(lab, platform, prefix, solution=solution, title=title)
    for n in topo["nodes"]:
        n["configuration"] = _Literal(n["configuration"])
    topo["lab"]["notes"] = _Literal(topo["lab"]["notes"])
    return yaml.dump(topo, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1000)
