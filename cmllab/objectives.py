"""Cisco exam-objective registry: one YAML file per exam blueprint in cmllab/exams/ (CCNA, ENCOR, ENARSI, DCCOR,
CCIE EI, CCIE DC ...), transcribed from Cisco's published exam topics with the source URL and date.

A lab is tagged with exam objectives as "<EXAM> <objective>" strings, e.g. "ENCOR 3.2.b" or "CCIE-EI 1.4.c". Tags
live in the lab folder's exams.yaml (lab: [...], steps: {step-id: [...]}) so the .cmllab packs stay importable by
older apps (they ignore the extra file), or inline as `exams:` on the lab / its steps (3.3.5+ only).
Adding an exam = dropping one more YAML file into cmllab/exams/ (see docs in README "Exam objectives")."""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

EXAMS_DIR = Path(__file__).resolve().parent / "exams"
SIDECAR = "exams.yaml"
MAX_TAGS = 60
_TAG = re.compile(r"^([A-Za-z][A-Za-z0-9-]{1,15})\s+(\d+\.\d+(?:\.[a-z]+)?(?:\.[ivx]+)?(?:\.\d+)?)$")


@dataclass(frozen=True)
class Exam:
    id: str                 # registry key used in tags, e.g. ENCOR, CCIE-EI
    label: str              # short display label, e.g. "CCIE EI"
    code: str               # Cisco exam code, e.g. 350-401
    name: str
    version: str
    track: str
    level: str
    source: str
    source_page: str
    published: str
    fetched: str
    notes: str
    domains: dict = field(default_factory=dict)      # "3.0" -> (name, weight %)
    objectives: dict = field(default_factory=dict)   # "3.2.b" -> text (in blueprint order)

    def text(self, oid: str) -> str:
        return self.objectives.get(oid, "")

    def domain(self, oid: str) -> str:
        return oid.split(".")[0] + ".0"

    def parent(self, oid: str) -> str | None:
        p = oid.rsplit(".", 1)[0]
        return p if p in self.objectives else None

    def leaves(self) -> list[str]:
        """Objectives without sub-items (the units the coverage report counts)."""
        ids = list(self.objectives)
        return [i for i in ids if not any(j.startswith(i + ".") for j in ids)]


