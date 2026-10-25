"""Walkthrough Next / Previous / jump scrolls to the top of the new step (3.3.3): walkscroll.js run with node on a fake
DOM, plus how the app wires it up (script order, strict CSP, focus without a ring, no scroll on re-renders)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from cmllab import __version__
from cmllab.web import security
from test_web_labs import make

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "cmllab" / "web" / "static"
NODE = shutil.which("node")


def test_walkscroll_js():
    if not NODE:
        pytest.skip("node is not installed")
    p = subprocess.run([NODE, str(ROOT / "tests/js/walkscroll_test.js")], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["failures"] == [], out["failures"]
    assert out["cases"]["page"]["delta"] == 900 - 56 - 8


def test_walkscroll_served_under_strict_csp():
    c, _ = make()
    r = c.get("/")
    html = r.text
    assert f"/static/walkscroll.js?v={__version__}" in html and html.index("walkscroll.js") < html.index("/static/app.js")
    csp = r.headers["content-security-policy"]
    assert csp == security.CSP and "script-src 'self';" in csp and "unsafe-eval" not in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    js = c.get("/static/walkscroll.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"] and "WalkScroll" in js.text
    assert not re.search(r"\beval\(|new Function|innerHTML|setAttribute\(\"style", js.text)   # CSP-safe, no inline styles


def test_app_scrolls_only_on_navigation():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    go = app[app.index("async function walkGo"):app.index("function cfgBlock")]
    assert 'WalkScroll.toStep($("#walk-step h3"), window, $("#walk-step"))' in go          # Next, Previous, step jump
    assert go.index("renderWalkStep()") < go.index("WalkScroll.toStep") < go.index("await api(")   # before the network
    for b in ('$("#w-prev").onclick = () => walkGo(i - 1)', '$("#w-next").onclick = () => walkGo(i + 1)',
              "b.onclick = () => walkGo(Number(b.dataset.step))"):
        assert b in app, b
    assert app.count("WalkScroll.toStep") == 1      # checking / applying a step re-renders in place without jumping
    after = app[app.index("async function afterStepJob"):app.index("/* ---------------------------------------------------------------- progress dashboard")]
    assert "WalkScroll" not in after


def test_focus_and_motion_rules():
    js = (STATIC / "walkscroll.js").read_text(encoding="utf-8")
    assert 'setAttribute("tabindex", "-1")' in js and "preventScroll: true" in js
    assert "(prefers-reduced-motion: reduce)" in js and '"instant"' in js and '"smooth"' in js
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".walk-step .walk-focus:focus,.walk-step .walk-focus:focus-visible{outline:none;box-shadow:none}" in css
    assert re.search(r"header\{[^}]*position:sticky", css)        # the offset walkscroll.js accounts for
