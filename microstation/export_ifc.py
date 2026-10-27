"""IFC 4.3 export step (run inside MicroStation 2025+ with the built DGN active).

    python load "<repo>\\microstation\\export_ifc.py"

MicroStation 2025 exports IFC with the (Technology Preview) iTwin IFC
exporter: File > Export > Exchange File Types > IFC (*.ifc), or the key-ins
``mdl load Bentley.Interchange.iTwinIFCExporter`` followed by
``IFC ITWINEXPORT`` (MicroStation 2025 help, "(Technology Preview) To export
DGN file to IFC format").  The dialog asks for IFC version, output file and
Schema Mapping File.  No programmatic export API is documented, so this
script

1. checks the prerequisites in the active DGN (generated elements present,
   Bentley 'IFC Classification' Item Type present, GCS, master unit),
2. validates export/SchemaMapping.json (JSON with /* */ comments) and copies it
   next to the DGN (output/SchemaMapping.json),
3. opens the exporter dialog with the documented key-ins (no screen-position
   macros), and
4. prints and writes the exact dialog settings to output/export_instructions.txt.

After exporting, run ``python export/complete_ifc_structure.py`` (explicit,
separate post step) and ``python validation/validate_ifc.py`` with a normal
Python that has IfcOpenShell.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_config, repo_path  # noqa: E402
from microstation.create_itemtypes import ITEM_TYPES, MARKER_ITEM_TYPE  # noqa: E402

KEYINS = ["mdl load Bentley.Interchange.iTwinIFCExporter", "IFC ITWINEXPORT"]


def strip_json_comments(text: str) -> str:
    """Remove /* ... */ and // comments outside strings (Bentley's mapping files use /* */)."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def load_jsonc(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", strip_json_comments(fh.read())))


def instructions(cfg, mapping_copy: str) -> str:
    ifc_out = cfg.file("ifc_bentley_export")
    return "\n".join([
        "IFC-export i MicroStation 2025 (Technology Preview iTwin IFC Exporter)",
        "",
        "1. Öppna exportdialogen: File > Export > Exchange File Types > IFC (*.ifc)",
        "   eller key-in: %s, därefter %s" % tuple(KEYINS),
        "   (första gången: uppdatera iModel Connector när MicroStation frågar, klicka Continue)",
        "2. IFC Version: välj IFC 4.3 (IFC4X3_ADD2) i listan.",
        "3. Output file: %s" % ifc_out,
        "4. Schema Mapping File: Browse -> %s" % mapping_copy,
        "   (filen genereras/valideras av export/build_schema_mapping.py)",
        "5. Klicka Export.",
        "",
        "Efter export (vanlig Python med IfcOpenShell):",
        "  python export/inspect_bentley_export.py   -> vilka klasser/relationer exportören skapade",
        "  python export/complete_ifc_structure.py   -> separat, uttryckligt efterbearbetningssteg",
        "  python validation/validate_ifc.py         -> IDS-validering, HTML/JSON-rapport",
    ])


def main():
    cfg = load_config()
    report = {"checks": {}, "warnings": []}
    mapping_src = cfg.file("schema_mapping")
    try:
        mapping = load_jsonc(mapping_src)
        report["checks"]["schema_mapping_parses"] = True
        report["checks"]["schema_mapping_sections"] = sorted(mapping) if isinstance(mapping, dict) else type(mapping).__name__
    except Exception as e:
        report["checks"]["schema_mapping_parses"] = "ERROR: %s" % e
    mapping_copy = repo_path(os.path.join("output", "SchemaMapping.json"))
    os.makedirs(os.path.dirname(mapping_copy), exist_ok=True)
    shutil.copyfile(mapping_src, mapping_copy)

    try:
        from microstation.msapi import MICROSTATION_AVAILABLE, MicroStationBackend
    except ImportError:
        MICROSTATION_AVAILABLE = False
    if MICROSTATION_AVAILABLE:
        be = MicroStationBackend()
        lib = cfg.mapping["item_type_library"]
        rows = be.scan_generated(lib, MARKER_ITEM_TYPE, {"BU26_Object": ITEM_TYPES["BU26_Object"]})
        report["checks"]["generated_elements"] = len(rows)
        if not rows:
            report["warnings"].append("No generated elements in the active DGN - run build_railway_dgn.py first")
        found = be.find_bentley_ifc_classification(cfg.mapping["bentley_ifc_classification"])
        report["checks"]["bentley_ifc_classification"] = found or "MISSING"
        if not found:
            report["warnings"].append("Bentley 'IFC Classification' Item Type missing: elements will be exported "
                                      "as proxies unless the mapping file classifies them")
        report["checks"]["model"] = be.check_model()
        from MSPyDgnPlatform import DgnGCS
        g = DgnGCS.FromModel(be.model_ref, True)
        report["checks"]["gcs"] = None if g is None else {"name": str(g.GetName()), "epsg": g.GetEPSGCode(False)}
        if g is None:
            report["warnings"].append("No GCS assigned to the model")
        from MSPyMstnPlatform import PyCadInputQueue
        for k in KEYINS:
            PyCadInputQueue.SendKeyin(k)
        report["keyins_sent"] = KEYINS
    else:
        report["warnings"].append("MicroStation not available - only the mapping file was checked")
    text = instructions(cfg, mapping_copy)
    with open(repo_path(os.path.join("output", "export_instructions.txt")), "w", encoding="utf-8") as fh:
        fh.write(text + "\n\n" + json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(text)
    for w in report["warnings"]:
        print("VARNING:", w)
    return report


if __name__ == "__main__":
    main()