@functools.lru_cache(maxsize=4)
def registry(folder: str | None = None) -> dict[str, Exam]:
    out: dict[str, Exam] = {}
    for f in sorted(Path(folder or EXAMS_DIR).glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        eid = str(d["id"])
        out[eid] = Exam(id=eid, label=str(d.get("label") or eid), code=str(d.get("code", "")), name=str(d.get("name", "")),
                        version=str(d.get("version", "")), track=str(d.get("track", "")), level=str(d.get("level", "")),
                        source=str(d.get("source", "")), source_page=str(d.get("source_page", "")),
                        published=str(d.get("published", "")), fetched=str(d.get("fetched", "")),
                        notes=str(d.get("notes") or ""),
                        domains={str(x["id"]): (str(x["name"]), x.get("weight")) for x in d.get("domains", [])},
                        objectives={str(x["id"]): str(x["text"]) for x in d.get("objectives", [])})
    return out


# short topic for a chip ("ENCOR 3.2.b · OSPF"): first keyword match in the objective text, then its parents'
_SHORT = [(re.compile(rx, re.I), lbl) for rx, lbl in [
    (r"(?-i:CoPP)|control plane polic", "CoPP"), (r"EIGRP and OSPF", "EIGRP / OSPF"),
    (r"\bvxlan\b.*\bevpn\b|\bevpn\b", "EVPN VXLAN"), (r"\bvxlan", "VXLAN"), (r"\bLISP\b", "LISP"),
    (r"\bDMVPN", "DMVPN"), (r"\bL3VPN|Layer 3 VPN", "MPLS L3VPN"), (r"\bMPLS|\bLDP\b", "MPLS"),
    (r"\bOSPF", "OSPF"), (r"\bEIGRP", "EIGRP"), (r"\bIS-?IS\b", "IS-IS"), (r"BGP|route reflector", "BGP"),
    (r"redistribut", "Redistribution"), (r"policy-based routing|\bPBR\b", "PBR"), (r"route map", "Route maps"),
    (r"summari", "Summarization"), (r"administrative distance", "Admin distance"),
    (r"\bBFD\b|Bidirectional Forwarding", "BFD"), (r"VRF", "VRF"), (r"\bGRE\b|IPsec", "GRE / IPsec"),
    (r"EtherChannel|PortChannel|\bLACP\b|Link aggregation", "EtherChannel"), (r"Virtual PortChannel|\bvPC\b", "vPC"),
    (r"Spanning Tree|\bSTP\b|RSTP|\bMST\b|PVST|PortFast|BPDU|root guard|loop guard", "STP"),
    (r"802\.1q|trunk", "Trunking"), (r"VLAN", "VLANs"), (r"CDP|LLDP|discovery protocol", "CDP / LLDP"),
    (r"HSRP|VRRP|\bFHRP|first hop redundancy", "FHRP"), (r"\bNAT\b|\bPAT\b", "NAT"), (r"\bNTP|\bPTP\b|time synchron", "NTP"),
    (r"multicast|\bPIM|\bIGMP|\bMSDP|\bRPF\b|\bMLD\b|\bRP\b", "Multicast"), (r"DHCP", "DHCP"),
    (r"\bACL|access control list|traffic filter", "ACLs"), (r"\bCoPP\b|control plane polic", "CoPP"),
    (r"\bAAA\b|TACACS|RADIUS|RBAC", "AAA"), (r"\bSNMP", "SNMP"), (r"syslog|logging", "Syslog"),
    (r"IP ?SLA|tracking", "IP SLA"), (r"NetFlow|flow export|telemetry", "NetFlow"), (r"\bR?SPAN\b|ERSPAN", "SPAN"),
    (r"debug|traceroute|\bping\b", "Troubleshooting"), (r"\bQoS|quality of service|queu|policing|shaping|marking|DSCP|congestion|HQoS|NBAR|trust boundary", "QoS"),
    (r"\bEEM", "EEM"), (r"NETCONF|RESTCONF|YANG", "NETCONF / YANG"), (r"JSON|XML|YAML|Jinja", "Data formats"),
    (r"python|ansible|terraform|automation|\bAPIs?\b", "Automation"), (r"IPv6", "IPv6"), (r"IPv4 address|subnet", "IPv4"),
    (r"static rout|default route|floating static", "Static routing"), (r"routing table|forwarding decision", "Routing table"),
    (r"SD-WAN", "SD-WAN"), (r"SD-Access", "SD-Access"), (r"wireless|WLAN|Wi-Fi|\bAP\b", "Wireless"),
    (r"spine-leaf|tier\b|design", "Design"), (r"SSH|Telnet|console|VTY|device access|local passwords|device management", "Device access"),
    (r"MTU", "MTU"), (r"security", "Security")]]


def short_topic(exam: "Exam", oid: str) -> str:
    cur: str | None = oid
    while cur:
        for rx, lbl in _SHORT:
            if rx.search(exam.text(cur)):
                return lbl
        cur = exam.parent(cur)
    words = _VERB.sub("", exam.text(oid)).split()
    out = ""
    for w in words:
        if len(out) + len(w) + 1 > 24:
            break
        out = (out + " " + w).strip()
    out = re.sub(r"(?:\s+(?:and|or|of|the|for|with|to|in|on|a|an))+$", "", out, flags=re.I)
    return (out or " ".join(words[:1])[:24]).rstrip(",:;")


_VERB = re.compile(r"^(?:(?:configure|verify|describe|explain|compare|interpret|troubleshoot|identify|apply|implement|"
                   r"recognize|determine|define|evaluate|construct|diagnose|analyze)(?: and)?\s+)+(?:the\s+)?", re.I)


def split(tag: str) -> tuple[str, str] | None:
    m = _TAG.match(str(tag).strip())
    return (m.group(1).upper(), m.group(2)) if m else None


def problem(tag: str, reg: dict[str, Exam] | None = None) -> str | None:
    """None if the tag names a known exam objective, else why not."""
    reg = registry() if reg is None else reg
    sp = split(tag)
    if not sp:
        return f"exam tag {tag!r}: use '<EXAM> <objective>', e.g. 'ENCOR 3.2.b'"
    ex = reg.get(sp[0])
    if not ex:
        return f"exam tag {tag!r}: unknown exam {sp[0]!r} (known: {', '.join(reg)})"
    if sp[1] not in ex.objectives:
        return f"exam tag {tag!r}: {ex.label} {ex.version} has no objective {sp[1]}"
    return None


def normalize(tags, limit: int | None = MAX_TAGS) -> list[str]:
    """Canonical, de-duplicated tags (at most `limit` for one lab or step; None = no cap, e.g. a whole library)."""
    out, seen = [], set()
    for t in tags or []:
        sp = split(t)
        s = f"{sp[0]} {sp[1]}" if sp else str(t).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out if limit is None else out[:limit]


def describe(tag: str, reg: dict[str, Exam] | None = None) -> dict:
    """Display info for one tag: {tag, exam, label, id, text, domain, version, code}."""
    reg = registry() if reg is None else reg
    sp = split(tag)
    ex = reg.get(sp[0]) if sp else None
    if not ex:
        return {"tag": tag, "exam": sp[0] if sp else "", "label": sp[0] if sp else tag, "id": sp[1] if sp else "",
                "text": "", "domain": "", "version": "", "code": "", "known": False, "topic": ""}
    oid = sp[1]
    text = ex.text(oid)
    par = ex.parent(oid)
    full = f"{ex.text(par)}: {text}" if par and len(text) < 40 else text
    dom = ex.domains.get(ex.domain(oid), ("", None))[0]
    return {"tag": f"{ex.id} {oid}", "exam": ex.id, "label": ex.label, "id": oid, "text": full, "domain": dom,
            "version": ex.version, "code": ex.code, "known": oid in ex.objectives, "topic": short_topic(ex, oid)}


def read_sidecar(text: str) -> dict:
    """exams.yaml -> {"lab": [...], "steps": {id: [...]}} (raises ValueError on bad structure)."""
    d = yaml.safe_load(text) or {}
    if not isinstance(d, dict):
        raise ValueError("exams.yaml must be a mapping with lab: and steps:")
    lab = d.get("lab") or []
    steps = d.get("steps") or {}
    if not isinstance(lab, list) or not isinstance(steps, dict) or not all(isinstance(v, list) for v in steps.values()):
        raise ValueError("exams.yaml: lab: must be a list of tags, steps: a mapping of step id -> list of tags")
    unknown = set(d) - {"lab", "steps"}
    if unknown:
        raise ValueError(f"exams.yaml: unknown keys {sorted(unknown)}")
    return {"lab": normalize(lab), "steps": {str(k): normalize(v) for k, v in steps.items()}}


def dump_sidecar(lab_tags: list[str], step_tags: dict[str, list[str]]) -> str:
    body = {"lab": list(lab_tags)}
    st = {k: list(v) for k, v in step_tags.items() if v}
    if st:
        body["steps"] = st
    return ("# Cisco exam objectives this lab covers: '<EXAM> <objective>' from cmllab/exams/*.yaml\n"
            + yaml.safe_dump(body, sort_keys=False, width=200))


def apply(lab, side: dict | None) -> None:
    """Merge sidecar tags into a Lab (inline `exams:` in lab.yaml wins where present)."""
    if not side:
        return
    if not lab.exams:
        lab.exams = list(side.get("lab", []))
    for st in lab.steps:
        if not st.exams and side.get("steps", {}).get(st.id):
            st.exams = list(side["steps"][st.id])


def lab_tags(lab) -> list[str]:
    """Every tag of a lab: lab-level first, then step-level ones; ENCOR labs without tags fall back to `blueprint`."""
    tags = list(lab.exams)
    for st in lab.steps:
        tags += st.exams
    if not tags and str(getattr(lab, "track", "")).strip().upper() == "ENCOR":
        tags = [f"ENCOR {b}" for b in lab.blueprint if problem(f"ENCOR {b}") is None]
    return normalize(tags)


def lint(lab, reg: dict[str, Exam] | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a lab's exam tags: unknown objectives are errors, no tags at all is a warning."""
    reg = registry() if reg is None else reg
    errs = [p for t in lab.exams for p in [problem(t, reg)] if p]
    for st in lab.steps:
        errs += [f"step {st.id}: {p}" for t in st.exams for p in [problem(t, reg)] if p]
    warns = []
    if not lab.exams and not any(st.exams for st in lab.steps):
        try:     # suggestions from the blueprint items, track and title (`cmllab exams --suggest` lists more)
            sug = suggest(lab.blueprint, lab.track or "ENCOR", f"{lab.title} {lab.summary}", limit=6, reg=reg)
        except Exception:   # noqa: BLE001 - a suggestion must never break validation
            sug = []
        hint = ("suggested: " + ", ".join(repr(t) for t in sug)) if sug else "e.g. 'ENCOR 3.2.b', 'CCNA 3.4'"
        warns.append(f"no exam objectives tagged: add exams.yaml (or `exams:`) - {hint} "
                     "(cmllab/exams/*.yaml lists every objective)")
    return errs, warns


def coverage(labs, reg: dict[str, Exam] | None = None) -> dict[str, dict]:
    """exam -> {objective -> [lab ids]} over leaf objectives; a tag on a parent covers its sub-items, a tag on a
    sub-item covers the sub-item (and counts toward the parent)."""
    reg = registry() if reg is None else reg
    cov = {e: {o: [] for o in ex.leaves()} for e, ex in reg.items()}
    for lab in labs:
        for t in lab_tags(lab):
            sp = split(t)
            if not sp or sp[0] not in cov:
                continue
            for o in cov[sp[0]]:
                if (o == sp[1] or o.startswith(sp[1] + ".")) and lab.id not in cov[sp[0]][o]:
                    cov[sp[0]][o].append(lab.id)
    return cov


def suggest(blueprint=(), track: str = "ENCOR", text: str = "", limit: int = 12,
            reg: dict[str, Exam] | None = None) -> list[str]:
    """Suggested exam tags for a lab being authored: its blueprint items as tags of its track's exam (when the track
    is an exam in the registry), then the objectives of every exam whose short topic matches those items' topics or a
    protocol named in `text` (title, summary). Only suggestions: the author keeps what the lab really covers."""
    reg = registry() if reg is None else reg
    out: list[str] = []
    tr = (track or "ENCOR").upper().replace(" ", "-")
    topics: list[str] = []
    for b in blueprint or ():
        t = f"{tr} {str(b).strip()}"
        if tr in reg and not problem(t, reg):
            out.append(t)
            topics.append(short_topic(reg[tr], str(b).strip()))
    words = set(re.findall(r"[a-z0-9-]+", (text or "").lower()))
    rank = {"associate": 0, "professional": 1, "expert": 2}
    order = sorted(reg.values(), key=lambda e: (e.id != tr, rank.get(e.level, 3), e.id))   # own exam, then CCNA -> CCIE
    for ex in order:
        hit = {oid for oid in ex.objectives
               if (st := short_topic(ex, oid)) in topics or (st.lower() in words and len(st) > 2)}
        for oid in ex.objectives:                     # the highest matching item (a parent covers its sub-items)
            if oid in hit and ex.parent(oid) not in hit:
                t = f"{ex.id} {oid}"
                if t not in out:
                    out.append(t)
    return out[:limit]


def chips(tags, reg: dict[str, Exam] | None = None) -> list[dict]:
    """Compact display info for tags (chip label, tooltip text) for the web UI."""
    out = []
    for t in normalize(tags):
        d = describe(t, reg)
        if d["known"]:
            out.append({"tag": d["tag"], "exam": d["exam"], "label": d["label"], "id": d["id"], "topic": d["topic"],
                        "text": d["text"], "domain": d["domain"], "version": d["version"], "code": d["code"]})
    return out


def vocabulary(used, reg: dict[str, Exam] | None = None) -> list[dict]:
    """The exams (in registry order) with the objectives that `used` tags name, for the library filters."""
    reg = registry() if reg is None else reg
    by: dict[str, list[str]] = {}
    for t in normalize(used, limit=None):    # the whole library: no per-lab cap
        sp = split(t)
        if sp and sp[0] in reg and sp[1] in reg[sp[0]].objectives:
            by.setdefault(sp[0], []).append(sp[1])
    out = []
    for eid, ex in reg.items():
        if eid not in by:
            continue
        ids = [o for o in ex.objectives if o in set(by[eid])]          # blueprint order
        out.append({"id": eid, "label": ex.label, "code": ex.code, "name": ex.name, "version": ex.version,
                    "objectives": [{"id": o, "tag": f"{eid} {o}", "topic": short_topic(ex, o), "text": describe(f"{eid} {o}", reg)["text"]}
                                   for o in ids]})
    return out


def as_json(reg: dict[str, Exam] | None = None) -> list[dict]:
    """The registry for the web UI (filters, tooltips)."""
    reg = registry() if reg is None else reg
    return [{"id": e.id, "label": e.label, "code": e.code, "name": e.name, "version": e.version, "track": e.track,
             "level": e.level, "source": e.source, "published": e.published,
             "domains": [{"id": k, "name": v[0], "weight": v[1]} for k, v in e.domains.items()],
             "objectives": [{"id": k, "text": v, "topic": short_topic(e, k)} for k, v in e.objectives.items()]} for e in reg.values()]
