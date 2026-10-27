"""Builds the complete design model (all DGN objects with metadata) from the
configuration and the LandXML file.

The result is independent of MicroStation; microstation/build_railway_dgn.py
instantiates every ``Component`` as a native DGN element.  Preview and full
mode produce the same object classification and structure, only the geometric
density (sweep sampling, rail profile, every n-th sleeper) differs.

Layout of the crossover (from the LandXML data):
  * turnout A on the N track (switch toe at the start of the branch), turnout B
    on the S track (toe at the end of the branch)
  * railway parts: N1 | A | N2 on N and S1 | B | S2 on S, split at the
    mid point between the two frogs; 4 x PLAINTRACK + 2 x TURNOUTTRACK
  * in the crossover zone common long sleepers span both tracks (configurable)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from common.config import Config
from geometry.georef import SWEREF99_1800
from geometry.landxml_reader import read_landxml
from geometry.track import TrackGeometry

from .components import Component, DesignModel, RailwayPartDef
from .geom import (BoxGeom, Mesh, MultiGeom, PolylineGeom, ShapeGeom, SweepGeom, add, convex_hull_xy, cross,
                   dot, norm, polygon_area_2d, scale, sub, unit)
from .turnout import TurnoutLayout, compute_layout

Vec3 = Tuple[float, float, float]
Outline = List[Tuple[float, float]]


def _fmt(template: Optional[str], **kw) -> str:
    if not template:
        return ""
    try:
        return template.format(**kw)
    except KeyError as e:  # pragma: no cover - configuration error
        raise KeyError("Template %r uses unknown field %s" % (template, e))


class RailwayModelBuilder:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.m = cfg.model
        self.ms = cfg.mode_settings
        self.rc = float(self.m["track"]["rail_centre_distance"])
        prof = self.m["rail_profiles"][self.ms["rail_profile"]]
        self.rail_outline: Outline = [tuple(p) for p in prof["outline"]]
        self.rail_height = float(prof["height"])
        self.pad = float(self.m["track"]["rail_pad_thickness"])
        sl = self.m["sleepers"]
        self.sl_len, self.sl_w, self.sl_h = float(sl["length"]), float(sl["width"]), float(sl["height"])
        self.v_sleeper_top = -(self.rail_height + self.pad)
        self.components: List[Component] = []
        self.report: Dict[str, Any] = {"warnings": [], "mode": cfg.mode}
        self.doc = read_landxml(cfg.file("landxml"))
        vmode = self.m.get("vertical_curve_mode", "length")
        self.al_cfg = {a["key"]: a for a in self.m["alignments"]}
        self.tracks: Dict[str, TrackGeometry] = {
            k: TrackGeometry(self.doc.alignment(a["landxml_name"]), vertical_mode=vmode) for k, a in self.al_cfg.items()
        }

    # ------------------------------------------------------------------ helpers
    def _cat(self, category: str) -> Dict[str, Any]:
        return self.cfg.category(category)

    def _new(self, category: str, object_id: str, geometry, fmt: Dict[str, Any], **kw) -> Component:
        c = self._cat(category)
        comp = Component(
            object_id=object_id, category=category,
            name=kw.pop("name", None) or _fmt(c.get("name"), **fmt),
            description=kw.pop("description", None) or _fmt(c.get("description"), **fmt),
            level=c["level"], ifc_entity=c["ifc_entity"],
            predefined_type=kw.pop("predefined_type", c.get("predefined_type")),
            geometry=geometry, spatial_relation=kw.pop("spatial_relation", c.get("spatial_relation", "none")),
            classifications=[tuple(x) for x in c.get("classifications", [])], **kw,
        )
        self.components.append(comp)
        return comp

    def _sampling(self, track: TrackGeometry, s0: float, s1: float) -> List[float]:
        return track.stations(min(s0, s1), max(s0, s1), float(self.ms["max_step"]), float(self.ms["max_chord_error"]))

    def _rail_sweep(self, pieces: Sequence[Tuple[TrackGeometry, float, float, Any]], outline: Outline) -> SweepGeom:
        """Sweep ``outline`` along consecutive pieces (track, s0, s1, u) where u
        is a constant or a function f(station) giving the lateral offset."""
        sections: List[List[Vec3]] = []
        for track, s0, s1, u in pieces:
            stas = self._sampling(track, s0, s1)
            for s in stas:
                uu = u(s) if callable(u) else u
                f = track.frame(s)
                sec = [f.point(uu + pu, pv) for pu, pv in outline]
                if sections and max(norm(sub(a, b)) for a, b in zip(sections[-1], sec)) < 1e-4:
                    continue
                sections.append(sec)
        return SweepGeom(sections)

    @staticmethod
    def _mesh_quantities(geom) -> Tuple[float, Mesh]:
        mesh = geom.to_mesh().oriented_outward()
        return mesh.volume(), mesh

    # ------------------------------------------------------------- preparation
    def _prepare_branch_profile(self) -> None:
        mode = self.m.get("branch_profile", "landxml")
        branch_keys = [k for k, a in self.al_cfg.items() if a.get("role") == "branch"]
        info = {}
        for bk in branch_keys:
            br = self.tracks[bk]
            # elevation difference at both ends to the main track it meets
            dz = {}
            for t in self.m["turnouts"]:
                if t["branch"] != bk:
                    continue
                main = self.tracks[t["main_track"]]
                sb = br.sta_start if t["branch_end"] == "start" else br.sta_end
                h = br.horizontal.evaluate(sb)
                sm, _ = main.horizontal.project(h.x, h.y)
                dz[t["branch_end"]] = main.elevation(sm)[0] - br.elevation(sb)[0]
            info[bk] = {"dz_start": dz.get("start", 0.0), "dz_end": dz.get("end", 0.0), "mode": mode}
            if mode == "adapt_to_main":
                a = dz.get("start", 0.0)
                b = (dz.get("end", 0.0) - a) / (br.sta_end - br.sta_start)
                br.z_correction = (a, b)
            elif mode != "landxml":
                raise ValueError("branch_profile must be 'landxml' or 'adapt_to_main'")
            for end, v in dz.items():
                if abs(v) > 0.005:
                    self.report["warnings"].append(
                        "Branch %s %s elevation differs %.3f m from the main track (branch_profile=%s)" % (bk, end, -v, mode))
        self.report["branch_profile"] = info

    def _curve_zones(self, track: TrackGeometry) -> List[Tuple[float, float, str]]:
        """Split the track into zones each dominated by one curve direction
        (consecutive curves turning the same way share a zone).  Zone limits
        lie at the middle of the tangent between curves of opposite direction.
        Returns (s0, s1, rot) with rot in {'cw', 'ccw', 'none'}."""
        merged: List[Tuple[float, float, str]] = []
        for seg in track.horizontal.segments:
            if seg.kind in ("Curve", "Spiral") and seg.el.rot:
                s0, s1 = seg.sta_start, seg.sta_start + seg.length
                if merged and merged[-1][2] == seg.el.rot:
                    merged[-1] = (merged[-1][0], s1, seg.el.rot)
                else:
                    merged.append((s0, s1, seg.el.rot))
        if not merged:
            return [(track.sta_start, track.sta_end, "none")]
        zones: List[Tuple[float, float, str]] = []
        start = track.sta_start
        for i, (c0, c1, rot) in enumerate(merged):
            end = 0.5 * (c1 + merged[i + 1][0]) if i + 1 < len(merged) else track.sta_end
            zones.append((start, end, rot))
            start = end
        return zones

    def _rail_position(self, zones, s0: float, s1: float, u: float) -> str:
        mid = 0.5 * (s0 + s1)
        for z0, z1, rot in zones:
            if z0 - 1e-6 <= mid <= z1 + 1e-6:
                if rot == "none":
                    return "innerräl" if u < 0 else "ytterräl"
                inner_left = rot == "ccw"
                return "innerräl" if (u > 0) == inner_left else "ytterräl"
        return "ytterräl"

    # ---------------------------------------------------------------- building
    def build(self) -> DesignModel:
        self._prepare_branch_profile()
        layouts = [compute_layout(t, self.tracks, self.rc) for t in self.m["turnouts"]]
        for lay in layouts:
            self.report["warnings"].extend("%s: %s" % (lay.turnout_id, w) for w in lay.warnings)
        self.layouts = {l.turnout_id: l for l in layouts}
        parts = self._define_parts(layouts)
        self.parts = parts
        self.part_by_key = {p.key: p for p in parts}
        self._spatial_objects(parts)
        self._alignments()
        sleepers_by_part = self._sleepers(parts, layouts)
        self._rails(parts, layouts)
        for lay in layouts:
            self._turnout_components(lay)
        self._ballast(parts, sleepers_by_part)
        self._finalise_spatial(parts)
        self.report["counts"] = {}
        for c in self.components:
            self.report["counts"][c.category] = self.report["counts"].get(c.category, 0) + 1
        self.report["turnouts"] = {
            l.turnout_id: {
                "main_track": l.main_key, "toe_main_station": round(l.toe_main, 4),
                "toe_branch_station": round(l.toe_branch, 4), "frog_main_station": round(l.frog_main, 4),
                "frog_branch_station": round(l.frog_branch, 4), "frog_angle_deg": round(math.degrees(l.frog_angle), 4),
                "frog_ratio_1_to": round(1.0 / math.tan(l.frog_angle), 2), "blade_length": round(l.blade_length, 3),
                "branch_side": "left" if l.sb > 0 else "right",
            } for l in layouts
        }
        self.report["railway_parts"] = [
            {"key": p.key, "id": p.object_id, "type": p.predefined_type, "track": p.track,
             "station_from": round(p.station_from, 4), "station_to": round(p.station_to, 4)} for p in parts
        ]
        return DesignModel(self.components, parts, self.report)

    def _define_parts(self, layouts: List[TurnoutLayout]) -> List[RailwayPartDef]:
        lay = {l.turnout_id: l for l in layouts}
        pcfg = {p["key"]: p for p in self.m["railway_parts"]}
        # crossover split: mid point between the frogs on the branch
        branch_keys = {l.branch_key for l in layouts}
        self.split: Dict[str, float] = {}
        if len(layouts) == 2 and len(branch_keys) == 1:
            bk = layouts[0].branch_key
            v_split = 0.5 * (layouts[0].frog_branch + layouts[1].frog_branch)
            br = self.tracks[bk]
            p = br.horizontal.evaluate(v_split)
            for l in layouts:
                sm, _ = self.tracks[l.main_key].horizontal.project(p.x, p.y)
                self.split[l.turnout_id] = sm
            self.split["_branch"] = v_split
        else:
            for l in layouts:
                # single turnout: part ends behind the frog
                self.split[l.turnout_id] = l.frog_main + l.d * (0.5 * float(l.params["frog_length"]) + float(l.params["frog_tail"]))
        self.turnout_range: Dict[str, Tuple[float, float]] = {}
        for l in layouts:
            lead = l.toe_main - l.d * float(l.params["part_lead_in"])
            a, b = sorted((lead, self.split[l.turnout_id]))
            self.turnout_range[l.turnout_id] = (a, b)
        out: List[RailwayPartDef] = []
        for key, p in pcfg.items():
            tr = self.tracks[p["track"]]
            if "station_from" in p and "station_to" in p:
                s0, s1 = float(p["station_from"]), float(p["station_to"])
            elif p["predefined_type"] == "TURNOUTTRACK":
                s0, s1 = self.turnout_range[p["turnout"]]
            else:
                s0, s1 = tr.sta_start, tr.sta_end
                for l in layouts:
                    if l.main_key != p["track"]:
                        continue
                    a, b = self.turnout_range[l.turnout_id]
                    # plain part before or after the turnout on the same track
                    others = [q for q in pcfg.values() if q["track"] == p["track"]]
                    idx = [q["key"] for q in others].index(key)
                    t_idx = [q["key"] for q in others].index(next(q["key"] for q in others if q.get("turnout") == l.turnout_id))
                    if idx < t_idx:
                        s1 = min(s1, a)
                    else:
                        s0 = max(s0, b)
            out.append(RailwayPartDef(key, p["id"], p["track"], p["predefined_type"], p["name"], p["long_name"],
                                      p["description"], s0, s1, p.get("turnout")))
        n_plain = sum(1 for p in out if p.predefined_type == "PLAINTRACK")
        n_turn = sum(1 for p in out if p.predefined_type == "TURNOUTTRACK")
        if (n_plain, n_turn) != (4, 2):
            self.report["warnings"].append("Expected 4 PLAINTRACK + 2 TURNOUTTRACK, got %d + %d" % (n_plain, n_turn))
        for p in out:
            if p.station_to - p.station_from < 1.0:
                raise ValueError("Railway part %s has no length (%.3f-%.3f)" % (p.key, p.station_from, p.station_to))
        return out

    def _part_at(self, track_key: str, station: float) -> RailwayPartDef:
        best = None
        for p in self.parts:
            if p.track == track_key and p.station_from - 1e-6 <= station <= p.station_to + 1e-6:
                if best is None or (p.predefined_type == "TURNOUTTRACK"):
                    best = p
        if best is None:
            raise ValueError("Station %.3f on %s is outside all railway parts" % (station, track_key))
        return best

    # ---------------------------------------------------------- spatial objects
    def _spatial_objects(self, parts: List[RailwayPartDef]) -> None:
        m = self.m
        n = self.tracks[self.m["alignments"][0]["key"]]
        f0 = n.frame(n.sta_start)
        self.ref_point = (f0.horizontal.x, f0.horizontal.y, f0.elevation) if m["coordinate_system"]["site_reference_point"] == "auto" \
            else tuple(m["coordinate_system"]["site_reference_point"])
        lat, lon = SWEREF99_1800.to_geodetic(self.ref_point[1], self.ref_point[0])
        self.report["site_reference"] = {"easting": self.ref_point[0], "northing": self.ref_point[1],
                                         "elevation": self.ref_point[2], "latitude": lat, "longitude": lon}
        marker = PolylineGeom([self.ref_point, add(self.ref_point, (1.0, 0.0, 0.0))])
        pj = m["project"]
        self._new("SPATIAL_PROJECT", "PRJ-1", marker, {}, name=pj["name"], description=pj["description"],
                  long_name=pj["long_name"], spatial_relation="none",
                  attributes={"Phase": pj["phase"]})
        st = m["site"]
        self._new("SPATIAL_SITE", "SITE-1", None, {}, name=st["name"], description=st["description"],
                  long_name=st["long_name"], spatial_parent="PRJ-1", spatial_relation="aggregated",
                  attributes={"RefLatitude": lat, "RefLongitude": lon, "RefElevation": self.ref_point[2],
                              "LandTitleNumber": st.get("land_title_number", "")})
        rw = m["railway"]
        self._new("SPATIAL_RAILWAY", rw["id"], None, {}, name=rw["name"], description=rw["description"],
                  long_name=rw["long_name"], object_type=rw["object_type"], spatial_parent="SITE-1",
                  spatial_relation="aggregated")
        sz = m["spatial_zone"]
        self._new("SPATIAL_ZONE", sz["id"], None, {}, name=sz["name"], description=sz["description"],
                  long_name=sz["long_name"], object_type=sz["object_type"], predefined_type=None,
                  spatial_parent="PRJ-1", spatial_relation="aggregated",
                  attributes={"PredefinedType": sz["predefined_type"]})
        bs = m["built_system"]
        self._new("BUILT_SYSTEM", bs["id"], PolylineGeom([self.ref_point, add(self.ref_point, (0.0, 1.0, 0.0))]), {},
                  name=bs["name"], description=bs["description"], long_name=bs["long_name"],
                  spatial_relation="none",
                  psets={"Pset_BuiltSystemRailwayTrack": {
                      "TrackID": str(bs["track_id"]), "TrackNumber": str(bs["track_number"]),
                      "TrackUsage": bs["track_usage"], "TrackCharacteristic": bs["track_characteristic"]}})
        for p in parts:
            cat = "SPATIAL_RAILWAYPART_PLAIN" if p.predefined_type == "PLAINTRACK" else "SPATIAL_RAILWAYPART_TURNOUT"
            self._new(cat, p.object_id, None, {}, name=p.name, description=p.description, long_name=p.long_name,
                      spatial_parent=rw["id"], spatial_relation="aggregated", railway_part_id=p.object_id,
                      alignment_id=self.al_cfg[p.track]["id"], station_from=p.station_from, station_to=p.station_to,
                      attributes={"UsageType": self.m["railway_part_usage_type"], "Track": p.track},
                      psets={"Pset_RailwayTrackStructurePart": dict(self.m["track_structure_pset"])},
                      groups=[bs["id"]])

    def _alignments(self) -> None:
        for key, a in self.al_cfg.items():
            tr = self.tracks[key]
            stas = self._sampling(tr, tr.sta_start, tr.sta_end)
            pts = []
            for s in stas:
                h = tr.horizontal.evaluate(s)
                pts.append((h.x, h.y, tr.elevation(s)[0]))
            self._new("ALIGNMENT", a["id"], PolylineGeom(pts), {"alignment": a["name"]}, name=a["name"],
                      description=a["description"], object_type=a.get("object_type"), alignment_id=a["id"],
                      station_from=tr.sta_start, station_to=tr.sta_end, spatial_parent="SITE-1",
                      spatial_relation="referenced",
                      attributes={"LandXmlName": a["landxml_name"], "Role": a["role"],
                                  "LandXmlGuid": tr.alignment.guid or ""})

    # ----------------------------------------------------------------- sleepers
    def _sleeper_grid(self, track: TrackGeometry, s0: float, s1: float) -> List[float]:
        sp = float(self.m["sleepers"]["spacing"])
        first = track.sta_start + float(self.m["sleepers"]["first_offset"])
        k0 = max(0, int(math.ceil((s0 - first) / sp - 1e-9)))
        out = []
        k = k0
        every = int(self.ms.get("sleeper_every_n", 1))
        while True:
            s = first + k * sp
            if s > s1 + 1e-9 or s > track.sta_end:
                break
            if s >= s0 - 1e-9 and k % every == 0:
                out.append(s)
            k += 1
        return out

    def _sleeper_box(self, track: TrackGeometry, s: float, u_left: float, u_right: float,
                     other: Optional[Tuple[TrackGeometry, float, float]] = None) -> BoxGeom:
        """Sleeper perpendicular to ``track`` at station ``s``.  Without
        ``other`` it spans u_right..u_left on this track.  With
        ``other = (track_b, station_b, offset_b)`` it is a common long sleeper
        from this track's outer end to the other track's outer end."""
        f = track.frame(s)
        if other is None:
            e_left = f.point(u_left, self.v_sleeper_top)
            e_right = f.point(u_right, self.v_sleeper_top)
        else:
            ot, s_o, o = other
            fo = ot.frame(s_o)
            if o < 0:  # other track on the right
                e_left = f.point(u_left, self.v_sleeper_top)
                e_right = fo.point(u_right, self.v_sleeper_top)
            else:
                e_left = fo.point(u_left, self.v_sleeper_top)
                e_right = f.point(u_right, self.v_sleeper_top)
        x = f.tangent
        yv = sub(e_left, e_right)
        yv = sub(yv, scale(x, dot(yv, x)))
        length = norm(yv)
        y = unit(yv)
        z = cross(x, y)
        mid = scale(add(e_left, e_right), 0.5)
        base = sub(mid, scale(z, self.sl_h))
        return BoxGeom(base, x, y, self.sl_w, length, self.sl_h)

    def _add_sleeper(self, part: RailwayPartDef, box: BoxGeom, seq: int, turnout: bool, track_key: str,
                     station: float) -> Component:
        cat = "SLEEPER_TURNOUT" if turnout else "SLEEPER"
        comp = self._new(cat, "%s-SLP-%05d" % (part.object_id, seq), box, {"part": part.name, "seq": seq},
                         spatial_parent=part.object_id, railway_part_id=part.object_id,
                         alignment_id=self.al_cfg[track_key]["id"], station_from=station, station_to=station,
                         qtos={"Qto_SleeperBaseQuantities": {"Length": round(box.size_y, 4), "Width": box.size_x,
                                                             "Height": box.size_z}},
                         psets={"Pset_TrackElementOccurrenceSleeper": {"HasSpecialEquipment": False,
                                                                       "IsContaminatedSleeper": False}},
                         attributes={"Material": self.m["sleepers"]["material"],
                                     "TypeName": self.m["sleepers"]["type_name"],
                                     "Sequence": seq},
                         groups=[part.object_id])
        return comp

    def _sleepers(self, parts: List[RailwayPartDef], layouts: List[TurnoutLayout]) -> Dict[str, List[Component]]:
        by_part: Dict[str, List[Component]] = {p.object_id: [] for p in parts}
        seq: Dict[str, int] = {p.object_id: 0 for p in parts}
        half = 0.5 * self.sl_len
        common = bool(self.m["sleepers"]["turnout"].get("crossover_common_sleepers", True)) and \
            len(layouts) == 2 and len({l.branch_key for l in layouts}) == 1 and layouts[0].main_key != layouts[1].main_key
        zone: Dict[str, Tuple[float, float]] = {}
        if common:
            la, lb = layouts
            ta, tb = self.tracks[la.main_key], self.tracks[lb.main_key]
            a0, a1 = self.turnout_range[la.turnout_id]
            b0, b1 = self.turnout_range[lb.turnout_id]
            # zone limits on track A expressed on A and on B
            pa = ta.horizontal.evaluate(a0 if la.d > 0 else a1)
            pb = tb.horizontal.evaluate(b1 if lb.d < 0 else b0)
            za0 = a0 if la.d > 0 else a1
            zb_on_a, _ = ta.horizontal.project(pb.x, pb.y)
            zone[la.main_key] = tuple(sorted((za0, zb_on_a)))
            za_on_b, _ = tb.horizontal.project(pa.x, pa.y)
            zb1 = b1 if lb.d < 0 else b0
            zone[lb.main_key] = tuple(sorted((za_on_b, zb1)))
            self.report["crossover_zone"] = {k: [round(v[0], 3), round(v[1], 3)] for k, v in zone.items()}
            # common sleepers along track A
            z0, z1 = zone[la.main_key]
            for s in self._sleeper_grid(ta, z0, z1):
                h = ta.horizontal.evaluate(s)
                sb, off = tb.horizontal.project(h.x, h.y, sta_hint=s - (b0 - a0))
                # offset of B relative to A in A's frame
                hb = tb.horizontal.evaluate(sb)
                nx, ny = h.left_normal
                o = (hb.x - h.x) * nx + (hb.y - h.y) * ny
                box = self._sleeper_box(ta, s, half, -half, other=(tb, sb, o))
                part = self.part_by_key[next(p.key for p in parts if p.turnout_id == la.turnout_id)] \
                    if (s - self.split[la.turnout_id]) * la.d < 0 else \
                    self.part_by_key[next(p.key for p in parts if p.turnout_id == lb.turnout_id)]
                seq[part.object_id] += 1
                by_part[part.object_id].append(self._add_sleeper(part, box, seq[part.object_id], True, la.main_key, s))
        max_len = float(self.m["sleepers"]["turnout"]["max_length"])
        over = float(self.m["sleepers"]["turnout"]["overhang"])
        for p in parts:
            tr = self.tracks[p.track]
            for s in self._sleeper_grid(tr, p.station_from, p.station_to):
                if p.track in zone and zone[p.track][0] - 1e-6 <= s <= zone[p.track][1] + 1e-6:
                    continue
                # avoid double sleepers on shared part boundaries
                if s >= p.station_to - 1e-9 and p.station_to < tr.sta_end:
                    continue
                if p.predefined_type == "TURNOUTTRACK" and not common:
                    lay = self.layouts[p.turnout_id]
                    br = self.tracks[lay.branch_key]
                    h = tr.horizontal.evaluate(s)
                    vb, off = br.horizontal.project(h.x, h.y)
                    hb = br.horizontal.evaluate(vb)
                    nx, ny = h.left_normal
                    o = (hb.x - h.x) * nx + (hb.y - h.y) * ny
                    ul = max(half, o + 0.5 * self.rc + over)
                    ur = min(-half, o - 0.5 * self.rc - over)
                    if ul - ur > max_len:
                        ul, ur = half, -half
                    box = self._sleeper_box(tr, s, ul, ur)
                    turnout_sleeper = True
                else:
                    box = self._sleeper_box(tr, s, half, -half)
                    turnout_sleeper = p.predefined_type == "TURNOUTTRACK"
                seq[p.object_id] += 1
                by_part[p.object_id].append(self._add_sleeper(p, box, seq[p.object_id], turnout_sleeper, p.track, s))
        return by_part

    # -------------------------------------------------------------------- rails
    def _rail_component(self, category: str, object_id: str, part: RailwayPartDef, pieces, outline: Outline,
                        fmt: Dict[str, Any], track_key: str, s0: float, s1: float, attrs: Dict[str, Any],
                        description: Optional[str] = None) -> Component:
        geom = self._rail_sweep(pieces, outline)
        return self._new(category, object_id, geom, fmt, description=description, spatial_parent=part.object_id,
                         railway_part_id=part.object_id, alignment_id=self.al_cfg[track_key]["id"],
                         station_from=min(s0, s1), station_to=max(s0, s1), attributes=attrs,
                         groups=[part.object_id])

    def _rails(self, parts: List[RailwayPartDef], layouts: List[TurnoutLayout]) -> None:
        """Running rails of the main tracks (plain parts and through rails in
        turnout parts).  Switch/frog areas are cut out and modelled in
        _turnout_components."""
        half = 0.5 * self.rc
        cut: Dict[Tuple[str, float], List[Tuple[float, float]]] = {}
        for l in layouts:
            p = l.params
            stock = sorted((l.toe_main - l.d * float(p["stock_rail_overhang"]), l.toe_main + l.d * l.blade_length))
            frog = sorted((l.frog_main - 0.5 * float(p["frog_length"]), l.frog_main + 0.5 * float(p["frog_length"])))
            cut.setdefault((l.main_key, l.u_far), []).append(tuple(stock))
            cut.setdefault((l.main_key, l.u_near), []).append(tuple(stock))
            cut.setdefault((l.main_key, l.u_near), []).append(tuple(frog))
        zones_cache = {k: self._curve_zones(t) for k, t in self.tracks.items()}
        self.report["curve_zones"] = {k: [(round(a, 3), round(b, 3), r) for a, b, r in z] for k, z in zones_cache.items()}
        for part in parts:
            tr = self.tracks[part.track]
            zones = zones_cache[part.track]
            for u, side in ((half, "V"), (-half, "H")):
                # intervals of this rail inside the part, minus cut-outs
                ivs = [(part.station_from, part.station_to)]
                for c0, c1 in cut.get((part.track, u), []):
                    nxt = []
                    for a, b in ivs:
                        if c1 <= a or c0 >= b:
                            nxt.append((a, b))
                            continue
                        if a < c0:
                            nxt.append((a, c0))
                        if c1 < b:
                            nxt.append((c1, b))
                    ivs = nxt
                # split at curve zone limits so each rail is entirely inner or outer rail
                pieces = []
                for a, b in ivs:
                    bounds = sorted({a, b} | {z for z0, z1, _ in zones for z in (z0, z1) if a < z < b})
                    pieces.extend(zip(bounds, bounds[1:]))
                k = 0
                for a, b in pieces:
                    if b - a < 0.05:
                        continue
                    k += 1
                    pos = self._rail_position(zones, a, b, u)
                    cat = "RAIL_MAIN" if part.predefined_type == "PLAINTRACK" else "RAIL_TURNOUT"
                    oid = "%s-RAIL-%s%02d" % (part.object_id, side, k)
                    self._rail_component(cat, oid, part, [(tr, a, b, u)], self.rail_outline,
                                         {"track": part.track, "side": side, "seq": k, "position": pos,
                                          "turnout": part.turnout_id or "", "part": part.name},
                                         part.track, a, b, {"Side": side, "Position": pos, "Track": part.track},
                                         description=pos)

    # ----------------------------------------------------------------- turnouts
    def _turnout_components(self, l: TurnoutLayout) -> None:
        p = l.params
        main, br = self.tracks[l.main_key], self.tracks[l.branch_key]
        part = next(x for x in self.parts if x.turnout_id == l.turnout_id)
        d, sb = l.d, l.sb
        half = 0.5 * self.rc
        u_near, u_far = l.u_near, l.u_far
        toe, vt, bl = l.toe_main, l.toe_branch, l.blade_length
        oh = float(p["stock_rail_overhang"])
        fl = float(p["frog_length"])
        zones_b = self._curve_zones(br)
        side_name = {+1: "V", -1: "H"}
        tid = l.turnout_id
        fmt = {"turnout": l.name, "part": part.name, "track": l.main_key}

        # stock rails: far (straight) and near (bent: main near rail before toe + branch near rail after)
        a, b = sorted((toe - d * oh, toe + d * bl))
        self._rail_component("RAIL_STOCK", "%s-STK-%s" % (tid, side_name[int(math.copysign(1, u_far))]), part,
                             [(main, a, b, u_far)], self.rail_outline, dict(fmt, side=side_name[int(math.copysign(1, u_far))]),
                             l.main_key, a, b, {"Side": "far", "Turnout": tid})
        if d > 0:
            pieces = [(main, toe - oh, toe, u_near), (br, vt, vt + bl, u_near)]
        else:
            pieces = [(br, vt - bl, vt, u_near), (main, toe, toe + oh, u_near)]
        self._rail_component("RAIL_STOCK", "%s-STK-%s" % (tid, side_name[int(math.copysign(1, u_near))]), part,
                             pieces, self.rail_outline, dict(fmt, side=side_name[int(math.copysign(1, u_near))]),
                             l.main_key, a, b, {"Side": "near", "Turnout": tid})

        # switch blades: tapered profile, offset inwards at the toe, closing to the rail line at the heel
        blade_outline: Outline = [(-0.025, -self.rail_height), (0.025, -self.rail_height), (0.025, 0.0), (-0.025, 0.0)]
        inward = 0.036 + 0.025 + 0.002

        def blade_u(base_u, inward_sign, start, length):
            return lambda s: base_u + inward_sign * inward * max(0.0, 1.0 - abs(s - start) / length)

        # straight blade along main near rail (inside = towards main centre = -sign(u_near))
        a, b = sorted((toe, toe + d * bl))
        self._rail_component("RAIL_BLADE", "%s-TNG-RAK" % tid, part,
                             [(main, a, b, blade_u(u_near, -math.copysign(1, u_near), toe, bl))], blade_outline,
                             dict(fmt, side="rak"), l.main_key, a, b, {"Route": "straight", "Turnout": tid})
        # curved blade along branch far rail (inside = towards branch centre)
        a, b = sorted((vt, vt + d * bl))
        self._rail_component("RAIL_BLADE", "%s-TNG-KRK" % tid, part,
                             [(br, a, b, blade_u(u_far, -math.copysign(1, u_far), vt, bl))], blade_outline,
                             dict(fmt, side="krok"), l.branch_key, a, b, {"Route": "diverging", "Turnout": tid})

        # branch rails inside this turnout part (up to the crossover split)
        v_split = self.split.get("_branch")
        if v_split is None:
            v_split = l.frog_branch + d * (0.5 * fl + float(p["frog_tail"]))
        heel = vt + d * bl
        # far rail: heel -> frog nose, frog tail -> split ; near rail: heel -> split
        segs = [
            ("BR-%s" % side_name[int(math.copysign(1, u_far))], u_far, [(heel, l.frog_branch - d * 0.5 * fl),
                                                                        (l.frog_branch + d * 0.5 * fl, v_split)]),
            ("BR-%s" % side_name[int(math.copysign(1, u_near))], u_near, [(heel, v_split)]),
        ]
        for name, u, ivs in segs:
            for k, (s0, s1) in enumerate(ivs, 1):
                a, b = sorted((s0, s1))
                if b - a < 0.05:
                    continue
                pos = self._rail_position(zones_b, a, b, u)
                self._rail_component("RAIL_TURNOUT", "%s-RAIL-%s%02d" % (tid, name, k), part, [(br, a, b, u)],
                                     self.rail_outline, dict(fmt, side=name, seq=k, position=pos),
                                     l.branch_key, a, b, {"Side": name, "Position": pos, "Track": l.branch_key},
                                     description=pos)

        # check rails (moträler) opposite the frog: main far rail and branch near rail
        cl = float(p["check_rail_length"])
        fw = float(p["flangeway"])
        chk_outline: Outline = [(-0.035, -0.150), (0.035, -0.150), (0.035, 0.020), (-0.035, 0.020)]
        shift = 0.036 + fw + 0.035
        u_chk_main = u_far - math.copysign(1, u_far) * shift
        a, b = l.frog_main - 0.5 * cl, l.frog_main + 0.5 * cl
        self._rail_component("RAIL_CHECK", "%s-MOT-HUVUD" % tid, part, [(main, a, b, u_chk_main)], chk_outline,
                             dict(fmt, side="huvudspår"), l.main_key, a, b, {"Track": l.main_key, "Turnout": tid})
        u_chk_br = u_near - math.copysign(1, u_near) * shift
        a, b = l.frog_branch - 0.5 * cl, l.frog_branch + 0.5 * cl
        self._rail_component("RAIL_CHECK", "%s-MOT-AVV" % tid, part, [(br, a, b, u_chk_br)], chk_outline,
                             dict(fmt, side="avvikande spår"), l.branch_key, a, b, {"Track": l.branch_key, "Turnout": tid})

        # frog: wedge along the bisector of main and branch tangents
        fm = main.frame(l.frog_main)
        fb = br.frame(l.frog_branch)
        t_bis = unit(add(fm.tangent, fb.tangent))
        up = fm.up
        lat = unit(cross(up, t_bis))
        sections = []
        n = 6
        for i in range(n + 1):
            t = -0.5 * fl + fl * i / n
            # narrow (nose) towards the toe
            frac = (t * d + 0.5 * fl) / fl  # 0 at nose (toe side), 1 at heel
            w = 0.04 + frac * (0.36 - 0.04)
            c = add(l.frog_point, scale(t_bis, t))
            sec = []
            for pu, pv in ((-0.5 * w, -self.rail_height), (0.5 * w, -self.rail_height), (0.5 * w, 0.0), (-0.5 * w, 0.0)):
                sec.append(add(add(c, scale(lat, pu)), scale(up, pv)))
            sections.append(sec)
        self._new("FROG", "%s-KORS" % tid, SweepGeom(sections), fmt, spatial_parent=part.object_id,
                  railway_part_id=part.object_id, alignment_id=self.al_cfg[l.main_key]["id"],
                  station_from=l.frog_main - 0.5 * fl, station_to=l.frog_main + 0.5 * fl,
                  attributes={"FrogAngleDeg": round(math.degrees(l.frog_angle), 4),
                              "FrogRatio": round(1.0 / math.tan(l.frog_angle), 2),
                              "BranchStation": round(l.frog_branch, 4), "Turnout": tid},
                  groups=[part.object_id, tid])

        # traction switching assembly: point machine on the far (non-branch) side + drive rod
        pm = p["point_machine"]
        s_pm = toe + d * 0.6
        f = main.frame(s_pm)
        far_sign = math.copysign(1, u_far)
        u_pm = u_far + far_sign * (float(pm["lateral_clearance"]) + 0.5 * float(pm["width"]))
        base = f.point(u_pm, self.v_sleeper_top)
        machine = BoxGeom(base, f.tangent, f.lateral, float(pm["length"]), float(pm["width"]), float(pm["height"]))
        u_rod0 = u_far + far_sign * float(pm["lateral_clearance"])
        u_rod1 = u_near
        rod_len = abs(u_rod0 - u_rod1)
        rod_base = f.point(0.5 * (u_rod0 + u_rod1), -0.12)
        rod = BoxGeom(rod_base, f.tangent, f.lateral, float(pm["drive_rod_width"]), rod_len, float(pm["drive_rod_height"]))
        self._new("SWITCH_ASSEMBLY", "%s-OMLAGG" % tid, MultiGeom([machine, rod]), fmt,
                  spatial_parent=part.object_id, railway_part_id=part.object_id,
                  alignment_id=self.al_cfg[l.main_key]["id"], station_from=s_pm, station_to=s_pm,
                  psets={"Pset_ElementAssemblyTypeTractionSwitchingAssembly": {
                      "RatedVoltage": float(pm["rated_voltage"]), "NominalPower": float(pm["nominal_power"])}},
                  attributes={"Turnout": tid, "ToeStation": round(toe, 4)},
                  groups=[part.object_id, tid])

    # ------------------------------------------------------------------ ballast
    def _other_track_offset(self, key: str, s: float) -> Optional[float]:
        tr = self.tracks[key]
        h = tr.horizontal.evaluate(s)
        best = None
        for ok, ot in self.tracks.items():
            if ok == key or self.al_cfg[ok].get("role") != "main":
                continue
            so, _ = ot.horizontal.project(h.x, h.y, sta_hint=self._hint.get((key, ok), None))
            if so <= ot.sta_start + 1e-6 or so >= ot.sta_end - 1e-6:
                continue
            self._hint[(key, ok)] = so
            ho = ot.horizontal.evaluate(so)
            nx, ny = h.left_normal
            o = (ho.x - h.x) * nx + (ho.y - h.y) * ny
            if best is None or abs(o) < abs(best):
                best = o
        return best

    def _ballast(self, parts: List[RailwayPartDef], sleepers_by_part: Dict[str, List[Component]]) -> None:
        bc = self.m["ballast"]
        shoulder = float(bc["shoulder_width"])
        below = float(bc["thickness_below_sleeper"])
        slope = float(bc["side_slope"])
        split_dist = float(bc["double_track_split_distance"])
        v_top = self.v_sleeper_top
        v_bot = v_top - self.sl_h - below
        thickness = v_top - v_bot
        half_top = 0.5 * self.sl_len + shoulder
        half_bot = half_top + thickness * slope
        self._hint: Dict[Tuple[str, str], float] = {}
        all_outline_pts: List[Vec3] = []
        self.part_footprints: Dict[str, List[Vec3]] = {}
        for p in parts:
            tr = self.tracks[p.track]
            stas = self._sampling(tr, p.station_from, p.station_to)
            sections = []
            widths = []
            left_edge, right_edge = [], []
            for s in stas:
                o = self._other_track_offset(p.track, s)
                ul_t, ul_b, ur_t, ur_b = half_top, half_bot, -half_top, -half_bot
                if o is not None and abs(o) < split_dist:
                    if o > 0:
                        ul_t = ul_b = 0.5 * o
                    else:
                        ur_t = ur_b = 0.5 * o
                f = tr.frame(s)
                sec = [f.point(ur_b, v_bot), f.point(ul_b, v_bot), f.point(ul_t, v_top), f.point(ur_t, v_top)]
                sections.append(sec)
                widths.append(ul_t - ur_t)
                left_edge.append(f.point(max(ul_t, ul_b), v_top))
                right_edge.append(f.point(min(ur_t, ur_b), v_top))
            geom = SweepGeom(sections)
            gross, mesh = self._mesh_quantities(geom)
            # net volume: subtract the part of every sleeper that lies inside this ballast body
            sleeper_vol = 0.0
            for sc in sleepers_by_part.get(p.object_id, []) + self._foreign_sleepers(p, sleepers_by_part):
                sleeper_vol += self._sleeper_share(sc.geometry, p, tr)
            net = gross - sleeper_vol
            length = p.station_to - p.station_from
            width = sum(widths) / len(widths)
            density = float(bc["density"])
            footprint = left_edge + list(reversed(right_edge))
            self.part_footprints[p.object_id] = footprint
            all_outline_pts.extend(footprint)
            self._new("BALLAST", "%s-BALLAST" % p.object_id, geom, {"part": p.name},
                      spatial_parent=p.object_id, railway_part_id=p.object_id, alignment_id=self.al_cfg[p.track]["id"],
                      station_from=p.station_from, station_to=p.station_to,
                      qtos={"Qto_CourseBaseQuantities": {
                          "Length": round(length, 4), "Width": round(width, 4), "Thickness": round(thickness, 4),
                          "GrossVolume": round(gross, 4), "Volume": round(net, 4), "Weight": round(net * density, 2)}},
                      psets={"Pset_CourseCommon": {"NominalLength": round(length, 4), "NominalWidth": round(width, 4),
                                                   "NominalThickness": round(thickness, 4)}},
                      attributes={"Material": bc["material"], "Density": density,
                                  "TopWidthNominal": round(2 * half_top, 4), "BottomWidthNominal": round(2 * half_bot, 4),
                                  "SideSlope": slope, "SleeperVolumeDeducted": round(sleeper_vol, 4),
                                  "MeshClosed": mesh.is_closed()},
                      groups=[p.object_id])
        hull = convex_hull_xy(all_outline_pts)
        self.site_area = abs(sum(abs(polygon_area_2d([(q[0], q[1]) for q in fp]))
                                 for fp in self.part_footprints.values()))
        self.hull = hull

    def _foreign_sleepers(self, part: RailwayPartDef, by_part: Dict[str, List[Component]]) -> List[Component]:
        """Sleepers of other parts that lie over this part's ballast (crossover common sleepers)."""
        out = []
        for pid, lst in by_part.items():
            if pid == part.object_id:
                continue
            for sc in lst:
                if sc.category == "SLEEPER_TURNOUT":
                    out.append(sc)
        return out

    def _sleeper_share(self, box: BoxGeom, part: RailwayPartDef, tr: TrackGeometry) -> float:
        """Volume of ``box`` lying laterally inside the ballast of ``part``
        (between the mid line to the other track and the outer edge)."""
        c = add(box.base_center, scale(box.z_axis, 0.5 * box.size_z))
        h_s, o_c = tr.horizontal.project(c[0], c[1], sta_hint=0.5 * (part.station_from + part.station_to))
        if not (part.station_from - 1e-6 <= h_s <= part.station_to + 1e-6):
            return 0.0
        h = tr.horizontal.evaluate(h_s)
        nx, ny = h.left_normal
        # lateral extent of the sleeper in this track's frame
        e1 = add(c, scale(box.y_axis, 0.5 * box.size_y))
        e2 = add(c, scale(box.y_axis, -0.5 * box.size_y))
        u1 = (e1[0] - h.x) * nx + (e1[1] - h.y) * ny
        u2 = (e2[0] - h.x) * nx + (e2[1] - h.y) * ny
        lo, hi = min(u1, u2), max(u1, u2)
        o = self._other_track_offset(part.track, h_s)
        bl, br_ = 1e9, -1e9
        if o is not None and abs(o) < float(self.m["ballast"]["double_track_split_distance"]):
            if o > 0:
                bl = 0.5 * o
            else:
                br_ = 0.5 * o
        inside = max(0.0, min(hi, bl) - max(lo, br_))
        return box.volume * inside / (hi - lo)

    # ------------------------------------------------------------------ spatial
    def _finalise_spatial(self, parts: List[RailwayPartDef]) -> None:
        z = self.ref_point[2]
        hull3 = [(x, y, z) for x, y in self.hull]
        area = self.site_area
        gpa = self.m["site"].get("gross_planned_area", "auto")
        if gpa != "auto":
            area = float(gpa)
        for c in self.components:
            if c.category in ("SPATIAL_SITE", "SPATIAL_RAILWAY", "SPATIAL_ZONE"):
                c.geometry = ShapeGeom(hull3)
            if c.category == "SPATIAL_SITE":
                c.psets["Pset_SpaceCommon"] = {"GrossPlannedArea": round(area, 2)}
            if c.category.startswith("SPATIAL_RAILWAYPART"):
                c.geometry = ShapeGeom(self.part_footprints[c.object_id])
        self.report["site_gross_planned_area_m2"] = round(area, 2)


def build_design_model(cfg: Config) -> DesignModel:
    return RailwayModelBuilder(cfg).build()
