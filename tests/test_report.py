"""Printable HTML reports (lab + progress)."""
from typer.testing import CliRunner

from encorlab import catalog, exam, history, report
from encorlab.cli import app as cli_app
from test_web import make, wait

LAB = "eigrp-basic"


def test_lab_report_after_check_and_escaping():
    c, _ = make(solved=True)
    r = c.get(f"/report/labs/{LAB}")
    assert r.status_code == 200 and "No detailed result yet" in r.text and "No attempts yet" in r.text
    assert wait(c, c.post(f"/api/labs/{LAB}/build").json()["job_id"])["state"] == "done"
    wait(c, c.post(f"/api/labs/{LAB}/check?hints_used=1&elapsed_s=754").json()["job_id"])
    html = c.get(f"/report/labs/{LAB}?name=<script>alert(1)</script>").text
    assert catalog.get(LAB).title in html and "Score " in html and "SOLVED" in html and ">PASS<" in html
    assert "Solution summary" in html and "0:12:34" in html and "hints used 1/" in html
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    with_out = c.get(f"/report/labs/{LAB}?outputs=true").text
    assert with_out.count("<pre>") > html.count("<pre>")
    assert "window.print()" in html and "@media print" in html


def test_report_trims_outputs_and_clears_with_history():
    rep = {"mode": "live", "earned": 0, "total": 1, "score_pct": 0, "passed": False,
           "results": [{"id": "x", "passed": False, "device": "R1", "description": "d", "command": "show x",
                        "details": [], "output": "A" * 10000}]}
    report.save_last(LAB, rep)
    out = report.load_last(LAB)["results"][0]["output"]
    assert len(out) < 4100 and "more characters" in out
    history.add(LAB, rep)
    history.clear(LAB)
    assert report.load_last(LAB) is None


def test_exam_report_and_block_during_exam():
    c, _ = make(solved=True)
    wait(c, c.post(f"/api/labs/{LAB}/build").json()["job_id"])
    c.post(f"/api/labs/{LAB}/exam/start?minutes=10")
    assert c.get(f"/report/labs/{LAB}").status_code == 403
    wait(c, c.post(f"/api/labs/{LAB}/check").json()["job_id"])
    html = c.get(f"/report/labs/{LAB}").text
    assert "Exam result:" in html and "100.0% PASS" in html and ">exam<" in html
    assert exam.active(LAB) is None


def test_progress_report():
    history.add(LAB, {"mode": "config", "earned": 1, "total": 1, "score_pct": 100, "passed": True, "results": []})
    c, _ = make()
    html = c.get("/report/progress?name=Dylan").text
    assert "CCNP ENCOR (350-401) practice progress" in html and "Dylan" in html
    assert "3.0 Infrastructure" in html and "no labs (theory)" in html and "solved" in html


def test_cli_report(tmp_path):
    out = tmp_path / "r.html"
    r = CliRunner().invoke(cli_app, ["report", LAB, "-o", str(out), "--name", "Dylan"])
    assert r.exit_code == 0 and "Dylan" in out.read_text() and catalog.get(LAB).title in out.read_text()
    r = CliRunner().invoke(cli_app, ["report", "-o", str(tmp_path / "p.html")])
    assert r.exit_code == 0 and "ENCOR exam domains" in (tmp_path / "p.html").read_text()


def test_markdown_filter_is_safe():
    out = str(report._md("**Fix** <img src=x onerror=alert(1)>\n\n```\n! R1\n<b>\n```\nuse `show ip route`"))
    assert "<b>Fix</b>" in out and "&lt;img" in out and "<pre>! R1\n&lt;b&gt;</pre>" in out and "<code>show ip route</code>" in out
