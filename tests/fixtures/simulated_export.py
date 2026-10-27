"""TEST FIXTURE - simulated exporter output, NOT produced by Bentley software.

Creates an IFC4X3_ADD2 file that looks like what a generic DGN->IFC export of
the generated DGN could contain, so that export/complete_ifc_structure.py and
validation/validate_ifc.py can be tested without MicroStation:

* every DGN element (incl. spatial carriers and alignment lines) becomes one
  IfcProduct, contained in the single IfcSite
* ``classified=True``: elements get the class from the Bentley 'IFC
  Classification' values (as the exporter is expected to do), carriers of
  project/site/built system stay IfcBuildingElementProxy;
  ``classified=False``: everything is IfcBuildingElementProxy (worst case)
* every Item Type becomes an IfcPropertySet with the Item Type name and
  generically typed values (IfcLabel / IfcReal / IfcBoolean / IfcInteger)
* geometry: triangulated face sets (solids) and polylines, absolute
  coordinates or shifted by ``shift`` (local engineering origin, no map
  conversion) to test the georeferencing repair.

The application name in the header says "SIMULATED" so the file can never be
mistaken for an exporter result.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ifcopenshell  # noqa: E402
import ifcopenshell.guid  # noqa: E402

from common.config import Config  # noqa: E402
from microstation.assign_metadata import bentley_ifc_values, item_values  # noqa: E402
from microstation.dgn_geometry import mesh_for  # noqa: E402
from model.components import DesignModel  # noqa: E402
from model.geom import BoxGeom, MultiGeom, PolylineGeom, ShapeGeom, SweepGeom  # noqa: E402


def _value(f, v):
    if isinstance(v, bool):
        return f.createIfcBoolean(v)
    if isinstance(v, int):
        return f.createIfcInteger(v)
    if isinstance(v, float):
        return f.createIfcReal(v)
    return f.createIfcLabel("" if v is None else str(v))


MS2026_ENUMERATED = {"TrackSupportingStructure", "TrackUsage", "TrackCharacteristic"}


def simulate(cfg: Config, design: DesignModel, path: str, classified: bool = True,
             shift: Tuple[float, float, float] = (0.0, 0.0, 0.0), include_bentley_item: bool = True,
             ms2026_quirks: bool = False) -> str:
    """ms2026_quirks mimics what MicroStation 2026's exporter actually wrote in
    the first real run: enumerated Pset properties as IfcPropertyEnumeratedValue
    with lower-case IFCTIME values, and FILE_NAME originating_system = $."""
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    f.header.file_name.name = os.path.basename(path)
    if not ms2026_quirks:
        f.header.file_name.originating_system = "SIMULATED EXPORT - BU26 test fixture (not Bentley)"
    person = f.createIfcPerson(None, "Test", "Fixture")
    org = f.createIfcOrganization(None, "BU26 tests")
    pao = f.createIfcPersonAndOrganization(person, org)
    app = f.createIfcApplication(org, "0", "SIMULATED EXPORT (test fixture)", "BU26SIM")
    oh = f.createIfcOwnerHistory(pao, app, None, "ADDED", None, None, None, int(time.time()))
    units = f.createIfcUnitAssignment([
        f.createIfcSIUnit(None, "LENGTHUNIT", None, "METRE"), f.createIfcSIUnit(None, "AREAUNIT", None, "SQUARE_METRE"),
        f.createIfcSIUnit(None, "VOLUMEUNIT", None, "CUBIC_METRE"), f.createIfcSIUnit(None, "PLANEANGLEUNIT", None, "RADIAN"),
        f.createIfcSIUnit(None, "MASSUNIT", "KILO", "GRAM")])
    origin = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None)
    ctx = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1e-5, origin, None)
    body = f.createIfcGeometricRepresentationSubContext("Body", "Model", None, None, None, None, ctx, None, "MODEL_VIEW", None)
    axis = f.createIfcGeometricRepresentationSubContext("Axis", "Model", None, None, None, None, ctx, None, "MODEL_VIEW", None)
    project = f.createIfcProject(ifcopenshell.guid.new(), oh, cfg.model["project"]["name"], None, None, None, None, [ctx], units)
    site_pl = f.createIfcLocalPlacement(None, origin)
    site = f.createIfcSite(ifcopenshell.guid.new(), oh, cfg.model["site"]["name"], None, None, site_pl, None, None, "ELEMENT",
                           None, None, None, None, None)
    f.createIfcRelAggregates(ifcopenshell.guid.new(), oh, None, None, project, [site])
    found = {"library": "IFC Classification", "item_type": "IFC Classification",
             "properties": {"version": "Version", "class": "Class", "type": "Type"}} if include_bentley_item else None
    apply_to = cfg.mapping["bentley_ifc_classification"]["apply_to_entities"]
    contained = []
    sx, sy, sz = shift

    def pts(seq):
        return [(p[0] - sx, p[1] - sy, p[2] - sz) for p in seq]

    for comp in design.components:
        g = comp.geometry
        reps = []
        if isinstance(g, (BoxGeom, SweepGeom, MultiGeom)):
            m = mesh_for(g)
            coords = f.createIfcCartesianPointList3D(pts(m.vertices))
            fs = f.createIfcTriangulatedFaceSet(coords, None, True, [tuple(i + 1 for i in t) for t in m.faces], None)
            reps.append(f.createIfcShapeRepresentation(body, "Body", "Tessellation", [fs]))
        elif isinstance(g, (PolylineGeom, ShapeGeom)):
            p3 = pts(g.points) + (pts(g.points[:1]) if isinstance(g, ShapeGeom) else [])
            pl = f.createIfcPolyline([f.createIfcCartesianPoint(p) for p in p3])
            reps.append(f.createIfcShapeRepresentation(axis, "Axis", "Curve3D", [pl]))
        bic = bentley_ifc_values(comp, found, "IFC4X3_ADD2", apply_to)
        ifc_class = comp.ifc_entity if (classified and bic) else "IfcBuildingElementProxy"
        el = f.create_entity(ifc_class, GlobalId=ifcopenshell.guid.new(), OwnerHistory=oh, Name=comp.name,
                             ObjectPlacement=f.createIfcLocalPlacement(site_pl, origin),
                             Representation=f.createIfcProductDefinitionShape(None, None, reps) if reps else None)
        if classified and bic and comp.predefined_type and hasattr(el, "PredefinedType"):
            try:
                el.PredefinedType = comp.predefined_type
            except Exception:
                el.PredefinedType = "USERDEFINED"
                el.ObjectType = comp.predefined_type
        contained.append(el)
        sets = item_values(comp, cfg.mode, cfg.file("landxml"))
        if bic:
            sets.append(("IFC Classification", bic["values"]))
        for set_name, values in sets:
            props = [f.createIfcPropertyEnumeratedValue(k, None, [f.createIfcTime(str(v).lower())], None)
                     if ms2026_quirks and k in MS2026_ENUMERATED else
                     f.createIfcPropertySingleValue(k, None, _value(f, v), None) for k, v in values.items()]
            ps = f.createIfcPropertySet(ifcopenshell.guid.new(), oh, set_name, None, props)
            f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), oh, None, None, [el], ps)
    f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), oh, None, None, contained, site)
    f.write(path)
    return path


if __name__ == "__main__":  # pragma: no cover
    import argparse
    from common.config import load_config
    from model.railway_model import build_design_model
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="preview")
    ap.add_argument("--out", required=True)
    ap.add_argument("--unclassified", action="store_true")
    a = ap.parse_args()
    c = load_config(mode=a.mode)
    print(simulate(c, build_design_model(c), a.out, classified=not a.unclassified))
