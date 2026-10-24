"""Device access through the CML console server (SSH to the controller, TCP/22,
same credentials as the web UI, then `open /<lab title>/<node label>/0`).
Only the controller must be reachable; devices need no management IPs.

Backends:
  ssh   - paramiko, pure Python, works on Windows/macOS/Linux (default)
  pyats - virl2_client's ClPyats (pyATS/Unicon). Linux/macOS only.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import socket
import time
import warnings
from pathlib import Path

# paramiko's own "Unknown ssh-rsa host key" UserWarning (WarningPolicy) is never used any more; keep stray
# paramiko warnings out of the console window
warnings.filterwarnings("ignore", category=UserWarning, module=r"paramiko(\..*)?")

log = logging.getLogger(__name__)

PROMPT_RE = re.compile(r"(?:^|[\r\n])(?!consoles>)([A-Za-z0-9._-]+)(\(config[^)]*\))?([>#]) ?$")
CONSOLES_RE = re.compile(r"consoles>\s*$")
# CSI (colours, cursor, bracketed paste ?2004h), OSC (window title, ends with BEL or ESC \), charset and keypad modes
ANSI_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-9A-Za-z]|[=>78DEHMc])|[\x00\x07]")
# Errors IOS and NX-OS print in configuration mode
CONFIG_ERROR_RE = re.compile(r"^\s*(% ?(Invalid|Incomplete|Ambiguous|Unknown|Unrecognized|Bad mask|Cannot)|ERROR:|Error:)",
                             re.M)


# NX-OS commands that enter a sub-mode even when nothing is configured under them (e.g. a bare
# `address-family l2vpn evpn` under `router bgp`, followed by a `neighbor` at the same level)
NXOS_MODE_RE = re.compile(r"^(router \S+|interface \S+|vlan \d[\d,-]*|vrf context \S+|vrf \S+|address-family .+|"
                          r"neighbor \S+( remote-as \S+)?|evpn|vni \d+ l2|route-map .+|line \S+|member vni \d+.*|template .+)$")


def config_script(text: str, os: str = "ios") -> list[str]:
    """Turn an indented config block (IOS / NX-OS style) into the exact lines to type in configuration mode.

    Comments and blanks are dropped. Within a block, an `exit` is sent whenever the indentation steps back out of a
    sub-mode (on NX-OS also after a known mode command with nothing under it). Every new top-level block starts
    from a clean global configuration mode (`end`, `configure terminal`), so a mode the device entered silently
    can never swallow the next block."""
    rows = [(len(l) - len(l.lstrip(" ")), l.strip()) for l in text.replace("\t", "  ").splitlines()]
    rows = [(i, l) for i, l in rows if l and not l.startswith("!") and l.lower() not in ("end", "configure terminal", "conf t")]
    out, stack = [], []
    for k, (ind, line) in enumerate(rows):
        if ind == 0 and stack:
            out += ["end", "configure terminal"]
            stack = []
        while stack and stack[-1] >= ind:
            stack.pop()
            out.append("exit")
        out.append(line)
        deeper = k + 1 < len(rows) and rows[k + 1][0] > ind
        if deeper or (os == "nxos" and NXOS_MODE_RE.match(line)):
            stack.append(ind)
    return out


class ConsoleError(RuntimeError):
    """kind: unreachable | hostkey | auth | not_running | timeout | prompt | closed | "" (other).
    tail: the last lines of console output, shown with the error in the GUI."""

    def __init__(self, msg: str, kind: str = "", tail: str = ""):
        self.kind, self.tail, self.reason = kind, tail, msg
        super().__init__(msg + (f"\nLast console output:\n{tail}" if tail.strip() else ""))


TAIL_LINES = 20
POKE_WAIT = 10.0    # seconds between the Enter presses that wake a console while waiting for it
OPEN_WAIT = 3.0     # seconds to wait for the console server's "Connected ... Escape character" banner after `open`
MORE_RE = re.compile(r"(?:--More--|<--- More --->|-- More --)[ \t]*$")


class _Chan:
    """Minimal expect-style wrapper around a paramiko channel (or a fake in tests)."""

    def __init__(self, chan, timeout: float = 30.0):
        self.chan = chan
        self.timeout = timeout
        self.buf = ""
        self.log = ""          # recent output (for error messages)

    def send(self, text: str) -> None:
        self.chan.send(text)

    def tail(self, n: int = TAIL_LINES) -> str:
        lines = [l for l in (self.log + self.buf).split("\n")]
        return "\n".join(lines[-n:]).strip("\n")

    def _feed(self, data: bytes) -> None:
        t = ANSI_RE.sub("", data.decode("utf-8", "replace")).replace("\r\n", "\n")
        # NX-OS (and some IOS-XE) consoles put a bare \r before prompts and erase "--More--" with backspaces
        t = t.replace("\r", "")
        if "\x08" in t:
            out: list[str] = []
            for ch in t:
                if ch == "\x08":
                    if out and out[-1] != "\n":
                        out.pop()
                else:
                    out.append(ch)
            t = "".join(out)
        self.buf += t
        self.log = (self.log + t)[-8000:]

    def read_until(self, patterns: list[re.Pattern], timeout: float | None = None,
                   idle: float | None = None) -> tuple[int, str]:
        """Wait until one of the patterns matches the buffered output. timeout: hard limit (seconds). idle: instead,
        fail only after this many seconds without any new output (slow, long command output keeps it alive);
        timeout is then the overall cap."""
        start = time.monotonic()
        limit = timeout or self.timeout
        last_data = start
        while True:
            for i, p in enumerate(patterns):
                m = p.search(self.buf)
                if m:
                    out = self.buf[: m.end()]
                    self.buf = self.buf[m.end():]
                    return i, out
            now = time.monotonic()
            if (idle is not None and now - last_data > idle) or now - start > limit:
                raise ConsoleError(f"no response within {int(now - start)} s (waiting for "
                                   f"{', '.join(p.pattern for p in patterns)[:160]})", "timeout", self.tail())
            if self.chan.recv_ready():
                data = self.chan.recv(65535)
                if not data:
                    raise ConsoleError("the console connection was closed", "closed", self.tail())
                self._feed(data)
                last_data = time.monotonic()
            else:
                if getattr(self.chan, "closed", False):
                    raise ConsoleError("the console connection was closed", "closed", self.tail())
                time.sleep(0.05)


# what a device console can show before it is at a usable privileged prompt
_P = {
    "consoles": CONSOLES_RE,
    # NX-OS 9000v stopped and started WITHOUT a wipe before its first-boot EEM applet saved the boot variable
    "loader": re.compile(r"(?:^|\n)\s*loader\s*>\s*$"),
    "poap": re.compile(r"Abort (Power On )?Auto Provisioning[^\n]*(\(yes/skip/no\))?[^\n]*:\s*$", re.I),
    "secure": re.compile(r"enforce secure password standard[^\n]*:\s*$", re.I),
    "admin_pw": re.compile(r"Enter the password for [\"']?admin[\"']?\s*:\s*$", re.I),
    "confirm_pw": re.compile(r"Confirm the password for [\"']?admin[\"']?\s*:\s*$", re.I),
    "basic": re.compile(r"basic configuration dialog[^\n]*:\s*$", re.I),
    "yesno": re.compile(r"\[yes/no\]:\s*$"),
    "incorrect": re.compile(r"Login incorrect|% ?Login invalid|% ?Authentication failed|% ?Bad passwords|Access denied"),
    "login": re.compile(r"([Uu]sername|[Ll]ogin)\s*:\s*$"),
    "password": re.compile(r"[Pp]assword\s*:\s*$"),
    "prompt": PROMPT_RE,
}


class DeviceSession:
    """One logged-in console session (IOS / IOS-XE / NX-OS), at the privileged-exec prompt."""

    def __init__(self, chan: _Chan, enable_secret: str, username: str, password: str, os: str = "ios",
                 creds: list[tuple[str, str]] | None = None, status=None, name: str = "", trace: list | None = None):
        self.c = chan
        self.enable_secret = enable_secret
        self.username = username
        self.password = password
        self.os = os
        # logins to try in order (NX-OS: the lab's day-0 config creates admin and your device user)
        self.creds = list(dict.fromkeys(creds or [(username, password)]))
        self.status = status or (lambda msg: None)
        self.name = name
        self.hostname = ""
        self.trace = trace if trace is not None else []     # what the login saw (for "Test console")

    def login(self, attempts: int = 12, ready_timeout: float | None = None) -> None:
        """Reach the privileged prompt. ready_timeout: how long a booting device may take to show its console
        (NX-OS boots for 10-15 minutes); status messages are sent while waiting."""
        names = list(_P)
        pats = [_P[k] for k in names]
        start = time.monotonic()
        ready_timeout = ready_timeout if ready_timeout is not None else 10.0 * attempts
        cred, sent_user, seen_any, last_status, logins = 0, False, False, start, 0
        stable, last_line = 0, None
        while True:
            self.c.send("\r")
            while True:
                try:
                    i, out = self.c.read_until(pats, timeout=POKE_WAIT)
                except ConsoleError:
                    break                     # nothing recognisable yet (booting, printing): poke again
                k = names[i]
                seen_any = True
                if k == "loader":
                    raise ConsoleError(f"{self.name or 'the node'}: NX-OS is stuck at the loader> prompt (the switch was "
                                       "restarted without a wipe before its boot variable was saved). Wipe and start the "
                                       "node in CML (or Reset the lab), or type 'boot bootflash:<nxos image>.bin' at "
                                       "the loader prompt", "prompt", self.c.tail())
                if k == "consoles":
                    raise ConsoleError(f"{self.name or 'the node'}: the console server has no console for this node "
                                       "(is the node started and BOOTED in CML?)", "not_running", self.c.tail())
                if k in ("poap", "secure", "basic", "yesno", "admin_pw", "confirm_pw"):
                    self.trace.append(f"setup question ({k}) answered")
                if k == "poap":
                    self.status(f"{self.name}: answering the NX-OS POAP question (no day-0 config was applied)")
                    self.c.send("yes\r")
                elif k == "secure":
                    self.c.send("no\r")
                elif k in ("admin_pw", "confirm_pw"):
                    self.c.send(self.creds[0][1] + "\r")
                elif k == "basic" or k == "yesno":
                    self.c.send("no\r")
                elif k == "incorrect":
                    self.trace.append(f"login as {self.creds[cred][0]} refused")
                    logins += 1
                    cred += 1
                    if cred >= len(self.creds):
                        raise ConsoleError(f"{self.name or 'device'}: login failed with "
                                           + ", ".join(u for u, _ in self.creds)
                                           + " (check the device username/password in Settings; NX-OS labs use the "
                                             "credentials the lab was built with)", "auth", self.c.tail())
                elif k == "login":
                    self.trace.append(f"login prompt: sent username {self.creds[cred][0]}")
                    self.c.send(self.creds[cred][0] + "\r")
                    sent_user = True
                elif k == "password":
                    self.trace.append("password prompt: sent the password")
                    self.c.send(self.creds[cred][1] + "\r")
                    sent_user = False
                else:
                    m = PROMPT_RE.search(out)
                    host, cfg, mark = m.group(1), m.group(2), m.group(3)
                    if cfg:
                        self.c.send("end\r")
                        continue
                    if mark == ">":
                        self.trace.append(f"user prompt {host}>: sent enable")
                        self.c.send("enable\r")
                        try:
                            j, _ = self.c.read_until([re.compile(r"[Pp]assword:\s*$"), re.compile(r"#\s*$")], timeout=10)
                        except ConsoleError:
                            continue
                        if j == 0:
                            self.c.send(self.enable_secret + "\r")
                        continue
                    self.hostname = host
                    self.c.buf = ""
                    self._exec("terminal length 0")
                    self._exec("terminal width 511" if self.os == "nxos" else "terminal width 0")
                    return
            waited = time.monotonic() - start
            last = next((l.strip() for l in reversed(self.c.buf.split("\n")) if l.strip()), "")
            stable = stable + 1 if last and last == last_line else 0
            last_line = last
            # the same unrecognised last line for about a minute (NX-OS: 5 minutes - its boot has long silent phases,
            # e.g. after "System is coming up ... Please wait", and pressing Enter echoes nothing until login)
            if stable >= (30 if self.os == "nxos" else 6):
                raise ConsoleError(f"{self.name or 'device'}: the console answers but its prompt was not recognised: "
                                   f"{last[-120:]!r}", "prompt", self.c.tail())
            if waited > ready_timeout:
                raise ConsoleError(
                    f"{self.name or 'device'}: the console did not reach a prompt within {int(waited // 60)} min "
                    f"{int(waited % 60)} s" + (" (output was seen but no login or prompt was recognised)" if seen_any
                                                else " (no output: still booting?)"),
                    "prompt" if seen_any else "timeout", self.c.tail())
            if time.monotonic() - last_status >= 3 * POKE_WAIT:
                last_status = time.monotonic()
                self.status(f"{self.name}: waiting for the console to be ready ({int(waited // 60)} min so far"
                            + ("; NX-OS takes 10-15 min to boot" if self.os == "nxos" else "") + ")")

    def _prompt(self) -> re.Pattern:
        return re.compile(r"(?:^|\n)" + re.escape(self.hostname) + r"(\([^)]*\))?#\s*$")

    def _exec(self, command: str, timeout: float = 60) -> str:
        """Run one command; waits while output keeps coming (idle limit `timeout`, at most 15 min) and pages
        through --More-- if paging is still on."""
        self.c.send(command + "\r")
        prompt = self._prompt()
        chunks = []
        while True:
            i, out = self.c.read_until([prompt, MORE_RE], timeout=900, idle=timeout)
            if i == 1:
                chunks.append(MORE_RE.sub("", out))
                self.c.send(" ")
                continue
            chunks.append(out)
            break
        lines = "".join(chunks).split("\n")
        if lines and command.strip() in lines[0]:
            lines = lines[1:]  # drop echo
        if lines:
            lines = lines[:-1]  # drop prompt
        return "\n".join(lines).strip("\n") + "\n"

    def run(self, command: str) -> str:
        return self._exec(command, timeout=90 if command.startswith("ping") else 60)

    def configure(self, text: str, os: str = "ios") -> str:
        """Type a config block in configuration mode. Stops at the first line the device rejects
        (ConsoleError naming the line); always returns to the privileged prompt."""
        log_out = []
        self._exec("configure terminal")
        try:
            for line in config_script(text, os):
                out = self._exec(line, timeout=120)
                log_out.append(f"{line}\n{out}" if out.strip() else line)
                if CONFIG_ERROR_RE.search(out):
                    raise ConsoleError(f"{self.hostname} rejected {line!r}: {out.strip()[:300]}")
        finally:
            self._exec("end")
        return "\n".join(log_out) + "\n"


# ------------------------------------------------------------------ SSH host key of the console server (TOFU)
def known_hosts_file() -> Path:
    """The app's own known_hosts (in the data folder); the system ~/.ssh/known_hosts is also honoured."""
    from .history import data_dir
    return data_dir() / "known_hosts"


