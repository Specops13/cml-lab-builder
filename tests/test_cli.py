from typer.testing import CliRunner

from encorlab.cli import app

r = CliRunner()


def test_list():
    res = r.invoke(app, ["list"])
    assert res.exit_code == 0 and "eigrp-basic" in res.output


def test_validate():
    res = r.invoke(app, ["validate"], env={"ENCOR_USE_KEYRING": "0"})
    assert res.exit_code == 0, res.output
    assert "OK   [builtin] eigrp-basic" in res.output and "solution=100.0%" in res.output


def test_task_and_export(tmp_path):
    env = {"ENCOR_USE_KEYRING": "0", "ENCOR_PLATFORM": "iol"}
    res = r.invoke(app, ["task", "eigrp-basic"], env=env)
    assert "Ethernet0/0" in res.output
    out = tmp_path / "lab.yaml"
    res = r.invoke(app, ["export", "eigrp-basic", "--cml-yaml", "--out", str(out)], env=env)
    assert res.exit_code == 0 and "version: 0.2.2" in out.read_text(encoding="utf-8")


def test_build_without_settings_fails_cleanly():
    res = r.invoke(app, ["build", "eigrp-basic"], env={"ENCOR_USE_KEYRING": "0", "CML_URL": "", "CML_USERNAME": "", "CML_PASSWORD": ""})
    assert res.exit_code != 0 and "required" in str(res.exception)
