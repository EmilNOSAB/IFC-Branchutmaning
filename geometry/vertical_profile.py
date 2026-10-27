"""Vertical profile (PVI based) evaluation.

LandXML stores the profile as PVIs; ``CircCurve``/``ParaCurve`` PVIs carry a
vertical curve with a horizontal ``length`` (and for CircCurve a ``radius``).

Data observation for Branschutmaningen_2026 (documented in docs/IDS_och_underlag_konflikter.md):
the given radii are not consistent with the given lengths and PVI grades
(``length != |radius * grade change|``), and curves built from the radius would
overlap neighbouring PVIs.  The default interpretation is therefore
``mode="length"``: a symmetric parabolic vertical curve of the stored length
centred on the PVI.  This reproduces every PVI elevation, every tangent grade
and every curve length exactly.  ``mode="radius"`` builds a curve of length
``|R * dg|`` instead and raises if curves overlap.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .landxml_reader import ProfilePoint


@dataclass
class VerticalCurve:
    pvi_station: float
    pvi_elevation: float
    grade_in: float
    grade_out: float
    length: float
    stored_radius: Optional[float]

    @property
    def bvc(self) -> float:
        return self.pvi_station - 0.5 * self.length

    @property
    def evc(self) -> float:
        return self.pvi_station + 0.5 * self.length

    @property
    def effective_radius(self) -> Optional[float]:
        dg = self.grade_out - self.grade_in
        if abs(dg) < 1e-12:
            return None
        return self.length / dg  # positive = sag (concave up)


@dataclass
class ProfileCheck:
    pvi_station: float
    stored_radius: Optional[float]
    stored_length: float
    grade_change: float
    radius_implied_length: Optional[float]
    effective_radius: Optional[float]
    sign_consistent: bool


class VerticalProfile:
    def __init__(self, points: List[ProfilePoint], mode: str = "length"):
        if len(points) < 2:
            raise ValueError("A profile needs at least two PVIs")
        self.points = points
        self.mode = mode
        self.stations = [p.station for p in points]
        self.grades = [
            (points[i + 1].elevation - points[i].elevation) / (points[i + 1].station - points[i].station)
            for i in range(len(points) - 1)
        ]
        self.curves: List[VerticalCurve] = []
        for i in range(1, len(points) - 1):
            p = points[i]
            if p.kind == "PVI" or (p.curve_length <= 0 and not p.radius):
                continue
            g1, g2 = self.grades[i - 1], self.grades[i]
            if mode == "length":
                length = p.curve_length
            elif mode == "radius":
                if p.radius is None:
                    raise ValueError("PVI %.3f has no radius" % p.station)
                length = abs(p.radius * (g2 - g1))
            else:
                raise ValueError("Unknown vertical curve mode %r" % mode)
            self.curves.append(VerticalCurve(p.station, p.elevation, g1, g2, length, p.radius))
        # overlap check
        for a, b in zip(self.curves, self.curves[1:]):
            if a.evc > b.bvc + 1e-6:
                raise ValueError(
                    "Vertical curves at %.3f and %.3f overlap (mode=%s)" % (a.pvi_station, b.pvi_station, mode))
        if self.curves:
            if self.curves[0].bvc < self.stations[0] - 1e-6 or self.curves[-1].evc > self.stations[-1] + 1e-6:
                raise ValueError("Vertical curve extends beyond profile ends (mode=%s)" % mode)
        self._curve_starts = [c.bvc for c in self.curves]

    @property
    def sta_start(self) -> float:
        return self.stations[0]

    @property
    def sta_end(self) -> float:
        return self.stations[-1]

    def _tangent(self, station: float) -> Tuple[float, float]:
        i = bisect.bisect_right(self.stations, station) - 1
        i = min(max(i, 0), len(self.grades) - 1)
        g = self.grades[i]
        z = self.points[i].elevation + g * (station - self.stations[i])
        return z, g

    def evaluate(self, station: float) -> Tuple[float, float]:
        """Return (elevation, grade) at station."""
        j = bisect.bisect_right(self._curve_starts, station) - 1
        if 0 <= j < len(self.curves):
            c = self.curves[j]
            if c.bvc <= station <= c.evc and c.length > 0:
                x = station - c.bvc
                z_bvc = c.pvi_elevation - c.grade_in * 0.5 * c.length
                a = (c.grade_out - c.grade_in) / (2.0 * c.length)
                return z_bvc + c.grade_in * x + a * x * x, c.grade_in + 2.0 * a * x
        return self._tangent(station)

    def checks(self) -> List[ProfileCheck]:
        out = []
        for i in range(1, len(self.points) - 1):
            p = self.points[i]
            if p.kind == "PVI":
                continue
            dg = self.grades[i] - self.grades[i - 1]
            implied = abs(p.radius * dg) if p.radius else None
            eff = p.curve_length / dg if abs(dg) > 1e-12 else None
            # LandXML radius sign in this file: negative = sag (dg > 0)
            consistent = p.radius is None or (p.radius < 0) == (dg > 0)
            out.append(ProfileCheck(p.station, p.radius, p.curve_length, dg, implied, eff, consistent))
        return out
