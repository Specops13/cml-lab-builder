"""Lab catalog: the labs installed in the user labs folder
(%APPDATA%\\cml-lab-builder\\labs or ~/.config/cml-lab-builder/labs, or CMLLAB_USER_LABS_DIR).

Since 2.0.0 the app ships without labs: every lab is a pack in the online library (labs/index.json in the repo,
sources in labsrc/) and is installed into the user labs folder. A read-only "built-in" folder still exists for
developers and the test suite: set CMLLAB_BUILTIN_LABS_DIR (e.g. to the repo's labsrc/) to use lab folders in
place. The packaged app has none (the package's own labs/ folder no longer exists).

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

LAB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
LABS_DIR = Path(os.environ.get("CMLLAB_BUILTIN_LABS_DIR") or (Path(__file__).parent / "labs"))


class LabNotFound(KeyError):
    pass


@dataclass
class Entry:
    lab: Lab
    path: Path
    source: str  # "builtin" | "user"


def user_labs_dir() -> Path:
    if os.environ.get("CMLLAB_USER_LABS_DIR"):
        return Path(os.environ["CMLLAB_USER_LABS_DIR"])
    from .config import settings_file
    return settings_file().parent / "labs"


def lab_dirs(root: Path | None = None) -> list[Path]:
    root = LABS_DIR if root is None else Path(root)
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


def entries(root: Path | None = None, user_root: Path | None = None, errors: dict | None = None) -> dict[str, Entry]:
    """Built-in (developer) labs first; user labs with a clashing id are ignored."""
    res = _scan(LABS_DIR if root is None else root, "builtin", errors)
    ur = user_labs_dir() if user_root is None else user_root
    for k, v in _scan(ur, "user", errors).items():
        if k in res:
            if errors is not None:
                errors[str(v.path)] = f"id {k!r} clashes with a built-in lab"
            continue
        res[k] = v
    return res


def load_all(root: Path | None = None) -> dict[str, Lab]:
    if root is not None and Path(root) != LABS_DIR:  # explicit root (tests): only that folder, strict
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


def get(lab_id: str, root: Path | None = None) -> Lab:
    if root is not None and Path(root) != LABS_DIR:
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
    if e.lab.is_walkthrough:
        return e.lab.step_solution()
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
