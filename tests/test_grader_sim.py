from cmllab import catalog, grader, platforms, sim
from cmllab.schema import Check

P = platforms.get("iol")


def chk(**kw):
    base = dict(id="c", description="d", device="R1", command="show x")
    base.update(kw)
    return Check(**base)


def test_ping_parse():
    c = chk(command="ping 1.1.1.1", min_success=80)
    assert grader.evaluate(c, "Success rate is 100 percent (5/5)", P)[0]
    assert not grader.evaluate(c, "Success rate is 60 percent (3/5)", P)[0]
    assert not grader.evaluate(c, "% Unrecognized host", P)[0]


def test_match_and_absent():
    c = chk(match=["^D\\s+2\\.2"], absent=["Null0"])
    assert grader.evaluate(c, "x\nD    2.2.2.2 [90/1]", P)[0]
    assert not grader.evaluate(c, "D    2.2.2.2 Null0", P)[0]


def test_eigrp_route_without_mask_and_with_mask():
    lab = catalog.get("eigrp-basic")
    c = next(x for x in lab.checks if x.id == "r1-route")
    a = "      2.0.0.0/32 is subnetted, 1 subnets\nD        2.2.2.2 [90/409600] via 10.0.12.2, 00:00:05, Ethernet0/0\n"
    b = "D        2.2.2.2/32 [90/409600] via 10.0.12.2, 00:00:05, Ethernet0/0\n"
    assert grader.evaluate(c, a, P)[0] and grader.evaluate(c, b, P)[0]
    assert not grader.evaluate(c, "C        10.0.12.0/24 is directly connected\n", P)[0]


def test_runner_error_is_failed_check():
    class Boom:
        def run(self, d, c):
            raise TimeoutError("console timeout")
    lab = catalog.get("eigrp-basic")
    rep = grader.grade(lab, Boom(), P)
    assert rep.score_pct == 0 and "console timeout" in rep.results[0].details[0]


def test_sim_filters():
    cfg = "hostname R1\nrouter eigrp 100\n network 1.1.1.1 0.0.0.0\ninterface Ethernet0/0\n ip address 1.1.1.1 255.0.0.0\n"
    assert sim.section(cfg, "router eigrp").splitlines() == ["router eigrp 100", " network 1.1.1.1 0.0.0.0"]
    assert sim.include(cfg, "^hostname") == "hostname R1\n"
    assert "ip address" in sim.interface(cfg, "Ethernet0/0")


def test_report_dict():
    lab = catalog.get("eigrp-basic")
    d = grader.grade(lab, sim.SimRunner(lab, P, True), P).to_dict()
    assert d["earned"] == d["total"] == 5 and d["passed"] is True and len(d["results"]) == 5