def host_entry(host: str, port: int) -> str:
    return host if int(port) == 22 else f"[{host}]:{int(port)}"


def fingerprint(key) -> dict:
    raw = key.asbytes()
    return {"type": key.get_name(), "sha256": "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("="),
            "md5": ":".join(f"{b:02x}" for b in hashlib.md5(raw, usedforsecurity=False).digest())}


def _host_keys():
    import paramiko
    hk = paramiko.HostKeys()
    f = known_hosts_file()
    if f.is_file():
        try:
            hk.load(str(f))
        except Exception as e:  # noqa: BLE001 - a corrupt file: start over rather than never connect
            log.warning("ignoring unreadable %s: %s", f, e)
            hk = paramiko.HostKeys()
    return hk


def stored_host_key(host: str, port: int) -> dict | None:
    keys = _host_keys().lookup(host_entry(host, port))
    if not keys:
        return None
    k = next(iter(keys.values()))
    return {"host": host_entry(host, port), **fingerprint(k), "file": str(known_hosts_file())}


def forget_host_key(host: str, port: int) -> bool:
    hk = _host_keys()
    e = host_entry(host, port)
    if e not in hk:
        return False
    del hk[e]
    f = known_hosts_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    hk.save(str(f))
    return True


def _tofu_policy():
    import paramiko

    class TrustOnFirstUse(paramiko.MissingHostKeyPolicy):
        """First connection: remember the key (no warning). Later: paramiko refuses a different key
        (BadHostKeyException), which becomes a clear 'host key changed' error."""

        def missing_host_key(self, client, hostname, key):
            hk = _host_keys()
            hk.add(hostname, key.get_name(), key)
            f = known_hosts_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            hk.save(str(f))
            client.get_host_keys().add(hostname, key.get_name(), key)
            log.info("trusting the console server's %s host key %s on first use (saved to %s)",
                     key.get_name(), fingerprint(key)["sha256"], f)
    return TrustOnFirstUse()


