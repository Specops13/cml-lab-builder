"""Console links: CML web URL + console server commands per node."""
from typer.testing import CliRunner

from encorlab import catalog, config, service
from encorlab.cli import app as cli_app
from fakes import FakeClient
from test_web import make, wait


def test_status_includes_console_commands():
    c, fc = make()
    assert "consoles" not in c.get("/api/labs/eigrp-basic/status").json()   # not built yet
    assert wait(c, c.post("/api/labs/eigrp-basic/build").json()["job_id"])["state"] == "done"
    st = c.get("/api/labs/eigrp-basic/status").json()
    lab_id = st["lab_id"]
    assert st["cml_lab_url"] == f"https://cml.x/lab/{lab_id}" and st["cml_title"] == "ENCOR-eigrp-basic"
    assert [x["node"] for x in st["consoles"]] == ["R1", "R2"]
    r1 = st["consoles"][0]
    assert r1["ssh"] == 'ssh -t u@cml.x "open /ENCOR-eigrp-basic/R1/0"' and r1["state"] == "BOOTED"
    assert "pw" not in str(st)    # never leaks the password


def test_console_info_custom_port_host_and_unsafe_title():
    lab = catalog.get("06-hsrp")
    s = config.Settings(cml_url="https://cml.example.com/", username="dylan", password="x",
                        console_host="console.example.com", console_port=2222, lab_prefix='ENCOR "x" ')
    d = service.console_info(s, lab, "1234-abcd", {"R1": "BOOTED"})
    assert d["cml_lab_url"] == "https://cml.example.com/lab/1234-abcd"
    first = d["consoles"][0]
    # a title with quotes would break the command line, so the lab UUID is used instead (the console server accepts ids)
    assert first["path"] == f"/1234-abcd/{lab.nodes[0].name}/0"
    assert first["ssh"].startswith('ssh -t -p 2222 dylan@console.example.com "open /1234-abcd/')
    assert len(d["consoles"]) == len(lab.nodes) and d["consoles"][1]["state"] is None


def test_cli_console(monkeypatch):
    fc = FakeClient()
    monkeypatch.setattr(service, "make_cml", lambda s, cf=None: service.CML(s, client_factory=lambda st: fc))
    monkeypatch.setenv("CML_URL", "https://cml.x"); monkeypatch.setenv("CML_USERNAME", "u"); monkeypatch.setenv("CML_PASSWORD", "pw")
    r = CliRunner().invoke(cli_app, ["console", "eigrp-basic"])
    assert r.exit_code == 1 and "not built" in r.output
    service.make_cml(config.from_env()).build(catalog.get("eigrp-basic"))
    r = CliRunner().invoke(cli_app, ["console", "eigrp-basic"])
    assert r.exit_code == 0 and "CML web UI: https://cml.x/lab/" in r.output and '"open /ENCOR-eigrp-basic/R2/0"' in r.output
