"""Console driver tests against a scripted fake of the CML console server + IOS CLI."""
import pytest

from encorlab import catalog, grader, platforms
from encorlab.config import Settings
from encorlab.console import ConsoleError, SSHConsoleRunner
from encorlab.sim import SimRunner


class FakeIOSChannel:
    """Behaves like: CML 'consoles>' menu -> open /lab/node/0 -> IOS console."""

    def __init__(self, sim, start_mode="user", hostname=None, banner_dialog=False, require_login=False):
        self.sim = sim
        self.out = "Welcome to the CML console server\r\nconsoles> "
        self.mode = "menu"
        self.start_mode = start_mode
        self.hostname = hostname
        self.dialog = banner_dialog
        self.require_login = require_login
        self.login_stage = 0
        self.inbuf = ""
        self.closed = False
        self.opened = None

    def recv_ready(self):
        return bool(self.out)

    def recv(self, n):
        d, self.out = self.out[:n], self.out[n:]
        return d.encode()

    def p(self):
        return {"user": f"{self.hostname}>", "priv": f"{self.hostname}#", "config": f"{self.hostname}(config)#"}[self.mode]

    def send(self, data):
        self.inbuf += data
        while "\r" in self.inbuf:
            line, self.inbuf = self.inbuf.split("\r", 1)
            self.handle(line)

    def handle(self, line):
        if self.mode == "menu":
            assert line.startswith("open /")
            _, lab, node, idx = line.split("/")
            self.opened = (lab, node, idx)
            self.hostname = self.hostname or node
            self.mode = "await"
            self.out += line + "\r\nConnected to CML terminalserver, line 0.\r\nEscape character is '^]'.\r\n"
            return
        if self.mode == "await":
            if self.dialog:
                self.dialog = False
                self.out += "\r\nWould you like to enter the initial configuration dialog? [yes/no]: "
                return
            if self.require_login and self.login_stage == 0:
                self.login_stage = 1
                self.out += "\r\nUsername: "
                return
            if self.require_login and self.login_stage == 1:
                self.login_stage = 2
                self.out += "\r\nPassword: "
                return
            self.mode = self.start_mode
            self.out += "\r\n" + self.p()
            return
        if line == "enable" and self.mode == "user":
            self.out += "enable\r\nPassword: "
            self.mode = "enpw"
            return
        if self.mode == "enpw":
            assert line == "cisco"
            self.mode = "priv"
            self.out += "\r\n" + self.p()
            return
        if line == "end":
            self.mode = "priv"
            self.out += "end\r\n" + self.p()
            return
        if line == "":
            self.out += "\r\n" + self.p()
            return
        if line.startswith("terminal "):
            self.out += line + "\r\n" + self.p()
            return
        body = self.sim.run(self.node, line).replace("\n", "\r\n")
        self.out += line + "\r\n" + body + self.p()

    @property
    def node(self):
        return self.opened[1]


class FakeSSH:
    def __init__(self, factory):
        self.factory = factory
        self.closed = False

    def invoke_shell(self, **kw):
        return self.factory()

    def close(self):
        self.closed = True


LAB = catalog.get("eigrp-basic")
P = platforms.get("iol")


def runner_with(**chan_kw):
    sim = SimRunner(LAB, P, solved=True)
    s = Settings(cml_url="https://cml.x", username="u", password="p")
    chans = []

    def factory():
        c = FakeIOSChannel(sim, **chan_kw)
        chans.append(c)
        return c
    r = SSHConsoleRunner(s, "ENCOR-eigrp-basic", client_factory=lambda: FakeSSH(factory))
    return r, chans


@pytest.mark.parametrize("kw", [
    {"start_mode": "user"},
    {"start_mode": "priv"},
    {"start_mode": "config"},
    {"start_mode": "priv", "banner_dialog": True},
    {"start_mode": "priv", "require_login": True},
])
def test_end_to_end_grading_over_console(kw):
    r, chans = runner_with(**kw)
    rep = grader.grade(LAB, r, P)
    assert rep.passed, [x.details for x in rep.results if not x.passed]
    assert {c.opened for c in chans} == {("ENCOR-eigrp-basic", "R1", "0"), ("ENCOR-eigrp-basic", "R2", "0")}
    assert len(chans) == 2  # one session per device, reused across checks
    r.close()


def test_output_strips_echo_and_prompt():
    r, _ = runner_with(start_mode="priv")
    out = r.run("R1", "show ip eigrp neighbors")
    assert out.startswith("EIGRP-IPv4 Neighbors") and "R1#" not in out


def test_unreachable_console_server():
    s = Settings(cml_url="https://cml.x", username="u", password="p")

    def boom():
        raise OSError("timed out")
    r = SSHConsoleRunner(s, "ENCOR-x", client_factory=boom)
    with pytest.raises(ConsoleError, match="cannot reach (the )?console server"):
        r.run("R1", "show version")


def test_console_host_default_and_override():
    s = Settings(cml_url="https://cml.example.ts.net:443/", username="u", password="p")
    assert s.effective_console_host == "cml.example.ts.net"
    s.console_host = "100.64.0.5"
    assert s.effective_console_host == "100.64.0.5"
