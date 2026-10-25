"""3.3.3: marking a step / a lab done by hand when a check is buggy. Recorded as completed-manually, distinct
from a graded pass: courses count it (the next lab follows), scores, mastery and solved labs do not."""
import re
from pathlib import Path

from cmllab import catalog, courses, history, manual, progress, walkthrough
from test_walkthrough import EVPN, evpn, make, wait

ROOT = Path(__file__).parent.parent
STATIC = ROOT / "cmllab" / "web" / "static"
REQ = [s.id for s in evpn().steps if walkthrough.checkable(s) and not s.optional]


# ---------------------------------------------------------------- walkthrough model
def test_mark_step_counts_as_done_not_passed():
    lab = evpn()
    st = walkthrough.mark_step(lab, "nve", True)
    s = {x["id"]: x for x in st["steps"]}["nve"]
    assert s["manual_at"] and s["done"] and s["passed"] is None
    assert st["required_passed"] == 0 and st["required_done"] == 1 and not st["completed"]
    st = walkthrough.mark_step(lab, "nve", False)
    assert {x["id"]: x for x in st["steps"]}["nve"]["manual_at"] is None and st["required_done"] == 0


def test_marking_every_failing_step_completes_manually_and_undo_reverts():
    lab = evpn()
    walkthrough.record(lab, {sid: {"passed": True, "score_pct": 100, "mode": "live"} for sid in REQ[:-1]})
    walkthrough.record(lab, {REQ[-1]: {"passed": False, "score_pct": 50, "mode": "live"}})
    assert not walkthrough.status(lab)["completed"]
    st = walkthrough.mark_step(lab, REQ[-1], True)          # the buggy check: advance past it
    assert st["completed"] and st["completed_manually"] and st["required_passed"] == len(REQ) - 1
    st = walkthrough.mark_step(lab, REQ[-1], False)
    assert not st["completed"] and not st["completed_manually"]
    # graded completion is never affected by marks
    walkthrough.mark_step(lab, REQ[-1], True)
    st = walkthrough.record(lab, {REQ[-1]: {"passed": True, "score_pct": 100, "mode": "live"}})
    assert st["completed"] and not st["completed_manually"]   # the step has since passed: a graded completion
    st = walkthrough.mark_step(lab, REQ[-1], False)
    assert st["completed"] and not st["completed_manually"]


def test_mark_whole_walkthrough_complete_and_undo():
    lab = evpn()
    walkthrough.record(lab, {REQ[0]: {"passed": True, "score_pct": 100, "mode": "live"}})
    st = walkthrough.mark_complete(lab, True)
    assert st["completed"] and st["completed_manually"] and st["manual_completed"]
    assert st["required_passed"] == 1                       # step results untouched
    st = walkthrough.mark_complete(lab, False)
    assert not st["completed"] and st["manual_completed"] is None and st["required_passed"] == 1
    # a graded completion stays graded: undo of a mark that was never made changes nothing
    st = walkthrough.record(lab, {sid: {"passed": True, "score_pct": 100, "mode": "live"} for sid in REQ})
    assert st["completed"] and not st["completed_manually"]
    assert walkthrough.mark_complete(lab, False)["completed"]


def test_reset_clears_manual_marks():
    lab = evpn()
    walkthrough.mark_step(lab, "nve", True)
    walkthrough.mark_complete(lab, True)
    st = walkthrough.reset(lab)
    assert not st["completed"] and st["manual_completed"] is None and not any(x["manual_at"] for x in st["steps"])


def test_unknown_step_is_an_error():
    import pytest
    with pytest.raises(walkthrough.WalkthroughError):
        walkthrough.mark_step(evpn(), "nope", True)


# ---------------------------------------------------------------- challenge labs + progress + courses
def test_challenge_mark_is_stored_apart_from_history():
    assert manual.set_done("eigrp-basic", True) and manual.get("eigrp-basic")
    assert history.load("eigrp-basic") == []
    first = manual.get("eigrp-basic")
    assert manual.set_done("eigrp-basic", True) == first   # idempotent, keeps the first time
    assert manual.set_done("eigrp-basic", False) is None and manual.load() == {}


def test_progress_lists_manual_completion_but_not_as_solved_or_mastery():
    entries = catalog.entries()
    p0 = progress.compute(entries=entries, histories={}, walkthroughs={}, marked={})
    p = progress.compute(entries=entries, histories={}, walkthroughs={}, marked={"eigrp-basic": 1.0})
    lab = {l["id"]: l for l in p["labs"]}["eigrp-basic"]
    assert lab["completed"] and lab["marked_manually"] and not lab["solved"] and lab["mastery_pct"] == 0
    assert p["overall"]["labs_solved"] == 0 and p["overall"]["labs_marked_manually"] == 1
    assert p["overall"]["mastery_pct"] == p0["overall"]["mastery_pct"]
    # a lab with a graded pass is solved; the mark is then irrelevant
    h = {"eigrp-basic": [{"ts": "2026-10-25 10:00:00", "score_pct": 100, "passed": True}]}
    lab = {l["id"]: l for l in progress.compute(entries=entries, histories=h, walkthroughs={},
                                                marked={"eigrp-basic": 1.0})["labs"]}["eigrp-basic"]
    assert lab["solved"] and lab["completed"] and not lab["marked_manually"]
    st = walkthrough.mark_complete(evpn(), True)
    w = progress.compute(entries=entries, histories={}, walkthroughs={EVPN: st}, marked={})["walkthroughs"]
    assert w["completed"] == 1 and w["marked_manually"] == 1 and w["labs"][0]["marked_manually"] and w["labs"][0]["started"]


