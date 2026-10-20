"""Platform profiles: map abstract node kinds and port indexes to CML node
definitions and IOS interface names (verified against CML community lab files:
IOL/IOL-L2 use Ethernet0/0..0/3 on slots 0..3; IOSv/IOSvL2 use GigabitEthernet0/0..)."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_PORTS = 4  # stay within the default interface count of every profile


@dataclass(frozen=True)
class Platform:
    name: str
    router: str
    switch: str
    long_prefix: str
    short_prefix: str

    def node_definition(self, kind: str) -> str:
        return {"router": self.router, "switch": self.switch}[kind]

    def ifname(self, idx: int, short: bool = False) -> str:
        if not 0 <= idx < MAX_PORTS:
            raise ValueError(f"port index {idx} out of range 0..{MAX_PORTS - 1}")
        return f"{self.short_prefix if short else self.long_prefix}0/{idx}"


PLATFORMS = {
    "iol": Platform("iol", "iol-xe", "ioll2-xe", "Ethernet", "Et"),
    "iosv": Platform("iosv", "iosv", "iosvl2", "GigabitEthernet", "Gi"),
}

_PH = re.compile(r"%if(\d)(s?)%")


def render(text: str, platform: Platform) -> str:
    """Replace %ifN% (long name) and %ifNs% (short name) placeholders."""
    return _PH.sub(lambda m: platform.ifname(int(m.group(1)), bool(m.group(2))), text)


def placeholders(text: str) -> set[int]:
    return {int(m.group(1)) for m in _PH.finditer(text)}


@dataclass(frozen=True)
class NodeDef:
    """An explicit CML node definition a lab node can ask for (`definition:` in lab.yaml) instead of the
    platform profile's router/switch. Port index p maps to the interface at CML slot p + first_slot."""
    id: str
    os: str                      # "nxos" | "ios"
    long_prefix: str             # data port p -> f"{long_prefix}{p + first_port}"
    short_prefix: str
    first_port: int
    first_slot: int              # CML slot of data port 0 (slot 0 is mgmt0 on NX-OS)
    mgmt: str = ""               # interface at slot 0, created unconnected (keeps the slots contiguous)
    boot_s: int = 0              # minimum boot timeout for labs using this node type

    def ifname(self, idx: int, short: bool = False) -> str:
        if not 0 <= idx < MAX_PORTS:
            raise ValueError(f"port index {idx} out of range 0..{MAX_PORTS - 1}")
        return f"{self.short_prefix if short else self.long_prefix}{idx + self.first_port}"


# CML 2.9 reference platform nxosv9000 (Nexus 9300v 10.5(3)F on the 2.9 refplat ISO): mgmt0, Ethernet1/1..1/64.
DEFINITIONS = {
    "nxosv9000": NodeDef("nxosv9000", "nxos", "Ethernet1/", "Eth1/", 1, 1, mgmt="mgmt0", boot_s=1500),
}


def node_def(name: str | None) -> NodeDef | None:
    if not name:
        return None
    try:
        return DEFINITIONS[name]
    except KeyError:
        raise ValueError(f"unknown node definition {name!r}; supported: {sorted(DEFINITIONS)}")


def get(name: str) -> Platform:
    try:
        return PLATFORMS[name]
    except KeyError:
        raise ValueError(f"unknown platform {name!r}; choose from {sorted(PLATFORMS)}")
