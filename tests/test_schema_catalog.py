import copy

import pytest
import yaml

from cmllab import catalog
from cmllab.schema import Lab
from tables import run_table

LAB = catalog.get("eigrp-basic")


def raw():
    return yaml.safe_load((catalog.LABS_DIR / "eigrp-basic" / "lab.yaml").read_text(encoding="utf-8"))


def test_catalog_basics():
    def _catalog_loads():
        labs = catalog.load_all()
        assert "eigrp-basic" in labs
        assert LAB.node_count == 2 and len(LAB.checks_for("live")) == 5 and len(LAB.checks_for("config")) == 6

    def _unknown_lab():
        with pytest.raises(catalog.LabNotFound):
            catalog.get("nope")

    def _solution_has_all_devices():
        sol = catalog.load_solution("eigrp-basic")
        assert set(sol) == {"R1", "R2"}
        assert "router eigrp 100" in sol["R1"]

    for case in (_catalog_loads, _unknown_lab, _solution_has_all_devices):
        case()


SCHEMA_REJECTS_ROWS = [
    (lambda d: d["links"].append({"a": {"node": "R1", "port": 0}, "b": {"node": "R2", "port": 1}}), "used twice"),
    (lambda d: d["links"].append({"a": {"node": "R9", "port": 1}, "b": {"node": "R2", "port": 1}}), "unknown node"),
    (lambda d: d["checks"][0].update(device="R9"), "unknown device"),
    (lambda d: d["checks"][0].update(command="configure terminal"), "read-only"),
    (lambda d: d["checks"][0].update(match=["(unclosed"]), "bad regex"),
    (lambda d: d["checks"][0].update(min_success=80), "requires a ping"),
    (lambda d: d["checks"].append(copy.deepcopy(d["checks"][0])), "duplicate check"),
    (lambda d: d["nodes"].append(copy.deepcopy(d["nodes"][0])), "duplicate node"),
    (lambda d: d["links"][0]["a"].update(port=4), "less than 4"),
    (lambda d: d.update(id="Bad ID"), "lowercase"),
]


def _schema_rejects(mutate, msg):
    d = raw()
    mutate(d)
    with pytest.raises(Exception) as ei:
        Lab.model_validate(d)
    assert msg in str(ei.value)


def test_schema_rejects():
    run_table(_schema_rejects, SCHEMA_REJECTS_ROWS)


def test_lab_id_must_match_folder(tmp_path):
    d = tmp_path / "other-name"
    d.mkdir()
    (d / "lab.yaml").write_text((catalog.LABS_DIR / "eigrp-basic" / "lab.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError):
        catalog.load_all(tmp_path)
