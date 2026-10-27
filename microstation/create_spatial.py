"""Alignments (3D line strings, level BU26_ALIGNMENT) and carrier elements for
the non-physical IFC objects (level BU26_SPATIAL, hidden by default):

  IfcProject, IfcBuiltSystem      - short marker line at the site reference point
  IfcSite, IfcRailway, IfcSpatialZone - outline of all ballast footprints
  IfcRailwayPart (x6)             - ballast footprint outline of the part

The carriers hold the IFC attributes, CoClass and property sets of these
objects as Item Types.  A carrier is metadata only: an Item Type value such
as ``SpatialParent`` does not create an IFC relationship by itself
(see docs/IFC_relationer.md for how the relationships are produced).
"""

from __future__ import annotations

from .context import place_components

CATEGORIES = ("SPATIAL_PROJECT", "SPATIAL_SITE", "SPATIAL_RAILWAY", "SPATIAL_ZONE", "BUILT_SYSTEM",
              "SPATIAL_RAILWAYPART_PLAIN", "SPATIAL_RAILWAYPART_TURNOUT", "ALIGNMENT")


def create(ctx, design) -> int:
    n = 0
    if ctx.cfg.model["dgn"].get("create_alignment_elements", True):
        n += place_components(ctx, [c for c in design.components if c.category == "ALIGNMENT"], "Linjeföringar")
    if ctx.cfg.model["dgn"].get("create_spatial_carriers", True):
        n += place_components(ctx, [c for c in design.components if c.category in CATEGORIES[:-1]],
                              "Rumsliga bärare")
    return n
