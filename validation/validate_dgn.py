"""Validates the generated DGN content against the design model.

Inside MicroStation (output DGN active):
    python load "<repo>\\validation\\validate_dgn.py"
Offline self-test with the recording backend (no DGN):
    python validation/validate_dgn.py --dry-run

Checks every generated element read back from the DGN (Item Type values):
* each expected object exists exactly once, no unexpected generated objects
* IFC entity and PredefinedType as in config/object_mapping.yaml
* CoClass system/code as required by the IDS
* Pset/Qto values equal to the design model (quantities within tolerance)
* spatial parent exists, 4 PLAINTRACK + 2 TURNOUTTRACK carriers
* level as configured for the category
Writes output/dgn_validation_report.json.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_config, repo_path  # noqa: E402
from microstation.assign_metadata import item_values  # noqa: E402
from microstation.create_itemtypes import ITEM_TYPES, MARKER_ITEM_TYPE  # noqa: E402
from model.railway_model import RailwayModelBuilder  # noqa: E402

REQUIRED_CLASSIFICATION = {
    ("IfcRail", "RAIL"): {("CoClass_KO", "WRA20")}, ("IfcRail", "STOCKRAIL"): {("CoClass_KO", "WRA20")},
    ("IfcRail", "CHECKRAIL"): {("CoClass_KO", "WRA20")}, ("IfcTrackElement", "SLEEPER"): {("CoClass_KO", "ULE14")},
    ("IfcTrackElement", "FROG"): {("CoClass_KO", "WRA20")},
    ("IfcElementAssembly", "TRACTION_SWITCHING_ASSEMBLY"): {("CoClass_KO", "QSB")},
    ("IfcCourse", "BALLASTBED"): {("CoClass_KO", "UTA10"), ("CoClass_PR", "CEB.3")},
    ("IfcRailway", "USERDEFINED"): {("CoClass_BV", "CAE")}, ("IfcRailwayPart", "PLAINTRACK"): {("CoClass_KS", "DA10")},
    ("IfcRailwayPart", "TURNOUTTRACK"): {("CoClass_KS", "DA20")}, ("IfcBuiltSystem", "RAILWAYTRACK"): {("CoClass_FS", "R")},
}


def _eq(a, b, tol=1e-3):
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    return ("" if a is None else str(a)) == ("" if b is None else str(b))


def validate(rows, design, cfg) -> dict:
    expected = {c.object_id: c for c in design.components}
    seen = {}
    issues = []
    for r in rows:
        obj = r["items"].get("BU26_Object", {})
        oid = obj.get("BU26_ObjectId")
        if oid in seen:
            issues.append({"object_id": oid, "element_id": r["element_id"], "issue": "duplicate object id"})
        seen[oid] = r
        comp = expected.get(oid)
        if comp is None:
            issues.append({"object_id": oid, "element_id": r["element_id"], "issue": "not in design model"})
            continue
        want = dict(item_values(comp, cfg.mode, cfg.file("landxml")))
        for it, values in want.items():
            have = r["items"].get(it)
            if have is None:
                issues.append({"object_id": oid, "element_id": r["element_id"], "issue": "item type %s missing" % it})
                continue
            for k, v in values.items():
                if k in ("ModelMode", "SourceFile"):
                    continue
                if not _eq(have.get(k), v):
                    issues.append({"object_id": oid, "element_id": r["element_id"],
                                   "issue": "%s.%s = %r, expected %r" % (it, k, have.get(k), v)})
        key = (comp.ifc_entity, comp.predefined_type)
        if key in REQUIRED_CLASSIFICATION:
            cls = r["items"].get("BU26_Classification", {})
            got = {(cls.get("CoClassSystem"), cls.get("CoClassIdentification")),
                   (cls.get("CoClassSystem2"), cls.get("CoClassIdentification2"))}
            for need in REQUIRED_CLASSIFICATION[key]:
                if need not in got:
                    issues.append({"object_id": oid, "element_id": r["element_id"],
                                   "issue": "CoClass %s %s missing" % need})
        if comp.spatial_parent and comp.spatial_parent not in expected:
            issues.append({"object_id": oid, "element_id": r["element_id"], "issue": "spatial parent missing"})
        if "level" in r and r["level"] != comp.level:
            issues.append({"object_id": oid, "element_id": r["element_id"],
                           "issue": "level %s, expected %s" % (r["level"], comp.level)})
    missing = sorted(set(expected) - set(seen))
    parts = [r for r in rows if r["items"].get("BU26_Object", {}).get("IfcEntity") == "IfcRailwayPart"]
    pdts = sorted(r["items"]["BU26_Object"].get("IfcPredefinedType") for r in parts)
    if pdts != ["PLAINTRACK"] * 4 + ["TURNOUTTRACK"] * 2:
        issues.append({"object_id": "-", "issue": "railway parts %s, expected 4 PLAINTRACK + 2 TURNOUTTRACK" % pdts})
    by_cat = {}
    for r in rows:
        c = r["items"].get("BU26_Object", {}).get("ObjectCategory", "?")
        by_cat[c] = by_cat.get(c, 0) + 1
    return {"elements_checked": len(rows), "expected_objects": len(expected), "missing_objects": missing[:200],
            "missing_count": len(missing), "issues": issues[:500], "issue_count": len(issues),
            "by_category": by_cat, "ok": not missing and not issues}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mode", choices=("preview", "full"))
    args, _ = ap.parse_known_args(argv if argv is not None else sys.argv[1:])
    cfg = load_config(mode=args.mode)
    lib = cfg.mapping["item_type_library"]
    if args.dry_run:
        from microstation.backend import RecordingBackend
        from microstation.build_railway_dgn import run
        be = RecordingBackend()
        run(["--mode", cfg.mode, "--report", repo_path("output/dryrun/model_report.dryrun.json")], backend=be,
            log=lambda *a: None)
        out = repo_path("output/dryrun/dgn_validation_report.dryrun.json")
    else:
        from microstation.msapi import MicroStationBackend
        be = MicroStationBackend()
        # mode of the DGN content is taken from the elements themselves
        out = cfg.file("dgn_validation_report")
    rows = be.scan_generated(lib, MARKER_ITEM_TYPE, ITEM_TYPES)
    if rows:
        mode = rows[0]["items"].get("BU26_Object", {}).get("ModelMode") or cfg.mode
        if mode != cfg.mode:
            cfg = load_config(mode=mode)
    design = RailwayModelBuilder(cfg).build()
    result = validate(rows, design, cfg)
    result["backend"] = be.name
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print("DGN-validering: %s (%d element, %d avvikelser, %d saknas) -> %s" % (
        "OK" if result["ok"] else "AVVIKELSER", result["elements_checked"], result["issue_count"],
        result["missing_count"], out))
    return result


if __name__ == "__main__":
    main()
