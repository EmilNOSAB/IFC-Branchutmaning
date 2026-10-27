"""Analyses the raw IFC written by MicroStation's exporter (before any post step).

    python export/inspect_bentley_export.py [--ifc output/Branschutmaningen_2026_bentley_export.ifc]

Answers the questions that decide how much post-processing is needed:
* which IFC class and PredefinedType did every DGN element get (vs. the
  IfcEntity/IfcPredefinedType Item Type values)?  how many proxies?
* under which names and with which IFC data types were the Item Types
  exported (property set names, IfcPropertySet vs IfcElementQuantity)?
* which relationships exist (aggregation, containment, groups,
  classification) and what does the spatial tree look like?
* units, map conversion and CRS
Writes output/bentley_export_analysis.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

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
import ifcopenshell.util.element as ue  # noqa: E402

from common.config import load_config, repo_path  # noqa: E402
from export.ifc_common import bu26_index, item_type_of_pset  # noqa: E402


def analyse(path: str) -> dict:
    f = ifcopenshell.open(path)
    out = {"file": os.path.abspath(path), "schema": f.schema_identifier,
           "originating_system": getattr(f.header.file_name, "originating_system", "")}
    out["product_counts"] = dict(Counter(e.is_a() for e in f.by_type("IfcProduct")))
    idx = bu26_index(f)
    out["bu26_objects_found"] = len(idx)
    mism, by_cat = [], defaultdict(Counter)
    for oid, rec in idx.items():
        obj = rec["sets"].get("BU26_Object", {})
        want = (obj.get("IfcEntity"), obj.get("IfcPredefinedType") or None)
        e = rec["entity"]
        got = (e.is_a(), getattr(e, "PredefinedType", None))
        by_cat[obj.get("ObjectCategory")]["%s.%s" % got] += 1
        if want[0] in ("IfcProject", "IfcSite", "IfcBuiltSystem"):
            continue
        if got[0] != want[0] or (want[1] and got[1] != want[1]):
            mism.append({"object_id": oid, "expected": "%s.%s" % want, "got": "%s.%s" % got})
    out["class_by_category"] = {k: dict(v) for k, v in by_cat.items()}
    out["class_mismatches"] = len(mism)
    out["class_mismatch_sample"] = mism[:50]
    names, kinds, types = Counter(), Counter(), defaultdict(Counter)
    for rel in f.by_type("IfcRelDefinesByProperties"):
        pd = rel.RelatingPropertyDefinition
        if not pd.is_a("IfcPropertySetDefinition"):
            continue
        names[pd.Name] += 1
        kinds["%s:%s" % (pd.is_a(), item_type_of_pset(pd.Name or "") or "-")] += 1
        for p in getattr(pd, "HasProperties", None) or []:
            if p.is_a("IfcPropertySingleValue") and p.NominalValue is not None:
                types["%s.%s" % (pd.Name, p.Name)][p.NominalValue.is_a()] += 1
        for q in getattr(pd, "Quantities", None) or []:
            types["%s.%s" % (pd.Name, q.Name)][q.is_a()] += 1
    out["property_set_names"] = dict(names.most_common())
    out["property_set_kinds"] = dict(kinds)
    out["property_value_types"] = {k: dict(v) for k, v in sorted(types.items())}
    rels = Counter(r.is_a() for r in f.by_type("IfcRelationship"))
    out["relationships"] = dict(rels)
    cont = Counter()
    for r in f.by_type("IfcRelContainedInSpatialStructure"):
        cont["%s <- %d elements" % (r.RelatingStructure.is_a(), len(r.RelatedElements))] += 1
    out["containment"] = dict(cont)
    agg = Counter("%s -> %s" % (r.RelatingObject.is_a(), ",".join(sorted({o.is_a() for o in r.RelatedObjects})))
                  for r in f.by_type("IfcRelAggregates"))
    out["aggregation"] = dict(agg)
    out["groups"] = [{"group": g.is_a(), "name": g.Name, "members": sum(len(r.RelatedObjects) for r in g.IsGroupedBy)}
                     for g in f.by_type("IfcGroup")]
    out["classifications"] = [{"name": c.Name, "source": c.Source} for c in f.by_type("IfcClassification")]
    out["classification_references"] = len(f.by_type("IfcClassificationReference"))
    out["units"] = [{"type": u.UnitType, "name": u.Name, "prefix": u.Prefix} for u in f.by_type("IfcSIUnit")]
    out["map_conversion"] = [m.get_info(recursive=False, include_identifier=False) for m in f.by_type("IfcMapConversion")]
    out["projected_crs"] = [c.get_info(recursive=False, include_identifier=False) for c in f.by_type("IfcProjectedCRS")]
    tree = []

    def walk(o, depth):
        tree.append("%s%s %s %s" % ("  " * depth, o.is_a(), getattr(o, "PredefinedType", "") or "", o.Name or ""))
        for c in ue.get_parts(o) or []:
            if depth < 6:
                walk(c, depth + 1)
    for p in f.by_type("IfcProject"):
        walk(p, 0)
    out["spatial_tree"] = tree[:200]
    out["post_step_needed_for"] = [k for k, v in {
        "classes": out["class_mismatches"] > 0,
        "railway_parts": "IfcRailwayPart" not in out["product_counts"],
        "containment_in_parts": not any(k.startswith("IfcRailwayPart") for k in cont),
        "built_system_group": not any(g["group"] == "IfcBuiltSystem" for g in out["groups"]),
        "classification": out["classification_references"] == 0,
        "quantity_sets": not any(k.startswith("IfcElementQuantity") for k in kinds),
        "georeferencing": not out["projected_crs"],
        "alignments": "IfcAlignment" not in out["product_counts"],
    }.items() if v]
    return out


def main(argv=None):
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ifc", default=cfg.file("ifc_bentley_export"))
    ap.add_argument("--out", default=repo_path("output/bentley_export_analysis.json"))
    a = ap.parse_args(argv)
    r = analyse(a.ifc)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(r, fh, ensure_ascii=False, indent=1, default=str)
    print("Exportanalys: %s" % a.out)
    print("Klasser: %s" % r["product_counts"])
    print("Klassavvikelser mot Item Types: %d, efterbearbetning behövs för: %s" % (
        r["class_mismatches"], ", ".join(r["post_step_needed_for"]) or "-"))
    return r


if __name__ == "__main__":
    main()
