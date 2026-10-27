# Körinstruktion – MicroStation 2025/2026

Instruktionen gäller MicroStation 2025 och 2026. Den första riktiga körningen gjordes i 2026, se `docs/MicroStation_verifiering.md`. `<repo>` står för den mapp där repot ligger, och ingen installationssökväg är hårdkodad.

**Princip:** IFC-filen skapas av MicroStations egen IFC-exportör och är leveransen. Den ändras inte i efterhand. All information måste därför finnas i DGN:en, dvs. i element, celler, Item Types, Named Groups och GCS, eller i SchemaMapping-filen. Python-skripten utanför MicroStation **läser** bara exportfilen, för validering och analys.

## 0. Förberedelser (en gång)

1. **Seedfil:** använd en 3D-seed med **masterenhet meter** (krävs för IDS #20). Ange den i `config/model_config.yaml` (`files.dgn_seed`) eller använd arbetsytans `MS_DESIGNSEED`.
2. **Python för kontrollerna:** `python -m pip install ifcopenshell ifctester pystache` i en vanlig Python. Skripten i `microstation/` körs med MicroStations inbyggda Python och behöver ingenting extra.
3. **Bentleys "IFC Classification":** byggskriptet importerar `IFC_Classes_Types.dgnlib` själv (`ItemTypeLibrary.CloneForFile`). Filen hittas via `MS_DGNLIBLIST`/`MSDIR` + `Default\Dgnlib\ItemTypes`. Om importen misslyckas står orsaken i `output\model_report.json` under `bentley_ifc_classification_import`. Importera den då manuellt: Item Types-dialogen > Libraries > Import > `IFC_Classes_Types.dgnlib`, och kör bygget igen.

## 1. Inspektera miljön

Öppna en DGN och kör:
```
python load "<repo>\microstation\inspect_environment.py"
```
Skriptet skriver två filer:
* `output\environment_report.json` med versioner, API-yta, sökrötter, GCS-nycklar och exportörens standardfil för SchemaMapping. Den hittade filen kopieras till `output\env\`.
* `output\ifc_classification_library.json` med alla egenskaper och picklistor i Bentleys "IFC Classification". Där syns vilka IFC-klasser och PredefinedTypes Bentley erbjuder, till exempel om IfcRailwayPart och IfcBuiltSystem finns.

## 2. Exportörsprov (en gång, cirka 5 minuter)

Bentley dokumenterar inte om exportören kan skapa IfcRailway/IfcRailwayPart som spatial struktur, containment, aggregering, grupper, klassificeringsreferenser, måttenheter och höjdsystem ur en DGN. Provet avgör det med ett objekt per mekanism:
```
python microstation\prepare_dgn.py --out output\probe\BU26_probe.dgn
```
Öppna `output\probe\BU26_probe.dgn` i MicroStation och kör:
```
python load "<repo>\microstation\probe_exporter.py"
```
Exportera sedan via File > Export > IFC:
* IFC 4.3
* Utfil: `output\probe\BU26_probe.ifc`
* Schema Mapping File: `output\probe\SchemaMapping_probe.json`

Kör till sist med vanlig Python:
```
python export\inspect_probe_export.py
```
Resultatet visas som JA/nej per mekanism och skrivs till `output\probe\probe_analysis.json`. Skicka den filen, `output\probe\probe_report.json` och `output\ifc_classification_library.json`. Då kan DGN-strukturen i bygget ställas in efter det exportören faktiskt klarar.

## 3. Skapa och bygg produktions-DGN:en

```
python microstation\prepare_dgn.py
```
Kommandot kopierar seedfilen till `output\Branschutmaningen_2026.dgn`. Öppna filen och kör:
```
python load "<repo>\microstation\build_railway_dgn.py"
```
* **Läge:** `mode: preview | full` i `config/model_config.yaml`, alternativt `BU26_MODE`.
* **Omkörning:** skriptet tar först bort element från tidigare körningar, så inga dubbletter skapas.
* **Rapport:** `output\model_report.json`. Där finns bland annat:
  * `bentley_ifc_classification_import`: importen av Bentleys bibliotek.
  * `bentley_ifc_classification`: vilka egenskaper som används.
  * `bentley_picklist_misses`: IFC-klasser eller PredefinedTypes som saknas i Bentleys picklistor.
  * `item_types.units_set`: måttegenskaper som fått enhet.
  * `coordinate_system`: vilken GCS som sattes. EPSG 5850 (SWEREF 99 18 00 + RH 2000) provas först.

## 4. Kontrollera DGN:en

```
python load "<repo>\validation\validate_dgn.py"
```
Skriptet läser tillbaka alla element och deras Item Types och jämför med designmodellen. Resultatet skrivs till `output\dgn_validation_report.json`.

## 5. IFC-export (MicroStation)

```
python load "<repo>\microstation\export_ifc.py"
```
Skriptet kontrollerar förutsättningarna, skriver `output\export_instructions.txt` och öppnar exportdialogen med key-ins (`mdl load Bentley.Interchange.iTwinIFCExporter`, `IFC ITWINEXPORT`). Fyll i dialogen så här:
1. IFC Version: **IFC 4.3**.
2. Utfil: `<repo>\output\Branschutmaningen_2026.ifc`.
3. Schema Mapping File: `<repo>\output\SchemaMapping.json`.
4. Export.

## 6. Kontroll av exportfilen (vanlig Python, läser bara)

```
python validation\validate_ifc.py              # IDS: output\validation_report.html/.json
python export\inspect_bentley_export.py        # klasser, relationer, datatyper, CRS
```

## Key-ins och automatisk start

* **Verifierat (MicroStation-hjälpen):** `python load "<fil>"` kör ett skript från key-in-fönstret. Det kan läggas i en key-in-skriptfil, på en knapp eller i en Function Key.
* **Exportören:** saknar dokumenterat programmerbart API. Dialogen fylls därför i manuellt, och inga skärmkoordinater eller GUI-makron används.
