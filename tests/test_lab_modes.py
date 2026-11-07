"""3.3.7: every lab in challenge or walkthrough mode, chosen at build time and switchable without a rebuild."""
from pathlib import Path

from typer.testing import CliRunner

from cmllab import catalog, guide, packs
from cmllab.cli import app as cli
from test_walkthrough import EVPN, make, wait

ROOT = Path(__file__).resolve().parents[1]
OSPF = "03-ospf-multiarea"


def test_every_library_lab_has_walkthrough_content_in_both_modes():
    """Shared validator: a step without commands, explanation or expected output fails the library build
    (packs.lint strict). Here: both shapes of every library lab can be produced."""
    for root in (ROOT / "labsrc", ROOT / "examples"):
        for d in sorted(p for p in root.iterdir() if (p / "lab.yaml").is_file()):
            pk = packs.read_dir(d)
            lab = packs.pack_lab(pk)
            assert not packs.guide_errors(lab, pk, packs.solution_of(lab, pk), strict=True), d.name
            if lab.is_walkthrough:
                ch = guide.as_challenge(lab)
                assert ch.checks and ch.solution and "## Goals" in ch.task and not ch.steps, d.name
            else:
                steps, _ = guide.guide_steps(lab, d)
                assert all(st.explain and (st.config or st.verify) for st in steps), d.name
                assert {c.id for st in steps for c in st.checks} == {c.id for c in lab.checks}, d.name
    # an unexplained command is a library error, not a silent "see the command reference"
    assert guide.unexplained("router ospf 1\n frobnicate 7\n") == ["frobnicate 7"]


def test_build_chooses_the_mode_and_switching_needs_no_rebuild():
    c, _ = make()
    assert c.get(f"/api/labs/{OSPF}").json()["mode_chosen"] is None
    r = c.post(f"/api/labs/{OSPF}/build?mode=walkthrough")
    assert wait(c, r.json()["job_id"])["state"] == "done"
    lab = c.get(f"/api/labs/{OSPF}").json()
    assert lab["type"] == lab["mode"] == "walkthrough" and lab["native_type"] == "challenge"
    assert lab["mode_chosen"] == "walkthrough" and lab["guide_source"] == "derived"
    st = lab["steps"][0]
    assert st["title"] == "Configure R1" and "router ospf 1" in st["config"]["R1"] and "Ethernet0/0" in st["config"]["R1"]
    assert "`area 1 stub`: Makes area 1 a stub area" in st["explain"] and st["verify"]
    last = lab["steps"][-1]
    assert last["id"] == "verify" and any("FULL/" in v["expect"] for v in last["verify"])
    # checks still run, per step
    j = wait(c, c.post(f"/api/labs/{OSPF}/steps/verify/check").json()["job_id"])
    assert j["state"] == "done" and j["result"]["passed"]
    # switch back without a rebuild: today's challenge, with its own checks and solution
    assert c.post(f"/api/labs/{OSPF}/mode?mode=challenge").json()["mode"] == "challenge"
    lab = c.get(f"/api/labs/{OSPF}").json()
    assert lab["type"] == "challenge" and lab["steps"] is None and len(lab["checks"]) == 12 and lab["has_solution"]
    assert c.post(f"/api/labs/{OSPF}/mode?mode=bogus").status_code == 400
    # a walkthrough lab played as a challenge: goals, every step check, the step configs as the solution
    assert c.post(f"/api/labs/{EVPN}/mode?mode=challenge").status_code == 200
    lab = c.get(f"/api/labs/{EVPN}").json()
    assert lab["type"] == "challenge" and lab["native_type"] == "walkthrough" and "## Goals" in lab["task"]
    assert lab["checks"] and c.get(f"/api/labs/{EVPN}/solution").status_code == 200
    assert {x["id"]: x["type"] for x in c.get("/api/labs").json()["labs"]}[EVPN] == "challenge"
    assert catalog.entry(EVPN).own.type == "walkthrough"


def test_cli_build_mode_switch_and_guide_scaffold(tmp_path):
    r = CliRunner()
    assert r.invoke(cli, ["build", OSPF, "--mode", "nope"]).exit_code == 2
    assert "challenge mode" in r.invoke(cli, ["mode", OSPF]).output
    assert "now in walkthrough mode" in r.invoke(cli, ["mode", OSPF, "walkthrough"]).output
    out = r.invoke(cli, ["step", OSPF]).output
    assert "Configure R1" in out and "Verify end to end" in out
    import shutil
    d = tmp_path / OSPF
    shutil.copytree(ROOT / "labsrc" / OSPF, d)
    assert "wrote" in r.invoke(cli, ["guide", str(d), "--write"]).output and (d / "guide.yaml").is_file()
    pk = packs.read_dir(d)
    assert pk.guide_yaml and packs.lint(pk, strict=True).ok


