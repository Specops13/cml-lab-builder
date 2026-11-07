"""Lab modes (3.3.7): every lab can be built as a **challenge** (goals, checks, hints, solution at the end) or as a
**walkthrough** (ordered steps with the exact commands per device, what each command does, and what good verification
output looks like). The mode is chosen at build time and remembered per lab (data folder, modes.json); it can be
switched later without rebuilding because it only changes how the lab is presented and graded.

How the other shape is produced:

* challenge lab -> walkthrough: the steps come from the lab folder's ``guide.yaml`` sidecar (written by the author or
  scaffolded with ``cmllab guide --write``). Without one they are derived on the fly from the reference solution
  (one "Configure <device>" step per device, each command explained from the glossary below, the device's config
  checks) plus a final "Verify end to end" step with every live check and the matching lines of fixture_solved.yaml.
* walkthrough lab -> challenge: the lab's own intro becomes the task with the step titles as goals, every step check
  is graded, the step configs are the reference solution and the step explanations stay hidden until it is solved.

``guide.yaml`` is a sidecar like exams.yaml: apps before 3.3.7 skip it ("ignored file in pack"), so packs stay
importable by older versions."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import yaml

from .schema import Check, Lab, Step, Verify

SIDECAR = "guide.yaml"
MODES = ("challenge", "walkthrough")
_lock = threading.Lock()


class GuideError(ValueError):
    pass


# ---------------------------------------------------------------- mode per lab (data folder)
def _modes_file() -> Path:
    from .history import data_dir
    return data_dir() / "modes.json"


def modes() -> dict[str, str]:
    try:
        d = json.loads(_modes_file().read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if v in MODES} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def get_mode(lab_id: str) -> str | None:
    """The mode chosen for this lab, or None if it was never chosen (the lab's own type is used)."""
    return modes().get(lab_id)


def set_mode(lab_id: str, mode: str) -> str:
    if mode not in MODES:
        raise GuideError(f"mode must be one of {', '.join(MODES)}")
    with _lock:
        d = modes()
        d[lab_id] = mode
        f = _modes_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(f)
    return mode


# ---------------------------------------------------------------- command glossary (IOS / IOS XE config lines)
# (regex on the stripped line, explanation). {name} fields come from named groups. First match wins.
GLOSSARY: list[tuple[str, str]] = [
    # interfaces
    (r"interface (?P<i>\S+)\.(?P<s>\d+)$", "Creates subinterface {s} of {i} and enters its configuration (one per VLAN on a router-on-a-stick or 802.1Q handoff)."),
    (r"interface (?P<i>Loopback\d+)$", "Creates (or enters) {i}, a virtual interface that is always up: the stable address for router IDs, peering and management."),
    (r"interface (?P<i>Vlan\d+)$", "Creates the switched virtual interface (SVI) {i}: the layer-3 gateway of that VLAN on this switch."),
    (r"interface (?P<i>Port-channel\d+)$", "Enters the logical EtherChannel interface {i}; settings here apply to the whole bundle."),
    (r"interface (?P<i>Tunnel\d+)$", "Creates the tunnel interface {i} (a virtual point-to-point link carried inside IP)."),
    (r"interface (?P<i>\S+)$", "Enters interface configuration mode for {i}; the indented lines below apply to that interface."),
    (r"description (?P<d>.+)$", "Labels the interface (\"{d}\") so `show interfaces description` documents the design."),
    (r"ip address (?P<a>\S+) (?P<m>\S+) secondary$", "Adds {a} {m} as a secondary address on the interface."),
    (r"ip address (?P<a>\S+) (?P<m>\S+)$", "Assigns the IPv4 address {a} with mask {m}; the connected subnet appears in the routing table once the interface is up."),
    (r"ip address dhcp$", "Gets the interface address from a DHCP server."),
    (r"no ip address$", "Removes any IPv4 address from the interface."),
    (r"ipv6 address (?P<a>\S+) link-local$", "Sets a fixed IPv6 link-local address ({a}) instead of the EUI-64 one, so next hops are easy to read."),
    (r"ipv6 address (?P<a>\S+)$", "Assigns the IPv6 address {a}."),
    (r"ipv6 unicast-routing$", "Turns on IPv6 routing (forwarding between interfaces and sending router advertisements)."),
    (r"no shutdown$", "Administratively enables the interface (interfaces created or left `shutdown` stay down until you do)."),
    (r"shutdown$", "Administratively disables the interface."),
    (r"no switchport$", "Turns the switch port into a routed (layer-3) port."),
    (r"switchport trunk encapsulation dot1q$", "Selects 802.1Q tagging for the trunk (needed on switches that also support ISL before `switchport mode trunk` is accepted)."),
    (r"switchport mode trunk$", "Makes the port a static 802.1Q trunk that carries multiple VLANs (no DTP negotiation needed on the other side)."),
    (r"switchport mode access$", "Makes the port a static access port that carries one VLAN, untagged."),
    (r"switchport access vlan (?P<v>\d+)$", "Places the access port in VLAN {v}."),
    (r"switchport trunk native vlan (?P<v>\d+)$", "Sets VLAN {v} as the trunk's native (untagged) VLAN; it must match on both ends or CDP reports a native VLAN mismatch."),
    (r"switchport trunk allowed vlan (?P<v>\S+)$", "Limits the trunk to VLANs {v}; other VLANs are pruned from this link."),
    (r"switchport nonegotiate$", "Stops sending DTP frames on the port (good practice on static trunks and access ports)."),
    (r"spanning-tree portfast( edge)?( trunk)?$", "Makes the port skip the listening/learning states (edge port toward a host); it still sends BPDUs and falls back if it receives one."),
    (r"spanning-tree bpduguard enable$", "Err-disables the port if a BPDU arrives, protecting the topology from rogue switches on edge ports."),
    (r"spanning-tree mode (?P<m>\S+)$", "Runs {m} spanning tree (Rapid PVST+ = one rapid 802.1w instance per VLAN, sub-second convergence)."),
    (r"spanning-tree vlan (?P<v>\S+) priority (?P<p>\d+)$", "Sets the bridge priority for VLAN(s) {v} to {p}; the lowest priority (then lowest MAC) wins the root bridge election."),
    (r"spanning-tree vlan (?P<v>\S+) root (?P<r>\S+)$", "Makes this switch the {r} root bridge for VLAN(s) {v} by lowering its priority."),
    (r"spanning-tree (vlan (?P<v>\S+) )?cost (?P<c>\d+)$", "Sets this port's spanning-tree path cost to {c}, steering which port becomes root or designated."),
    (r"spanning-tree (vlan (?P<v>\S+) )?port-priority (?P<p>\d+)$", "Sets this port's spanning-tree port priority ({p}); a lower value is preferred as the tie-breaker."),
    (r"vlan (?P<v>[\d,-]+)$", "Creates VLAN {v} in the VLAN database (a switch only forwards VLANs that exist)."),
    (r"name (?P<n>\S+)$", "Names the VLAN {n} (documentation; shows in `show vlan brief`)."),
    (r"channel-group (?P<g>\d+) mode active$", "Bundles the port into EtherChannel {g} with LACP in active mode (it sends LACP; active-active or active-passive forms the bundle)."),
    (r"channel-group (?P<g>\d+) mode passive$", "Bundles the port into EtherChannel {g} with LACP in passive mode (it only answers LACP; it needs an active partner)."),
    (r"channel-group (?P<g>\d+) mode desirable$", "Bundles the port into EtherChannel {g} with PAgP in desirable mode (it sends PAgP; desirable-desirable or desirable-auto forms the bundle)."),
    (r"channel-group (?P<g>\d+) mode auto$", "Bundles the port into EtherChannel {g} with PAgP auto (it only answers PAgP; it needs a desirable partner)."),
    (r"channel-group (?P<g>\d+) mode on$", "Forces the port into EtherChannel {g} without a negotiation protocol (both ends must be `on`)."),
    (r"port-channel load-balance (?P<m>\S+)$", "Hashes flows over the EtherChannel members by {m}, so different source/destination pairs use different links."),
    (r"lacp (port-)?priority (?P<p>\d+)$", "Sets the LACP priority to {p} (lower wins: decides which ports are active when more than the maximum are bundled)."),
    # OSPF
    (r"ip ospf (?P<p>\d+) area (?P<a>\S+)$", "Enables OSPF process {p} on this interface in area {a} (interface mode instead of a `network` statement): the subnet is advertised and hellos are sent."),
    (r"ip ospf network point-to-point$", "Uses the OSPF point-to-point network type: no DR/BDR election, faster adjacency; on a loopback it advertises the real prefix length instead of a /32."),
    (r"ip ospf network (?P<t>\S+)$", "Sets the OSPF network type to {t}, which decides DR election and hello timers; it must be compatible on both ends."),
    (r"ip ospf cost (?P<c>\d+)$", "Sets this interface's OSPF cost to {c}, overriding the bandwidth-based cost to steer path selection."),
    (r"ip ospf priority (?P<p>\d+)$", "Sets the OSPF DR election priority to {p} (0 = never DR/BDR, highest wins)."),
    (r"ip ospf hello-interval (?P<t>\d+)$", "Sets the OSPF hello interval to {t} s (must match the neighbor)."),
    (r"ip ospf dead-interval (?P<t>\d+)$", "Sets the OSPF dead interval to {t} s (must match the neighbor)."),
    (r"ip ospf authentication message-digest$", "Turns on OSPF MD5 authentication on this interface."),
    (r"ip ospf message-digest-key (?P<k>\d+) md5 \S+$", "Defines MD5 key {k} for OSPF on this interface (key ID and string must match the neighbor)."),
    (r"router ospf (?P<p>\d+)$", "Starts OSPFv2 process {p} (locally significant) and enters its configuration."),
    (r"router-id (?P<r>\S+)$", "Fixes the router ID at {r} instead of letting the router pick the highest loopback/interface address; it must be unique."),
    (r"area (?P<a>\S+) stub no-summary$", "Makes area {a} totally stubby (on the ABR): no external or inter-area LSAs inside, just a default route."),
    (r"area (?P<a>\S+) stub$", "Makes area {a} a stub area: no external (type 5) LSAs inside it, the ABR injects a default route instead. Every router in the area must agree."),
    (r"area (?P<a>\S+) nssa( (?P<o>.+))?$", "Makes area {a} not-so-stubby: no type 5 LSAs, but an ASBR inside may redistribute as type 7."),
    (r"area (?P<a>\S+) range (?P<n>\S+) (?P<m>\S+)$", "On the ABR, summarizes area {a}'s routes inside {n} {m} into one inter-area route for the other areas."),
    (r"area (?P<a>\S+) authentication message-digest$", "Requires MD5 authentication for all OSPF interfaces in area {a}."),
    (r"passive-interface default$", "Makes every interface passive by default (no hellos); enable the transit links with `no passive-interface`."),
    (r"no passive-interface (?P<i>\S+)$", "Sends hellos on {i} again (needed for adjacencies when passive-interface default is used)."),
    (r"passive-interface (?P<i>\S+)$", "Advertises {i}'s subnet but sends no hellos there, so no neighbor can form on it (loopbacks, user LANs)."),
    (r"passive-interface$", "Makes this interface passive: its subnet is advertised but no hellos are sent."),
    (r"network (?P<n>\S+) (?P<w>\S+) area (?P<a>\S+)$", "Enables OSPF in area {a} on every interface whose address falls inside {n} with wildcard {w}."),
    (r"default-information originate( always)?$", "Advertises a default route into the routing protocol (with `always` even when this router has none itself)."),
    (r"auto-cost reference-bandwidth (?P<b>\d+)$", "Raises the reference bandwidth to {b} Mbps so fast links get different costs (set it the same on every router)."),
    # EIGRP
    (r"router eigrp (?P<n>[A-Za-z]\S*)$", "Starts EIGRP in named mode (instance name {n}); everything for this AS is configured under one address family."),
    (r"router eigrp (?P<n>\d+)$", "Starts classic-mode EIGRP for autonomous system {n} (must match the neighbors)."),
    (r"address-family ipv4 unicast autonomous-system (?P<a>\d+)$", "Opens the EIGRP IPv4 address family for AS {a} (neighbors must use the same AS)."),
    (r"af-interface default$", "Settings for all interfaces in this address family unless an interface overrides them."),
    (r"af-interface (?P<i>\S+)$", "Settings for EIGRP on interface {i} only."),
    (r"authentication mode (?P<m>\S+)$", "Requires {m} authentication on EIGRP packets (neighbors must agree)."),
    (r"authentication key-chain (?P<k>\S+)$", "Uses the keys of key chain {k} to authenticate the routing protocol."),
    (r"exit-af-interface$", "Leaves the af-interface section."),
    (r"topology base$", "Enters the base topology: route-related EIGRP settings (redistribution, variance, distance)."),
    (r"exit-af-topology$", "Leaves the topology section."),
    (r"exit-address-family$", "Leaves the address family."),
    (r"network (?P<n>\S+) (?P<w>\S+)$", "Enables the routing protocol on interfaces whose address falls inside {n} with wildcard {w} and advertises those subnets."),
    (r"network (?P<n>\S+) mask (?P<m>\S+)$", "Advertises {n} {m} in BGP (the exact prefix must be in the routing table)."),
    (r"network (?P<n>\S+)$", "Advertises network {n} (BGP: the classful prefix must exist in the routing table)."),
    (r"eigrp router-id (?P<r>\S+)$", "Fixes the EIGRP router ID at {r}."),
    (r"eigrp stub( (?P<o>.+))?$", "Declares this router an EIGRP stub (advertising {o}): hubs do not query it, which keeps queries short and stops it being used for transit."),
    (r"variance (?P<v>\d+)$", "Allows unequal-cost load sharing over feasible successors whose metric is within {v}x of the best."),
    (r"key chain (?P<k>\S+)$", "Creates key chain {k}, a list of authentication keys that routing protocols can reference."),
    (r"key (?P<k>\d+)$", "Defines key number {k} in the chain (the key ID must match the neighbor's)."),
    (r"key-string \S+$", "Sets the key's secret string (must be identical on both ends)."),
    # BGP
    (r"router bgp (?P<a>\d+)$", "Starts BGP for autonomous system {a} (one BGP process per router)."),
    (r"bgp router-id (?P<r>\S+)$", "Fixes the BGP router ID at {r}."),
    (r"bgp log-neighbor-changes$", "Logs every BGP neighbor up/down event (useful when troubleshooting)."),
    (r"no bgp default ipv4-unicast$", "Stops activating every neighbor for IPv4 automatically; neighbors are activated per address family."),
    (r"neighbor (?P<n>\S+) remote-as (?P<a>\d+)$", "Defines BGP neighbor {n} in AS {a} (same AS as ours = iBGP, different = eBGP). The session is TCP 179."),
    (r"neighbor (?P<n>\S+) update-source (?P<i>\S+)$", "Sources the BGP session to {n} from {i} (so a loopback-to-loopback iBGP session survives a link failure)."),
    (r"neighbor (?P<n>\S+) next-hop-self$", "Rewrites the next hop to this router for routes sent to {n} (iBGP peers otherwise get an unreachable eBGP next hop)."),
    (r"neighbor (?P<n>\S+) ebgp-multihop( (?P<h>\d+))?$", "Allows the eBGP session to {n} over more than one hop (needed between loopbacks)."),
    (r"neighbor (?P<n>\S+) activate$", "Activates neighbor {n} in this address family so prefixes of this family are exchanged."),
    (r"neighbor (?P<n>\S+) send-community( (?P<t>\S+))?$", "Sends BGP communities to {n} (extended communities carry the VPN route targets)."),
    (r"neighbor (?P<n>\S+) route-reflector-client$", "Makes {n} a route-reflector client: iBGP routes are reflected to it, so a full iBGP mesh is not needed."),
    (r"neighbor (?P<n>\S+) password \S+$", "Protects the session to {n} with TCP MD5 authentication (same password on both sides)."),
    (r"neighbor (?P<n>\S+) route-map (?P<r>\S+) (?P<d>in|out)$", "Filters or changes the routes exchanged with {n} through route-map {r} (direction: {d})."),
    (r"neighbor (?P<n>\S+) (?P<k>.+)$", "Sets `{k}` for BGP neighbor {n}."),
    (r"address-family (?P<f>ipv4|ipv6|vpnv4|vpnv6|l2vpn)( (?P<x>.+))?$", "Enters the BGP {f} address family; neighbors and networks under it exchange only that kind of prefix."),
    (r"redistribute connected( (?P<o>.+))?$", "Redistributes connected subnets into this routing protocol."),
    (r"redistribute static( (?P<o>.+))?$", "Redistributes static routes into this routing protocol."),
    (r"redistribute (?P<p>eigrp|ospf|bgp|rip) (?P<n>\S+)( (?P<o>.+))?$", "Redistributes {p} {n} routes into this protocol (options: {o}). A seed metric and route-map/tags keep two-way redistribution loop-free."),
    # FHRP / tracking
    (r"standby version 2$", "Uses HSRP version 2 (group numbers up to 4095, IPv6 support, different multicast address)."),
    (r"standby (?P<g>\d+) ip (?P<a>\S+)$", "Joins HSRP group {g} with virtual IP {a}: hosts use it as their gateway, whichever router is active answers."),
    (r"standby (?P<g>\d+) priority (?P<p>\d+)$", "Sets this router's HSRP priority in group {g} to {p} (highest becomes active; default 100)."),
    (r"standby (?P<g>\d+) preempt$", "Lets this router take the active role back as soon as it has the highest priority."),
    (r"standby (?P<g>\d+) track (?P<t>\d+) decrement (?P<d>\d+)$", "Lowers the group {g} priority by {d} while track object {t} is down, so the standby router can take over."),
    (r"standby (?P<g>\d+) authentication md5 key-string \S+$", "Authenticates HSRP group {g} hellos with MD5 (same key on every router in the group), so a rogue device cannot become active."),
    (r"standby (?P<g>\d+) (?P<k>.+)$", "Sets `{k}` for HSRP group {g}."),
    (r"vrrp (?P<g>\d+) (?P<k>.+)$", "VRRP group {g}: `{k}`."),
    (r"glbp (?P<g>\d+) (?P<k>.+)$", "GLBP group {g}: `{k}`."),
    (r"track (?P<t>\d+) interface (?P<i>\S+) line-protocol$", "Track object {t} follows the line protocol of {i} (up/down), for HSRP, routes or EEM to react to."),
    (r"track (?P<t>\d+) ip sla (?P<s>\d+)( reachability)?$", "Track object {t} follows IP SLA operation {s}: down when the probe fails."),
    (r"track (?P<t>\d+) (?P<k>.+)$", "Track object {t}: `{k}`."),
    # ACL / NAT / VRF / PBR / route-maps
    (r"ip access-list standard (?P<n>\S+)$", "Creates the named standard ACL {n} (matches on source address only)."),
    (r"ip access-list extended (?P<n>\S+)$", "Creates the named extended ACL {n} (matches protocol, source, destination and ports)."),
    (r"(\d+ )?permit (?P<r>.+)$", "ACL entry: permits {r}. Entries are checked top-down, first match wins; an implicit deny follows the last line."),
    (r"(\d+ )?deny (?P<r>.+)$", "ACL entry: denies {r} (checked in order; put specific denies before broader permits)."),
    (r"(\d+ )?remark .+$", "Comment inside the ACL (documentation only)."),
    (r"ip access-group (?P<n>\S+) (?P<d>in|out)$", "Applies ACL {n} to packets {d}bound on this interface (one ACL per direction)."),
    (r"ip nat inside$", "Marks this interface as NAT inside (the private side)."),
    (r"ip nat outside$", "Marks this interface as NAT outside (the public side)."),
    (r"ip nat inside source list (?P<a>\S+) interface (?P<i>\S+) overload$", "PAT: translates inside sources matched by ACL {a} to {i}'s address, sharing it with port numbers (overload)."),
    (r"ip nat inside source static (?P<l>\S+) (?P<g>\S+)$", "Static NAT: inside host {l} is always seen outside as {g} (reachable from outside)."),
    (r"ip nat inside source static (?P<p>tcp|udp) (?P<l>\S+) (?P<lp>\d+) (?P<g>\S+) (?P<gp>\d+)$", "Static port forwarding: {p} {g}:{gp} outside goes to {l}:{lp} inside."),
    (r"ip nat inside source (?P<r>.+)$", "NAT rule: {r}."),
    (r"vrf definition (?P<v>\S+)$", "Creates VRF {v}: a separate routing table, so customers' addresses can overlap."),
    (r"rd (?P<r>\S+)$", "Sets the route distinguisher {r}, which makes this VRF's prefixes unique inside MP-BGP (VPNv4)."),
    (r"route-target export (?P<r>\S+)$", "Tags routes exported from this VRF with route target {r}."),
    (r"route-target import (?P<r>\S+)$", "Imports VPN routes tagged with route target {r} into this VRF."),
    (r"route-target both (?P<r>\S+)$", "Imports and exports route target {r}."),
    (r"vrf forwarding (?P<v>\S+)$", "Puts the interface into VRF {v} (this removes its IP address: configure the address after this line)."),
    (r"ip vrf forwarding (?P<v>\S+)$", "Puts the interface into VRF {v} (this removes its IP address: configure the address after this line)."),
    (r"ip route vrf (?P<v>\S+) (?P<n>\S+) (?P<m>\S+) (?P<h>.+)$", "Static route in VRF {v}: {n} {m} via {h}."),
    (r"ip route (?P<n>\S+) (?P<m>\S+) (?P<h>.+)$", "Static route: {n} {m} via {h} (a trailing number is the administrative distance, used for floating routes)."),
    (r"ipv6 route (?P<n>\S+) (?P<h>.+)$", "IPv6 static route to {n} via {h}."),
    (r"route-map (?P<r>\S+) (?P<a>permit|deny) (?P<s>\d+)$", "Route-map {r} sequence {s} ({a}): the match/set lines below apply to what this sequence matches; sequences are checked in order."),
    (r"match ip address prefix-list (?P<p>\S+)$", "Matches prefixes permitted by prefix list {p}."),
    (r"match ip address (?P<a>\S+)$", "Matches packets/routes permitted by ACL {a}."),
    (r"match tag (?P<t>\S+)$", "Matches routes carrying tag {t} (used to stop redistributed routes from coming back)."),
    (r"match interface (?P<i>\S+)$", "Matches routes whose next-hop interface is {i}."),
    (r"match (?P<k>.+)$", "Matches `{k}`."),
    (r"set transform-set (?P<t>\S+)$", "Uses transform set {t} for the traffic this profile/crypto map protects."),
    (r"set ip next-hop (?P<h>\S+)$", "Policy-based routing: sends matched packets to next hop {h} instead of following the routing table."),
    (r"set tag (?P<t>\S+)$", "Tags the routes with {t} so another router can recognize (and filter) them later."),
    (r"set (?P<k>.+)$", "Sets `{k}` on what the sequence matched."),
    (r"ip policy route-map (?P<r>\S+)$", "Applies policy-based routing with route-map {r} to packets arriving on this interface."),
    (r"ip prefix-list (?P<p>\S+) (seq \d+ )?(?P<a>permit|deny) (?P<n>.+)$", "Prefix list {p}: {a}s {n} (prefix plus optional ge/le length range)."),
    # IPsec / tunnels
    (r"crypto isakmp policy (?P<p>\d+)$", "IKEv1 phase 1 policy {p}: the parameters below must match a policy on the peer."),
    (r"encryption (?P<e>.+)$", "Phase 1 encryption: {e}."),
    (r"hash (?P<h>\S+)$", "Phase 1 integrity hash: {h}."),
    (r"authentication pre-share$", "Peers authenticate with a pre-shared key."),
    (r"group (?P<g>\d+)$", "Diffie-Hellman group {g} for the key exchange (14 = 2048-bit)."),
    (r"lifetime (?P<l>\d+)$", "Phase 1 SA lifetime {l} s."),
    (r"crypto isakmp key \S+ address (?P<a>\S+)$", "Pre-shared key for peer {a} (identical on both sides)."),
    (r"crypto ipsec transform-set (?P<t>\S+) (?P<x>.+)$", "Transform set {t}: protects the traffic with {x} (phase 2)."),
    (r"mode transport$", "Transport mode: only the payload is encrypted, the GRE header already provides the outer addresses (saves 20 bytes)."),
    (r"mode tunnel$", "Tunnel mode: the whole original packet is encrypted inside a new IP header."),
    (r"crypto ipsec profile (?P<p>\S+)$", "IPsec profile {p}: phase 2 settings that a tunnel interface can reference."),
    (r"set transform-set (?P<t>\S+)$", "Uses transform set {t}."),
    (r"tunnel source (?P<s>\S+)$", "The tunnel's outer source is {s}."),
    (r"tunnel destination (?P<d>\S+)$", "The tunnel's outer destination is {d} (must be reachable through the underlay)."),
    (r"tunnel mode (?P<m>.+)$", "Tunnel encapsulation: {m}."),
    (r"tunnel protection ipsec profile (?P<p>\S+)$", "Encrypts everything sent over the tunnel with IPsec profile {p} (no crypto map or ACL needed)."),
    (r"ip mtu (?P<m>\d+)$", "Sets the IP MTU to {m} bytes to leave room for tunnel/IPsec overhead."),
    (r"ip tcp adjust-mss (?P<m>\d+)$", "Rewrites the TCP MSS of SYN packets to {m} so TCP sessions avoid fragmentation."),
    # management services
    (r"ntp authentication-key (?P<k>\d+) md5 \S+$", "Defines NTP authentication key {k} (MD5)."),
    (r"ntp authenticate$", "Requires NTP authentication: only time from authenticated sources is accepted."),
    (r"ntp trusted-key (?P<k>\d+)$", "Trusts key {k} for NTP."),
    (r"ntp source (?P<i>\S+)$", "Sends NTP packets from {i}'s address."),
    (r"ntp master (?P<s>\d+)$", "Makes this router an authoritative NTP server at stratum {s} (from its own clock)."),
    (r"ntp server (?P<s>\S+)( key (?P<k>\d+))?( (?P<o>.+))?$", "Synchronizes the clock from NTP server {s} (authenticated with key {k} if given)."),
    (r"ntp peer (?P<s>\S+)$", "Symmetric NTP peering with {s}."),
    (r"service timestamps (?P<t>\S+) (?P<o>.+)$", "Stamps {t} messages with {o} (needed to correlate events across devices)."),
    (r"logging trap (?P<l>\S+)$", "Sends syslog messages of severity {l} and more severe to the syslog servers."),
    (r"logging host (?P<h>\S+)$", "Sends syslog to server {h}."),
    (r"logging source-interface (?P<i>\S+)$", "Sources syslog messages from {i}."),
    (r"logging buffered( (?P<o>.+))?$", "Keeps log messages in RAM (`show logging`)."),
    (r"snmp-server group (?P<g>\S+) v3 (?P<l>\S+)( (?P<o>.+))?$", "SNMPv3 group {g} with security level {l} (priv = authentication and encryption)."),
    (r"snmp-server user (?P<u>\S+) (?P<g>\S+) v3 (?P<o>.+)$", "SNMPv3 user {u} in group {g} with its authentication and privacy keys."),
    (r"snmp-server community \S+ (?P<a>\S+)( (?P<o>.+))?$", "SNMPv2c community string with {a} access."),
    (r"snmp-server (?P<k>.+)$", "SNMP: `{k}`."),
    # IP SLA
    (r"ip sla (?P<s>\d+)$", "Creates IP SLA operation {s}: a synthetic probe the router runs itself."),
    (r"icmp-echo (?P<d>\S+)( source-interface (?P<i>\S+))?$", "The probe pings {d} (from {i})."),
    (r"frequency (?P<f>\d+)$", "Runs the probe every {f} s."),
    (r"timeout (?P<t>\d+)$", "Waits {t} ms for each reply."),
    (r"threshold (?P<t>\d+)$", "Reports over-threshold when the round trip exceeds {t} ms."),
    (r"ip sla schedule (?P<s>\d+) (?P<o>.+)$", "Starts IP SLA operation {s} ({o})."),
    # multicast / MPLS
    (r"ip multicast-routing( distributed)?$", "Turns on IPv4 multicast forwarding (without it PIM does nothing)."),
    (r"ip pim sparse-mode$", "Runs PIM sparse mode on the interface: multicast is forwarded only where receivers joined, via the RP."),
    (r"ip pim rp-address (?P<r>\S+)( (?P<o>.+))?$", "Statically sets the rendezvous point to {r}."),
    (r"ip pim bsr-candidate (?P<o>.+)$", "Offers this router as bootstrap router ({o}); the BSR floods the RP-set to all PIM routers."),
    (r"ip pim rp-candidate (?P<o>.+)$", "Offers this router as candidate RP ({o})."),
    (r"ip pim ssm default$", "Enables source-specific multicast for 232.0.0.0/8 (receivers join (S,G) directly, no RP needed)."),
    (r"ip pim (?P<k>.+)$", "PIM: `{k}`."),
    (r"ip igmp join-group (?P<g>\S+)( source (?P<s>\S+))?$", "Makes the router act as a receiver of group {g} (it answers pings to the group, handy for testing)."),
    (r"ip igmp version (?P<v>\d)$", "Uses IGMPv{v} on the interface (v3 is needed for SSM)."),
    (r"ip igmp (?P<k>.+)$", "IGMP: `{k}`."),
    (r"mpls ldp router-id (?P<i>\S+)( force)?$", "Uses {i}'s address as the LDP router ID (and transport address), so LDP sessions run between loopbacks."),
    (r"mpls ip$", "Enables MPLS forwarding and LDP on the interface (labels are exchanged with LDP neighbors on it)."),
    (r"mpls label protocol ldp$", "Uses LDP to distribute labels."),
    (r"mpls (?P<k>.+)$", "MPLS: `{k}`."),
    # misc
    (r"ip routing$", "Turns on IPv4 routing between interfaces."),
    (r"no ip routing$", "Turns off routing: the device behaves like a host."),
    (r"ip default-gateway (?P<g>\S+)$", "Default gateway {g} when IP routing is off."),
    (r"hostname (?P<h>\S+)$", "Sets the device name to {h}."),
    (r"ip domain[ -]name (?P<d>\S+)$", "Sets the DNS domain name {d} (needed for RSA keys)."),
    (r"username (?P<u>\S+) (?P<o>.+)$", "Creates local user {u}."),
    (r"ip helper-address (?P<a>\S+)$", "DHCP relay: forwards client broadcasts from this subnet to the server {a} as unicast."),
    (r"ip dhcp pool (?P<p>\S+)$", "Creates DHCP pool {p}."),
    (r"ip dhcp excluded-address (?P<o>.+)$", "Never hands out {o} (reserved for static use)."),
    (r"default-router (?P<g>\S+)$", "DHCP option 3: clients get {g} as their gateway."),
    (r"dns-server (?P<s>.+)$", "DHCP option 6: DNS server {s}."),
    (r"bandwidth (?P<b>\d+)$", "Sets the interface bandwidth to {b} kbps for routing metrics and QoS (it does not change the speed)."),
    (r"delay (?P<d>\d+)$", "Sets the interface delay to {d} tens of microseconds (an EIGRP metric component)."),
    (r"distance (?P<o>.+)$", "Changes the administrative distance: {o}."),
    (r"maximum-paths (?P<n>\d+)$", "Installs up to {n} equal-cost paths."),
    (r"exit$", "Leaves the current configuration sub-mode."),
]
_GLOSS = [(re.compile(p), t) for p, t in GLOSSARY]


def explain_line(line: str) -> str | None:
    s = line.strip()
    for rx, tmpl in _GLOSS:
        m = rx.fullmatch(s)
        if m:
            vals = {k: (v or "") for k, v in m.groupdict().items()}
            vals = {k: v.strip() for k, v in vals.items()}
            try:
                return tmpl.format(**vals).replace(" ()", "").replace("(from )", "").replace(" (options: )", "")
            except (KeyError, IndexError):
                return tmpl
    return None


def unexplained(cfg: str) -> list[str]:
    return [ln.strip() for ln in cfg.splitlines() if ln.strip() and not ln.strip().startswith("!") and explain_line(ln) is None]


def explain_block(cfg: str) -> str:
    """Markdown bullets: one per config line (sub-mode lines indented under their parent)."""
    out = []
    for ln in cfg.splitlines():
        if not ln.strip() or ln.strip().startswith("!"):
            continue
        txt = explain_line(ln) or "See the command reference for this line."
        out.append(f"- `{ln.strip()}`: {txt}")
    return "\n".join(out)


# ---------------------------------------------------------------- derive / load a guide for a challenge lab
_TOP = re.compile(r"^(\S.*)$")


def _verify_for_config(dev: str, cfg: str) -> list[dict]:
    """`show running-config` views of what the device step typed."""
    out, seen = [], set()
    for ln in cfg.splitlines():
        m = _TOP.match(ln)
        if not m or ln.startswith("!"):
            continue
        head = m.group(1).strip()
        if head.startswith("interface "):
            cmd = f"show running-config {head}"
        elif head.split()[0] in ("router", "vrf", "key", "crypto", "ip", "route-map", "track", "ntp", "snmp-server",
                                 "logging", "vlan", "spanning-tree", "port-channel", "mpls", "service"):
            sec = " ".join(head.split()[:2]) if head.split()[0] in ("router", "ip", "crypto", "route-map", "vrf", "key") \
                else head.split()[0]
            cmd = f"show running-config | section {sec}"
        else:
            cmd = f"show running-config | include {head.split()[0]}"
        if cmd in seen:
            continue
        seen.add(cmd)
        out.append({"device": dev, "command": cmd,
                    "expect": f"The `{head}` lines you just typed (IOS may show them in its own order or with defaults added)."})
    return out[:6]


def _excerpt(check: Check, output: str | None) -> str:
    if not output:
        return ""
    lines = output.splitlines()
    keep: list[int] = []
    for rx in check.match:
        try:
            r = re.compile(rx, re.M)
        except re.error:
            continue
        for i, ln in enumerate(lines):
            if r.search(ln) and i not in keep:
                keep.append(i)
                break
    if check.min_success:
        keep += [i for i, ln in enumerate(lines) if "Success rate" in ln and i not in keep]
    if not keep:
        return ""
    return "\n".join(lines[i] for i in sorted(keep))


def _expect(check: Check, fixture: dict) -> str:
    parts = []
    if check.description:
        parts.append(check.description.rstrip(".") + ".")
    if check.min_success:
        parts.append(f"Success rate of at least {check.min_success} percent.")
    ex = _excerpt(check, (fixture.get(check.device) or {}).get(check.command))
    if ex:
        parts.append("Look for:\n```\n" + ex + "\n```")
    elif check.match and not check.min_success:
        parts.append("Look for: " + "; ".join(f"`{_readable(r)}`" for r in check.match[:3]) + ".")
    if check.absent:
        parts.append("It must **not** show: " + "; ".join(f"`{_readable(r)}`" for r in check.absent[:3]) + ".")
    if check.hint:
        parts.append(f"If it does not: {check.hint}")
    return "\n\n".join(parts) or "The command succeeds."


def _readable(rx: str) -> str:
    s = re.sub(r"\\s[+*]|\\s", " ", rx)
    s = re.sub(r"\(\?:?[^)]*\)\??", "", s) if len(s) > 60 else s
    s = s.replace("\\.", ".").replace("\\d+", "N").replace("\\S+", "x").replace("^", "").replace("$", "").replace("\\b", "")
    return re.sub(r"\s+", " ", s).strip().replace("`", "'")


def derive(lab: Lab, solution: dict[str, str], fixture: dict | None = None) -> list[dict]:
    """guide.yaml-shaped steps for a challenge lab, from its reference solution, checks and solved fixture."""
    fixture = fixture or {}
    order = [n.name for n in lab.nodes if n.name in solution] + [d for d in solution if d not in {n.name for n in lab.nodes}]
    steps = []
    for i, dev in enumerate(order, 1):
        cfg = solution[dev].strip("\n") + "\n"
        cfg_checks = [c.id for c in lab.checks if c.mode == "config" and c.device == dev]
        steps.append({
            "id": f"cfg-{dev.lower()}",
            "title": f"Configure {dev}",
            "explain": (f"On **{dev}**, enter global configuration mode (`configure terminal`) and type the lines below "
                        f"(or paste them). Indented lines belong to the line above them.\n\n" + explain_block(cfg) +
                        ("\n\nSome protocols only come up once the neighbors are configured too: the end-to-end checks "
                         "are in the last step." if i < len(order) else "")),
            "config": {dev: cfg},
            "verify": _verify_for_config(dev, cfg),
            "checks": cfg_checks})
    live = [c for c in lab.checks if c.mode == "live"]
    if live:
        steps.append({
            "id": "verify",
            "title": "Verify end to end",
            "explain": ("Every device is configured. Run each command below on the device shown and compare it with "
                        "the expected output, then click **Check this step**. If a check fails, its hint tells you "
                        "where to look; re-read the step for that device."),
            "verify": [{"device": c.device, "command": c.command, "expect": _expect(c, fixture)} for c in live],
            "checks": [c.id for c in live]})
    return steps


def read_sidecar(text: str) -> list[dict]:
    d = yaml.safe_load(text) or {}
    if not isinstance(d, dict) or not isinstance(d.get("steps"), list):
        raise GuideError("guide.yaml must be a mapping with a `steps:` list")
    return d["steps"]


def dump_sidecar(steps: list[dict], note: str = "") -> str:
    from .ai import to_yaml_text
    head = ("# Walkthrough mode for this challenge lab (CML Lab Builder 3.3.7+; older apps ignore this file).\n"
            "# Each step: id, title, explain (Markdown), config (device -> exact lines), verify (device, command, expect),\n"
            "# checks (ids of this lab's checks). Scaffold with `cmllab guide <lab folder> --write`.\n")
    return head + (f"# {note}\n" if note else "") + to_yaml_text({"steps": steps})


def steps_from(lab: Lab, raw: list[dict]) -> list[Step]:
    """guide.yaml steps -> Step objects (check ids resolved against the lab's checks). Raises GuideError."""
    by_id = {c.id: c for c in lab.checks}
    out, seen, errs = [], set(), []
    for k, s in enumerate(raw):
        if not isinstance(s, dict):
            raise GuideError(f"guide step {k + 1} must be a mapping")
        unknown = set(s) - {"id", "title", "explain", "config", "verify", "checks", "optional", "apply"}
        if unknown:
            errs.append(f"guide step {s.get('id', k + 1)}: unknown keys {sorted(unknown)}")
        ids = s.get("checks") or []
        missing = [c for c in ids if c not in by_id]
        if missing:
            errs.append(f"guide step {s.get('id', k + 1)}: unknown check ids {missing}")
        if s.get("id") in seen:
            errs.append(f"guide step id {s.get('id')!r} is used twice")
        seen.add(s.get("id"))
        for d in (s.get("config") or {}):
            if d not in {n.name for n in lab.nodes}:
                errs.append(f"guide step {s.get('id')}: config for unknown device {d!r}")
        if errs:
            continue
        try:
            out.append(Step(id=s.get("id"), title=s.get("title"), explain=s.get("explain") or "",
                            config={d: str(c) for d, c in (s.get("config") or {}).items()},
                            verify=[Verify(**v) for v in (s.get("verify") or [])],
                            checks=[by_id[c] for c in ids], optional=bool(s.get("optional", False)),
                            apply=bool(s.get("apply", True))))
        except Exception as e:  # pydantic ValidationError and friends
            errs.append(f"guide step {s.get('id', k + 1)}: {e}")
    if errs:
        raise GuideError("; ".join(errs))
    return out


def problems(lab: Lab, steps: list[Step]) -> list[str]:
    """Walkthrough content the library requires on every step (both native walkthroughs and guides)."""
    errs = []
    if not steps:
        return ["no walkthrough steps"]
    for st in steps:
        if not st.explain.strip():
            errs.append(f"step {st.id}: no explanation")
        if not st.config and not st.verify:
            errs.append(f"step {st.id}: no commands (config or verify) to show")
        for v in st.verify:
            if not v.expect.strip():
                errs.append(f"step {st.id}: verify `{v.command}` has no expected output")
    covered = {c.id for st in steps for c in st.checks}
    if not lab.is_walkthrough:
        left = [c.id for c in lab.checks if c.id not in covered]
        if left:
            errs.append(f"checks not in any guide step: {left}")
    return errs


def guide_steps(lab: Lab, folder: Path | None, solution: dict[str, str] | None = None,
                fixture: dict | None = None, text: str | None = None) -> tuple[list[Step], str]:
    """(steps, source) for a challenge lab: source 'guide.yaml' or 'derived'."""
    if text is None and folder is not None and (folder / SIDECAR).is_file():
        text = (folder / SIDECAR).read_text(encoding="utf-8")
    if text:
        return steps_from(lab, read_sidecar(text)), SIDECAR
    if solution is None and folder is not None:
        from .catalog import parse_solution_cfg
        f = folder / "solution.cfg"
        solution = parse_solution_cfg(f.read_text(encoding="utf-8")) if f.is_file() else dict(lab.solution or {})
    if fixture is None and folder is not None and (folder / "fixture_solved.yaml").is_file():
        fixture = yaml.safe_load((folder / "fixture_solved.yaml").read_text(encoding="utf-8")) or {}
    return steps_from(lab, derive(lab, solution or {}, fixture)), "derived"


# ---------------------------------------------------------------- the lab in the other shape
def as_walkthrough(lab: Lab, steps: list[Step]) -> Lab:
    intro = ("**Walkthrough mode.** Every step shows the exact commands per device, what each one does and what "
             "good verification output looks like. Checks still run. Switch to Challenge mode on the lab page to "
             "solve it on your own instead.\n\n")
    return lab.model_copy(update={"type": "walkthrough", "steps": steps, "checks": [], "faults": [],
                                  "task": intro + lab.task})


def as_challenge(lab: Lab) -> Lab:
    goals = "\n".join(f"{i}. {st.title}{' (optional)' if st.optional else ''}" for i, st in enumerate(lab.steps, 1))
    task = ("**Challenge mode.** The step-by-step commands are hidden: build it from the goals below and click Check. "
            "Hints and the full solution are available as in every challenge.\n\n" + lab.task.rstrip() +
            "\n\n## Goals\n\n" + goals + "\n")
    return lab.model_copy(update={"type": "challenge", "task": task, "steps": [],
                                  "checks": [c for st in lab.steps for c in st.checks],
                                  "solution": lab.step_solution()})


def effective(lab: Lab, folder: Path | None, mode: str | None) -> Lab:
    """The lab as the student sees it in `mode` (None or the lab's own type: unchanged)."""
    if mode is None or mode == lab.type:
        return lab
    if mode == "challenge":
        return as_challenge(lab)
    steps, _ = guide_steps(lab, folder)
    return as_walkthrough(lab, steps)
