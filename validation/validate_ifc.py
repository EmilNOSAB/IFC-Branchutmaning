"""IDS validation of the exported IFC (IfcOpenShell + IfcTester).

    python validation/validate_ifc.py [--ifc output/Branschutmaningen_2026.ifc]
                                      [--ids input/Branschutmaningen_2026.ids]
                                      [--html output/validation_report.html] [--json output/validation_report.json]

Reads and validates only; it never creates the IFC.  Reports
* all 22 IDS specifications: passed/failed, applicable entities, every failing
  requirement grouped as entity class / attribute / property set / quantity
  set / classification / relationship, and specifications without any
  applicable entity (missing entities)
* every failure linked to the DGN object id (BU26_ObjectId Item Type value) and GlobalId
* failures that are forced by contradictory IDS specifications (validation/ids_conflicts.py)
* additional structural checks (proxies, containment, groups, alignments,
  georeferencing, units, IFC schema validity)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import sys
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ifcopenshell  # noqa: E402
import ifcopenshell.util.element  # noqa: E402

from common.config import load_config, repo_path  # noqa: E402
from validation.ids_conflicts import find_conflicts, parse as parse_ids  # noqa: E402

GROUPS = {
    "entity": "Felaktiga klasser / PredefinedType",
    "attribute": "Saknade eller felaktiga attribut",
    "property": "Felaktiga eller saknade Property Sets",
    "quantity": "Saknade Quantity Sets",
    "classification": "Saknade klassificeringar",
    "partof": "Felaktiga relationer",
}


def _group(req: Dict[str, Any]) -> str:
    ft = (req.get("facet_type") or "").lower()
    if ft == "property":
        meta = json.dumps(req.get("metadata", {}), default=str) + req.get("description", "")
        return "quantity" if "Qto_" in meta else "property"
    return {"entity": "entity", "attribute": "attribute", "classification": "classification",
            "partof": "partof"}.get(ft, ft or "other")


def object_ids(f: ifcopenshell.file) -> Dict[str, str]:
    """GlobalId -> BU26_ObjectId (the DGN element identity exported from the Item Types)."""
    out = {}
    for obj in f.by_type("IfcObject"):
        for props in ifcopenshell.util.element.get_psets(obj).values():
            oid = props.get("BU26_ObjectId")
            if oid:
                out[obj.GlobalId] = oid
                break
    return out


def structural_checks(f: ifcopenshell.file, cfg) -> Dict[str, Any]:
    chk: Dict[str, Any] = {}
    chk["schema"] = f.schema_identifier
    chk["projects"] = len(f.by_type("IfcProject"))
    proxies = f.by_type("IfcBuildingElementProxy")
    chk["proxies"] = len(proxies)
    parts = f.by_type("IfcRailwayPart")
    chk["railway_parts"] = sorted(p.PredefinedType for p in parts)
    chk["railway_parts_ok"] = chk["railway_parts"] == ["PLAINTRACK"] * 4 + ["TURNOUTTRACK"] * 2
    chk["alignments"] = [{"name": a.Name, "layouts": [r.RelatedObjects[0].is_a() if r.RelatedObjects else None
                                                      for r in a.IsNestedBy]}
                         for a in f.by_type("IfcAlignment") if not ifcopenshell.util.element.get_aggregate(a)
                         or ifcopenshell.util.element.get_aggregate(a).is_a("IfcProject")]
    phys = [e for e in f.by_type("IfcElement")]
    uncontained = [e.GlobalId for e in phys if not ifcopenshell.util.element.get_container(e)
                   and not ifcopenshell.util.element.get_aggregate(e)]
    chk["elements"] = len(phys)
    chk["elements_without_spatial_relation"] = len(uncontained)
    bs = f.by_type("IfcBuiltSystem")
    chk["built_systems"] = [{"name": b.Name, "type": b.PredefinedType,
                             "members": sum(len(r.RelatedObjects) for r in b.IsGroupedBy)} for b in bs]
    chk["classification_relations"] = len(f.by_type("IfcRelAssociatesClassification"))
    chk["element_quantities"] = sorted({q.Name for q in f.by_type("IfcElementQuantity")})
    crs = f.by_type("IfcProjectedCRS")
    chk["projected_crs"] = [{"name": c.Name, "description": c.Description, "vertical": c.VerticalDatum} for c in crs]
    mc = f.by_type("IfcMapConversion")
    chk["map_conversion"] = [{"eastings": m.Eastings, "northings": m.Northings, "height": m.OrthogonalHeight}
                             for m in mc]
    chk["length_units"] = [{"name": u.Name, "prefix": u.Prefix} for u in f.by_type("IfcSIUnit")
                           if u.UnitType == "LENGTHUNIT"]
    try:
        from ifcopenshell import validate as ifc_validate
        logger = ifc_validate.json_logger()
        ifc_validate.validate(f, logger)
        chk["schema_validation_issues"] = len(logger.statements)
        chk["schema_validation_sample"] = [str(s)[:300] for s in logger.statements[:20]]
    except Exception as e:  # pragma: no cover
        chk["schema_validation_error"] = str(e)
    return chk


def validate(ifc_path: str, ids_path: str) -> Dict[str, Any]:
    from ifctester import ids as ids_mod
    from ifctester import reporter
    f = ifcopenshell.open(ifc_path)
    spec = ids_mod.open(ids_path)
    spec.validate(f)
    res = reporter.Json(spec).report()
    gid2oid = object_ids(f)
    conflicts = find_conflicts(parse_ids(ids_path))
    conflict_specs: Dict[str, List[str]] = {}
    for c in conflicts:
        conflict_specs.setdefault(c["spec_a"], []).append("%s (%s)" % (c["spec_b"], "; ".join(c["reasons"])))
        conflict_specs.setdefault(c["spec_b"], []).append("%s (%s)" % (c["spec_a"], "; ".join(c["reasons"])))
    specs = []
    summary_groups: Dict[str, int] = {k: 0 for k in GROUPS}
    missing_entities = []
    for sp in res["specifications"]:
        reqs = []
        for rq in sp["requirements"]:
            fails = []
            for fe in rq.get("failed_entities") or []:
                gid = fe.get("global_id")
                fails.append({"global_id": gid, "dgn_object_id": gid2oid.get(gid), "class": fe.get("class"),
                              "predefined_type": fe.get("predefined_type"), "name": fe.get("name"),
                              "reason": fe.get("reason")})
            g = _group(rq)
            if not rq["status"]:
                summary_groups[g] = summary_groups.get(g, 0) + 1
            reqs.append({"description": rq["description"], "facet": rq.get("facet_type"), "group": g,
                         "status": rq["status"], "failed": len(fails), "passed": rq.get("total_pass"),
                         "failures": fails[:200]})
        applicable = sp.get("total_applicable", 0)
        if applicable == 0:
            missing_entities.append(sp["name"])
        specs.append({"name": sp["name"], "status": sp["status"], "applicable": applicable,
                      "applicable_pass": sp.get("total_applicable_pass"), "requirements": reqs,
                      "ids_conflicts": conflict_specs.get(sp["name"], [])})
    return {
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "ifc": os.path.abspath(ifc_path), "ids": os.path.abspath(ids_path),
        "ifc_application": getattr(f.header.file_name, "originating_system", ""),
        "total_specifications": res["total_specifications"], "passed": res["total_specifications_pass"],
        "failed": res["total_specifications_fail"],
        "passed_specs": [s["name"] for s in specs if s["status"]],
        "failed_specs": [s["name"] for s in specs if not s["status"]],
        "failed_specs_only_due_to_ids_conflicts": [
            s["name"] for s in specs if not s["status"] and s["ids_conflicts"] and _only_conflict_failures(s)],
        "missing_entities": missing_entities, "failed_requirement_groups": summary_groups,
        "ids_conflicts": conflicts, "structure": structural_checks(f, None), "specifications": specs,
    }


def _only_conflict_failures(spec: Dict[str, Any]) -> bool:
    """True when every failing requirement of the spec is one that the IDS itself
    makes impossible (the Description value or the PLAINTRACK/TURNOUTTRACK parent
    named in a conflicting specification)."""
    for rq in spec["requirements"]:
        if rq["status"]:
            continue
        d = rq["description"]
        if rq["facet"] in ("Attribute",) and "Description" in d:
            continue
        if rq["facet"] in ("PartOf",) and "IFCRAILWAYPART" in d.upper():
            continue
        return False
    return True


def to_html(r: Dict[str, Any]) -> str:
    e = html.escape
    rows = []
    for s in r["specifications"]:
        cls = "ok" if s["status"] else ("conf" if s["name"] in r["failed_specs_only_due_to_ids_conflicts"] else "bad")
        reqs = []
        for q in s["requirements"]:
            fl = ""
            if q["failures"]:
                items = "".join("<li><code>%s</code> %s %s - %s</li>" % (
                    e(str(x["dgn_object_id"] or "-")), e(str(x["class"])), e(str(x["global_id"])), e(str(x["reason"])))
                    for x in q["failures"][:15])
                more = "<li>... %d till</li>" % (q["failed"] - 15) if q["failed"] > 15 else ""
                fl = "<details><summary>%d underkända</summary><ul>%s%s</ul></details>" % (q["failed"], items, more)
            reqs.append("<tr class='%s'><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                "ok" if q["status"] else "bad", e(GROUPS.get(q["group"], q["group"])), e(q["description"]),
                "Godkänd" if q["status"] else "Underkänd", fl))
        conf = "<p class='note'>Motsägelse i IDS: %s</p>" % e("; ".join(s["ids_conflicts"])) if s["ids_conflicts"] else ""
        rows.append("<section class='%s'><h3>%s - %s</h3><p>Tillämpliga entiteter: %s (godkända %s)</p>%s"
                    "<table><tr><th>Grupp</th><th>Krav</th><th>Status</th><th>Detaljer</th></tr>%s</table></section>" % (
                        cls, e(s["name"]), "GODKÄND" if s["status"] else "UNDERKÄND", s["applicable"],
                        s["applicable_pass"], conf, "".join(reqs)))
    st = r["structure"]
    struct = "".join("<tr><td>%s</td><td><code>%s</code></td></tr>" % (e(k), e(json.dumps(v, ensure_ascii=False,
                                                                                           default=str)[:600]))
                     for k, v in st.items())
    groups = "".join("<li>%s: %d</li>" % (e(GROUPS.get(k, k)), v) for k, v in r["failed_requirement_groups"].items())
    return """<!doctype html><html lang="sv"><head><meta charset="utf-8"><title>IDS-validering</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}h1{font-size:22px}
