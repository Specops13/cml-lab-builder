"""v1.4.0: solution summary (author-written or auto-generated) and progressive hints."""
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from encorlab import catalog, cli, history, packs, platforms, solution
from encorlab.schema import Lab
from test_web import make, wait

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "encorlab" / "web" / "static"
IOL = platforms.get("iol")
BUILTIN = sorted(d.name for d in catalog.lab_dirs())


def _lab_dict(lab_id="eigrp-basic"):
    return yaml.safe_load((catalog.LABS_DIR / lab_id / "lab.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("lab_id", BUILTIN)
def test_builtin_labs_have_summary_and_hints(lab_id):
    lab = catalog.get(lab_id)
    s = lab.solution_summary
    assert s.strip() and "```" in s and "Why it works" in s, lab_id
    assert re.search(r"\*\*(Root cause|What was missing)", s), lab_id
    assert 2 <= len(lab.hints) <= 4
    text, auto = solution.summary(lab, catalog.load_solution(lab_id), IOL)
    assert not auto and "%if" not in text
    for h in lab.hints:  # hints never paste a whole solution block
        assert "```" not in h and len(h) < 300


def test_example_pack_has_summary_and_hints():
    p = packs.read_dir(ROOT / "examples" / "ospf-multiarea-stub")
    rep = packs.lint(p, strict=True)
    assert rep.ok and not any("solution_summary" in w or "no hints" in w for w in rep.warnings)
    lab, _ = packs.parse_lab_text(p.lab_yaml)
    assert lab.solution_summary.strip() and len(lab.hints) == 3


def test_fallback_summary_and_hints_from_checks():
    d = _lab_dict()
    d.pop("solution_summary"), d.pop("hints")
    lab = Lab.model_validate(d)
    sol = catalog.load_solution("eigrp-basic")
    text, auto = solution.summary(lab, sol, IOL)
    assert auto and "**R1**" in text and "**R2**" in text and "network 10.0.12.0 0.0.0.255" in text
    hs = solution.hints(lab, IOL)
    check_hints = [c.hint for c in lab.checks if c.hint]
    assert hs == list(dict.fromkeys(check_hints))  # check order, duplicates dropped
    assert solution.fallback_summary({}).startswith("_This lab has no reference solution")


def test_schema_fields_and_empty_hint_rejected():
    props = Lab.model_json_schema()["properties"]
    assert "solution_summary" in props and "hints" in props
    d = _lab_dict()
    d["hints"] = ["ok", "  "]
    with pytest.raises(Exception, match="empty"):
        Lab.model_validate(d)


def test_validator_warns_without_summary_or_hints():
    d = _lab_dict()
    d.pop("solution_summary"), d.pop("hints")
    for c in d["checks"]:
        c.pop("hint", None)
    d["id"] = "no-summary-lab"
    d["solution"] = catalog.load_solution("eigrp-basic")
    rep = packs.lint(packs.Pack(lab_yaml=yaml.safe_dump(d), solution_cfg=None, fixtures={}, warnings=[]))
    assert rep.ok
    assert any("no solution_summary" in w for w in rep.warnings)
    assert any("no hints" in w for w in rep.warnings)


def test_api_lab_detail_has_ordered_hints():
    c, _ = make()
    t = c.get("/api/labs/eigrp-basic").json()
    assert t["hints"] == catalog.get("eigrp-basic").hints and t["has_solution_summary"] is True


def test_check_100_includes_summary_and_records_hints(monkeypatch):
    c, _ = make(solved=True)
    r = wait(c, c.post("/api/labs/eigrp-basic/check?mode=config&hints_used=2").json()["job_id"])["result"]
    assert r["passed"] and "Why it works" in r["solution_summary"] and r["solution_summary_auto"] is False
    assert r["hints_used"] == 2 and r["hints_total"] == 3
    h = history.load("eigrp-basic")[-1]
    assert h["hints_used"] == 2 and h["hints_total"] == 3
    r = wait(c, c.post("/api/labs/eigrp-basic/check?mode=config&hints_used=99").json()["job_id"])["result"]
    assert r["hints_used"] == 3  # clamped


def test_check_not_solved_has_no_summary_but_reveal_works():
    c, _ = make(solved=False)
    r = wait(c, c.post("/api/labs/eigrp-basic/check?mode=config").json()["job_id"])["result"]
    assert not r["passed"] and "solution_summary" not in r and r["hints_used"] is None
    s = c.get("/api/labs/eigrp-basic/solution").json()
    assert "Why it works" in s["summary"] and set(s["configs"]) == {"R1", "R2"}
    assert c.get("/api/labs/nope/solution").status_code == 404


def test_solution_rendered_for_platform():
    c, _ = make()
    c.post("/api/settings", json={"platform": "iosv"})
    s = c.get("/api/labs/06-hsrp/solution").json()
    blob = s["summary"] + "".join(s["configs"].values())
    assert "%if" not in blob and "GigabitEthernet0/0" in blob


def test_cli_solution_and_hint():
    r = CliRunner().invoke(cli.app, ["solution", "eigrp-basic"])
    assert r.exit_code == 0 and "Why it works" in r.output and "! device R1" in r.output
    r = CliRunner().invoke(cli.app, ["hint", "eigrp-basic", "2"])
    assert r.exit_code == 0 and r.output.startswith("Hint 2 of 3:")
    assert CliRunner().invoke(cli.app, ["hint", "eigrp-basic", "9"]).exit_code != 0


def test_cli_check_prints_summary_on_100(capsys):
    base = {"results": [], "notes": [], "mode": "config", "earned": 2, "total": 2, "score_pct": 100.0}
    cli._print_check(dict(base, passed=True, solution_summary="**Root cause:** X", solution_summary_auto=False))
    assert "Solution summary:" in capsys.readouterr().out
    cli._print_check(dict(base, passed=False, score_pct=50.0))
    assert "Solution summary" not in capsys.readouterr().out


def test_frontend_hint_button_and_reveal_solution():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="a-hint"' in js and "hints:${id}" in js and "localStorage" in js
    assert "Hint ${used + 1} of ${total}" in js and "Hint ${i + 1} of ${total}" in js
    assert 'if (kind === "reset") hintsSet(lab, 0)' in js          # cleared on Reset
    assert 'q.set("hints_used"' in js                               # recorded with each check
    assert "Reveal solution" in js and re.search(r"\$\(\"#a-reveal\"\)[\s\S]{0,200}if \(!confirm\(", js)
    assert "r.passed && r.solution_summary" in js                   # auto panel at 100%
    help_keys = (STATIC / "help.json").read_text(encoding="utf-8")
    for k in ("lab.hintNext", "lab.hintsBox", "lab.revealSolution", "lab.solutionPanel", "f.solutionSummary", "f.hints"):
        assert f'"{k}"' in help_keys


def test_docs_require_summary():
    ai = (ROOT / "docs" / "AI-PROMPT.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "LAB-AUTHORING.md").read_text(encoding="utf-8")
    assert "solution_summary:` (Markdown, REQUIRED)" in ai and "`hints:`" in ai
    assert "## Solution summary and hints" in guide and "validator warns" in guide
    ex = Lab.model_validate(yaml.safe_load((ROOT / "docs" / "example-lab.yaml").read_text(encoding="utf-8")))
    assert ex.solution_summary and ex.hints
