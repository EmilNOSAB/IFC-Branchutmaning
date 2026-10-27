"""Design model: structure, classification, identities and quantities."""
import math

from model.geom import BoxGeom, MultiGeom, SweepGeom


def test_four_plain_and_two_turnout_parts(design_full):
    _, dm = design_full
    types = sorted(p.predefined_type for p in dm.parts)
    assert types == ["PLAINTRACK"] * 4 + ["TURNOUTTRACK"] * 2
    # parts on the same track are contiguous and cover the track
    for track in ("N", "S"):
        ps = sorted((p for p in dm.parts if p.track == track), key=lambda p: p.station_from)
        for a, b in zip(ps, ps[1:]):
            assert math.isclose(a.station_to, b.station_from, abs_tol=1e-9)


def test_unique_object_ids(design_full):
    _, dm = design_full
    ids = [c.object_id for c in dm.components]
    assert len(ids) == len(set(ids))


def test_every_physical_component_is_classified_and_has_a_part(design_full):
    _, dm = design_full
    part_ids = {p.object_id for p in dm.parts}
    for c in dm.components:
        if not c.is_physical:
            continue
        assert c.ifc_entity in ("IfcRail", "IfcTrackElement", "IfcCourse", "IfcElementAssembly"), c.object_id
        assert c.ifc_entity != "IfcBuildingElementProxy"
        assert c.predefined_type
        assert c.classifications, c.object_id
        assert c.spatial_parent in part_ids, c.object_id
        assert c.railway_part_id == c.spatial_parent
        assert c.level.startswith("BU26_")


def test_expected_ifc_classes_and_relations(design_full):
    _, dm = design_full
    by = dm.by_category()
    expect = {
        "RAIL_MAIN": ("IfcRail", "RAIL", "contained"), "RAIL_TURNOUT": ("IfcRail", "RAIL", "contained"),
        "RAIL_STOCK": ("IfcRail", "STOCKRAIL", "contained"), "RAIL_CHECK": ("IfcRail", "CHECKRAIL", "contained"),
        "FROG": ("IfcTrackElement", "FROG", "contained"), "SLEEPER": ("IfcTrackElement", "SLEEPER", "contained"),
        "SLEEPER_TURNOUT": ("IfcTrackElement", "SLEEPER", "contained"),
        "BALLAST": ("IfcCourse", "BALLASTBED", "contained"),
        "SWITCH_ASSEMBLY": ("IfcElementAssembly", "TRACTION_SWITCHING_ASSEMBLY", "aggregated"),
    }
    for cat, (ent, pdt, rel) in expect.items():
        assert by[cat], cat
        for c in by[cat]:
            assert (c.ifc_entity, c.predefined_type, c.spatial_relation) == (ent, pdt, rel)


def test_turnout_components_in_turnout_parts(design_full):
    _, dm = design_full
    turnout_parts = {p.object_id for p in dm.parts if p.predefined_type == "TURNOUTTRACK"}
    for c in dm.components:
        if c.category in ("RAIL_STOCK", "RAIL_CHECK", "RAIL_BLADE", "FROG", "SWITCH_ASSEMBLY", "SLEEPER_TURNOUT",
                          "RAIL_TURNOUT"):
            assert c.spatial_parent in turnout_parts, c.object_id
        if c.category in ("RAIL_MAIN", "SLEEPER"):
            assert c.spatial_parent not in turnout_parts, c.object_id
    by = dm.by_category()
    assert len(by["FROG"]) == 2 and len(by["SWITCH_ASSEMBLY"]) == 2
    assert len(by["RAIL_STOCK"]) == 4 and len(by["RAIL_CHECK"]) == 4


def test_plain_rails_are_inner_or_outer(design_full):
    _, dm = design_full
    for c in dm.by_category()["RAIL_MAIN"]:
        assert c.description in ("innerräl", "ytterräl")


def test_inner_rail_is_on_the_inside_of_the_curve(design_full):
    b, dm = design_full
    for c in dm.by_category()["RAIL_MAIN"]:
        tr = b.tracks[c.attributes["Track"]]
        # find a station inside the rail with clear curvature
        s = c.station_from
        while s < c.station_to:
            k = tr.horizontal.evaluate(s).curvature
            if abs(k) > 1e-3:
                left = c.attributes["Side"] == "V"
                inner_left = k < 0  # ccw: centre on the left
                assert (c.description == "innerräl") == (left == inner_left), (c.object_id, s)
                break
            s += 1.0


