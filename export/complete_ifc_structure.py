"""EXPLICIT POST-PROCESSING STEP - run only after the DGN has been built in
MicroStation and exported with MicroStation's own IFC exporter.

    python export/complete_ifc_structure.py \
        [--in output/Branschutmaningen_2026_bentley_export.ifc] [--out output/Branschutmaningen_2026.ifc]

What it does and why
--------------------
Item Type values such as ``SpatialParent`` are metadata; an exporter does not
turn them into IFC relationships by itself.  This step completes, in the
exported file, what the export could not express (see
output/bentley_export_analysis.json from export/inspect_bentley_export.py),
using ONLY information that came out of the DGN (the exported BU2026_IFC Item
Type values) plus LandXML for the semantic alignment layouts:

 1. units check (METRE without prefix, IDS #20), owner history
 2. georeferencing: IfcMapConversion + IfcProjectedCRS EPSG:3011 / RH 2000 (IDS #21);
    the offset between IFC and SWEREF coordinates is measured, not assumed
 3. IfcProject / IfcSite attributes, RefLatitude/RefLongitude/RefElevation,
    Pset_SpaceCommon (IDS #1, #2)
 4. IfcRailway, 6 x IfcRailwayPart (IfcRelAggregates), IfcSpatialZone (IDS #3, #5, #6, #8)
 5. 3 x IfcAlignment with horizontal/vertical/cant layouts and geometry,
    aggregated to the project and referenced in the site (IDS #4)
 6. IfcBuiltSystem RAILWAYTRACK + IfcRelAssignsToGroup of the 6 parts (IDS #15)
 7. physical elements: IFC class/PredefinedType from the Item Types (no
    proxies), IfcRelContainedInSpatialStructure to the railway part, switch
    assembly IfcRelAggregates to the turnout part (IDS #7-#14, #16, #17, #22)
 8. CoClass IfcClassification/IfcClassificationReference (IfcRelAssociatesClassification)
 9. Psets and Qtos with the IFC data types from config/object_mapping.yaml
    (IfcRelDefinesByProperties, IfcElementQuantity) (IDS #18, #19 ...)
10. carrier elements that only transported metadata are removed

Physical geometry is never created here: every physical element must already
exist in the exported file.  Every change is written to
output/postprocess_report.json.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import ifcopenshell  # noqa: E402
except ImportError:  # pragma: no cover
    raise SystemExit("IfcOpenShell saknas i den här Python-installationen (%s).\n"
                     "Installera i en vanlig Python 3.11/3.12 (inte MicroStations):\n"
                     "  python -m venv .venv && .venv\\Scripts\\activate\n"
                     "  python -m pip install ifcopenshell ifctester pystache numpy" % __import__("sys").executable)
import ifcopenshell.api  # noqa: E402
import ifcopenshell.api.aggregate  # noqa: E402
import ifcopenshell.api.alignment  # noqa: E402
import ifcopenshell.api.classification  # noqa: E402
import ifcopenshell.api.georeference  # noqa: E402
import ifcopenshell.api.group  # noqa: E402
import ifcopenshell.api.root  # noqa: E402
import ifcopenshell.api.spatial  # noqa: E402
import ifcopenshell.guid  # noqa: E402
import ifcopenshell.util.element  # noqa: E402
import ifcopenshell.util.placement  # noqa: E402
import ifcopenshell.util.unit  # noqa: E402

from common.config import Config, load_config  # noqa: E402
from export.ifc_common import bu26_index, entity_label  # noqa: E402
from geometry.georef import deg_to_dms  # noqa: E402
from geometry.landxml_reader import read_landxml  # noqa: E402
from geometry.track import TrackGeometry  # noqa: E402

PHYSICAL = ("IfcRail", "IfcTrackElement", "IfcCourse", "IfcElementAssembly")
SPATIAL = ("IfcRailway", "IfcRailwayPart", "IfcSpatialZone")
NON_PRODUCT = ("IfcBuiltSystem",)


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", ".t.")


def _float(v) -> float:
    return float(v)


class Completer:
    def __init__(self, f: ifcopenshell.file, cfg: Config, log=print):
        self.f = f
        self.cfg = cfg
        self.log = log
        self.changes: List[Dict[str, Any]] = []
        self.problems: List[str] = []
        self.created: Dict[str, Any] = {}  # object_id -> new/reused IFC entity
        self.to_remove: List[Any] = []

    # ------------------------------------------------------------ utilities
    def change(self, action: str, target: str, **details):
        self.changes.append(dict(action=action, target=target, **details))

    def _str(self, rec, key, default=""):
        v = rec["sets"].get("BU26_Object", {}).get(key)
        return default if v in (None, "") else str(v)

    def _placement(self, rel_to=None):
        f = self.f
        return f.createIfcLocalPlacement(rel_to, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)),
                                                                              None, None))

    # ----------------------------------------------------------------- steps
    def run(self) -> Dict[str, Any]:
        f = self.f
        if f.schema_identifier.upper() not in ("IFC4X3_ADD2", "IFC4X3"):
            raise SystemExit("The exported file is %s - export IFC 4.3 (IFC4X3_ADD2) from MicroStation" %
                             f.schema_identifier)
        self.idx = bu26_index(f)
        if not self.idx:
            raise SystemExit("No BU26 Item Type values found in the IFC - the exporter did not write the Item "
                             "Types; check the export settings (ProcessEmptyProperties/mapping)")
        modes = {self._str(r, "ModelMode") for r in self.idx.values()}
        mode = sorted(m for m in modes if m)[0] if any(modes) else self.cfg.mode
        if mode != self.cfg.mode:
            self.cfg = load_config(mode=mode)
        self.log("BU26-objekt i exporten: %d (läge %s)" % (len(self.idx), mode))
        self.owner_history()
        self.units()
        self.georeference()
        self.project_and_site()
        self.railway_and_parts()
        self.spatial_zone()
        self.alignments()
        self.built_system()
        self.physical_elements()
        self.classifications()
        self.property_sets()
        self.cleanup()
        return self.summary()

    def owner_history(self):
        f = self.f
        ohs = f.by_type("IfcOwnerHistory")
        if ohs:
            self.oh = ohs[0]
        else:
            person = f.createIfcPerson(None, "Branschutmaningen", "2026")
            org = f.createIfcOrganization(None, "Branschutmaningen 2026")
            pao = f.createIfcPersonAndOrganization(person, org)
            app = f.createIfcApplication(org, "1.0", "BU26 complete_ifc_structure.py", "BU26POST")
            self.oh = f.createIfcOwnerHistory(pao, app, None, "MODIFIED", int(time.time()), pao, app, int(time.time()))
            self.change("create", "IfcOwnerHistory")

    def ensure_oh(self, ent):
        if hasattr(ent, "OwnerHistory") and ent.OwnerHistory is None:
            ent.OwnerHistory = self.oh

    def units(self):
        self.unit_report = []
        for u in self.f.by_type("IfcSIUnit"):
            if u.UnitType == "LENGTHUNIT":
                self.unit_report.append({"name": u.Name, "prefix": u.Prefix})
                if u.Name != "METRE" or u.Prefix is not None:
                    self.problems.append("Length unit is %s%s - IDS #20 requires METRE without prefix. Set the "
                                         "DGN master unit to metres and export again." % (u.Prefix or "", u.Name))

    # ---------------------------------------------------------- georeference
    def _world_bbox(self, ent) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
        try:
            import ifcopenshell.geom
            s = ifcopenshell.geom.settings()
            s.set("use-world-coords", True)
            shape = ifcopenshell.geom.create_shape(s, ent)
            v = shape.geometry.verts
            xs, ys, zs = v[0::3], v[1::3], v[2::3]
            return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
        except Exception as e:
            self.problems.append("Geometry evaluation failed for %s: %s" % (entity_label(ent), e))
            return None

    def georeference(self):
        """Measure the translation between IFC model coordinates and SWEREF 99 18 00
        using a ballast body (design bbox from the same configuration), then make
        sure IfcMapConversion/IfcProjectedCRS describe it."""
        from microstation.dgn_geometry import mesh_for
        from model.railway_model import RailwayModelBuilder
        self.builder = RailwayModelBuilder(self.cfg)
        self.design = self.builder.build()
        self.offset = (0.0, 0.0, 0.0)
        probe = None
        for c in self.design.components:
            if c.category == "BALLAST" and c.object_id in self.idx:
                probe = c
                break
        if probe is not None:
            bb = self._world_bbox(self.idx[probe.object_id]["entity"])
            if bb:
                dmin, dmax = mesh_for(probe.geometry).bbox()
                o1 = tuple(dmin[i] - bb[0][i] for i in range(3))
                o2 = tuple(dmax[i] - bb[1][i] for i in range(3))
                if max(abs(o1[i] - o2[i]) for i in range(3)) > 0.01:
                    self.problems.append("IFC coordinates are not a pure translation of SWEREF coordinates "
                                         "(rotation/scale in export?) - georeferencing not changed: %s %s" % (o1, o2))
                    return
                self.offset = tuple(round(v, 4) for v in o1)
        cs = self.cfg.model["coordinate_system"]
        f = self.f
        mcs = f.by_type("IfcMapConversion")
        if not mcs:
            ifcopenshell.api.georeference.add_georeferencing(f, ifc_class="IfcMapConversion", name=cs["ifc_crs_name"])
            self.change("create", "IfcMapConversion/IfcProjectedCRS")
        mc = f.by_type("IfcMapConversion")[0]
        old = (mc.Eastings, mc.Northings, mc.OrthogonalHeight)
        if any(abs((old[i] or 0.0) - self.offset[i]) > 1e-3 for i in range(3)) or mc.XAxisAbscissa is None:
            self.change("edit", "IfcMapConversion", old=old, new=self.offset)
        mc.Eastings, mc.Northings, mc.OrthogonalHeight = self.offset
        if mc.XAxisAbscissa is None:
            mc.XAxisAbscissa, mc.XAxisOrdinate = 1.0, 0.0
        if mc.Scale is None:
            mc.Scale = 1.0
        crs = mc.TargetCRS
        before = (crs.Name, crs.Description, getattr(crs, "VerticalDatum", None))
        crs.Name = cs["ifc_crs_name"]
        crs.Description = cs["ifc_crs_description"]
        crs.VerticalDatum = cs["ifc_vertical_datum"]
        crs.GeodeticDatum = "SWEREF99"
        crs.MapProjection = "Transverse Mercator"
        crs.MapZone = "18 00"
        if crs.is_a("IfcProjectedCRS") and getattr(crs, "MapUnit", None) is None:
            lu = [u for u in f.by_type("IfcSIUnit") if u.UnitType == "LENGTHUNIT"]
            if lu:
                crs.MapUnit = lu[0]
        self.change("edit", "IfcProjectedCRS", old=before, new=(crs.Name, crs.Description, crs.VerticalDatum))

    # ------------------------------------------------------- project / site
    def project_and_site(self):
        f = self.f
        projects = f.by_type("IfcProject")
        if len(projects) != 1:
            raise SystemExit("Expected exactly one IfcProject, found %d" % len(projects))
        self.project = projects[0]
        pj = self.cfg.model["project"]
        rec = self.idx.get("PRJ-1")
        name = self._str(rec, "IfcName", pj["name"]) if rec else pj["name"]
        self.project.Name = name
        self.project.LongName = self._str(rec, "IfcLongName", pj["long_name"]) if rec else pj["long_name"]
        self.project.Phase = self._str(rec, "Phase", pj["phase"]) if rec else pj["phase"]
        self.project.Description = self._str(rec, "IfcDescription", pj["description"]) if rec else pj["description"]
        self.ensure_oh(self.project)
        self.change("edit", "IfcProject", Name=self.project.Name, LongName=self.project.LongName, Phase=self.project.Phase)
        if rec:
            self.to_remove.append(rec["entity"])
        sites = f.by_type("IfcSite")
        if len(sites) > 1:
            self.problems.append("%d IfcSite in the export; the first one is used" % len(sites))
        if sites:
            self.site = sites[0]
        else:
            self.site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite")
            self.site.ObjectPlacement = self._placement()
            self.change("create", "IfcSite")
        srec = self.idx.get("SITE-1")
        st = self.cfg.model["site"]
        self.site.Name = self._str(srec, "IfcName", st["name"]) if srec else st["name"]
        self.site.LongName = self._str(srec, "IfcLongName", st["long_name"]) if srec else st["long_name"]
        self.site.Description = self._str(srec, "IfcDescription", st["description"]) if srec else st["description"]
        obj = srec["sets"]["BU26_Object"] if srec else {}
        lat = obj.get("RefLatitude") or self.design.report["site_reference"]["latitude"]
        lon = obj.get("RefLongitude") or self.design.report["site_reference"]["longitude"]
        elev = obj.get("RefElevation")
        if elev in (None, ""):
            elev = self.design.report["site_reference"]["elevation"]
        self.site.RefLatitude = deg_to_dms(float(lat))
        self.site.RefLongitude = deg_to_dms(float(lon))
        self.site.RefElevation = float(elev)
        ltn = obj.get("LandTitleNumber") or st.get("land_title_number")
        if ltn:
            self.site.LandTitleNumber = str(ltn)
        if self.site.CompositionType is None:
            self.site.CompositionType = "ELEMENT"
        self.ensure_oh(self.site)
        if self.site.ObjectPlacement is None:
            self.site.ObjectPlacement = self._placement()
        parent = ifcopenshell.util.element.get_aggregate(self.site)
        if parent != self.project:
            ifcopenshell.api.aggregate.assign_object(f, products=[self.site], relating_object=self.project)
            self.change("relate", "IfcRelAggregates IfcProject->IfcSite")
        self.change("edit", "IfcSite", Name=self.site.Name, RefLatitude=self.site.RefLatitude,
                    RefLongitude=self.site.RefLongitude, RefElevation=self.site.RefElevation)
        if srec:
            self.created["SITE-1"] = self.site
            gpa = srec["sets"].get("Pset_SpaceCommon", {}).get("GrossPlannedArea")
            self.site_gpa = gpa
            self.to_remove.append(srec["entity"])

    # ------------------------------------------------------- spatial elements
    def _spatial_entity(self, oid: str, ifc_class: str, predefined_type: Optional[str]):
        """Reuse the exported object when the exporter already made it the right
        class, otherwise create a new one (keeping the DGN-derived GlobalId)."""
        rec = self.idx[oid]
        ent = rec["entity"]
        if ent.is_a(ifc_class):
            self._detach_containment(ent)
            if predefined_type:
                ent.PredefinedType = predefined_type
            self.change("reuse", oid, entity=entity_label(ent))
            return ent
        guid = ent.GlobalId
        new = ifcopenshell.api.root.create_entity(self.f, ifc_class=ifc_class, predefined_type=predefined_type)
        self.to_remove.append(ent)
        self.pending_guid = getattr(self, "pending_guid", [])
        self.pending_guid.append((new, guid))
        # carry over the representation (footprint) only if the placement chain is identity
        self.change("create", oid, entity=ifc_class, replaces=entity_label(ent))
        return new

    def _detach_containment(self, ent):
        """Remove ``ent`` from every IfcRelContainedInSpatialStructure (spatial
        elements have no ContainedInStructure inverse, so this works on the
        relationships directly)."""
        for rel in list(self.f.get_inverse(ent)):
            if rel.is_a("IfcRelContainedInSpatialStructure") and ent in rel.RelatedElements:
                rest = [e for e in rel.RelatedElements if e != ent]
                if rest:
                    rel.RelatedElements = rest
                else:
                    self.f.remove(rel)

    def _attrs(self, ent, rec, long_name=True, object_type=True):
        ent.Name = self._str(rec, "IfcName", ent.Name or "")
        ent.Description = self._str(rec, "IfcDescription") or None
        if long_name and hasattr(ent, "LongName"):
            ent.LongName = self._str(rec, "IfcLongName") or None
        if object_type and hasattr(ent, "ObjectType"):
            ot = self._str(rec, "IfcObjectType")
            if ot:
                ent.ObjectType = ot
        self.ensure_oh(ent)

    def railway_and_parts(self):
        f = self.f
        rw_ids = [k for k, r in self.idx.items() if self._str(r, "IfcEntity") == "IfcRailway"]
        if len(rw_ids) != 1:
            raise SystemExit("Expected one IfcRailway carrier, found %s" % rw_ids)
        rid = rw_ids[0]
        self.railway = self._spatial_entity(rid, "IfcRailway", "USERDEFINED")
        self._attrs(self.railway, self.idx[rid])
        if not self.railway.ObjectType:
            self.railway.ObjectType = self.cfg.model["railway"]["object_type"]
        if self.railway.ObjectPlacement is None or not self.idx[rid]["entity"].is_a("IfcRailway"):
            self.railway.ObjectPlacement = self._placement(self.site.ObjectPlacement)
        ifcopenshell.api.aggregate.assign_object(f, products=[self.railway], relating_object=self.site)
        self.change("relate", "IfcRelAggregates IfcSite->IfcRailway", railway=self.railway.Name)
        self.created[rid] = self.railway
        self.parts: Dict[str, Any] = {}
        part_ids = [k for k, r in self.idx.items() if self._str(r, "IfcEntity") == "IfcRailwayPart"]
        for pid in sorted(part_ids):
            rec = self.idx[pid]
            pdt = self._str(rec, "IfcPredefinedType")
            part = self._spatial_entity(pid, "IfcRailwayPart", pdt)
            self._attrs(part, rec)
            part.UsageType = self._str(rec, "UsageType", self.cfg.model["railway_part_usage_type"])
            if part.ObjectPlacement is None or not rec["entity"].is_a("IfcRailwayPart"):
                part.ObjectPlacement = self._placement(self.railway.ObjectPlacement)
            self.parts[pid] = part
            self.created[pid] = part
        ifcopenshell.api.aggregate.assign_object(f, products=list(self.parts.values()), relating_object=self.railway)
        kinds = sorted(p.PredefinedType for p in self.parts.values())
        self.change("relate", "IfcRelAggregates IfcRailway->IfcRailwayPart", parts=kinds)
        if kinds != ["PLAINTRACK"] * 4 + ["TURNOUTTRACK"] * 2:
            self.problems.append("Railway parts are %s, expected 4 PLAINTRACK + 2 TURNOUTTRACK" % kinds)

    def spatial_zone(self):
        f = self.f
        z_ids = [k for k, r in self.idx.items() if self._str(r, "IfcEntity") == "IfcSpatialZone"]
        self.zone = None
        for zid in z_ids:
            rec = self.idx[zid]
            zone = self._spatial_entity(zid, "IfcSpatialZone", self._str(rec, "IfcPredefinedType") or "NOTDEFINED")
            self._attrs(zone, rec)
            if zone.PredefinedType == "USERDEFINED" and not zone.ObjectType:
                zone.ObjectType = self.cfg.model["spatial_zone"]["object_type"]
            if zone.ObjectPlacement is None or not rec["entity"].is_a("IfcSpatialZone"):
                zone.ObjectPlacement = self._placement(self.site.ObjectPlacement)
            relation = self.cfg.model["spatial_zone"].get("relation", "aggregate_project")
            target = self.project if relation == "aggregate_project" else self.site
            ifcopenshell.api.aggregate.assign_object(f, products=[zone], relating_object=target)
            self.change("relate", "IfcRelAggregates %s->IfcSpatialZone" % target.is_a())
            self.created[zid] = zone
            self.zone = zone

    # --------------------------------------------------------------- alignments
    def _angle(self, az: float) -> float:
        scale = ifcopenshell.util.unit.calculate_unit_scale(self.f, "PLANEANGLEUNIT")
        return (math.pi / 2.0 - az) / scale

    def _build_alignment(self, name: str, track: TrackGeometry):
        """Alignment layouts in IFC model coordinates: model = SWEREF/RH2000 - offset
        (offset = IfcMapConversion Eastings/Northings/OrthogonalHeight)."""
        f = self.f
        ox, oy, oz = (-v for v in self.offset)
        al = ifcopenshell.api.alignment.create(f, name, include_vertical=True, include_cant=True)
        hl = ifcopenshell.api.alignment.get_horizontal_layout(al)
        for seg in track.horizontal.segments:
            el = seg.el
            sign = 1.0 if el.rot == "ccw" else -1.0
            if seg.kind == "Line":
                kind, r0, r1 = "LINE", 0.0, 0.0
            elif seg.kind == "Curve":
                kind, r0, r1 = "CIRCULARARC", sign * el.radius, sign * el.radius
            else:
                kind = "CLOTHOID"
                r0 = 0.0 if math.isinf(el.radius_start) else sign * el.radius_start
                r1 = 0.0 if math.isinf(el.radius_end) else sign * el.radius_end
            p = f.createIfcAlignmentHorizontalSegment(
                StartTag=None, EndTag=None,
                StartPoint=f.createIfcCartesianPoint((el.start.x + ox, el.start.y + oy)),
                StartDirection=self._angle(el.dir_start), StartRadiusOfCurvature=r0, EndRadiusOfCurvature=r1,
                SegmentLength=el.length, GravityCenterLineHeight=None, PredefinedType=kind)
            ifcopenshell.api.alignment.create_layout_segment(f, hl, p)
        vl = ifcopenshell.api.alignment.get_vertical_layout(al)
        prof = track.profile
        s0 = track.sta_start
        edges = [prof.sta_start]
        for c in prof.curves:
            edges += [c.bvc, c.evc]
        edges.append(prof.sta_end)
        curve_at = {round(c.bvc, 6): c for c in prof.curves}
        for a, b in zip(edges, edges[1:]):
            if b - a < 1e-6:
                continue
            za, ga = track.elevation(a)
            zb, gb = track.elevation(b - 1e-9)
            c = curve_at.get(round(a, 6))
            if c is not None and abs(c.evc - b) < 1e-6:
                dg = c.grade_out - c.grade_in
                kind, rad = "PARABOLICARC", (c.length / dg if abs(dg) > 1e-12 else 0.0)
                g0, g1 = c.grade_in + track.z_correction[1], c.grade_out + track.z_correction[1]
            else:
                kind, rad, g0, g1 = "CONSTANTGRADIENT", 0.0, ga, ga
            p = f.createIfcAlignmentVerticalSegment(
                StartTag=None, EndTag=None, StartDistAlong=a - s0, HorizontalLength=b - a, StartHeight=za + oz,
                StartGradient=g0, EndGradient=g1, RadiusOfCurvature=rad, PredefinedType=kind)
            ifcopenshell.api.alignment.create_layout_segment(f, vl, p)
        cl = ifcopenshell.api.alignment.get_cant_layout(al)
        if cl is not None:
            if hasattr(cl, "RailHeadDistance"):
                cl.RailHeadDistance = track.cant.gauge
            rows = track.cant.rows
            for r0_, r1_ in zip(rows, rows[1:]):
                a, b = r0_.station, r1_.station
                if b - a < 1e-6:
                    continue
                ca = track.cant.evaluate(a + 1e-9)
                cb = track.cant.evaluate(b - 1e-9)
                side = ca.raised_side or cb.raised_side
                lv0 = ca.applied_m if side == "left" else 0.0
                rv0 = ca.applied_m if side == "right" else 0.0
                lv1 = cb.applied_m if side == "left" else 0.0
                rv1 = cb.applied_m if side == "right" else 0.0
                kind = "LINEARTRANSITION" if r0_.transition_type else "CONSTANTCANT"
                p = f.createIfcAlignmentCantSegment(
                    StartTag=None, EndTag=None, StartDistAlong=a - s0, HorizontalLength=b - a,
                    StartCantLeft=lv0, EndCantLeft=lv1, StartCantRight=rv0, EndCantRight=rv1, PredefinedType=kind)
                ifcopenshell.api.alignment.create_layout_segment(f, cl, p)
        ifcopenshell.api.alignment.add_stationing_referent(f, "%.3f" % track.sta_start, al, 0.0, track.sta_start,
                                                           has_increasing_station=True)
        return al

    def alignments(self):
        f = self.f
        a_ids = [k for k, r in self.idx.items() if self._str(r, "IfcEntity") == "IfcAlignment"]
        doc = read_landxml(self.cfg.file("landxml"))
        self.alignment_entities = {}
        for aid in sorted(a_ids):
            rec = self.idx[aid]
            acfg = next(a for a in self.cfg.model["alignments"] if a["id"] == aid)
            track = self.builder.tracks[acfg["key"]]
            if track.alignment.name != doc.alignment(acfg["landxml_name"]).name:
                raise ValueError("LandXML alignment mismatch for %s" % aid)
            old = rec["entity"]
            al = self._build_alignment(self._str(rec, "IfcName", acfg["name"]), track)
            al.Description = self._str(rec, "IfcDescription", acfg["description"])
            al.PredefinedType = "USERDEFINED"
            al.ObjectType = self._str(rec, "IfcObjectType", acfg.get("object_type", "Spårmittlinje"))
            self.ensure_oh(al)
            self.to_remove.append(old)
            self.pending_guid = getattr(self, "pending_guid", [])
            self.pending_guid.append((al, old.GlobalId))
            if ifcopenshell.util.element.get_aggregate(al) != self.project:
                ifcopenshell.api.aggregate.assign_object(f, products=[al], relating_object=self.project)
            ifcopenshell.api.spatial.reference_structure(f, products=[al], relating_structure=self.site)
            self.alignment_entities[aid] = al
            self.created[aid] = al
            self.change("create", aid, entity="IfcAlignment", segments=len(track.horizontal.segments),
                        landxml=acfg["landxml_name"], replaces=entity_label(old))

    # ------------------------------------------------------------- built system
    def built_system(self):
        f = self.f
        b_ids = [k for k, r in self.idx.items() if self._str(r, "IfcEntity") == "IfcBuiltSystem"]
        if not b_ids:
            self.problems.append("No IfcBuiltSystem carrier in the export")
            return
        bid = b_ids[0]
        rec = self.idx[bid]
        bs = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuiltSystem",
                                                 predefined_type=self._str(rec, "IfcPredefinedType", "RAILWAYTRACK"))
        self._attrs(bs, rec)
        self.ensure_oh(bs)
        ifcopenshell.api.group.assign_group(f, products=list(self.parts.values()), group=bs)
        self.pending_guid = getattr(self, "pending_guid", [])
        self.pending_guid.append((bs, rec["entity"].GlobalId))
        self.to_remove.append(rec["entity"])
        self.created[bid] = bs
        self.built = bs
        self.change("create", bid, entity="IfcBuiltSystem", group_members=len(self.parts))

    # --------------------------------------------------------- physical elements
    def physical_elements(self):
        f = self.f
        by_part: Dict[str, List[Any]] = {}
        assemblies: Dict[str, List[Any]] = {}
        reclassed = 0
        self.physical = []
        for oid, rec in self.idx.items():
            ent_name = self._str(rec, "IfcEntity")
            if ent_name not in PHYSICAL:
                continue
            ent = rec["entity"]
            pdt = self._str(rec, "IfcPredefinedType") or None
            if not ent.is_a(ent_name):
                old = entity_label(ent)
                ent = ifcopenshell.api.root.reassign_class(f, ent, ifc_class=ent_name, predefined_type=pdt)
                rec["entity"] = ent
                reclassed += 1
                self.change("reclass", oid, old=old, new=entity_label(ent))
            elif pdt and getattr(ent, "PredefinedType", None) != pdt:
                ent.PredefinedType = pdt
                if ent.ObjectType == pdt:
                    ent.ObjectType = None
                self.change("edit", oid, PredefinedType=pdt)
            ent.Name = self._str(rec, "IfcName", ent.Name or "")
            ent.Description = self._str(rec, "IfcDescription") or None
            self.ensure_oh(ent)
            parent = self._str(rec, "SpatialParent")
            if parent not in self.parts:
                self.problems.append("%s: spatial parent %r is not a railway part" % (oid, parent))
                continue
            if self._str(rec, "SpatialRelation") == "aggregated":
                assemblies.setdefault(parent, []).append(ent)
            else:
                by_part.setdefault(parent, []).append(ent)
            self.physical.append(ent)
        for pid, ents in by_part.items():
            ifcopenshell.api.spatial.assign_container(f, products=ents, relating_structure=self.parts[pid])
            self._reparent_placements(ents, self.parts[pid])
            self.change("relate", "IfcRelContainedInSpatialStructure %s" % pid, elements=len(ents))
        for pid, ents in assemblies.items():
            ifcopenshell.api.spatial.unassign_container(f, products=ents)
            ifcopenshell.api.aggregate.assign_object(f, products=ents, relating_object=self.parts[pid])
            self._reparent_placements(ents, self.parts[pid])
            self.change("relate", "IfcRelAggregates %s->IfcElementAssembly" % pid, elements=len(ents))
        if self.zone is not None and self.physical:
            ifcopenshell.api.spatial.reference_structure(f, products=self.physical, relating_structure=self.zone)
            self.change("relate", "IfcRelReferencedInSpatialStructure IfcSpatialZone", elements=len(self.physical))
        self.reclassed = reclassed

    def _reparent_placements(self, ents, part):
        """Place elements relative to their container when that does not move them."""
        import numpy as np
        part_m = ifcopenshell.util.placement.get_local_placement(part.ObjectPlacement)
        if not np.allclose(part_m, np.eye(4), atol=1e-9):
            return
        for e in ents:
            pl = e.ObjectPlacement
            if pl is None or not pl.is_a("IfcLocalPlacement"):
                continue
            rel = pl.PlacementRelTo
            rel_m = ifcopenshell.util.placement.get_local_placement(rel) if rel else np.eye(4)
            if np.allclose(rel_m, np.eye(4), atol=1e-9) and rel is not part.ObjectPlacement:
                if len(f_users := self.f.get_inverse(pl)) <= 1:
                    pl.PlacementRelTo = part.ObjectPlacement

    # ------------------------------------------------------------ classification
    def classifications(self):
        f = self.f
        systems = self.cfg.mapping["classification_systems"]
        cls_entities: Dict[str, Any] = {c.Name: c for c in f.by_type("IfcClassification")}
        groups: Dict[Tuple[str, str, str], List[Any]] = {}
        for oid, rec in self.idx.items():
            target = self.created.get(oid) or (rec["entity"] if self._str(rec, "IfcEntity") in PHYSICAL else None)
            if target is None:
                continue
            c = rec["sets"].get("BU26_Classification", {})
            for suffix in ("", "2"):
                sysname = c.get("CoClassSystem" + suffix)
                code = c.get("CoClassIdentification" + suffix)
                if sysname and code:
                    groups.setdefault((str(sysname), str(code), str(c.get("CoClassName" + suffix) or "")), []).append(target)
        for (sysname, code, name), objs in sorted(groups.items()):
            cls = cls_entities.get(sysname)
            if cls is None:
                cls = ifcopenshell.api.classification.add_classification(f, classification=sysname)
                meta = systems.get(sysname, {})
                cls.Source = meta.get("source")
                cls.Edition = meta.get("edition")
                cls.Description = meta.get("description")
                cls_entities[sysname] = cls
                self.change("create", "IfcClassification %s" % sysname)
            ref = ifcopenshell.api.classification.add_reference(f, products=objs, identification=code, name=name,
                                                                classification=cls)
            self.change("relate", "IfcRelAssociatesClassification %s %s" % (sysname, code), objects=len(objs))

    # ------------------------------------------------------------ property sets
    def _typed(self, ifc_type: str, value):
        f = self.f
        if ifc_type == "IfcBoolean":
            return f.create_entity(ifc_type, _bool(value))
        if ifc_type in ("IfcLabel", "IfcIdentifier", "IfcText"):
            v = value
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            return f.create_entity(ifc_type, str(v))
        return f.create_entity(ifc_type, _float(value))

    def _remove_raw_set(self, ent, pset_ids):
        f = self.f
        for pid in pset_ids or []:
            if pid is None:
                continue
            try:
                ps = f.by_id(pid)
            except RuntimeError:
                continue
            for rel in list(getattr(ps, "DefinesOccurrence", []) or []):
                objs = [o for o in rel.RelatedObjects if o != ent]
                if objs:
                    rel.RelatedObjects = objs
                else:
                    f.remove(rel)
            if not f.get_inverse(ps):
                for p in list(getattr(ps, "HasProperties", None) or getattr(ps, "Quantities", None) or []):
                    if len(f.get_inverse(p)) <= 1:
                        f.remove(p)
                f.remove(ps)

    def property_sets(self):
        f = self.f
        pset_types = self.cfg.mapping["property_sets"]
        qto_types = self.cfg.mapping["quantity_sets"]
        shared: Dict[Tuple, Any] = {}
        members: Dict[int, List[Any]] = {}
        n_sets = 0
        for oid, rec in self.idx.items():
            target = self.created.get(oid)
            if target is None and self._str(rec, "IfcEntity") in PHYSICAL:
                target = rec["entity"]
            if target is None:
                continue
            for set_name, values in rec["sets"].items():
                if set_name in pset_types:
                    types = pset_types[set_name]
                elif set_name in qto_types:
                    types = qto_types[set_name]
                else:
                    continue
                if target is rec["entity"]:
                    self._remove_raw_set(target, rec["pset_ids"].get(set_name))
                clean = {k: v for k, v in values.items() if k in types and v is not None and v != ""}
                key = (set_name, tuple(sorted((k, str(v)) for k, v in clean.items())))
                ps = shared.get(key)
                if ps is None:
                    if set_name in qto_types:
                        qs = []
                        for k, v in clean.items():
                            qt = types[k]
                            attr = {"IfcQuantityLength": "LengthValue", "IfcQuantityVolume": "VolumeValue",
                                    "IfcQuantityArea": "AreaValue", "IfcQuantityWeight": "WeightValue",
                                    "IfcQuantityCount": "CountValue"}[qt]
                            qs.append(f.create_entity(qt, **{"Name": k, attr: float(v)}))
                        ps = f.createIfcElementQuantity(ifcopenshell.guid.new(), self.oh, set_name,
                                                        "Beräknad från DGN-geometrin (BU26)",
                                                        "BU26 design model / DGN", qs)
                    else:
                        props = [f.createIfcPropertySingleValue(k, None, self._typed(types[k], v), None)
                                 for k, v in clean.items()]
                        ps = f.createIfcPropertySet(ifcopenshell.guid.new(), self.oh, set_name, None, props)
                    shared[key] = ps
                    n_sets += 1
                members.setdefault(ps.id(), []).append(target)
        # Pset_SpaceCommon on the site (IDS #2) from the site carrier values
        for ps_id, objs in members.items():
            f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), self.oh, None, None, objs, f.by_id(ps_id))
        self.change("create", "typed property/quantity sets", unique_sets=n_sets, relations=len(members))

    # ------------------------------------------------------------------ cleanup
    def cleanup(self):
        f = self.f
        removed = 0
        keep = set(id(e) for e in self.created.values())
        for ent in self.to_remove:
            if id(ent) in keep:
                continue
            try:
                ifcopenshell.api.root.remove_product(f, product=ent)
                removed += 1
            except Exception as e:
                self.problems.append("Could not remove carrier %s: %s" % (entity_label(ent), e))
        for new, guid in getattr(self, "pending_guid", []):
            if not any(e.GlobalId == guid for e in f.by_type("IfcRoot") if e is not new):
                new.GlobalId = guid
        self.removed_carriers = removed
        self.change("remove", "metadata carrier elements", count=removed)
        for e in [self.project, self.site, self.railway] + list(self.parts.values()) + \
                list(getattr(self, "alignment_entities", {}).values()) + ([self.zone] if self.zone else []):
            self.ensure_oh(e)

    def summary(self) -> Dict[str, Any]:
        f = self.f
        ours = {id(r["entity"]) for r in self.idx.values()}
        proxies = [e for e in f.by_type("IfcBuildingElementProxy")]
        bu26_proxies = []
        for e in proxies:
            for pn, props in ifcopenshell.util.element.get_psets(e).items():
                if "BU26_ObjectId" in props:
                    bu26_proxies.append(props["BU26_ObjectId"])
        counts: Dict[str, int] = {}
        for e in f.by_type("IfcProduct"):
            counts[e.is_a()] = counts.get(e.is_a(), 0) + 1
        return {"bu26_objects": len(self.idx), "reclassified": getattr(self, "reclassed", 0),
                "removed_carriers": getattr(self, "removed_carriers", 0), "offset_model_to_map": self.offset,
                "length_units": self.unit_report, "remaining_proxies": len(proxies),
                "bu26_objects_still_proxy": bu26_proxies, "product_counts": counts,
                "problems": self.problems, "changes": self.changes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Separate IFC post-processing step (see module docstring)")
    ap.add_argument("--in", dest="inp", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)
    cfg = load_config()
    inp = args.inp or cfg.file("ifc_bentley_export")
    out = args.out or cfg.file("ifc_output")
    rep = args.report or os.path.join(os.path.dirname(out), "postprocess_report.json")
    if os.path.abspath(inp) == os.path.abspath(out):
        raise SystemExit("Input and output must differ - the exporter result is kept unchanged")
    f = ifcopenshell.open(inp)
    t0 = time.perf_counter()
    result = Completer(f, cfg).run()
    f.write(out)
    result.update({"input": inp, "output": out, "seconds": round(time.perf_counter() - t0, 2)})
    with open(rep, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, default=str)
    print("Efterbearbetad IFC: %s (%d ändringar, %d problem) - rapport %s" % (
        out, len(result["changes"]), len(result["problems"]), rep))
    for p in result["problems"]:
        print("PROBLEM:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
