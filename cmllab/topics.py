"""Library topic tags (3.2.0): the one controlled vocabulary, and defaults for labs that have none.

Every library lab carries `topics` in library/index.json (and labs/index.json): a few subject topics from TOPICS,
then its type (walkthrough / challenge) and its track (encor, ...). The subject topics of the published labs are set
in labsrc/library.yaml (`topics:`); a lab that has none there, and any lab in a third-party index, gets them from
derive(): its blueprint items (ENCOR), then keywords in its id, title, summary and domain, then its node types.
The pack files do not carry topics, so adding or changing them never changes a pack (no "Update available").
Older apps ignore the field (unknown keys in index items are skipped by every version since 1.x)."""
from __future__ import annotations

import re

# (id, label, area). The order is the order of the chips and of the groups on the Library page.
TOPICS: list[tuple[str, str, str]] = [
    ("ospf", "OSPF", "Routing"),
    ("eigrp", "EIGRP", "Routing"),
    ("bgp", "BGP", "Routing"),
    ("routing-policy", "Redistribution & PBR", "Routing"),
    ("switching", "VLAN / STP / EtherChannel", "Switching"),
    ("fhrp", "HSRP / FHRP", "Switching"),
    ("ip-services", "IP services (NAT, NTP)", "IP services"),
    ("multicast", "Multicast", "IP services"),
    ("vrf", "VRF", "VPN & overlays"),
    ("tunnels", "GRE / IPsec", "VPN & overlays"),
    ("mpls", "MPLS", "VPN & overlays"),
    ("evpn-vxlan", "EVPN / VXLAN", "VPN & overlays"),
    ("data-center", "Data center", "VPN & overlays"),
    ("security", "Security", "Security & operations"),
    ("qos", "QoS", "Security & operations"),
    ("assurance", "Monitoring & assurance", "Security & operations"),
    ("automation", "Automation", "Security & operations"),
    ("troubleshooting", "Troubleshooting", "Security & operations"),
    ("other", "Other", "Other"),
    ("walkthrough", "Walkthrough", "Type"),
    ("challenge", "Challenge", "Type"),
    ("encor", "ENCOR", "Track"),
]
LABELS = {t: lbl for t, lbl, _ in TOPICS}
AREA = {t: a for t, _, a in TOPICS}
TYPE_TOPICS = ("walkthrough", "challenge")
SUBJECTS = [t for t, _, a in TOPICS if a not in ("Type", "Track")]
MAX_TOPICS = 8
_ALIASES = {lbl.lower(): t for t, lbl, _ in TOPICS} | {
    "vlan": "switching", "stp": "switching", "etherchannel": "switching", "hsrp": "fhrp", "evpn": "evpn-vxlan",
    "vxlan": "evpn-vxlan", "datacenter": "data-center", "redistribution": "routing-policy", "pbr": "routing-policy",
    "ipsec": "tunnels", "gre": "tunnels", "monitoring": "assurance", "assurance": "assurance", "nat": "ip-services"}

# ENCOR 350-401 blueprint items -> topic (the longest matching prefix wins)
BLUEPRINT = {"1.5": "qos", "1.1.a": "data-center", "2.2.a": "vrf", "2.2.b": "tunnels", "2.2": "mpls", "2.3": "evpn-vxlan",
             "3.1": "switching", "3.2.a": "eigrp", "3.2.b": "ospf", "3.2.c": "bgp", "3.2.d": "routing-policy",
             "3.3.a": "ip-services", "3.3.b": "ip-services", "3.3.c": "fhrp", "3.3.d": "multicast", "4": "assurance",
             "5": "security", "6": "automation"}

