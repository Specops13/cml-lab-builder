"""No user-facing text may contain raw placeholder tokens such as %if0% / %if1s%."""
import io
import json
import re
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cmllab import catalog, config, packs, platforms
from cmllab.cli import app as cli_app
from cmllab.grader import grade
from cmllab.render import to_yaml
from cmllab.sim import SimRunner
from cmllab.web.app import create_app
from fakes import FakeClient

TOKEN = re.compile(r"%\w+%")
OSPF = Path(__file__).parent.parent / "examples" / "ospf-multiarea-stub"
APP_JS = Path(__file__).parent.parent / "cmllab" / "web" / "static" / "app.js"


def no_tokens(obj, where):
    text = obj if isinstance(obj, str) else json.dumps(obj)
    found = sorted(set(TOKEN.findall(text)))
    assert not found, f"raw placeholders {found} in {where}"


@pytest.fixture
def with_pack():
    rep = packs.install(packs.read_dir(OSPF))
    assert rep.ok, rep.errors
    return [e for e in catalog.entries().values()]


def cases(entries):
    for e in entries:
        for p in e.lab.platforms:
            yield e, platforms.get(p)


def test_api_task_hints_checks_and_titles(with_pack):
    for e, plat in cases(with_pack):
        s = config.Settings(cml_url="https://cml.x", username="u", password="pw", platform=plat.name)
        c = TestClient(create_app(config.SettingsStore(s), client_factory=lambda st: FakeClient(), persist=False))
        no_tokens(c.get("/api/labs").json(), f"/api/labs ({plat.name})")
        d = c.get(f"/api/labs/{e.lab.id}").json()
        no_tokens(d, f"/api/labs/{e.lab.id} ({plat.name})")
        assert plat.long_prefix + "0/" in d["task"] or "%if" not in e.lab.task


def test_grade_reports_rendered(with_pack):
    for e, plat in cases(with_pack):
        sol = catalog.load_solution(e.lab.id)
        for solved in (True, False):
            for mode in ("live", "config"):
                rep = grade(e.lab, SimRunner(e.lab, plat, solved, solution=sol), plat, mode=mode).to_dict()
                no_tokens(rep, f"grade {e.lab.id} {plat.name} {mode} solved={solved}")


def test_cml_topology_rendered(with_pack):
    for e, plat in cases(with_pack):
        no_tokens(to_yaml(e.lab, plat, "CML-"), f"topology {e.lab.id} {plat.name}")


def test_cli_task_and_list(with_pack):
    r = CliRunner()
    for e, plat in cases(with_pack):
        out = r.invoke(cli_app, ["task", e.lab.id], env={"CMLLAB_PLATFORM": plat.name}).output
        no_tokens(out, f"cli task {e.lab.id} {plat.name}")
    no_tokens(r.invoke(cli_app, ["list"]).output, "cli list")


def test_ospf_task_names_per_platform(with_pack):
    r = CliRunner()
    iol = r.invoke(cli_app, ["task", "ospf-multiarea-stub"], env={"CMLLAB_PLATFORM": "iol"}).output
    assert "R1 Ethernet0/0 - R2 Ethernet0/0" in iol and "R2 Ethernet0/1 - R3 Ethernet0/0" in iol


def test_template_description_with_interface_rendered():
    lab_d = yaml.safe_load((OSPF / "lab.yaml").read_text(encoding="utf-8"))
    lab_d["checks"].append({"id": "r1-if", "template": "interface_up", "device": "R1", "params": {"interface": "%if0%"},
                            "hint": "Check %if0% on R1"})
    from cmllab.schema import Lab
    lab = Lab.model_validate(lab_d)
    plat = platforms.get("iol")
    rep = grade(lab, SimRunner(lab, plat, False, solution={}, fixtures={}), plat, mode="live").to_dict()
    r = next(x for x in rep["results"] if x["id"] == "r1-if")
    assert r["description"] == "Ethernet0/0 is up/up" and r["hint"] == "Check Ethernet0/0 on R1"
    no_tokens(rep, "template interface_up")


def test_exported_readmes_have_no_tokens(with_pack):
    for e in with_pack:
        z = zipfile.ZipFile(io.BytesIO(packs.export_pack(e.lab.id)))
        if "README.md" in z.namelist():
            no_tokens(z.read("README.md").decode(), f"README of {e.lab.id}")


def test_builder_preview_js_matches_python_platforms():
    m = re.search(r'const IFNAMES = \{iol: \["([^"]+)", "([^"]+)"\], iosv: \["([^"]+)", "([^"]+)"\]\}', APP_JS.read_text(encoding="utf-8"))
    assert m, "IFNAMES table missing in app.js"
    iol, iosv = platforms.get("iol"), platforms.get("iosv")
    assert (m.group(1) + "2", m.group(2) + "2") == (iol.ifname(2, False), iol.ifname(2, True))
    assert (m.group(3) + "2", m.group(4) + "2") == (iosv.ifname(2, False), iosv.ifname(2, True))
