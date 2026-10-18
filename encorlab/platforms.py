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


def get(name: str) -> Platform:
    try:
        return PLATFORMS[name]
    except KeyError:
        raise ValueError(f"unknown platform {name!r}; choose from {sorted(PLATFORMS)}")
