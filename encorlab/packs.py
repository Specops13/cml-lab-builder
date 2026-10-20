"""Lab packs: import, lint/offline-test, install, export.

A pack is either
  * a single lab .yaml (solution may be embedded under `solution:`), or
  * a .encorlab file = zip with lab.yaml [+ solution.cfg, fixture_solved.yaml,
    fixture_blank.yaml, README.md] at the root (or inside one top folder).
"""
from __future__ import annotations

import io
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from . import catalog
from .grader import grade
from .platforms import MAX_PORTS, PLATFORMS, get as get_platform, node_def
from .render import to_yaml
from .schema import Lab

MAX_PACK_BYTES = 5 * 1024 * 1024
PACK_FILES = ("lab.yaml", "solution.cfg", "fixture_solved.yaml", "fixture_blank.yaml", "README.md")
PACK_EXT = ".encorlab"


class LabError(ValueError):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("; ".join(errors))


@dataclass
class Pack:
    lab_yaml: str
    solution_cfg: str | None = None
    fixtures: dict = field(default_factory=dict)   # {"solved": {...}, "blank": {...}}
    readme: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Report:
    ok: bool
    lab_id: str | None
    title: str | None
    errors: list[str]
    warnings: list[str]
    results: list[dict]   # offline grading summary lines

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ---------------------------------------------------------------- parsing
def friendly_validation_errors(e: ValidationError, data) -> list[str]:
    out = []
    for err in e.errors():
        loc = err.get("loc", ())
        parts = []
        cur = data
        for p in loc:
            if isinstance(p, int):
                label = f"[{p}]"
                try:
                    cur = cur[p]
                    if isinstance(cur, dict) and (cur.get("id") or cur.get("name")):
                        label += f" ({cur.get('id') or cur.get('name')})"
                except Exception:
                    cur = None
                parts.append(label)
            else:
                parts.append(("." if parts else "") + str(p))
                try:
                    cur = cur[p] if isinstance(cur, dict) else None
                except Exception:
                    cur = None
        where = "".join(parts) or "lab"
        msg = err.get("msg", "").removeprefix("Value error, ")
        if err.get("type") == "missing":
            msg = "required field is missing"
        elif err.get("type") == "extra_forbidden":
            msg = "unknown field"
        out.append(f"{where}: {msg}")
    return out


def parse_lab_text(text: str) -> tuple[Lab, dict]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise LabError([f"YAML syntax error{where}: {getattr(e, 'problem', e)}"])
    if not isinstance(data, dict):
        raise LabError(["lab file must be a YAML mapping (id:, title:, nodes:, ...)"])
    try:
        return Lab.model_validate(data), data
    except ValidationError as e:
        raise LabError(friendly_validation_errors(e, data))


def _safe_member(name: str) -> bool:
    return not (name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name)


