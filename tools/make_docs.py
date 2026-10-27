"""Generates docs/Kravmatris.md and docs/Geometri_verifiering.md from the IDS,
the configuration and the geometry/design code, so the documents always match
the implementation.

    python tools/make_docs.py [--pipeline-check]

``--pipeline-check`` additionally runs the export chain on the SIMULATED
export fixture (tests/fixtures/simulated_export.py) and adds the per
specification result of that test run to the matrix (clearly labelled - it is
not a result of a MicroStation export).
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from common.config import load_config, repo_path  # noqa: E402
from geometry.alignment_math import HorizontalAlignment  # noqa: E402
from geometry.landxml_reader import read_landxml  # noqa: E402
from geometry.vertical_profile import VerticalProfile  # noqa: E402
from model.railway_model import RailwayModelBuilder  # noqa: E402
from validation.ids_conflicts import find_conflicts, parse as parse_ids  # noqa: E402

NS = {"ids": "http://standards.buildingsmart.org/IDS", "xs": "http://www.w3.org/2001/XMLSchema"}

# How each IDS requirement is produced (DGN source -> IFC mechanism)
SPEC_SOURCES = {
    "#1": ("Bärare PRJ-1 (BU26_SPATIAL)", "BU26_Object: IfcName, IfcLongName, IfcDescription, Phase",
           "Exportören skapar IfcProject (ProjectConfigurations.ProjectName); efterbearbetning sätter LongName/Phase/OwnerHistory"),
    "#2": ("Bärare SITE-1", "BU26_Object: IfcName, IfcLongName, IfcDescription, RefLatitude/RefLongitude/RefElevation; Pset_SpaceCommon.GrossPlannedArea",
           "Exportören skapar IfcSite (SiteName); efterbearbetning: attribut, Ref*, Pset_SpaceCommon (IfcAreaMeasure), IfcRelAggregates Project->Site"),
    "#3": ("Bärare SZ-E1", "BU26_Object: IfcName, IfcLongName, IfcDescription, IfcObjectType, IfcPredefinedType",
           "Bentley IFC Classification -> IfcSpatialZone (om exportören stöder det), annars efterbearbetning; IfcRelAggregates Project->Zone, IfcRelReferencedInSpatialStructure"),
    "#4": ("Linjeföringar AL-N/AL-S/AL-V (3D-linjesträngar, BU26_ALIGNMENT)", "BU26_Object: IfcName, IfcDescription, IfcObjectType, Start/EndStation",
           "Efterbearbetning: IfcAlignment med horisontal/vertikal/cant-layout och geometri från LandXML, aggregerad till IfcProject, refererad i IfcSite"),
    "#5": ("Bärare RW-1", "BU26_Object + BU26_Classification (CoClass_BV CAE)",
           "IfcRailway USERDEFINED/ObjectType; IfcRelAggregates Site->Railway; IfcRelAssociatesClassification"),
    "#6": ("Bärare RP-N1, RP-N2, RP-S1, RP-S2 (fotavtryck)", "BU26_Object, BU26_Classification (CoClass_KS DA10), Pset_RailwayTrackStructurePart",
           "IfcRailwayPart PLAINTRACK, UsageType LONGITUDINAL; IfcRelAggregates Railway->Part; IfcRelAssignsToGroup BuiltSystem"),
    "#7": ("Räler RAIL_MAIN (BU26_RAIL_MAIN)", "BU26_Object (IfcRail/RAIL, IfcDescription innerräl/ytterräl, SpatialParent), BU26_Classification WRA20",
           "IfcRail.RAIL i IfcRelContainedInSpatialStructure -> PLAINTRACK"),
    "#8": ("Bärare RP-VA, RP-VB", "BU26_Object, BU26_Classification (CoClass_KS DA20), Pset_RailwayTrackStructurePart",
           "IfcRailwayPart TURNOUTTRACK; aggregering + grupp som #6"),
    "#9": ("Slipers SLEEPER (BU26_SLEEPER)", "BU26_Object (IfcTrackElement/SLEEPER), BU26_Classification ULE14",
           "IfcTrackElement.SLEEPER i PLAINTRACK"),
    "#10": ("Genomgående räler RAIL_TURNOUT", "BU26_Object (IfcRail/RAIL), BU26_Classification WRA20",
            "IfcRail.RAIL i TURNOUTTRACK"),
    "#11": ("Växeldriv SWITCH_ASSEMBLY (BU26_SWITCH_ASSEMBLY)", "BU26_Object (SpatialRelation=aggregated), BU26_Classification QSB, Pset_ElementAssemblyTypeTractionSwitchingAssembly",
            "IfcElementAssembly.TRACTION_SWITCHING_ASSEMBLY, IfcRelAggregates TURNOUTTRACK->Assembly; RatedVoltage IfcElectricVoltageMeasure, NominalPower IfcPowerMeasure"),
    "#12": ("Stödräler RAIL_STOCK (BU26_RAIL_STOCK)", "BU26_Object (IfcRail/STOCKRAIL), WRA20", "IfcRail.STOCKRAIL i TURNOUTTRACK"),
    "#13": ("Moträler RAIL_CHECK (BU26_RAIL_CHECK)", "BU26_Object (IfcRail/CHECKRAIL), WRA20", "IfcRail.CHECKRAIL i TURNOUTTRACK"),
    "#14": ("Korsningar FROG (BU26_FROG)", "BU26_Object (IfcTrackElement/FROG), WRA20", "IfcTrackElement.FROG i TURNOUTTRACK"),
    "#15": ("Bärare BS-1", "BU26_Object (IfcName Tvärbanan, IfcLongName Polarexpress), BU26_Classification FS R, Pset_BuiltSystemRailwayTrack",
            "Efterbearbetning: IfcBuiltSystem RAILWAYTRACK (IfcGroup, ingen geometri), IfcRelAssignsToGroup, Pset med IfcLabel/IfcIdentifier"),
    "#16": ("Räler RAIL_MAIN", "som #7", "som #7"),
    "#17": ("Växelslipers SLEEPER_TURNOUT (BU26_SLEEPER_TURNOUT)", "BU26_Object (IfcTrackElement/SLEEPER), ULE14", "IfcTrackElement.SLEEPER i TURNOUTTRACK"),
    "#18": ("Ballast BALLAST (BU26_BALLAST)", "Qto_CourseBaseQuantities (beräknat ur solidens geometri)",
            "IfcElementQuantity Qto_CourseBaseQuantities: IfcQuantityLength/Volume/Weight"),
    "#19": ("Slipers SLEEPER + SLEEPER_TURNOUT", "Qto_SleeperBaseQuantities (lådans mått)", "IfcElementQuantity med IfcQuantityLength"),
    "#20": ("DGN-modellens masterenhet = m", "-", "Exportören: IfcSIUnit LENGTHUNIT METRE utan prefix (kontrolleras, ändras ej)"),
    "#21": ("DGN Geographic Coordinate System SWEREF 99 18 00", "config coordinate_system",
            "Exportörens georeferering (om GCS satt); efterbearbetning: IfcProjectedCRS EPSG:3011 / SWEREF 99 18 00 / RH 2000, IfcMapConversion uppmätt"),
    "#22": ("Ballast BALLAST", "BU26_Classification: CoClass_KO UTA10 + CoClass_PR CEB.3", "Två IfcClassificationReference; IfcCourse i IfcRailwayPart"),
}


def _simple(el):
    if el is None:
        return None
    sv = el.find("ids:simpleValue", NS)
    if sv is not None:
        return sv.text
    return "|".join(e.get("value") for e in el.iter("{%s}enumeration" % NS["xs"])) or None


def ids_requirements(path):
    root = ET.parse(path).getroot()
    out = []
    for sp in root.find("ids:specifications", NS):
        app = sp.find("ids:applicability", NS).find("ids:entity", NS)
        ent = "%s%s" % (_simple(app.find("ids:name", NS)), ("." + _simple(app.find("ids:predefinedType", NS)))
                        if app.find("ids:predefinedType", NS) is not None else "")
        reqs = []
        for r in sp.find("ids:requirements", NS):
            tag = r.tag.split("}")[1]
            if tag == "attribute":
                v = _simple(r.find("ids:value", NS))
                reqs.append("%s%s%s" % ("" if r.get("cardinality") != "prohibited" else "ej ", _simple(r.find("ids:name", NS)),
                                        "=" + v if v else ""))
            elif tag == "property":
                v = _simple(r.find("ids:value", NS))
                reqs.append("%s.%s (%s)%s" % (_simple(r.find("ids:propertySet", NS)), _simple(r.find("ids:baseName", NS)),
                                             r.get("dataType"), "=" + v if v else ""))
            elif tag == "classification":
                reqs.append("klass %s %s" % (_simple(r.find("ids:system", NS)), _simple(r.find("ids:value", NS))))
            elif tag == "partOf":
                e = r.find("ids:entity", NS)
                pdt = _simple(e.find("ids:predefinedType", NS))
                reqs.append("partOf %s %s%s" % (r.get("relation"), _simple(e.find("ids:name", NS)), "." + pdt if pdt else ""))
            elif tag == "entity":
                reqs.append("entitet %s" % _simple(r.find("ids:name", NS)))
        out.append((sp.get("name"), ent, reqs))
    return out


def requirements_matrix(cfg, pipeline=None) -> str:
    ids_path = cfg.file("ids")
    conflicts = find_conflicts(parse_ids(ids_path))
    conf = {}
    for c in conflicts:
        conf.setdefault(c["spec_a"], []).append(c["spec_b"])
        conf.setdefault(c["spec_b"], []).append(c["spec_a"])
    lines = ["# Kravmatris IDS -> DGN -> Item Type -> IFC", "",
             "Genererad av `tools/make_docs.py` ur `input/Branschutmaningen_2026.ids` (oförändrad) och konfigurationen.",
             "", "Kolumnen *Testkörning (simulerad export)* visar resultatet när exportkedjan körs på den **simulerade** "
             "exportfixturen i `tests/fixtures/simulated_export.py` – inte på en verklig MicroStation-export. "
             "Den verkliga statusen fås av `validation/validate_ifc.py` efter export i MicroStation.", "",
             "| IDS | Tillämplighet | Krav (fasetter) | DGN-objekt | Item Type-fält | IFC-mappning / mekanism | Förväntat IFC-resultat | Motsägelse i IDS | Testkörning (simulerad export) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, ent, reqs in ids_requirements(ids_path):
        key = name.split()[0]
        src = SPEC_SOURCES.get(key, ("", "", ""))
        expected = "Godkänd" if name not in conf else "Kan inte godkännas för alla objekt (motsägelse)"
        status = ""
        if pipeline is not None:
            status = "godkänd" if name in pipeline["passed_specs"] else (
                "underkänd (endast IDS-motsägelse)" if name in pipeline["failed_specs_only_due_to_ids_conflicts"]
                else "UNDERKÄND")
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            name.replace("|", "/"), ent, "<br>".join(reqs), src[0], src[1], src[2], expected,
            ", ".join(conf.get(name, [])) or "-", status))
    lines += ["", "## Motsägelser som hittades automatiskt (`validation/ids_conflicts.py`)", ""]
    for c in conflicts:
        lines.append("* **%s** mot **%s** (%s): %s" % (c["spec_a"], c["spec_b"], c["applicability"], "; ".join(c["reasons"])))
    lines += ["", "Se `docs/IDS_och_underlag_konflikter.md` för hur modellen hanterar varje motsägelse."]
    return "\n".join(lines) + "\n"


def geometry_report(cfg) -> str:
    doc = read_landxml(cfg.file("landxml"))
    L = ["# Geometriverifiering (LandXML -> spårgeometri -> designmodell)", "",
         "Genererad av `tools/make_docs.py`. Alla värden är beräknade av koden i `geometry/` och `model/`.", "",
         "## Horisontalgeometri mot LandXML:s lagrade punkter", "",
         "Varje element utvärderas från sin egen startpunkt/riktning och integreras till slutet; avvikelsen mot "
         "LandXML:s `End` och `dirEnd` visas. Koordinatordning i filen: Northing Easting; riktningar är azimut från norr medurs.", "",
         "| Linjeföring | # | Typ | staStart | Längd (m) | Slutpunktsavvikelse (mm) | Riktningsavvikelse (µrad) |", "|---|---|---|---|---|---|---|"]
    for al in doc.alignments:
        for c in HorizontalAlignment(al).verify():
            L.append("| %s | %d | %s | %.4f | %.4f | %.4f | %.4f |" % (al.name, c.index, c.kind, c.sta_start, c.length,
                                                                    c.end_position_error * 1000, c.end_azimuth_error * 1e6))
    L += ["", "## Vertikalkurvor", "",
          "LandXML anger både radie och längd. Med radien blir kurvlängden |R·Δg|, vilket inte stämmer med angiven längd "
          "och ger överlappande kurvor; därför används angiven längd (parabel centrerad i PVI), se docs/IDS_och_underlag_konflikter.md (D-01).", "",
          "| Linjeföring | PVI station | R (fil) | L (fil) | Δg | L enligt R | Effektiv R = L/Δg |", "|---|---|---|---|---|---|---|"]
    for al in doc.alignments:
        if len(al.profile) < 3:
            continue
        for c in VerticalProfile(al.profile).checks():
            L.append("| %s | %.3f | %s | %.3f | %.5f | %s | %s |" % (
                al.name, c.pvi_station, c.stored_radius, c.stored_length, c.grade_change,
                "%.2f" % c.radius_implied_length if c.radius_implied_length else "-",
                "%.0f" % c.effective_radius if c.effective_radius else "-"))
    b = RailwayModelBuilder(cfg)
    dm = b.build()
    r = dm.report
    L += ["", "## Rälsförhöjning (exempel)", "", "| Spår | Station | Förhöjning (mm) | Höjd sida | Vänster räl ö.k. | Höger räl ö.k. |", "|---|---|---|---|---|---|"]
    for key, st in (("N", 7004.25), ("N", 7070.0), ("N", 7280.0), ("N", 7515.0), ("S", 7280.0), ("S", 7700.0)):
        f = b.tracks[key].frame(st)
        L.append("| %s | %.2f | %.1f | %s | %.4f | %.4f |" % (key, st, f.cant.applied_m * 1000, f.cant.raised_side or "-",
                                                             f.point(0.75, 0)[2], f.point(-0.75, 0)[2]))
    L += ["", "## Växlar (beräknade ur geometrin)", "", "| Växel | Huvudspår | Tungspets | Korsning (huvudspår) | Korsning (förbindelse) | Korsningsvinkel | 1:n | Tunglängd | Avvikande sida |",
          "|---|---|---|---|---|---|---|---|---|"]
    for tid, t in r["turnouts"].items():
        L.append("| %s | %s | %.3f | %.3f | %.3f | %.3f° | %.2f | %.2f | %s |" % (
            tid, t["main_track"], t["toe_main_station"], t["frog_main_station"], t["frog_branch_station"],
            t["frog_angle_deg"], t["frog_ratio_1_to"], t["blade_length"], t["branch_side"]))
    L += ["", "## Spårdelar (IfcRailwayPart)", "", "| Id | Typ | Spår | Från | Till | Längd |", "|---|---|---|---|---|---|"]
    for p in r["railway_parts"]:
        L.append("| %s | %s | %s | %.3f | %.3f | %.3f |" % (p["id"], p["type"], p["track"], p["station_from"],
                                                           p["station_to"], p["station_to"] - p["station_from"]))
    L += ["", "## Mängder (full-läge)", "", "| Ballast | Längd | Bredd | Tjocklek | GrossVolume m³ | Volume m³ | Weight t |", "|---|---|---|---|---|---|---|"]
    for c in dm.components:
        if c.category == "BALLAST":
            q = c.qtos["Qto_CourseBaseQuantities"]
            L.append("| %s | %.2f | %.3f | %.2f | %.1f | %.1f | %.1f |" % (c.object_id, q["Length"], q["Width"], q["Thickness"],
                                                                         q["GrossVolume"], q["Volume"], q["Weight"] / 1000))
    L += ["", "Antal objekt per kategori (full-läge): " + ", ".join("%s %d" % kv for kv in sorted(r["counts"].items())), "",
          "Varningar: " + "; ".join(r["warnings"]), "",
          "Referenspunkt för IfcSite: E %.3f N %.3f H %.3f -> lat %.9f lon %.9f (kontrollerad mot pyproj EPSG:3011->4326, se tests/test_georef.py)" % (
              r["site_reference"]["easting"], r["site_reference"]["northing"], r["site_reference"]["elevation"],
              r["site_reference"]["latitude"], r["site_reference"]["longitude"]),
          "", "![Växelförbindelse i plan](img/vaxelforbindelse_plan.png)"]
    return "\n".join(L) + "\n"


def pipeline_check():
    from export.complete_ifc_structure import Completer
    from model.railway_model import build_design_model
    from tests.fixtures.simulated_export import simulate
    from validation.validate_ifc import validate
    import ifcopenshell
    cfg = load_config(mode="preview")
    with tempfile.TemporaryDirectory() as d:
        raw = os.path.join(d, "raw.ifc")
        simulate(cfg, build_design_model(cfg), raw, classified=False, include_bentley_item=False)
        f = ifcopenshell.open(raw)
        Completer(f, cfg, log=lambda *a: None).run()
        out = os.path.join(d, "out.ifc")
        f.write(out)
        return validate(out, cfg.file("ids"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline-check", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(mode="full")
    pipe = pipeline_check() if a.pipeline_check else None
    with open(repo_path("docs/Kravmatris.md"), "w", encoding="utf-8") as fh:
        fh.write(requirements_matrix(cfg, pipe))
    with open(repo_path("docs/Geometri_verifiering.md"), "w", encoding="utf-8") as fh:
        fh.write(geometry_report(cfg))
    print("docs/Kravmatris.md, docs/Geometri_verifiering.md skrivna")


if __name__ == "__main__":
    main()
