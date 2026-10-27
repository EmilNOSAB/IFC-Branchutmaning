# output/

Resultat från körningarna skrivs hit och kan checkas in för granskning (`output/dryrun/` och `output/env/` ignoreras):

| Fil | Skapas av |
|---|---|
| `Branschutmaningen_2026.dgn` | MicroStation, `microstation/build_railway_dgn.py` (modellen öppen som aktiv fil) |
| `model_report.json` | `microstation/build_railway_dgn.py` i MicroStation |
| `dgn_validation_report.json` | `validation/validate_dgn.py` i MicroStation |
| `environment_report.json`, `ifc_classification_library.json`, `env/` | `microstation/inspect_environment.py` |
| `SchemaMapping.json`, `export_instructions.txt` | `microstation/export_ifc.py` |
| `Branschutmaningen_2026.ifc` | MicroStations IFC-exportör (dialog) – leveransen, ändras inte |
| `bentley_export_analysis.json` | `export/inspect_bentley_export.py` |
| `probe/` | exportörsprovet: `BU26_probe.dgn`, `probe_report.json` (MicroStation), `BU26_probe.ifc` (exportören), `probe_analysis.json` (`export/inspect_probe_export.py`) |
| `validation_report.html/.json` | `validation/validate_ifc.py` |
| `dryrun/` | torrkörningar utan MicroStation (`--dry-run`), skriver aldrig DGN |
