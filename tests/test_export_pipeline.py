"""Export side: SchemaMapping builder, IFC post step and IDS validation on a
SIMULATED export (tests/fixtures/simulated_export.py - not Bentley output)."""
import json
import os

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("ifctester")

from common.config import REPO_ROOT, load_config  # noqa: E402
from export.build_schema_mapping import loads_jsonc, merge  # noqa: E402
from export.complete_ifc_structure import Completer  # noqa: E402
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


def _run(tmp_path, preview, **kw):
    cfg, design = preview
    raw = str(tmp_path / "raw.ifc")
    simulate(cfg, design, raw, **kw)
    f = ifcopenshell.open(raw)
    result = Completer(f, cfg, log=lambda *a: None).run()
    out = str(tmp_path / "completed.ifc")
    f.write(out)
    return raw, out, result


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
    assert "IfcBuiltSystem" not in rep["class_entries_added"] and "IfcProject" not in rep["class_entries_added"]
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


@pytest.mark.parametrize("classified,shift", [(True, (0.0, 0.0, 0.0)), (False, (132000.0, 6617000.0, 5.0))])
def test_post_step_reaches_all_satisfiable_specs(tmp_path, preview, classified, shift):
    raw, out, result = _run(tmp_path, preview, classified=classified, shift=shift,
                            include_bentley_item=classified)
    assert result["problems"] == []
    assert result["bu26_objects_still_proxy"] == []
    assert tuple(result["offset_model_to_map"]) == pytest.approx(shift, abs=1e-3)
    r = validate(out, IDS)
    assert set(r["failed_specs"]) == CONFLICT_SPECS
    assert set(r["failed_specs_only_due_to_ids_conflicts"]) == CONFLICT_SPECS
    st = r["structure"]
    assert st["proxies"] == 0 and st["projects"] == 1 and st["railway_parts_ok"]
    assert st["elements_without_spatial_relation"] == 0
    assert st["built_systems"][0]["members"] == 6
    assert st["schema_validation_issues"] == 0
    assert st["map_conversion"][0]["eastings"] == pytest.approx(shift[0])
    assert {"Qto_CourseBaseQuantities", "Qto_SleeperBaseQuantities"} <= set(st["element_quantities"])


def test_alignment_geometry_in_model_coordinates(tmp_path, preview):
    import ifcopenshell.geom
    import numpy as np
    from geometry.landxml_reader import read_landxml
    shift = (132000.0, 6617000.0, 5.0)
    _, out, _ = _run(tmp_path, preview, classified=True, shift=shift)
    f = ifcopenshell.open(out)
    doc = read_landxml(load_config().file("landxml"))
    s = ifcopenshell.geom.settings()
    for a in f.by_type("IfcAlignment"):
        lx = doc.alignment(a.Name)
        axis = next(r for r in a.Representation.Representations if r.RepresentationIdentifier == "Axis")
        v = np.array(ifcopenshell.geom.create_shape(s, axis.Items[0]).verts).reshape(-1, 3)
        st, en = lx.elements[0].start, lx.elements[-1].end
        assert np.allclose(v[0][:2], (st.x - shift[0], st.y - shift[1]), atol=2e-3)
        assert np.allclose(v[-1][:2], (en.x - shift[0], en.y - shift[1]), atol=2e-3)
        assert abs(v[0][2] - (lx.profile[0].elevation - shift[2])) < 2e-3


def test_post_step_relations_and_types(tmp_path, preview):
    import ifcopenshell.util.element as ue
    _, out, _ = _run(tmp_path, preview, classified=False, shift=(0.0, 0.0, 0.0), include_bentley_item=False)
    f = ifcopenshell.open(out)
    asm = f.by_type("IfcElementAssembly")
    assert len(asm) == 2
    for a in asm:
        parent = ue.get_aggregate(a)
        assert parent.is_a("IfcRailwayPart") and parent.PredefinedType == "TURNOUTTRACK"
        assert ue.get_container(a) is None
        pset = ue.get_psets(a)["Pset_ElementAssemblyTypeTractionSwitchingAssembly"]
        assert pset["RatedVoltage"] == 400.0 and pset["NominalPower"] == 1200.0
    site = f.by_type("IfcSite")[0]
    assert site.RefLatitude[0] == 59 and site.RefLongitude[0] == 17
    rw = f.by_type("IfcRailway")[0]
    assert ue.get_aggregate(rw) == site and rw.PredefinedType == "USERDEFINED" and rw.ObjectType
    for al in f.by_type("IfcAlignment"):
        assert ue.get_aggregate(al).is_a("IfcProject")
        assert al.OwnerHistory is not None and al.Description
    # typed values
    for pv in f.by_type("IfcPropertySingleValue"):
        if pv.Name == "TrackNumber":
            assert pv.NominalValue.is_a("IfcIdentifier")
        if pv.Name == "GrossPlannedArea":
            assert pv.NominalValue.is_a("IfcAreaMeasure")
    for q in f.by_type("IfcQuantityWeight"):
        assert q.Name == "Weight" and q.WeightValue > 0
