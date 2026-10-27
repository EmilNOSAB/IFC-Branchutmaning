"""Export side: SchemaMapping builder, export analysis and IDS validation on a
SIMULATED export (tests/fixtures/simulated_export.py - not Bentley output).
The exported IFC is the deliverable; nothing here modifies an export."""
import json
import os

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("ifctester")

from common.config import REPO_ROOT, load_config  # noqa: E402
from export.build_schema_mapping import loads_jsonc, merge  # noqa: E402
from export.inspect_bentley_export import analyse  # noqa: E402
from model.railway_model import build_design_model  # noqa: E402
from tests.fixtures.simulated_export import simulate  # noqa: E402
from validation.ids_conflicts import find_conflicts, parse  # noqa: E402
from validation.validate_ifc import validate  # noqa: E402

IDS = os.path.join(REPO_ROOT, "input", "Branschutmaningen_2026.ids")
CONFLICT_SPECS = {"#7 IfcRail.RAIL", "#9 IfcTrackElement.SLEEPER", "#10 IfcRail.RAIL", "#16 IfcRail.RAIL",
                  "#17 IfcTrackElement.SLEEPER"}


@pytest.fixture(scope="module")
def preview():
    cfg = load_config(mode="preview")
    return cfg, build_design_model(cfg)


def test_committed_schema_mapping_is_valid_jsonc():
    text = open(os.path.join(REPO_ROOT, "export", "SchemaMapping.json"), encoding="utf-8").read()
    doc = loads_jsonc(text)
    assert set(doc) == {"GlobalVariables", "ProjectConfigurations"}
    assert all(v in ("true", "false") for v in doc["GlobalVariables"].values())
    assert doc["ProjectConfigurations"]["ProjectName"] == load_config().model["project"]["name"]


def test_schema_mapping_merge_keeps_template_and_appends_dynamic_classes():
    template = loads_jsonc("""/* t */ {"GlobalVariables": {"ProcessEmptyProperties": "true"},
        "X": {"L": [ {"Class": ["IFCDynamic", "IfcElementAssembly", "IfcElementAssembly"], "Extra": 1},
                     {"Class": ["Other", "A", "IfcWall"]} ]}, "Untouched": [1, 2]}""")
    doc, rep = merge(template, load_config())
    assert doc["Untouched"] == [1, 2]
    assert doc["GlobalVariables"]["ProcessEmptyProperties"] == "false"
    classes = [tuple(e["Class"]) for e in doc["X"]["L"]]
    assert ("IFCDynamic", "IfcRail", "IfcRail") in classes
    assert classes.count(("IFCDynamic", "IfcElementAssembly", "IfcElementAssembly")) == 1  # not duplicated
    assert "IfcBuiltSystem" in rep["class_entries_added"] and "IfcProject" not in rep["class_entries_added"]
    assert all(e.get("Extra") == 1 for e in doc["X"]["L"] if e["Class"][0] == "IFCDynamic")


def test_merge_without_dynamic_list_adds_nothing():
    doc, rep = merge({"A": [{"Class": ["S", "C", "IfcWall"]}]}, load_config())
    assert rep["class_entries_added"] == [] and rep["notes"]


def test_ids_static_conflicts():
    pairs = {(c["spec_a"], c["spec_b"]) for c in find_conflicts(parse(IDS))}
    assert pairs == {("#7 IfcRail.RAIL", "#10 IfcRail.RAIL"), ("#7 IfcRail.RAIL", "#16 IfcRail.RAIL"),
                     ("#9 IfcTrackElement.SLEEPER", "#17 IfcTrackElement.SLEEPER"),
                     ("#10 IfcRail.RAIL", "#16 IfcRail.RAIL")}


def test_raw_simulated_export_fails_most_specs(tmp_path, preview):
    cfg, design = preview
    raw = str(tmp_path / "raw.ifc")
    simulate(cfg, design, raw)
    r = validate(raw, IDS)
    assert r["passed"] <= 2


def test_analysis_lists_what_the_export_lacks(tmp_path, preview):
    cfg, design = preview
    raw = str(tmp_path / "raw.ifc")
    simulate(cfg, design, raw, classified=False, include_bentley_item=False)
    a = analyse(raw)
    assert a["product_counts"].get("IfcBuildingElementProxy", 0) == len(design.components)
    assert {"classes", "railway_parts", "containment_in_parts", "built_system_group",
            "classification", "alignments"} <= set(a["missing_in_export"])


def test_classified_export_is_validated_as_is(tmp_path, preview):
    """With classes from Bentley's IFC Classification but no spatial relations,
    the validator reports exactly that and does not touch the file."""
    cfg, design = preview
    raw = str(tmp_path / "raw.ifc")
    simulate(cfg, design, raw, classified=True)
    before = open(raw, "rb").read()
    r = validate(raw, IDS)
    assert open(raw, "rb").read() == before
    assert r["structure"]["proxies"] < len(design.components)
    assert "#7 IfcRail.RAIL" in r["failed_specs"]
