"""Thin adapter over virl2_client 2.9.x. The only module that talks to the CML API."""
from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from typing import Callable

from .platforms import get as get_platform, node_def
from .render import full_config, lab_title, to_yaml
from .schema import Lab

log = logging.getLogger(__name__)

UNCOUNTED = {"unmanaged_switch", "external_connector"}
ACTIVE = {"STARTED", "QUEUED", "BOOTED"}


class CMLError(RuntimeError):
    pass


@dataclass
class LabStatus:
    exists: bool
    lab_id: str | None = None
    state: str | None = None
    nodes: dict | None = None
    converged: bool | None = None


def _default_factory(settings):
    from virl2_client import ClientLibrary
    return ClientLibrary(settings.cml_url, settings.username, settings.password,
                         ssl_verify=settings.verify_tls, raise_for_auth_failure=True)


class CML:
    def __init__(self, settings, client_factory: Callable | None = None, sleep=time.sleep):
        if not settings.is_configured():
            raise CMLError("CML URL, username and password are required (Settings page or CML_* env vars)")
        self.s = settings
        self._sleep = sleep
        try:
            self.client = (client_factory or _default_factory)(settings)
        except Exception as e:
            raise CMLError(f"cannot connect/authenticate to {settings.cml_url}: {type(e).__name__}: {e}") from e

    # ---- discovery -------------------------------------------------------
    def doctor(self) -> dict:
        info = self.client.system_info()
        version = str(info.get("version", "unknown"))
        defs = {d.get("id") for d in self.client.definitions.node_definitions()}
        plat = get_platform(self.s.platform)
        need = {plat.router, plat.switch}
        console = probe_console(self.s.effective_console_host, self.s.console_port)
        return {
            "controller_version": version,
            "console_server": f"{self.s.effective_console_host}:{self.s.console_port}",
            "console_reachable": console["ok"],
            "console_detail": console["detail"],
            "version_ok": version.startswith("2.9"),
            "platform": plat.name,
            "required_node_definitions": sorted(need),
            "missing_node_definitions": sorted(need - defs),
            "running_counted_nodes": self.running_counted_nodes(),
            "node_limit": self.s.node_limit,
        }

    def running_counted_nodes(self, exclude_lab_id: str | None = None) -> int:
        count = 0
        for lab in self.client.all_labs(show_all=False):
            if exclude_lab_id and lab.id == exclude_lab_id:
                continue
            for n in lab.nodes():
                if n.node_definition not in UNCOUNTED and n.state in ACTIVE:
                    count += 1
        return count

    def title_for(self, lab: Lab, test: bool = False) -> str:
        return f"{self.s.lab_prefix}TEST-{lab.id}" if test else lab_title(lab, self.s.lab_prefix)

    def find(self, lab: Lab, title: str | None = None):
        t = title or lab_title(lab, self.s.lab_prefix)
        found = self.client.find_labs_by_title(t)
        if len(found) > 1:
            raise CMLError(f"{len(found)} labs titled {t!r} exist; destroy duplicates in CML first")
        return found[0] if found else None

    def list_labs(self) -> list[dict]:
        out = []
        for lab in self.client.all_labs(show_all=False):
            try:
                n = len(lab.nodes())
            except Exception:
                n = None
            out.append({"id": lab.id, "title": lab.title, "state": lab.state(), "nodes": n})
        return out

    def download(self, lab_id: str) -> tuple[str, str]:
        for lab in self.client.all_labs(show_all=False):
            if lab.id == lab_id:
                return lab.download(), lab.title
        raise CMLError(f"no CML lab with id {lab_id}")

    def status(self, lab: Lab) -> LabStatus:
        cl = self.find(lab)
        if cl is None:
            return LabStatus(False)
        return LabStatus(True, cl.id, cl.state(), {n.label: n.state for n in cl.nodes()}, cl.has_converged())

    # ---- lifecycle -------------------------------------------------------
    def check_capacity(self, lab: Lab, existing=None) -> None:
        running = self.running_counted_nodes(exclude_lab_id=existing.id if existing else None)
        if running + lab.node_count > self.s.node_limit:
            raise CMLError(
                f"starting {lab.node_count} nodes would exceed the node limit "
                f"({running} already running, limit {self.s.node_limit}); stop another lab first")

    def creds(self) -> tuple[str, str]:
        """The NX-OS day-0 login (admin and this user get the password); Settings > NX-OS login, else the device login."""
        return (getattr(self.s, "nxos_username", "") or self.s.device_username or "cisco",
                getattr(self.s, "nxos_password", "") or self.s.device_password or "cisco")

    def boot_timeout(self, lab: Lab) -> int:
        need = [d.boot_s for n in lab.nodes if (d := node_def(n.definition))]
        return max([self.s.boot_timeout, *need])

    def check_definitions(self, lab: Lab) -> None:
        """Fail early with a clear message when the lab needs a node definition this CML server lacks."""
        wanted = sorted({n.definition for n in lab.nodes if n.definition})
        if not wanted:
            return
        try:
            have = {d.get("id") for d in self.client.definitions.node_definitions()}
        except Exception:
            return  # older client/server: let the import report it
        missing = [w for w in wanted if w not in have]
        if missing:
            raise CMLError(f"this lab needs the CML node definition(s) {', '.join(missing)}, which this server "
                           "does not have; install the image from the CML reference platform ISO first")

    def build(self, lab: Lab, start: bool = True, rebuild: bool = False,
              progress: Callable[[str], None] = lambda m: None, solution: dict | None = None,
              title: str | None = None):
        plat = get_platform(self.s.platform)
        title = title or lab_title(lab, self.s.lab_prefix)
        existing = self.find(lab, title)
        if existing is not None and rebuild:
            progress("Removing existing lab (rebuild requested)")
            self._destroy(existing)
            existing = None
        if existing is None:
            self.check_definitions(lab)
            progress(f"Importing topology ({plat.name} profile)")
            cl = self.client.import_lab(to_yaml(lab, plat, self.s.lab_prefix, solution=solution, title=title,
                                                creds=self.creds()), title=title)
        else:
            progress("Lab already exists in CML; reusing it (use rebuild to recreate)")
            cl = existing
        if start:
            self.check_capacity(lab, cl)
            progress("Starting nodes")
            cl.start(wait=False)
            self.wait_booted(cl, progress, self.boot_timeout(lab))
        return cl

    def wait_booted(self, cl, progress: Callable[[str], None] = lambda m: None, timeout: int | None = None) -> None:
        timeout = timeout or self.s.boot_timeout
        deadline = time.monotonic() + timeout
        while True:
            if cl.has_converged():
                states = {n.label: n.state for n in cl.nodes()}
                if all(s == "BOOTED" for s in states.values()):
                    progress("All nodes booted")
                    return
            else:
                states = {n.label: n.state for n in cl.nodes()}
            progress("Waiting for boot: " + ", ".join(f"{k}={v}" for k, v in sorted(states.items())))
            if time.monotonic() > deadline:
                raise CMLError(f"nodes did not boot within {timeout}s: {states}")
            self._sleep(10)

    def reset(self, lab: Lab, progress: Callable[[str], None] = lambda m: None, extra: dict | None = None,
              label: str = "initial", configs: dict | None = None):
        """Stop + wipe (restores day-0 configs on next boot) + start.
        extra: device -> config added to the starting config (fault practice).
        configs: device -> complete config used verbatim (snapshot restore); other devices get their starting config."""
        cl = self.find(lab)
        if cl is None:
            raise CMLError("lab is not built")
        progress("Stopping nodes")
        cl.stop(wait=True)
        progress("Wiping nodes")
        cl.wipe(wait=True)
        # Config extraction (config grading mode) overwrites the stored day-0 config,
        # so always re-apply the lab's original configs before booting again.
        plat = get_platform(self.s.platform)
        progress(f"Restoring {label} configs")
        names = {n.name for n in lab.nodes}
        for n in cl.nodes():
            if n.label in names:
                n.configuration = configs[n.label] if configs and configs.get(n.label) else full_config(lab, n.label, plat, extra, self.creds())
        self.check_capacity(lab, cl)
        progress("Starting nodes")
        cl.start(wait=False)
        self.wait_booted(cl, progress, self.boot_timeout(lab))
        return cl

    def destroy(self, lab: Lab, progress: Callable[[str], None] = lambda m: None, title: str | None = None) -> bool:
        cl = self.find(lab, title)
        if cl is None:
            progress("Nothing to destroy")
            return False
        progress("Stopping, wiping and removing lab")
        self._destroy(cl)
        return True

    def _destroy(self, cl) -> None:
        if not cl.title.startswith(self.s.lab_prefix):
            raise CMLError(f"refusing to delete lab {cl.title!r}: not created by encorlab")
        cl.stop(wait=True)
        cl.wipe(wait=True)
        cl.remove()

    def config_source(self, lab: Lab, title: str | None = None) -> "CMLConfigSource":
        cl = self.find(lab, title)
        if cl is None:
            raise CMLError("lab is not built")
        return CMLConfigSource(cl)

    def runner(self, lab: Lab, title: str | None = None):
        from .console import PyatsRunner, SSHConsoleRunner
        cl = self.find(lab, title)
        if cl is None:
            raise CMLError("lab is not built")
        if self.s.console_backend == "pyats":
            return PyatsRunner(self.s, cl)
        return SSHConsoleRunner(self.s, cl.title, node_os=node_os(lab), ready_timeout=node_ready_timeout(lab))


