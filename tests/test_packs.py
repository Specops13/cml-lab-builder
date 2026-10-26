import io
import zipfile

import pytest
import yaml

from cmllab import catalog, packs, prompt
from tables import run_table

EXAMPLE = prompt.example()


def zbytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, t in files.items():
            z.writestr(n, t)
    return buf.getvalue()


def test_read_yaml_and_strict_lint_ok():
    pk = packs.read_upload("x.yaml", EXAMPLE.encode())
    rep = packs.lint(pk, strict=True, builtin_ids=packs.builtin_ids())
    assert rep.ok, rep.errors
    assert rep.lab_id == "example-eigrp-pair"
    assert {(r["platform"], r["mode"]) for r in rep.results} >= {("iol", "config"), ("iosv", "config")}
    assert all(r["solution_pct"] == 100 and r["blank_pct"] == 0 for r in rep.results)


def test_zip_with_top_folder_and_ignored_files():
    pk = packs.read_upload("a.encorlab", zbytes({"mylab/lab.yaml": EXAMPLE, "mylab/notes.txt": "x"}))
    assert "example-eigrp-pair" in pk.lab_yaml
    assert any("notes.txt" in w for w in pk.warnings)


BAD_UPLOADS_ROWS = [
    ("a.encorlab", b"not a zip", "not a valid"),
    ("a.encorlab", None, "unsafe path"),
    ("a.txt", b"hello", "unsupported file type"),
    ("a.encorlab", zbytes({"readme.md": "x"}), "no lab.yaml"),
    ("a.yaml", b"\xff\xfe\x00bad", "UTF-8"),
]


def _bad_uploads(name, data, msg):
    if data is None:
        data = zbytes({"../evil/lab.yaml": EXAMPLE})
    with pytest.raises(packs.LabError) as e:
        packs.read_upload(name, data)
    assert msg in " ".join(e.value.errors)


def test_bad_uploads():
    run_table(_bad_uploads, BAD_UPLOADS_ROWS)


def test_upload_limits_and_friendly_errors():
    def _too_big():
        with pytest.raises(packs.LabError) as e:
            packs.read_upload("a.yaml", b"x" * (packs.MAX_PACK_BYTES + 1))
        assert "larger" in e.value.errors[0]

    def _friendly_errors_have_paths():
        d = yaml.safe_load(EXAMPLE)
        d["difficulty"] = 9
        d["checks"][0]["bogus"] = 1
        rep = packs.lint(packs.Pack(yaml.safe_dump(d)))
        assert not rep.ok
        text = "\n".join(rep.errors)
        assert "difficulty" in text and "checks[0]" in text

    def _yaml_syntax_error_reports_line():
        rep = packs.lint(packs.Pack("id: x\nnodes: [\n"))
        assert not rep.ok and "line" in rep.errors[0].lower()

    for case in (_too_big, _friendly_errors_have_paths, _yaml_syntax_error_reports_line):
        case()


def test_literal_interface_rejected():
    rep = packs.lint(packs.Pack(EXAMPLE.replace("interface %if0%", "interface Ethernet0/0", 1)))
    assert not rep.ok and any("Ethernet0/0" in e for e in rep.errors)


def test_strict_requires_solution_and_blank_fail():
    d = yaml.safe_load(EXAMPLE)
    sol = d.pop("solution")
    assert not packs.lint(packs.Pack(yaml.safe_dump(d)), strict=True).ok
    assert packs.lint(packs.Pack(yaml.safe_dump(d)), strict=False).ok
    # answer leaked into the starting config -> blank passes -> error
    d["solution"] = sol
    d["nodes"][0]["config"] += sol["R1"]
    d["nodes"][1]["config"] += sol["R2"]
    rep = packs.lint(packs.Pack(yaml.safe_dump(d)), strict=True)
    assert not rep.ok and any("blank" in e.lower() or "starting" in e.lower() for e in rep.errors)


def test_builtin_id_clash():
    d = yaml.safe_load(EXAMPLE)
    d["id"] = "eigrp-basic"
    rep = packs.install(packs.Pack(yaml.safe_dump(d)))
    assert not rep.ok and any("built-in" in e for e in rep.errors)


def test_install_replace_export_delete_roundtrip():
    pk = packs.read_upload("x.yaml", EXAMPLE.encode())
    assert packs.install(pk).ok
    e = catalog.entry("example-eigrp-pair")
    assert e.source == "user" and catalog.load_solution("example-eigrp-pair")
    rep = packs.install(pk)
    assert not rep.ok and "already exists" in rep.errors[-1]
    assert packs.install(pk, overwrite=True).ok
    data = packs.export_pack("example-eigrp-pair")
    assert packs.lint(packs.read_upload("e.encorlab", data), strict=True).ok
    with pytest.raises(packs.LabError):
        packs.delete_user_lab("eigrp-basic")
    packs.delete_user_lab("example-eigrp-pair")
    with pytest.raises(catalog.LabNotFound):
        catalog.entry("example-eigrp-pair")


def test_broken_user_lab_listed_not_fatal(tmp_path):
    bad = catalog.user_labs_dir() / "broken"
    bad.mkdir(parents=True)
    (bad / "lab.yaml").write_text("id: [", encoding="utf-8")
    errors = {}
    es = catalog.entries(errors=errors)
    assert "eigrp-basic" in es and errors


def test_builtin_packs_roundtrip_through_pack_bytes():
    for lid, e in catalog.entries().items():
        pk = packs.read_dir(e.path)
        again = packs.read_upload("p.encorlab", packs.build_pack_bytes(pk))
        assert packs.lint(again, strict=True).ok, lid
