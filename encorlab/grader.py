"""Grade a lab by running read-only show/ping commands and matching regexes."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Callable, Protocol

from .platforms import Platform, render
from .schema import Check, Lab

PING_RE = re.compile(r"Success rate is (\d+) percent")


class Runner(Protocol):
    """Live mode: runs a command on a device console."""
    def run(self, device: str, command: str) -> str: ...


class ConfigSource(Protocol):
    """Config mode: returns a device's running configuration."""
    def get_config(self, device: str) -> str: ...


CONFIG_NOTE = ("Config mode checks the running configuration only (fetched through the CML API over HTTPS). "
               "It cannot verify neighbor adjacencies, learned routes or reachability.")


@dataclass
class CheckResult:
    id: str
    description: str
    device: str
    command: str
    passed: bool
    points: int
    earned: int
    details: list[str] = field(default_factory=list)
    hint: str = ""
    output: str = ""


@dataclass
class GradeReport:
    lab_id: str
    platform: str
    results: list[CheckResult]
    mode: str = "live"
    notes: list[str] = field(default_factory=list)

    @property
    def earned(self) -> int:
        return sum(r.earned for r in self.results)

    @property
    def total(self) -> int:
        return sum(r.points for r in self.results)

    @property
    def score_pct(self) -> float:
        return round(100.0 * self.earned / self.total, 1) if self.total else 0.0

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def to_dict(self) -> dict:
        return {
            "lab_id": self.lab_id, "platform": self.platform, "mode": self.mode, "notes": self.notes,
            "earned": self.earned,
            "total": self.total, "score_pct": self.score_pct, "passed": self.passed,
            "results": [asdict(r) for r in self.results],
        }


def evaluate(check: Check, output: str, platform: Platform) -> tuple[bool, list[str]]:
    details: list[str] = []
    ok = True
    if check.min_success is not None:
        m = PING_RE.search(output)
        rate = int(m.group(1)) if m else 0
        good = rate >= check.min_success
        details.append(f"ping success {rate}% (need >= {check.min_success}%)" + ("" if good else " - FAIL"))
        ok &= good
    for pat in check.match:
        p = render(pat, platform)
        good = re.search(p, output, re.M) is not None
        details.append(("found: " if good else "missing: ") + p)
        ok &= good
    for pat in check.absent:
        p = render(pat, platform)
        bad = re.search(p, output, re.M) is not None
        details.append(("unexpected: " if bad else "absent as required: ") + p)
        ok &= not bad
    return ok, details


def grade(lab: Lab, runner, platform: Platform,
          progress: Callable[[str], None] | None = None, mode: str = "live") -> GradeReport:
    """mode='live': runner.run(device, cmd); mode='config': runner.get_config(device)."""
    if mode not in ("live", "config"):
        raise ValueError(f"unknown grading mode {mode!r}")
    results = []
    configs: dict[str, str] = {}
    for c in lab.checks_for(mode):
        cmd = render(c.command, platform) if mode == "live" else "(running-config via CML API)"
        if progress:
            progress(f"{c.device}: {cmd}")
        try:
            if mode == "live":
                out = runner.run(c.device, cmd)
            else:
                if c.device not in configs:
                    configs[c.device] = runner.get_config(c.device)
                out = configs[c.device]
            ok, details = evaluate(c, out, platform)
        except Exception as e:  # device unreachable, timeout, ...
            out, ok, details = "", False, [f"error running command: {type(e).__name__}: {e}"]
        results.append(CheckResult(
            id=c.id, description=render(c.description, platform), device=c.device, command=cmd,
            passed=ok, points=c.points, earned=c.points if ok else 0,
            details=details, hint="" if ok else render(c.hint, platform), output=out[-4000:],
        ))
    return GradeReport(lab.id, platform.name, results, mode=mode,
                       notes=[CONFIG_NOTE] if mode == "config" else [])
