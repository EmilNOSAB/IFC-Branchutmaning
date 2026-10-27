"""Vertical profile, cant and the 3D track frame."""
import math

import pytest

from geometry.track import TrackGeometry
from geometry.vertical_profile import VerticalProfile


def test_profile_passes_pvis_on_tangents(landxml):
    for name in ("Del 1 - NSpår", "Del 1 - SSpår"):
        al = landxml.alignment(name)
        vp = VerticalProfile(al.profile)
        assert math.isclose(vp.evaluate(al.profile[0].station)[0], al.profile[0].elevation, abs_tol=1e-9)
        assert math.isclose(vp.evaluate(al.profile[-1].station)[0], al.profile[-1].elevation, abs_tol=1e-9)
        # continuity of elevation and grade at every BVC / EVC
        for c in vp.curves:
            for s in (c.bvc, c.evc):
                za, ga = vp.evaluate(s - 1e-6)
                zb, gb = vp.evaluate(s + 1e-6)
                assert abs(za - zb) < 1e-6 and abs(ga - gb) < 1e-5
            # PVI elevation is reached by the tangents, the curve passes below/above by L*dg/8
            zc, _ = vp.evaluate(c.pvi_station)
            assert math.isclose(zc - c.pvi_elevation, c.length * (c.grade_out - c.grade_in) / 8.0, abs_tol=1e-9)


def test_radius_mode_is_inconsistent_with_file(landxml):
    """Documented data observation: building the curves from the radii makes them overlap."""
    with pytest.raises(ValueError):
        VerticalProfile(landxml.alignment("Del 1 - NSpår").profile, mode="radius")


def test_radius_sign_matches_curve_type(landxml):
    for name in ("Del 1 - NSpår", "Del 1 - SSpår"):
        for chk in VerticalProfile(landxml.alignment(name).profile).checks():
            assert chk.sign_consistent


def test_cant_values_and_raised_side(landxml):
    t = TrackGeometry(landxml.alignment("Del 1 - NSpår"))
    # middle of the first (cw) circular curve: 50 mm, left (outer) rail raised
    c = t.cant.evaluate(7070.0)
    assert math.isclose(c.applied_m, 0.050) and c.raised_side == "left"
    # middle of the ccw curve: 50 mm, right rail raised
    c = t.cant.evaluate(7280.0)
    assert math.isclose(c.applied_m, 0.050) and c.raised_side == "right"
    # 295 m curve: 70 mm
    assert math.isclose(t.cant.evaluate(7515.0).applied_m, 0.070)
    # linear ramp in the transition (clothoid 6994.25 - 7014.25)
    assert math.isclose(t.cant.evaluate(7004.2537480).applied_m, 0.025, abs_tol=1e-9)
    assert t.cant.evaluate(7700.0).applied_m == 0.0


def test_cant_side_agrees_with_horizontal_curvature(landxml):
    for name in ("Del 1 - NSpår", "Del 1 - SSpår"):
        t = TrackGeometry(landxml.alignment(name))
        s = t.sta_start
        while s < t.sta_end:
            c = t.cant.evaluate(s)
            k = t.horizontal.evaluate(s).curvature
            if c.applied_m > 1e-6 and abs(k) > 1e-6:
                # positive curvature = right hand curve -> left rail raised
                assert (c.raised_side == "left") == (k > 0), (name, s)
            s += 1.0


def test_rail_heights_follow_cant_about_inner_rail(landxml):
    t = TrackGeometry(landxml.alignment("Del 1 - NSpår"))
    s = 7070.0
    f = t.frame(s)
    z_profile = t.elevation(s)[0]
    left = f.point(0.75, 0.0)
    right = f.point(-0.75, 0.0)
    # inner rail on the profile, outer rail raised by the cant.  Tolerance 0.1 mm: the
    # lateral axis is orthogonalised against the graded tangent (effect ~0.02 mm at 3.3 % grade)
    assert math.isclose(right[2], z_profile, abs_tol=1e-4)
    assert math.isclose(left[2] - right[2], 0.050, abs_tol=1e-4)
    # rotation matrix is orthonormal and right handed
    tx, lt, up = f.rotation_matrix
    for a in (tx, lt, up):
        assert math.isclose(sum(v * v for v in a), 1.0, abs_tol=1e-12)
    assert abs(sum(a * b for a, b in zip(tx, lt))) < 1e-12
    cr = (tx[1] * lt[2] - tx[2] * lt[1], tx[2] * lt[0] - tx[0] * lt[2], tx[0] * lt[1] - tx[1] * lt[0])
    assert all(math.isclose(a, b, abs_tol=1e-12) for a, b in zip(cr, up))


def test_frame_grade_matches_profile(landxml):
    t = TrackGeometry(landxml.alignment("Del 1 - SSpår"))
    f = t.frame(7100.0)
    g = t.elevation(7100.0)[1]
    assert math.isclose(f.tangent[2] / math.hypot(f.tangent[0], f.tangent[1]), g, rel_tol=1e-9)


def test_sampling_hits_breakpoints_and_chord_tolerance(landxml):
    t = TrackGeometry(landxml.alignment("Del 1 - NSpår"))
    st = t.stations(t.sta_start, t.sta_end, 2.0, 0.005)
    for seg in t.horizontal.segments:
        assert any(abs(s - seg.sta_start) < 1e-9 for s in st)
    for a, b in zip(st, st[1:]):
        assert 0 < b - a <= 2.0 + 1e-9
