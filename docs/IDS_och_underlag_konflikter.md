# Motsägelser och observationer i underlagen

Originalunderlagen i `input/` har inte ändrats (kontrollsummor i `input/SHA256SUMS`). Nedan står varje motsägelse eller avvikelse vi hittat, var den finns och hur lösningen hanterar den. Punkterna K-03 till K-05 hittas också automatiskt av `validation/ids_conflicts.py`.

## A. IDS mot IDS (kan inte uppfyllas samtidigt)

| Id | Underlag | Motsägelse | Konsekvens | Hantering |
|---|---|---|---|---|
| K-03 | IDS #7 och #16 | Båda gäller **alla** `IfcRail.RAIL`. #7 kräver `Description = "innerräl"`, #16 kräver `Description = "ytterräl"`. | Varje RAIL-objekt underkänns i minst en av de två. | Varje räl får sitt verkliga läge. Rälerna delas per kurvzon så att varje rälelement är antingen inner- eller ytterräl (`model/railway_model.py::_curve_zones`). I raka partier gäller närmaste kurva. |
| K-04 | IDS #7/#16 och #10 | Alla `IfcRail.RAIL` ska enligt #7/#16 ligga i `IfcRailwayPart.PLAINTRACK`, men enligt #10 i `TURNOUTTRACK`. | RAIL i spår underkänns i #10, RAIL i växel underkänns i #7/#16. | Räler läggs där de fysiskt finns: i spårdel respektive växeldel. |
| K-05 | IDS #9 och #17 | Alla `IfcTrackElement.SLEEPER` ska enligt #9 ligga i PLAINTRACK, men enligt #17 i TURNOUTTRACK. | Varje sliper underkänns i #9 eller #17. | Slipers läggs i den spårdel de tillhör. |

Med de här tre motsägelserna kan högst 17 av 22 specifikationer godkännas för en modell som innehåller både spår och växel. `validation/validate_ifc.py` markerar specifikationer som underkänns *enbart* på grund av motsägelserna.

## B. PDF-beskrivningen mot IDS och diagram

| Id | Underlag | Motsägelse | Valt i modellen (ändras i `config/model_config.yaml`) |
|---|---|---|---|
| K-01 | PDF s. 8 och IDS #1 (instructions) | IfcProject: PDF anger Name **BH55**, LongName **Polarexpress**, Phase **Branschutmaningen 2026**. IDS-instruktionen anger **KG55**, **Kistagrenen** och **Branschutmaning 2026**. IDS-kraven kontrollerar bara att attributen finns. | PDF-värdena. Alternativet står som kommentar i konfigurationen. |
| K-02 | PDF s. 10, IDS #15 (krav) och IDS #15 (instructions) | IfcBuiltSystem LongName: PDF anger **Norra nordpolen**, IDS-kravet kräver värdet **Polarexpress** och IDS-instruktionen anger **Norra Ulvsunda-Ursviks torg**. | **Polarexpress**, eftersom det är det värde IDS kontrollerar. |
| K-06 | PDF s. 11 (tabell) mot IDS #14 | PDF:en skriver `IfcRail.FROG`, IDS:en `IfcTrackElement.FROG`. `FROG` finns inte i `IfcRailTypeEnum`. | `IfcTrackElement.FROG`, som är giltigt enligt IFC 4.3. |
| K-07 | PDF s. 7 mot LandXML | PDF: "banöverbyggnaden av en del dubbelspår från km 6+300 – 6+800". LandXML: NSpår 6+950,070–8+010,020 och SSpår 6+949,997–8+006,098. PDF:ens växelområde (~7+900–8+010) stämmer däremot. | Hela sträckan i LandXML modelleras. Stationeringen hämtas ur filen. Med `station_from/station_to` per spårdel kan sträckan begränsas. |
| K-08 | IDS #2 mot IFC 4.3 | `Pset_SpaceCommon.GrossPlannedArea` krävs på IfcSite, men enligt IFC 4.3 gäller `Pset_SpaceCommon` för IfcSpace. buildingSMART:s valideringstjänst kan varna (Pset på fel entitet). | Psetet skrivs ändå eftersom IDS kräver det: `IfcAreaMeasure` = summan av ballastens fotavtryck (konfigurerbart). |
| K-09 | Diagrammet mot IDS #3 | Diagrammet visar `IfcSpatialZone CONSTRUCTION` aggregerad till IfcProject. IDS-instruktionen rekommenderar `USERDEFINED` + ObjectType och säger att element knyts med IfcRelReferencedInSpatialStructure. | `CONSTRUCTION` med ObjectType "Entreprenad", IfcRelAggregates Project→Zone (diagrammet) och IfcRelReferencedInSpatialStructure för de fysiska elementen (IDS). Båda delarna är konfigurerbara (`spatial_zone.predefined_type`, `spatial_zone.relation`). |
| K-10 | Diagrammet mot IDS #11 | I diagrammet ligger IfcElementAssembly i samma grupp som elementen under "IfcRelContainedInSpatialStructure". IDS #11 kräver `IfcRelAggregates` till TURNOUTTRACK. | IDS följs: IfcRelAggregates TURNOUTTRACK→Assembly, utan containment (ett element som ingår i en aggregering ska inte samtidigt vara contained). |
| K-11 | PDF s. 8 mot IDS #1 | Phase "Branschutmaningen 2026" mot "Branschutmaning 2026". | Som K-01 (PDF). |
| K-12 | PDF s. 10 mot IDS #22 | PDF: "CoClass_PR (eller BSAB_PR)". IDS tillåter `CoClass_PR` eller `BSAB96_PR`. | `CoClass_PR`, som båda godtar. |
| K-13 | Excel ("TF_IFC 4x3 Attributmappning") | Beskriver CoClass_FS som "Fysiska system", medan PDF och Praxi använder FS = Funktionella system. | Ingen påverkan på värdena (systemnamnet `CoClass_FS` är detsamma). |

