import pytest

from cmllab import catalog
from cmllab.cml import CML, CMLError
from fakes import FakeClient

LAB = catalog.get("eigrp-basic")


def mk(settings, client):
    return CML(settings, client_factory=lambda s: client, sleep=lambda s: None)


def test_requires_credentials(settings):
    settings.password = ""
    with pytest.raises(CMLError):
        CML(settings, client_factory=lambda s: FakeClient())


def test_connect_error_wrapped(settings):
    def boom(s):
        raise ConnectionError("refused")
    with pytest.raises(CMLError, match="refused"):
        CML(settings, client_factory=boom)


def test_build_imports_starts_and_waits(settings):
    c = FakeClient(boot_polls=3)
    msgs = []
    lab = mk(settings, c).build(LAB, progress=msgs.append)
    assert lab.title == "CML-eigrp-basic" and lab.calls == ["start"]
    assert all(n.state == "BOOTED" for n in lab.nodes())
    assert any("Waiting for boot" in m for m in msgs) and msgs[-1] == "All nodes booted"
    assert "version: 0.2.2" in c.imported_yaml[0]


def test_build_is_idempotent(settings):
    c = FakeClient()
    m = mk(settings, c)
    a = m.build(LAB)
    b = m.build(LAB)
    assert a is b and len(c.all_labs()) == 1


def test_rebuild_replaces(settings):
    c = FakeClient()
    m = mk(settings, c)
    a = m.build(LAB)
    b = m.build(LAB, rebuild=True)
    assert a.removed and a.calls[-3:] == ["stop", "wipe", "remove"] and b is not a


def test_capacity_check(settings):
    c = FakeClient()
    c.add_foreign_running_lab(19)
    with pytest.raises(CMLError, match="node limit"):
        mk(settings, c).build(LAB)


def test_capacity_ignores_own_running_lab(settings):
    c = FakeClient()
    c.add_foreign_running_lab(18)
    m = mk(settings, c)
    m.build(LAB)
    m.build(LAB)  # restarting own lab must not double count


def test_boot_timeout(settings):
    settings.boot_timeout = 0
    c = FakeClient(boot_polls=10**6)
    with pytest.raises(CMLError, match="did not boot"):
        mk(settings, c).build(LAB)


def test_reset(settings):
    c = FakeClient()
    m = mk(settings, c)
    lab = m.build(LAB)
    m.reset(LAB)
    assert lab.calls == ["start", "stop", "wipe", "start"]
    assert all(n.state == "BOOTED" for n in lab.nodes())


def test_reset_requires_built(settings):
    with pytest.raises(CMLError, match="not built"):
        mk(settings, FakeClient()).reset(LAB)


def test_destroy(settings):
    c = FakeClient()
    m = mk(settings, c)
    lab = m.build(LAB)
    assert m.destroy(LAB) is True and lab.removed
    assert m.destroy(LAB) is False


def test_refuse_foreign_delete(settings):
    c = FakeClient()
    m = mk(settings, c)
    foreign = c.add_foreign_running_lab(1, title="Prod lab")
    with pytest.raises(CMLError, match="refusing"):
        m._destroy(foreign)


def test_duplicate_titles(settings):
    c = FakeClient()
    m = mk(settings, c)
    m.build(LAB, start=False)
    c.import_lab(c.imported_yaml[0], title="CML-eigrp-basic")
    with pytest.raises(CMLError, match="duplicates"):
        m.find(LAB)


def test_doctor(settings):
    info = mk(settings, FakeClient()).doctor()
    assert info["version_ok"] and info["missing_node_definitions"] == []
    info = mk(settings, FakeClient(version="2.8.0", defs=["iosv"])).doctor()
    assert not info["version_ok"] and info["missing_node_definitions"] == ["iol-xe", "ioll2-xe"]


def test_status(settings):
    c = FakeClient()
    m = mk(settings, c)
    assert m.status(LAB).exists is False
    m.build(LAB)
    st = m.status(LAB)
    assert st.exists and st.nodes == {"R1": "BOOTED", "R2": "BOOTED"}


def test_runner_selection(settings):
    from cmllab.console import SSHConsoleRunner
    c = FakeClient()
    m = mk(settings, c)
    m.build(LAB)
    r = m.runner(LAB)
    assert isinstance(r, SSHConsoleRunner) and r.lab_title == "CML-eigrp-basic"


def test_reset_restores_initial_configs_after_extraction(settings):
    c = FakeClient()
    m = mk(settings, c)
    lab = m.build(LAB)
    original = lab.get_node_by_label("R1").configuration
    r1 = lab.get_node_by_label("R1")
    r1.running_config = "hostname R1\nrouter eigrp 100\n"
    m.config_source(LAB).get_config("R1")
    assert r1.configuration != original  # extraction overwrote the stored config
    m.reset(LAB)
    assert r1.configuration == original and "interface Ethernet0/0" in original


def test_config_source_extracts(settings):
    c = FakeClient()
    m = mk(settings, c)
    lab = m.build(LAB)
    n = lab.get_node_by_label("R2")
    n.running_config = "hostname R2\nrouter eigrp 100\n network 2.2.2.2 0.0.0.0\n"
    cfg = m.config_source(LAB).get_config("R2")
    assert "router eigrp 100" in cfg and n.extract_calls == 1 and "sync" in lab.calls


def test_config_source_requires_booted(settings):
    c = FakeClient()
    m = mk(settings, c)
    lab = m.build(LAB, start=False)
    with pytest.raises(CMLError, match="BOOTED"):
        m.config_source(LAB).get_config("R1")


def test_config_source_requires_built(settings):
    with pytest.raises(CMLError, match="not built"):
        mk(settings, FakeClient()).config_source(LAB)


def test_doctor_reports_console(settings, monkeypatch):
    import cmllab.cml as cmlmod
    monkeypatch.setattr(cmlmod, "probe_console", lambda h, p: {"ok": False, "detail": "refused"})
    info = mk(settings, FakeClient()).doctor()
    assert info["console_reachable"] is False and info["console_server"] == "cml.example.ts.net:22"
