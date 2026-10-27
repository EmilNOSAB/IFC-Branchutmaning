"""Item Type values for a design-model component (pure Python) and their
attachment to a DGN element through the backend."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from model.components import Component

from .create_itemtypes import ITEM_TYPES


def _num(v: Optional[float]) -> float:
    return float(v) if v is not None else 0.0


def item_values(comp: Component, mode: str, source_file: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Return [(item_type, {property: value})] for one component."""
    a = comp.attributes
    obj = {
        "BU26_ObjectId": comp.object_id,
        "ObjectCategory": comp.category,
        "IfcEntity": comp.ifc_entity,
        "IfcPredefinedType": comp.predefined_type or a.get("PredefinedType", ""),
        "IfcObjectType": comp.object_type or "",
        "IfcName": comp.name,
        "IfcDescription": comp.description or "",
        "IfcLongName": comp.long_name or "",
        "SpatialParent": comp.spatial_parent or "",
        "SpatialRelation": comp.spatial_relation,
        "RailwayPartId": comp.railway_part_id or "",
        "AlignmentId": comp.alignment_id or "",
        "StartStation": _num(comp.station_from),
        "EndStation": _num(comp.station_to),
        "Track": str(a.get("Track", "")),
        "Side": str(a.get("Side", "")),
        "RailPosition": str(a.get("Position", "")),
        "TurnoutId": str(a.get("Turnout", "")),
        "GroupIds": ";".join(comp.groups),
        "Material": str(a.get("Material", "")),
        "Phase": str(a.get("Phase", "")),
        "UsageType": str(a.get("UsageType", "")),
        "RefLatitude": _num(a.get("RefLatitude")),
        "RefLongitude": _num(a.get("RefLongitude")),
        "RefElevation": _num(a.get("RefElevation")),
        "LandTitleNumber": str(a.get("LandTitleNumber", "")),
        "ModelMode": mode,
        "SourceFile": os.path.basename(source_file),
    }
    items: List[Tuple[str, Dict[str, Any]]] = [("BU26_Object", obj)]
    if comp.classifications:
        cls: Dict[str, Any] = {}
        for i, (system, code, name) in enumerate(comp.classifications[:2]):
            suffix = "" if i == 0 else "2"
            cls["CoClassSystem" + suffix] = system
            cls["CoClassIdentification" + suffix] = code
            cls["CoClassName" + suffix] = name
        items.append(("BU26_Classification", cls))
    for sets in (comp.psets, comp.qtos):
        for set_name, values in sets.items():
            if set_name not in ITEM_TYPES:
                raise KeyError("No Item Type for %s (component %s)" % (set_name, comp.object_id))
            items.append((set_name, dict(values)))
    return items


def bentley_ifc_values(comp: Component, found: Optional[Dict[str, Any]], version_value: str,
                       apply_to: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Values for Bentley's delivered 'IFC Classification' Item Type."""
    if not found or (apply_to is not None and comp.ifc_entity not in apply_to):
        return None
    props = found.get("properties", {})
    values = {}
    if "version" in props:
        values[props["version"]] = version_value
    if "class" in props:
        values[props["class"]] = comp.ifc_entity
    pdt = comp.predefined_type or comp.attributes.get("PredefinedType")
    if "type" in props and pdt:
        values[props["type"]] = pdt
    return {"library": found["library"], "item_type": found["item_type"], "values": values}


def attach(backend, element, comp: Component, library: str, mode: str, source_file: str,
           bentley_found: Optional[Dict[str, Any]], version_value: str, apply_to: Optional[List[str]] = None) -> None:
    backend.attach_items(element, library, item_values(comp, mode, source_file),
                         bentley_ifc_values(comp, bentley_found, version_value, apply_to))
