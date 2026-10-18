"""Device access through the CML console server (SSH to the controller, TCP/22,
same credentials as the web UI, then `open /<lab title>/<node label>/0`).
Only the controller must be reachable; devices need no management IPs.

Backends:
  ssh   - paramiko, pure Python, works on Windows/macOS/Linux (default)
  pyats - virl2_client's ClPyats (pyATS/Unicon). Linux/macOS only.
"""
from __future__ import annotations

import logging
import re
import socket
import time

log = logging.getLogger(__name__)

PROMPT_RE = re.compile(r"(?:^|[\r\n])([A-Za-z0-9._-]+)(\(config[^)]*\))?([>#]) ?$")
CONSOLES_RE = re.compile(r"consoles>\s*$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class ConsoleError(RuntimeError):
    pass


class _Chan:
    """Minimal expect-style wrapper around a paramiko channel (or a fake in tests)."""

    def __init__(self, chan, timeout: float = 30.0):
        self.chan = chan
        self.timeout = timeout
        self.buf = ""

    def send(self, text: str) -> None:
        self.chan.send(text)

    def read_until(self, patterns: list[re.Pattern], timeout: float | None = None) -> tuple[int, str]:
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            for i, p in enumerate(patterns):
                m = p.search(self.buf)
                if m:
                    out = self.buf[: m.end()]
                    self.buf = self.buf[m.end():]
                    return i, out
            if time.monotonic() > deadline:
                raise ConsoleError(f"timeout waiting for {[p.pattern for p in patterns]}; last output: {self.buf[-300:]!r}")
            if self.chan.recv_ready():
                data = self.chan.recv(65535)
                if not data:
                    raise ConsoleError("console connection closed")
                self.buf += ANSI_RE.sub("", data.decode("utf-8", "replace")).replace("\r\n", "\n")
            else:
                if getattr(self.chan, "closed", False):
                    raise ConsoleError("console connection closed")
                time.sleep(0.05)


class DeviceSession:
    """One logged-in IOS console session, at the privileged-exec prompt."""

    def __init__(self, chan: _Chan, enable_secret: str, username: str, password: str):
        self.c = chan
        self.enable_secret = enable_secret
        self.username = username
        self.password = password
        self.hostname = ""

    def login(self, attempts: int = 12) -> None:
        pats = [
            re.compile(r"\[yes/no\]:\s*$"),
            re.compile(r"[Uu]sername:\s*$"),
            re.compile(r"[Pp]assword:\s*$"),
            PROMPT_RE,
        ]
        for _ in range(attempts):
            self.c.send("\r")
            try:
                i, out = self.c.read_until(pats, timeout=10)
            except ConsoleError:
                continue  # device may still be booting / printing
            if i == 0:
                self.c.send("no\r")
            elif i == 1:
                self.c.send(self.username + "\r")
            elif i == 2:
                self.c.send(self.password + "\r")
            else:
                m = PROMPT_RE.search(out)
                host, cfg, mark = m.group(1), m.group(2), m.group(3)
                if cfg:
                    self.c.send("end\r")
                    continue
                if mark == ">":
                    self.c.send("enable\r")
                    j, _ = self.c.read_until([re.compile(r"[Pp]assword:\s*$"), re.compile(r"#\s*$")], timeout=10)
                    if j == 0:
                        self.c.send(self.enable_secret + "\r")
                    continue
                self.hostname = host
                self.c.buf = ""
                self._exec("terminal length 0")
                self._exec("terminal width 0")
                return
        raise ConsoleError("could not reach a privileged prompt on the device console")

    def _prompt(self) -> re.Pattern:
        return re.compile(r"(?:^|\n)" + re.escape(self.hostname) + r"(\([^)]*\))?#\s*$")

    def _exec(self, command: str, timeout: float = 60) -> str:
        self.c.send(command + "\r")
        _, out = self.c.read_until([self._prompt()], timeout=timeout)
        lines = out.split("\n")
        if lines and command.strip() in lines[0]:
            lines = lines[1:]  # drop echo
        if lines:
            lines = lines[:-1]  # drop prompt
        return "\n".join(lines).strip("\n") + "\n"

    def run(self, command: str) -> str:
        return self._exec(command, timeout=90 if command.startswith("ping") else 60)


class SSHConsoleRunner:
    """Runner that opens one console session per device via the CML console server."""

    def __init__(self, settings, lab_title: str, client_factory=None):
        self.s = settings
        self.lab_title = lab_title
        self._client_factory = client_factory
        self._sessions: dict[str, DeviceSession] = {}
        self._clients = []

    def _new_client(self):
        if self._client_factory:
            return self._client_factory()
        import paramiko
        cli = paramiko.SSHClient()
        cli.load_system_host_keys()
        # The console server is the user's own controller reached over a private
        # network (Tailscale); unknown host keys are accepted and logged.
        cli.set_missing_host_key_policy(paramiko.WarningPolicy())
        cli.connect(self.s.effective_console_host, port=self.s.console_port,
                    username=self.s.username, password=self.s.password,
                    look_for_keys=False, allow_agent=False, timeout=15)
        return cli

    def _session(self, device: str) -> DeviceSession:
        if device in self._sessions:
            return self._sessions[device]
        try:
            cli = self._new_client()
        except (socket.error, OSError) as e:
            raise ConsoleError(f"cannot reach console server {self.s.effective_console_host}:{self.s.console_port}: {e}")
        self._clients.append(cli)
        chan = _Chan(cli.invoke_shell(term="vt100", width=511, height=1000))
        chan.read_until([CONSOLES_RE], timeout=20)
        chan.send(f"open /{self.lab_title}/{device}/0\r")
        time.sleep(0.5)
        sess = DeviceSession(chan, self.s.device_enable, self.s.device_username, self.s.device_password)
        sess.login()
        self._sessions[device] = sess
        return sess

    def run(self, device: str, command: str) -> str:
        return self._session(device).run(command)

    def close(self) -> None:
        for c in self._clients:
            try:
                c.close()
            except Exception:
                pass
        self._sessions.clear()
        self._clients.clear()


class PyatsRunner:
    """Runner using virl2_client's pyATS integration (needs `pip install encorlab[pyats]`)."""

    def __init__(self, settings, lab):
        self.lab = lab
        host = settings.effective_console_host
        if settings.console_port != 22:
            host = f"{host}:{settings.console_port}"
        lab.pyats.hostname = host
        lab.pyats.sync_testbed(settings.username, settings.password)

    def run(self, device: str, command: str) -> str:
        return self.lab.pyats.run_command(device, command)

    def close(self) -> None:
        try:
            self.lab.pyats.cleanup_pyats_connections()
        except Exception:
            pass
