"""Library topic tags (3.2.0): the vocabulary, derivation for labs without topics, the index and the library page."""
import json
import sys
from pathlib import Path

import pytest
import yaml

from cmllab import library, topics
from test_library_labs import client, fetcher

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "cmllab" / "web" / "static"
sys.path.insert(0, str(ROOT / "packaging"))


def test_vocabulary_is_small_unique_and_labelled():
    ids = [t for t, _, _ in topics.TOPICS]
    assert len(ids) == len(set(ids)) and 15 <= len(ids) <= 30
    assert all(lbl and area for _, lbl, area in topics.TOPICS)
    assert {"walkthrough", "challenge"} <= set(ids) and "other" in topics.SUBJECTS and "walkthrough" not in topics.SUBJECTS
    v = topics.vocabulary(["ospf", "ccnp-dc"])
    assert v[0] == {"id": "ospf", "label": "OSPF", "area": "Routing"} and v[-1] == {"id": "ccnp-dc", "label": "CCNP DC", "area": "Track"}


def test_normalize_accepts_ids_and_labels_and_drops_unknowns():
    assert topics.normalize(["OSPF", "evpn / vxlan", "Data Center", "made-up", "ospf", 3]) == ["ospf", "evpn-vxlan", "data-center"]
    assert topics.normalize(None) == [] and topics.normalize("bgp") == ["bgp"]


@pytest.mark.parametrize("item,expect", [
    ({"id": "x", "title": "OSPF over GRE", "blueprint": ["3.2.b"]}, ["ospf", "tunnels"]),
    ({"id": "x", "title": "Leaf and spine", "node_types": ["nxosv9000"]}, ["data-center"]),
    ({"id": "x", "title": "Default routes", "description": "A lab with a default route."}, ["other"]),   # 'default' != fault
    ({"id": "x", "title": "Fix the broken HSRP", "blueprint": ["3.3.c"]}, ["fhrp", "troubleshooting"]),
    ({"id": "x", "title": "Something", "blueprint": ["3.2.b"], "track": "CCIE"}, ["other"]),   # blueprint map is ENCOR's
])
def test_derive(item, expect):
    assert topics.derive(item)[:len(expect)] == expect if expect != ["other"] else topics.derive(item) == ["other"]


def test_for_lab_adds_type_and_track():
    assert topics.for_lab({"topics": ["BGP"], "type": "walkthrough", "track": "ENCOR"}) == ["bgp", "walkthrough", "encor"]
    assert topics.for_lab({"title": "MPLS LDP", "track": "CCNP SP"}) == ["mpls", "challenge", "ccnp-sp"]


def test_every_library_lab_has_curated_topics_in_both_indexes():
    src = yaml.safe_load((ROOT / "labsrc/library.yaml").read_text(encoding="utf-8"))["topics"]
    for folder in ("library", "labs"):
        idx = json.loads((ROOT / folder / "index.json").read_text(encoding="utf-8"))
        for it in idx["items"]:
            assert it.get("topics"), (folder, it["id"])
            assert all(t in topics.LABELS or t == "encor" for t in it["topics"]), it
            if it["kind"] == "lab":
                assert it["topics"][:len(src[it["id"]])] == src[it["id"]], it["id"]
                assert ("walkthrough" if it.get("type") == "walkthrough" else "challenge") in it["topics"]


def test_packs_carry_no_topics_so_old_clients_and_the_strict_schema_are_unaffected():
    import zipfile
    for p in (ROOT / "library").glob("*.cmllab"):
        with zipfile.ZipFile(p) as z:
            lab = yaml.safe_load(z.read("lab.yaml"))
        assert "topics" not in lab, p.name


def test_topic_map_validation(tmp_path, monkeypatch):
    import build_library
    (tmp_path / "library.yaml").write_text("topics:\n  a: [ospf]\n  ghost: [bgp]\n  b: [nonsense]\n", encoding="utf-8")
    monkeypatch.setattr(build_library, "LABSRC", tmp_path)
    with pytest.raises(SystemExit) as e:
        build_library.topic_map({"a", "b", "c"})
    msg = str(e.value)
    assert "ghost: not a library lab" in msg and "c: no topics" in msg and "unknown topic(s) ['nonsense']" in msg
    (tmp_path / "library.yaml").write_text("topics:\n  a: [ospf, bgp]\n", encoding="utf-8")
    assert build_library.topic_map({"a"}) == {"a": ["ospf", "bgp"]}


def test_third_party_index_without_topics_gets_derived_ones():
    raw = {"format": 1, "items": [
        {"kind": "lab", "id": "my-vxlan", "file": "my-vxlan.cmllab", "sha256": "0" * 64, "size": 1, "version": "1.0",
         "title": "My VXLAN fabric", "node_types": ["nxosv9000"]},
        {"kind": "lab", "id": "my-lab", "file": "my-lab.cmllab", "sha256": "0" * 64, "size": 1, "version": "1.0",
         "title": "Something", "topics": ["QoS", "bogus"], "type": "walkthrough", "track": "Home"},
        {"kind": "course", "id": "c", "file": "c.cmlcourse", "sha256": "0" * 64, "size": 1, "version": "1.0",
         "title": "C", "labs": ["my-vxlan", "my-lab"]}]}
    items = {i["id"]: i for i in library.parse_index(json.dumps(raw).encode())}
    assert items["my-vxlan"]["topics"][:2] == ["evpn-vxlan", "data-center"] and "challenge" in items["my-vxlan"]["topics"]
    assert items["my-lab"]["topics"] == ["qos", "walkthrough", "home"]
    assert set(items["c"]["topics"]) >= {"evpn-vxlan", "qos", "home"}


def test_api_library_returns_topics_and_vocabulary():
    c = client(fetcher())
    idx = c.get("/api/library").json()
    assert idx["topics"][0]["id"] == "ospf" and any(t["id"] == "encor" and t["area"] == "Track" for t in idx["topics"])
    voc = {t["id"] for t in idx["topics"]}
    assert all(it["topics"] and set(it["topics"]) <= voc for it in idx["items"])


def test_library_page_has_topic_ui():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for s in ('id="lib-topics"', 'role="group" aria-label="Filter by topic"', 'id="lib-view-grouped"', 'id="lib-view-list"',
              '"cmllab.library"', "aria-pressed", "aria-expanded", "aria-controls", "localStorage.setItem(LIB_PREFS",
              "ArrowRight", "lib-card", "lib-group", "type-badge", "ram_heavy", "Fuzzy.library.labels"):
        assert s in js, s
    help_ = json.loads((STATIC / "help.json").read_text(encoding="utf-8"))
    for k in ("lib.topic", "lib.cardTopic", "lib.clearTopics", "lib.group", "lib.viewGrouped", "lib.viewList",
              "lib.expandAll", "lib.collapseAll"):
        assert help_.get(k), k
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".lib-grid{" in css and ".chip[aria-pressed=true]" in css and "@media (max-width:900px){.lib-grid" in css
    assert "topics:" in (STATIC / "fuzzy.js").read_text(encoding="utf-8")
