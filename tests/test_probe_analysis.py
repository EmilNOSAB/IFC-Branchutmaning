"""export/inspect_probe_export.py on hand-made IFC files (not Bentley output)."""
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.api  # noqa: E402

from export.inspect_probe_export import analyse  # noqa: E402


def _probe(f, cls, pid, pdt=None, **kw):
    o = ifcopenshell.api.run("root.create_entity", f, ifc_class=cls, predefined_type=pdt, name=pid)
    ps = ifcopenshell.api.run("pset.add_pset", f, product=o, name="BU26_Probe")
    ifcopenshell.api.run("pset.edit_pset", f, pset=ps, properties={"ProbeId": pid})
    return o


def test_verdicts_follow_the_ifc_structure(tmp_path):
    f = ifcopenshell.api.run("project.create_file", version="IFC4X3_ADD2")
    project = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="P")
    site = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSite", name="S")
    ifcopenshell.api.run("aggregate.assign_object", f, products=[site], relating_object=project)
    rail = _probe(f, "IfcRail", "P01", "RAIL")
    ps = ifcopenshell.api.run("pset.add_pset", f, product=rail, name="Pset_ProbeUnits")
    ps.HasProperties = [f.createIfcPropertySingleValue("LengthWithUnit", None, f.createIfcLengthMeasure(12.5), None)]
    part = _probe(f, "IfcRailwayPart", "P03", "PLAINTRACK")
    ifcopenshell.api.run("aggregate.assign_object", f, products=[part], relating_object=site)
    sleeper = _probe(f, "IfcTrackElement", "P03-c1", "SLEEPER")
    ifcopenshell.api.run("spatial.assign_container", f, products=[sleeper], relating_structure=part)
    proxy = _probe(f, "IfcBuildingElementProxy", "P07")
    ifcopenshell.api.run("spatial.assign_container", f, products=[rail, proxy], relating_structure=site)
    path = str(tmp_path / "probe.ifc")
    f.write(path)
    v = analyse(path)["verdict"]
    assert v["class_from_ifc_classification (P01 IfcRail.RAIL)"]
    assert v["railwaypart_from_cell (P03)"]
    assert v["containment_via_cell, items after add (P03-c1 in P03)"]
    assert v["units_give_measure_types (P01 Pset_ProbeUnits)"]
    assert not v["alignment (P07 IfcAlignment)"]
    assert not v["containment_via_cell, items before add (P04-c1 in P04)"]
    assert not v["classification_reference (P12)"]
