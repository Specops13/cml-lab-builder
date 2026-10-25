"""Manual completion (3.3.3): when a check is buggy, the student can mark a challenge lab complete by hand.

Stored in the user data folder (manual_complete.json: lab id -> unix time), never in the grading history, so a
lab marked by hand is *completed-manually*, not a graded pass: it does not raise scores, mastery or streaks, but
courses count it as done (the next lab becomes the course's "next"). Walkthroughs keep their manual marks (per
step and per lab) in their own progress file, see walkthrough.py."""
from __future__ import annotations

import json
import threading
import time

_lock = threading.Lock()


def _file():
    from .history import data_dir
    return data_dir() / "manual_complete.json"


def load() -> dict[str, float]:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in d.items() if isinstance(v, (int, float))} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def get(lab_id: str) -> float | None:
    return load().get(lab_id)


def set_done(lab_id: str, done: bool) -> float | None:
    """Mark (done=True) or unmark a lab; returns the stored time or None."""
    with _lock:
        d = load()
        if done:
            d.setdefault(lab_id, time.time())
        else:
            d.pop(lab_id, None)
        f = _file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        tmp.replace(f)
        return d.get(lab_id)
