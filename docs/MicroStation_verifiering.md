# Det som måste verifieras inuti MicroStation

Utvecklingsmiljön för det här repot är en Linux-container **utan MicroStation**. Se `docs/evidence/environment_report_linux_container.json`: Python-modulerna `MSPy*` finns inte. Därför gäller följande:

* Repot innehåller ingen MicroStation. DGN- och IFC-filerna i `output/` kommer från användarens körning i **MicroStation 2026**, se avsnittet *Första körningen i MicroStation 2026* nedan.
* Allt som inte kräver MicroStation har körts och testats här (automatiska tester, se README): LandXML-läsning, spårgeometri, designmodell, Item Type-värden, orkestreringen av byggskriptet (inspelande backend), SchemaMapping-byggaren, efterbearbetningen och IDS-valideringen (på en *simulerad* export).
* Alla Bentley-API-anrop finns i `microstation/msapi.py`. Signaturerna är kontrollerade mot MicroStation Python API-referensen på developer.bentley.com och Bentleys officiella API-presentationer.

## Verifieringslista

Kör först `python load "<repo>\microstation\inspect_environment.py"`. Den skriver `output/environment_report.json` som besvarar V-01–V-05 automatiskt.

| Id | Vad | Hur det verifieras | Förväntat | Om det avviker |
|---|---|---|---|---|
| V-01 | MicroStation-version, Python 3.12, `MS_PYTHON` | environment_report: `config_variables`, `python` | 2024/2025, Python 3.12 | Python-API:t kräver 2024 eller senare, IFC 4.3-exporten kräver 2025. |
| V-02 | Enum för Item Type-egenskapernas typ | **Verifierat i MicroStation 2026** (byggkörning): medlemmarna heter `eString`, `eBoolean`, `eDouble`, `eInteger`, `eDateTime`, `ePoint`, `eCustom` och finns direkt på `CustomProperty` (Bentleys PDF skriver `Type.String`) | – | `msapi.property_types()` söker `e`-namnen först, därefter namnen utan prefix. |
| V-03 | Hur ett Item Type-bibliotek skapas | **Verifierat i MicroStation 2026:** konstruktorn `ItemTypeLibrary(name, dgnfile, forCopy=False)`, det finns ingen `Create` | – | `msapi.create_item_type_library()` använder konstruktorn när `Create` saknas. |
| V-04 | Bentleys "IFC Classification": import och egenskapsnamn | Byggskriptet importerar biblioteket själv (V-18). `inspect_environment.py` skriver `output/ifc_classification_library.json` med alla egenskaper och picklistor | Version/Class/Type (eller liknande) med picklistor | Egenskapsnamnen hittas via kandidaterna i `config/object_mapping.yaml` eller på namn. Värden som saknas i picklistan listas i `model_report.json` (`bentley_picklist_misses`). |
| V-05 | GCS-nyckelnamn för SWEREF 99 18 00 | environment_report: `gcs_candidates` | Minst en giltig nyckel med EPSG 3011 | Ange rätt nyckel i `coordinate_system.bentley_gcs_keynames`, eller sätt GCS i dialogen. Byggskriptet provar även `BaseGCS.InitFromEPSGCode(3011)`. |
| V-06 | `DgnBoxDetail.InitFromCenters`: baseX/baseY är hela måttet (inte halva) | Mät en sliper i MicroStation (Measure Distance). `validate_dgn.py` kontrollerar Item Type-värdena | 2,60 × 0,30 × 0,22 m | Halvera eller dubblera i `MicroStationBackend.add_box`. |
| V-07 | **IFC-exportören och SchemaMapping-filen**: läser den en fil med bara `GlobalVariables` och `ProjectConfigurations`, eller krävs hela standardfilen? | Exportera med `export/SchemaMapping.json`, och kör därefter `build_schema_mapping.py --template output/env/<standardfil>` och exportera igen | Den sammanslagna filen fungerar alltid | Använd alltid den sammanslagna filen. |
| V-08 | Vilken IFC-klass varje element faktiskt får | `python export/inspect_bentley_export.py` på exportfilen: `class_by_category`, `class_mismatches` | Inga proxys för klassade element när "IFC Classification" används | Efterbearbetningen klassar om, men rapportera avvikelsen. |
| V-09 | Hur Item Types exporteras (Pset-namn och prefix, datatyper, IfcPropertySet eller IfcElementQuantity) | inspect_bentley_export: `property_set_names`, `property_value_types` | Item Type-namnet finns med i Pset-namnet | `export/ifc_common.item_type_of_pset` hanterar prefix med `:`, `.`, `__` och `/`. Andra mönster läggs till där. |
| V-10 | Relationer som exportören själv skapar (aggregering, containment, grupper, klassificering, georeferering) | inspect_bentley_export: `relationships`, `spatial_tree`, `missing_in_export` | Dokumenteras | Efterbearbetningen kompletterar det som saknas. Resultatet registreras i `docs/IFC_relationer.md`. |
| V-11 | Enhet: IfcSIUnit LENGTHUNIT METRE utan prefix (IDS #20) | inspect_bentley_export: `units` | METRE | Sätt masterenheten i seedfilen till meter och exportera igen. |
| V-12 | Prestanda i full-läge (~3 500 element) | `output/model_report.json`: `timings_s` | Minuter, inte timmar | Kör `preview` för kontroll. Tidtagning finns per steg och per kategori. |
| V-13 | Slutna polyface-nät | Första körningen i MicroStation: `AddPolygon` + `Compress()` gav "not closed by edge pairing" för räler, tungor och växeldriv (Compress slog troligen ihop punkter på millimeteravstånd). Nu används `CreateIndexedMesh(3, DPoint3dArray, Int32Array)` med exakt delade index; indexbasen (0/1) testas och loggas en gång. | Inga varningar; loggen visar "CreateIndexedMesh with N-based indices" | Om varningen kvarstår: rapportera loggraden. Reservvägen `AddPolygon` utan `Compress()` används automatiskt. |
| V-14 | `dgn.linear_solid_kind: ruled_sweep` (valfritt) | Byt i konfigurationen och bygg i preview | DgnRuledSweep-solider | Konstruktorn är verifierad i MicroStation 2026: `DgnRuledSweepDetail(sectionCurves, capped)`. Standardvärdet är fortfarande `mesh`. |
| V-15 | Named groups (`NamedGroup.Create`/`AddMember`/`WriteToFile`) | Named Groups-dialogen: BU26_RP-N1 … BU26_BS-1 | 6 + 2 + 1 grupper | Fel loggas per grupp och byggnaden fortsätter. |
| V-16 | Spara med key-in `FILEDESIGN` | Filens tidsstämpel | Sparad | Spara manuellt (File > Save). |
| V-17 | Konstruktorerna `ElementPropertiesSetter()`, `EditElementHandle()` / `EditElementHandle(elementRef)` (Bentleys PDF 06 och 24), `NamedGroupFlags()`, `NamedGroupMemberFlags()`, `ECValue()`, `DPoint3d(x, y, z)`, `DVec3d(x, y, z)` | Byggskriptet i preview-läge utan fel i `errors` | Inga fel | Konstruktorerna listas inte på referenssidorna men används i Bentleys exempel. Ett fel visar exakt vilket anrop som behöver justeras i `msapi.py`. |
| V-18 | Automatisk import av "IFC Classification": `DgnDocument.CreateForLocalFile`, `DgnFile(doc, DgnFileOpenMode.eReadOnly)`, `LoadDgnFile()`, `FillDictionaryModel()` (Bentleys PDF 05), `ItemTypeLibrary.CloneForFile(destFile, False)` + `Write()`, picklistor med `PickListLibrary.GetPickListLibFromDgn/SavePickListLibToDgn` | `model_report.json`: `bentley_ifc_classification_import` | `written: true`, picklistor sparade | Manuell import i Item Types-dialogen. Felet står i rapporten. |
| V-19 | Enheter på Item Type-egenskaper: `DgnECUnit.FromID(id)` + `CustomProperty.SetUnits` | **Verifierat (körning 2):** VOLT, WATT, METRE, METRE_SQUARED, METRE_CUBED och KILOGRAM löses upp och sätts. Exportören skriver ändå `IfcReal` med en `IfcSIUnit` i `Unit`, inte `IfcLengthMeasure`/`IfcVolumeMeasure`, och Qto_ blir `IfcPropertySet`. | – | IDS-krav med dataType IFC…MEASURE kan därför inte uppfyllas av exportören med Item Types. |
| V-20 | GCS EPSG 5850 (SWEREF 99 18 00 + RH 2000) | **Verifierat (körning 2):** `InitFromEPSGCode(5850)` ger status 103 (stöds inte). Reserven SWEREF1999-18-00 / EPSG 3011 används. VerticalDatum blir "SWEREF1999" (`VertDatumCode.evdcFromDatum`). | – | IDS #21 VerticalDatum = RH 2000 kan inte uppfyllas med Bentleys GCS-bibliotek. |
| V-21 | Celler: `NormalCellHeaderHandler.CreateOrphanCellElement/AddChildElement/AddChildComplete`, Item Types på barn via `ChildEditElemIter` | Exportörsprovet, `output/probe/probe_report.json` (`P03`–`P06`, `read_back`) | Barnens ProbeId läses tillbaka | Felet står per prov i rapporten. |
| V-22 | **Vad exportören gör med varje DGN-konstruktion** (spatial struktur, containment, aggregering, grupper, IfcAlignment, enheter, Qto, klassificering, höjdsystem) | `python export/inspect_probe_export.py` (JA/nej per mekanism) | – | Avgör hur produktions-DGN:en byggs. Se `docs/IFC_relationer.md`. |

## Första körningen i MicroStation 2026

Verifierat i användarens körning (filerna finns i `output/`):

* **DGN:** 3 477 element, 0 fel. `dgn_validation_report.json` är ok, och full-läget byggs på cirka 15 s (V-12).
* **API:** `ItemTypeLibrary(name, dgnfile, forCopy)` är konstruktorn (det finns ingen `Create`). Egenskapstyperna heter `eString`/`eBoolean`/`eDouble`/`eInteger` (V-02). `DgnRuledSweepDetail(sectionCurves, capped)` finns (V-14). EPSG 3011 ger GCS-nyckeln `SWEREF1999-18-00`, som nu står först i `bentley_gcs_keynames` (V-05). 1 m = 10 000 UOR.
* **Exportören (V-08 – V-11):**
  * "IFC Classification" (IFC_Classes_Types.dgnlib) var inte importerad. Då blir alla element `IfcBuildingElementProxy` direkt i `IfcSite`.
  * Item Types blir `IfcPropertySet` med Item Type-namnet.
  * `IfcMapConversion`/`IfcProjectedCRS` EPSG:3011 skrivs, och koordinaterna är absoluta (förskjutning 0).
  * Exportören känner igen IFC 4.3-mallarna för standard-Pset. Egenskaper som har en uppräkning där (`TrackSupportingStructure`, `TrackUsage`, `TrackCharacteristic`) skrivs som `IfcPropertyEnumeratedValue` med **gemener och fel typ**: `(IFCTIME('subgradelayer'))`. Det går inte att påverka från DGN:en, och värdena underkänns därför av IDS (#6, #8, #15).
  * Huvudet `FILE_NAME` har `originating_system` och `authorization` = `$`. Det ger 2 fel i schemavalideringen. Det är exportörens eget fel och går inte att påverka från DGN:en.
* **IDS på exportfilen som den är:** **1/22**. Alla element är proxys, det finns inga spårdelar, grupper eller klassificeringar, och mängderna är IfcReal i IfcPropertySet. Rapporten finns i `docs/evidence/microstation2026_run1/validation_report_raw_export.json`.
* En efterbearbetning av samma fil gav 17/22. Den visade att informationen i DGN:en räcker, men den har tagits bort: exportfilen ska levereras som MicroStation skriver den. Allt som saknas måste därför komma från DGN-strukturen eller SchemaMapping, och det avgörs med exportörsprovet (V-22).

## Andra körningen i MicroStation 2026 (utan efterbearbetning)

* **IFC Classification:** byggskriptet hittade `IFC_Classes_Types.dgnlib` via MSDIR, men inget av de gissade biblioteksnamnen. Allt blev därför proxys igen (1/22). Nu räknas alla Item Type-bibliotek i filen upp (`ItemTypeLibraries` och `DgnECManager.DiscoverSchemas`), och det bibliotek som har item typen `IfcClassification` väljs. Om kopieringen inte går appliceras item typen direkt från dgnlib-filen med `ApplyCustomItem(itemType, True)`, som importerar biblioteket.
* **Enheter:** sätts i DGN:en, men exportören skriver IfcReal + Unit (V-19).
* **Uppräkningsvärden:** `TrackSupportingStructure`, `TrackUsage` och `TrackCharacteristic` blir `IfcPropertyEnumeratedValue(IfcText('subgradelayer'))`, dvs. med gemener.
* **Pset_Stationing:** exportören delar seten. `Station` hamnar i `Pset_Stationing`, `HasIncreasingStation` i ett set som heter `Stationing`.
* **GCS:** EPSG 5850 stöds inte (V-20).

## Vad som är känt och vad som är osäkert om exportören

| Känt (Bentleys dokumentation) | Osäkert, avgörs av V-07 till V-11 |
|---|---|
| MicroStation 2025: File > Export > Exchange File Types > IFC, eller key-in `mdl load Bentley.Interchange.iTwinIFCExporter` och sedan `IFC ITWINEXPORT` (Technology Preview). | Om ett DGN-element med IFC Classification = IfcRailwayPart/IfcRailway blir ett spatialt element i trädet eller bara en produkt. |
| I dialogen väljs IFC-version, utfil och Schema Mapping File. | Om Item Type-värden som `SpatialParent` kan ge relationer (det antas inte). |
| Bentleys Item Type "IFC Classification" (IFC_Classes_Types.dgnlib) sätter version, klass och typ. Utan den blir objekten proxys (OpenRail/OpenRoads-hjälpen). | Exakt hur egenskaperna i "IFC Classification" heter. |
| Kända delar av SchemaMapping-formatet: `GlobalVariables` (ProcessEmptyProperties, JoinAssemblies, ConstructionElements, ProcessGroupingElements), `ProjectConfigurations`, `{"Class": ["IFCDynamic", "<Ifc>", "<Ifc>"]}`, kommentarer `/* */`. | Namnet på listan med klassmappningar och formatet för egenskapsmappningar (finns i standardfilen som levereras med exportören). |
