"""Helpers shared by the export inspection and the validator (read only)."""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

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
import ifcopenshell.util.element  # noqa: E402

from microstation.create_itemtypes import ITEM_TYPES  # noqa: E402

ITEM_NAMES = set(ITEM_TYPES)


def item_type_of_pset(pset_name: str) -> Optional[str]:
    """Map an exported property set name to one of our Item Type names.  The
    exporter may prefix the Item Type with its library/schema name
    (e.g. 'BU2026_IFC:BU26_Object' or 'BU2026_IFC.BU26_Object')."""
    if pset_name in ITEM_NAMES:
        return pset_name
    for sep in (":", ".", "__", "/"):
        if sep in pset_name:
            tail = pset_name.split(sep)[-1]
            if tail in ITEM_NAMES:
                return tail
    for name in ITEM_NAMES:
        if pset_name.endswith(name):
            return name
    return None


def bu26_index(f: ifcopenshell.file) -> Dict[str, Dict[str, Any]]:
    """object_id -> {"entity": inst, "sets": {item_type: {prop: value}}, "pset_ids": {item_type: [ids]}}"""
    out: Dict[str, Dict[str, Any]] = {}
    dup: List[str] = []
    for obj in f.by_type("IfcObject"):
        psets = ifcopenshell.util.element.get_psets(obj)
        sets: Dict[str, Dict[str, Any]] = {}
        ids: Dict[str, List[int]] = {}
        for pname, props in psets.items():
            it = item_type_of_pset(pname)
            if it is None:
                continue
            vals = {k: v for k, v in props.items() if k != "id"}
            sets.setdefault(it, {}).update(vals)
            ids.setdefault(it, []).append(props.get("id"))
        oid = sets.get("BU26_Object", {}).get("BU26_ObjectId")
        if not oid:
            continue
        if oid in out:
            dup.append(oid)
        out[oid] = {"entity": obj, "sets": sets, "pset_ids": ids}
    if dup:
        raise ValueError("BU26 object ids occur on more than one IFC object: %s" % sorted(set(dup))[:20])
    return out


def entity_label(e) -> str:
    return "#%d=%s(%s)" % (e.id(), e.is_a(), getattr(e, "Name", ""))
