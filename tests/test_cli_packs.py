import json
from pathlib import Path

from typer.testing import CliRunner

from cmllab import catalog, prompt
from cmllab.cli import app

r = CliRunner()
OSPF = Path(__file__).parent.parent / "examples" / "ospf-multiarea-stub"


def test_validate_pack_import_export_delete(tmp_path):
    res = r.invoke(app, ["validate", str(OSPF)])
    assert res.exit_code == 0 and "live   solution=100.0% blank=0.0%" in res.output, res.output
    out = tmp_path / "o.encorlab"
    res = r.invoke(app, ["pack", str(OSPF), "-o", str(out)])
    assert res.exit_code == 0 and out.is_file(), res.output
    res = r.invoke(app, ["import", str(out)])
    assert res.exit_code == 0, res.output
    assert catalog.entry("ospf-multiarea-stub").source == "user"
    assert r.invoke(app, ["import", str(out)]).exit_code == 1
    assert r.invoke(app, ["import", str(out), "--replace"]).exit_code == 0
    exp = tmp_path / "e.encorlab"
    assert r.invoke(app, ["export", "ospf-multiarea-stub", "-o", str(exp)]).exit_code == 0 and exp.is_file()
    assert "ospf-multiarea-stub" in r.invoke(app, ["list"]).output
    assert r.invoke(app, ["delete", "eigrp-basic", "-y"]).exit_code == 1
    assert r.invoke(app, ["delete", "ospf-multiarea-stub", "-y"]).exit_code == 0


def test_validate_bad_file_and_pack_refuses(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text(prompt.example().replace("%if0%", "Ethernet0/0"), encoding="utf-8")
    res = r.invoke(app, ["validate", str(f)])
    assert res.exit_code == 1 and "Ethernet0/0" in res.output
    assert r.invoke(app, ["pack", str(f), "-o", str(tmp_path / "x.encorlab")]).exit_code == 1
    assert not (tmp_path / "x.encorlab").exists()


def test_schema_prompt_docs(tmp_path):
    s = tmp_path / "s.json"
    assert r.invoke(app, ["schema", "-o", str(s)]).exit_code == 0 and json.loads(s.read_text(encoding="utf-8"))["$id"]
    res = r.invoke(app, ["prompt", "BGP lab"])
    assert res.exit_code == 0 and "BGP lab" in res.output
    assert r.invoke(app, ["docs", "-o", str(tmp_path / "d")]).exit_code == 0
    assert (tmp_path / "d" / "AI-PROMPT.md").is_file()
    assert "3.3.2" in r.invoke(app, ["version"]).output
