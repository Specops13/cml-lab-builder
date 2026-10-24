"""Walkthrough labs (`type: walkthrough`): a guided build in ordered steps instead of a graded challenge.

Per-lab progress lives in the user data folder (walkthroughs/<lab>.json): the step the student is on, the result
of each "Check this step", which steps were applied for them, and when the walkthrough was completed (every
required step that has checks passed). Walkthroughs never write grading history, so they stay out of scores,
mastery and streaks; the progress page lists them separately."""
from __future__ import annotations

import json
import threading
import time

from . import catalog
from .platforms import get as get_platform, node_def, render
from .schema import Lab, Step
from .paths import safe_name as _safe

_lock = threading.Lock()


class WalkthroughError(RuntimeError):
    pass


def _file(lab_id: str):
    from .history import data_dir
    return data_dir() / "walkthroughs" / f"{_safe(lab_id)}.json"


def load(lab_id: str) -> dict:
    try:
        d = json.loads(_file(lab_id).read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("current", 0)
            d.setdefault("steps", {})
            d.setdefault("completed", None)
            return d
    except (OSError, ValueError):
        pass
    return {"current": 0, "steps": {}, "completed": None}


def _save(lab_id: str, d: dict) -> None:
    f = _file(lab_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(f)


def _require(lab: Lab) -> None:
    if not lab.is_walkthrough:
        raise WalkthroughError(f"{lab.id} is not a walkthrough lab")


def checkable(step: Step) -> bool:
    return bool(step.checks)


def status(lab: Lab, state: dict | None = None) -> dict:
    """{"current", "steps": [{id, title, optional, has_checks, passed, checked_at, applied_at}], "required",
    "required_passed", "pct", "completed"}."""
    _require(lab)
    d = state or load(lab.id)
    steps, req, ok = [], 0, 0
    for st in lab.steps:
        r = d["steps"].get(st.id, {})
        steps.append({"id": st.id, "title": st.title, "optional": st.optional, "has_checks": checkable(st),
                      "passed": r.get("passed"), "score_pct": r.get("score_pct"), "checked_at": r.get("at"),
                      "applied_at": r.get("applied_at"), "mode": r.get("mode")})
        if checkable(st) and not st.optional:
            req += 1
            ok += bool(r.get("passed"))
    cur = min(max(int(d.get("current", 0)), 0), len(lab.steps))   # == len(steps): the summary page
    return {"current": cur, "steps": steps, "required": req, "required_passed": ok,
            "pct": round(100.0 * ok / req, 1) if req else 0.0, "completed": d.get("completed")}


def _update_completed(lab: Lab, d: dict) -> None:
    req = [st for st in lab.steps if checkable(st) and not st.optional]
    if req and all(d["steps"].get(st.id, {}).get("passed") for st in req) and not d.get("completed"):
        d["completed"] = time.time()      # stays completed even if a later re-check fails


def set_current(lab: Lab, index: int) -> dict:
    _require(lab)
    with _lock:
        d = load(lab.id)
        d["current"] = min(max(int(index), 0), len(lab.steps))
        _save(lab.id, d)
        return status(lab, d)


def reset(lab: Lab) -> dict:
    _require(lab)
    with _lock:
        d = {"current": 0, "steps": {}, "completed": None}
        _save(lab.id, d)
        return status(lab, d)


def record(lab: Lab, results: dict[str, dict]) -> dict:
    """results: step id -> {"passed", "score_pct", "mode"}."""
    with _lock:
        d = load(lab.id)
        for sid, r in results.items():
            prev = d["steps"].get(sid, {})
            d["steps"][sid] = {**prev, **r, "at": time.time()}
        _update_completed(lab, d)
        _save(lab.id, d)
        return status(lab, d)


def _mark_applied(lab: Lab, sid: str) -> None:
    with _lock:
        d = load(lab.id)
        d["steps"].setdefault(sid, {})["applied_at"] = time.time()
        _save(lab.id, d)


def step_lab(lab: Lab, step: Step) -> Lab:
    """A plain (challenge-shaped) copy of the lab graded with just this step's checks."""
    return lab.model_copy(update={"type": "challenge", "steps": [], "checks": list(step.checks), "faults": []})


def _merge(reports: list[dict]) -> dict:
    res = [r for d in reports for r in d["results"]]
    earned, total = sum(r["earned"] for r in res), sum(r["points"] for r in res)
    return {"results": res, "earned": earned, "total": total,
            "score_pct": round(100.0 * earned / total, 1) if total else 0.0,
            "passed": bool(res) and all(r["passed"] for r in res),
            "mode": "+".join(dict.fromkeys(d["mode"] for d in reports)),
            "notes": [n for d in reports for n in d.get("notes", [])]}


def _grade(settings, lab: Lab, progress, **kw) -> dict:
    """Live checks (falling back to config per the grading-mode setting) plus the config checks."""
    from .service import do_check
    has_live, has_cfg = bool(lab.checks_for("live")), bool(lab.checks_for("config"))
    reports = []
    common = dict(lab=lab, record=False, fault_aware=False, client_factory=kw.get("client_factory"),
                  title=kw.get("title"))
    if has_live:
        d = do_check(settings, lab.id, progress, runner=kw.get("runner"), config_source=kw.get("config_source"),
                     probe=kw.get("probe"), mode=settings.grading_mode, **common)
        reports.append(d)
        if d["mode"] == "config":
            has_cfg = False      # the fallback already graded the config checks
    if has_cfg:
        reports.append(do_check(settings, lab.id, progress, config_source=kw.get("config_source"), mode="config",
                                **common))
    return _merge(reports)


def check_step(settings, lab_id: str, step_id: str, progress, **kw) -> dict:
    lab = kw.pop("lab", None) or catalog.get(lab_id)
    _require(lab)
    st = _step(lab, step_id)
    if not st.checks:
        raise WalkthroughError(f"step {step_id} has nothing to check; just read it and move on")
    progress(f"Checking step: {st.title}")
    d = _grade(settings, step_lab(lab, st), progress, **kw)
    d["step"] = st.id
    d["walkthrough"] = record(lab, {st.id: {"passed": d["passed"], "score_pct": d["score_pct"], "mode": d["mode"]}})
    progress(f"Step {'passed' if d['passed'] else 'not done yet'}: {d['earned']}/{d['total']} ({d['score_pct']}%)")
    return d


def check_all(settings, lab_id: str, progress, **kw) -> dict:
    """Check every step with checks (optional ones too) in one pass and record each step's result."""
    lab = kw.pop("lab", None) or catalog.get(lab_id)
    _require(lab)
    steps = [st for st in lab.steps if st.checks]
    every = lab.model_copy(update={"type": "challenge", "steps": [], "faults": [],
                                   "checks": [c for st in steps for c in st.checks]})
    progress(f"Checking all {len(steps)} steps")
    d = _grade(settings, every, progress, **kw)
    by_id = {r["id"]: r for r in d["results"]}
    per = {}
    for st in steps:
        rs = [by_id[c.id] for c in st.checks if c.id in by_id]
        if not rs:
            continue      # e.g. config-only step skipped in live mode
        e, t = sum(r["earned"] for r in rs), sum(r["points"] for r in rs)
        per[st.id] = {"passed": all(r["passed"] for r in rs), "score_pct": round(100.0 * e / t, 1) if t else 0.0,
                      "mode": d["mode"]}
    d["steps"] = per
    d["walkthrough"] = record(lab, per)
    return d


def _step(lab: Lab, step_id: str) -> Step:
    try:
        return lab.step(step_id)
    except KeyError:
        raise WalkthroughError(f"unknown step {step_id!r}")


def apply_step(settings, lab_id: str, step_id: str, progress, runner=None, client_factory=None, lab=None) -> dict:
    """Type this step's config into each device over the CML console (same path as live checks).
    Stops at the first line a device rejects."""
    from .service import make_cml
    lab = lab or catalog.get(lab_id)
    _require(lab)
    st = _step(lab, step_id)
    if not st.apply or not st.config:
        raise WalkthroughError("this step has no config to apply")
    plat = get_platform(settings.platform)
    own = runner is None
    if own:
        progress(f"Opening device consoles via {settings.effective_console_host}:{settings.console_port}")
        runner = make_cml(settings, client_factory).runner(lab)
    if not hasattr(runner, "configure"):
        raise WalkthroughError("the console backend cannot push configuration")
    log = {}
    try:
        for dev, cfg in st.config.items():
            progress(f"Configuring {dev} ({len(cfg.strip().splitlines())} lines)")
            nd = node_def(lab.node(dev).definition)
            log[dev] = runner.configure(dev, render(cfg, plat), nd.os if nd else "ios")
    finally:
        if own and hasattr(runner, "close"):
            runner.close()
    _mark_applied(lab, st.id)
    progress(f"Applied step '{st.title}' on {', '.join(log)}. Give the protocols a few seconds, then Check this step.")
    return {"step": st.id, "applied": list(log), "log": log}


def summary(lab: Lab, plat=None) -> dict:
    """The finished build: per-device config of every step in order (optional steps flagged)."""
    _require(lab)
    plat = plat or get_platform("iol")
    devices: dict[str, list[dict]] = {}
    for st in lab.steps:
        for dev, cfg in st.config.items():
            devices.setdefault(dev, []).append({"step": st.id, "title": st.title, "optional": st.optional,
                                                "config": render(cfg, plat).rstrip() + "\n"})
    return {"devices": devices, "text": render(lab.solution_summary, plat) if lab.solution_summary else ""}


def all_status() -> dict[str, dict]:
    """lab id -> status for every walkthrough lab in the catalog (for progress/courses)."""
    out = {}
    for lid, e in catalog.entries().items():
        if e.lab.is_walkthrough:
            out[lid] = status(e.lab)
    return out
