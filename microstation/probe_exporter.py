"""Exporter probe: which DGN constructs does MicroStation's own IFC exporter
turn into the IFC structure the IDS asks for?  (run inside MicroStation)

    python microstation/prepare_dgn.py --out output/probe/BU26_probe.dgn
    (open output/probe/BU26_probe.dgn in MicroStation)
    python load "<repo>\\microstation\\probe_exporter.py"
    File > Export > IFC: IFC 4.3, output/probe/BU26_probe.ifc,
        Schema Mapping File output/probe/SchemaMapping_probe.json
    python export/inspect_probe_export.py

Bentley documents only that the 'IFC Classification' Item Type sets the IFC
class and that Item Types become property sets.  Spatial structure,
containment, aggregation, groups, classification references, measure types
and the vertical datum are not documented for a DGN export, so each candidate
construct is placed once, with a probe id (Item Type BU26_Probe.ProbeId):

  P01 box        IFC Classification IfcRail/RAIL + Pset with unit-carrying values
  P02 shape      IfcRailwayPart/PLAINTRACK (does a classified element become a spatial element?)
  P03 cell       IfcRailwayPart/PLAINTRACK with 2 sleeper boxes as children
                 (items attached to the children after the cell is in the model)
  P04 cell       IfcRailwayPart/PLAINTRACK, children classified BEFORE they are added to the cell
  P05 cell       IfcRailway > cell IfcRailwayPart/TURNOUTTRACK > box IfcRail/STOCKRAIL (nested)
  P06 cell       IfcElementAssembly/TRACTION_SWITCHING_ASSEMBLY with 2 unclassified children
  P07 line       IfcAlignment + Pset_Stationing
  P08 box        IfcSpatialZone/CONSTRUCTION
  P09 line       IfcBuiltSystem/RAILWAYTRACK
  P10 group      named group with P01 and P08 (ProcessGroupingElements=true in the probe mapping)
  P11 box        IfcCourse/BALLASTBED + Qto_CourseBaseQuantities with units (IfcElementQuantity?)
  P12 box        Item Types shaped like a classification reference (speculative)
  GCS            EPSG 5850 (SWEREF 99 18 00 + RH 2000) if the GCS library accepts it

Writes output/probe/probe_report.json (what was created and every API
failure).  Nothing here is used by the production build until the probe
export shows that a construct works.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_config, repo_path  # noqa: E402
from export.build_schema_mapping import loads_jsonc  # noqa: E402
from microstation.assign_metadata import match_picklist  # noqa: E402

PROBE_LIBRARY = "BU26_PROBE"
PROBE_ITEM_TYPES = {
    "BU26_Probe": [("ProbeId", "String"), ("Note", "String")],
    "Pset_ProbeUnits": [("LengthWithUnit", "Double"), ("AreaWithUnit", "Double"), ("VolumeWithUnit", "Double"),
                        ("VoltageWithUnit", "Double"), ("PowerWithUnit", "Double"), ("PlainDouble", "Double"),
                        ("Label", "String"), ("Flag", "Boolean"), ("Count", "Integer")],
    "Pset_Stationing": [("Station", "Double"), ("HasIncreasingStation", "Boolean")],
    "Qto_CourseBaseQuantities": [("Length", "Double"), ("Width", "Double"), ("Thickness", "Double"),
                                 ("Volume", "Double"), ("GrossVolume", "Double"), ("Weight", "Double")],
    # speculative shapes of a classification reference
    "IfcClassificationReference": [("Identification", "String"), ("Name", "String"), ("ReferencedSource", "String")],
    "Classification": [("System", "String"), ("Code", "String"), ("Name", "String")],
}
PROBE_UNITS = {
    ("Pset_ProbeUnits", "LengthWithUnit"): "IfcLengthMeasure",
    ("Pset_ProbeUnits", "AreaWithUnit"): "IfcAreaMeasure",
    ("Pset_ProbeUnits", "VolumeWithUnit"): "IfcVolumeMeasure",
    ("Pset_ProbeUnits", "VoltageWithUnit"): "IfcElectricVoltageMeasure",
    ("Pset_ProbeUnits", "PowerWithUnit"): "IfcPowerMeasure",
    ("Pset_Stationing", "Station"): "IfcLengthMeasure",
    ("Qto_CourseBaseQuantities", "Length"): "IfcQuantityLength",
    ("Qto_CourseBaseQuantities", "Width"): "IfcQuantityLength",
    ("Qto_CourseBaseQuantities", "Thickness"): "IfcQuantityLength",
    ("Qto_CourseBaseQuantities", "Volume"): "IfcQuantityVolume",
    ("Qto_CourseBaseQuantities", "GrossVolume"): "IfcQuantityVolume",
    ("Qto_CourseBaseQuantities", "Weight"): "IfcQuantityWeight",
}
UNIT_VALUES = {"LengthWithUnit": 12.5, "AreaWithUnit": 7.25, "VolumeWithUnit": 3.125, "VoltageWithUnit": 400.0,
               "PowerWithUnit": 1200.0, "PlainDouble": 1.5, "Label": "SUBGRADELAYER", "Flag": True, "Count": 3}


class Probe:
    def __init__(self, backend, cfg, log=print, mapping_out: str = ""):
        self.be = backend
        self.cfg = cfg
        self.mapping_out = mapping_out
        self.log = log
        self.report = {"created": {}, "errors": [], "warnings": []}
        self.bic = None
        self.level = None

    # ------------------------------------------------------------ helpers
    def _classify(self, entity, pdt):
        if not self.bic:
            return None
        props, lists = self.bic["properties"], self.bic.get("picklists", {})
        values = {}
        version = self.cfg.mapping["bentley_ifc_classification"].get("version_value", "IFC4X3_ADD2")
        for role, wanted in (("version", version), ("class", entity), ("type", pdt)):
            if role in props and wanted:
                v, ok = match_picklist(wanted, lists.get(role), role)
                values[props[role]] = v
                if not ok:
                    self.report["warnings"].append("%s=%s is not in Bentley's pick list" % (role, wanted))
        return {"library": self.bic["library"], "item_type": self.bic["item_type"], "values": values}

    def _items(self, pid, extra=None):
        items = [("BU26_Probe", {"ProbeId": pid, "Note": "exporter probe"})]
        return items + list(extra or [])

    def attach(self, el, pid, entity=None, pdt=None, extra=None):
        self.be.attach_items(el, PROBE_LIBRARY, self._items(pid, extra), self._classify(entity, pdt) if entity else None)

    def try_attach(self, el, pid, entity=None, pdt=None, extra=None):
        """attach() that reports instead of raising (used on cell children)."""
        try:
            self.attach(el, pid, entity, pdt, extra)
            return "ok"
        except Exception as e:
            self.report["errors"].append("%s: %s: %s" % (pid, type(e).__name__, e))
            return "FAILED: %s" % e

    def read_back_children(self, cell):
        ids = []
        self.be.for_each_cell_child(cell, lambda i, ch: ids.append(
            self.be.get_item_value(ch, PROBE_LIBRARY, "BU26_Probe", "ProbeId")))
        return ids

    def box(self, x, y, z, sx=2.0, sy=0.5, sz=0.3, hold=False):
        self.be.hold_elements = hold
        try:
            return self.be.add_box((x, y, z), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), sx, sy, sz, self.level, 3, 0)
        finally:
            self.be.hold_elements = False

    def step(self, pid, fn):
        try:
            self.report["created"][pid] = fn() or "ok"
            self.log("  %s ok" % pid)
        except Exception as e:
            self.report["created"][pid] = "FAILED"
            self.report["errors"].append("%s: %s: %s" % (pid, type(e).__name__, e))
            self.report.setdefault("tracebacks", {})[pid] = traceback.format_exc().splitlines()[-6:]
            self.log("  %s FEL: %s" % (pid, e))

    # ------------------------------------------------------------- probes
    def run(self):
        be, cfg = self.be, self.cfg
        self.report["coordinate_system"] = be.set_coordinate_system(cfg.model["coordinate_system"])
        self.level = be.ensure_levels({"BU26_PROBE": {"description": "BU26 exporter probe"}})["BU26_PROBE"]
        self.report["item_types"] = be.ensure_item_types(PROBE_LIBRARY, PROBE_ITEM_TYPES, PROBE_UNITS,
                                                         cfg.mapping.get("item_type_units"))
        self.bic, self.report["bentley_ifc_classification_import"] = be.ensure_bentley_ifc_classification(
            cfg.mapping["bentley_ifc_classification"])
        self.report["bentley_ifc_classification"] = self.bic or "NOT AVAILABLE"
        if not self.bic:
            self.report["errors"].append("IFC Classification not available - class probes are meaningless")
        x0, y0, z0 = self._origin()
        units = [("Pset_ProbeUnits", dict(UNIT_VALUES))]

        def p01():
            el = self.box(x0, y0, z0)
            self.attach(el, "P01", "IfcRail", "RAIL", units)
        self.step("P01", p01)

        def p02():
            pts = [(x0, y0 + 5, z0), (x0 + 10, y0 + 5, z0), (x0 + 10, y0 + 8, z0), (x0, y0 + 8, z0)]
            el = be.add_shape(pts, self.level, 4, 0)
            self.attach(el, "P02", "IfcRailwayPart", "PLAINTRACK")
        self.step("P02", p02)

        def p03():
            kids = [self.box(x0 + 20 + 3 * i, y0, z0, 0.3, 2.6, 0.22, hold=True) for i in range(2)]
            cell = be.add_cell("P03 RailwayPart", kids, self.level)
            self.attach(cell, "P03", "IfcRailwayPart", "PLAINTRACK")
            res = []
            n = be.for_each_cell_child(cell, lambda i, ch: res.append(
                self.try_attach(ch, "P03-c%d" % (i + 1), "IfcTrackElement", "SLEEPER")))
            return {"children": n, "attach": res, "read_back": self.read_back_children(cell)}
        self.step("P03", p03)

        def p04():
            kids, res = [], []
            for i in range(2):
                ch = self.box(x0 + 30 + 3 * i, y0, z0, 0.3, 2.6, 0.22, hold=True)
                res.append(self.try_attach(ch, "P04-c%d" % (i + 1), "IfcTrackElement", "SLEEPER"))
                kids.append(ch)
            cell = be.add_cell("P04 RailwayPart", kids, self.level)
            self.attach(cell, "P04", "IfcRailwayPart", "PLAINTRACK")
            return {"attach_before_add": res, "read_back": self.read_back_children(cell)}
        self.step("P04", p04)

        def p05():
            rail = self.box(x0 + 40, y0, z0, 6.0, 0.07, 0.17, hold=True)
            res = [self.try_attach(rail, "P05-rail", "IfcRail", "STOCKRAIL")]
            part = be.add_cell("P05 RailwayPart", [rail], self.level, add=False)
            res.append(self.try_attach(part, "P05-part", "IfcRailwayPart", "TURNOUTTRACK"))
            railway = be.add_cell("P05 Railway", [part], self.level)
            self.attach(railway, "P05", "IfcRailway", "USERDEFINED")
            return {"attach_before_add": res, "read_back": self.read_back_children(railway)}
        self.step("P05", p05)

        def p06():
            kids = [self.box(x0 + 50, y0 + 3 * i, z0, 1.0, 0.4, 0.3, hold=True) for i in range(2)]
            cell = be.add_cell("P06 Assembly", kids, self.level)
            self.attach(cell, "P06", "IfcElementAssembly", "TRACTION_SWITCHING_ASSEMBLY")
        self.step("P06", p06)

        def p07():
            pts = [(x0 + 60 + i, y0 + 0.1 * i * i, z0) for i in range(11)]
            el = be.add_linestring(pts, self.level, 1, 2)
            self.attach(el, "P07", "IfcAlignment", "USERDEFINED",
                        [("Pset_Stationing", {"Station": 6950.0, "HasIncreasingStation": True})])
        self.step("P07", p07)

        def p08():
            el = self.box(x0 + 75, y0, z0, 4.0, 4.0, 0.1)
            self.attach(el, "P08", "IfcSpatialZone", "CONSTRUCTION")
            return {"element_id": be.element_id(el)}
        self.step("P08", p08)

        def p09():
            el = be.add_linestring([(x0 + 85, y0, z0), (x0 + 86, y0, z0)], self.level, 1, 0)
            self.attach(el, "P09", "IfcBuiltSystem", "RAILWAYTRACK")
        self.step("P09", p09)

        def p11():
            el = self.box(x0 + 95, y0, z0, 10.0, 3.0, 0.5)
            self.attach(el, "P11", "IfcCourse", "BALLASTBED", [("Qto_CourseBaseQuantities", {
                "Length": 10.0, "Width": 3.0, "Thickness": 0.5, "Volume": 15.0, "GrossVolume": 15.0,
                "Weight": 27000.0})])
            return {"element_id": be.element_id(el)}
        self.step("P11", p11)

        def p12():
            el = self.box(x0 + 110, y0, z0)
            self.attach(el, "P12", "IfcRail", "RAIL", [
                ("IfcClassificationReference", {"Identification": "WRA20", "Name": "Räl",
                                                "ReferencedSource": "CoClass_KO"}),
                ("Classification", {"System": "CoClass_KO", "Code": "WRA20", "Name": "Räl"})])
        self.step("P12", p12)

        def p10():
            ids = []
            for pid in ("P08", "P11"):
                info = self.report["created"].get(pid)
                if isinstance(info, dict) and "element_id" in info:
                    ids.append(info["element_id"])
            be.create_named_group("P10 Group", "BU26 probe: named group as IfcGroup?", ids)
            return {"members": ids}
        self.step("P10", p10)
        self.report["schema_mapping"] = write_probe_mapping(cfg, self.mapping_out)
        be.save()
        return self.report

    def _origin(self):
        from geometry.landxml_reader import read_landxml
        doc = read_landxml(self.cfg.file("landxml"))
        st = doc.alignments[0].elements[0].start
        return st.x + 30.0, st.y + 30.0, 10.0


def write_probe_mapping(cfg, out: str = "") -> str:
    """export/SchemaMapping.json with ProcessGroupingElements = true."""
    with open(cfg.file("schema_mapping"), encoding="utf-8") as fh:
        doc = loads_jsonc(fh.read())
    doc.setdefault("GlobalVariables", {})["ProcessGroupingElements"] = "true"
    out = out or repo_path("output/probe/SchemaMapping_probe.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("/* BU26 exporter probe: export/SchemaMapping.json with ProcessGroupingElements = true */\n")
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    return out


def main():
    from microstation.msapi import MICROSTATION_AVAILABLE, IMPORT_ERROR, MicroStationBackend
    if not MICROSTATION_AVAILABLE:
        raise SystemExit("Run inside MicroStation (%s)" % IMPORT_ERROR)
    cfg = load_config(mode="preview")
    be = MicroStationBackend()
    name = str(be.dgn_file.GetFileName())
    if os.path.normcase(os.path.abspath(name)) == os.path.normcase(os.path.abspath(cfg.file("dgn_output"))):
        raise SystemExit("The active file is the production DGN - open output/probe/BU26_probe.dgn instead")
    rep = Probe(be, cfg).run()
    out = repo_path("output/probe/probe_report.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, default=str)
    print("Probe-rapport: %s (fel: %d)" % (out, len(rep["errors"])))
    print("Exportera nu: File > Export > IFC, IFC 4.3, utfil output\\probe\\BU26_probe.ifc, "
          "Schema Mapping File %s" % rep["schema_mapping"])


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print("AVBRUTET: %s" % e)
    except Exception:
        traceback.print_exc()