def node_os(lab: Lab) -> dict:
    """node name -> "nxos" / "ios" (how the console session logs in and sets up the terminal)."""
    from .platforms import node_def
    return {n.name: (node_def(n.definition).os if node_def(n.definition) else "ios") for n in lab.nodes}


def node_ready_timeout(lab: Lab) -> dict:
    """How long a node's console may take to come up (its boot time, at least 5 minutes)."""
    from .platforms import node_def
    return {n.name: max(300, node_def(n.definition).boot_s if node_def(n.definition) else 300) for n in lab.nodes}


class CMLConfigSource:
    """Config grading over HTTPS only: Node.extract_configuration() (PUT
    /labs/{lab}/nodes/{node}/extract_configuration) makes CML read the running
    config from the booted node; Node.configuration then returns it.
    Extraction only works while the node is running (BOOTED)."""

    def __init__(self, cml_lab):
        self.cl = cml_lab

    def get_config(self, device: str) -> str:
        node = self.cl.get_node_by_label(device)
        if node.state != "BOOTED":
            raise CMLError(f"{device} is {node.state}; config extraction needs a running (BOOTED) node")
        node.extract_configuration()
        self.cl.sync(exclude_configurations=False)
        cfg = node.configuration
        if not cfg:
            raise CMLError(f"CML returned no configuration for {device}")
        return cfg


def probe_console(host: str, port: int, timeout: float = 5.0) -> dict:
    """TCP reachability of the console server; a real SSH server answers with 'SSH-'."""
    if not host:
        return {"ok": False, "detail": "no console host configured"}
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                banner = sock.recv(64).decode("ascii", "replace").strip()
            except socket.timeout:
                banner = ""
    except OSError as e:
        return {"ok": False, "detail": f"TCP connect to {host}:{port} failed: {e}"}
    if banner.startswith("SSH-"):
        return {"ok": True, "detail": f"SSH banner: {banner}"}
    return {"ok": False, "detail": f"TCP open but no SSH banner (got {banner!r}); the proxy must be TCP passthrough, not HTTP"}
