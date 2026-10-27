"""Item Type library BU2026_IFC.

Design rules
------------
* One library (``BU2026_IFC``) created directly in the DGN by the build script
  (it can be exported to a DGNLIB from the Item Types dialog for reuse).
* ``BU26_Object``: identity, IFC entity/PredefinedType/attributes, spatial
  parent and stationing of every generated element.  It is also the marker
  used to find generated elements again (purge, validation, export analysis).
* ``BU26_Classification``: up to two CoClass references (ballast needs two).
* Property and quantity sets are Item Types named exactly like the IFC sets
  (``Pset_RailwayTrackStructurePart``, ``Qto_CourseBaseQuantities`` ...) with
  properties named exactly like the IFC properties, so that an export that
  writes Item Types as property sets produces the IFC names directly.
* Only String, Boolean, Integer and Double property types are used.  Double
  properties whose IFC type is a measure (config/object_mapping.yaml
  property_sets/quantity_sets) get a unit (CustomProperty.SetUnits), so the
  exporter has the information to write IfcLengthMeasure/IfcVolumeMeasure ...
  instead of IfcReal.

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
    "Pset_Stationing": [
        ("Station", "Double"),
        ("HasIncreasingStation", "Boolean"),
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


def measure_types(mapping: Dict) -> Dict[Tuple[str, str], str]:
    """(item type, property) -> IFC measure type, for the Double properties that
    get a unit (keys of mapping['item_type_units'])."""
    with_units = set(mapping.get("item_type_units", {}))
    out = {}
    for section in ("property_sets", "quantity_sets"):
        for set_name, props in mapping.get(section, {}).items():
            for prop, ifc_type in props.items():
                if ifc_type in with_units:
                    out[(set_name, prop)] = ifc_type
    return out


def create_item_types(backend, library: str, mapping: Dict) -> Dict:
    """Create (or complete) the library in the active DGN.  Existing item types
    and properties are kept, so the call is idempotent."""
    return backend.ensure_item_types(library, ITEM_TYPES, measure_types(mapping), mapping.get("item_type_units"))
