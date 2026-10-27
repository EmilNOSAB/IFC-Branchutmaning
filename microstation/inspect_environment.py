"""Step 1: inspect the MicroStation environment (run inside MicroStation).

    python load "<repo>\\microstation\\inspect_environment.py"

Writes output/environment_report.json with
* MicroStation/Python versions and relevant configuration variables
* the Python API surface used by this project (dir() of the classes, enum
  members such as CustomProperty.Type, DgnRuledSweepDetail constructor doc)
* Bentley's IFC_Classes_Types.dgnlib / .xlsx and the iTwinIFCExporter files,
  including the delivered default SchemaMapping*.json files (copied to
  output/env/ so export/build_schema_mapping.py can use them as template)
* whether the 'IFC Classification' Item Type is present in the active DGN
* which Bentley GCS key names for SWEREF 99 18 00 resolve (nothing is written)

Search roots come from configuration/environment variables; no installation
path is hard-coded.
"""

from __future__ import annotations

import fnmatch
import json
import os
import platform
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_config, repo_path  # noqa: E402

CFG_VARS = ["_USTN_PRODUCT_RELEASE", "_USTN_PRODUCT_VERSION_GENERATION", "_ENGINENAME", "_USTN_INSTALLED",
            "MSDIR", "_USTN_PROGRAMDATA", "_USTN_CONFIGURATION", "MS_PYTHON", "MS_PYTHONSEARCHDIRECTORIES",
            "MS_DESIGNSEED", "MS_SEEDFILES", "MS_DGNLIBLIST", "MS_DGNLIBLIST_ITEMTYPES", "ITEMTYPE_LOOKUP",
            "MS_GEOCOORDINATE_DATA", "_USTN_WORKSPACENAME", "_USTN_WORKSETNAME"]
PATTERNS = ["IFC_Classes_Types*", "*SchemaMapping*.json", "*iTwinIFCExporter*", "*IfcExport*.json", "*Mapping*.json"]


def _is_mapping_template(path: str) -> bool:
    """A JSON(C) file that looks like an IFC export mapping (GlobalVariables or
    "Class" entries), found in a folder whose path mentions IFC."""
    if not path.lower().endswith(".json") or "ifc" not in path.lower():
        return False
    try:
        if os.path.getsize(path) > 20 * 1024 * 1024:
            return False
        with open(path, encoding="utf-8", errors="ignore") as fh:
            head = fh.read()
        return "GlobalVariables" in head or '"Class"' in head
    except OSError:
        return False


def _search_json_in_ifc_dirs(roots, max_depth=9, limit=100):
    hits = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.count(os.sep) - base_depth >= max_depth:
                dirnames[:] = []
            if "ifc" not in dirpath.lower():
                continue
            for name in filenames:
                full = os.path.join(dirpath, name)
                if _is_mapping_template(full):
                    hits.append(full)
                    if len(hits) >= limit:
                        return hits
    return hits
API_CLASSES = {
    "MSPyDgnPlatform": ["CustomProperty", "ItemTypeLibrary", "ItemType", "CustomItemHost", "DraftingElementSchema",
                        "NamedGroup", "DgnGCS", "BaseGCS", "FileLevelCache", "ElementPropertiesSetter"],
    "MSPyBentleyGeom": ["DgnRuledSweepDetail", "DgnBoxDetail", "PolyfaceHeader", "ISolidPrimitive", "CurveVector"],
    "MSPyMstnPlatform": ["ISessionMgr", "PyCadInputQueue", "PythonKeyinManager"],
}


def _search(roots, patterns, max_depth=7, limit=200):
    hits = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.count(os.sep) - base_depth >= max_depth:
                dirnames[:] = []
            for name in filenames + dirnames:
                if any(fnmatch.fnmatch(name, p) for p in patterns):
                    hits.append(os.path.join(dirpath, name))
                    if len(hits) >= limit:
                        return hits
    return hits


def main():
    report = {"python": sys.version, "platform": platform.platform(), "executable": sys.executable}
    try:
        import MSPyMstnPlatform  # noqa: F401
        inside = True
    except ImportError as e:
        inside = False
        report["microstation"] = "NOT AVAILABLE (%s) - run this script inside MicroStation" % e
    cfg = load_config()
    if inside:
        from microstation.msapi import get_config_variable
        report["config_variables"] = {v: get_config_variable(v) for v in CFG_VARS}
        api = {}
        for mod_name, classes in API_CLASSES.items():
            mod = __import__(mod_name)
            for cls_name in classes:
                cls = getattr(mod, cls_name, None)
                if cls is None:
                    api["%s.%s" % (mod_name, cls_name)] = "MISSING"
                    continue
                entry = {"members": [m for m in dir(cls) if not m.startswith("__")]}
                try:
                    entry["init_doc"] = (cls.__init__.__doc__ or "")[:2000]
                except Exception:
                    pass
                api["%s.%s" % (mod_name, cls_name)] = entry
        from MSPyDgnPlatform import CustomProperty
        for enum_name in ("Type", "Type1"):
            enum = getattr(CustomProperty, enum_name, None)
            if enum is not None:
                api["CustomProperty.%s members" % enum_name] = [m for m in dir(enum) if not m.startswith("_")]
        report["api"] = api
        # Bentley IFC Classification item type in the active DGN
        from microstation.msapi import MicroStationBackend
        be = MicroStationBackend()
        report["active_dgn"] = be.environment()
        report["active_model"] = be.check_model()
        report["bentley_ifc_classification_in_active_dgn"] = be.find_bentley_ifc_classification(
            cfg.mapping["bentley_ifc_classification"])
        # GCS key names (read only)
        from MSPyDgnPlatform import DgnGCS
        gcs = {}
        for key in cfg.model["coordinate_system"]["bentley_gcs_keynames"]:
            try:
                g = DgnGCS.CreateGCS(key, be.model_ref)
                gcs[key] = None if g is None else {"valid": bool(g.IsValid()) if hasattr(g, "IsValid") else None,
                                                   "epsg": g.GetEPSGCode(False), "name": str(g.GetName())}
            except Exception as e:
                gcs[key] = "exception: %s" % e
        report["gcs_candidates"] = gcs
        roots = [report["config_variables"].get(v) for v in ("_USTN_INSTALLED", "MSDIR", "_USTN_PROGRAMDATA",
                                                             "_USTN_CONFIGURATION")]
    else:
        roots = []
    for env in ("ProgramData", "ProgramFiles", "LOCALAPPDATA"):
        if os.environ.get(env):
            roots.append(os.path.join(os.environ[env], "Bentley"))
    roots = list(dict.fromkeys(r for r in roots if r))
    files = _search(roots, PATTERNS)
    report["bentley_files"] = files
    templates = list(dict.fromkeys([f for f in files if _is_mapping_template(f)] + _search_json_in_ifc_dirs(roots)))
    report["schema_mapping_candidates"] = templates
    env_dir = repo_path(os.path.join("output", "env"))
    os.makedirs(env_dir, exist_ok=True)
    copied = []
    for f in templates:
        if os.path.isfile(f):
            dst = os.path.join(env_dir, "%02d_%s" % (len(copied), os.path.basename(f)))
            shutil.copyfile(f, dst)
            copied.append({"source": f, "copy": dst})
    report["schema_mapping_templates"] = copied
    out = repo_path(os.path.join("output", "environment_report.json"))
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
    print("Miljörapport: %s" % out)
    print("Hittade Bentley-filer: %d, SchemaMapping-mallar: %d" % (len(files), len(copied)))
    return report


if __name__ == "__main__":
    main()
