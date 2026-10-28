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

Item Type-värden som `SpatialParent` är **metadata**. De skapar inga IFC-relationer av sig själva. Relationer kan bara uppstå om exportören översätter en DGN-struktur (cell, grupp, klassning) till dem, och det avgör provet.

## Vem som skapar vad

IFC-filen skapas enbart av MicroStations exportör. Därför avgör DGN-innehållet och SchemaMapping allt. Tabellen nedan visar status per DGN-konstruktion.

* **Verifierat** = sett i den första riktiga exporten (MicroStation 2026). Den gav **1/22** IDS-krav.
* **Prov P0x** = provas av `microstation/probe_exporter.py`, se `docs/Korinstruktion_MicroStation.md` steg 2.

| IFC-resultat | DGN-konstruktion | Status |
|---|---|---|
| IfcProject (Name) | `ProjectConfigurations.ProjectName` i SchemaMapping | Verifierat. LongName och Phase saknas, och exportören skriver en standardtext som Description. |
| IfcSite (Name), Project→Site | `ProjectConfigurations.SiteName` | Verifierat. RefLatitude/RefLongitude räknas av exportören (fel värden i körning 1), och LongName saknas. |
| Elementklass + PredefinedType | Bentleys "IFC Classification" (importeras nu automatiskt) | Dokumenterat av Bentley. I körning 1 saknades biblioteket och allt blev IfcBuildingElementProxy. Prov P01. |
| IfcRailwayPart / IfcRailway som spatial struktur | Klassat element (P02) eller cell (P03–P05) | Ej verifierat |
| IfcRelContainedInSpatialStructure i spårdel | Element som barn i en klassad cell (P03/P04) | Ej verifierat. I körning 1 låg allt i IfcSite. |
| IfcRelAggregates spårdel→växeldriv | Cell IfcElementAssembly (P06) | Ej verifierat |
| IfcAlignment | Klassad 3D-linjesträng (P07) | Ej verifierat. Nästade horisontal-, vertikal- och cant-layouter kan bara en civil-exportör (OpenRail) skapa. |
| IfcSpatialZone | Klassat element (P08) | Ej verifierat |
| IfcBuiltSystem + IfcRelAssignsToGroup | Klassat element (P09), Named Group med `ProcessGroupingElements=true` (P10) | Ej verifierat |
| IfcRelDefinesByProperties (Pset) | Item Type med samma namn som Pset:en | Verifierat (Item Type-namn = Pset-namn). Uppräkningsegenskaper skrivs med gemener och fel typ (IFCTIME). |
| Måttyper (IfcLengthMeasure …) | Item Type-egenskap med enhet (`SetUnits`) | Verifierat (körning 2): exportören skriver IfcReal + Unit, inte måttyp. |
| IfcElementQuantity (Qto) | Item Type `Qto_*` med enheter | Verifierat (körning 2): blir IfcPropertySet med IfcReal + Unit. |
| IfcClassificationReference (CoClass) | Ingen känd DGN-konstruktion (P12 provar två Item Type-former) | Ej verifierat. Körning 1 innehöll inga referenser. |
| IfcProjectedCRS + IfcMapConversion | DGN:ens GCS | Verifierat: EPSG:3011, absoluta koordinater. VerticalDatum blir "SWEREF1999". EPSG 5850 (+ RH 2000) stöds inte av Bentleys GCS-bibliotek. |

Det som provet visar att exportören inte kan skapa går inte att få in i en oförändrad export från vanliga MicroStation. Kvar finns då två vägar: OpenRail Designer (civil-geometri och dess IFC-exportör) eller att acceptera att kravet inte uppfylls.

## Kontroll

`validation/validate_ifc.py` läser exportfilen utan att ändra den och kontrollerar alla IDS-relationer (partOf) och dessutom: proxys, element utan rumslig relation, antal och typ av IfcRailwayPart, gruppmedlemmar i IfcBuiltSystem, IfcElementQuantity, CRS/MapConversion, enheter och IFC-schemats regler (`ifcopenshell.validate`).
