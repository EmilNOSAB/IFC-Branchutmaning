# Körinstruktion – MicroStation 2025

Instruktionen gäller MicroStation 2025 (IFC 4.3-exporten är en Technology Preview i 2025). Python-delen fungerar även i 2024. Sökvägen till installationen är inte hårdkodad någonstans. `<repo>` står för den mapp där repot ligger.

## 0. Förberedelser (en gång)

1. **Seedfil:** använd en 3D-seed med **masterenhet meter** (krävs för IDS #20). Ange den i `config/model_config.yaml` (`files.dgn_seed`) eller använd arbetsytans `MS_DESIGNSEED`.
2. **Bentleys IFC Classification Item Type:** öppna Item Types-dialogen, välj Libraries > **Import** och välj `IFC_Classes_Types.dgnlib` (levereras i MicroStations `Default\Dgnlib\ItemTypes`). Gör det helst i seedfilen, så finns biblioteket i varje ny DGN. Öppna sedan DGN:en på nytt (Bentley-hjälpen kräver det för picklistorna). Utan biblioteket fungerar byggskriptet ändå, men exportören klassar då elementen som proxys och efterbearbetningen måste klassa om dem.
3. **Python:** MicroStations inbyggda Python 3.12 räcker för skripten i `microstation/`. PyYAML behövs inte, eftersom `common/miniyaml.py` läser konfigurationen. IfcOpenShell/IfcTester behövs bara för `export/` och `validation/` och körs med en vanlig Python:
   `python -m pip install ifcopenshell ifctester` (ifctester kräver även `pystache`).

## 1. Skapa och öppna DGN:en

* `python microstation\prepare_dgn.py` (vanlig Python eller `python load` i MicroStation) kopierar seedfilen till `<repo>\output\Branschutmaningen_2026.dgn`, precis som File > New gör. Seedfilen tas från `files.dgn_seed`, annars från `MS_DESIGNSEED`. En befintlig fil skrivs aldrig över utan `--force`.
* Öppna filen (File > Open). Alternativt: File > New med den metriska 3D-seedfilen och samma namn.

## 2. Inspektera miljön (steg 1 i arbetsordningen)

```
python load "<repo>\microstation\inspect_environment.py"
```
Detta skriver `output\environment_report.json`: versioner, konfigurationsvariabler, API-yta, IFC_Classes_Types-filer, exportörens standardfiler för SchemaMapping (kopieras till `output\env\`), giltiga GCS-nycklar och om "IFC Classification" finns i DGN:en. Gå igenom `docs/MicroStation_verifiering.md` V-01 till V-05.

## 3. Bygg modellen

```
python load "<repo>\microstation\build_railway_dgn.py"
```
Läget väljs med `mode: preview | full` i `config/model_config.yaml`. Det kan också styras med miljövariabeln eller MicroStation-konfigurationsvariabeln `BU26_MODE` (sätts i arbetsytans .cfg eller innan MicroStation startas). Kör först `preview` (glesare geometri, var tionde sliper, samma klassning och struktur) och därefter `full`. Skriptet arbetar alltid i den **aktiva** 3D-modellen och tar först bort element från tidigare körningar (känns igen på Item Type `BU2026_IFC:BU26_Object`), så en omkörning skapar inga dubbletter. Logg och tider skrivs i MicroStations Python-konsol. Rapporten hamnar i `output\model_report.json`.

Python Manager fungerar också: Utilities > Python Manager > Load, sedan Run.

## 4. Kontrollera DGN:en

```
python load "<repo>\validation\validate_dgn.py"
```
Skriptet läser tillbaka alla genererade element och deras Item Types och jämför med designmodellen: ID, IFC-klass, PredefinedType, CoClass, Pset/Qto-värden och nivåer. Resultatet skrivs till `output\dgn_validation_report.json`. Granska också visuellt: nivåerna `BU26_*`, Named Groups (`BU26_RP-*`, `BU26_VXL-*`, `BU26_BS-1`), Item Types via Properties och mät några slipers (V-06).

## 5. SchemaMapping

Med standardfilen från exportören som `inspect_environment.py` har kopierat:
```
python export\build_schema_mapping.py --template output\env\00_<namn>.json
```
Utan mall finns den fristående `export/SchemaMapping.json` med de dokumenterade sektionerna (se `export/README.md`, V-07).

## 6. IFC-export

```
python load "<repo>\microstation\export_ifc.py"
```
Skriptet kontrollerar förutsättningarna och öppnar exportdialogen med de dokumenterade key-ins `mdl load Bentley.Interchange.iTwinIFCExporter` och `IFC ITWINEXPORT`. Det skriver också `output\export_instructions.txt`. I dialogen:
1. IFC Version: **IFC 4.3**.
2. Utfil: `<repo>\output\Branschutmaningen_2026_bentley_export.ifc`.
3. Schema Mapping File: Browse → `<repo>\output\SchemaMapping.json`.
4. Export.

Inga GUI-makron eller skärmkoordinater används. Exportören har inget dokumenterat programmerbart API, så dialogen fylls i manuellt.

## 7. Analys, efterbearbetning och validering (vanlig Python)

```
python export\inspect_bentley_export.py        # vilka klasser och relationer exportören skapade (V-08 – V-11)
python export\complete_ifc_structure.py        # separat, uttryckligt efterbearbetningssteg
python validation\validate_ifc.py              # IDS: output\validation_report.html/.json
```
Exportfilen ändras aldrig. Efterbearbetningen skriver `output\Branschutmaningen_2026.ifc` och loggar varje ändring i `output\postprocess_report.json`. Validera gärna även den råa exporten:
`python validation\validate_ifc.py --ifc output\Branschutmaningen_2026_bentley_export.ifc --html output\validation_raw.html --json output\validation_raw.json`

## Key-ins och automatisk start

* **Verifierat (MicroStation-hjälpen):** `python load "<fil>"` kör ett skript från key-in-fönstret. Det kan läggas i en key-in-skriptfil, på en knapp eller i en Function Key.
* **Egna key-ins:** MicroStation Python kan registrera key-ins med `PythonKeyinManager.GetManager().LoadCommandTableFromXml(WString(__file__), WString(<commands.xml>))` (developer.bentley.com, "Developing Python Applications"). En sådan tabell ingår inte här, eftersom XML-formatet inte har kunnat provas.
* **Automatisk start utan användare:** inte verifierad. Kör i stället `python load` från en key-in-skriptfil.
