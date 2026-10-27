"""Sleepers (IfcTrackElement SLEEPER): one DgnBox solid per sleeper, placed
perpendicular to the track at the configured spacing, rotated by grade and
cant.  Turnout sleepers (long sleepers / crossover common sleepers) use level
BU26_SLEEPER_TURNOUT.

Shared cells were considered for instancing but are not used: every sleeper
needs its own Item Type values (id, part, station, quantities) and the export
of shared-cell instances with per-instance items has not been verified.  A
DgnBox primitive is a compact native solid (a few hundred bytes), so
individual solids keep the DGN small enough (about 3 400 sleepers in full mode).
"""

from __future__ import annotations

from .context import place_components

CATEGORIES = ("SLEEPER", "SLEEPER_TURNOUT")


def create(ctx, design) -> int:
    n = place_components(ctx, [c for c in design.components if c.category == "SLEEPER"], "Slipers (spår)")
    n += place_components(ctx, [c for c in design.components if c.category == "SLEEPER_TURNOUT"], "Växelslipers")
    return n
