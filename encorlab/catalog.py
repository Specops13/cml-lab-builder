"""Lab catalog: built-in labs (package labs/ folder) + user labs
(%APPDATA%\\encorlab\\labs or ~/.config/encorlab/labs, or ENCOR_USER_LABS_DIR).

A lab folder contains lab.yaml and optionally solution.cfg, fixture_solved.yaml,
fixture_blank.yaml. A reference solution may instead be embedded in lab.yaml
under `solution:` (device -> config text)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .schema import Lab

LABS_DIR = Path(__file__).parent / "labs"


class LabNotFound(KeyError):
    pass


@dataclass
class Entry:
    lab: Lab
    path: Path
    source: str  # "builtin" | "user"


def user_labs_dir() -> Path:
    if os.environ.get("ENCOR_USER_LABS_DIR"):
        return Path(os.environ["ENCOR_USER_LABS_DIR"])
    from .config import settings_file
    return settings_file().parent / "labs"


def lab_dirs(root: Path = LABS_DIR) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if (p / "lab.yaml").is_file())


def load_lab_file(path: Path) -> Lab:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return Lab.model_validate(data)


def _scan(root: Path, source: str, errors: dict | None) -> dict[str, Entry]:
    out = {}
    for d in lab_dirs(root):
        try:
            lab = load_lab_file(d / "lab.yaml")
            if lab.id != d.name:
                raise ValueError(f"lab id {lab.id!r} must equal folder name {d.name!r}")
        except Exception as e:
            if source == "builtin" and errors is None:
                raise
            if errors is not None:
                errors[str(d)] = str(e)
            continue
        out[lab.id] = Entry(lab, d, source)
    return out


def entries(root: Path = LABS_DIR, user_root: Path | None = None, errors: dict | None = None) -> dict[str, Entry]:
    """Built-in labs first; user labs with a clashing id are ignored."""
    res = _scan(root, "builtin", errors)
    ur = user_labs_dir() if user_root is None else user_root
    for k, v in _scan(ur, "user", errors).items():
        if k in res:
            if errors is not None:
                errors[str(v.path)] = f"id {k!r} clashes with a built-in lab"
            continue
        res[k] = v
    return res


def load_all(root: Path = LABS_DIR) -> dict[str, Lab]:
    if root != LABS_DIR:  # explicit root (tests): only that folder, strict
        labs = {}
        for d in lab_dirs(root):
            lab = load_lab_file(d / "lab.yaml")
            if lab.id != d.name:
                raise ValueError(f"lab id {lab.id!r} must equal folder name {d.name!r}")
            labs[lab.id] = lab
        return labs
    return {k: e.lab for k, e in entries().items()}


def entry(lab_id: str) -> Entry:
    es = entries()
    if lab_id not in es:
        raise LabNotFound(f"unknown lab {lab_id!r}; available: {', '.join(es)}")
    return es[lab_id]


def get(lab_id: str, root: Path = LABS_DIR) -> Lab:
    if root != LABS_DIR:
        labs = load_all(root)
        if lab_id not in labs:
            raise LabNotFound(lab_id)
        return labs[lab_id]
    return entry(lab_id).lab


_SECTION = re.compile(r"^!\s*device\s+(\S+)\s*$", re.I)


def parse_solution_cfg(text: str) -> dict[str, str]:
    """solution.cfg is split into per-device blocks by lines '! device NAME'."""
    out: dict[str, list[str]] = {}
    cur = None
    for line in text.splitlines():
        m = _SECTION.match(line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, [])
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v).strip() + "\n" for k, v in out.items()}


def format_solution_cfg(sol: dict[str, str]) -> str:
    return "".join(f"! device {k}\n{v.rstrip()}\n" for k, v in sol.items())


def load_solution(lab_id: str) -> dict[str, str]:
    e = entry(lab_id)
    f = e.path / "solution.cfg"
    if f.exists():
        return parse_solution_cfg(f.read_text(encoding="utf-8"))
    return dict(e.lab.solution or {})


def load_fixture(lab_id: str, state: str) -> dict[str, dict[str, str]]:
    path = entry(lab_id).path / f"fixture_{state}.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
