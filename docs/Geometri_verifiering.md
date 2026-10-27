# Geometriverifiering (LandXML -> spårgeometri -> designmodell)

Genererad av `tools/make_docs.py`. Alla värden är beräknade av koden i `geometry/` och `model/`.

## Horisontalgeometri mot LandXML:s lagrade punkter

Varje element utvärderas från sin egen startpunkt/riktning och integreras till slutet; avvikelsen mot LandXML:s `End` och `dirEnd` visas. Koordinatordning i filen: Northing Easting; riktningar är azimut från norr medurs.

| Linjeföring | # | Typ | staStart | Längd (m) | Slutpunktsavvikelse (mm) | Riktningsavvikelse (µrad) |
|---|---|---|---|---|---|---|
| Del 1 - NSpår | 0 | Line | 6950.0704 | 44.1834 | 0.0002 | 0.0000 |
| Del 1 - NSpår | 1 | Spiral | 6994.2537 | 20.0000 | 0.0004 | 0.0001 |
| Del 1 - NSpår | 2 | Curve | 7014.2537 | 111.7052 | 0.0004 | -0.0001 |
| Del 1 - NSpår | 3 | Spiral | 7125.9590 | 29.0000 | 0.0014 | -0.0002 |
| Del 1 - NSpår | 4 | Line | 7154.9590 | 16.8130 | 0.0005 | 0.0000 |
| Del 1 - NSpår | 5 | Spiral | 7171.7720 | 29.0000 | 0.0012 | -0.0002 |
| Del 1 - NSpår | 6 | Curve | 7200.7720 | 158.0161 | 0.0008 | 0.0004 |
| Del 1 - NSpår | 7 | Spiral | 7358.7881 | 20.0000 | 0.0000 | 0.0003 |
| Del 1 - NSpår | 8 | Line | 7378.7881 | 97.2281 | 0.0003 | 0.0000 |
| Del 1 - NSpår | 9 | Spiral | 7476.0162 | 30.1032 | 0.0003 | 0.0001 |
| Del 1 - NSpår | 10 | Curve | 7506.1195 | 23.2384 | 0.0004 | -0.0006 |
| Del 1 - NSpår | 11 | Spiral | 7529.3578 | 29.9594 | 0.0001 | -0.0001 |
| Del 1 - NSpår | 12 | Line | 7559.3172 | 450.7033 | 0.0004 | 0.0000 |
| Del 1 - SSpår | 0 | Line | 6949.9970 | 37.3345 | 0.0006 | 0.0000 |
| Del 1 - SSpår | 1 | Spiral | 6987.3315 | 20.0000 | 0.0012 | -0.0006 |
| Del 1 - SSpår | 2 | Curve | 7007.3316 | 111.7052 | 0.0003 | 0.0002 |
| Del 1 - SSpår | 3 | Spiral | 7119.0368 | 29.0000 | 0.0021 | -0.0004 |
| Del 1 - SSpår | 4 | Line | 7148.0368 | 16.9175 | 0.0010 | 0.0000 |
| Del 1 - SSpår | 5 | Spiral | 7164.9543 | 29.0000 | 0.0021 | 0.0004 |
| Del 1 - SSpår | 6 | Curve | 7193.9543 | 159.2169 | 0.0006 | -0.0009 |
| Del 1 - SSpår | 7 | Spiral | 7353.1712 | 20.0000 | 0.0007 | 0.0005 |
| Del 1 - SSpår | 8 | Line | 7373.1712 | 99.4042 | 0.0000 | 0.0000 |
| Del 1 - SSpår | 9 | Spiral | 7472.5754 | 30.0000 | 0.0003 | -0.0003 |
| Del 1 - SSpår | 10 | Curve | 7502.5755 | 23.2696 | 0.0001 | 0.0001 |
| Del 1 - SSpår | 11 | Spiral | 7525.8451 | 30.0000 | 0.0005 | -0.0004 |
| Del 1 - SSpår | 12 | Line | 7555.8451 | 450.2532 | 0.0009 | 0.0000 |
| Växel 1 - fiktiv förbindning | 0 | Curve | 7920.0000 | 64.5191 | 0.0007 | -0.0000 |

## Vertikalkurvor

LandXML anger både radie och längd. Med radien blir kurvlängden |R·Δg|, vilket inte stämmer med angiven längd och ger överlappande kurvor; därför används angiven längd (parabel centrerad i PVI), se docs/IDS_och_underlag_konflikter.md (D-01).

