# IFC-struktur och relationer – hur de uppstår

Målet är strukturen i diagrammet och IDS:en:

```
IfcProject  (BH55 / Polarexpress / Branschutmaningen 2026)
├── IfcSite (KG55-OMR)                       IfcRelAggregates
│   └── IfcRailway USERDEFINED "Spårväg"     IfcRelAggregates
│       ├── IfcRailwayPart PLAINTRACK  RP-N1 IfcRelAggregates, UsageType LONGITUDINAL
│       ├── IfcRailwayPart TURNOUTTRACK RP-VA
│       ├── IfcRailwayPart PLAINTRACK  RP-N2
│       ├── IfcRailwayPart PLAINTRACK  RP-S1
│       ├── IfcRailwayPart TURNOUTTRACK RP-VB
│       └── IfcRailwayPart PLAINTRACK  RP-S2
├── IfcSpatialZone CONSTRUCTION SZ-E1        IfcRelAggregates (diagrammet)
└── IfcAlignment x3 (AL-N, AL-S, AL-V)       IfcRelAggregates + IfcRelReferencedInSpatialStructure -> IfcSite
IfcBuiltSystem RAILWAYTRACK "Tvärbanan"      IfcRelAssignsToGroup -> 6 x IfcRailwayPart
```

Element i varje IfcRailwayPart: IfcRail (RAIL/STOCKRAIL/CHECKRAIL/BLADE), IfcTrackElement (SLEEPER/FROG) och IfcCourse BALLASTBED via IfcRelContainedInSpatialStructure. IfcElementAssembly TRACTION_SWITCHING_ASSEMBLY via IfcRelAggregates.

## Var informationen finns i DGN:en

| IFC-begrepp | DGN | Item Type / egenskap |
|---|---|---|
| Klass + PredefinedType | varje element | `BU26_Object.IfcEntity`, `.IfcPredefinedType` + Bentleys `IFC Classification` (Class/Type) |
| Name/Description/LongName/ObjectType | varje element/bärare | `BU26_Object.IfcName`, `.IfcDescription`, `.IfcLongName`, `.IfcObjectType` |
| Rumslig förälder | varje element | `BU26_Object.SpatialParent` (ID för RailwayPart), `.SpatialRelation` (contained/aggregated) |
| Logisk gruppering | Named Groups `BU26_RP-*`, `BU26_VXL-*`, `BU26_BS-1` | `BU26_Object.GroupIds` |
| CoClass | varje element/bärare | `BU26_Classification.CoClassSystem/Identification/Name` (+`2` för ballastens andra) |
| Psets/Qtos | element/bärare | Item Types med samma namn som IFC-seten (`Pset_*`, `Qto_*`) |
| Spatiala objekt | bärarelement på nivån `BU26_SPATIAL` (fotavtryck eller markör) | samma Item Types |
| Linjeföringar | 3D-linjesträngar på `BU26_ALIGNMENT` | `BU26_Object` + LandXML |

Item Type-värden som `SpatialParent` är **metadata**. De skapar inga IFC-relationer av sig själva.

## Vem som skapar vad

| Relation / objekt | MicroStation-exportören (förväntat, verifieras V-08 – V-10) | Efterbearbetning (`export/complete_ifc_structure.py`) |
|---|---|---|
| IfcProject, IfcSite, IfcRelAggregates Project→Site | Ja (ProjectConfigurations) | Attribut, RefLat/Long/Elev, OwnerHistory, Pset_SpaceCommon |
| Elementklasser | Ja, när "IFC Classification" finns | Klassar om proxys/fel klass utifrån `BU26_Object` |
| IfcRelContainedInSpatialStructure | Troligen till IfcSite eller annan standardbehållare | Flyttar till rätt IfcRailwayPart |
| IfcRailway/IfcRailwayPart som spatial struktur | Okänt (V-10) | Skapas eller återanvänds och aggregeras |
| IfcRelAggregates Part→Assembly | Nej (inte uttryckbart i DGN) | Skapas |
| IfcBuiltSystem + IfcRelAssignsToGroup | Nej (IfcGroup utan geometri; `ProcessGroupingElements=false`) | Skapas |
| IfcRelAssociatesClassification | Okänt (Item Types blir troligen Psets) | Skapas (IfcClassification per system) |
| IfcRelDefinesByProperties | Ja (Item Types → Psets) | Ersätter med typade Psets och IfcElementQuantity |
| IfcAlignment | Nej i vanlig MicroStation (OpenRail har civil-API) | Skapas från LandXML med horisontal-, vertikal- och cant-layout samt geometri |
| Georeferering | Från DGN:ens GCS (om satt) | IfcProjectedCRS EPSG:3011 / RH 2000. Offset mäts mellan IFC och SWEREF. |

Efterbearbetningen skapar **ingen fysisk geometri**. Varje fysiskt element måste redan finnas i exportfilen, och den behåller exportörens GlobalId. Ersatta bärare och alignment får bärarens GlobalId.

## Kontroll

`validation/validate_ifc.py` kontrollerar alla IDS-relationer (partOf) och dessutom: proxys, element utan rumslig relation, antal och typ av IfcRailwayPart, gruppmedlemmar i IfcBuiltSystem, IfcElementQuantity, CRS/MapConversion, enheter och IFC-schemats regler (`ifcopenshell.validate`).
