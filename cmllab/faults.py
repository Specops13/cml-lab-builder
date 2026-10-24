"""'Break my lab': predefined faults applied on top of a working lab for unlimited troubleshooting practice.

A fault is applied by rebuilding the lab in CML with day-0 config = starting config + reference solution +
fault config (IOS applies it line by line, so `no ...` lines remove what the solution added). The active
fault is remembered in the user data folder (faults/<lab>.json); the student only sees the ticket until the
lab passes Check again (or they reveal the answer)."""
from __future__ import annotations

import json
import random
import time

from .platforms import Platform, render
from .schema import Fault, Lab
from .paths import safe_name as _safe


class FaultError(ValueError):
    pass


# ---------------------------------------------------------------- state
def _file(lab_id: str):
    from .history import data_dir
    return data_dir() / "faults" / f"{_safe(lab_id)}.json"


def active(lab_id: str) -> dict | None:
    try:
        d = json.loads(_file(lab_id).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("fault_id") else None
    except (OSError, ValueError):
        return None


def set_active(lab_id: str, fault_id: str) -> dict:
    prev = active(lab_id) or {}
    d = {"fault_id": fault_id, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "revealed": False,
         "recent": ([fault_id] + [x for x in prev.get("recent", []) if x != fault_id])[:5]}
    f = _file(lab_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return d


def mark_revealed(lab_id: str) -> None:
    d = active(lab_id)
    if d:
        d["revealed"] = True
        _file(lab_id).write_text(json.dumps(d, indent=1), encoding="utf-8")


def clear(lab_id: str) -> None:
    """End fault practice but remember recently used faults so the next pick differs."""
    d = active(lab_id)
    f = _file(lab_id)
    if d:
        f.write_text(json.dumps({"fault_id": None, "recent": d.get("recent", [])}, indent=1), encoding="utf-8")


def _recent(lab_id: str) -> list[str]:
    try:
        return json.loads(_file(lab_id).read_text(encoding="utf-8")).get("recent", [])
    except (OSError, ValueError, AttributeError):
        return []


# ---------------------------------------------------------------- choosing / applying
def get(lab: Lab, fault_id: str) -> Fault:
    for f in lab.faults:
        if f.id == fault_id:
            return f
    raise FaultError(f"lab {lab.id} has no fault {fault_id!r}; available: {', '.join(f.id for f in lab.faults) or 'none'}")


def pick(lab: Lab, fault_id: str | None = None, rng: random.Random | None = None) -> Fault:
    if not lab.faults:
        raise FaultError(f"lab {lab.id} has no predefined faults")
    if fault_id:
        return get(lab, fault_id)
    recent = _recent(lab.id)
    pool = [f for f in lab.faults if f.id not in recent[: max(0, len(lab.faults) - 1)]] or list(lab.faults)
    return (rng or random).choice(pool)


def broken_config(solution: dict[str, str], fault: Fault) -> dict[str, str]:
    """device -> config appended to the starting config when building the broken lab."""
    out = {k: v for k, v in solution.items()}
    out[fault.device] = (out.get(fault.device, "").rstrip() + "\n" + fault.config.rstrip() + "\n").lstrip("\n")
    return out


def grading_lab(lab: Lab, fault: Fault | None) -> Lab:
    """The lab plus the fault's extra checks."""
    if fault is None or not fault.checks:
        return lab
    return lab.model_copy(update={"checks": list(lab.checks) + list(fault.checks)})


def public(lab: Lab, state: dict | None, plat: Platform) -> dict | None:
    """What the student may see about the active fault (no cause, no fix)."""
    if not state or not state.get("fault_id"):
        return None
    try:
        f = get(lab, state["fault_id"])
    except FaultError:
        return None
    return {"ticket": render(f.ticket, plat), "started": state.get("started"), "revealed": bool(state.get("revealed")),
            "hints": [render(h, plat) for h in f.hints], "extra_checks": len(f.checks)}


def reveal(lab: Lab, fault: Fault, plat: Platform) -> dict:
    return {"id": fault.id, "title": render(fault.title, plat), "device": fault.device,
            "explanation": render(fault.explanation, plat), "config": render(fault.config, plat)}


# ---------------------------------------------------------------- offline validation
def validate(lab: Lab, solution: dict[str, str], plat: Platform) -> list[str]:
    """Every fault must be detected by the config-mode checks (lab + fault checks) on the solved lab,
    and the solved lab without the fault must still pass those checks (so the fault is fixable)."""
    from .grader import grade
    from .sim import SimRunner
    errs = []
    if lab.faults and not solution:
        return ["faults need a reference solution"]
    for f in lab.faults:
        gl = grading_lab(lab, f)
        ok = grade(gl, SimRunner(gl, plat, True, solution=solution, fixtures={}, extra={"_": ""}), plat, mode="config")
        if not ok.passed:
            bad = [r.id for r in ok.results if not r.passed]
            errs.append(f"[{plat.name}] fault {f.id}: the solved lab fails {bad} even without the fault")
        broken = grade(gl, SimRunner(gl, plat, True, solution=solution, fixtures={}, extra={f.device: f.config}),
                       plat, mode="config")
        if broken.passed:
            errs.append(f"[{plat.name}] fault {f.id}: no config check detects it (add a check under the fault)")
    return errs
