"""Estimated CML server RAM per lab, from the node definitions it uses.

The table holds the default RAM of the CML 2.9 reference-platform node definitions (refplat ISO). A node or image
definition on your server can override these values, so this is an estimate. A lab author can replace it with
`ram_gb:` in lab.yaml. Labs at or above the Settings threshold (default 16 GB) are tagged "RAM heavy"."""
from __future__ import annotations

from .platforms import get as get_platform

# GB per running node (default `ram` of the CML 2.9 reference node definitions)
RAM_GB = {
    "iol-xe": 1.0, "ioll2-xe": 1.0, "iol-xe-serial-4eth": 1.0,
    "iosv": 0.5, "iosvl2": 0.75,
    "csr1000v": 3.0, "cat8000v": 4.0,
    "cat9000v-uadp": 18.0, "cat9000v-q200": 18.0,
    "nxosv9000": 12.0,            # Nexus 9300v 10.5(3): 12 GB in the 2.9 definition (10 GB minimum; older definitions: 8 GB)
    "iosxrv9000": 20.0, "asav": 2.0,
    "alpine": 0.5, "desktop": 0.5, "server": 0.125, "ubuntu": 2.0,
    "unmanaged_switch": 0.0, "external_connector": 0.0,
}
CPUS = {"iol-xe": 1, "ioll2-xe": 1, "nxosv9000": 2, "cat8000v": 1, "csr1000v": 1, "cat9000v-uadp": 4, "cat9000v-q200": 4, "iosxrv9000": 4,
        "iosv": 1, "iosvl2": 1, "asav": 1, "ubuntu": 1, "alpine": 1}
DEFAULT_HEAVY_GB = 16
UNKNOWN_GB = 2.0


def node_definitions(lab, platform: str = "iol") -> list[str]:
    plat = get_platform(platform if platform in lab.platforms else lab.platforms[0])
    return [n.definition or plat.node_definition(n.kind) for n in lab.nodes]


def _fmt(gb: float) -> str:
    return f"{gb:.0f}" if gb >= 10 or gb == int(gb) else f"{gb:.1f}"


def estimate(lab, platform: str = "iol", heavy_gb: float = DEFAULT_HEAVY_GB) -> dict:
    """{"gb", "label", "heavy", "source": "estimate"|"author", "detail", "tooltip", "breakdown": [...]}."""
    counts: dict[str, int] = {}
    for d in node_definitions(lab, platform):
        counts[d] = counts.get(d, 0) + 1
    breakdown = [{"definition": d, "count": n, "gb_each": RAM_GB.get(d, UNKNOWN_GB), "known": d in RAM_GB,
                  "cpus_each": CPUS.get(d)} for d, n in sorted(counts.items(), key=lambda x: -RAM_GB.get(x[0], UNKNOWN_GB))]
    est = round(sum(b["count"] * b["gb_each"] for b in breakdown), 1)
    author = getattr(lab, "ram_gb", None)
    gb = float(author) if author else est
    parts = " + ".join(f"{b['count']} × {b['definition']} ({_fmt(b['gb_each'])} GB{'' if b['known'] else ', unknown type'})"
                       for b in breakdown)
    heavy = gb >= float(heavy_gb)
    if author:
        tip = (f"About {_fmt(gb)} GB of CML server RAM, as given by the lab author (ram_gb). "
               f"The node-definition defaults would add up to about {_fmt(est)} GB: {parts}.")
    else:
        tip = (f"About {_fmt(gb)} GB of CML server RAM while the lab runs, estimated from the CML 2.9 node-definition "
               f"defaults: {parts}. Your server's node or image settings can differ.")
    if heavy:
        tip += f" Labs needing {_fmt(float(heavy_gb))} GB or more are marked RAM heavy (threshold in Settings)."
    cpus = sum(b["count"] * (b["cpus_each"] or 0) for b in breakdown)
    return {"gb": gb, "estimate_gb": est, "label": f"~{_fmt(gb)} GB", "heavy": heavy, "threshold_gb": float(heavy_gb),
            "source": "author" if author else "estimate", "tooltip": tip, "breakdown": breakdown, "vcpus": cpus}
