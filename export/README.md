# export/

| Fil | Roll |
|---|---|
| `SchemaMapping.json` | Schema Mapping File för MicroStations iTwin IFC-exportör (IFC 4.3). **Bentley-format**, inget internt format. |
| `build_schema_mapping.py` | Genererar `SchemaMapping.json`. Med `--template` utgår den från standardfilen som levereras med den installerade exportören. |
| `schema_mapping_build_report.json` | Vad byggaren gjorde (mall/ingen mall, tillagda klassposter). |
| `inspect_bentley_export.py` | Analyserar den råa exporten: klass per DGN-kategori, Pset-namn och -datatyper, relationer, CRS. |
| `inspect_probe_export.py` | Analyserar exporten av provfilen från `microstation/probe_exporter.py`: vilka DGN-konstruktioner exportören översätter till spatial struktur, relationer, grupper, måttyper och klassificering. |
| `ifc_common.py` | Gemensamma hjälpfunktioner (hittar BU26-objekt via Item Type-värden). |

## SchemaMapping.json

Bentley publicerar standardmappningen som en bilaga på Bentley Communities ("Default Schema mapping for Export to IFC", version 1–7). Bilagan kräver inloggning och kunde inte hämtas under utvecklingen. Följande delar av formatet är däremot offentligt beskrivna i versionsinläggen och används exakt så:

```jsonc
"GlobalVariables": {
  "ProcessEmptyProperties": "false",   // v2
  "JoinAssemblies": "false",           // v3
  "ConstructionElements": "false",     // v4
  "ProcessGroupingElements": "false"   // v5
},
"ProjectConfigurations": { "ProjectName": ..., "SiteName": ..., "Authorization": ..., "Author": {...}, "Organization": {...} },  // v7
/* Mapping for Standard IFC classes */  { "Class": [ "IFCDynamic", "IfcElementAssembly", "IfcElementAssembly" ] }  // v6
```

Den incheckade `SchemaMapping.json` är den **fristående** varianten. Den innehåller bara `GlobalVariables` och `ProjectConfigurations`, eftersom namnet på listan med klassmappningar och formatet för egenskapsmappningar inte är offentliga. Inga egna fält har lagts till som exportören inte känner igen.

Inför produktionsexporten:
1. `microstation/inspect_environment.py` hittar exportörens standardfiler och kopierar dem till `output/env/`.
2. `python export/build_schema_mapping.py --template output/env/<fil>.json` behåller mallen och ändrar bara
   * `GlobalVariables` (värdena ovan),
   * `ProjectConfigurations` (från `config/model_config.yaml`),
   * lägger till `{"Class": ["IFCDynamic", X, X]}` för de IFC 4.3-klasser som saknas i mallens IFCDynamic-lista: X ∈ `bentley_ifc_classification.apply_to_entities` (IfcRail, IfcTrackElement, IfcCourse, IfcElementAssembly, IfcRailwayPart, IfcRailway, IfcSpatialZone, IfcAlignment). Posten kopieras från en befintlig IFCDynamic-post i mallen. Saknar mallen en sådan lista läggs inget till och rapporten anger det.

Tolkningen av `"Class": [EC-schema, EC-klass, IFC-klass]` med EC-schemat `IFCDynamic` är en slutsats av Bentleys exempel. Den bekräftas genom att exportera och köra `inspect_bentley_export.py` (V-07/V-08 i `docs/MicroStation_verifiering.md`).

Klassningen per element görs i DGN:en med Bentleys "IFC Classification" Item Type (Version/Class/Type), som byggskriptet fyller i. DGN-nivån styr aldrig IFC-klassen.

## Ingen efterbearbetning

IFC-filen från MicroStations exportör är leveransen. Skripten här läser den bara, för validering och analys. Om något saknas i exporten ändras DGN-strukturen eller SchemaMapping, och därefter görs en ny export.
