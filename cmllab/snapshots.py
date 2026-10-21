"""Config snapshots: save the running configs of a built lab (CML config extraction over HTTPS) and restore them
later (stop, wipe and boot the lab with the saved configs as day-0 configs).

Stored in <data>/snapshots/<lab>/<name>.json as {name, lab_id, platform, created, note, configs: {node: config}}."""
from __future__ import annotations

import json
import re
import time

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
MAX_PER_LAB = 20
MAX_CONFIG = 512 * 1024


class SnapshotError(ValueError):
    pass


def _dir(lab_id: str):
    from .history import data_dir
    return data_dir() / "snapshots" / lab_id


_BANNER = re.compile(r"^(Building configuration\.\.\.|Current configuration\s*:.*|! Last configuration change.*|"
                     r"! NVRAM config last updated.*)$")


def clean_config(cfg: str) -> str:
    """Drop the show-run banners CML/IOS put in front of an extracted config (they are not config commands)."""
    lines = cfg.replace("\r\n", "\n").split("\n")
    while lines and (not lines[0].strip() or _BANNER.match(lines[0].strip())):
        lines.pop(0)
    out = "\n".join(l for l in lines if not _BANNER.match(l.strip()))
    return out.rstrip() + "\n"


def check_name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise SnapshotError("snapshot name: 1-40 letters, digits, '.', '_' or '-' (start with a letter or digit)")
    return name


def default_name() -> str:
    return time.strftime("snap-%Y%m%d-%H%M%S")


def list_snapshots(lab_id: str) -> list[dict]:
    d = _dir(lab_id)
    out = []
    for f in d.glob("*.json") if d.is_dir() else []:
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            out.append({"name": s["name"], "created": s["created"], "platform": s.get("platform"), "note": s.get("note", ""),
                        "nodes": sorted(s["configs"]), "size": sum(len(c) for c in s["configs"].values())})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(out, key=lambda x: x["created"], reverse=True)


def load(lab_id: str, name: str) -> dict:
    f = _dir(lab_id) / f"{check_name(name)}.json"
    try:
        s = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SnapshotError(f"no snapshot named {name!r} for {lab_id}")
    except (OSError, ValueError) as e:
        raise SnapshotError(f"snapshot {name!r} is unreadable: {e}")
    if not isinstance(s.get("configs"), dict) or not s["configs"]:
        raise SnapshotError(f"snapshot {name!r} has no configs")
    return s


def save(lab_id: str, name: str, configs: dict[str, str], platform: str, note: str = "", overwrite: bool = False) -> dict:
    check_name(name)
    if not configs:
        raise SnapshotError("nothing to save: no configs were read")
    d = _dir(lab_id)
    f = d / f"{name}.json"
    if f.exists() and not overwrite:
        raise SnapshotError(f"a snapshot named {name!r} already exists")
    if not f.exists() and len(list_snapshots(lab_id)) >= MAX_PER_LAB:
        raise SnapshotError(f"at most {MAX_PER_LAB} snapshots per lab; delete an old one first")
    for node, cfg in configs.items():
        if len(cfg) > MAX_CONFIG:
            raise SnapshotError(f"{node}: config is larger than {MAX_CONFIG // 1024} KB")
    configs = {n: clean_config(c) for n, c in configs.items()}
    d.mkdir(parents=True, exist_ok=True)
    s = {"name": name, "lab_id": lab_id, "platform": platform, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "note": (note or "")[:200], "configs": configs}
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    tmp.replace(f)
    return {k: v for k, v in s.items() if k != "configs"} | {"nodes": sorted(configs)}


def delete(lab_id: str, name: str) -> None:
    f = _dir(lab_id) / f"{check_name(name)}.json"
    if not f.exists():
        raise SnapshotError(f"no snapshot named {name!r} for {lab_id}")
    f.unlink()


def as_cfg(s: dict) -> str:
    """The snapshot as a solution.cfg-style text file (`! device NAME` sections)."""
    return "".join(f"! device {n}\n{c.rstrip()}\n" for n, c in sorted(s["configs"].items()))
