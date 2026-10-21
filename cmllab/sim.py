"""Offline device simulator used by tests and `cmllab selftest`.
Serves 'show running-config' (incl. '| include', '| section', 'interface X')
from initial config (+ solution.cfg when solved) and other commands from
recorded/synthesized fixture output."""
from __future__ import annotations

import re

from . import catalog
from .platforms import Platform, render
from .render import node_config
from .schema import Lab

PING_FAIL = "Type escape sequence to abort.\nSending 5, 100-byte ICMP Echos:\n.....\nSuccess rate is 0 percent (0/5)\n"


def blocks(config: str) -> list[list[str]]:
    out: list[list[str]] = []
    for line in config.splitlines():
        if not line.strip() or line.strip() == "!":
            continue
        if line.startswith(" ") and out:
            out[-1].append(line)
        else:
            out.append([line])
    return out


def section(config: str, pattern: str) -> str:
    rx = re.compile(pattern)
    res = []
    for b in blocks(config):
        if rx.search(b[0]):
            res.extend(b)
        else:
            res.extend(l for l in b[1:] if rx.search(l))
    return "\n".join(res) + ("\n" if res else "")


def include(config: str, pattern: str) -> str:
    rx = re.compile(pattern)
    return "".join(l + "\n" for l in config.splitlines() if rx.search(l))


def interface(config: str, name: str) -> str:
    res = []
    for b in blocks(config):
        if b[0].strip().lower() == f"interface {name}".lower():
            res.extend(b)
    return "Building configuration...\n\n" + "\n".join(res) + "\nend\n"


class SimRunner:
    def __init__(self, lab: Lab, platform: Platform, solved: bool,
                 solution: dict | None = None, fixtures: dict | None = None, extra: dict | None = None):
        """solution/fixtures default to the catalog's files for lab.id.
        fixtures = {"solved": {...}, "blank": {...}} when given explicitly.
        extra = device -> config applied after the solution (e.g. a fault), merged IOS-style."""
        self.lab = lab
        self.platform = platform
        if solution is None:
            solution = catalog.load_solution(lab.id)
        sol = solution if solved else {}
        self.running = {}
        for n in lab.nodes:
            if extra:
                from .iosmerge import merge
                self.running[n.name] = merge(node_config(lab, n.name, platform), render(sol.get(n.name, ""), platform),
                                             render(extra.get(n.name, ""), platform))
                continue
            cfg = node_config(lab, n.name, platform).replace("\nend\n", "\n")
            cfg += render(sol.get(n.name, ""), platform)
            self.running[n.name] = cfg
        state = "solved" if solved else "blank"
        fx = (fixtures or {}).get(state, {}) if fixtures is not None else catalog.load_fixture(lab.id, state)
        self.fixture = {dev: {render(k, platform): render(v, platform) for k, v in cmds.items()}
                        for dev, cmds in fx.items()}

    def get_config(self, device: str) -> str:
        if device not in self.running:
            raise KeyError(f"unknown device {device}")
        return "Building configuration...\n\n" + self.running[device] + "end\n"

    def run(self, device: str, command: str) -> str:
        if device not in self.running:
            raise KeyError(f"unknown device {device}")
        cmd = command.strip()
        cfg = self.running[device]
        if cmd.startswith("show running-config"):
            rest = cmd[len("show running-config"):].strip()
            if rest.startswith("| section "):
                return section(cfg, rest[len("| section "):])
            if rest.startswith("| include "):
                return include(cfg, rest[len("| include "):])
            if rest.startswith("interface "):
                return interface(cfg, rest[len("interface "):])
            return cfg
        out = self.fixture.get(device, {}).get(cmd)
        if out is not None:
            return out
        return PING_FAIL if cmd.startswith("ping") else ""