def test_walkthrough_commands_alone_pass_every_step_in_live_and_config_grading():
    """3.3.8 (lab 05 step 5): apply only what each challenge lab's walkthrough tells you to type on top of the
    day-0 configs, then every step must pass, both with console (live) grading and in the config-mode fallback."""
    import yaml

    from cmllab import config, platforms, walkthrough
    from cmllab.sim import SimRunner
    s = config.Settings(cml_url="https://cml.x", username="u", password="pw")
    n = 0
    for root in (ROOT / "labsrc", ROOT / "examples"):
        for d in sorted(p for p in root.iterdir() if (p / "lab.yaml").is_file()):
            pk = packs.read_dir(d)
            lab = packs.pack_lab(pk)
            if lab.is_walkthrough:
                continue
            wl = guide.as_walkthrough(lab, guide.guide_steps(lab, d)[0])
            fx = {k: yaml.safe_load((d / f"fixture_{k}.yaml").read_text()) if (d / f"fixture_{k}.yaml").is_file()
                  else {} for k in ("solved", "blank")}
            sim = SimRunner(wl, platforms.get("iol"), True, solution=wl.step_solution(), fixtures=fx)
            assert any(c.mode == "config" for c in wl.steps[-1].checks), d.name   # gradable without consoles
            for st in (st for st in wl.steps if st.checks):
                for m in ("live", "config") if any(c.mode == "config" for c in st.checks) else ("live",):
                    s.grading_mode = m
                    r = walkthrough._grade(s, walkthrough.step_lab(wl, st), lambda _: None, runner=sim,
                                           config_source=sim)
                    assert r["results"] and r["passed"], (d.name, st.id, m, [x["id"] for x in r["results"]
                                                                            if not x["passed"]])
            n += 1
    assert n >= 20


def test_day0_config_survives_config_grading_and_lab_reuse():
    """3.3.8 (lab 05 on real CML: R3 booted with only Loopback0): config extraction must not replace a node's
    stored day-0 config, and building over an existing lab restores day-0 on nodes that will boot from it."""
    from cmllab import config
    from cmllab.cml import CML, CMLConfigSource
    from fakes import FakeClient
    lab = packs.pack_lab(packs.read_dir(ROOT / "labsrc" / "05-bgp-ebgp-ibgp"))
    fc = FakeClient()
    cml = CML(config.Settings(cml_url="https://cml.x", username="u", password="pw"), client_factory=lambda s: fc)
    cl = cml.build(lab, start=False)
    r3 = cl.get_node_by_label("R3")
    day0 = r3.configuration
    assert "ip address 10.0.23.1 255.255.255.252" in day0 and "ip address 10.0.34.1" in day0
    r3.state, r3.running_config = "BOOTED", "hostname R3\ninterface Loopback0\n ip address 10.255.0.3 255.255.255.255\n"
    assert "Loopback0" in CMLConfigSource(cl).get_config("R3") and r3.configuration == day0
    r3.state, r3.configuration = "DEFINED_ON_CORE", r3.running_config      # stale stored config from an older run
    msgs = []
    cml.build(lab, start=False, progress=msgs.append)
    assert r3.configuration == day0 and any("R3: restored" in m for m in msgs)


def test_every_lab_uses_valid_unique_ip_host_addresses():
    """3.3.8: lab 05's R3 used 10.0.23.3/30 (the broadcast address), which IOS rejects, so its links never came up.
    Every library lab: day-0, solution and step `ip address` lines are usable host addresses, one owner each."""
    bad = []
    for root in (ROOT / "labsrc", ROOT / "examples"):
        for d in sorted(p for p in root.iterdir() if (p / "lab.yaml").is_file()):
            pk = packs.read_dir(d)
            lab = packs.pack_lab(pk)
            bad += [f"{d.name}: {e}" for e in packs.address_errors(lab, packs.solution_of(lab, pk))]
    assert not bad, bad
    from cmllab.schema import Lab
    probe = Lab.model_validate({**lab.model_dump(), "steps": [], "type": "challenge"})
    assert packs.address_errors(probe, {"R9": "interface e0/0\n ip address 10.0.0.3 255.255.255.252\n"})
