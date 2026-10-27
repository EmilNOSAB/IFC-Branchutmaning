"""Writes design-model geometry as native DGN elements through the backend.

Element kinds
-------------
BoxGeom      -> DgnBox solid primitive (sleepers, point machine parts)
SweepGeom    -> closed polyface mesh (default) or DgnRuledSweep solid
                (``dgn.linear_solid_kind``); used for rails, check rails,
                blades, frogs and ballast.  End caps are triangulated so that
                the non-convex 60E1 outline is valid in any viewer/exporter.
MultiGeom    -> one closed mesh containing all parts (switch assembly)
PolylineGeom -> 3D line string (alignments, spatial markers)
ShapeGeom    -> closed 3D shape (footprints of site/railway/parts)
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from model.geom import BoxGeom, Mesh, MultiGeom, PolylineGeom, ShapeGeom, SweepGeom, cross, dot, norm, sub, unit

Vec3 = Tuple[float, float, float]


def _triangulate_planar(points: Sequence[Vec3]) -> List[Tuple[int, int, int]]:
    """Ear clipping of a simple planar polygon given in 3D."""
    n = len(points)
    if n < 3:
        return []
    # Newell normal
    nx = ny = nz = 0.0
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    normal = unit((nx, ny, nz))
    # 2D basis in the polygon plane
    ref = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0)
    ex = unit(cross(ref, normal))
    ey = cross(normal, ex)
    pts2 = [(dot(p, ex), dot(p, ey)) for p in points]

    def area2(i, j, k):
        a, b, c = pts2[i], pts2[j], pts2[k]
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def inside(p, a, b, c):
        d1 = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        d2 = (c[0] - b[0]) * (p[1] - b[1]) - (c[1] - b[1]) * (p[0] - b[0])
        d3 = (a[0] - c[0]) * (p[1] - c[1]) - (a[1] - c[1]) * (p[0] - c[0])
        return d1 >= -1e-12 and d2 >= -1e-12 and d3 >= -1e-12

    idx = list(range(n))
    # make counter-clockwise in the 2D basis
    if sum(area2(0, idx[i], idx[i + 1]) for i in range(1, n - 1)) < 0:
        idx.reverse()
        flip = True
    else:
        flip = False
    tris: List[Tuple[int, int, int]] = []
    guard = 0
    while len(idx) > 3 and guard < 10 * n:
        guard += 1
        for k in range(len(idx)):
            i, j, l = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if area2(i, j, l) <= 1e-14:
                continue
            if any(inside(pts2[m], pts2[i], pts2[j], pts2[l]) for m in idx if m not in (i, j, l)):
                continue
            tris.append((i, j, l))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    if flip:
        tris = [(c, b, a) for a, b, c in tris]
    return tris


def mesh_for(geom, triangulate_quads: bool = True) -> Mesh:
    """Closed, outward oriented mesh.  Faces with more than four vertices
    (section end caps) are ear-clipped; quads are split into two triangles by
    default because ruled quads between canted sections are slightly
    non-planar."""
    mesh = geom.to_mesh().oriented_outward()
    faces = []
    for f in mesh.faces:
        if len(f) == 3:
            faces.append(f)
        elif len(f) == 4:
            if triangulate_quads:
                faces.append((f[0], f[1], f[2]))
                faces.append((f[0], f[2], f[3]))
            else:
                faces.append(f)
        else:
            local = [mesh.vertices[i] for i in f]
            for a, b, c in _triangulate_planar(local):
                faces.append((f[a], f[b], f[c]))
    return Mesh(mesh.vertices, faces)


def place(backend, geom, level_id: int, color: int, weight: int, linear_solid_kind: str = "mesh"):
    """Create one DGN element for ``geom`` and return the backend handle."""
    if isinstance(geom, BoxGeom):
        return backend.add_box(geom.base_center, geom.x_axis, geom.y_axis, geom.size_x, geom.size_y, geom.size_z,
                               level_id, color, weight)
    if isinstance(geom, SweepGeom):
        if linear_solid_kind == "ruled_sweep":
            return backend.add_ruled_sweep(geom.sections, level_id, color, weight)
        m = mesh_for(geom)
        return backend.add_mesh(m.vertices, m.faces, level_id, color, weight)
    if isinstance(geom, MultiGeom):
        m = mesh_for(geom)
        return backend.add_mesh(m.vertices, m.faces, level_id, color, weight)
    if isinstance(geom, PolylineGeom):
        return backend.add_linestring(geom.points, level_id, color, weight)
    if isinstance(geom, ShapeGeom):
        return backend.add_shape(geom.points, level_id, color, weight)
    raise TypeError("Unsupported geometry %r" % type(geom))


def segment_length(points: Sequence[Vec3]) -> float:
    return sum(norm(sub(b, a)) for a, b in zip(points, points[1:]))