| Linjeföring | PVI station | R (fil) | L (fil) | Δg | L enligt R | Effektiv R = L/Δg |
|---|---|---|---|---|---|---|
| Del 1 - NSpår | 6981.681 | -2500.0 | 23.610 | 0.03051 | 76.28 | 774 |
| Del 1 - NSpår | 7023.885 | 6300.0 | 20.000 | -0.00875 | 55.12 | -2286 |
| Del 1 - NSpår | 7139.631 | 2000.0 | 29.544 | -0.01299 | 25.99 | -2274 |
| Del 1 - NSpår | 7193.725 | 1600.0 | 54.218 | -0.05265 | 84.24 | -1030 |
| Del 1 - NSpår | 7360.135 | -3400.0 | 55.729 | 0.02335 | 79.38 | 2387 |
| Del 1 - NSpår | 7517.666 | -4500.0 | 22.547 | 0.00129 | 5.81 | 17475 |
| Del 1 - NSpår | 7642.452 | -4000.0 | 54.402 | 0.02358 | 94.33 | 2307 |
| Del 1 - NSpår | 7975.127 | 1000.0 | 59.269 | -0.08867 | 88.67 | -668 |
| Del 1 - SSpår | 6982.187 | -2500.0 | 18.100 | 0.00179 | 4.46 | 10135 |
| Del 1 - SSpår | 7172.753 | 2100.0 | 102.633 | -0.06361 | 133.59 | -1613 |
| Del 1 - SSpår | 7365.700 | -2600.0 | 40.652 | 0.02262 | 58.81 | 1797 |
| Del 1 - SSpår | 7514.336 | -4500.0 | 22.496 | 0.00403 | 18.14 | 5581 |
| Del 1 - SSpår | 7637.990 | -4000.0 | 54.448 | 0.01829 | 73.15 | 2977 |
| Del 1 - SSpår | 7970.101 | 1000.0 | 58.549 | -0.07127 | 71.27 | -822 |

## Rälsförhöjning (exempel)

| Spår | Station | Förhöjning (mm) | Höjd sida | Vänster räl ö.k. | Höger räl ö.k. |
|---|---|---|---|---|---|
| N | 7004.25 | 25.0 | left | 7.9788 | 7.9538 |
| N | 7070.00 | 50.0 | left | 9.9018 | 9.8519 |
| N | 7280.00 | 50.0 | right | 8.9989 | 9.0488 |
| N | 7515.00 | 70.0 | left | 3.4298 | 3.3598 |
| S | 7280.00 | 50.0 | right | 8.7395 | 8.7895 |
| S | 7700.00 | 0.0 | - | 2.4358 | 2.4358 |

## Växlar (beräknade ur geometrin)

| Växel | Huvudspår | Tungspets | Korsning (huvudspår) | Korsning (förbindelse) | Korsningsvinkel | 1:n | Tunglängd | Avvikande sida |
|---|---|---|---|---|---|---|---|---|
| VXL-A | N | 7920.000 | 7961.058 | 7961.039 | 4.185° | 13.67 | 12.00 | right |
| VXL-B | S | 7980.000 | 7965.264 | 7969.773 | 5.075° | 11.26 | 11.50 | left |

## Spårdelar (IfcRailwayPart)

| Id | Typ | Spår | Från | Till | Längd |
|---|---|---|---|---|---|
| RP-N1 | PLAINTRACK | N | 6950.070 | 7917.000 | 966.930 |
| RP-VA | TURNOUTTRACK | N | 7917.000 | 7965.357 | 48.357 |
| RP-N2 | PLAINTRACK | N | 7965.357 | 8010.020 | 44.664 |
| RP-S1 | PLAINTRACK | S | 6949.997 | 7960.979 | 1010.982 |
| RP-VB | TURNOUTTRACK | S | 7960.979 | 7983.000 | 22.021 |
| RP-S2 | PLAINTRACK | S | 7983.000 | 8006.098 | 23.098 |

## Mängder (full-läge)

| Ballast | Längd | Bredd | Tjocklek | GrossVolume m³ | Volume m³ | Weight t |
|---|---|---|---|---|---|---|
| RP-N1-BALLAST | 966.93 | 3.635 | 0.52 | 2026.0 | 1749.4 | 2974.0 |
| RP-VA-BALLAST | 48.36 | 3.550 | 0.52 | 99.1 | 82.4 | 140.1 |
| RP-N2-BALLAST | 44.66 | 3.550 | 0.52 | 91.6 | 77.4 | 131.6 |
| RP-S1-BALLAST | 1010.98 | 3.632 | 0.52 | 2115.7 | 1823.8 | 3100.5 |
| RP-VB-BALLAST | 22.02 | 3.550 | 0.52 | 45.1 | 37.4 | 63.6 |
| RP-S2-BALLAST | 23.10 | 3.539 | 0.52 | 47.4 | 40.9 | 69.5 |

Antal objekt per kategori (full-läge): ALIGNMENT 3, BALLAST 6, BUILT_SYSTEM 1, FROG 2, RAIL_BLADE 4, RAIL_CHECK 4, RAIL_MAIN 16, RAIL_STOCK 4, RAIL_TURNOUT 16, SLEEPER 3292, SLEEPER_TURNOUT 117, SPATIAL_PROJECT 1, SPATIAL_RAILWAY 1, SPATIAL_RAILWAYPART_PLAIN 4, SPATIAL_RAILWAYPART_TURNOUT 2, SPATIAL_SITE 1, SPATIAL_ZONE 1, SWITCH_ASSEMBLY 2

Varningar: Branch V end elevation differs 0.228 m from the main track (branch_profile=adapt_to_main); VXL-B: Blade length reduced from 12.00 m to 11.50 m: frog lies 14.75 m from the toe

Referenspunkt för IfcSite: E 132866.058 N 6617370.645 H 7.022 -> lat 59.670212860 lon 17.695960303 (kontrollerad mot pyproj EPSG:3011->4326, se tests/test_georef.py)

![Växelförbindelse i plan](img/vaxelforbindelse_plan.png)
