"""Shared core used by both CLI and web UI."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable

from . import catalog
from .cml import CML
from .grader import grade
from .platforms import get as get_platform


def make_cml(settings, client_factory=None) -> CML:
    return CML(settings, client_factory=client_factory)


def do_build(settings, lab_id, progress, rebuild=False, client_factory=None):
    lab = catalog.get(lab_id)
    cml = make_cml(settings, client_factory)
    cl = cml.build(lab, start=True, rebuild=rebuild, progress=progress)
    progress(f"Lab ready in CML: {cl.title} (id {cl.id})")
    return {"lab_id": cl.id, "title": cl.title}


def _grade_live(settings, lab, plat, progress, client_factory, runner, title=None):
    own = runner is None
    if own:
        progress(f"Opening device consoles via {settings.effective_console_host}:{settings.console_port}")
        runner = make_cml(settings, client_factory).runner(lab, title)
    try:
        return grade(lab, runner, plat, progress=progress, mode="live")
    finally:
        if own and hasattr(runner, "close"):
            runner.close()


def _grade_config(settings, lab, plat, progress, client_factory, config_source, title=None):
    if config_source is None:
        progress("Extracting running configs through the CML API (HTTPS)")
        config_source = make_cml(settings, client_factory).config_source(lab, title)
    return grade(lab, config_source, plat, progress=progress, mode="config")


def _all_connect_errors(report) -> bool:
    return bool(report.results) and all(
        (not r.passed) and r.details and r.details[0].startswith("error running command") for r in report.results)


def do_break(settings, lab_id, progress, fault_id: str | None = None, client_factory=None, rng=None):
    """'Break my lab': rebuild the lab with the reference solution plus one random predefined fault."""
    from . import faults
    lab = catalog.get(lab_id)
    sol = catalog.load_solution(lab_id)
    if not sol:
        raise faults.FaultError("this lab has no reference solution, so it cannot be broken")
    f = faults.pick(lab, fault_id, rng=rng)
    progress(f"Picked one of {len(lab.faults)} faults. Rebuilding the lab with a working config plus the fault "
             "(your current device configs are replaced)")
    cml = make_cml(settings, client_factory)
    cml.build(lab, start=True, rebuild=True, progress=progress, solution=faults.broken_config(sol, f))
    faults.set_active(lab_id, f.id)
    plat = get_platform(settings.platform)
    progress("Fault applied. Read the trouble ticket, find the problem and fix it, then click Check.")
    return {"ticket": faults.public(lab, faults.active(lab_id), plat)["ticket"], "faults_total": len(lab.faults)}


def do_check(settings, lab_id, progress, client_factory=None, runner=None, config_source=None,
             mode: str | None = None, probe=None, lab=None, title=None, record=True, hints_used: int | None = None,
             fault_aware: bool = True, extra: dict | None = None):
    """mode: 'live', 'config' or 'auto' (live first, fall back to config if the console is unreachable).
    While a 'Break my lab' fault is active the fault's extra checks are graded too.
    extra: additional fields stored with the history entry (exam mode, elapsed time)."""
    from . import faults, history
    from .cml import probe_console
    lab = lab or catalog.get(lab_id)
    plat = get_platform(settings.platform)
    fstate = faults.active(lab.id) if fault_aware else None
    fault = None
    if fstate:
        try:
            fault = faults.get(lab, fstate["fault_id"])
        except faults.FaultError:
            fault = None
    base_lab = lab
    lab = faults.grading_lab(lab, fault)
    mode = mode or settings.grading_mode
    if mode not in ("auto", "live", "config"):
        raise ValueError(f"unknown grading mode {mode!r}")
    notes: list[str] = []
    report = None
    if mode in ("auto", "live"):
        if mode == "auto" and runner is None:
            pr = (probe or probe_console)(settings.effective_console_host, settings.console_port)
            if not pr["ok"]:
                notes.append(f"Live console unavailable ({pr['detail']}); fell back to config mode.")
                progress(notes[-1])
        if not notes:
            report = _grade_live(settings, lab, plat, progress, client_factory, runner, title)
            if mode == "auto" and _all_connect_errors(report):
                notes.append("Live console checks could not connect to any device "
                             f"({report.results[0].details[0]}); fell back to config mode.")
                progress(notes[-1])
                report = None
    if report is None:
        report = _grade_config(settings, lab, plat, progress, client_factory, config_source, title)
    report.notes = notes + report.notes
    progress(f"Mode: {report.mode}. Score: {report.earned}/{report.total} ({report.score_pct}%)")
    d = report.to_dict()
    d["requested_mode"] = mode
    from . import solution as sol_mod
    total_hints = len(fault.hints) if (fault and fault.hints) else len(sol_mod.hints(base_lab, plat))
    d["hints_total"] = total_hints
    d["hints_used"] = None if hints_used is None else max(0, min(int(hints_used), total_hints))
    d.update(extra or {})
    if fault:
        d["fault"] = fault.id
        if d.get("passed"):
            d["fault_fixed"] = faults.reveal(base_lab, fault, plat)
            d["fault_revealed"] = bool(fstate.get("revealed"))
            faults.clear(base_lab.id)
            progress(f"Fault fixed: {d['fault_fixed']['title']}")
    elif d.get("passed"):
        try:
            sol = catalog.load_solution(lab.id)
        except catalog.LabNotFound:
            sol = dict(lab.solution or {})
        d["solution_summary"], d["solution_summary_auto"] = sol_mod.summary(base_lab, sol, plat)
    if record:
        try:
            history.add(lab.id, d)
        except OSError:
            pass
    return d


def do_test_live(settings, lab, solution: dict, progress, client_factory=None, mode="auto", keep=False,
                 runner=None, config_source=None, probe=None):
    """Build a throw-away copy of the lab with the solution pre-applied, grade it, then delete it.
    A correct lab scores 100% here."""
    if not solution:
        raise ValueError("this lab has no reference solution to test with")
    cml = make_cml(settings, client_factory)
    title = cml.title_for(lab, test=True)
    progress(f"Building test copy {title} with the solution pre-applied")
    cml.build(lab, start=True, rebuild=True, progress=progress, solution=solution, title=title)
    try:
        return do_check(settings, lab.id, progress, client_factory=client_factory, runner=runner,
                        config_source=config_source, mode=mode, probe=probe, lab=lab, title=title, record=False,
                        fault_aware=False)
    finally:
        if not keep:
            progress("Removing test copy")
            cml.destroy(lab, progress=progress, title=title)


def do_reset(settings, lab_id, progress, client_factory=None):
    """Back to the starting configs; during fault practice back to the broken lab (same fault)."""
    from . import faults
    lab = catalog.get(lab_id)
    st = faults.active(lab_id)
    if st:
        f = faults.get(lab, st["fault_id"])
        make_cml(settings, client_factory).reset(
            lab, progress=progress, extra=faults.broken_config(catalog.load_solution(lab_id), f),
            label="broken (fault practice)")
        return {"reset": True, "fault_practice": True}
    make_cml(settings, client_factory).reset(lab, progress=progress)
    return {"reset": True}


def do_destroy(settings, lab_id, progress, client_factory=None):
    lab = catalog.get(lab_id)
    return {"destroyed": make_cml(settings, client_factory).destroy(lab, progress=progress)}


def do_status(settings, lab_id, client_factory=None):
    lab = catalog.get(lab_id)
    st = make_cml(settings, client_factory).status(lab)
    return st.__dict__


@dataclass
class Job:
    id: str
    kind: str
    lab_id: str
    state: str = "running"   # running | done | error
    log: list[str] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    started: float = field(default_factory=time.time)


class JobManager:
    """Runs long operations in background threads; one active job per lab."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, lab_id: str, fn: Callable[[Callable[[str], None]], dict]) -> Job:
        with self._lock:
            for j in self._jobs.values():
                if j.lab_id == lab_id and j.state == "running":
                    raise RuntimeError(f"a {j.kind} job is already running for {lab_id}")
            job = Job(uuid.uuid4().hex[:12], kind, lab_id)
            self._jobs[job.id] = job

        def progress(msg: str):
            job.log.append(time.strftime("%H:%M:%S ") + msg)

        def target():
            try:
                job.result = fn(progress)
                job.state = "done"
            except Exception as e:
                job.error = f"{type(e).__name__}: {e}"
                job.log.append("ERROR " + job.error)
                job.log.append(traceback.format_exc(limit=3))
                job.state = "error"

        threading.Thread(target=target, daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)
