"""Horizontal alignment evaluation (line, circular arc, clothoid).

Conventions (see landxml_reader): x = easting, y = northing, azimuth measured
from north, clockwise, in radians.  Signed curvature ``k = d(azimuth)/ds`` is
positive for clockwise (right-hand) curves.

Every geometry element is evaluated from its own LandXML start point and start
direction, so numerical errors never accumulate from one element to the next.
``verify()`` integrates each element to its end and compares with the end
point and end direction stored in the file.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .landxml_reader import Alignment, HorizontalElement

# 5-point Gauss-Legendre nodes/weights on [-1, 1]
_GL_NODES = (
    -0.9061798459386640, -0.5384693101056831, 0.0,
    0.5384693101056831, 0.9061798459386640,
)
_GL_WEIGHTS = (
    0.2369268850561891, 0.4786286704993665, 0.5688888888888889,
    0.4786286704993665, 0.2369268850561891,
)


@dataclass(frozen=True)
class HPoint:
    """Result of a horizontal evaluation."""

    station: float
    x: float
    y: float
    azimuth: float  # rad, from north clockwise
    curvature: float  # 1/m, positive = turning right (cw)

    @property
    def tangent(self) -> Tuple[float, float]:
        """Unit tangent (dx, dy) in the x=east, y=north plane."""
        return (math.sin(self.azimuth), math.cos(self.azimuth))

    @property
    def left_normal(self) -> Tuple[float, float]:
        """Unit vector pointing to the left of the direction of travel."""
        tx, ty = self.tangent
        return (-ty, tx)


def _signed_curvature(radius: Optional[float], rot: Optional[str]) -> float:
    if radius is None or math.isinf(radius) or radius == 0:
        return 0.0
    sign = 1.0 if rot == "cw" else -1.0
    return sign / abs(radius)


class HorizontalSegment:
    """Evaluator for one LandXML horizontal element."""

    def __init__(self, el: HorizontalElement):
        self.el = el
        self.kind = el.kind
        self.sta_start = el.sta_start
        self.length = el.length
        self.x0 = el.start.x
        self.y0 = el.start.y
        self.az0 = el.dir_start
        if el.kind == "Line":
            self.k0 = self.k1 = 0.0
        elif el.kind == "Curve":
            self.k0 = self.k1 = _signed_curvature(el.radius, el.rot)
        elif el.kind == "Spiral":
            if el.spi_type not in (None, "clothoid"):
                raise NotImplementedError("Spiral type %r is not supported" % el.spi_type)
            self.k0 = _signed_curvature(el.radius_start, el.rot)
            self.k1 = _signed_curvature(el.radius_end, el.rot)
        else:  # pragma: no cover - reader filters other kinds
            raise ValueError(el.kind)
        self.dk = (self.k1 - self.k0) / self.length if self.length > 0 else 0.0

    def curvature_at(self, s: float) -> float:
        return self.k0 + self.dk * s

    def azimuth_at(self, s: float) -> float:
        return self.az0 + self.k0 * s + 0.5 * self.dk * s * s

    def xy_at(self, s: float) -> Tuple[float, float]:
        if self.kind == "Line":
            return (self.x0 + s * math.sin(self.az0), self.y0 + s * math.cos(self.az0))
        if self.kind == "Curve":
            k = self.k0
            # exact circular arc
            a1 = self.az0 + k * s
            # integral of sin(az) ds = -(cos(a1)-cos(a0))/k ; integral of cos = (sin(a1)-sin(a0))/k
            return (
                self.x0 - (math.cos(a1) - math.cos(self.az0)) / k,
                self.y0 + (math.sin(a1) - math.sin(self.az0)) / k,
            )
        # clothoid: composite Gauss-Legendre integration of the direction field
        n = max(1, int(math.ceil(abs(s) / 2.0)))
        h = s / n
        x = self.x0
        y = self.y0
        for i in range(n):
            a = i * h
            for node, w in zip(_GL_NODES, _GL_WEIGHTS):
                t = a + 0.5 * h * (node + 1.0)
                az = self.azimuth_at(t)
                x += 0.5 * h * w * math.sin(az)
                y += 0.5 * h * w * math.cos(az)
        return (x, y)

    def evaluate(self, s: float) -> HPoint:
        x, y = self.xy_at(s)
        return HPoint(self.sta_start + s, x, y, self.azimuth_at(s), self.curvature_at(s))


@dataclass
class SegmentCheck:
    index: int
    kind: str
    sta_start: float
    length: float
    end_position_error: float  # m, computed end vs LandXML End point
    end_azimuth_error: float  # rad, computed vs LandXML dirEnd
    start_gap: float  # m, distance from previous element's LandXML end point
    station_gap: float  # m, staStart - (previous staStart + previous length)


class HorizontalAlignment:
    def __init__(self, alignment: Alignment):
        self.name = alignment.name
        self.segments = [HorizontalSegment(e) for e in alignment.elements]
        if not self.segments:
            raise ValueError("Alignment %r has no horizontal geometry" % alignment.name)
        self._starts = [seg.sta_start for seg in self.segments]
        self.sta_start = alignment.sta_start
        self.sta_end = alignment.sta_start + alignment.length

    def segment_index(self, station: float) -> int:
        i = bisect.bisect_right(self._starts, station) - 1
        return min(max(i, 0), len(self.segments) - 1)

    def evaluate(self, station: float) -> HPoint:
        """Evaluate at a station.  Stations outside the alignment are extrapolated
        along the first/last element (needed only for tiny numeric overshoots)."""
        seg = self.segments[self.segment_index(station)]
        return seg.evaluate(station - seg.sta_start)

    def verify(self) -> List[SegmentCheck]:
        out: List[SegmentCheck] = []
        prev = None
        for i, seg in enumerate(self.segments):
            end = seg.evaluate(seg.length)
            el = seg.el
            gap = 0.0 if prev is None else prev.el.end.dist(el.start)
            sgap = 0.0 if prev is None else seg.sta_start - (prev.sta_start + prev.length)
            daz = (end.azimuth - el.dir_end + math.pi) % (2 * math.pi) - math.pi
            out.append(SegmentCheck(
                i, seg.kind, seg.sta_start, seg.length,
                math.hypot(end.x - el.end.x, end.y - el.end.y), daz, gap, sgap,
            ))
            prev = seg
        return out

    def breakpoints(self) -> List[float]:
        """Stations where the horizontal geometry type changes."""
        pts = [seg.sta_start for seg in self.segments]
        pts.append(self.sta_end)
        return pts

    def project(self, x: float, y: float, sta_hint: Optional[float] = None,
                search_step: float = 1.0) -> Tuple[float, float]:
        """Return (station, signed offset) of the closest point.  Offset is
        positive to the LEFT of the direction of travel."""
        if sta_hint is None:
            best = None
            s = self.sta_start
            while s <= self.sta_end:
                p = self.evaluate(s)
                d = (p.x - x) ** 2 + (p.y - y) ** 2
                if best is None or d < best[0]:
                    best = (d, s)
                s += search_step
            sta = best[1]
        else:
            sta = sta_hint
        for _ in range(50):
            p = self.evaluate(sta)
            tx, ty = p.tangent
            ds = (x - p.x) * tx + (y - p.y) * ty
            sta = min(max(sta + ds, self.sta_start), self.sta_end)
            if abs(ds) < 1e-9:
                break
        p = self.evaluate(sta)
        nx, ny = p.left_normal
        return sta, (x - p.x) * nx + (y - p.y) * ny
