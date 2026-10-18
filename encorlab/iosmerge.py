"""Apply IOS configuration lines on top of a running config, roughly the way IOS does when it
processes a config sequentially (used offline to simulate 'solution + fault' configs).

The config is a tree by indentation. A line replaces an existing sibling with the same key
(e.g. a second `ip address` or `switchport trunk native vlan` on the same interface), `no X`
removes the matching sibling (or is kept as a literal line when nothing matches, e.g.
`no ip domain lookup`), and `shutdown` / `no shutdown` toggle one another. Anything not covered
by the key rules is additive, which is what IOS does for lists such as `network` statements."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A line whose text matches one of these patterns shares a "slot" with any sibling that has the same key.
_SINGLETON = [re.compile(p) for p in (
    r"^(ip address)\b(?!.*\bsecondary\b)", r"^(ipv6 address)\b(?!.*\b(?:link-local|eui-64)\b)",
    r"^(description)\b", r"^(hostname)\b", r"^(standby version)\b",
    r"^(standby \d+ (?:priority|ip|preempt|authentication|timers|track \d+))\b",
    r"^(vrrp \d+ (?:priority|ip|preempt|authentication|timers))\b",
    r"^(ip ospf \d+ area)\b", r"^(ip ospf (?:network|cost|priority|hello-interval|dead-interval))\b",
    r"^(ip ospf authentication(?:-key)?)\b", r"^(ip ospf message-digest-key \d+)\b",
    r"^(router-id)\b", r"^(eigrp router-id)\b", r"^(bgp router-id)\b", r"^(eigrp stub)\b",
    r"^(auto-summary)\b", r"^(default-information originate)\b",
    r"^(neighbor \S+ remote-as)\b", r"^(neighbor \S+ update-source)\b", r"^(neighbor \S+ next-hop-self)\b",
    r"^(neighbor \S+ (?:route-map \S+ (?:in|out)|password|shutdown|ebgp-multihop))\b",
    r"^(switchport mode)\b", r"^(switchport access vlan)\b", r"^(switchport trunk native vlan)\b",
    r"^(switchport trunk allowed vlan)\b", r"^(switchport trunk encapsulation)\b", r"^(switchport nonegotiate)\b",
    r"^(channel-group)\b", r"^(channel-protocol)\b", r"^(spanning-tree mode)\b", r"^(spanning-tree vlan \S+ priority)\b",
    r"^(spanning-tree (?:portfast|bpduguard|guard))\b", r"^(port-channel load-balance)\b",
    r"^(tunnel source)\b", r"^(tunnel destination)\b", r"^(tunnel protection)\b", r"^(tunnel mode)\b",
    r"^(key-string)\b", r"^(authentication mode)\b", r"^(authentication key-chain)\b", r"^(passive-interface)$",
    r"^(encryption)\b", r"^(hash)\b", r"^(group)\b", r"^(authentication)\b(?!\s+(?:mode|key-chain))",
    r"^(mode)\b", r"^(set transform-set)\b", r"^(set ip next-hop)\b", r"^(set tag)\b", r"^(set metric)\b",
    r"^(match ip address)\b", r"^(match tag)\b", r"^(ip policy route-map)\b",
    r"^(ip access-group \S+ in)\b", r"^(ip access-group \S+ out)\b", r"^(vrf forwarding)\b",
    r"^(ntp master)\b", r"^(ntp authentication-key \d+)\b", r"^(ntp server \S+)\b", r"^(ntp source)\b", r"^(logging trap)\b", r"^(logging source-interface)\b",
    r"^(frequency)\b", r"^(threshold)\b", r"^(timeout)\b", r"^(icmp-echo)\b",
    r"^(track \d+)\b", r"^(ip sla schedule \d+)\b", r"^(ip sla \d+)$",
    r"^(ip pim (?:sparse-mode|dense-mode|sparse-dense-mode))$", r"^(ip pim rp-address)\b", r"^(ip multicast-routing)\b",
    r"^(distribute-list \S+ (?:in|out))\b", r"^(redistribute \S+(?: \d+)?)\b", r"^(default-metric)\b",
    r"^(maximum-paths)\b", r"^(distance)\b", r"^(variance)\b",
)]
_ACCESS_GROUP = re.compile(r"^ip access-group \S+ (in|out)\b")
_NAT_SIDE = re.compile(r"^ip nat (inside|outside)$")
_ISAKMP_KEY = re.compile(r"^crypto isakmp key (?:\d )?\S+ address (\S+)")


def key(text: str) -> str:
    t = " ".join(text.split())
    if t in ("shutdown", "no shutdown"):
        return "shutdown"
    m = _ACCESS_GROUP.match(t)
    if m:
        return f"ip access-group {m.group(1)}"
    if _NAT_SIDE.match(t):
        return "ip nat side"
    m = _ISAKMP_KEY.match(t)
    if m:
        return f"crypto isakmp key address {m.group(1)}"
    for rx in _SINGLETON:
        m = rx.match(t)
        if m:
            return m.group(1)
    return t


@dataclass
class Node:
    text: str
    children: list["Node"] = field(default_factory=list)

    def find(self, k: str) -> "Node | None":
        for c in self.children:
            if key(c.text) == k:
                return c
        return None


def _lines(config: str) -> list[tuple[int, str]]:
    out = []
    for raw in config.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s or s == "!" or s == "end" or s.startswith("Building configuration") or s.startswith("Current configuration"):
            continue
        if s in ("exit-address-family", "exit-af-interface", "exit-af-topology", "exit"):
            continue  # IOS context exits: indentation already tells us where we are
        out.append((len(line) - len(line.lstrip(" ")), s))
    return out


def apply(root: Node, config: str) -> Node:
    """Apply config text to the tree (in place) and return it."""
    stack: list[tuple[int, Node]] = [(-1, root)]
    for indent, text in _lines(config):
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if text.startswith("no ") and text != "no shutdown":
            rest = text[3:].strip()
            k = key(rest)
            victims = [c for c in parent.children
                       if key(c.text) == k or c.text == rest or c.text.startswith(rest + " ")]
            if victims:
                parent.children = [c for c in parent.children if c not in victims]
                continue
            node = parent.find(key(text)) or None
            if node is None:
                node = Node(text)
                parent.children.append(node)
            stack.append((indent, node))
            continue
        existing = parent.find(key(text))
        if existing is not None:
            existing.text = text
            node = existing
        else:
            node = Node(text)
            parent.children.append(node)
        stack.append((indent, node))
    return root


def parse(config: str) -> Node:
    return apply(Node(""), config)


def dump(root: Node) -> str:
    out: list[str] = []

    def walk(n: Node, depth: int):
        for c in n.children:
            out.append(" " * depth + c.text)
            walk(c, depth + 1)
    walk(root, 0)
    return "\n".join(out) + "\n"


def merge(*configs: str) -> str:
    """Apply several configs in order, e.g. merge(start, solution, fault)."""
    root = Node("")
    for c in configs:
        apply(root, c or "")
    return dump(root)