KEYWORDS: list[tuple[str, str]] = [   # (regex on id/title/summary/domain, topic)
    (r"\bospf", "ospf"), (r"\beigrp", "eigrp"), (r"\bbgp|\bebgp|\bibgp", "bgp"),
    (r"redistribut|\bpbr\b|policy[- ]based|route[- ]map", "routing-policy"),
    (r"\bvlans?\b|\bstp\b|spanning|trunk|etherchannel|\blacp\b|\bpagp\b|\bswitch", "switching"),
    (r"\bhsrp|\bvrrp|\bglbp|\bfhrp|first[- ]hop", "fhrp"),
    (r"\bnat\b|\bntp\b|\bdhcp", "ip-services"), (r"multicast|\bpim\b|\bigmp|\bmcast", "multicast"),
    (r"\bvrf", "vrf"), (r"\bgre\b|ipsec|dmvpn|tunnel", "tunnels"), (r"\bmpls|\bldp\b|l3vpn", "mpls"),
    (r"\bevpn|vxlan", "evpn-vxlan"), (r"data ?cent(er|re)|\bnexus|nx-?os|spine|\bleaf", "data-center"),
    (r"\bacl|security|\baaa\b|copp|firewall|802\.1x|port[- ]security", "security"), (r"\bqos\b|quality of service", "qos"),
    (r"\bsnmp|syslog|netflow|ip ?sla|\bspan\b|assurance|monitor", "assurance"),
    (r"automation|netconf|restconf|\byang\b|ansible|python|\bapi\b|programmab", "automation"),
    (r"troubleshoot|\bbroken\b|\bfaults?\b", "troubleshooting"),
]
_KW = [(re.compile(rx, re.I), t) for rx, t in KEYWORDS]
NODE_TOPICS = {"nxosv9000": "data-center", "nxosv": "data-center", "asav": "security", "ftdv": "security"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:30]


def normalize(values) -> list[str]:
    """Known topic ids from a list of ids or labels (case-insensitive); anything else is dropped. Order kept, no dups."""
    out: list[str] = []
    for v in values if isinstance(values, list) else []:
        s = str(v).strip().lower()
        t = s if s in LABELS else _ALIASES.get(s) or (slug(s) if slug(s) in LABELS else None)
        if t and t not in out:
            out.append(t)
    return out


def derive(item: dict) -> list[str]:
    """Subject topics for a lab without any: blueprint (ENCOR track), keywords, node types; 'other' if nothing fits."""
    out: list[str] = []
    add = lambda t: t not in out and out.append(t)  # noqa: E731
    if (item.get("track") or "ENCOR").upper() == "ENCOR":
        for bp in item.get("blueprint") or []:
            keys = [k for k in BLUEPRINT if str(bp) == k or str(bp).startswith(k + ".")]
            if keys:
                add(BLUEPRINT[max(keys, key=len)])
    for keys in (("id", "title", "domain"), ("description", "summary")):   # the summary only if little was found
        if len(out) >= 2 and keys[0] == "description":
            break
        text = " ".join(str(item.get(k) or "") for k in keys).replace("-", " ")
        for rx, t in _KW:
            if rx.search(text):
                add(t)
    for d in item.get("node_types") or []:
        if d in NODE_TOPICS:
            add(NODE_TOPICS[d])
    return out[:4] or ["other"]


def track_topic(track: str) -> str | None:
    s = slug(track or "")
    return s or None


def for_lab(item: dict) -> list[str]:
    """The full topic list of a library lab: its subject topics (given, else derived), its type, its track."""
    subj = [t for t in normalize(item.get("topics")) if t in SUBJECTS] or derive(item)
    out = subj[:MAX_TOPICS - 2]
    out.append("walkthrough" if item.get("type") == "walkthrough" else "challenge")
    tr = track_topic(item.get("track") or "")
    if tr and tr not in out:
        out.append(tr)
    return out


def for_course(course: dict, labs_by_id: dict) -> list[str]:
    """A course's topics: the most common subject topics of its labs (up to 6), then the tracks of its labs."""
    count: dict[str, int] = {}
    tracks: list[str] = []
    for lid in course.get("labs") or []:
        lab = labs_by_id.get(lid)
        for t in (lab or {}).get("topics") or []:
            if t in SUBJECTS:
                count[t] = count.get(t, 0) + 1
            elif t not in TYPE_TOPICS and t not in tracks:
                tracks.append(t)
    subj = sorted(count, key=lambda t: (-count[t], SUBJECTS.index(t)))[:6]
    if not subj:
        subj = [t for t in normalize(course.get("topics")) if t in SUBJECTS] or derive(course)
    return subj + tracks[:2]


def vocabulary(used: list[str] | None = None) -> list[dict]:
    """[{id, label, area}] in display order: the vocabulary, plus any other track topics in use (label = upper)."""
    out = [{"id": t, "label": lbl, "area": a} for t, lbl, a in TOPICS]
    for t in used or []:
        if t not in LABELS and not any(o["id"] == t for o in out):
            out.append({"id": t, "label": t.replace("-", " ").upper(), "area": "Track"})
    return out
