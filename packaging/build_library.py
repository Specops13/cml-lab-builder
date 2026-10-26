"""Build the online lab library in library/ (served from the GitHub repo):
    library/<lab-id>.cmllab        one per lab folder in labsrc/ (the former built-in labs) and examples/
    library/<course-id>.cmlcourse  one per folder in examples/courses/ (labs from labsrc/ are referenced, not
                                   bundled: the app installs them from the library together with the course)
    library/index.json             file, kind, id, title, version, sha256, size ... (checked by the app before
                                   installing) and the recommended starter set (labsrc/library.yaml)
and the same files under the pre-2.1 names in labs/ (*.encorlab, *.encorcourse, index.json) for 2.0.x apps, which
read labs/index.json and only accept those extensions. The pack bytes are identical in both folders.

A lab whose pack changed must raise its `version:` (the app shows "Update available" for installed copies).
Every lab must carry exam-objective tags (exams.yaml next to lab.yaml, ids from cmllab/exams/*.yaml): unknown
objective ids and untagged labs fail the build.

Zips are built with fixed timestamps, so re-running without changes produces identical files.
Usage: python packaging/build_library.py [--check]   (--check: fail if labs/ is out of date)"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from cmllab import courses, library, packs, topics  # noqa: E402
from cmllab.schema import version_key  # noqa: E402

LABSRC = ROOT / "labsrc"


def lab_folders() -> list[Path]:
    out = {}
    for root in (LABSRC, ROOT / "examples"):
        for d in sorted(p for p in root.iterdir() if (p / "lab.yaml").is_file()):
            if d.name in out:
                sys.exit(f"lab id {d.name!r} exists in both {out[d.name].parent} and {root}")
            out[d.name] = d
    return [out[k] for k in sorted(out)]


def starter() -> list[str]:
    d = yaml.safe_load((LABSRC / "library.yaml").read_text(encoding="utf-8")) or {}
    return [str(x) for x in d.get("starter", [])]


def topic_map(ids: set[str]) -> dict[str, list[str]]:
    """labsrc/library.yaml `topics:`: every library lab, known subject topics only (cmllab/topics.py)."""
    d = yaml.safe_load((LABSRC / "library.yaml").read_text(encoding="utf-8")) or {}
    m = {str(k): v for k, v in (d.get("topics") or {}).items()}
    errs = [f"{k}: not a library lab" for k in m if k not in ids]
    errs += [f"{k}: no topics in labsrc/library.yaml" for k in sorted(ids) if not m.get(k)]
    for k, v in m.items():
        bad = [t for t in (v or []) if t not in topics.SUBJECTS]
        if bad:
            errs.append(f"{k}: unknown topic(s) {bad} (see cmllab/topics.py)")
    if errs:
        sys.exit("labsrc/library.yaml topics: " + "; ".join(errs))
    return {k: list(v) for k, v in m.items()}


def build(out: Path, previous: dict | None = None, pack_ext: str = packs.PACK_EXT,
          course_ext: str = courses.COURSE_EXT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ex = ROOT / "examples"
    ids = set()
    for d in lab_folders():
        data = courses.deterministic_pack(d)
        rep = packs.lint(packs.read_upload(d.name + packs.PACK_EXT, data), strict=True)
        if not rep.ok:
            sys.exit(f"{d.name}: " + "; ".join(rep.errors))
        untagged = [w for w in rep.warnings if w.startswith("no exam objectives")]
        if untagged:         # every library lab names the exam objectives it covers (exams.yaml, 3.3.5)
            sys.exit(f"{d.name}: {untagged[0]}")
        (out / f"{rep.lab_id}{pack_ext}").write_bytes(data)
        ids.add(rep.lab_id)
    lib_ids = {d.name for d in LABSRC.iterdir() if (d / "lab.yaml").is_file()}
    for d in sorted(p for p in (ex / "courses").iterdir() if (p / "course.yaml").is_file()):
        c = courses.parse_course_yaml((d / "course.yaml").read_text(encoding="utf-8"))
        (out / f"{c.id}{course_ext}").write_bytes(courses.build(d, search=[ex], known=lib_ids))
    idx = library.build_index(out, lab_roots=[LABSRC, ex], topic_map=topic_map(ids))
    bad = [s for s in starter() if s not in ids]
    if bad:
        sys.exit(f"labsrc/library.yaml: starter labs not in the library: {bad}")
    idx["starter"] = starter()
    for it in idx["items"]:
        old = next((o for o in (previous or {}).get("items", []) if o.get("file") == it["file"]), None)
        if (it.get("kind") == "lab" and old and old.get("sha256") != it["sha256"]
                and version_key(old.get("version", "1")) >= version_key(it.get("version", "1"))):
            sys.exit(f"{it['file']} changed: raise `version:` in its lab.yaml (now {it.get('version', 1)}) so "
                     "installed copies are offered the update")
    (out / "index.json").write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")


def _previous(target: Path) -> dict:
    try:
        return json.loads((target / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


TARGETS = ((ROOT / "library", packs.PACK_EXT, courses.COURSE_EXT), (ROOT / "labs", ".encorlab", ".encorcourse"))


def main() -> None:
    for target, pext, cext in TARGETS:
        if "--check" in sys.argv:
            with tempfile.TemporaryDirectory() as t:
                build(Path(t), _previous(target), pext, cext)
                new = {p.name: p.read_bytes() for p in Path(t).iterdir()}
            old = {p.name: p.read_bytes() for p in target.iterdir()} if target.is_dir() else {}
            if new != old:
                sys.exit(f"{target.name}/ is out of date: run python packaging/build_library.py")
            print(f"{target.name}/ is up to date")
            continue
        build(target, _previous(target), pext, cext)
        print(f"wrote {len(list(target.iterdir()))} files to {target}")


if __name__ == "__main__":
    main()
