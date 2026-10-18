"""ENCOR 350-401 v1.2 exam topics (Cisco Learning Network), used to map labs to domains for the progress dashboard."""
from __future__ import annotations

VERSION = "350-401 ENCOR v1.2"

DOMAINS: dict[str, tuple[str, int]] = {   # id -> (name, exam weight %)
    "1.0": ("Architecture", 15),
    "2.0": ("Virtualization", 10),
    "3.0": ("Infrastructure", 30),
    "4.0": ("Network Assurance", 10),
    "5.0": ("Security", 20),
    "6.0": ("Automation and Artificial Intelligence", 15),
}

ITEMS: dict[str, str] = {
    "1.1": "Enterprise network design principles", "1.1.a": "2-tier, 3-tier, fabric and cloud design",
    "1.1.b": "High availability: redundancy, FHRP, SSO", "1.2": "Catalyst SD-WAN", "1.3": "SD-Access",
    "1.4": "Interpret QoS configurations",
    "2.1": "Device virtualization", "2.2": "Data path virtualization", "2.2.a": "VRF", "2.2.b": "GRE and IPsec tunneling",
    "2.3": "Network virtualization: LISP, VXLAN",
    "3.1": "Layer 2", "3.1.a": "802.1Q trunking", "3.1.b": "EtherChannel", "3.1.c": "Spanning tree (RSTP, MST) and enhancements",
    "3.2": "Layer 3", "3.2.a": "EIGRP and OSPF concepts", "3.2.b": "OSPFv2/v3", "3.2.c": "eBGP", "3.2.d": "Policy-based routing",
    "3.3": "IP services", "3.3.a": "NTP and PTP", "3.3.b": "NAT/PAT", "3.3.c": "FHRP: HSRP, VRRP",
    "3.3.d": "Multicast: RPF, PIM SM, IGMP, SSM, bidir, MSDP",
    "4.1": "Diagnose with debugs, traceroute, ping, SNMP, syslog", "4.2": "Flexible NetFlow", "4.3": "SPAN/RSPAN/ERSPAN",
    "4.4": "IP SLA", "4.5": "Catalyst Center workflows", "4.6": "NETCONF and RESTCONF",
    "5.1": "Device access control", "5.1.a": "Lines and local user authentication", "5.1.b": "AAA",
    "5.2": "Infrastructure security", "5.2.a": "ACLs", "5.2.b": "CoPP", "5.3": "REST API security",
    "5.4": "Network security design",
    "6.1": "Python", "6.2": "JSON", "6.3": "YANG", "6.4": "Catalyst Center and SD-WAN Manager APIs",
    "6.5": "REST API response codes", "6.6": "EEM applets", "6.7": "Agent vs agentless orchestration",
}


def domain_of(item: str) -> str | None:
    d = item.split(".")[0] + ".0"
    return d if d in DOMAINS else None


def title(item: str) -> str:
    return ITEMS.get(item) or ITEMS.get(".".join(item.split(".")[:2]), "")


def known(item: str) -> bool:
    return item in ITEMS