def test_courses_count_manual_completion_and_move_to_the_next_lab():
    courses.install((ROOT / "labs" / "encor-routing.encorcourse").read_bytes())
    order = courses.list_courses()[0]["labs"]
    first, second = order[0]["id"], order[1]["id"]
    c = courses.list_courses({}, manual={first: 1.0})[0]
    assert c["solved"] == 1 and c["next"] == second
    lab = {x["id"]: x for x in c["labs"]}[first]
    assert lab["solved"] and lab["marked_manually"] and lab["best"] is None


# ---------------------------------------------------------------- web API
def test_api_challenge_mark_complete_and_undo():
    courses.install((ROOT / "labs" / "encor-routing.encorcourse").read_bytes())
    c, _ = make()
    first = c.get("/api/courses").json()["courses"][0]["labs"][0]["id"]
    r = c.post(f"/api/labs/{first}/mark-complete").json()
    assert r["solved"] and r["marked_manually"] and r["manual_completed"]
    lab = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}[first]
    assert lab["solved"] and lab["marked_manually"]
    d = c.get(f"/api/labs/{first}").json()
    assert d["solved"] and d["marked_manually"] and d["manual_completed"]
    crs = c.get("/api/courses").json()["courses"][0]
    assert crs["solved"] == 1 and crs["next"] != first and {x["id"]: x for x in crs["labs"]}[first]["marked_manually"]
    p = c.get("/api/progress").json()
    assert {l["id"]: l for l in p["labs"]}[first]["marked_manually"] and p["overall"]["labs_solved"] == 0
    assert c.get(f"/api/history/{first}").json() == []         # never a graded attempt
    r = c.post(f"/api/labs/{first}/mark-complete?done=false").json()
    assert not r["solved"] and not r["marked_manually"] and r["manual_completed"] is None
    assert c.get("/api/courses").json()["courses"][0]["next"] == first
    assert c.post("/api/labs/no-such-lab/mark-complete").status_code == 404


def test_api_walkthrough_step_and_lab_marks():
    c, _ = make(solved=False)
    res = wait(c, c.post(f"/api/labs/{EVPN}/steps/nve/check").json()["job_id"])["result"]
    assert not res["passed"]
    st = c.post(f"/api/labs/{EVPN}/steps/nve/mark-done").json()
    nve = {x["id"]: x for x in st["steps"]}["nve"]
    assert nve["passed"] is False and nve["manual_at"] and nve["done"] and st["required_done"] == 1
    assert c.post(f"/api/labs/{EVPN}/steps/nope/mark-done").status_code == 404
    assert c.post("/api/labs/eigrp-basic/steps/x/mark-done").status_code == 400     # not a walkthrough
    r = c.post(f"/api/labs/{EVPN}/mark-complete").json()["walkthrough"]
    assert r["completed"] and r["completed_manually"]
    lab = {l["id"]: l for l in c.get("/api/labs").json()["labs"]}[EVPN]
    assert lab["solved"] and lab["marked_manually"] and lab["walkthrough"]["completed_manually"]
    p = c.get("/api/progress").json()["walkthroughs"]
    assert p["completed"] == 1 and p["marked_manually"] == 1 and p["labs"][0]["steps_marked"] == 1
    r = c.post(f"/api/labs/{EVPN}/mark-complete?done=false").json()["walkthrough"]
    assert not r["completed"] and r["required_done"] == 1
    st = c.post(f"/api/labs/{EVPN}/steps/nve/mark-done?done=false").json()
    assert st["required_done"] == 0


def test_api_mark_needs_the_csrf_header():
    """Like every POST: without the app's CSRF header, or from another origin, the mark is refused."""
    c, _ = make()
    c.headers.pop("X-CMLLab-Request", None)
    assert c.post("/api/labs/eigrp-basic/mark-complete").status_code == 403
    assert c.post(f"/api/labs/{EVPN}/steps/nve/mark-done").status_code == 403
    c, _ = make()
    assert c.post("/api/labs/eigrp-basic/mark-complete", headers={"origin": "https://evil.example"}).status_code == 403
    assert manual.load() == {} and not walkthrough.status(evpn())["steps"][6]["manual_at"]


# ---------------------------------------------------------------- UI
def test_ui_has_mark_controls_labels_and_confirm():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    help_ = (STATIC / "help.json").read_text(encoding="utf-8")
    for key in ("w.markStep", "w.unmarkStep", "lab.markComplete", "lab.unmarkComplete", "p.marked"):
        assert f'data-help="{key}"' in js and f'"{key}"' in help_
    assert "Mark step done" in js and "Mark lab complete" in js and "Undo / mark incomplete" in js
    assert re.search(r"if \(!confirm\(done\s*\? `Mark this \$\{what\} complete by hand", js)
    assert js.count("manTag(") >= 6 and "marked manually" in js
    assert "/mark-complete?done=" in js and "/mark-done?done=" in js
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".tag.manual{" in css and ".walk-steps li.man button{" in css
    assert "onclick=" not in re.sub(r"\.onclick\s*=", "", js)     # no inline handlers (CSP)