def login_creds(settings, os: str) -> list[tuple[str, str]]:
    """Logins to try in order. NX-OS: Settings > NX-OS login first (the lab's day-0 creates it and gives admin the
    same password), then the device login, then admin with the usual lab passwords."""
    creds = [(settings.device_username, settings.device_password)]
    if os == "nxos":
        nu, np_ = getattr(settings, "nxos_username", ""), getattr(settings, "nxos_password", "")
        if nu or np_:
            creds.insert(0, (nu or settings.device_username, np_ or settings.device_password))
        creds += [("admin", np_ or settings.device_password), ("admin", "cisco"), ("admin", "admin")]
    return creds


class SSHConsoleRunner:
    """Runner that opens one console session per device via the CML console server."""

    def __init__(self, settings, lab_title: str, client_factory=None, node_os: dict | None = None,
                 ready_timeout: dict | None = None, progress=None):
        self.s = settings
        self.lab_title = lab_title
        self._client_factory = client_factory
        self._sessions: dict[str, DeviceSession] = {}
        self._failed: dict[str, ConsoleError] = {}
        self._clients = []
        self.node_os = node_os or {}
        self.ready_timeout = ready_timeout or {}
        self.progress = progress

    def _status(self, msg: str) -> None:
        if self.progress:
            try:
                self.progress(msg)
            except Exception:  # noqa: BLE001
                pass

    def _new_client(self):
        if self._client_factory:
            return self._client_factory()
        import paramiko
        cli = paramiko.SSHClient()
        try:
            cli.load_system_host_keys()
        except Exception:  # noqa: BLE001 - unreadable ~/.ssh/known_hosts
            pass
        f = known_hosts_file()
        if f.is_file():
            for host, keys in _host_keys().items():
                for kt, k in keys.items():
                    cli.get_host_keys().add(host, kt, k)
        cli.set_missing_host_key_policy(_tofu_policy())
        host, port = self.s.effective_console_host, self.s.console_port
        try:
            cli.connect(host, port=port, username=self.s.username, password=self.s.password,
                        look_for_keys=False, allow_agent=False, timeout=15, banner_timeout=30, auth_timeout=30)
        except paramiko.BadHostKeyException as e:
            raise ConsoleError(
                f"the SSH host key of the console server {host_entry(host, port)} has CHANGED: stored "
                f"{fingerprint(e.expected_key)['sha256']}, the server now sends {fingerprint(e.key)['sha256']}. This is "
                "expected after reinstalling or upgrading CML; otherwise something may be intercepting the connection. "
                "If you expect it, click Settings > Forget host key and check again.", "hostkey")
        except paramiko.AuthenticationException as e:
            raise ConsoleError(f"the console server {host} refused the CML username/password from Settings ({e})", "auth")
        except (paramiko.SSHException, socket.error, OSError) as e:
            raise ConsoleError(f"cannot reach the console server {host}:{port}: {type(e).__name__}: {e}", "unreachable")
        return cli

    def _session(self, device: str) -> DeviceSession:
        if device in self._sessions:
            return self._sessions[device]
        if device in self._failed:          # do not wait for a broken console once per check
            raise self._failed[device]
        try:
            sess = self._open(device)
        except ConsoleError as e:
            self._failed[device] = e
            raise
        self._sessions[device] = sess
        return sess

    def _open(self, device: str) -> DeviceSession:
        try:
            cli = self._new_client()
        except ConsoleError:
            raise
        except (socket.error, OSError) as e:
            raise ConsoleError(f"cannot reach the console server {self.s.effective_console_host}:{self.s.console_port}: {e}",
                               "unreachable")
        self._clients.append(cli)
        chan = _Chan(cli.invoke_shell(term="vt100", width=511, height=1000))
        chan.read_until([CONSOLES_RE], timeout=20)
        chan.send(f"open /{self.lab_title}/{device}/0\r")
        try:
            j, out = chan.read_until([re.compile(r"Escape character is|Connected to"), CONSOLES_RE], timeout=OPEN_WAIT)
            if j == 1:
                msg = out.replace("consoles>", "").strip().splitlines()
                msg = " ".join(l for l in msg if not l.startswith("open /")).strip()
                raise ConsoleError(f"{device}: the console server could not open the console"
                                   + (f" ({msg})" if msg else "") + ". Is the node started and BOOTED in CML?",
                                   "not_running", chan.tail())
        except ConsoleError as e:
            if e.kind != "timeout":
                raise
        os_ = self.node_os.get(device, "ios")
        creds = login_creds(self.s, os_)
        sess = DeviceSession(chan, self.s.device_enable, self.s.device_username, self.s.device_password, os=os_,
                             creds=creds, status=self._status, name=device)
        sess.login(ready_timeout=self.ready_timeout.get(device, 1500 if os_ == "nxos" else 300))
        return sess

    def run(self, device: str, command: str) -> str:
        return self._session(device).run(command)

    def configure(self, device: str, text: str, os: str = "ios") -> str:
        return self._session(device).configure(text, os)

    def close(self) -> None:
        for c in self._clients:
            try:
                c.close()
            except Exception:
                pass
        self._sessions.clear()
        self._clients.clear()
        self._failed.clear()


