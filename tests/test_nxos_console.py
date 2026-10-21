"""2.1.0: console sessions to NX-OS (nxosv9000) against a scripted fake of the CML console server + NX-OS console,
the SSH host key of the console server (trust on first use), and the "Test console" diagnosis."""
import threading
import time

import pytest

from cmllab import config, console
from cmllab.console import ConsoleError, SSHConsoleRunner, diagnose

ESC = "\x1b"


class FakeNX:
    """consoles> -> open /lab/node/0 -> an NX-OS console with the quirks of a real one: bare \\r before prompts,
    \\r\\r\\n line ends, ANSI/OSC escapes, a login: prompt (console exec-timeout), optional POAP first-boot dialog,
    paging (--More--) when `terminal length 0` is not sent, slow output."""

    def __init__(self, host="LEAF1", users=(("cisco", "cisco"),), poap=False, not_running=False, paging=False,
                 slow=False, weird_prompt=False, banner=True):
        self.out = "Welcome\r\nconsoles> "
        self.mode, self.inbuf, self.closed = "menu", "", False
        self.host, self.users, self.poap, self.not_running = host, dict(users), poap, not_running
        self.paging, self.slow, self.weird, self.banner = paging, slow, weird_prompt, banner
        self.user, self.sent, self.length0, self.lock = None, [], False, threading.Lock()
        self.pending = []           # (time, text) for slow output

    def recv_ready(self):
        now = time.monotonic()
        with self.lock:
            while self.pending and self.pending[0][0] <= now:
                self.out += self.pending.pop(0)[1]
        return bool(self.out)

    def recv(self, n):
        d, self.out = self.out[:n], self.out[n:]
        return d.encode()

    def p(self):
        return "\r\n\r" + (f"{ESC}]0;{self.host}\x07" if not self.weird else "") + (f"{self.host}# " if not self.weird else "bash-4.4$ ")

    def send(self, data):
        self.inbuf += data
        while "\r" in self.inbuf or (self.mode == "more" and " " in self.inbuf):
            if self.mode == "more" and self.inbuf.startswith(" "):
                self.inbuf = self.inbuf[1:]
                self._more()
                continue
            line, self.inbuf = self.inbuf.split("\r", 1)
            self.sent.append(line)
            self.handle(line)

    def handle(self, line):
        if self.mode == "menu":
            if self.not_running:
                self.out += line + "\r\nNode not found or not running.\r\nconsoles> "
                return
            self.mode = "poap" if self.poap else "idle"
            self.out += line + "\r\n" + ("Connected to CML terminalserver, line 0.\r\nEscape character is '^]'.\r\n" if self.banner else "")
            return
        if self.mode == "poap":
            if not line:
                self.out += "\r\nAbort Power On Auto Provisioning [yes - continue with normal setup, skip - bypass password and basic configuration, no - continue with Power On Auto Provisioning] (yes/skip/no)[no]: "
                return
            assert line == "yes"
            self.mode = "secure"
            self.out += "yes\r\n\r\n         ---- System Admin Account Setup ----\r\n\r\nDo you want to enforce secure password standard (yes/no) [y]: "
            return
        if self.mode == "secure":
            assert line == "no"
            self.mode = "adminpw"
            self.out += "\r\n  Enter the password for \"admin\": "
            return
        if self.mode == "adminpw":
            self.users["admin"] = line
            self.mode = "confirm"
            self.out += "\r\n  Confirm the password for \"admin\": "
            return
        if self.mode == "confirm":
            self.mode = "basic"
            self.out += "\r\n\r\nWould you like to enter the basic configuration dialog (yes/no): "
            return
        if self.mode == "basic":
            assert line == "no"
            self.host = "switch"
            self.mode = "idle"
            self.out += "\r\n\r\n"
            return
        if self.mode == "idle":                       # logged out by the console exec-timeout
            self.mode = "login"
            self.out += f"\r\r\nUser Access Verification\r\r\n{self.host} login: "
            return
        if self.mode == "login":
            if not line:
                self.out += f"\r\r\n{self.host} login: "
                return
            self.user, self.mode = line, "pw"
            self.out += line + "\r\r\nPassword: "
            return
        if self.mode == "pw":
            if self.users.get(self.user) == line:
                self.mode = "exec"
                self.out += "\r\r\nCisco NX-OS Software\r\r\nCopyright (c) 2002-2025, Cisco Systems, Inc." + self.p()
            else:
                self.mode = "login"
                self.out += "\r\r\nLogin incorrect\r\r\n" + f"{self.host} login: "
            return
        # exec
        if line == "terminal length 0":
            self.length0 = True
        if line.startswith("show bgp l2vpn evpn"):
            body = "".join(f"*>l[2]:[0]:[0]:[48]:[0050.0000.{i:04x}]:[0]:[0.0.0.0]/216\r\r\n" for i in range(60))
            if self.slow:
                t = time.monotonic()
                with self.lock:
                    for k in range(6):
                        self.pending.append((t + 0.5 * (k + 1), body[k * len(body) // 6:(k + 1) * len(body) // 6]))
                    self.pending.append((t + 3.5, self.p()))
                self.out += line + "\r\r\n"
                return
            if self.paging and not self.length0:
                self.more = body.split("\r\r\n")
                self.mode = "more"
                self.out += line + "\r\r\n"
                self._more()
                return
            self.out += line + "\r\r\n" + body + self.p()
            return
        self.out += line + "\r\r\n" + (f"{ESC}[1m" if line.startswith("show") else "") + (
            "14:02:01.123 UTC Tue Oct 20 2026\r\r\n" if line == "show clock" else "") + self.p()

    def _more(self):
        chunk, self.more = self.more[:20], self.more[20:]
        self.out += "\r\r\n".join(chunk) + "\r\r\n"
        if self.more:
            self.out += f"{ESC}[7m--More--{ESC}[m"
        else:
            self.mode = "exec"
            self.out += self.p()


class FakeSSH:
    def __init__(self, chan):
        self.chan = chan

    def invoke_shell(self, **kw):
        return self.chan

    def close(self):
        pass


def runner(chan, **kw):
    s = config.Settings(cml_url="https://cml.x", username="u", password="p")
    for k, v in kw.pop("settings", {}).items():
        setattr(s, k, v)
    return SSHConsoleRunner(s, "CML-18-evpn-vxlan", client_factory=lambda: FakeSSH(chan),
                            node_os={"LEAF1": "nxos", "R1": "ios"}, ready_timeout={"LEAF1": 20, "R1": 20}, **kw)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(console, "POKE_WAIT", 0.3)


def test_nxos_login_prompt_quirks_and_command():
    ch = FakeNX()
    r = runner(ch)
    out = r.run("LEAF1", "show clock")
    assert out.strip() == "14:02:01.123 UTC Tue Oct 20 2026"       # no escapes, no \r, no prompt
    assert ch.sent[0] == "open /CML-18-evpn-vxlan/LEAF1/0"
    assert "cisco" in ch.sent and "terminal length 0" in ch.sent and "terminal width 511" in ch.sent
    assert "terminal width 0" not in ch.sent                        # NX-OS rejects width 0
    assert r._sessions["LEAF1"].hostname == "LEAF1"


def test_nxos_falls_back_to_admin_with_the_device_password():
    ch = FakeNX(users=(("admin", "cisco"),))
    r = runner(ch)
    assert "UTC" in r.run("LEAF1", "show clock")
    assert ch.sent.count("cisco") >= 2 and "admin" in ch.sent      # tried cisco, refused, then admin


def test_nxos_credentials_from_settings_win():
    ch = FakeNX(users=(("netops", "Ev3n!"),))
    r = runner(ch, settings={"nxos_username": "netops", "nxos_password": "Ev3n!"})
    assert "UTC" in r.run("LEAF1", "show clock")
    assert ch.sent[2:4] == ["netops", "Ev3n!"] or ("netops" in ch.sent and ch.sent.index("netops") < (ch.sent + ["cisco"]).index("cisco"))


def test_nxos_auth_failure_is_reported_with_the_console_tail():
    ch = FakeNX(users=(("someone", "else"),))
    r = runner(ch)
    with pytest.raises(ConsoleError) as e:
        r.run("LEAF1", "show clock")
    assert e.value.kind == "auth" and "login failed" in str(e.value)
    assert "Last console output:" in str(e.value) and "Login incorrect" in e.value.tail
    with pytest.raises(ConsoleError):                                # cached: no second long wait per check
        r.run("LEAF1", "show version")


def test_nxos_first_boot_poap_and_admin_setup_dialog():
    ch = FakeNX(poap=True, users=())
    r = runner(ch)
    assert "UTC" in r.run("LEAF1", "show clock")
    assert ch.users["admin"] == "cisco" and "yes" in ch.sent and ch.sent.count("no") >= 2
    assert r._sessions["LEAF1"].hostname == "switch"


def test_paging_more_is_handled():
    ch = FakeNX(paging=True)
    s = runner(ch)._session("LEAF1")
    ch.length0 = False                     # as if `terminal length 0` had not taken effect
    out = s.run("show bgp l2vpn evpn")
    lines = [l for l in out.splitlines() if l.startswith("*>l")]
    assert len(lines) == 60 and "--More--" not in out


def test_slow_large_output_waits_while_data_keeps_coming():
    ch = FakeNX(slow=True)
    s = runner(ch)._session("LEAF1")
    t = time.monotonic()
    out = s._exec("show bgp l2vpn evpn", timeout=1.5)     # 1.5 s idle limit, the output takes 3.5 s in total
    assert len([l for l in out.splitlines() if l.startswith("*>l")]) == 60 and time.monotonic() - t >= 3


def test_node_not_running_is_a_clear_error():
    r = runner(FakeNX(not_running=True))
    with pytest.raises(ConsoleError) as e:
        r.run("LEAF1", "show clock")
    assert e.value.kind == "not_running" and "Node not found or not running" in str(e.value)


def test_unrecognised_prompt_fails_fast_with_the_tail():
    ch = FakeNX(weird_prompt=True, users=(("cisco", "cisco"),))
    r = runner(ch)
    t = time.monotonic()
    with pytest.raises(ConsoleError) as e:
        r.run("LEAF1", "show clock")
    assert e.value.kind == "prompt" and "bash-4.4$" in str(e.value) and time.monotonic() - t < 15


def test_no_banner_after_open_still_works():
    assert "UTC" in runner(FakeNX(banner=False)).run("LEAF1", "show clock")


def test_diagnose_reports_every_stage():
    s = config.Settings(cml_url="https://cml.x", username="u", password="p")
    ch = FakeNX()
    d = diagnose(s, "CML-18-evpn-vxlan", "LEAF1", "nxos", client_factory=lambda: FakeSSH(ch), ready_timeout=20)
    assert d["ok"], d
    names = [x["name"] for x in d["stages"]]
    assert names[0].startswith("SSH") and any(n.startswith("open /CML-18-evpn-vxlan/LEAF1/0") for n in names)
    login = next(x for x in d["stages"] if x["name"].startswith("log in"))
    assert "LEAF1#" in login["detail"] and "login prompt" in login["detail"]
    assert "UTC" in d["stages"][-1]["detail"] and "LEAF1" in d["tail"]
    bad = diagnose(s, "CML-18-evpn-vxlan", "LEAF1", "nxos", client_factory=lambda: FakeSSH(FakeNX(not_running=True)))
    assert not bad["ok"] and bad["stages"][-1]["ok"] is False and "not running" in bad["stages"][-1]["detail"]


def test_ansi_osc_and_backspaces_are_stripped():
    c = console._Chan(None)
    c._feed(f"{ESC}[?2004h{ESC}]0;LEAF1\x07LEAF1#\r\r\n--More--\x08\x08\x08\x08\x08\x08\x08\x08abc{ESC}(B".encode())
    assert c.buf == "LEAF1#\nabc"


# ---------------------------------------------------------------- SSH host key (trust on first use)
def test_host_key_trust_on_first_use_store_show_forget(tmp_path, monkeypatch):
    import paramiko
    monkeypatch.setenv("CMLLAB_DATA_DIR", str(tmp_path))
    key = paramiko.RSAKey.generate(1024)

    class Cli:
        def __init__(self):
            self.hk = paramiko.HostKeys()

        def get_host_keys(self):
            return self.hk
    pol = console._tofu_policy()
    pol.missing_host_key(Cli(), "192.168.11.96", key)
    st = console.stored_host_key("192.168.11.96", 22)
    assert st and st["sha256"].startswith("SHA256:") and st["type"] == "ssh-rsa" and len(st["md5"].split(":")) == 16
    assert (tmp_path / "known_hosts").is_file()
    pol.missing_host_key(Cli(), "[cml.x]:2222", key)
    assert console.stored_host_key("cml.x", 2222) and console.stored_host_key("cml.x", 22) is None
    assert console.forget_host_key("192.168.11.96", 22) and console.stored_host_key("192.168.11.96", 22) is None
    assert console.stored_host_key("cml.x", 2222)                  # others kept


def test_changed_host_key_is_a_clear_error_and_no_warning(tmp_path, monkeypatch):
    import warnings

    import paramiko
    monkeypatch.setenv("CMLLAB_DATA_DIR", str(tmp_path))
    old, new = paramiko.RSAKey.generate(1024), paramiko.RSAKey.generate(1024)

    def connect(self, host, **kw):
        if host in self.get_host_keys():
            raise paramiko.BadHostKeyException(host, new, old)
        self._policy.missing_host_key(self, host, new)
    monkeypatch.setattr(paramiko.SSHClient, "connect", connect)
    s = config.Settings(cml_url="https://192.168.11.96", username="u", password="p")
    r = SSHConsoleRunner(s, "CML-x")
    with warnings.catch_warnings():
        warnings.simplefilter("error")                               # a UserWarning would fail the test
        r._new_client()                                              # first use: stored, no warning
    assert console.stored_host_key("192.168.11.96", 22)
    with pytest.raises(ConsoleError) as e:
        r._new_client()
    assert e.value.kind == "hostkey" and "CHANGED" in str(e.value) and "Forget host key" in str(e.value)


def test_api_console_test_and_hostkey(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from cmllab.web.app import create_app
    monkeypatch.setenv("CMLLAB_DATA_DIR", str(tmp_path))
    store = config.SettingsStore(config.Settings(cml_url="https://cml.x", username="u", password="p"))

    class Lab:
        title = "CML-18-evpn-vxlan"

    class Cml:
        def find(self, lab, title=None):
            return Lab()
    from cmllab import service
    monkeypatch.setattr(service, "make_cml", lambda s, cf=None: Cml())
    ch = FakeNX()
    app = create_app(store=store, persist=False, console_factory=lambda: FakeSSH(ch))
    c = TestClient(app)
    d = c.get("/api/labs/18-evpn-vxlan").json()
    nodes = {n["name"]: n["os"] for n in d["node_list"]}
    assert nodes["LEAF1"] == "nxos"
    r = c.post("/api/labs/18-evpn-vxlan/console-test", params={"node": "LEAF1"}).json()
    assert r["ok"] and r["os"] == "nxos", r
    assert c.post("/api/labs/18-evpn-vxlan/console-test", params={"node": "NOPE"}).status_code == 404
    h = c.get("/api/console/hostkey").json()
    assert h["host"] == "cml.x" and h["key"] is None
    assert c.post("/api/console/hostkey/forget").json() == {"forgotten": False}
