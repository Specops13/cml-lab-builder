"""Exam mode: timed one-shot attempt, hints off/penalized, solution withheld, score report."""
import time

import pytest
from typer.testing import CliRunner

from encorlab import catalog, exam, faults, history, progress
from encorlab.cli import app as cli_app
from test_web import make, wait

LAB = "eigrp-basic"


def test_defaults_and_validation():
    lab = catalog.get(LAB)
    assert exam.default_minutes(lab) == 20 and exam.default_minutes(catalog.get("09-gre-ipsec")) >= 45
    for kw, msg in [({"hints": "maybe"}, "penalty"), ({"minutes": 2}, "5-240"), ({"minutes": 500}, "5-240"), ({"penalty": 99}, "0-50")]:
        with pytest.raises(exam.ExamError, match=msg):
            exam.start(lab, **kw)
    faults.set_active(LAB, lab.faults[0].id)
    with pytest.raises(exam.ExamError, match="fault practice"):
        exam.start(lab)


def test_scoring_penalty_late_and_hints():
    lab = catalog.get(LAB)
    t0 = time.time()
    st = exam.start(lab, 30, "penalty", 10, now=t0)
    assert st["remaining_s"] == 1800 and not st["expired"] and st["hints_used"] == 0
    assert exam.use_hint(LAB, 3) == 1 and exam.use_hint(LAB, 3) == 2
    x = exam.finish(LAB, 100.0, now=t0 + 600)
    assert (x["final_pct"], x["penalty"], x["used_s"], x["passed"], x["late"]) == (80.0, 20, 600, True, False)
    assert exam.active(LAB) is None
    exam.start(lab, 10, "off", now=t0)
    with pytest.raises(exam.ExamError, match="disabled"):
        exam.use_hint(LAB, 3)
    x = exam.finish(LAB, 100.0, now=t0 + 600 + exam.GRACE_S + 1)
    assert x["late"] and x["final_pct"] == 0 and not x["passed"]
    exam.start(lab, 10, "penalty", now=t0)
    assert exam.status(LAB, now=t0 + 700)["expired"] and exam.status(LAB, now=t0 + 700)["remaining_s"] == 0
    exam.use_hint(LAB, 1)
    with pytest.raises(exam.ExamError, match="no more hints"):
        exam.use_hint(LAB, 1)
    assert exam.finish(LAB, 5.0, now=t0 + 60)["final_pct"] == 0     # never below 0


def test_api_exam_flow_withholds_solution_and_records_report():
    c, _ = make(solved=True)
    assert wait(c, c.post(f"/api/labs/{LAB}/build").json()["job_id"])["state"] == "done"
    assert c.get(f"/api/labs/{LAB}").json()["hints"]
    st = c.post(f"/api/labs/{LAB}/exam/start?minutes=15&hints=penalty&penalty=5").json()
    assert st["duration_s"] == 900
    assert c.post(f"/api/labs/{LAB}/exam/start").status_code == 409
    d = c.get(f"/api/labs/{LAB}").json()
    assert d["exam"]["hints"] == "penalty" and d["hints"] == [] and d["hints_total"] >= 1
    assert all(ch["hint"] == "" for ch in d["checks"])
    for url in (f"/api/labs/{LAB}/solution", f"/api/labs/{LAB}/source", f"/api/labs/{LAB}/export"):
        assert c.get(url).status_code == 403, url
    assert c.post(f"/api/labs/{LAB}/break").status_code == 403
    h = c.post(f"/api/labs/{LAB}/exam/hint").json()
    assert h["n"] == 1 and len(h["hints"]) == 1 and c.get(f"/api/labs/{LAB}").json()["exam"]["hints_shown"] == h["hints"]
    assert any(l["exam_active"] for l in c.get("/api/labs").json()["labs"] if l["id"] == LAB)
    # the client claims 0 hints; the server's count wins
    j = wait(c, c.post(f"/api/labs/{LAB}/check?hints_used=0&revealed=true").json()["job_id"])
    x = j["result"]["exam"]
    assert (x["raw_pct"], x["penalty"], x["final_pct"], x["passed"]) == (100.0, 5, 95.0, True)
    assert j["result"]["hints_used"] == 1 and "revealed" not in j["result"]
    e = history.load(LAB)[-1]
    assert e["exam"]["final_pct"] == 95.0 and progress.attempt_score(e) == 95.0
    assert c.get(f"/api/labs/{LAB}").json()["exam"] is None
    assert c.get(f"/api/labs/{LAB}/solution").status_code == 200


def test_api_exam_hints_off_and_abort():
    c, _ = make()
    c.post(f"/api/labs/{LAB}/exam/start?hints=off")
    assert c.post(f"/api/labs/{LAB}/exam/hint").status_code == 400
    assert c.post(f"/api/labs/{LAB}/exam/start?minutes=1").status_code == 409
    assert c.post(f"/api/labs/{LAB}/exam/abort").json() == {"aborted": True}
    assert c.get(f"/api/labs/{LAB}").json()["exam"] is None and history.load(LAB) == []
    assert c.post(f"/api/labs/{LAB}/exam/start?minutes=1").status_code == 400


def test_cli_exam():
    run = CliRunner().invoke
    assert "No exam running" in run(cli_app, ["exam", LAB]).output
    r = run(cli_app, ["exam", LAB, "--start", "--minutes", "25", "--hints", "penalty", "--penalty", "7"])
    assert r.exit_code == 0 and "0:25:00 on the clock" in r.output and "-7 points" in r.output
    assert "left of 0:25:00" in run(cli_app, ["exam", LAB]).output
    r = run(cli_app, ["hint", LAB])
    assert "Hint 1 of" in r.output and "exam: -7 points each, 1 used" in r.output
    assert run(cli_app, ["solution", LAB]).exit_code == 1
    assert run(cli_app, ["exam", LAB, "--start"]).exit_code == 1
    assert "aborted" in run(cli_app, ["exam", LAB, "--abort"]).output and exam.active(LAB) is None
