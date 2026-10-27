# Första körningen i MicroStation 2026

* `dgn_validation_report.json`, `bentley_export_analysis.json` och `validation_report_before_fix.json` kommer från användarens körning. `validation_report_before_fix.json` gav 14/22.
* `validation_report_after_fix.*`: samma Bentley-export (`Branschutmaningen_2026_bentley_export.ifc` från MicroStation 2026), efterbearbetad med den rättade `export/complete_ifc_structure.py` och validerad med `validation/validate_ifc.py` i Linux-containern. Resultatet är 17/22. De 5 underkända beror enbart på motsägelser i IDS:en, och schemavalideringen ger 0 fel.

IFC-filerna (cirka 20 MB vardera) och DGN:en versioneras inte här.
