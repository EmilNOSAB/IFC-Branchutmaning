"""3D track frame along an alignment: position, tangent, lateral, up, grade,
cant and the local rotation matrix at any station.

Cross-section coordinates (u, v)
--------------------------------
``u`` is the lateral distance to the LEFT of the track centre line measured in
the canted rail-top plane, ``v`` is the height above that plane.  ``to_world``
maps (station, u, v) to model coordinates (x = E, y = N, z = RH 2000).

Profile reference
-----------------
The LandXML horizontal alignment is the track centre line.  The vertical
profile is interpreted as top of rail (RÖK) of the low rail, consistent with
``rotationPoint="insideRail"``: without cant both rails lie at the profile
elevation, with cant the inner rail stays at the profile elevation and the
outer rail is raised by the applied cant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .alignment_math import HorizontalAlignment, HPoint
from .cant import CantProfile, CantValue
from .landxml_reader import Alignment
from .vertical_profile import VerticalProfile

Vec3 = Tuple[float, float, float]


def _norm(v: Vec3) -> Vec3:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass(frozen=True)
class TrackFrame:
    station: float
    origin: Vec3  # centre of the rail-top plane on the track centre line
    tangent: Vec3  # unit, along travel incl. grade
    lateral: Vec3  # unit, to the left, in the canted plane
    up: Vec3  # unit, normal of the canted rail-top plane
    elevation: float  # profile elevation (low rail top)
    grade: float  # dz/ds
    azimuth: float
    curvature: float
    cant: CantValue
    horizontal: HPoint

    @property
    def rotation_matrix(self) -> Tuple[Vec3, Vec3, Vec3]:
        """Rows are the world components of the local axes:
        row 0 = tangent (local x), row 1 = lateral/left (local y), row 2 = up (local z).
        Local-to-world: world = origin + M^T * local."""
        return (self.tangent, self.lateral, self.up)

    def point(self, u: float, v: float, along: float = 0.0) -> Vec3:
        o, t, l, w = self.origin, self.tangent, self.lateral, self.up
        return (
            o[0] + along * t[0] + u * l[0] + v * w[0],
            o[1] + along * t[1] + u * l[1] + v * w[1],
            o[2] + along * t[2] + u * l[2] + v * w[2],
        )


class TrackGeometry:
    """Combines horizontal alignment, vertical profile and cant."""

    def __init__(self, alignment: Alignment, vertical_mode: str = "length"):
        self.alignment = alignment
        self.name = alignment.name
        self.horizontal = HorizontalAlignment(alignment)
        self.profile = VerticalProfile(alignment.profile, mode=vertical_mode) if alignment.profile else None
        self.cant = CantProfile(alignment.cant)
        self.sta_start = alignment.sta_start
        self.sta_end = alignment.sta_end

    def elevation(self, station: float) -> Tuple[float, float]:
        if self.profile is None:
            return 0.0, 0.0
        return self.profile.evaluate(station)

    def frame(self, station: float) -> TrackFrame:
        h = self.horizontal.evaluate(station)
        z, g = self.elevation(station)
        c = self.cant.evaluate(station)
        phi = c.roll_angle
        tx, ty = h.tangent
        nx, ny = h.left_normal
        half = 0.5 * c.gauge
        # lateral axis rotated by the roll angle (positive = left side up)
        lat = (nx * math.cos(phi), ny * math.cos(phi), math.sin(phi))
        if c.raised_side == "left":
            pivot = (h.x - half * nx, h.y - half * ny, z)  # right (low) rail
            origin = (pivot[0] + half * lat[0], pivot[1] + half * lat[1], pivot[2] + half * lat[2])
        elif c.raised_side == "right":
            pivot = (h.x + half * nx, h.y + half * ny, z)  # left (low) rail
            origin = (pivot[0] - half * lat[0], pivot[1] - half * lat[1], pivot[2] - half * lat[2])
        else:
            origin = (h.x, h.y, z)
        tangent = _norm((tx, ty, g))
        # make lateral exactly orthogonal to the graded tangent
        d = _dot(lat, tangent)
        lat = _norm((lat[0] - d * tangent[0], lat[1] - d * tangent[1], lat[2] - d * tangent[2]))
        up = _cross(tangent, lat)
        return TrackFrame(station, origin, tangent, lat, up, z, g, h.azimuth, h.curvature, c, h)

    def to_world(self, station: float, u: float, v: float) -> Vec3:
        return self.frame(station).point(u, v)

    def stations(self, sta0: float, sta1: float, max_step: float,
                 max_chord_error: float = 0.005, extra: Sequence[float] = ()) -> List[float]:
        """Sampling stations between sta0 and sta1.  The step is limited by
        ``max_step`` and by the chord error ``R(1-cos(ds/2R))`` for the local
        radius; all horizontal break points and ``extra`` stations inside the
        range are included so that element transitions are hit exactly."""
        if sta1 <= sta0:
            return [sta0]
        fixed = {sta0, sta1}
        for b in list(self.horizontal.breakpoints()) + list(extra):
            if sta0 < b < sta1:
                fixed.add(b)
        if self.profile is not None:
            for c in self.profile.curves:
                for b in (c.bvc, c.evc):
                    if sta0 < b < sta1:
                        fixed.add(b)
        keys = sorted(fixed)
        out: List[float] = []
        for a, b in zip(keys, keys[1:]):
            s = a
            out.append(a)
            while True:
                k = max(abs(self.horizontal.evaluate(s).curvature), abs(self.horizontal.evaluate(min(b, s + max_step)).curvature))
                step = max_step
                if k > 0:
                    # chord error e = R (1 - cos(theta/2)), theta = ds/R -> ds = 2R acos(1 - e/R)
                    r = 1.0 / k
                    step = min(step, 2.0 * r * math.acos(max(-1.0, 1.0 - max_chord_error / r)))
                if s + step >= b - 1e-6:
                    break
                s += step
                out.append(s)
        out.append(keys[-1])
        return out
