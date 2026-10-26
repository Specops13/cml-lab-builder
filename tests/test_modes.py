"""Grading modes: live, config, auto fallback; console TCP probe; settings persistence."""
import socket
import threading

import pytest

from cmllab import catalog, config, grader, platforms, service
from cmllab.cml import probe_console
from cmllab.schema import Check, Lab
from cmllab.sim import SimRunner
from tables import run_table

LAB = catalog.get("eigrp-basic")
P = platforms.get("iol")


def s(**kw):
    base = dict(cml_url="https://cml.x", username="u", password="p")
    base.update(kw)
    return config.Settings(**base)


class DeadRunner:
    def run(self, d, c):
        raise ConnectionRefusedError("console refused")


def test_config_mode_solved_and_blank():
    a = grader.grade(LAB, SimRunner(LAB, P, True), P, mode="config")
    b = grader.grade(LAB, SimRunner(LAB, P, False), P, mode="config")
    assert a.passed and a.mode == "config" and len(a.results) == 6
    assert b.score_pct == 0
    assert "cannot verify neighbor adjacencies" in a.notes[0]


def test_live_mode_has_no_note():
    r = grader.grade(LAB, SimRunner(LAB, P, True), P, mode="live")
    assert r.mode == "live" and r.notes == [] and len(r.results) == 5


def test_bad_mode():
    with pytest.raises(ValueError):
        grader.grade(LAB, SimRunner(LAB, P, True), P, mode="x")


R1_CONFIG_REGEXES_ROWS = [
    ("router eigrp 100\n network 1.1.1.1 0.0.0.0\n network 10.0.12.0 0.0.0.255\n", True),
    ("router eigrp 100\n network 1.0.0.0\n network 10.0.0.0\n", True),            # classful (IOS rewrites)
    ("router eigrp 100\n network 10.0.12.1 0.0.0.0\n network 1.1.1.1 0.0.0.0\n", True),
    ("router eigrp LAB\n address-family ipv4 unicast autonomous-system 100\n  network 10.0.12.0 0.0.0.255\n  network 1.1.1.1 0.0.0.0\n", True),
    ("router eigrp 10\n network 10.0.12.0 0.0.0.255\n network 1.1.1.1 0.0.0.0\n", False),  # wrong AS
    ("router eigrp 100\n network 10.0.13.0 0.0.0.255\n network 1.1.1.1 0.0.0.0\n", False),  # wrong subnet
    ("router eigrp 100\n network 10.0.12.0 0.0.0.255\n", False),                      # loopback missing
]


def _r1_config_regexes(cfg, ok):
    class Src:
        def get_config(self, d):
            return cfg
    lab = Lab.model_validate({**LAB.model_dump(), "checks": [c.model_dump() for c in LAB.checks]})
    lab.checks[:] = [c for c in lab.checks if c.mode == "live" or c.device == "R1"]
    rep = grader.grade(lab, Src(), P, mode="config")
    assert rep.passed is ok, [r.details for r in rep.results]


def test_r1_config_regexes():
    run_table(_r1_config_regexes, R1_CONFIG_REGEXES_ROWS)


def test_config_check_schema():
    with pytest.raises(ValueError):
        Check(id="x", description="d", device="R1", mode="config", command="show run", match=["a"])
    with pytest.raises(ValueError):
        Check(id="x", description="d", device="R1", mode="config", match=[])
    Check(id="x", description="d", device="R1", mode="config", match=["router eigrp"])


def test_lab_requires_both_modes():
    d = LAB.model_dump()
    d["checks"] = [c for c in d["checks"] if c["mode"] == "live"]
    with pytest.raises(ValueError, match="no config checks"):
        Lab.model_validate(d)


def test_service_live_mode():
    d = service.do_check(s(), "eigrp-basic", lambda m: None, runner=SimRunner(LAB, P, True), mode="live")
    assert d["mode"] == "live" and d["passed"] and d["notes"] == []


def test_service_config_mode():
    d = service.do_check(s(), "eigrp-basic", lambda m: None, config_source=SimRunner(LAB, P, True), mode="config")
    assert d["mode"] == "config" and d["passed"] and d["requested_mode"] == "config"


def test_auto_falls_back_when_probe_fails():
    log = []
    d = service.do_check(s(), "eigrp-basic", log.append, config_source=SimRunner(LAB, P, True), mode="auto",
                         probe=lambda h, p: {"ok": False, "detail": "TCP connect failed"})
    assert d["mode"] == "config" and d["passed"]
    assert "fell back to config mode" in d["notes"][0] and any("fell back" in m for m in log)


def test_auto_falls_back_when_all_live_checks_error():
    d = service.do_check(s(), "eigrp-basic", lambda m: None, runner=DeadRunner(),
                         config_source=SimRunner(LAB, P, True), mode="auto")
    assert d["mode"] == "config" and "could not connect" in d["notes"][0]


def test_auto_uses_live_when_available():
    d = service.do_check(s(), "eigrp-basic", lambda m: None, runner=SimRunner(LAB, P, False),
                         config_source=SimRunner(LAB, P, True), mode="auto")
    assert d["mode"] == "live" and not d["passed"]   # real failures are not masked by fallback


def test_live_only_never_falls_back():
    d = service.do_check(s(), "eigrp-basic", lambda m: None, runner=DeadRunner(),
                         config_source=SimRunner(LAB, P, True), mode="live")
    assert d["mode"] == "live" and d["score_pct"] == 0


def test_default_mode_from_settings():
    d = service.do_check(s(grading_mode="config"), "eigrp-basic", lambda m: None, config_source=SimRunner(LAB, P, True))
    assert d["mode"] == "config"


def _server(payload: bytes):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        c, _ = srv.accept()
        if payload:
            c.sendall(payload)
        c.close()
        srv.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1]


def test_probe():
    def _probe_ssh_banner():
        port = _server(b"SSH-2.0-OpenSSH_9.6\r\n")
        r = probe_console("127.0.0.1", port)
        assert r["ok"] and "SSH-2.0" in r["detail"]

    def _probe_http_proxy_detected():
        port = _server(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        r = probe_console("127.0.0.1", port)
        assert not r["ok"] and "TCP passthrough" in r["detail"]

    def _probe_closed_port():
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.close()
        r = probe_console("127.0.0.1", port, timeout=1)
        assert not r["ok"] and "failed" in r["detail"]

    def _probe_no_host():
        assert probe_console("", 22)["ok"] is False

    for case in (_probe_ssh_banner, _probe_http_proxy_detected, _probe_closed_port, _probe_no_host):
        case()


def test_settings_persistence(tmp_path):
    env = {"CMLLAB_SETTINGS_FILE": str(tmp_path / "s.json"), "CMLLAB_USE_KEYRING": "0",
           "CML_CONSOLE_HOST": "env-host", "CML_CONSOLE_PORT": "2222"}
    st = config.from_env(env)
    assert st.console_host == "env-host" and st.console_port == 2222
    st.console_host, st.console_port, st.grading_mode, st.password = "ssh.example.net", 22, "config", "SECRET"
    f = config.save_settings(st, env)
    assert "SECRET" not in f.read_text(encoding="utf-8") and "ssh.example.net" in f.read_text(encoding="utf-8")
    again = config.from_env(env)
    assert again.console_host == "ssh.example.net" and again.grading_mode == "config" and again.password == ""


def test_settings_validation_new_fields():
    st = config.SettingsStore(s())
    with pytest.raises(ValueError):
        st.update(grading_mode="magic")
    with pytest.raises(ValueError):
        st.update(console_port=70000)
    assert st.update(console_host="ssh.x", console_port="2022").console_port == 2022
