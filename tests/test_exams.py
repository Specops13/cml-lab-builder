"""Exam-objective map (3.3.5): the exam registry (cmllab/exams/*.yaml), tags on labs and steps (exams.yaml sidecar
or inline `exams:`), validation in lint and build_library.py, the API, CLI and library UI. Per-lab tag checks for
the library are in test_lab_content.py."""
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cmllab import catalog, cli, config, objectives, packs
from cmllab.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "cmllab" / "web" / "static"
EXPECTED = {"CCNA": ("200-301", "v1.1", 111), "ENCOR": ("350-401", "v1.2", 59), "ENARSI": ("300-410", "v1.1", 55),
            "DCCOR": ("350-601", "v1.2", 72), "CCIE-EI": ("", "v1.1", 272), "CCIE-DC": ("", "v3.1", 145)}


def client():
    return TestClient(create_app(config.SettingsStore(config.Settings()), persist=False))


def test_registry_is_sourced_from_cisco_and_consistent():
    reg = objectives.registry()
    assert set(reg) == set(EXPECTED)
    for eid, ex in reg.items():
        code, ver, n = EXPECTED[eid]
        assert (code == "" or ex.code == code) and ex.version == ver and len(ex.objectives) == n, eid
        assert ex.source.startswith("https://learningcontent.cisco.com/documents/marketing/exam-topics/"), eid
        assert ex.source.endswith(".pdf") and re.match(r"\d{4}-\d{2}-\d{2}$", ex.published), eid
        assert sum(w for _, w in ex.domains.values()) == 100, eid
        for oid, text in ex.objectives.items():
            assert objectives.split(f"{eid} {oid}") == (eid, oid) and text.strip(), (eid, oid)
            assert ex.domain(oid) in ex.domains, (eid, oid)
            p = oid.rsplit(".", 1)[0]
            assert p.count(".") == 0 or p in ex.objectives, (eid, oid)    # sub-items have their parent
        assert ex.leaves() and set(ex.leaves()) <= set(ex.objectives)
    assert reg["ENCOR"].text("3.2.b").startswith("Configure simple OSPFv2/v3")


def test_tags_validate_normalize_describe_and_chips():
    assert objectives.problem("ENCOR 3.2.b") is None and objectives.problem("CCIE-DC 1.2.a.ii") is None
    for bad, why in (("ENCOR 9.9", "no objective 9.9"), ("FOO 1.1", "unknown exam"), ("ENCOR", "use '<EXAM> <objective>'"),
                     ("3.2.b", "use '<EXAM>")):
        assert why in objectives.problem(bad), bad
    assert objectives.normalize(["encor  3.2.b", "ENCOR 3.2.b", " CCNA 3.4 "]) == ["ENCOR 3.2.b", "CCNA 3.4"]
    d = objectives.describe("ENCOR 3.2.b")
    assert d["known"] and d["topic"] == "OSPF" and d["version"] == "v1.2" and d["domain"] == "Infrastructure"
    assert objectives.describe("CCIE-EI 1.3.a")["label"] == "CCIE EI"
    assert [c["tag"] for c in objectives.chips(["ENCOR 3.2.b", "ENCOR 9.9", "nonsense"])] == ["ENCOR 3.2.b"]


def test_sidecar_roundtrip_apply_and_inline_tags():
    text = objectives.dump_sidecar(["ENCOR 3.2.b"], {"s1": ["CCNA 3.4"], "s2": []})
    assert objectives.read_sidecar(text) == {"lab": ["ENCOR 3.2.b"], "steps": {"s1": ["CCNA 3.4"]}}
    for bad in ("[1, 2]", "lab: x", "steps: {a: b}", "lab: []\nother: 1"):
        with pytest.raises(ValueError):
            objectives.read_sidecar(bad)
    lab = catalog.get("18-evpn-vxlan")             # tags come from labsrc/18-evpn-vxlan/exams.yaml
    assert "ENCOR 2.3.b" in lab.exams and lab.step("underlay-ospf").exams[0] == "ENCOR 3.2.b"
    tags = objectives.lab_tags(lab)
    assert tags[: len(lab.exams)] == lab.exams and "CCIE-DC 1.2.a.ii" in tags and len(set(tags)) == len(tags)
    d = yaml.safe_load((catalog.LABS_DIR / "eigrp-basic" / "lab.yaml").read_text(encoding="utf-8"))
    d["exams"] = ["ENARSI 1.1"]                    # inline tags (3.3.5+ schema) win over the sidecar
    pk = packs.Pack(yaml.safe_dump(d), exams_yaml="lab: [ENCOR 3.2.a]\n")
    assert packs.pack_lab(pk).exams == ["ENARSI 1.1"]


