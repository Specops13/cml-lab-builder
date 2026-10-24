"""In-memory stand-in for virl2_client.ClientLibrary (only the API surface we use)."""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import yaml

_ids = itertools.count(1)


class FakeNode:
    def __init__(self, label, node_definition, configuration=""):
        self.label = label
        self.node_definition = node_definition
        self.state = "DEFINED_ON_CORE"
        self.configuration = configuration
        self.running_config = None   # what the "device" currently runs (set by tests)
        self.extract_calls = 0
        self.ram = None              # MiB, None = the node definition's default (like CML)

    def extract_configuration(self):
        self.extract_calls += 1
        if self.running_config is not None:
            self.configuration = self.running_config


class FakeLab:
    def __init__(self, title, topology, boot_polls=1):
        self.id = f"lab-{next(_ids)}"
        self.title = title
        self.topology = topology
        self._nodes = [FakeNode(n["label"], n["node_definition"], n.get("configuration", "")) for n in topology["nodes"]]
        self._boot_polls = boot_polls
        self._polls = 0
        self.calls = []
        self.removed = False

    def nodes(self):
        return list(self._nodes)

    def get_node_by_label(self, label):
        for n in self._nodes:
            if n.label == label:
                return n
        raise KeyError(label)

    def sync(self, topology_only=True, with_node_configurations=None, exclude_configurations=False):
        self.calls.append("sync")

    def state(self):
        return "STARTED" if any(n.state != "DEFINED_ON_CORE" for n in self._nodes) else "DEFINED_ON_CORE"

    def start(self, wait=None):
        self.calls.append("start")
        for n in self._nodes:
            n.state = "STARTED"

    def has_converged(self):
        self._polls += 1
        if self._polls >= self._boot_polls:
            for n in self._nodes:
                if n.state == "STARTED":
                    n.state = "BOOTED"
            return True
        return False

    def stop(self, wait=None):
        self.calls.append("stop")
        for n in self._nodes:
            n.state = "STOPPED"

    def wipe(self, wait=None):
        self.calls.append("wipe")
        for n in self._nodes:
            n.state = "DEFINED_ON_CORE"
        self._polls = 0

    def download(self):
        return yaml.safe_dump(self.topology, sort_keys=False)

    def remove(self):
        self.calls.append("remove")
        self.removed = True


class FakeDefinitions:
    def __init__(self, ids):
        self.ids = ids

    def node_definitions(self):
        return [{"id": i} for i in self.ids]


class FakeLicensing:
    def __init__(self, status=None, error=None):
        self._status, self.error = status, error

    def status(self):
        if self.error:
            raise self.error
        return self._status or {"features": []}


GIB = 1024 ** 3


class FakeClient:
    def __init__(self, version="2.9.1+build.7", defs=("iol-xe", "ioll2-xe", "iosv", "iosvl2"), boot_polls=1,
                 total_gb=64, free_gb=48):
        self.stats = {"all": {"memory": {"total": total_gb * GIB, "free": free_gb * GIB, "used": (total_gb - free_gb) * GIB},
                              "cpu": {"count": 16}}, "computes": {}}
        self.stats_error = None
        self.licensing = FakeLicensing()
        self.labs = []
        self.version = version
        self.definitions = FakeDefinitions(list(defs))
        self.boot_polls = boot_polls
        self.imported_yaml = []

    def system_info(self):
        return {"version": self.version, "ready": True}

    def get_system_stats(self):
        if self.stats_error:
            raise self.stats_error
        return self.stats

    def all_labs(self, show_all=False):
        return [l for l in self.labs if not l.removed]

    def find_labs_by_title(self, title):
        return [l for l in self.all_labs() if l.title == title]

    def import_lab(self, topology, title=None):
        self.imported_yaml.append(topology)
        topo = yaml.safe_load(topology)
        lab = FakeLab(title or topo["lab"]["title"], topo, self.boot_polls)
        self.labs.append(lab)
        return lab

    def add_foreign_running_lab(self, n, title="someone-else"):
        topo = {"nodes": [{"label": f"X{i}", "node_definition": "iol-xe"} for i in range(n)]}
        lab = FakeLab(title, topo)
        lab.start()
        self.labs.append(lab)
        return lab


# ---------------------------------------------------------------- update signing (a throwaway test key; conftest trusts it)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import fake_release as _fr  # noqa: E402

TEST_SEED, TEST_PUB_HEX = _fr.test_key()


def sign(data: bytes) -> bytes:
    """Detached signature file content (signing.py format) made with the test key."""
    return _fr.sign(TEST_SEED, data)
