import yaml

from encorlab import catalog, platforms
from encorlab.render import SCHEMA_VERSION, to_topology, to_yaml

LAB = catalog.get("eigrp-basic")


def test_iol_names_and_defs():
    p = platforms.get("iol")
    assert p.ifname(0) == "Ethernet0/0" and p.ifname(3, short=True) == "Et0/3"
    assert p.node_definition("router") == "iol-xe" and p.node_definition("switch") == "ioll2-xe"
    q = platforms.get("iosv")
    assert q.ifname(1) == "GigabitEthernet0/1" and q.node_definition("switch") == "iosvl2"


def test_placeholder_render():
    assert platforms.render("int %if0% / %if2s%", platforms.get("iol")) == "int Ethernet0/0 / Et0/2"


def test_topology_shape_matches_cml_schema():
    y = to_yaml(LAB, platforms.get("iol"), "ENCOR-")
    t = yaml.safe_load(y)
    assert set(t) == {"lab", "nodes", "links"}
    assert t["lab"]["version"] == SCHEMA_VERSION == "0.2.2"
    assert t["lab"]["title"] == "ENCOR-eigrp-basic"
    n0 = t["nodes"][0]
    assert n0["id"] == "n0" and n0["label"] == "R1" and n0["node_definition"] == "iol-xe"
    assert n0["interfaces"][0] == {"id": "i0", "label": "Loopback0", "type": "loopback"}
    assert n0["interfaces"][1] == {"id": "i1", "label": "Ethernet0/0", "type": "physical", "slot": 0}
    assert "hostname R1" in n0["configuration"] and "interface Ethernet0/0" in n0["configuration"]
    assert "%if" not in y
    assert t["links"] == [{"id": "l0", "n1": "n0", "n2": "n1", "i1": "i1", "i2": "i1",
                           "label": "R1-Ethernet0/0<->R2-Ethernet0/0"}]


def test_iosv_render():
    t = to_topology(LAB, platforms.get("iosv"), "X-")
    assert t["nodes"][1]["node_definition"] == "iosv"
    assert "interface GigabitEthernet0/0" in t["nodes"][1]["configuration"]


def test_config_is_literal_block():
    y = to_yaml(LAB, platforms.get("iol"), "ENCOR-")
    assert "configuration: |" in y