def test_lint_warns_untagged_and_rejects_unknown_ids_and_steps():
    d = yaml.safe_load((catalog.LABS_DIR / "eigrp-basic" / "lab.yaml").read_text(encoding="utf-8"))
    rep = packs.lint(packs.Pack(yaml.safe_dump(d)))
    assert any(w.startswith("no exam objectives") and "suggested: '" in w for w in rep.warnings), rep.warnings
    rep = packs.lint(packs.Pack(yaml.safe_dump(d), exams_yaml="lab: [ENCOR 7.7]\n"))
    assert not rep.ok and any("no objective 7.7" in e for e in rep.errors)
    rep = packs.lint(packs.Pack(yaml.safe_dump(d), exams_yaml="lab: [ENCOR 3.2.a]\nsteps: {nope: [CCNA 3.4]}\n"))
    assert not rep.ok and any("step 'nope'" in e for e in rep.errors)


def test_build_library_refuses_untagged_or_unknown_objectives(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_library
    src = tmp_path / "eigrp-basic"
    shutil.copytree(catalog.LABS_DIR / "eigrp-basic", src)
    monkeypatch.setattr(build_library, "lab_folders", lambda: [src])
    (src / "exams.yaml").unlink()
    with pytest.raises(SystemExit, match="no exam objectives"):
        build_library.build(tmp_path / "out")
    (src / "exams.yaml").write_text("lab: [ENCOR 3.9.z]\n")
    with pytest.raises(SystemExit, match="no objective 3.9.z"):
        build_library.build(tmp_path / "out")


def test_coverage_suggest_and_vocabulary():
    labs = [e.lab for e in catalog.entries().values()]
    cov = objectives.coverage(labs)
    assert set(cov) == set(objectives.registry())
    assert "18-evpn-vxlan" in cov["ENCOR"]["2.3.b"] and "18-evpn-vxlan" in cov["CCIE-DC"]["1.2.a.ii"]
    assert "3.2" not in cov["ENCOR"] and "3.2.b" in cov["ENCOR"]      # leaves only; parent tags cover sub-items
    sug = objectives.suggest(["3.2.b"], "ENCOR", "OSPF lab")
    assert sug[:2] == ["ENCOR 3.2.b", "CCNA 3.4"] and len(sug) <= 12      # own exam, then CCNA -> CCIE, parents
    voc = objectives.vocabulary(["ENCOR 3.2.b", "ENCOR 3.2.a", "CCNA 3.4", "BAD 1.1"])
    assert [e["id"] for e in voc] == ["CCNA", "ENCOR"]
    assert [o["id"] for o in voc[1]["objectives"]] == ["3.2.a", "3.2.b"]                   # blueprint order


def test_api_exams_suggest_and_lab_chips():
    c = client()
    ex = c.get("/api/exams").json()["exams"]
    assert {e["id"] for e in ex} == set(EXPECTED) and all(e["source"] and e["objectives"] for e in ex)
    s = c.get("/api/exams/suggest", params={"blueprint": "3.2.b", "track": "ENCOR", "text": "OSPF"}).json()
    assert s["tags"][0] == "ENCOR 3.2.b" and s["exams"][0]["topic"] == "OSPF"
    labs = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}
    chip = labs["18-evpn-vxlan"]["exams"][0]
    assert chip["tag"] == "ENCOR 2.3.b" and chip["text"] and chip["topic"]
    d = c.get("/api/labs/18-evpn-vxlan").json()
    assert d["exams"][0]["tag"] == "ENCOR 2.3.b"
    step = next(st for st in d["steps"] if st["id"] == "underlay-ospf")
    assert [x["tag"] for x in step["exams"]][:1] == ["ENCOR 3.2.b"]


def test_cli_exams():
    r = CliRunner().invoke(cli.app, ["exams"])
    assert r.exit_code == 0 and all(e in r.output for e in EXPECTED) and "learningcontent.cisco.com" in r.output
    r = CliRunner().invoke(cli.app, ["exams", "encor", "--coverage"])
    assert r.exit_code == 0 and re.search(r"^3\.2\.b .*<- .*", r.output, re.M) and "(no lab)" in r.output
    r = CliRunner().invoke(cli.app, ["exams", "--suggest", "3.2.b"])
    assert r.exit_code == 0 and r.output.startswith("ENCOR 3.2.b")
    assert CliRunner().invoke(cli.app, ["exams", "NOPE"]).exit_code != 0


def test_library_ui_has_exam_chips_filters_and_builder_field():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    fz = (STATIC / "fuzzy.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for needle in ('id="lib-exam"', 'id="lib-obj"', "data-exam-tag", 'data-help="lib.cardExam"', 'id="f-exams"',
                   'id="f-exams-suggest"', "/api/exams/suggest"):
        assert needle in js, needle
    assert re.search(r"exams:\s*1\.8", fz)
    for tok in ("--color-exam:", "--color-exam-bg:", "--color-exam-border:"):
        assert css.count(tok) >= 2, tok          # light and dark
    assert ".tag.exam" in css and ".chip.exam" in css
