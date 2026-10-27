"""Running rails of plain track (IfcRail RAIL, level BU26_RAIL_MAIN).

Each rail is a closed solid swept along the 3D rail line (horizontal
alignment, vertical profile and cant) with the 60E1 outline (simple
rectangle in preview mode).  Rails are split per railway part and per curve
zone so that every rail element is entirely an inner rail ("innerräl") or
an outer rail ("ytterräl").
"""

from __future__ import annotations

from .context import place_components

CATEGORIES = ("RAIL_MAIN",)


def create(ctx, design) -> int:
    comps = [c for c in design.components if c.category in CATEGORIES]
    return place_components(ctx, comps, "Räler (spår)")
