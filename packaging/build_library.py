"""Build the online lab library in labs/ (served from the GitHub repo):
    labs/<lab-id>.encorlab        one per folder in examples/ that has a lab.yaml
    labs/<course-id>.encorcourse  one per folder in examples/courses/
    labs/index.json               file, kind, id, title, sha256, size ... (checked by the app before installing)

Zips are built with fixed timestamps, so re-running without changes produces identical files.
Usage: python packaging/build_library.py [--check]   (--check: fail if labs/ is out of date)"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from encorlab import courses, library, packs  # noqa: E402


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ex = ROOT / "examples"
    for d in sorted(p for p in ex.iterdir() if (p / "lab.yaml").is_file()):
        data = courses.deterministic_pack(d)
        rep = packs.lint(packs.read_upload(d.name + packs.PACK_EXT, data), builtin_ids=packs.builtin_ids())
        if not rep.ok:
            sys.exit(f"{d.name}: " + "; ".join(rep.errors))
        (out / f"{rep.lab_id}{packs.PACK_EXT}").write_bytes(data)
    for d in sorted(p for p in (ex / "courses").iterdir() if (p / "course.yaml").is_file()):
        c = courses.parse_course_yaml((d / "course.yaml").read_text(encoding="utf-8"))
        (out / f"{c.id}{courses.COURSE_EXT}").write_bytes(courses.build(d, search=[ex]))
    (out / "index.json").write_text(json.dumps(library.build_index(out), indent=2) + "\n", encoding="utf-8")


def main() -> None:
    target = ROOT / "labs"
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as t:
            build(Path(t))
            new = {p.name: p.read_bytes() for p in Path(t).iterdir()}
        old = {p.name: p.read_bytes() for p in target.iterdir()} if target.is_dir() else {}
        if new != old:
            sys.exit("labs/ is out of date: run python packaging/build_library.py")
        print("labs/ is up to date")
        return
    build(target)
    print(f"wrote {len(list(target.iterdir()))} files to {target}")


if __name__ == "__main__":
    main()
