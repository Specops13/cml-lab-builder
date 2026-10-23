"""Library search (3.1.0): fuzzy.js ranking + speed (run with node), the served UI and the index search fields."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cmllab import __version__, library, topics
from test_web_labs import make, upload, zip_dir, OSPF

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "cmllab" / "web" / "static"
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def js_run(tmp_path_factory):
    if not NODE:
        pytest.skip("node is not installed")
    voc = tmp_path_factory.mktemp("topics") / "topics.json"
    voc.write_text(json.dumps(topics.vocabulary()), encoding="utf-8")
    p = subprocess.run([NODE, str(ROOT / "tests/js/fuzzy_test.js"), str(ROOT / "library/index.json"), str(voc)],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_fuzzy_ranking(js_run):
    assert js_run["failures"] == []
    ex = js_run["examples"]
    assert ex["evpn mpls"][0] == "19-evpn-mpls" and ex["vrf lit"][0] == "08-vrf-lite"
    assert "ospf-multiarea-stub" in ex["ospf stb"][:2] and "14-multicast-pim-sm" in ex["mcast"]


def test_fuzzy_speed(js_run):
    b = js_run["bench"]
    print("library search benchmark:", b)
    assert b["items"] >= 290 and b["keystrokes"] > 50
    # target < 5 ms per keystroke for a few hundred labs (typically ~1 ms); loose bound for slow CI machines
    assert b["mean_ms"] < 5 and b["p95_ms"] < 20, b


def test_search_ui_served():
    c, _ = make()
    html = c.get("/").text
    assert f'/static/fuzzy.js?v={__version__}' in html and html.index("fuzzy.js") < html.index("app.js")
    r = c.get("/static/fuzzy.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"] and "window" in r.text and "Fuzzy" in r.text
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    for s in ('id="lib-search"', 'id="lib-kind"', 'id="lib-status"', 'id="lib-course"', 'id="lib-noheavy"', "lib-empty",
              "Fuzzy.search", "Fuzzy.highlight", 'e.key === "/"', '"k"', '"Escape"'):
        assert s in app_js, s
    assert "/api/library" not in app_js[app_js.index("function libApply"):app_js.index("function libBindValues")]  # client side
    help_ = json.loads((STATIC / "help.json").read_text(encoding="utf-8"))
    for k in ("lib.search", "lib.fKind", "lib.fStatus", "lib.fCourse", "lib.fHeavy"):
        assert help_.get(k), k
    assert "mark{" in (STATIC / "style.css").read_text(encoding="utf-8")


def test_index_has_search_fields():
    idx = json.loads((ROOT / "library/index.json").read_text(encoding="utf-8"))
    labs = {i["id"]: i for i in idx["items"] if i["kind"] == "lab"}
    assert "nxosv9000" in labs["20-evpn-vxlan-superspine"]["node_types"] and "iol-xe" in labs["19-evpn-mpls"]["node_types"]
    assert labs["01-vlan-trunk-stp"]["domain"].startswith("3.0") and labs["01-vlan-trunk-stp"]["platforms"] == ["iol", "iosv"]
    parsed = {i["id"]: i for i in library.parse_index(json.dumps(idx).encode())}
    assert parsed["20-evpn-vxlan-superspine"]["node_types"] == labs["20-evpn-vxlan-superspine"]["node_types"]
    assert parsed["01-vlan-trunk-stp"]["track"] == "ENCOR"
    # older indexes without the fields still parse
    old = {"format": 1, "items": [{k: v for k, v in labs["06-hsrp"].items() if k not in ("domain", "node_types", "platforms", "track")}]}
    p = library.parse_index(json.dumps(old).encode())[0]
    assert p["node_types"] == [] and p["domain"] == "" and p["platforms"] == []


def test_api_labs_has_node_types():
    c, _ = make()
    assert upload(c, "ospf.zip", zip_dir(OSPF)).status_code == 200
    lab = next(l for l in c.get("/api/labs").json()["labs"] if l["id"] == "ospf-multiarea-stub")
    assert lab["node_types"] and lab["track"]
