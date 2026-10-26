"""2.1.0 rename: product name, file extensions (.cmllab/.cmlcourse plus the old ones), env prefixes, tracks."""
import dataclasses
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from cmllab import PRODUCT, __version__, catalog, courses, library, packs, progress

ROOT = Path(__file__).resolve().parents[1]


def test_product_name_and_version():
    assert PRODUCT == "CML Lab Builder" and __version__ == "3.3.5"


def test_extensions_new_and_legacy_import(tmp_path, monkeypatch):
    monkeypatch.setenv("CMLLAB_USER_LABS_DIR", str(tmp_path / "labs"))
    assert packs.PACK_EXT == ".cmllab" and ".encorlab" in packs.PACK_EXTS
    assert courses.COURSE_EXT == ".cmlcourse" and ".encorcourse" in courses.COURSE_EXTS
    data = (ROOT / "labs" / "troubleshoot-ospf-7node.encorlab").read_bytes()
    for name in ("x.cmllab", "x.encorlab"):
        p = packs.read_upload(name, data)
        assert packs.parse_lab_text(p.lab_yaml)[0].id == "troubleshoot-ospf-7node"
    assert library._FILE_RE.match("a.cmllab") and library._FILE_RE.match("a.encorlab")
    assert library._FILE_RE.match("c.cmlcourse") and library._FILE_RE.match("c.encorcourse")


def test_cli_export_uses_the_new_extension(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from cmllab.cli import app
    monkeypatch.setenv("CMLLAB_USER_LABS_DIR", str(tmp_path / "labs"))
    r = CliRunner().invoke(app, ["import", str(ROOT / "library" / "troubleshoot-ospf-7node.cmllab")])
    assert r.exit_code == 0, r.output
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["export", "troubleshoot-ospf-7node"])
    assert r.exit_code == 0, r.output
    out = list(tmp_path.glob("*.cmllab"))
    assert out and zipfile.ZipFile(io.BytesIO(out[0].read_bytes())).namelist()


def test_cmllab_env_prefix_is_accepted():
    code = ("import os; os.environ.pop('CMLLAB_GRADING_MODE', None); os.environ['CMLLAB_GRADING_MODE']='config';"
            "import cmllab, cmllab.config as c; print(os.environ.get('CMLLAB_GRADING_MODE'), c.from_env().grading_mode)")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CMLLAB_GRADING", "CMLLAB_"))}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT).stdout.split()
    assert out == ["config", "config"]


def test_progress_tracks_and_encor_domains():
    ents = catalog.entries()
    a = ents["eigrp-basic"]
    b = ents["06-hsrp"]
    other = dataclasses.replace(b, lab=b.lab.model_copy(update={"track": "CCNA"}))
    hist = {"eigrp-basic": [{"ts": "2026-10-01 10:00:00", "score_pct": 100.0, "passed": True}],
            "06-hsrp": [{"ts": "2026-10-01 11:00:00", "score_pct": 50.0, "passed": False}]}
    only_encor = progress.compute(entries={"eigrp-basic": a, "06-hsrp": b}, histories=hist, walkthroughs={})
    assert [t["id"] for t in only_encor["tracks"]] == ["ENCOR"]
    mixed = progress.compute(entries={"eigrp-basic": a, "06-hsrp": other}, histories=hist, walkthroughs={})
    assert [t["id"] for t in mixed["tracks"]] == ["ENCOR", "CCNA"] and mixed["tracks"][0]["encor"]
    assert mixed["overall"]["mastery_pct"] == 75.0                       # plain average with several tracks
    assert all("06-hsrp" not in d["lab_ids"] for d in mixed["domains"])  # the CCNA lab is not in the ENCOR domains
    ccna = progress.compute(entries={"06-hsrp": other}, histories=hist, walkthroughs={})
    assert ccna["tracks"][0]["id"] == "CCNA" and not any(d["labs"] for d in ccna["domains"])


def test_track_lint_only_checks_encor_blueprints():
    import re
    p = packs.read_upload("x.cmllab", (ROOT / "library" / "troubleshoot-ospf-7node.cmllab").read_bytes())
    y = re.sub(r"(?m)^blueprint:.*(\n  - .*)*", "blueprint: ['9.9.z']", p.lab_yaml, count=1)
    assert "9.9.z" in y
    enc = packs.lint(dataclasses.replace(p, lab_yaml=y))
    assert any("9.9.z" in w for w in enc.warnings)
    other = packs.lint(dataclasses.replace(p, lab_yaml=y + "\ntrack: CCNA\n"))
    assert other.ok and not any("9.9.z" in w for w in other.warnings), other.errors
