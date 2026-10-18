"""Template regexes against realistic IOS output."""
import pytest

from encorlab import platforms
from encorlab.grader import evaluate
from encorlab.schema import Check

IOL = platforms.get("iol")
IOSV = platforms.get("iosv")


def chk(template, **params):
    return Check.model_validate({"id": "t", "device": "R1", "template": template, "params": params})


OSPF_NBR = """
Neighbor ID     Pri   State           Dead Time   Address         Interface
2.2.2.2           0   FULL/  -        00:00:35    10.0.12.2       Ethernet0/0
3.3.3.3           1   INIT/DROTHER    00:00:39    10.0.13.3       Ethernet0/1
"""
EIGRP_NBR = """EIGRP-IPv4 Neighbors for AS(100)
H   Address                 Interface              Hold Uptime   SRTT   RTO  Q  Seq
0   10.0.12.2               Et0/0                    13 00:02:41    6   100  0  3
"""
EIGRP_NBR_V = EIGRP_NBR.replace("Et0/0", "Gi0/0")
BGP_SUM = """Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.0.12.2       4        65002       9       9        5    0    0 00:05:01        2
10.0.13.3       4        65003       0       0        1    0    0 never    Active
"""
ROUTES = """Gateway of last resort is 10.0.23.2 to network 0.0.0.0

O*IA  0.0.0.0/0 [110/11] via 10.0.23.2, 00:05:40, Ethernet0/0
      2.0.0.0/32 is subnetted, 1 subnets
D        2.2.2.2 [90/409600] via 10.0.12.2, 00:02:38, Ethernet0/0
      10.0.0.0/8 is variably subnetted, 4 subnets, 2 masks
O IA     10.0.34.0/24 [110/30] via 10.0.12.2, 00:05:02, Ethernet0/0
O E2     192.168.50.0/24 [110/20] via 10.0.12.2, 00:01:00, Ethernet0/0
      172.16.0.0/22 is subnetted, 1 subnets
O IA     172.16.0.0 [110/21] via 10.0.12.2, 00:04:51, Ethernet0/0
B        203.0.113.0/24 [20/0] via 10.0.12.2, 00:01:00
S*    0.0.0.0/0 [1/0] via 10.0.0.1
"""
PING_OK = "Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/2 ms"
PING_BAD = "Success rate is 0 percent (0/5)"
VLANS = """VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Et0/2, Et0/3
10   USERS                            active    Et1/0
20   VOICE                            act/lshut
"""
RUN = """router ospf 1
 router-id 1.1.1.1
 area 1 stub no-summary
router eigrp CORE
 !
 address-family ipv4 unicast autonomous-system 100
  network 10.0.0.0
router bgp 65001
"""


@pytest.mark.parametrize("check,out,plat,want", [
    (chk("ospf_neighbor", neighbor_id="2.2.2.2"), OSPF_NBR, IOL, True),
    (chk("ospf_neighbor", neighbor_id="3.3.3.3"), OSPF_NBR, IOL, False),
    (chk("eigrp_neighbor", address="10.0.12.2"), EIGRP_NBR, IOL, True),
    (chk("eigrp_neighbor", address="10.0.12.2", interface="%if0%"), EIGRP_NBR, IOL, True),
    (chk("eigrp_neighbor", address="10.0.12.2", interface="%if0%"), EIGRP_NBR_V, IOSV, True),
    (chk("eigrp_neighbor", address="10.0.12.2", interface="%if1%"), EIGRP_NBR, IOL, False),
    (chk("bgp_established", neighbor="10.0.12.2", remote_as=65002), BGP_SUM, IOL, True),
    (chk("bgp_established", neighbor="10.0.13.3", remote_as=65003), BGP_SUM, IOL, False),
    (chk("route_present", prefix="2.2.2.2/32", code="D"), ROUTES, IOL, True),
    (chk("route_present", prefix="172.16.0.0/22", code="O IA"), ROUTES, IOL, True),
    (chk("route_present", prefix="10.0.34.0/24", code="O IA", via="10.0.12.2"), ROUTES, IOL, True),
    (chk("route_present", prefix="10.0.34.0/24", code="O IA", via="10.9.9.9"), ROUTES, IOL, False),
    (chk("route_present", prefix="192.168.50.0/24", code="O E2"), ROUTES, IOL, True),
    (chk("route_present", prefix="203.0.113.0/24", code="B"), ROUTES, IOL, True),
    (chk("route_present", prefix="0.0.0.0/0", code="S"), ROUTES, IOL, True),
    (chk("route_present", prefix="172.16.0.0/22", code="O"), ROUTES, IOL, False),
    (chk("ping", target="2.2.2.2"), PING_OK, IOL, True),
    (chk("ping", target="2.2.2.2"), PING_BAD, IOL, False),
    (chk("interface_up", interface="%if0%"), "Ethernet0/0 is up, line protocol is up", IOL, True),
    (chk("interface_up", interface="%if0%"), "GigabitEthernet0/0 is up, line protocol is up", IOSV, True),
    (chk("interface_up", interface="Tunnel0"), "Tunnel0 is up, line protocol is down", IOL, False),
    (chk("vlan_exists", vlan=10, name="USERS"), VLANS, IOL, True),
    (chk("vlan_exists", vlan=20), VLANS, IOL, False),
    (chk("show_contains", command="show ip protocols", pattern="Routing Protocol is \"ospf 1\""), 'Routing Protocol is "ospf 1"', IOL, True),
    (chk("config_router", protocol="ospf", process=1), RUN, IOL, True),
    (chk("config_router", protocol="eigrp", process=100), RUN, IOL, True),
    (chk("config_router", protocol="bgp", process=65001), RUN, IOL, True),
    (chk("config_router", protocol="bgp", process=65002), RUN, IOL, False),
    (chk("config_lines", lines="router-id 1.1.1.1\narea 1 stub no-summary"), RUN, IOL, True),
    (chk("config_lines", lines="area 1 stub"), RUN, IOL, False),
    (chk("config_regex", pattern=r"^ area 1 stub"), RUN, IOL, True),
])
def test_template_vs_ios(check, out, plat, want):
    ok, details = evaluate(check, out, plat)
    assert ok is want, details


def test_template_param_errors():
    with pytest.raises(Exception):
        chk("ospf_neighbor")
    with pytest.raises(Exception):
        chk("ospf_neighbor", neighbor_id="2.2.2.2", extra=1)
    with pytest.raises(Exception):
        chk("route_present", prefix="1.1.1.1/40", code="O")
    with pytest.raises(Exception):
        chk("route_present", prefix="1.1.1.1/32", code="R")
    with pytest.raises(Exception):
        chk("nope")


def test_template_description_generated_and_explicit_wins():
    assert "2.2.2.2" in chk("ospf_neighbor", neighbor_id="2.2.2.2").description
    c = Check.model_validate({"id": "t", "device": "R1", "template": "ping", "params": {"target": "1.1.1.1"}, "description": "mine"})
    assert c.description == "mine" and c.min_success == 80 and c.command == "ping 1.1.1.1 repeat 5"
