# Första körningen i MicroStation 2026

| Fil | Innehåll |
|---|---|
| `dgn_validation_report.json` | Användarens körning: DGN med 3 477 element, 0 fel |
| `bentley_export_analysis.json` | `export/inspect_bentley_export.py` på Bentley-exporten |
| `validation_report_raw_export.*` | Bentley-exporten validerad som den är, utan någon ändring: **1/22** |

Valideringen av exportfilen kördes i Linux-containern med `validation/validate_ifc.py`, som bara läser filen.

I den körningen saknades Bentleys "IFC Classification" i DGN:en. Därför blev alla element IfcBuildingElementProxy i IfcSite. IFC-filerna (cirka 20 MB) och DGN:en versioneras inte här.
