"""Exam mode: a timed, one-shot attempt at a lab with hints disabled or penalized and a score report.

State lives in <data>/exams/<lab>.json, so the web UI and the CLI see the same exam. While an exam runs the API
withholds hints and the solution; the next hint (penalty mode) is only served through use_hint(). The exam ends
with the first Check ("Submit"). The final score is the check score minus the hint penalty, and a submission later
than the time limit plus a short grace period scores 0%."""
from __future__ import annotations

import json
import time

from .schema import Lab
from .paths import safe_name as _safe

HINT_MODES = ("penalty", "off")
DEFAULT_PENALTY = 10        # points per hint in penalty mode
GRACE_S = 60                # network/boot slack after the countdown ends
PASS_PCT = 80               # practice target, not Cisco's (unpublished) cut score
MIN_MINUTES, MAX_MINUTES = 5, 240
_DEFAULT_MINUTES = {1: 20, 2: 30, 3: 45, 4: 60, 5: 75}


class ExamError(ValueError):
    pass


def default_minutes(lab: Lab) -> int:
    return _DEFAULT_MINUTES.get(lab.difficulty, 45) + 5 * max(0, len(lab.nodes) - 4)


def _file(lab_id: str):
    from .history import data_dir
    return data_dir() / "exams" / f"{_safe(lab_id)}.json"


def active(lab_id: str) -> dict | None:
    try:
        d = json.loads(_file(lab_id).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("started") else None
    except (OSError, ValueError):
        return None


def _save(lab_id: str, d: dict) -> None:
    f = _file(lab_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d), encoding="utf-8")


def clear(lab_id: str) -> None:
    try:
        _file(lab_id).unlink()
    except FileNotFoundError:
        pass


def start(lab: Lab, minutes: int | None = None, hints: str = "penalty", penalty: int = DEFAULT_PENALTY,
          now: float | None = None) -> dict:
    from . import faults
    if lab.is_walkthrough:
        raise ExamError("exam mode is not available for walkthrough labs")
    if hints not in HINT_MODES:
        raise ExamError("hints must be 'penalty' or 'off'")
    if faults.active(lab.id):
        raise ExamError("end the Break my lab fault practice first")
    minutes = default_minutes(lab) if minutes in (None, 0) else int(minutes)
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise ExamError(f"duration must be {MIN_MINUTES}-{MAX_MINUTES} minutes")
    if not 0 <= int(penalty) <= 50:
        raise ExamError("hint penalty must be 0-50 points")
    d = {"started": now or time.time(), "duration_s": minutes * 60, "hints": hints, "penalty": int(penalty), "hints_used": 0}
    _save(lab.id, d)
    return status(lab.id, now)


def running(now: float | None = None) -> list[str]:
    """Labs with an exam that is still on the clock (an expired exam no longer blocks anything)."""
    from .history import data_dir
    out = []
    for f in sorted((data_dir() / "exams").glob("*.json")):
        st = status(f.stem, now)
        if st and not st["expired"]:
            out.append(f.stem)
    return out


def status(lab_id: str, now: float | None = None) -> dict | None:
    d = active(lab_id)
    if not d:
        return None
    now = now or time.time()
    elapsed = max(0, now - d["started"])
    return {"started": time.strftime("%Y-%m-%d %H:%M", time.localtime(d["started"])), "started_ts": d["started"],
            "duration_s": d["duration_s"], "elapsed_s": int(elapsed), "remaining_s": max(0, int(d["duration_s"] - elapsed)),
            "expired": elapsed > d["duration_s"], "hints": d["hints"], "penalty": d["penalty"], "hints_used": d["hints_used"],
            "pass_pct": PASS_PCT}


def use_hint(lab_id: str, total: int) -> int:
    """Record one more hint (penalty mode) and return its 1-based number."""
    d = active(lab_id)
    if not d:
        raise ExamError("no exam is running")
    if d["hints"] == "off":
        raise ExamError("hints are disabled in this exam")
    if d["hints_used"] >= total:
        raise ExamError("no more hints")
    d["hints_used"] += 1
    _save(lab_id, d)
    return d["hints_used"]


def finish(lab_id: str, score_pct: float, now: float | None = None) -> dict:
    """Score the submission and end the exam. Returns the exam block stored with the history entry."""
    d = active(lab_id)
    if not d:
        raise ExamError("no exam is running")
    now = now or time.time()
    elapsed = max(0.0, now - d["started"])
    late = elapsed > d["duration_s"] + GRACE_S
    penalty = d["hints_used"] * d["penalty"] if d["hints"] == "penalty" else 0
    final = 0.0 if late else max(0.0, round(float(score_pct) - penalty, 1))
    clear(lab_id)
    return {"duration_s": d["duration_s"], "used_s": int(min(elapsed, d["duration_s"] + GRACE_S)) if not late else int(elapsed),
            "hints": d["hints"], "hints_used": d["hints_used"], "penalty_per_hint": d["penalty"], "penalty": penalty,
            "raw_pct": score_pct, "final_pct": final, "late": late, "pass_pct": PASS_PCT, "passed": final >= PASS_PCT}
