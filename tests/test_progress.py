"""Progress dashboard: scoring rules, streaks, time, domain mapping, API and CLI."""
import datetime as dt

from typer.testing import CliRunner

from cmllab import blueprint, catalog, history, packs, progress
from cmllab.cli import app as cli_app
from test_web import make, wait

D = dt.date(2026, 10, 18)


def rep(score, passed=False, hints=None, failed=(), **kw):
    r = {"mode": "config", "earned": score, "total": 100, "score_pct": score, "passed": passed,
         "results": [{"id": f, "passed": False} for f in failed], "hints_used": hints, "hints_total": 3}
    r.update(kw)
    return r


def test_attempt_score_rules():
    assert progress.attempt_score({"score_pct": 100, "hints_used": 2}) == 90
    assert progress.attempt_score({"score_pct": 10, "hints_used": 3}) == 0
    assert progress.attempt_score({"score_pct": 100, "revealed": True}) == 50
    assert progress.attempt_score({"score_pct": 100, "exam": {"final_pct": 72.5}}) == 72.5


def test_lab_time_handles_timer_resets():
    assert progress.lab_time([{"elapsed_s": 60}, {"elapsed_s": 300}, {"elapsed_s": 40}, {}, {"elapsed_s": 100}]) == 400


def test_streaks():
    days = {D, D - dt.timedelta(days=1), D - dt.timedelta(days=2), D - dt.timedelta(days=10), D - dt.timedelta(days=11)}
    assert progress.streaks(days, D) == {"current": 3, "longest": 3, "active_days": 5, "last_day": "2026-10-18"}
    assert progress.streaks({D - dt.timedelta(days=1)}, D)["current"] == 1     # yesterday still counts
    assert progress.streaks({D - dt.timedelta(days=2)}, D)["current"] == 0
    assert progress.streaks(set(), D)["current"] == 0


def test_blueprint_v12_mapping_of_builtin_labs():
    for lid, e in catalog.entries().items():
        for b in e.lab.blueprint:
            assert blueprint.known(b), f"{lid}: {b} is not an ENCOR v1.2 topic"
    assert catalog.get("06-hsrp").blueprint == ["3.3.c"] and blueprint.title("3.3.c").startswith("FHRP")
    assert sum(w for _, w in blueprint.DOMAINS.values()) == 100


def test_compute_from_history():
    history.add("06-hsrp", rep(100, True, hints=1, elapsed_s=600))
    history.add("06-hsrp", rep(40, failed=["r1-auth"], elapsed_s=120))
    history.add("eigrp-basic", rep(50, failed=["r1-ping", "r1-route"], hints=0, elapsed_s=300))
    history.add("eigrp-basic", rep(100, True, fault="r2-wrong-as", elapsed_s=900))
    p = progress.compute(today=dt.date.today())
    o = p["overall"]
    assert o["labs_solved"] == 2 and o["labs_attempted"] == 2 and o["checks_run"] == 4 and o["faults_fixed"] == 1
    assert o["time_spent_s"] == 600 + 120 + 900
    hsrp = next(l for l in p["labs"] if l["id"] == "06-hsrp")
    assert hsrp["mastery_pct"] == 95
    ip = next(d for d in p["domains"] if d["id"] == "3.0")
    assert ip["attempted"] == 2 and 0 < ip["mastery_pct"] < 100
    # item mastery averages every lab tagged with the item (unattempted labs count as 0)
    n_fhrp = sum("3.3.c" in e.lab.blueprint for e in catalog.entries().values())
    assert next(i for i in p["items"] if i["id"] == "3.3.c")["mastery_pct"] == round(95 / n_fhrp, 1)
    assert p["weakest"][0]["mastery_pct"] == 0
    assert {f["check_id"] for f in p["failed_checks"]} == {"r1-auth", "r1-ping", "r1-route"}
    assert p["streak"]["current"] == 1 and p["activity"][-1]["checks"] == 4
    assert p["recent"][0]["kind"] in ("lab", "fault")
    assert 0 < o["mastery_pct"] < 100 and "1.0" in o["uncovered_domains"]


def test_api_check_records_elapsed_and_revealed_and_progress_endpoint():
    c, _ = make()
    j = wait(c, c.post("/api/labs/eigrp-basic/check?mode=config&hints_used=1&elapsed_s=321&revealed=true").json()["job_id"])
    assert j["state"] == "done"
    h = history.load("eigrp-basic")[-1]
    assert h["elapsed_s"] == 321 and h["revealed"] is True and h["hints_used"] == 1
    p = c.get("/api/progress").json()
    lab = next(l for l in p["labs"] if l["id"] == "eigrp-basic")
    assert lab["mastery_pct"] == 50 and lab["time_s"] == 321   # revealed caps the counted score at 50%


def test_cli_progress():
    history.add("03-ospf-multiarea", rep(80, failed=["r3-stub"]))
    r = CliRunner().invoke(cli_app, ["progress"])
    assert r.exit_code == 0 and "Overall mastery" in r.output and "3.0 Infrastructure" in r.output
    assert "no labs yet" in r.output and "Weakest topics" in r.output


def test_lint_warns_on_unknown_blueprint_item():
    d = catalog.entry("eigrp-basic").path
    text = (d / "lab.yaml").read_text(encoding="utf-8").replace('id: eigrp-basic', 'id: eigrp-x').replace('["3.2.a"]', '["3.2.a", "9.9"]')
    rep_ = packs.lint(packs.Pack(text, (d / "solution.cfg").read_text(encoding="utf-8")))
    assert any("not ENCOR v1.2 exam topics" in w for w in rep_.warnings)
