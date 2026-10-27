"""Cant (rälsförhöjning) evaluation.

LandXML ``CantStation`` rows give ``appliedCant`` in millimetres.  A station
with ``transitionType`` starts a transition that runs to the next station; the
cant is interpolated linearly over the transition (a linear cant ramp is the
standard companion of a clothoid).  Between stations without a transition the
cant is constant.

Which rail is raised
--------------------
The ``curvature`` attribute is not always given for the end that carries the
cant (e.g. NSpår 7171.77 says ``cw`` but ramps into the ``ccw`` curve at
7200.77).  The raised side is therefore taken from the station in the interval
that has the larger applied cant; if both ends are zero the cant is zero.  The
result is cross-checked against the sign of the horizontal curvature in tests.

Rotation point ``insideRail``: the low (inner) rail keeps the profile
elevation and the outer rail is raised by the full cant.  The cant reference
distance is the LandXML ``gauge`` attribute (1.500 m in the file).
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Optional

from .landxml_reader import Cant


@dataclass(frozen=True)
class CantValue:
    applied_m: float  # >= 0, metres
    raised_side: Optional[str]  # "left" | "right" | None
    gauge: float
    rotation_point: str

    @property
    def roll_angle(self) -> float:
        """Signed roll angle (rad) about the travel direction.  Positive when the
        LEFT rail is raised (right-hand rule about the tangent, z up)."""
        if self.applied_m == 0 or self.raised_side is None:
            return 0.0
        a = math.asin(min(1.0, self.applied_m / self.gauge))
        return a if self.raised_side == "left" else -a


def _side(curvature: Optional[str]) -> Optional[str]:
    # cw = right-hand curve -> the outer (left) rail is raised
    if curvature == "cw":
        return "left"
    if curvature == "ccw":
        return "right"
    return None


class CantProfile:
    def __init__(self, cant: Optional[Cant]):
        self.cant = cant
        self.rows = sorted(cant.stations, key=lambda r: r.station) if cant else []
        self.stations = [r.station for r in self.rows]
        self.gauge = cant.gauge if cant else 1.5
        self.rotation_point = cant.rotation_point if cant else "insideRail"

    def evaluate(self, station: float) -> CantValue:
        if not self.rows:
            return CantValue(0.0, None, self.gauge, self.rotation_point)
        i = bisect.bisect_right(self.stations, station) - 1
        if i < 0:
            r = self.rows[0]
            return CantValue(r.applied_cant_mm / 1000.0, _side(r.curvature) if r.applied_cant_mm else None,
                             self.gauge, self.rotation_point)
        a = self.rows[i]
        b = self.rows[i + 1] if i + 1 < len(self.rows) else None
        if b is None or not a.transition_type:
            mm = a.applied_cant_mm
            side = _side(a.curvature) if mm else None
            return CantValue(mm / 1000.0, side, self.gauge, self.rotation_point)
        t = (station - a.station) / (b.station - a.station) if b.station > a.station else 0.0
        mm = a.applied_cant_mm + t * (b.applied_cant_mm - a.applied_cant_mm)
        dominant = a if a.applied_cant_mm >= b.applied_cant_mm else b
        side = _side(dominant.curvature) if mm > 1e-9 else None
        return CantValue(mm / 1000.0, side, self.gauge, self.rotation_point)