class PyatsRunner:
    """Runner using virl2_client's pyATS integration (needs `pip install cml-lab-builder[pyats]`)."""

    def __init__(self, settings, lab):
        self.lab = lab
        host = settings.effective_console_host
        if settings.console_port != 22:
            host = f"{host}:{settings.console_port}"
        lab.pyats.hostname = host
        lab.pyats.sync_testbed(settings.username, settings.password)

    def run(self, device: str, command: str) -> str:
        return self.lab.pyats.run_command(device, command)

    def configure(self, device: str, text: str, os: str = "ios") -> str:
        # one configure session per top-level block (Unicon enters and leaves configuration mode itself)
        chunks, cur = [], []
        for line in config_script(text, os) + ["end"]:
            if line == "end":
                if cur:
                    chunks.append(cur)
                cur = []
            elif line != "configure terminal":
                cur.append(line)
        return "".join(self.lab.pyats.run_config_command(device, "\n".join(c)) or "" for c in chunks)

    def close(self) -> None:
        try:
            self.lab.pyats.cleanup_pyats_connections()
        except Exception:
            pass


# ------------------------------------------------------------------ "Test console" (lab page): stage by stage
def diagnose(settings, lab_title: str, device: str, os: str = "ios", client_factory=None,
             command: str = "show clock", ready_timeout: float | None = None) -> dict:
    """Open one node's console like a check does and report every stage: SSH to the console server, the console
    server menu, `open /<lab>/<node>/0`, what the console showed (login / password / POAP ...), the prompt, one
    command. Returns {ok, stages: [{name, ok, detail}], tail} with the last console lines (also on success)."""
    if ready_timeout is None:          # NX-OS keeps booting for minutes after CML reports BOOTED
        ready_timeout = 600 if os == "nxos" else 120
    stages: list[dict] = []
    add = lambda name, ok, detail="": stages.append({"name": name, "ok": bool(ok), "detail": detail})  # noqa: E731
    r = SSHConsoleRunner(settings, lab_title, client_factory, node_os={device: os}, ready_timeout={device: ready_timeout})
    chan = None
    stage = "SSH to the console server"
    host, port = settings.effective_console_host, settings.console_port
    try:
        cli = r._new_client()
        r._clients.append(cli)
        hk = stored_host_key(host, port) if client_factory is None else None
        add(stage, True, f"{settings.username}@{host}:{port}" + (f", host key {hk['sha256']}" if hk else ""))
        stage = "console server menu (consoles>)"
        chan = _Chan(cli.invoke_shell(term="vt100", width=511, height=1000))
        chan.read_until([CONSOLES_RE], timeout=20)
        add(stage, True)
        stage = f"open /{lab_title}/{device}/0"
        chan.send(f"open /{lab_title}/{device}/0\r")
        try:
            j, out = chan.read_until([re.compile(r"Escape character is|Connected to"), CONSOLES_RE], timeout=OPEN_WAIT)
        except ConsoleError:
            add(stage, True, f"no 'Connected' banner within {OPEN_WAIT:.0f} s; trying the console anyway")
        else:
            if j == 1:
                raise ConsoleError("the console server refused: " + " ".join(
                    l for l in out.replace("consoles>", "").strip().splitlines() if not l.startswith("open /")).strip(),
                    "not_running", chan.tail())
            add(stage, True, "connected")
        stage = "log in and reach the privileged prompt"
        events: list[str] = []
        creds = login_creds(settings, os)   # same logins as a check (incl. Settings > NX-OS login)
        sess = DeviceSession(chan, settings.device_enable, settings.device_username, settings.device_password,
                             os=os, creds=creds, status=events.append, name=device, trace=events)
        sess.login(ready_timeout=ready_timeout)
        add(stage, True, f"prompt {sess.hostname}#" + (f" ({'; '.join(events)})" if events else " (no login needed)"))
        stage = f"run '{command}'"
        out = sess.run(command)
        add(stage, True, out.strip()[:300])
    except ConsoleError as e:
        add(stage, False, (f"[{e.kind}] " if e.kind else "") + e.reason)
    except Exception as e:  # noqa: BLE001 - report anything else as the failing stage
        add(stage, False, f"{type(e).__name__}: {e}")
    finally:
        tail = chan.tail(TAIL_LINES) if chan else ""
        r.close()
    return {"ok": all(s["ok"] for s in stages), "stages": stages, "tail": tail, "device": device, "os": os}