## C. Dataobservationer i LandXML

| Id | Observation | Hantering |
|---|---|---|
| D-01 | Vertikalkurvorna anger både `radius` och `length`, men de stämmer inte överens med PVI-lutningarna: t.ex. NSpår PVI 6981,68 R=-2500, L=23,61 m, men \|R·Δg\| = 76,3 m. Med radierna skulle kurvorna överlappa varandra och profilens ändar. | Paraboler med **angiven längd**, centrerade i PVI. Alla PVI-höjder och tangentlutningar hålls exakt. Radiens tecken stämmer med kurvtypen (negativ = konkav/sag). Se `docs/Geometri_verifiering.md`. Testet `test_radius_mode_is_inconsistent_with_file` visar att radietolkningen inte går. |
| D-02 | Växelförbindelsens profil slutar på +3,814, men SSpår ligger på +3,586 i anslutningspunkten (0,228 m skillnad). I början stämmer den (0,3 mm). | `branch_profile: adapt_to_main` (standard): linjär höjdkorrektion 0 → −0,228 m längs förbindelsen (3,5 ‰), så att den ansluter till båda spåren. Med `landxml` används profilen oförändrad. IfcAlignment följer samma val. |
| D-03 | Förbindelsen börjar tangentiellt mot NSpår (riktning 0,321006 = NSpårets), men når SSpår **i vinkel** (riktning 0,4358 mot 0,3210, ca 6,6°) och slutar mitt på spårmitten. | Växel B beräknas ur verklig geometri. Korsningen ligger bara 14,75 m från anslutningspunkten, så tungan kortas automatiskt till 11,50 m. En varning skrivs i rapporten. |
| D-04 | Spåravståndet N–S är 3,70 m i växelområdet och 4,14–4,36 m i kurvorna. | Ballasten delas vid mittlinjen mellan spåren. I förbindelsezonen används gemensamma långslipers (≈6,3 m) som når över båda spåren. |
| D-05 | Höjdskillnaden mellan N och S i växelzonen är +0,11 till +0,22 m (S högre). | De gemensamma långslipersna lutas så att de ligger an mot båda spårens rälplan (fiktiva data). |
| D-06 | `Cant name="R?lsf?rh?jning"` (teckenkodningsfel i två av tre linjeföringar). | Påverkar inte beräkningen. |
| D-07 | `Cant gauge="1.5"` är avståndet mellan rälernas kontaktpunkter (inte spårvidden 1,435). | Används som referensavstånd för rälsförhöjningen och som rälmittavstånd. |
| D-08 | I CantStation-raderna motsvarar `curvature` inte alltid den kurva som rampen leder in i (t.ex. NSpår 7171,77 "cw" före ccw-kurvan vid 7200,77). | Sidan bestäms av den station i intervallet som har störst förhöjning. Testet `test_cant_side_agrees_with_horizontal_curvature` kontrollerar mot horisontalkurvaturen. |
| D-09 | `Project name="Jetline"` i LandXML är inte samma som projektnamnet i PDF/IDS. | Används inte för IFC-attribut. |

## D. Övrigt

* `input/BranschUtmaningen_2026-IFC4x3 rumslig struktur.png` är den bild som bifogades i konversationen. Den kan vara omkodad jämfört med originalfilen. Innehållet (informationsmodellen) är detsamma.
