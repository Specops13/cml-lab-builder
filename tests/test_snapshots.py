"""Config snapshots: save running configs via the CML API, restore them as day-0 configs."""
import pytest
from typer.testing import CliRunner

from cmllab import catalog, config, exam, platforms, service, snapshots
from cmllab.cli import app as cli_app
from cmllab.sim import SimRunner
from fakes import FakeClient
from test_web import make, wait

LAB = "eigrp-basic"


def test_store_validation_and_limits():
    for bad in ("", "has space", "../x", "-x", "x" * 41):
        with pytest.raises(snapshots.SnapshotError):
            snapshots.check_name(bad)
    m = snapshots.save(LAB, "one", {"R1": "Building configuration...\n\nhostname R1\nend\n"}, "iol", "first")
    assert m["nodes"] == ["R1"] and m["note"] == "first"
    assert snapshots.load(LAB, "one")["configs"]["R1"] == "hostname R1\nend\n"     # banner stripped
    with pytest.raises(snapshots.SnapshotError, match="already exists"):
        snapshots.save(LAB, "one", {"R1": "x"}, "iol")
    snapshots.save(LAB, "one", {"R1": "hostname R1b\n"}, "iol", overwrite=True)
    with pytest.raises(snapshots.SnapshotError, match="nothing to save"):
        snapshots.save(LAB, "two", {}, "iol")
    for i in range(snapshots.MAX_PER_LAB - 1):
        snapshots.save(LAB, f"s{i}", {"R1": "x"}, "iol")
    with pytest.raises(snapshots.SnapshotError, match="at most"):
        snapshots.save(LAB, "too-many", {"R1": "x"}, "iol")
    assert len(snapshots.list_snapshots(LAB)) == snapshots.MAX_PER_LAB
    assert snapshots.as_cfg(snapshots.load(LAB, "one")) == "! device R1\nhostname R1b\n"
    snapshots.delete(LAB, "one")
    with pytest.raises(snapshots.SnapshotError, match="no snapshot"):
        snapshots.load(LAB, "one")


def test_save_and_restore_through_cml():
    lab = catalog.get(LAB)
    s = config.Settings(cml_url="https://cml.x", username="u", password="pw")
    fc = FakeClient()
    cml = service.make_cml(s, lambda st: fc)
    cl = cml.build(lab)
    src = SimRunner(lab, platforms.get("iol"), solved=True)
    meta = service.do_snapshot_save(s, LAB, "solved", lambda m: None, client_factory=lambda st: fc, config_source=src)
    assert meta["nodes"] == ["R1", "R2"]
    saved = snapshots.load(LAB, "solved")["configs"]
    assert "router eigrp 100" in saved["R1"] and not saved["R1"].startswith("Building")
    log = []
    r = service.do_snapshot_restore(s, LAB, "solved", log.append, client_factory=lambda st: fc)
    assert r["nodes"] == ["R1", "R2"] and any("snapshot 'solved'" in m for m in log)
    assert cl.get_node_by_label("R1").configuration == saved["R1"]
    # platform mismatch is refused
    s2 = config.Settings(cml_url="https://cml.x", username="u", password="pw", platform="iosv")
    with pytest.raises(snapshots.SnapshotError, match="taken on iol"):
        service.do_snapshot_restore(s2, LAB, "solved", lambda m: None, client_factory=lambda st: fc)


def test_api_snapshot_flow():
    c, fc = make(solved=True)
    assert c.get(f"/api/labs/{LAB}/snapshots").json() == {"snapshots": [], "max": snapshots.MAX_PER_LAB}
    assert wait(c, c.post(f"/api/labs/{LAB}/build").json()["job_id"])["state"] == "done"
    j = wait(c, c.post(f"/api/labs/{LAB}/snapshots?name=good&note=working").json()["job_id"])
    assert j["state"] == "done" and j["result"]["name"] == "good"
    assert c.post(f"/api/labs/{LAB}/snapshots?name=good").status_code == 409
    assert c.post(f"/api/labs/{LAB}/snapshots?name=bad%20name").status_code == 400
    lst = c.get(f"/api/labs/{LAB}/snapshots").json()["snapshots"]
    assert lst[0]["name"] == "good" and lst[0]["nodes"] == ["R1", "R2"] and lst[0]["note"] == "working"
    assert "router eigrp" in c.get(f"/api/labs/{LAB}/snapshots/good").json()["configs"]["R1"]
    cfg = c.get(f"/api/labs/{LAB}/snapshots/good?fmt=cfg")
    assert cfg.text.startswith("! device R1") and "attachment" in cfg.headers["content-disposition"]
    j = wait(c, c.post(f"/api/labs/{LAB}/snapshots/good/restore").json()["job_id"])
    assert j["state"] == "done" and j["result"]["restored"] == "good"
    assert c.post(f"/api/labs/{LAB}/snapshots/nope/restore").status_code == 404
    # blocked during an exam
    exam.start(catalog.get(LAB), 10)
    assert c.post(f"/api/labs/{LAB}/snapshots/good/restore").status_code == 403
    assert c.post(f"/api/labs/{LAB}/snapshots").status_code == 403
    assert c.get(f"/api/labs/{LAB}/snapshots/good").status_code == 403
    exam.clear(LAB)
    assert c.delete(f"/api/labs/{LAB}/snapshots/good").json() == {"deleted": "good"}
    assert c.delete(f"/api/labs/{LAB}/snapshots/good").status_code == 404


def test_cli_snapshot(monkeypatch):
    fc = FakeClient()
    lab = catalog.get(LAB)
    monkeypatch.setattr(service, "make_cml", lambda s, cf=None: service.CML(s, client_factory=lambda st: fc))
    for k, v in (("CML_URL", "https://cml.x"), ("CML_USERNAME", "u"), ("CML_PASSWORD", "pw")):
        monkeypatch.setenv(k, v)
    service.make_cml(config.from_env()).build(lab)
    for n in fc.all_labs()[0].nodes():
        n.state = "BOOTED"
        n.running_config = f"hostname {n.label}\nrouter eigrp 100\nend\n"
    run = CliRunner().invoke
    assert "no snapshots" in run(cli_app, ["snapshot", LAB]).output
    r = run(cli_app, ["snapshot", LAB, "--save", "a1", "--note", "hello"])
    assert r.exit_code == 0 and "saved a1 (R1, R2)" in r.output
    assert "a1" in run(cli_app, ["snapshot", LAB]).output and "hello" in run(cli_app, ["snapshot", LAB]).output
    assert "! device R2\nhostname R2" in run(cli_app, ["snapshot", LAB, "--show", "a1"]).output
    r = run(cli_app, ["snapshot", LAB, "--restore", "a1"], input="y\n")
    assert r.exit_code == 0 and "restored a1" in r.output
    assert run(cli_app, ["snapshot", LAB, "--delete", "a1"]).exit_code == 0
    assert run(cli_app, ["snapshot", LAB, "--show", "a1"]).exit_code == 1
