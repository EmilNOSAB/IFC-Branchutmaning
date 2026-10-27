"""Reads the IFC that MicroStation exported from the probe DGN
(microstation/probe_exporter.py) and reports, per probe object, what the
exporter made of it.  Read only.

    python export/inspect_probe_export.py [--ifc output/probe/BU26_probe.ifc]

Writes output/probe/probe_analysis.json and prints one verdict per construct.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import repo_path  # noqa: E402

try:
    import ifcopenshell
    import ifcopenshell.util.classification as uc
    import ifcopenshell.util.element as ue
except ImportError:  # pragma: no cover
    raise SystemExit("IfcOpenShell saknas: python -m pip install ifcopenshell")


def _describe(o):
    if o is None:
        return None
    return "%s%s %s" % (o.is_a(), "." + str(o.PredefinedType) if getattr(o, "PredefinedType", None) else "",
                        o.Name or "")


def _value_types(f, o):
    out = {}
    for rel in getattr(o, "IsDefinedBy", []) or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        d = rel.RelatingPropertyDefinition
        kind = d.is_a()
        if d.is_a("IfcPropertySet"):
            for p in d.HasProperties:
                if p.is_a("IfcPropertySingleValue"):
                    out["%s.%s" % (d.Name, p.Name)] = "%s:%s" % (kind, p.NominalValue.is_a() if p.NominalValue else None)
                else:
                    out["%s.%s" % (d.Name, p.Name)] = "%s:%s" % (kind, p.is_a())
        elif d.is_a("IfcElementQuantity"):
            for q in d.Quantities:
                out["%s.%s" % (d.Name, q.Name)] = "%s:%s" % (kind, q.is_a())
    return out


def probe_objects(f):
    objs = {}
    for o in f.by_type("IfcObjectDefinition"):
        pid = (ue.get_psets(o).get("BU26_Probe") or {}).get("ProbeId")
        if pid:
            objs[pid] = o
    return objs


def analyse(path):
    f = ifcopenshell.open(path)
    objs = probe_objects(f)
    rows = {}
    for pid, o in sorted(objs.items()):
        rows[pid] = {
            "entity": _describe(o),
            "object_type": getattr(o, "ObjectType", None),
            "container": _describe(ue.get_container(o)) if o.is_a("IfcElement") else None,
            "aggregate_parent": _describe(ue.get_aggregate(o)),
            "parts": [_describe(p) for p in (ue.get_parts(o) or [])],
            "contained_elements": [_describe(e) for r in getattr(o, "ContainsElements", []) or []
                                   for e in r.RelatedElements][:10],
            "groups": [_describe(r.RelatingGroup) for r in getattr(o, "HasAssignments", []) or []
                       if r.is_a("IfcRelAssignsToGroup")],
            "classification_refs": [(r.Identification, r.Name) for r in uc.get_references(o)],
            "has_geometry": bool(getattr(o, "Representation", None)),
            "values": _value_types(f, o),
        }

    def ent(pid):
        return (rows.get(pid) or {}).get("entity") or ""

    def child_in(child, parent_pid, key):
        r = rows.get(child)
        return bool(r and r[key] and r[key] == ent(parent_pid))

    crs = [dict(Name=c.Name, Description=c.Description, GeodeticDatum=c.GeodeticDatum,
                VerticalDatum=c.VerticalDatum) for c in f.by_type("IfcProjectedCRS")]
    groups = [dict(entity=_describe(g), members=[_describe(m) for r in g.IsGroupedBy for m in r.RelatedObjects])
              for g in f.by_type("IfcGroup")]
    units = {k: v for k, v in (rows.get("P01") or {}).get("values", {}).items() if k.startswith("Pset_ProbeUnits.")}
    qto = {k: v for k, v in (rows.get("P11") or {}).get("values", {}).items() if k.startswith("Qto_")}
    verdict = {
        "class_from_ifc_classification (P01 IfcRail.RAIL)": ent("P01").startswith("IfcRail.RAIL"),
        "railwaypart_from_element (P02)": ent("P02").startswith("IfcRailwayPart"),
        "railwaypart_from_cell (P03)": ent("P03").startswith("IfcRailwayPart"),
        "containment_via_cell, items after add (P03-c1 in P03)": child_in("P03-c1", "P03", "container"),
        "containment_via_cell, items before add (P04-c1 in P04)": child_in("P04-c1", "P04", "container"),
        "aggregation_via_cell (P03-c1 part of P03)": child_in("P03-c1", "P03", "aggregate_parent"),
        "nested_spatial (P05-part in P05 IfcRailway)": child_in("P05-part", "P05", "aggregate_parent"),
        "nested_containment (P05-rail in P05-part)": child_in("P05-rail", "P05-part", "container"),
        "assembly_aggregation (P06 has parts)": bool((rows.get("P06") or {}).get("parts")),
        "alignment (P07 IfcAlignment)": ent("P07").startswith("IfcAlignment"),
        "spatial_zone (P08)": ent("P08").startswith("IfcSpatialZone"),
        "built_system (P09 IfcBuiltSystem)": ent("P09").startswith("IfcBuiltSystem")
        or any(g["entity"].startswith("IfcBuiltSystem") for g in groups),
        "named_group_exported (P10)": any("P10" in (g["entity"] or "") for g in groups),
        "units_give_measure_types (P01 Pset_ProbeUnits)": any("Measure" in v for v in units.values()),
        "qto_as_element_quantity (P11)": any(v.startswith("IfcElementQuantity") for v in qto.values()),
        "classification_reference (P12)": bool(f.by_type("IfcClassificationReference")),
        "vertical_datum_RH2000": any("RH" in str(c.get("VerticalDatum") or "") for c in crs),
    }
    return {
        "file": os.path.abspath(path),
        "application": [(a.ApplicationFullName, a.Version) for a in f.by_type("IfcApplication")],
        "verdict": verdict,
        "probe_objects": rows,
        "missing_probe_ids": sorted({"P%02d" % i for i in range(1, 13)} - {k.split("-")[0] for k in rows} - {"P10"}),
        "spatial_elements": [_describe(s) for s in f.by_type("IfcSpatialElement")],
        "groups": groups,
        "unit_value_types": units,
        "qto_value_types": qto,
        "projected_crs": crs,
        "classification_references": [(r.Identification, r.Name) for r in f.by_type("IfcClassificationReference")],
        "product_counts": {k: len(f.by_type(k)) for k in sorted({p.is_a() for p in f.by_type("IfcProduct")})},
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ifc", default=repo_path("output/probe/BU26_probe.ifc"))
    ap.add_argument("--out", default=repo_path("output/probe/probe_analysis.json"))
    a = ap.parse_args(argv)
    if not os.path.exists(a.ifc):
        raise SystemExit("Hittar inte %s - exportera provfilen från MicroStation först" % a.ifc)
    r = analyse(a.ifc)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(r, fh, ensure_ascii=False, indent=1, default=str)
    for k, v in r["verdict"].items():
        print("%-62s %s" % (k, "JA" if v else "nej"))
    print("Analys: %s" % a.out)
    return r


if __name__ == "__main__":
    main()
