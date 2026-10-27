# output/

Resultat från körningarna skrivs hit (versioneras inte):

| Fil | Skapas av |
|---|---|
| `Branschutmaningen_2026.dgn` | MicroStation, `microstation/build_railway_dgn.py` (modellen öppen som aktiv fil) |
| `model_report.json` | `microstation/build_railway_dgn.py` i MicroStation |
| `dgn_validation_report.json` | `validation/validate_dgn.py` i MicroStation |
| `environment_report.json`, `env/` | `microstation/inspect_environment.py` |
| `SchemaMapping.json`, `export_instructions.txt` | `microstation/export_ifc.py` |
| `Branschutmaningen_2026_bentley_export.ifc` | MicroStations IFC-exportör (dialog) |
| `bentley_export_analysis.json` | `export/inspect_bentley_export.py` |
| `Branschutmaningen_2026.ifc`, `postprocess_report.json` | `export/complete_ifc_structure.py` (separat efterbearbetning) |
| `validation_report.html/.json` | `validation/validate_ifc.py` |
| `dryrun/` | torrkörningar utan MicroStation (`--dry-run`), skriver aldrig DGN |
