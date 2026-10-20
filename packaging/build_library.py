"""Build the online lab library in labs/ (served from the GitHub repo):
    labs/<lab-id>.encorlab        one per lab folder in labsrc/ (the former built-in labs) and examples/
    labs/<course-id>.encorcourse  one per folder in examples/courses/ (labs from labsrc/ are referenced, not
                                  bundled: the app installs them from the library together with the course)
    labs/index.json               file, kind, id, title, version, sha256, size ... (checked by the app before
                                  installing) and the recommended starter set (labsrc/library.yaml)

A lab whose pack changed must raise its `version:` (the app shows "Update available" for installed copies).

Zips are built with fixed timestamps, so re-running without changes produces identical files.
Usage: python packaging/build_library.py [--check]   (--check: fail if labs/ is out of date)"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from encorlab import courses, library, packs  # noqa: E402
from encorlab.schema import version_key  # noqa: E402

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


def build(out: Path, previous: dict | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ex = ROOT / "examples"
    ids = set()
    for d in lab_folders():
        data = courses.deterministic_pack(d)
        rep = packs.lint(packs.read_upload(d.name + packs.PACK_EXT, data), strict=True)
        if not rep.ok:
            sys.exit(f"{d.name}: " + "; ".join(rep.errors))
        (out / f"{rep.lab_id}{packs.PACK_EXT}").write_bytes(data)
        ids.add(rep.lab_id)
    lib_ids = {d.name for d in LABSRC.iterdir() if (d / "lab.yaml").is_file()}
    for d in sorted(p for p in (ex / "courses").iterdir() if (p / "course.yaml").is_file()):
        c = courses.parse_course_yaml((d / "course.yaml").read_text(encoding="utf-8"))
        (out / f"{c.id}{courses.COURSE_EXT}").write_bytes(courses.build(d, search=[ex], known=lib_ids))
    idx = library.build_index(out, lab_roots=[LABSRC, ex])
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


def main() -> None:
    target = ROOT / "labs"
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as t:
            build(Path(t), _previous(target))
            new = {p.name: p.read_bytes() for p in Path(t).iterdir()}
        old = {p.name: p.read_bytes() for p in target.iterdir()} if target.is_dir() else {}
        if new != old:
            sys.exit("labs/ is out of date: run python packaging/build_library.py")
        print("labs/ is up to date")
        return
    build(target, _previous(target))
    print(f"wrote {len(list(target.iterdir()))} files to {target}")


if __name__ == "__main__":
    main()
