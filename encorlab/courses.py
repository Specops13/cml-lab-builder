"""Courses: a .encorcourse file bundles several labs into an ordered study track.

Format (a zip):
    course.yaml          id, title, description, labs: [lab ids in study order]
    labs/<lab-id>/...    optional lab pack files (lab.yaml, solution.cfg, fixtures, README.md)

A course may also reference built-in labs or labs that are already installed. Installing is
all-or-nothing: every bundled lab is validated first. Installed courses live in <data>/courses/<id>.yaml."""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel, Field, ValidationError

from . import catalog, packs

COURSE_EXT = ".encorcourse"
MAX_COURSE_BYTES = 20 * 1024 * 1024
MAX_LABS = 50
ID_RE = r"^[a-z0-9][a-z0-9-]{1,48}$"


class Course(BaseModel):
    id: str = Field(pattern=ID_RE)
    title: str = Field(min_length=3, max_length=120)
    description: str = ""
    author: str = ""
    version: str = ""
    labs: list[str] = Field(min_length=1, max_length=MAX_LABS)


def courses_dir() -> Path:
    from .history import data_dir
    return data_dir() / "courses"


def is_course(filename: str, data: bytes) -> bool:
    if filename.lower().endswith(COURSE_EXT):
        return True
    if data[:2] != b"PK":
        return False
    try:
        return "course.yaml" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        return False


def parse_course_yaml(text: str) -> Course:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise packs.LabError([f"course.yaml: YAML error: {e}"])
    if not isinstance(data, dict):
        raise packs.LabError(["course.yaml must be a mapping with id, title and labs"])
    try:
        c = Course.model_validate(data)
    except ValidationError as e:
        raise packs.LabError([f"course.yaml: {'.'.join(map(str, x['loc'])) or 'root'}: {x['msg']}" for x in e.errors()])
    if len(set(c.labs)) != len(c.labs):
        raise packs.LabError(["course.yaml: a lab is listed twice"])
    return c


def read_course(data: bytes) -> tuple[Course, dict[str, packs.Pack]]:
    """Parse a course zip. Returns the course and the bundled lab packs keyed by folder name."""
    if len(data) > MAX_COURSE_BYTES:
        raise packs.LabError([f"course file is larger than {MAX_COURSE_BYTES // 1024 // 1024} MB"])
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise packs.LabError(["not a valid .encorcourse/zip file"])
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if sum(i.file_size for i in infos) > MAX_COURSE_BYTES:
        raise packs.LabError(["course contents are too large"])
    names = {i.filename for i in infos}
    if "course.yaml" not in names:
        raise packs.LabError(["course file has no course.yaml"])
    groups: dict[str, dict[str, bytes]] = {}
    for i in infos:
        if not packs._safe_member(i.filename):
            raise packs.LabError([f"unsafe path inside course: {i.filename}"])
        p = PurePosixPath(i.filename)
        if len(p.parts) == 3 and p.parts[0] == "labs" and p.parts[2] in packs.PACK_FILES:
            groups.setdefault(p.parts[1], {})[p.parts[2]] = zf.read(i)
    course = parse_course_yaml(zf.read("course.yaml").decode("utf-8-sig"))
    bundled = {}
    for folder, files in groups.items():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n, b in files.items():
                z.writestr(n, b)
        bundled[folder] = packs.read_upload(f"{folder}.encorlab", buf.getvalue())
    return course, bundled


def install(data: bytes, node_limit: int = 20, overwrite: bool = False) -> dict:
    """Validate everything, then install bundled labs and record the course. Raises LabError."""
    course, bundled = read_course(data)
    errors, warnings, reports = [], [], {}
    builtin = packs.builtin_ids()
    for folder, pk in bundled.items():
        rep = packs.lint(pk, node_limit=node_limit, builtin_ids=builtin)
        reports[folder] = rep
        warnings += [f"{folder}: {w}" for w in pk.warnings + rep.warnings]
        if not rep.ok:
            errors += [f"{folder}: {e}" for e in rep.errors]
        elif rep.lab_id != folder:
            errors.append(f"labs/{folder}/ contains lab id {rep.lab_id!r}; the folder must be named after the lab id")
    if errors:
        raise packs.LabError(errors, warnings)
    missing = missing_labs(course, bundled)
    if missing:
        raise packs.LabError([f"course lists lab {m!r}, which is neither bundled nor installed (install it from the "
                              "lab library first, or install the course from the library)" for m in missing], warnings)
    extra = sorted(set(bundled) - set(course.labs))
    if extra:
        warnings.append(f"bundled labs not listed in course.yaml are installed but not part of the course: {', '.join(extra)}")
    existing = [f for f in bundled if (catalog.user_labs_dir() / f).exists() and not _same_lab(f, bundled[f])]
    if existing and not overwrite:
        raise packs.LabError([f"a user lab with id {f!r} already exists (choose replace to overwrite)" for f in existing], warnings)
    installed = []
    for folder, pk in bundled.items():
        rep = packs.install(pk, node_limit=node_limit, overwrite=True)
        if not rep.ok:   # pragma: no cover - linted above
            raise packs.LabError(rep.errors, warnings)
        installed.append(rep.lab_id)
    d = courses_dir()
    d.mkdir(parents=True, exist_ok=True)
    meta = course.model_dump()
    meta["bundled"] = sorted(installed)
    (d / f"{course.id}.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return {"ok": True, "kind": "course", "course_id": course.id, "title": course.title, "labs": course.labs,
            "installed": sorted(installed), "warnings": warnings, "errors": []}


