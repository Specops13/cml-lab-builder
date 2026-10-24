"""NX-OS: a long silent boot phase must not be mistaken for an unknown prompt; loader> gets a clear error;
Test console uses the NX-OS login from Settings."""
import pytest

from cmllab import console
from cmllab.console import ConsoleError, DeviceSession, _Chan


class Script:
    """Prints `boot` once, stays silent for `quiet` pokes, then shows final text."""
    def __init__(self, boot, quiet, final):
        self.out, self.quiet, self.final, self.pokes, self.closed = boot, quiet, final, 0, False

    def recv_ready(self):
        return bool(self.out)

    def recv(self, n):
        d, self.out = self.out[:n], self.out[n:]
        return d.encode()

    def send(self, data):
        if data == "\r":
            self.pokes += 1
            if self.pokes == self.quiet:
                self.out += self.final
        elif data.startswith("terminal"):
            self.out += "\r\nSS1# "


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(console, "POKE_WAIT", 0.02)


def test_nxos_quiet_boot_is_waited_out():
    ch = Script("System is coming up ... Please wait...\r\n", 15, "\r\nSS1# ")
    s = DeviceSession(_Chan(ch), "", "cisco", "cisco", os="nxos", name="SS1")
    s.login(ready_timeout=60)
    assert s.hostname == "SS1"


def test_ios_still_gives_up_after_about_a_minute_of_the_same_line():
    ch = Script("Some unknown thing\r\n", 999, "")
    s = DeviceSession(_Chan(ch), "", "cisco", "cisco", os="ios", name="R1")
    with pytest.raises(ConsoleError) as e:
        s.login(ready_timeout=60)
    assert e.value.kind == "prompt"


def test_loader_prompt_is_explained():
    ch = Script("\r\nloader > ", 999, "")
    s = DeviceSession(_Chan(ch), "", "cisco", "cisco", os="nxos", name="SS1")
    with pytest.raises(ConsoleError) as e:
        s.login(ready_timeout=60)
    assert "loader" in str(e.value) and "Wipe" in str(e.value)


def test_login_creds_include_nxos_login():
    class S:
        device_username, device_password = "cisco", "cisco"
        nxos_username, nxos_password = "dylan", "Secret1"
    c = console.login_creds(S(), "nxos")
    assert c[0] == ("dylan", "Secret1") and ("admin", "Secret1") in c
    assert console.login_creds(S(), "ios") == [("cisco", "cisco")]
