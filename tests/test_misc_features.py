import json

import httpx
import pytest
import yaml

from encorlab import ai, catalog, history, packs, platforms, prompt
from encorlab.cml_import import _slug, draft_from_topology
from encorlab.render import to_yaml

EXAMPLE = yaml.safe_load(prompt.example())


# ---------------------------------------------------------------- CML import
def test_draft_from_rendered_topology_roundtrip():
    lab = catalog.get("eigrp-basic")
    topo = to_yaml(lab, platforms.get("iol"), "ENCOR-")
    draft, warnings = draft_from_topology(topo, "My EIGRP Lab")
    assert draft["id"] == "my-eigrp-lab" and draft["platforms"] == ["iol"]
    assert [n["name"] for n in draft["nodes"]] == [n.name for n in lab.nodes]
    assert draft["links"] == [l.model_dump() for l in lab.links]
    cfg = draft["nodes"][0]["config"]
    assert "%if0%" in cfg and "Ethernet0/0" not in cfg and "hostname" not in cfg
    assert any("checks" in w for w in warnings)


def test_draft_skips_unsupported_and_rejects_mixed():
    topo = {"nodes": [
        {"id": "n0", "label": "R1", "node_definition": "iol-xe", "x": 0, "y": 0, "configuration": "hostname R1",
         "interfaces": [{"id": "i0", "type": "loopback", "slot": 0, "label": "Loopback0"},
                        {"id": "i1", "type": "physical", "slot": 0, "label": "Ethernet0/0"}]},
        {"id": "n1", "label": "ext", "node_definition": "external_connector", "interfaces": []},
        {"id": "n2", "label": "fw", "node_definition": "asav", "interfaces": []}],
        "links": [{"id": "l0", "n1": "n0", "i1": "i1", "n2": "n1", "i2": "i0"}]}
    draft, warnings = draft_from_topology(yaml.safe_dump(topo))
    assert len(draft["nodes"]) == 1 and draft["links"] == []
    assert any("fw" in w for w in warnings) and any("l0" in w for w in warnings)
    topo["nodes"][2]["node_definition"] = "iosv"
    with pytest.raises(ValueError):
        draft_from_topology(yaml.safe_dump(topo))
    assert _slug("ENCOR: Lab #1!") == "encor-lab-1"


# ---------------------------------------------------------------- history
def test_history_add_load_cap_clear():
    for i in range(60):
        history.add("eigrp-basic", {"mode": "live", "earned": i, "total": 5, "score_pct": 20.0, "passed": False,
                                    "results": [{"id": "a", "passed": False}, {"id": "b", "passed": True}]})
    h = history.load("eigrp-basic")
    assert len(h) == history.MAX_ENTRIES and h[-1]["earned"] == 59 and h[-1]["failed"] == ["a"]
    history.clear("eigrp-basic")
    assert history.load("eigrp-basic") == []


# ---------------------------------------------------------------- prompt / schema
def test_prompt_is_self_contained():
    p = prompt.build_prompt("OSPF stub lab")
    assert "OSPF stub lab" in p and prompt.PLACEHOLDER not in p
    for needle in ("%if0%", "solution", "ospf_neighbor", "O*IA", "example-eigrp-pair", '"$schema"', "mode: config"):
        assert needle in p, needle
    assert prompt.PLACEHOLDER in prompt.build_prompt("")


def test_json_schema_validates_example_shape():
    s = prompt.json_schema()
    assert s["type"] == "object" and {"id", "nodes", "checks", "task"} <= set(s["required"])
    assert "Check" in json.dumps(s["$defs"])


# ---------------------------------------------------------------- AI (mocked)
def _reply(content):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def mock(responses, seen):
    it = iter(responses)

    def handler(req: httpx.Request):
        seen.append(req)
        status, body = next(it)
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def test_ai_success_first_try_and_auth_header():
    seen = []
    t = mock([(200, _reply(json.dumps(EXAMPLE)))], seen)
    r = ai.generate("eigrp pair", "https://api.example/v1", "m", "KEY", transport=t)
    assert r["ok"] and "example-eigrp-pair" in r["lab_yaml"]
    assert seen[0].url.path == "/v1/chat/completions" and seen[0].headers["authorization"] == "Bearer KEY"
    body = json.loads(seen[0].content)
    assert body["model"] == "m" and "JSON Schema" in body["messages"][0]["content"]


def test_ai_retries_with_errors_then_succeeds_fenced_yaml():
    bad = dict(EXAMPLE)
    bad = {k: v for k, v in bad.items() if k != "solution"}
    seen = []
    t = mock([(200, _reply(json.dumps(bad))), (200, _reply("Here:\n```yaml\n" + prompt.example() + "```"))], seen)
    r = ai.generate("eigrp pair", "http://localhost:1/v1", "m", None, transport=t)
    assert r["ok"] and len(r["attempts"]) == 2 and r["attempts"][0]["errors"]
    second = json.loads(seen[1].content)["messages"]
    assert "failed validation" in second[-1]["content"] and "authorization" not in seen[0].headers


def test_ai_gives_up_after_retries():
    seen = []
    t = mock([(200, _reply("not json {"))] * 3, seen)
    r = ai.generate("x", "http://h/v1", "m", None, transport=t)
    assert not r["ok"] and len(r["attempts"]) == 3


def test_ai_401_and_400_fallback():
    with pytest.raises(ai.AIError, match="401"):
        ai.generate("x", "http://h/v1", "m", "bad", transport=mock([(401, {"error": "no"})], []))
    seen = []
    t = mock([(400, {"error": "response_format unsupported"}), (200, _reply(json.dumps(EXAMPLE)))], seen)
    assert ai.generate("x", "http://h/v1", "m", None, transport=t)["ok"]
    assert "response_format" not in json.loads(seen[1].content)


def test_extract_lab_variants():
    assert ai.extract_lab(json.dumps({"lab": EXAMPLE}))["id"] == "example-eigrp-pair"
    with pytest.raises(ai.AIError):
        ai.extract_lab("[1, 2]")
