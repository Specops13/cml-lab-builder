"""Turn an existing CML lab topology (YAML from Lab.download()) into a draft
ENCOR lab definition that the builder can finish (task + checks)."""
from __future__ import annotations

import re

import yaml

from .platforms import MAX_PORTS, PLATFORMS

DEF_MAP = {"iol-xe": ("iol", "router"), "ioll2-xe": ("iol", "switch"),
           "iosv": ("iosv", "router"), "iosvl2": ("iosv", "switch")}
SKIP_DEFS = {"external_connector", "unmanaged_switch"}


def _main_config(cfg) -> str:
    if isinstance(cfg, list):  # schema 0.3.x: list of {name, content}
        for item in cfg:
            if isinstance(item, dict) and item.get("content"):
                return item["content"]
        return ""
    return cfg or ""


def _clean_config(text: str, hostname: str, platform) -> str:
    out = []
    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip() or s.strip() == "!" or s.strip() == "end":
            continue
        if re.match(rf"^hostname\s+{re.escape(hostname)}\s*$", s):
            continue
        if s.startswith(("Building configuration", "Current configuration", "version ", "!")):
            continue
        out.append(s)
    text = "\n".join(out) + ("\n" if out else "")
    rx = re.compile(rf"\b{platform.long_prefix}0/([0-{MAX_PORTS - 1}])\b")
    return rx.sub(lambda m: f"%if{m.group(1)}%", text)


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    s = s if re.match(r"^[a-z0-9]", s or "") else "lab-" + s
    return (s or "imported-lab")[:40].rstrip("-")


def draft_from_topology(topology_yaml: str, title: str | None = None) -> tuple[dict, list[str]]:
    topo = yaml.safe_load(topology_yaml) or {}
    warnings: list[str] = []
    nodes_in = topo.get("nodes") or []
    plats = {DEF_MAP[n["node_definition"]][0] for n in nodes_in if n.get("node_definition") in DEF_MAP}
    if not plats:
        raise ValueError("the CML lab has no IOL/IOL-L2/IOSv/IOSvL2 nodes")
    if len(plats) > 1:
        raise ValueError("the CML lab mixes IOL and IOSv nodes; use one image family")
    plat_name = plats.pop()
    plat = PLATFORMS[plat_name]
    node_ids, iface_port, nodes = {}, {}, []
    for n in nodes_in:
        nd = n.get("node_definition")
        if nd not in DEF_MAP:
            if nd not in SKIP_DEFS:
                warnings.append(f"skipped node {n.get('label')} ({nd}): not supported")
            continue
        name = re.sub(r"[^A-Za-z0-9_-]", "-", str(n.get("label", "")))[:31] or f"N{len(nodes)}"
        if not name[0].isalpha():
            name = "N" + name[:30]
        node_ids[n["id"]] = name
        for i in n.get("interfaces") or []:
            if i.get("type") == "physical" and i.get("slot") is not None:
                iface_port[(n["id"], i["id"])] = int(i["slot"])
        nodes.append({"name": name, "kind": DEF_MAP[nd][1], "x": int(n.get("x", 0)), "y": int(n.get("y", 0)),
                      "config": _clean_config(_main_config(n.get("configuration")), str(n.get("label", "")), plat)})
    links = []
    for ln in topo.get("links") or []:
        a, b = (ln.get("n1"), ln.get("i1")), (ln.get("n2"), ln.get("i2"))
        if a[0] not in node_ids or b[0] not in node_ids:
            warnings.append(f"skipped link {ln.get('id')}: connects to an unsupported node")
            continue
        pa, pb = iface_port.get(a), iface_port.get(b)
        if pa is None or pb is None or pa >= MAX_PORTS or pb >= MAX_PORTS:
            warnings.append(f"skipped link {ln.get('id')}: uses an interface beyond port {MAX_PORTS - 1}")
            continue
        links.append({"a": {"node": node_ids[a[0]], "port": pa}, "b": {"node": node_ids[b[0]], "port": pb}})
    t = title or (topo.get("lab") or {}).get("title") or "Imported lab"
    draft = {
        "id": _slug(t), "title": t, "blueprint": [], "domain": "", "difficulty": 2, "platforms": [plat_name],
        "summary": "", "nodes": nodes, "links": links,
        "task": f"# {t}\n\nDescribe the task here.\n", "checks": [], "solution": {},
    }
    warnings.append("add blueprint, domain, summary, task text, live + config checks and a solution before saving")
    return draft, warnings
