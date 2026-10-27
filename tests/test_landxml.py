"""LandXML reading and horizontal geometry against the points stored in the file."""
import math

from geometry.alignment_math import HorizontalAlignment


def test_three_alignments_with_stationing_from_file(landxml):
    names = [a.name for a in landxml.alignments]
    assert names == ["Del 1 - NSpår", "Del 1 - SSpår", "Växel 1 - fiktiv förbindning"]
    starts = {a.name: a.sta_start for a in landxml.alignments}
    # stationing is taken from the file, not assumed to start at zero
    assert math.isclose(starts["Del 1 - NSpår"], 6950.0703640)
    assert math.isclose(starts["Del 1 - SSpår"], 6949.9970120)
    assert math.isclose(starts["Växel 1 - fiktiv förbindning"], 7920.0)
    assert landxml.linear_unit == "meter"
    assert landxml.grid_scale_factor == 1.0


def test_coordinate_order_northing_easting(landxml):
    n = landxml.alignment("Del 1 - NSpår")
    first = n.elements[0]
    # file: "6617370.644571 132866.057940" = N E
    assert math.isclose(first.start.y, 6617370.644571)
    assert math.isclose(first.start.x, 132866.057940)
    # azimuth of the first line computed from its end points equals 'dir'
    az = math.atan2(first.end.x - first.start.x, first.end.y - first.start.y)
    assert abs(az - first.dir_start) < 1e-8


def test_every_element_reproduces_landxml_end_points(landxml):
    for al in landxml.alignments:
        h = HorizontalAlignment(al)
        for chk in h.verify():
            assert chk.end_position_error < 5e-6, (al.name, chk)  # < 0.005 mm
            assert abs(chk.end_azimuth_error) < 1e-7, (al.name, chk)
            assert chk.start_gap < 1e-6
            assert abs(chk.station_gap) < 1e-6


def test_element_types_present(landxml):
    kinds = {e.kind for a in landxml.alignments for e in a.elements}
    assert kinds == {"Line", "Curve", "Spiral"}


def test_curve_points_lie_on_circle(landxml):
    for al in landxml.alignments:
        h = HorizontalAlignment(al)
        for seg in h.segments:
            if seg.kind != "Curve":
                continue
            c = seg.el.center
            for t in (0.0, 0.25, 0.5, 0.75, 1.0):
                p = seg.evaluate(t * seg.length)
                assert abs(math.hypot(p.x - c.x, p.y - c.y) - seg.el.radius) < 1e-6


def test_clothoid_curvature_linear_and_theta(landxml):
    al = landxml.alignment("Del 1 - NSpår")
    h = HorizontalAlignment(al)
    sp = next(s for s in h.segments if s.kind == "Spiral")
    assert sp.curvature_at(0) == 0.0
    assert math.isclose(sp.curvature_at(sp.length), 1 / 153.0, rel_tol=1e-9)
    # total deflection = L / 2R = theta from the file
    assert math.isclose(sp.azimuth_at(sp.length) - sp.az0, 0.065359477, rel_tol=1e-7)


def test_projection_roundtrip(landxml):
    h = HorizontalAlignment(landxml.alignment("Del 1 - SSpår"))
    for s in (6960.0, 7100.0, 7250.0, 7500.0, 7990.0):
        p = h.evaluate(s)
        nx, ny = p.left_normal
        st, off = h.project(p.x + 2.0 * nx, p.y + 2.0 * ny)
        assert abs(st - s) < 1e-6 and abs(off - 2.0) < 1e-6
