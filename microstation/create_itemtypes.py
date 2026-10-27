"""Item Type library BU2026_IFC.

Design rules
------------
* One library (``BU2026_IFC``) created directly in the DGN by the build script
  (it can be exported to a DGNLIB from the Item Types dialog for reuse).
* ``BU26_Object``: identity, IFC entity/PredefinedType/attributes, spatial
  parent and stationing of every generated element.  It is also the marker
  used to find generated elements again (purge, validation, IFC post step).
* ``BU26_Classification``: up to two CoClass references (ballast needs two).
* Property and quantity sets are Item Types named exactly like the IFC sets
  (``Pset_RailwayTrackStructurePart``, ``Qto_CourseBaseQuantities`` ...) with
  properties named exactly like the IFC properties, so that an export that
  writes Item Types as property sets produces the IFC names directly.
* Only String, Boolean, Integer and Double property types are used (the
  basic Item Type types; no units/expressions), which every IFC/iModel
  connector can read.  The IFC measure types (IfcLengthMeasure ...) are listed
  in config/object_mapping.yaml and applied by export/complete_ifc_structure.py.

Bentley's delivered ``IFC Classification`` Item Type (IFC_Classes_Types.dgnlib)
is attached in addition, when it has been imported into the DGN.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

MARKER_ITEM_TYPE = "BU26_Object"

ITEM_TYPES: Dict[str, List[Tuple[str, str]]] = {
    "BU26_Object": [
        ("BU26_ObjectId", "String"),
        ("ObjectCategory", "String"),
        ("IfcEntity", "String"),
        ("IfcPredefinedType", "String"),
        ("IfcObjectType", "String"),
        ("IfcName", "String"),
        ("IfcDescription", "String"),
        ("IfcLongName", "String"),
        ("SpatialParent", "String"),
        ("SpatialRelation", "String"),
        ("RailwayPartId", "String"),
        ("AlignmentId", "String"),
        ("StartStation", "Double"),
        ("EndStation", "Double"),
        ("Track", "String"),
        ("Side", "String"),
        ("RailPosition", "String"),
        ("TurnoutId", "String"),
        ("GroupIds", "String"),
        ("Material", "String"),
        ("Phase", "String"),
        ("UsageType", "String"),
        ("RefLatitude", "Double"),
        ("RefLongitude", "Double"),
        ("RefElevation", "Double"),
        ("LandTitleNumber", "String"),
        ("ModelMode", "String"),
        ("SourceFile", "String"),
    ],
    "BU26_Classification": [
        ("CoClassSystem", "String"),
        ("CoClassIdentification", "String"),
        ("CoClassName", "String"),
        ("CoClassSystem2", "String"),
        ("CoClassIdentification2", "String"),
        ("CoClassName2", "String"),
    ],
    "Pset_RailwayTrackStructurePart": [
        ("HasBallastTrack", "Boolean"),
        ("HasCWR", "Boolean"),
        ("IsSunExposed", "Boolean"),
        ("TrackSupportingStructure", "String"),
    ],
    "Pset_BuiltSystemRailwayTrack": [
        ("TrackID", "String"),
        ("TrackNumber", "String"),
        ("TrackUsage", "String"),
        ("TrackCharacteristic", "String"),
    ],
    "Pset_ElementAssemblyTypeTractionSwitchingAssembly": [
        ("RatedVoltage", "Double"),
        ("NominalPower", "Double"),
    ],
    "Pset_SpaceCommon": [
        ("GrossPlannedArea", "Double"),
    ],
    "Pset_CourseCommon": [
        ("NominalLength", "Double"),
        ("NominalThickness", "Double"),
        ("NominalWidth", "Double"),
    ],
    "Pset_TrackElementOccurrenceSleeper": [
        ("HasSpecialEquipment", "Boolean"),
        ("IsContaminatedSleeper", "Boolean"),
    ],
    "Qto_CourseBaseQuantities": [
        ("Length", "Double"),
        ("Width", "Double"),
        ("Thickness", "Double"),
        ("Volume", "Double"),
        ("GrossVolume", "Double"),
        ("Weight", "Double"),
    ],
    "Qto_SleeperBaseQuantities": [
        ("Length", "Double"),
        ("Width", "Double"),
        ("Height", "Double"),
    ],
}


def check_spec_against_mapping(mapping: Dict) -> List[str]:
    """Every Pset/Qto defined in config/object_mapping.yaml must exist as an Item
    Type with the same property names (and vice versa for Pset_/Qto_ types)."""
    problems = []
    sets = dict(mapping.get("property_sets", {}))
    sets.update(mapping.get("quantity_sets", {}))
    for name, props in sets.items():
        if name not in ITEM_TYPES:
            problems.append("Item type %s missing" % name)
            continue
        have = {p for p, _ in ITEM_TYPES[name]}
        for p in props:
            if p not in have:
                problems.append("Item type %s lacks property %s" % (name, p))
    for name in ITEM_TYPES:
        if name.startswith(("Pset_", "Qto_")) and name not in sets:
            problems.append("Item type %s has no IFC type mapping in object_mapping.yaml" % name)
    return problems


def create_item_types(backend, library: str) -> Dict:
    """Create (or complete) the library in the active DGN.  Existing item types
    and properties are kept, so the call is idempotent."""
    return backend.ensure_item_types(library, ITEM_TYPES)