def read_upload(filename: str, data: bytes) -> Pack:
    if len(data) > MAX_PACK_BYTES:
        raise LabError([f"file is larger than {MAX_PACK_BYTES // 1024 // 1024} MB"])
    name = filename.lower()
    if name.endswith((".yaml", ".yml")):
        try:
            return Pack(lab_yaml=data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            raise LabError(["file is not UTF-8 text"])
    if not (name.endswith((PACK_EXT, ".zip")) or data[:2] == b"PK"):
        raise LabError([f"unsupported file type: {filename} (use .encorlab, .zip or .yaml)"])
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise LabError(["not a valid .encorlab/zip file"])
    files = {}
    warnings = []
    total = 0
    names = [i for i in zf.infolist() if not i.is_dir()]
    tops = {Path(i.filename).parts[0] for i in names if len(Path(i.filename).parts) > 1}
    prefix = ""
    if not any(i.filename == "lab.yaml" for i in names) and len(tops) == 1:
        prefix = tops.pop() + "/"
    for info in names:
        if not _safe_member(info.filename):
            raise LabError([f"unsafe path inside pack: {info.filename}"])
        total += info.file_size
        if total > MAX_PACK_BYTES:
            raise LabError(["pack contents are too large"])
        rel = info.filename[len(prefix):] if info.filename.startswith(prefix) else info.filename
        if rel in PACK_FILES:
            files[rel] = zf.read(info).decode("utf-8-sig")
        elif not rel.startswith("__MACOSX"):
            warnings.append(f"ignored file in pack: {info.filename}")
    if "lab.yaml" not in files:
        raise LabError(["pack has no lab.yaml"])
    fixtures = {}
    for st in ("solved", "blank"):
        t = files.get(f"fixture_{st}.yaml")
        if t:
            try:
                fixtures[st] = yaml.safe_load(t) or {}
            except yaml.YAMLError as e:
                raise LabError([f"fixture_{st}.yaml: YAML error: {e}"])
    return Pack(files["lab.yaml"], files.get("solution.cfg"), fixtures, files.get("README.md"), warnings)


def read_dir(path: Path) -> Pack:
    path = Path(path)
    if path.is_file():
        return read_upload(path.name, path.read_bytes())
    if not (path / "lab.yaml").is_file():
        raise LabError([f"{path} has no lab.yaml"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in PACK_FILES:
            if (path / n).is_file():
                z.write(path / n, n)
    return read_upload("dir.encorlab", buf.getvalue())


# ---------------------------------------------------------------- linting
_LITERAL_IF = re.compile(r"\b(Ethernet|GigabitEthernet|Et|Gi)(\d+)/(\d+)\b")


def _literal_ifs(text: str) -> set[str]:
    return {m.group(0) for m in _LITERAL_IF.finditer(text or "")}


def solution_of(lab: Lab, pack: Pack) -> dict[str, str]:
    if lab.is_walkthrough:
        return lab.step_solution()
    if pack.solution_cfg:
        return catalog.parse_solution_cfg(pack.solution_cfg)
    return dict(lab.solution or {})


def lint(pack: Pack, node_limit: int = 20, strict: bool = False, builtin_ids: set[str] | None = None) -> Report:
    """strict=True (pack/AI): solution required; blank must score 0% in config mode."""
    from .sim import SimRunner
    warnings = list(pack.warnings)
    try:
        lab, _ = parse_lab_text(pack.lab_yaml)
    except LabError as e:
        return Report(False, None, None, e.errors, warnings, [])
    errors: list[str] = []
    results: list[dict] = []
    if builtin_ids and lab.id in builtin_ids:
        errors.append(f"id {lab.id!r} is used by a built-in lab; pick another id")
    if lab.node_count > node_limit:
        errors.append(f"lab has {lab.node_count} nodes; your node limit is {node_limit}")
    if lab.node_count > 8:
        warnings.append("labs with more than 8 nodes are slow to boot; keep labs small")
    # literal interface names: only OK when the lab supports exactly one platform and the name fits it.
    # Nodes with an explicit `definition` (e.g. nxosv9000) always use that definition's literal names.
    sol = solution_of(lab, pack)
    per_dev: dict[str, list[str]] = {n.name: [n.config] for n in lab.nodes}
    all_checks = lab.graded_checks + [c for st in lab.steps for c in st.checks if st.optional]
    for c in all_checks:
        per_dev.setdefault(c.device, []).extend([c.command, *c.match, *c.absent])
    for dev, cfg in sol.items():
        per_dev.setdefault(dev, []).append(cfg)
    for st in lab.steps:
        for v in st.verify:
            per_dev.setdefault(v.device, []).append(v.command)
    defs = {n.name: n.definition for n in lab.nodes}
    plat_lits: set[str] = set()
    for dev, texts in per_dev.items():
        lits = set().union(*(_literal_ifs(t) for t in texts)) if texts else set()
        nd = node_def(defs.get(dev))
        if nd is None:
            plat_lits |= lits
            continue
        ok = re.compile(rf"^({re.escape(nd.long_prefix)}|{re.escape(nd.short_prefix)})[{nd.first_port}-{nd.first_port + MAX_PORTS - 1}]$")
        bad = sorted(l for l in lits if not ok.match(l))
        if bad:
            errors.append(f"{dev}: interface names {bad} do not exist on {nd.id} in this app "
                          f"(valid: {nd.ifname(0)}-{nd.ifname(MAX_PORTS - 1)})")
    if plat_lits:
        if len(lab.platforms) > 1:
            errors.append(f"literal interface names {sorted(plat_lits)} found; use %if0%..%if3% (long) / %if0s%..%if3s% (short) "
                          "placeholders so the lab works on both IOL and IOSv, or set platforms to a single platform")
        else:
            p = PLATFORMS[lab.platforms[0]]
            ok = re.compile(rf"^({p.long_prefix}|{p.short_prefix})0/[0-{MAX_PORTS - 1}]$")
            bad = sorted(l for l in plat_lits if not ok.match(l))
            if bad:
                errors.append(f"interface names {bad} do not exist on platform {p.name} "
                              f"(valid: {p.long_prefix}0/0-0/{MAX_PORTS - 1}); prefer %ifN% placeholders")
    if not sol:
        (errors if strict else warnings).append(
            "no reference solution (solution.cfg or `solution:` in lab.yaml); the lab cannot be tested offline")
    if not lab.solution_summary.strip():
        warnings.append("no solution_summary: add a short Markdown summary (root cause, exact fix commands per device, "
                        "why it works); until then the app shows an auto-generated one built from the solution")
    from .blueprint import known as known_item
    unknown = [b for b in lab.blueprint if not known_item(b)]
    if unknown:
        warnings.append(f"blueprint items {unknown} are not ENCOR v1.2 exam topics (e.g. 3.2.b); the progress dashboard "
                        "maps them by their domain number only")
    if not lab.is_walkthrough and not lab.hints and not any(c.hint for c in lab.graded_checks):
        warnings.append("no hints: add an ordered `hints:` list (vague first) for the Hint button")
    for dev in sol:
        if dev not in {n.name for n in lab.nodes}:
            errors.append(f"solution references unknown device {dev}")
    if lab.is_walkthrough:
        for st in lab.steps:
            if st.config and not (st.checks or st.verify):
                warnings.append(f"step {st.id} changes config but has no verify commands or checks")
    if errors:
        return Report(False, lab.id, lab.title, errors, warnings, results)
    # walkthroughs: grade every step's checks (optional steps too) against all step configs
    glab = lab if not lab.is_walkthrough else lab.model_copy(update={
        "type": "challenge", "steps": [], "checks": [c for st in lab.steps for c in st.checks]})
    for plat_name in lab.platforms:
        plat = get_platform(plat_name)
        try:
            to_yaml(lab, plat, "ENCOR-")
        except Exception as e:
            errors.append(f"cannot render topology for {plat_name}: {e}")
            continue
        if not sol:
            continue
        for mode in ("config", "live"):
            if mode == "live" and not pack.fixtures.get("solved"):
                continue
            if not glab.checks_for(mode):
                continue
            solved = grade(glab, SimRunner(lab, plat, True, solution=sol, fixtures=pack.fixtures), plat, mode=mode)
            blank = grade(glab, SimRunner(lab, plat, False, solution=sol, fixtures=pack.fixtures), plat, mode=mode)
            results.append({"platform": plat_name, "mode": mode, "solution_pct": solved.score_pct, "blank_pct": blank.score_pct})
            if not solved.passed:
                for r in solved.results:
                    if not r.passed:
                        errors.append(f"[{plat_name}/{mode}] solution fails check {r.id}: " + "; ".join(r.details))
            if blank.passed:
                errors.append(f"[{plat_name}/{mode}] the starting config already passes every check - nothing to solve")
            elif blank.score_pct > 0:
                passing = [r.id for r in blank.results if r.passed]
                if lab.is_walkthrough:
                    continue      # e.g. a cabling check in the first step passes before any config
                (errors if (strict and mode == "config") else warnings).append(
                    f"[{plat_name}/{mode}] checks already passing on the starting config: {passing}")
        if sol and lab.faults:
            from .faults import validate as validate_faults
            errors.extend(validate_faults(lab, sol, plat))
    if sol and not pack.fixtures.get("solved"):
        warnings.append("live checks are not tested offline (no fixture_solved.yaml); they are validated for syntax only")
    return Report(not errors, lab.id, lab.title, errors, warnings, results)


# ---------------------------------------------------------------- install/export
def builtin_ids() -> set[str]:
    return {d.name for d in catalog.lab_dirs(catalog.LABS_DIR)}


def install(pack: Pack, node_limit: int = 20, overwrite: bool = False) -> Report:
    rep = lint(pack, node_limit=node_limit, builtin_ids=builtin_ids())
    if not rep.ok:
        return rep
    dest = catalog.user_labs_dir() / rep.lab_id
    if dest.exists() and not overwrite:
        rep.ok = False
        rep.errors.append(f"a user lab with id {rep.lab_id!r} already exists (choose replace to overwrite)")
        return rep
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    (tmp / "lab.yaml").write_text(pack.lab_yaml, encoding="utf-8")
    if pack.solution_cfg:
        (tmp / "solution.cfg").write_text(pack.solution_cfg, encoding="utf-8")
    for st, fx in pack.fixtures.items():
        (tmp / f"fixture_{st}.yaml").write_text(yaml.safe_dump(fx, sort_keys=False), encoding="utf-8")
    if pack.readme:
        (tmp / "README.md").write_text(pack.readme, encoding="utf-8")
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)
    return rep


def delete_user_lab(lab_id: str) -> None:
    e = catalog.entry(lab_id)
    if e.source != "user":
        raise LabError([f"{lab_id} is a built-in lab and cannot be deleted"])
    shutil.rmtree(e.path)


def export_pack(lab_id: str) -> bytes:
    e = catalog.entry(lab_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in PACK_FILES:
            f = e.path / n
            if f.is_file():
                z.writestr(n, f.read_text(encoding="utf-8"))
    return buf.getvalue()


def build_pack_bytes(pack: Pack) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("lab.yaml", pack.lab_yaml)
        if pack.solution_cfg:
            z.writestr("solution.cfg", pack.solution_cfg)
        for st, fx in pack.fixtures.items():
            z.writestr(f"fixture_{st}.yaml", yaml.safe_dump(fx, sort_keys=False))
        if pack.readme:
            z.writestr("README.md", pack.readme)
    return buf.getvalue()
