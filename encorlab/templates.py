"""Check templates: short, parameterised checks that expand into regular
match/command checks. Lab authors write e.g.

  - id: r1-nbr
    template: ospf_neighbor
    device: R1
    params: {neighbor_id: 2.2.2.2}

Every template documents its params so the UI builder and the JSON Schema
can offer them."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

IP_RE = r"^\d{1,3}(\.\d{1,3}){3}$"


def q(text: str) -> str:
    """Escape a literal for use in a regex."""
    return re.escape(str(text))


def _ip(v: str) -> str:
    if not re.match(IP_RE, str(v)):
        raise ValueError(f"{v!r} is not an IPv4 address")
    return str(v)


def _prefix(v: str) -> tuple[str, str | None]:
    v = str(v)
    net, _, plen = v.partition("/")
    _ip(net)
    if plen and not (plen.isdigit() and 0 <= int(plen) <= 32):
        raise ValueError(f"bad prefix length in {v!r}")
    return net, plen or None


@dataclass
class Param:
    name: str
    description: str
    required: bool = True
    default: object = None


@dataclass
class Template:
    name: str
    mode: str
    title: str
    params: list[Param]
    build: Callable[[dict], dict]
    description_fmt: str = ""
    extra: dict = field(default_factory=dict)

    def expand(self, params: dict) -> dict:
        p = {}
        for prm in self.params:
            if prm.name in params and params[prm.name] not in (None, ""):
                p[prm.name] = params[prm.name]
            elif prm.required:
                raise ValueError(f"template {self.name}: missing param {prm.name!r}")
            else:
                p[prm.name] = prm.default
        unknown = set(params) - {x.name for x in self.params}
        if unknown:
            raise ValueError(f"template {self.name}: unknown params {sorted(unknown)}")
        out = self.build(p)
        out["mode"] = self.mode
        if "description" not in out:
            out["description"] = self.description_fmt.format(**p)
        return out


def _intf_short(name: str) -> str:
    """Accept %ifN%, %ifNs% or literal names; return a regex for the short form used in tables."""
    m = re.fullmatch(r"%if(\d)s?%", name)
    if m:
        return f"%if{m.group(1)}s%"
    m = re.fullmatch(r"([A-Za-z]{2})[A-Za-z-]*([\d/.]+)", name)
    return q(m.group(1) + m.group(2)) if m else q(name)


def _intf_long(name: str) -> str:
    m = re.fullmatch(r"%if(\d)s?%", name)
    return f"%if{m.group(1)}%" if m else q(name)


def _ping(p):
    target = _ip(p["target"])
    cmd = f"ping {target}" + (f" source {p['source']}" if p.get("source") else "") + " repeat 5"
    return {"command": cmd, "min_success": int(p["min_success"])}


def _route(p):
    net, plen = _prefix(p["prefix"])
    code = p["code"]
    codes = {"O": r"O", "O IA": r"O IA", "O E2": r"O E2", "D": r"D", "D EX": r"D EX", "B": r"B", "S": r"S\*?", "C": r"C"}
    if code not in codes:
        raise ValueError(f"route code must be one of {sorted(codes)}")
    mask = f"(/{plen})?" if plen else r"(/\d+)?"
    via = rf".*via {q(_ip(p['via']))}" if p.get("via") else ""
    vrf = f" vrf {p['vrf']}" if p.get("vrf") else ""
    return {"command": f"show ip route{vrf}", "match": [rf"^{codes[code]}\s+{q(net)}{mask}\s{via}"]}


def _vlan(p):
    vid = int(p["vlan"])
    name = q(p["name"]) if p.get("name") else r"\S+"
    return {"command": "show vlan brief", "match": [rf"^{vid}\s+{name}\s+active"]}


def _cfg_lines(p):
    lines = [l for l in str(p["lines"]).splitlines() if l.strip()]
    if not lines:
        raise ValueError("config_lines: give at least one line")
    return {"match": [rf"^\s*{q(l.strip())}\s*$" for l in lines]}


def _router(p):
    proto = p["protocol"]
    pid = str(p["process"])
    if proto not in ("ospf", "eigrp", "bgp"):
        raise ValueError("protocol must be ospf, eigrp or bgp")
    if proto == "eigrp":
        rx = rf"^router eigrp {q(pid)}\s*$|^ address-family ipv4 unicast autonomous-system {q(pid)}\b"
    else:
        rx = rf"^router {proto} {q(pid)}\b"
    return {"match": [rx]}


TEMPLATES: dict[str, Template] = {t.name: t for t in [
    Template("ospf_neighbor", "live", "OSPF neighbor FULL",
             [Param("neighbor_id", "Neighbor router ID")],
             lambda p: {"command": "show ip ospf neighbor", "match": [rf"^{q(_ip(p['neighbor_id']))}\s+\d+\s+FULL/"]},
             "OSPF adjacency with {neighbor_id} is FULL"),
    Template("eigrp_neighbor", "live", "EIGRP neighbor up",
             [Param("address", "Neighbor IP address"), Param("interface", "Local interface (%if0% or Ethernet0/0)", False)],
             lambda p: {"command": "show ip eigrp neighbors",
                        "match": [rf"{q(_ip(p['address']))}\s+" + (_intf_short(p["interface"]) + r"\s" if p.get("interface") else "")]},
             "EIGRP neighbor {address} is up"),
    Template("bgp_established", "live", "BGP session Established",
             [Param("neighbor", "Neighbor IP"), Param("remote_as", "Neighbor AS number")],
             lambda p: {"command": "show ip bgp summary",
                        "match": [rf"^{q(_ip(p['neighbor']))}\s+4\s+{int(p['remote_as'])}\s.*\s\d+\s*$"]},
             "BGP session to {neighbor} (AS {remote_as}) is Established"),
    Template("route_present", "live", "Route present in routing table",
             [Param("prefix", "Prefix, e.g. 2.2.2.2/32"), Param("code", "Route code: O, O IA, O E2, D, D EX, B, S, C"),
              Param("via", "Next hop", False), Param("vrf", "VRF name", False)],
             _route, "{code} route to {prefix} is installed"),
    Template("ping", "live", "Ping succeeds",
             [Param("target", "Destination IP"), Param("source", "Source interface or IP", False),
              Param("min_success", "Minimum success %", False, 80)],
             _ping, "Ping {target} succeeds"),
    Template("interface_up", "live", "Interface up/up",
             [Param("interface", "Interface (%if0% or Ethernet0/0, Loopback0, Tunnel0)")],
             lambda p: {"command": f"show interfaces {p['interface']}",
                        "match": [rf"{_intf_long(p['interface'])} is up, line protocol is up"]},
             "{interface} is up/up"),
    Template("vlan_exists", "live", "VLAN exists and is active",
             [Param("vlan", "VLAN ID"), Param("name", "VLAN name", False)],
             _vlan, "VLAN {vlan} exists"),
    Template("show_contains", "live", "Show command output matches regex",
             [Param("command", "show command"), Param("pattern", "Python regex (multiline)")],
             lambda p: {"command": p["command"], "match": [p["pattern"]]},
             "'{command}' output matches"),
    Template("config_lines", "config", "Running config contains lines",
             [Param("lines", "One or more exact config lines (newline separated)")],
             _cfg_lines, "Config contains the required lines"),
    Template("config_regex", "config", "Running config matches regex",
             [Param("pattern", "Python regex (multiline)")],
             lambda p: {"match": [p["pattern"]]}, "Config matches {pattern}"),
    Template("config_router", "config", "Routing process configured",
             [Param("protocol", "ospf, eigrp or bgp"), Param("process", "Process ID / AS number")],
             _router, "router {protocol} {process} is configured"),
]}


def catalog() -> list[dict]:
    return [{"name": t.name, "mode": t.mode, "title": t.title,
             "params": [{"name": p.name, "description": p.description, "required": p.required, "default": p.default}
                        for p in t.params]} for t in TEMPLATES.values()]


def expand_check(data: dict) -> dict:
    if not isinstance(data, dict) or "template" not in data:
        return data
    if not data.get("template"):
        return {k: v for k, v in data.items() if k not in ("template", "params")}
    d = dict(data)
    name = d.pop("template")
    params = d.pop("params", None) or {}
    if name not in TEMPLATES:
        raise ValueError(f"unknown template {name!r}; choose from {sorted(TEMPLATES)}")
    exp = TEMPLATES[name].expand(params)
    exp.update({k: v for k, v in d.items() if v not in (None, "", [])})  # explicit fields win
    exp["template"] = name
    exp["params"] = params
    return exp
