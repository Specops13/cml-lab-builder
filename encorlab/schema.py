"""Lab definition schema (one lab.yaml per lab) + semantic validation."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .templates import expand_check

from .platforms import MAX_PORTS, PLATFORMS, placeholders

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,30}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Node(_Strict):
    """A router or switch. `config` is the starting config (hostname is added automatically)."""
    name: str = Field(description="Node label/hostname: letter first, then letters/digits/_/-, max 31 chars (e.g. R1, SW1)")
    kind: Literal["router", "switch"] = Field(description="router -> iol-xe / iosv; switch -> ioll2-xe / iosvl2")
    x: int = Field(default=0, description="Canvas X position in CML")
    y: int = Field(default=0, description="Canvas Y position in CML")
    config: str = Field(description="Starting IOS config (no hostname line needed). Use %if0%..%if3% for data interfaces")

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if not _NAME.match(v):
            raise ValueError(f"invalid node name {v!r}")
        return v


class Endpoint(_Strict):
    node: str = Field(description="Node name")
    port: int = Field(ge=0, lt=MAX_PORTS, description="Data port index 0-3 (= %if0%..%if3%)")


class Link(_Strict):
    a: Endpoint
    b: Endpoint


class Check(_Strict):
    """A grading check. Either give command/match/absent/min_success directly, or a
    `template` + `params` (see LAB-AUTHORING.md)."""
    id: str
    description: str = ""
    device: str
    mode: Literal["live", "config"] = Field(default="live", description="live = show/ping over the device console; config = regex on the running config fetched via the CML API")
    command: str = Field(default="", description="live only: read-only 'show ...' or 'ping ...' command")
    match: list[str] = Field(default=[], description="Python regexes (multiline: ^ and $ match per line) that must ALL match")
    absent: list[str] = Field(default=[], description="Python regexes that must NOT match")
    min_success: int | None = Field(default=None, ge=1, le=100, description="live ping checks: minimum 'Success rate is N percent'")
    points: int = Field(default=1, ge=1)
    hint: str = Field(default="", description="Shown to the student when the check fails")
    template: str | None = Field(default=None, description="Optional check template (see LAB-AUTHORING.md)")
    params: dict | None = Field(default=None, description="Parameters for the template")

    @model_validator(mode="before")
    @classmethod
    def _expand_template(cls, data):
        return expand_check(data)

    @model_validator(mode="after")
    def _shape(self):
        if not self.description.strip():
            raise ValueError(f"check {self.id}: description is required")
        if self.min_success is None and not (self.match or self.absent):
            raise ValueError(f"check {self.id}: needs match/absent or min_success")
        if self.mode == "config":
            if self.command or self.min_success is not None:
                raise ValueError(f"check {self.id}: config checks take no command/min_success (they match the running config)")
        else:
            if self.min_success is not None and not self.command.strip().startswith("ping"):
                raise ValueError(f"check {self.id}: min_success requires a ping command")
            if not self.command.strip().startswith(("show ", "ping ")):
                raise ValueError(f"check {self.id}: only read-only 'show'/'ping' commands allowed")
        for p in self.match + self.absent:
            try:
                re.compile(p, re.M)
            except re.error as e:
                raise ValueError(f"check {self.id}: bad regex {p!r}: {e}")
        return self


class Fault(_Strict):
    """A predefined fault for "Break my lab": applied on top of a working (solved) lab so the student
    gets a realistic trouble ticket. `config` is IOS config applied after the solution (use `no ...`
    to remove lines). Optional `checks` are graded in addition to the lab checks while the fault is active."""
    id: str = Field(description="Short unique id, e.g. 'r2-wrong-key'")
    title: str = Field(description="Short name of the fault (shown after it is fixed)")
    ticket: str = Field(description="Symptom-only trouble ticket shown to the student (never the cause)")
    device: str = Field(description="Device the fault is applied to")
    config: str = Field(description="IOS config applied after the solution, e.g. 'interface %if0%\\n shutdown'")
    explanation: str = Field(description="Markdown: root cause and the exact fix, shown after the fault is fixed or revealed")
    hints: list[str] = Field(default=[], description="Progressive hints for this fault, vaguest first")
    checks: list[Check] = Field(default=[], description="Extra checks graded while this fault is active")

    @field_validator("id")
    @classmethod
    def _fid(cls, v):
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,40}$", v):
            raise ValueError("fault id must be lowercase letters, digits, dashes")
        return v


class Lab(_Strict):
    """One ENCOR practice lab."""
    id: str = Field(description="Lowercase id: letters, digits, dashes (2-41 chars). Also the folder name")
    title: str
    blueprint: list[str] = Field(description="ENCOR 350-401 v1.2 blueprint items, e.g. ['3.2.b']")
    domain: str = Field(description="Blueprint domain, e.g. '3.0 Infrastructure - Layer 3'")
    difficulty: int = Field(ge=1, le=5, description="1 (easy) to 5 (hard)")
    platforms: list[Literal["iol", "iosv"]] = Field(default=["iol", "iosv"], description="Image profiles the lab supports")
    summary: str = Field(description="One-line summary for the catalog")
    nodes: list[Node]
    links: list[Link]
    task: str = Field(description="Markdown task text shown to the student")
    checks: list[Check] = Field(description="Needs at least one live and one config check")
    solution: dict[str, str] | None = Field(default=None, description="Optional reference solution: device -> config lines")
    solution_summary: str = Field(default="", description=(
        "Markdown shown after the lab is solved (or on 'Reveal solution'): the root cause / what was missing, "
        "the exact fix commands per device, and briefly why it works. Required for new labs; if empty the app "
        "generates a fallback from `solution`"))
    hints: list[str] = Field(default=[], description=(
        "Ordered progressive hints (vague first, most specific last), revealed one at a time with the Hint button. "
        "Never paste the full answer into a hint. If empty, the per-check hints are used in check order"))
    faults: list[Fault] = Field(default=[], description=(
        "Optional predefined faults for 'Break my lab' (random troubleshooting practice on the solved lab)"))
    author: str = ""
    version: str = "1"

    @model_validator(mode="before")
    @classmethod
    def _drop_schema_key(cls, data):
        if isinstance(data, dict) and "$schema" in data:
            data = {k: v for k, v in data.items() if k != "$schema"}
        return data

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,40}$", v):
            raise ValueError("lab id must be lowercase letters, digits, dashes")
        return v

    @model_validator(mode="after")
    def _semantics(self):
        errs = []
        names = [n.name for n in self.nodes]
        if len(set(names)) != len(names):
            errs.append("duplicate node names")
        for p in self.platforms:
            if p not in PLATFORMS:
                errs.append(f"unknown platform {p}")
        used: set[tuple[str, int]] = set()
        for ln in self.links:
            for ep in (ln.a, ln.b):
                if ep.node not in names:
                    errs.append(f"link references unknown node {ep.node}")
                if (ep.node, ep.port) in used:
                    errs.append(f"port {ep.node}:{ep.port} used twice")
                used.add((ep.node, ep.port))
            if ln.a.node == ln.b.node:
                errs.append("self-link not allowed")
        ids = [c.id for c in self.checks]
        if len(set(ids)) != len(ids):
            errs.append("duplicate check ids")
        for c in self.checks:
            if c.device not in names:
                errs.append(f"check {c.id} references unknown device {c.device}")
        for dev in (self.solution or {}):
            if dev not in names:
                errs.append(f"solution references unknown device {dev}")
        fids = [f.id for f in self.faults]
        if len(set(fids)) != len(fids):
            errs.append("duplicate fault ids")
        for f in self.faults:
            if f.device not in names:
                errs.append(f"fault {f.id} references unknown device {f.device}")
            if not f.config.strip() or not f.ticket.strip() or not f.explanation.strip():
                errs.append(f"fault {f.id}: config, ticket and explanation are required")
            for c in f.checks:
                if c.device not in names:
                    errs.append(f"fault {f.id}: check {c.id} references unknown device {c.device}")
                if c.id in ids:
                    errs.append(f"fault {f.id}: check id {c.id} clashes with a lab check")
            if any(not h.strip() for h in f.hints):
                errs.append(f"fault {f.id}: hints must not contain empty entries")
        if any(not h.strip() for h in self.hints):
            errs.append("hints must not contain empty entries")
        for n in self.nodes:
            for idx in placeholders(n.config):
                if idx >= MAX_PORTS:
                    errs.append(f"{n.name}: placeholder port {idx} out of range")
        if not self.checks_for("live"):
            errs.append("lab has no live checks")
        if not self.checks_for("config"):
            errs.append("lab has no config checks")
        if errs:
            raise ValueError("; ".join(errs))
        return self

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    def node(self, name: str) -> Node:
        for n in self.nodes:
            if n.name == name:
                return n
        raise KeyError(name)

    def checks_for(self, mode: str) -> list[Check]:
        return [c for c in self.checks if c.mode == mode]

    @property
    def total_points(self) -> int:
        return sum(c.points for c in self.checks)