def test_meshes_closed_and_volumes_positive(design_preview):
    _, dm = design_preview
    for c in dm.components:
        g = c.geometry
        if isinstance(g, (SweepGeom, BoxGeom, MultiGeom)):
            m = g.to_mesh().oriented_outward()
            assert m.is_closed(), c.object_id
            assert m.volume() > 0, c.object_id


def test_box_volume_equals_mesh_volume():
    b = BoxGeom((10.0, 20.0, 3.0), (0.6, 0.8, 0.0), (-0.8, 0.6, 0.0), 0.3, 2.6, 0.22)
    assert math.isclose(b.to_mesh().oriented_outward().volume(), 0.3 * 2.6 * 0.22, rel_tol=1e-12)


def test_ballast_quantities(design_full):
    b, dm = design_full
    cfg = b.m["ballast"]
    for c in dm.by_category()["BALLAST"]:
        q = c.qtos["Qto_CourseBaseQuantities"]
        assert set(q) == {"Length", "Width", "Thickness", "GrossVolume", "Volume", "Weight"}
        # gross volume close to length x mean section area (section between 3.4/3.7 top and slope)
        assert q["GrossVolume"] > q["Volume"] > 0
        assert math.isclose(q["Weight"], q["Volume"] * cfg["density"], rel_tol=1e-5)  # volume rounded to 0.1 l
        est = q["Length"] * q["Thickness"] * (q["Width"] + 0.5 * q["Thickness"] * cfg["side_slope"])
        assert 0.85 < q["GrossVolume"] / est < 1.15, (c.object_id, q, est)


def test_sleeper_quantities_and_spacing(design_full):
    b, dm = design_full
    sl = [c for c in dm.by_category()["SLEEPER"] if c.railway_part_id == "RP-N1"]
    for c in sl:
        q = c.qtos["Qto_SleeperBaseQuantities"]
        assert math.isclose(q["Length"], 2.6, abs_tol=1e-6)
        assert q["Width"] == 0.3 and q["Height"] == 0.22
    st = sorted(c.station_from for c in sl)
    for a, b_ in zip(st, st[1:]):
        assert math.isclose(b_ - a, 0.6, abs_tol=1e-9)


def test_sleepers_follow_cant(design_full):
    b, dm = design_full
    tr = b.tracks["N"]
    c = min((c for c in dm.by_category()["SLEEPER"] if c.railway_part_id == "RP-N1"),
            key=lambda c: abs(c.station_from - 7070.0))
    y = c.geometry.y_axis
    f = tr.frame(c.station_from)
    # sleeper long axis tilted like the rail-top plane: z component = sin(roll)
    assert math.isclose(y[2], f.lateral[2], abs_tol=1e-9)
    assert math.isclose(math.asin(y[2]) * 1.5, 0.050, rel_tol=1e-3)


def test_preview_and_full_share_structure(design_full, design_preview):
    _, full = design_full
    _, prev = design_preview
    cats_full = {c.category for c in full.components}
    cats_prev = {c.category for c in prev.components}
    assert cats_full == cats_prev
    nf = {c.object_id for c in full.components if not c.category.startswith("SLEEPER")}
    npv = {c.object_id for c in prev.components if not c.category.startswith("SLEEPER")}
    assert nf == npv
    assert len(prev.by_category()["SLEEPER"]) < len(full.by_category()["SLEEPER"])


def test_frog_is_on_both_rails(design_full):
    b, dm = design_full
    for tid, lay in b.layouts.items():
        main, br = b.tracks[lay.main_key], b.tracks[lay.branch_key]
        p = lay.frog_point
        _, om = main.horizontal.project(p[0], p[1])
        _, ob = br.horizontal.project(p[0], p[1])
        assert math.isclose(om, lay.u_near, abs_tol=1e-6)
        assert math.isclose(ob, lay.u_far, abs_tol=1e-6)