section{border-left:6px solid #999;padding:4px 12px;margin:14px 0;background:#fafafa}
section.ok{border-color:#2e7d32}section.bad{border-color:#c62828}section.conf{border-color:#ef6c00}
table{border-collapse:collapse;width:100%%;font-size:13px}td,th{border:1px solid #ddd;padding:4px;vertical-align:top}
tr.ok td:nth-child(3){color:#2e7d32}tr.bad td:nth-child(3){color:#c62828;font-weight:bold}
.note{color:#ef6c00}code{font-size:12px}</style></head><body>
<h1>IDS-validering - Branschutmaningen 2026</h1>
<p>IFC: <code>%s</code><br>Skapad av: <code>%s</code><br>IDS: <code>%s</code><br>%s</p>
<p><b>%d av %d specifikationer godkända.</b> Underkända enbart p.g.a. motsägelser i IDS: %s</p>
<p>Specifikationer utan tillämpliga entiteter (saknade entiteter): %s</p>
<h2>Underkända krav per grupp</h2><ul>%s</ul>
<h2>Specifikationer</h2>%s
<h2>Strukturkontroller</h2><table>%s</table></body></html>""" % (
        e(r["ifc"]), e(str(r["ifc_application"])), e(r["ids"]), e(r["generated"]), r["passed"],
        r["total_specifications"], e(", ".join(r["failed_specs_only_due_to_ids_conflicts"]) or "-"),
        e(", ".join(r["missing_entities"]) or "-"), groups, "".join(rows), struct)


def main(argv=None):
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ifc", default=cfg.file("ifc_output"))
    ap.add_argument("--ids", default=cfg.file("ids"))
    ap.add_argument("--html", default=cfg.file("validation_report_html"))
    ap.add_argument("--json", default=cfg.file("validation_report_json"))
    args = ap.parse_args(argv)
    if not os.path.exists(args.ifc):
        raise SystemExit("IFC file %s not found - export it from MicroStation first" % args.ifc)
    r = validate(args.ifc, args.ids)
    os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(r, fh, ensure_ascii=False, indent=1, default=str)
    with open(args.html, "w", encoding="utf-8") as fh:
        fh.write(to_html(r))
    print("IDS: %d/%d specifikationer godkända. Underkända: %s" % (r["passed"], r["total_specifications"],
                                                                  ", ".join(r["failed_specs"]) or "-"))
    print("Underkända enbart p.g.a. IDS-motsägelser: %s" % (", ".join(r["failed_specs_only_due_to_ids_conflicts"]) or "-"))
    print("Rapporter: %s, %s" % (args.html, args.json))
    return r


if __name__ == "__main__":
    main()
