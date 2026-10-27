"""Branschutmaningen 2026 - builds the 3D railway DGN in MicroStation.

Run inside MicroStation (2024/2025, MicroStation Python 3.12) with the output
DGN open as the active 3D design file:

    Key-in:  python load "<repo>\\microstation\\build_railway_dgn.py"

or from the Python Manager (Utilities > Python Manager > Load, Run).
Mode (preview | full) comes from config/model_config.yaml (``mode``), the
environment variable or MicroStation configuration variable ``BU26_MODE``.

Outside MicroStation the same script runs as a dry run with an in-memory
recording backend (no DGN is written):

    python microstation/build_railway_dgn.py --dry-run [--mode preview]

Steps
  1. read configuration                 7. create Item Types (+ find Bentley IFC Classification)
  2. check that MicroStation is there   8. create all 3D components with Item Types
  3. check the active 3D DGN            9. named groups (railway parts, turnouts, built system)
  4. read LandXML                      10. save the DGN
  5. compute track geometry/model      11. basic model check (read back from the DGN)
  6. purge earlier output, levels, GCS  12. write output/model_report.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_config, repo_path  # noqa: E402
from microstation import (create_ballast, create_rails, create_sleepers, create_spatial,  # noqa: E402
                          create_turnout)
from microstation.backend import BackendError, RecordingBackend  # noqa: E402
from microstation.context import BuildContext  # noqa: E402
from microstation.create_itemtypes import ITEM_TYPES, MARKER_ITEM_TYPE, check_spec_against_mapping  # noqa: E402
from microstation.create_levels import create_levels  # noqa: E402
from model.railway_model import RailwayModelBuilder  # noqa: E402


def _resolve_mode(cli_mode, backend_is_ms):
    if cli_mode:
        return cli_mode
    env = os.environ.get("BU26_MODE")
    if env:
        return env
    if backend_is_ms:
        try:
            from microstation.msapi import get_config_variable
            v = get_config_variable("BU26_MODE")
            if v:
                return v
        except Exception:
            pass
    return None


def create_named_groups(ctx, design) -> int:
    members = {}
    for c in design.components:
        eid = ctx.element_ids.get(c.object_id)
        if eid is None:
            continue
        for g in c.groups:
            members.setdefault(g, []).append(eid)
    desc = {p.object_id: "IfcRailwayPart %s %s" % (p.predefined_type, p.long_name) for p in design.parts}
    bs = ctx.cfg.model["built_system"]
    desc[bs["id"]] = "IfcBuiltSystem RAILWAYTRACK %s (gruppering av spårdelar)" % bs["name"]
    for t in ctx.cfg.model["turnouts"]:
        desc[t["id"]] = "Spårväxel %s" % t["name"]
    n = 0
    for name, ids in sorted(members.items()):
        try:
            ctx.backend.create_named_group("BU26_%s" % name, desc.get(name, name), ids)
            n += 1
        except Exception as e:
            ctx.errors.append("named group %s: %s" % (name, e))
    return n


def basic_model_check(ctx, design) -> dict:
    """Read the generated elements back from the DGN and compare with the design."""
    from microstation.create_itemtypes import ITEM_TYPES as SPEC
    try:
        rows = ctx.backend.scan_generated(ctx.library, MARKER_ITEM_TYPE, SPEC)
    except TypeError:
        rows = ctx.backend.scan_generated(ctx.library, MARKER_ITEM_TYPE)
    expected = {}
    for c in design.components:
        expected[c.category] = expected.get(c.category, 0) + 1
    found = {}
    ids = set()
    missing_items = []
    for r in rows:
        obj = r["items"].get("BU26_Object", {})
        found[obj.get("ObjectCategory", "?")] = found.get(obj.get("ObjectCategory", "?"), 0) + 1
        ids.add(obj.get("BU26_ObjectId"))
        if obj.get("IfcEntity") in ("IfcRail", "IfcTrackElement", "IfcCourse", "IfcElementAssembly") and \
                "BU26_Classification" not in r["items"]:
            missing_items.append(obj.get("BU26_ObjectId"))
    dups = len(rows) - len(ids)
    return {
        "elements_read_back": len(rows),
        "by_category_expected": expected,
        "by_category_found": found,
        "category_mismatch": {k: (expected.get(k, 0), found.get(k, 0))
                              for k in set(expected) | set(found) if expected.get(k, 0) != found.get(k, 0)},
        "duplicate_object_ids": dups,
        "physical_without_classification": missing_items[:50],
        "ok": not dups and not missing_items and all(expected.get(k, 0) == found.get(k, 0)
                                                    for k in set(expected) | set(found)),
    }


def run(argv=None, backend=None, log=print) -> dict:
    ap = argparse.ArgumentParser(description="Build the Branschutmaningen 2026 DGN")
    ap.add_argument("--mode", choices=("preview", "full"))
    ap.add_argument("--dry-run", action="store_true", help="no MicroStation: record instead of writing a DGN")
    ap.add_argument("--config", default=None)
    ap.add_argument("--report", default=None, help="report path (default from config)")
    # MicroStation passes its own argv; ignore unknown entries
    args, _ = ap.parse_known_args(argv if argv is not None else sys.argv[1:])

    t_all = time.perf_counter()
    timings = {}

    def step(name):
        timings[name] = time.perf_counter()

    def done(name):
        timings[name] = round(time.perf_counter() - timings[name], 3)
        log("%-40s %8.2f s" % (name, timings[name]))

    # 1-2. backend
    if backend is None:
        if args.dry_run:
            backend = RecordingBackend()
        else:
            from microstation.msapi import MICROSTATION_AVAILABLE, IMPORT_ERROR, MicroStationBackend
            if not MICROSTATION_AVAILABLE:
                raise SystemExit("MicroStation Python API not available (%s). Run inside MicroStation or use "
                                 "--dry-run." % IMPORT_ERROR)
            backend = MicroStationBackend(log=log)
    is_ms = backend.__class__.__name__ == "MicroStationBackend"
    step("1. Läs konfiguration")
    cfg = load_config(args.config, mode=_resolve_mode(args.mode, is_ms))
    problems = check_spec_against_mapping(cfg.mapping)
    if problems:
        raise SystemExit("Item Type spec does not match object_mapping.yaml: %s" % problems)
    done("1. Läs konfiguration")
    log("Läge: %s, backend: %s" % (cfg.mode, backend.name))

    report = {"generated": _dt.datetime.now().isoformat(timespec="seconds"), "backend": backend.name,
              "dry_run": not is_ms, "mode": cfg.mode, "errors": [], "warnings": []}

    # 3. model checks
    step("2-3. Kontrollera MicroStation och DGN")
    report["environment"] = backend.environment()
    report["model_check"] = backend.check_model()
    if not report["model_check"].get("is3d", False):
        raise SystemExit("The active model is not 3D. Create the DGN from a 3D seed file.")
    label = str(report["model_check"].get("master_unit_label", "m"))
    if is_ms and label.strip().lower() not in ("m", "meter", "meters", "metre", "metres"):
        report["warnings"].append("Master unit is %r, expected metres (IDS #20 requires METRE without prefix "
                                  "in the IFC export)" % label)
    done("2-3. Kontrollera MicroStation och DGN")

    # 4-5. design model
    step("4-5. LandXML + spårgeometri + komponenter")
    builder = RailwayModelBuilder(cfg)
    design = builder.build()
    report["design"] = design.report
    report["warnings"].extend(design.report.get("warnings", []))
    done("4-5. LandXML + spårgeometri + komponenter")

    # 6. purge / levels / GCS
    library = cfg.mapping["item_type_library"]
    step("6. Rensa tidigare genererade element")
    if cfg.model["dgn"].get("rebuild_strategy", "purge") == "purge":
        report["purged_elements"] = backend.purge_generated(library, MARKER_ITEM_TYPE)
        log("  borttagna element från tidigare körning: %s" % report["purged_elements"])
    done("6. Rensa tidigare genererade element")
    step("6. Nivåer")
    level_ids = create_levels(backend, cfg.levels)
    done("6. Nivåer")
    step("6. Koordinatsystem")
    report["coordinate_system"] = backend.set_coordinate_system(cfg.model["coordinate_system"])
    done("6. Koordinatsystem")

    # 7. item types
    step("7. Item Types")
    report["item_types"] = backend.ensure_item_types(library, ITEM_TYPES)
    bic = cfg.mapping["bentley_ifc_classification"]
    found = backend.find_bentley_ifc_classification(bic) if bic.get("enabled", True) else None
    report["bentley_ifc_classification"] = found or (
        "NOT FOUND - import %s into the DGN (Item Types dialog > Import) to let the Bentley exporter "
        "classify the elements; see docs/Korinstruktion_MicroStation.md" % bic["dgnlib_file"])
    if not found:
        report["warnings"].append("Bentley 'IFC Classification' Item Type not present in the DGN")
    done("7. Item Types")

    ctx = BuildContext(cfg=cfg, backend=backend, level_ids=level_ids, library=library, mode=cfg.mode,
                       source_file=cfg.file("landxml"), bentley_ifc=found, log=log)

    # 8. components
    step("8. Skapa 3D-komponenter")
    backend.begin_bulk()
    try:
        create_spatial.create(ctx, design)
        create_ballast.create(ctx, design)
        create_sleepers.create(ctx, design)
        create_rails.create(ctx, design)
        create_turnout.create(ctx, design)
    finally:
        backend.end_bulk()
    done("8. Skapa 3D-komponenter")

    # 9. groups
    step("9. Logiska grupper")
    if cfg.model["dgn"].get("create_named_groups", True):
        report["named_groups"] = create_named_groups(ctx, design)
    done("9. Logiska grupper")

    # 10. save
    step("10. Spara DGN")
    if cfg.model["dgn"].get("save_after_build", True):
        backend.save()
    done("10. Spara DGN")

    # 11. check
    step("11. Modellkontroll")
    report["model_check_after_build"] = basic_model_check(ctx, design)
    done("11. Modellkontroll")

    report["created_by_category"] = ctx.counts
    report["created_total"] = sum(ctx.counts.values())
    report["timings_s"] = dict(timings, **{"placement:" + k: round(v, 3) for k, v in ctx.timings.items()})
    report["errors"] = ctx.errors
    report["element_ids"] = ctx.element_ids
    report["total_time_s"] = round(time.perf_counter() - t_all, 3)
    out = args.report or (cfg.file("model_report") if is_ms else
                          repo_path(os.path.join("output", "dryrun", "model_report.dryrun.json")))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
    log("Rapport: %s" % out)
    log("Skapade element: %d, fel: %d, varningar: %d, kontroll ok: %s" % (
        report["created_total"], len(ctx.errors), len(report["warnings"]), report["model_check_after_build"]["ok"]))
    return report


def main():
    try:
        run()
    except SystemExit as e:
        print("AVBRUTET: %s" % e)
        if __name__ == "__main__" and not _inside_microstation():
            raise
    except BackendError as e:
        print("MicroStation-fel: %s" % e)
        traceback.print_exc()
    except Exception:
        traceback.print_exc()


def _inside_microstation() -> bool:
    try:
        import MSPyMstnPlatform  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    main()
