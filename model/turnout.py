"""Turnout (spårväxel) layout generator.

A turnout is defined by a main track, a branch alignment and which end of the
branch lies on the main track (``branch_end``).  Everything else is derived
from the actual geometry:

* switch toe (tungspets): the branch end point projected on the main track
* direction ``d`` from the toe towards the frog (+1 = increasing main station)
* branch side ``sb`` in the main track's frame (+1 = left, -1 = right)
* frog (korsning): intersection of the branch rail on the side away from the
  branch (``far`` rail) with the main rail on the branch side (``near`` rail),
  solved numerically on the 3D rail lines
* blades are shortened automatically if the frog lies closer to the toe than
  blade length + half frog length + 1 m closure (reported as a warning)

Rail naming (seen from the toe towards the frog):
  main near rail   - main rail on the branch side (straight blade, then through
                     rail interrupted by the frog)
  main far rail    - straight stock rail, then through rail; carries the main check rail
  branch far rail  - curved blade, closure rail, interrupted by the frog
  branch near rail - continuation of the bent stock rail; carries the branch check rail
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from geometry.track import TrackGeometry


@dataclass
class TurnoutLayout:
    turnout_id: str
    name: str
    main_key: str
    branch_key: str
    toe_main: float  # main station of switch toe
    toe_branch: float  # branch station of switch toe
    d: int  # +1: frog at higher main station than toe
    sb: int  # branch side in main frame: +1 left, -1 right
    frog_main: float
    frog_branch: float
    frog_point: Tuple[float, float, float]
    frog_angle: float  # rad, between main and branch tangents at the frog
    blade_length: float
    params: Dict
    warnings: List[str] = field(default_factory=list)

    @property
    def u_near(self) -> float:
        return self.sb * 0.5 * self.params["_rc"]

    @property
    def u_far(self) -> float:
        return -self.sb * 0.5 * self.params["_rc"]


def _branch_toe(branch: TrackGeometry, branch_end: str) -> Tuple[float, int]:
    if branch_end == "start":
        return branch.sta_start, +1
    if branch_end == "end":
        return branch.sta_end, -1
    raise ValueError("branch_end must be 'start' or 'end', got %r" % branch_end)


def compute_layout(turnout_cfg: Dict, tracks: Dict[str, TrackGeometry], rail_centre_distance: float) -> TurnoutLayout:
    main = tracks[turnout_cfg["main_track"]]
    branch = tracks[turnout_cfg["branch"]]
    toe_b, d = _branch_toe(branch, turnout_cfg["branch_end"])
    hb = branch.horizontal.evaluate(toe_b)
    toe_m, off = main.horizontal.project(hb.x, hb.y)
    warnings: List[str] = []
    if abs(off) > 0.01:
        warnings.append("Branch end is %.3f m off the main track centre line" % off)
    # direction consistency: branch forward must be roughly main forward
    hm = main.horizontal.evaluate(toe_m)
    dang = (hb.azimuth - hm.azimuth + math.pi) % (2 * math.pi) - math.pi
    if abs(dang) > math.radians(30):
        raise ValueError("Branch %s is not running in the main track direction at the toe" % turnout_cfg["branch"])
    # branch side: sample 15 m from the toe towards the frog
    probe = branch.horizontal.evaluate(toe_b + d * min(15.0, 0.5 * (branch.sta_end - branch.sta_start)))
    _, probe_off = main.horizontal.project(probe.x, probe.y, sta_hint=toe_m + d * 15.0)
    sb = 1 if probe_off > 0 else -1
    rc = rail_centre_distance
    u_near_main = sb * 0.5 * rc
    u_far_branch = -sb * 0.5 * rc

    def miss(vb: float) -> float:
        p = branch.frame(vb).point(u_far_branch, 0.0)
        _, o = main.horizontal.project(p[0], p[1], sta_hint=toe_m + d * abs(vb - toe_b))
        return sb * (o - u_near_main)  # < 0 before crossing, > 0 after

    # scan from the toe towards the frog
    step = 0.5
    vb = toe_b + d * 1.0
    prev = miss(vb)
    found = None
    limit = branch.sta_end - branch.sta_start
    travelled = 1.0
    while travelled < limit:
        nxt = vb + d * step
        cur = miss(nxt)
        if prev < 0 <= cur:
            a, b = vb, nxt
            for _ in range(60):
                m = 0.5 * (a + b)
                if miss(m) < 0:
                    a = m
                else:
                    b = m
            found = 0.5 * (a + b)
            break
        vb, prev = nxt, cur
        travelled += step
    if found is None:
        raise ValueError("No frog found for turnout %s: branch rail never crosses the main rail" % turnout_cfg["id"])
    frog_b = found
    fp = branch.frame(frog_b).point(u_far_branch, 0.0)
    frog_m, _ = main.horizontal.project(fp[0], fp[1], sta_hint=toe_m + d * abs(frog_b - toe_b))
    ang = abs((branch.horizontal.evaluate(frog_b).azimuth - main.horizontal.evaluate(frog_m).azimuth + math.pi)
              % (2 * math.pi) - math.pi)
    blade = float(turnout_cfg["blade_length"])
    max_blade = abs(frog_b - toe_b) - 0.5 * float(turnout_cfg["frog_length"]) - 1.0
    if blade > max_blade:
        warnings.append("Blade length reduced from %.2f m to %.2f m: frog lies %.2f m from the toe"
                        % (blade, max_blade, abs(frog_b - toe_b)))
        blade = max_blade
    params = dict(turnout_cfg)
    params["_rc"] = rc
    return TurnoutLayout(
        turnout_id=turnout_cfg["id"], name=turnout_cfg.get("name", turnout_cfg["id"]),
        main_key=turnout_cfg["main_track"], branch_key=turnout_cfg["branch"],
        toe_main=toe_m, toe_branch=toe_b, d=d, sb=sb,
        frog_main=frog_m, frog_branch=frog_b, frog_point=fp, frog_angle=ang,
        blade_length=blade, params=params, warnings=warnings,
    )