def missing_labs(course: Course, bundled: dict) -> list[str]:
    """Labs a course lists that are neither bundled in the course file nor installed."""
    known = set(catalog.entries())
    return [lid for lid in course.labs if lid not in bundled and lid not in known]


def _same_lab(folder: str, pk: packs.Pack) -> bool:
    """An installed lab identical to the bundled copy is not a conflict (e.g. installed earlier from the library)."""
    f = catalog.user_labs_dir() / folder / "lab.yaml"
    try:
        return f.read_text(encoding="utf-8") == pk.lab_yaml
    except OSError:
        return False


def _load(path: Path) -> dict | None:
    try:
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        Course.model_validate({k: v for k, v in d.items() if k != "bundled"})
        return d
    except Exception:
        return None


def list_courses(best: dict[str, float | None] | None = None, platform: str = "iol",
                 heavy_gb: float = 16) -> list[dict]:
    """Installed courses with per-lab availability and best score (best: {lab_id: best_pct}; a completed
    walkthrough counts as 100), lab type and estimated RAM (the course's ram is its heaviest lab: labs run one
    at a time)."""
    from . import sizing
    best = best or {}
    known = catalog.entries()
    out = []
    d = courses_dir()
    for f in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        c = _load(f)
        if not c:
            continue
        labs = []
        for lid in c["labs"]:
            e = known.get(lid)
            b = best.get(lid)
            labs.append({"id": lid, "title": e.lab.title if e else lid, "available": e is not None,
                         "best": b, "solved": b is not None and b >= 100,
                         "type": e.lab.type if e else None,
                         "ram": _ram_brief(sizing.estimate(e.lab, platform, heavy_gb)) if e else None})
        done = sum(1 for x in labs if x["solved"])
        nxt = next((x["id"] for x in labs if x["available"] and not x["solved"]), None)
        out.append({"id": c["id"], "title": c["title"], "description": c.get("description", ""),
                    "author": c.get("author", ""), "version": c.get("version", ""), "labs": labs,
                    "solved": done, "total": len(labs), "pct": round(100 * done / len(labs)), "next": nxt,
                    "bundled": c.get("bundled", []),
                    "ram": max((x["ram"] for x in labs if x["ram"]), key=lambda r: r["gb"], default=None)})
    return out


def _ram_brief(r: dict) -> dict:
    return {k: r[k] for k in ("gb", "label", "heavy", "tooltip", "source")}


def delete(course_id: str, remove_labs: bool = False) -> list[str]:
    """Remove a course; optionally also delete its bundled (imported) labs that no other course uses."""
    if not re.match(ID_RE, course_id):
        raise packs.LabError([f"invalid course id {course_id!r}"])
    f = courses_dir() / f"{course_id}.yaml"
    c = _load(f) if f.exists() else None
    if not c:
        raise packs.LabError([f"course {course_id!r} is not installed"])
    removed = []
    if remove_labs:
        others = {lid for o in list_courses() if o["id"] != course_id for lid in (x["id"] for x in o["labs"])}
        for lid in c.get("bundled", []):
            if lid in others:
                continue
            try:
                packs.delete_user_lab(lid)
                removed.append(lid)
            except (packs.LabError, catalog.LabNotFound):
                pass
    f.unlink()
    return removed


# ---------------------------------------------------------------- building
_EPOCH = (2020, 1, 1, 0, 0, 0)


def _zput(z: zipfile.ZipFile, name: str, data: bytes) -> None:
    zi = zipfile.ZipInfo(name, _EPOCH)          # fixed timestamp: same input -> same bytes (stable sha256)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    z.writestr(zi, data)


def deterministic_pack(path: Path) -> bytes:
    """Pack a lab folder into .encorlab bytes reproducibly."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in packs.PACK_FILES:
            if (Path(path) / n).is_file():
                _zput(z, n, (Path(path) / n).read_bytes())
    return buf.getvalue()


def build(source: Path, search: list[Path] | None = None, known: set[str] | None = None) -> bytes:
    """Build a .encorcourse from a folder: course.yaml + labs/<id>/ (optional). Labs listed in course.yaml that
    are not built in, not in `known` (labs the library publishes as packs; the app installs them from the library
    with the course) and not under labs/ are taken from <search dir>/<id>/. Validates the result."""
    known = set(known or ()) | packs.builtin_ids()
    source = Path(source)
    if not (source / "course.yaml").is_file():
        raise packs.LabError([f"{source} has no course.yaml"])
    course = parse_course_yaml((source / "course.yaml").read_text(encoding="utf-8"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        _zput(z, "course.yaml", (source / "course.yaml").read_bytes())
        labs_dir = source / "labs"
        dirs = {p.name: p for p in labs_dir.iterdir() if p.is_dir()} if labs_dir.is_dir() else {}
        for lid in course.labs:
            for root in search or []:
                if lid not in dirs and lid not in known and (Path(root) / lid / "lab.yaml").is_file():
                    dirs[lid] = Path(root) / lid
        for _, d in sorted(dirs.items()):
            for n in packs.PACK_FILES:
                if (d / n).is_file():
                    _zput(z, f"labs/{d.name}/{n}", (d / n).read_bytes())
    data = buf.getvalue()
    _, bundled = read_course(data)
    for folder, pk in bundled.items():
        rep = packs.lint(pk, builtin_ids=packs.builtin_ids())
        if not rep.ok:
            raise packs.LabError([f"{folder}: {e}" for e in rep.errors])
    missing = [lid for lid in course.labs if lid not in bundled and lid not in known]
    if missing:
        raise packs.LabError([f"course lists {m!r}, which is neither bundled nor a library lab" for m in missing])
    return data
