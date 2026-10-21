"""Per-lab results history (JSON files in the user data folder)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

MAX_ENTRIES = 50


def data_dir() -> Path:
    from . import paths
    if paths.env_get("DATA_DIR"):
        return Path(paths.env_get("DATA_DIR"))
    from .config import settings_file
    return settings_file().parent


def _file(lab_id: str) -> Path:
    return data_dir() / "history" / f"{lab_id}.json"


def load(lab_id: str) -> list[dict]:
    try:
        data = json.loads(_file(lab_id).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def add(lab_id: str, report: dict) -> dict:
    entry = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": report.get("mode"), "earned": report.get("earned"), "total": report.get("total"),
        "score_pct": report.get("score_pct"), "passed": report.get("passed"),
        "failed": [r["id"] for r in report.get("results", []) if not r.get("passed")],
        "hints_used": report.get("hints_used"), "hints_total": report.get("hints_total"),
    }
    for k in ("fault", "elapsed_s", "exam", "revealed"):
        if report.get(k) is not None:
            entry[k] = report[k]
    items = (load(lab_id) + [entry])[-MAX_ENTRIES:]
    f = _file(lab_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(items, indent=1), encoding="utf-8")
    return entry


def clear(lab_id: str) -> None:
    for f in (_file(lab_id), data_dir() / "reports" / f"{lab_id}.json"):
        try:
            f.unlink()
        except FileNotFoundError:
            pass
