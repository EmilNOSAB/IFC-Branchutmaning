"""Geometry primitives of the design model and exact quantity computations.

The design model describes every DGN element with one of these primitives.
The MicroStation layer turns them into native elements (DgnBox solid
primitives, closed polyface meshes / ruled sweeps, line strings, shapes).
Quantities are computed from exactly the same vertex data that is written to
the DGN, so model quantities and DGN geometry cannot drift apart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

Vec3 = Tuple[float, float, float]


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec3) -> Vec3:
    n = norm(a)
    if n == 0:
        raise ValueError("zero-length vector")
    return (a[0] / n, a[1] / n, a[2] / n)


@dataclass
class BoxGeom:
    """Oriented box. ``base_center`` is the centre of the bottom face,
    ``x_axis``/``y_axis`` are orthonormal, z = x cross y points up."""

    base_center: Vec3
    x_axis: Vec3
    y_axis: Vec3
    size_x: float
    size_y: float
    size_z: float

    @property
    def z_axis(self) -> Vec3:
        return cross(self.x_axis, self.y_axis)

    @property
    def top_center(self) -> Vec3:
        return add(self.base_center, scale(self.z_axis, self.size_z))

    @property
    def volume(self) -> float:
        return self.size_x * self.size_y * self.size_z

    def corners(self) -> List[Vec3]:
        out = []
        for h in (0.0, self.size_z):
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                p = add(self.base_center, scale(self.x_axis, 0.5 * sx * self.size_x))
                p = add(p, scale(self.y_axis, 0.5 * sy * self.size_y))
                out.append(add(p, scale(self.z_axis, h)))
        return out

    def to_mesh(self) -> "Mesh":
        c = self.corners()
        faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        return Mesh(c, faces)


@dataclass
class SweepGeom:
    """Closed solid swept through ``sections``: each section is a closed
    polygon (same vertex count, counter-clockwise when looking along the sweep
    direction); consecutive sections are joined by ruled quads; both ends are
    capped."""

    sections: List[List[Vec3]]

    def to_mesh(self) -> "Mesh":
        n = len(self.sections[0])
        if any(len(s) != n for s in self.sections):
            raise ValueError("all sections must have the same vertex count")
        verts: List[Vec3] = [p for sec in self.sections for p in sec]
        faces: List[Tuple[int, ...]] = []
        for k in range(len(self.sections) - 1):
            a0, b0 = k * n, (k + 1) * n
            for i in range(n):
                j = (i + 1) % n
                faces.append((a0 + i, a0 + j, b0 + j, b0 + i))
        faces.append(tuple(reversed(range(n))))  # start cap faces backwards
        last = (len(self.sections) - 1) * n
        faces.append(tuple(range(last, last + n)))
        return Mesh(verts, faces)


@dataclass
class MultiGeom:
    parts: List[object]

    def to_mesh(self) -> "Mesh":
        verts: List[Vec3] = []
        faces: List[Tuple[int, ...]] = []
        for p in self.parts:
            m = p.to_mesh()
            off = len(verts)
            verts.extend(m.vertices)
            faces.extend(tuple(i + off for i in f) for f in m.faces)
        return Mesh(verts, faces)


@dataclass
class PolylineGeom:
    points: List[Vec3]


@dataclass
class ShapeGeom:
    """Closed outline (first point is not repeated)."""

    points: List[Vec3]


@dataclass
class Mesh:
    vertices: List[Vec3]
    faces: List[Tuple[int, ...]] = field(default_factory=list)

    def volume(self) -> float:
        """Signed volume by the divergence theorem (fan triangulation of each
        face).  Positive for outward-oriented closed meshes."""
        v = 0.0
        vs = self.vertices
        for f in self.faces:
            p0 = vs[f[0]]
            for i in range(1, len(f) - 1):
                v += dot(p0, cross(vs[f[i]], vs[f[i + 1]]))
        return v / 6.0

    def oriented_outward(self) -> "Mesh":
        """Return the mesh with faces reversed if its signed volume is negative."""
        if self.volume() < 0:
            return Mesh(self.vertices, [tuple(reversed(f)) for f in self.faces])
        return self

    def is_closed(self) -> bool:
        """Every directed edge must have exactly one opposite edge."""
        edges = {}
        for f in self.faces:
            for i in range(len(f)):
                e = (f[i], f[(i + 1) % len(f)])
                edges[e] = edges.get(e, 0) + 1
        for (a, b), c in edges.items():
            if c != 1 or edges.get((b, a), 0) != 1:
                return False
        return True

    def bbox(self) -> Tuple[Vec3, Vec3]:
        xs = [p[0] for p in self.vertices]
        ys = [p[1] for p in self.vertices]
        zs = [p[2] for p in self.vertices]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def polygon_area_xy(points: Sequence[Vec3]) -> float:
    a = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[(i + 1) % n][0], points[(i + 1) % n][1]
        a += x1 * y2 - x2 * y1
    return 0.5 * a


def polygon_area_2d(points: Sequence[Tuple[float, float]]) -> float:
    a = 0.0
    n = len(points)
    for i in range(n):
        a += points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
    return 0.5 * a


def convex_hull_xy(points: Sequence[Vec3]) -> List[Tuple[float, float]]:
    pts = sorted(set((p[0], p[1]) for p in points))
    if len(pts) <= 2:
        return pts

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: List[Tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]
