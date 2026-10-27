"""Turnout components (model/turnout.py computes the layout):

* RAIL_TURNOUT    through and closure rails in turnout parts   IfcRail RAIL
* RAIL_STOCK      stock rails                                   IfcRail STOCKRAIL
* RAIL_BLADE      switch blades                                 IfcRail BLADE
* RAIL_CHECK      check rails opposite the frog                 IfcRail CHECKRAIL
* FROG            crossing nose (simplified wedge)              IfcTrackElement FROG
* SWITCH_ASSEMBLY point machine with drive rod                  IfcElementAssembly TRACTION_SWITCHING_ASSEMBLY
"""

from __future__ import annotations

from .context import place_components

CATEGORIES = ("RAIL_TURNOUT", "RAIL_STOCK", "RAIL_BLADE", "RAIL_CHECK", "FROG", "SWITCH_ASSEMBLY")
LABELS = {
    "RAIL_TURNOUT": "Genomgående räler växel", "RAIL_STOCK": "Stödräler", "RAIL_BLADE": "Tungor",
    "RAIL_CHECK": "Moträler", "FROG": "Korsningar", "SWITCH_ASSEMBLY": "Omläggningsanordningar",
}


def create(ctx, design) -> int:
    n = 0
    for cat in CATEGORIES:
        n += place_components(ctx, [c for c in design.components if c.category == cat], LABELS[cat])
    return n
