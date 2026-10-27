"""Ballast bed (IfcCourse BALLASTBED): one closed solid per railway part, swept
along the track with the configured cross section (shoulder width, thickness
below sleeper, side slope); towards the neighbouring main track the section
is cut at the mid line.  Quantities (Qto_CourseBaseQuantities) are computed
from the same solid: GrossVolume = solid volume, Volume = GrossVolume minus
embedded sleepers, Weight = Volume x density."""

from __future__ import annotations

from .context import place_components

CATEGORIES = ("BALLAST",)


def create(ctx, design) -> int:
    return place_components(ctx, [c for c in design.components if c.category in CATEGORIES], "Ballast")
