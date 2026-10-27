"""Build orchestration with the in-memory RecordingBackend (no MicroStation, no DGN)."""
from microstation.backend import RecordingBackend
from microstation.build_railway_dgn import run
from microstation.create_itemtypes import ITEM_TYPES, MARKER_ITEM_TYPE, check_spec_against_mapping
from validation.validate_dgn import validate


def _build(tmp_path, backend, mode="preview"):
    return run(["--mode", mode, "--dry-run", "--report", str(tmp_path / "r.json")], backend=backend,
               log=lambda *a: None)


def test_item_type_spec_matches_object_mapping(cfg):
    assert check_spec_against_mapping(cfg.mapping) == []


def test_dry_run_creates_all_components(tmp_path):
    be = RecordingBackend()
    rep = _build(tmp_path, be)
    assert rep["errors"] == []
    assert rep["model_check_after_build"]["ok"]
    assert rep["created_total"] == len(be.elements)
    levels = {e.level for e in be.elements}
    assert levels <= set(be.levels)
    # every element carries the marker item type and an object id
    assert all(MARKER_ITEM_TYPE in e.items and e.object_id for e in be.elements)
    # named groups: 6 parts, 2 turnouts, built system
    assert {"BU26_RP-N1", "BU26_RP-VA", "BU26_VXL-A", "BU26_VXL-B", "BU26_BS-1"} <= set(be.groups)
    assert len(be.groups["BU26_BS-1"]) == 6


def test_rerun_does_not_duplicate(tmp_path):
    be = RecordingBackend()
    _build(tmp_path, be)
    n = len(be.elements)
    rep = _build(tmp_path, be)
    assert rep["purged_elements"] == n
    assert len(be.elements) == n
    ids = [e.object_id for e in be.elements]
    assert len(ids) == len(set(ids))


def test_dgn_validation_on_recorded_elements(tmp_path, cfg):
    from common.config import load_config
    from model.railway_model import build_design_model
    be = RecordingBackend()
    _build(tmp_path, be)
    c = load_config(mode="preview")
    rows = be.scan_generated(c.mapping["item_type_library"], MARKER_ITEM_TYPE, ITEM_TYPES)
    res = validate(rows, build_design_model(c), c)
    assert res["ok"], res["issues"][:5]
    # tamper with one value -> detected
    rows[0]["items"]["BU26_Object"]["IfcEntity"] = "IfcBuildingElementProxy"
    assert not validate(rows, build_design_model(c), c)["ok"]


def test_mesh_elements_are_triangulated_and_boxes_native(tmp_path):
    be = RecordingBackend()
    _build(tmp_path, be)
    kinds = {}
    for e in be.elements:
        kinds.setdefault(e.items["BU26_Object"]["ObjectCategory"], set()).add(e.kind)
    assert kinds["SLEEPER"] == {"box"}
    assert kinds["BALLAST"] == {"mesh"} and kinds["RAIL_MAIN"] == {"mesh"}
    assert kinds["ALIGNMENT"] == {"linestring"}
    assert kinds["SPATIAL_RAILWAYPART_PLAIN"] == {"shape"}


def test_probe_runs_on_recording_backend(tmp_path, cfg):
    """The exporter probe (microstation/probe_exporter.py) places every probe
    object and classifies cell children; pick list spelling is applied."""
    from microstation.probe_exporter import Probe
    be = RecordingBackend()
    be.bentley_ifc = {"library": "IFC Classification", "item_type": "IFC Classification",
                      "properties": {"version": "Version", "class": "Class", "type": "Type"},
                      "picklists": {"version": ["IFC2x3", "IFC4x3"], "class": ["IfcRail", "IFCRAILWAYPART"]}}
    rep = Probe(be, cfg, log=lambda *a: None, mapping_out=str(tmp_path / "m.json")).run()
    assert rep["errors"] == []
    assert set(rep["created"]) == {"P%02d" % i for i in range(1, 13)}
    assert rep["created"]["P03"]["read_back"] == ["P03-c1", "P03-c2"]
    assert rep["created"]["P05"]["read_back"] == ["P05-part"]
    cells = [e for e in be.elements if e.kind == "cell"]
    part = next(c for c in cells if c.items["BU26_Probe"]["ProbeId"] == "P03")
    assert part.items["IFC Classification"]["values"] == {"Version": "IFC4x3", "Class": "IFCRAILWAYPART",
                                                          "Type": "PLAINTRACK"}
    assert "class=IfcTrackElement is not in Bentley's pick list" in rep["warnings"]
    assert be.groups["P10 Group"]
    assert '"ProcessGroupingElements": "true"' in open(str(tmp_path / "m.json"), encoding="utf-8").read()
