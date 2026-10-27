"""Plan-view plot of the design model (no MicroStation needed).

Draws ballast tops, sleepers, rails, blades, check rails, frogs and point
machines in a local system along the track so that the turnout layout can be
checked before the DGN is built.

    python tools/plot_design_model.py --mode full --out docs/img/crossover_plan.png \
        --origin-track N --origin-station 7920 --from -15 --to 80
"""

from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import load_config  # noqa: E402
from model.geom import BoxGeom, MultiGeom, SweepGeom  # noqa: E402
from model.railway_model import RailwayModelBuilder  # noqa: E402

COLORS = {
    "BALLAST": "#e8dcc0", "SLEEPER": "#b0b0b0", "SLEEPER_TURNOUT": "#9a9a66", "RAIL_MAIN": "#000000",
    "RAIL_TURNOUT": "#333399", "RAIL_STOCK": "#cc6600", "RAIL_BLADE": "#ff0000", "RAIL_CHECK": "#00a000",
    "FROG": "#aa00aa", "SWITCH_ASSEMBLY": "#0088ff",
}
ORDER = list(COLORS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--origin-track", default="N")
    ap.add_argument("--origin-station", type=float, default=7920.0)
    ap.add_argument("--from", dest="x0", type=float, default=-15.0)
    ap.add_argument("--to", dest="x1", type=float, default=80.0)
    ap.add_argument("--ymin", type=float, default=-7.0)
    ap.add_argument("--ymax", type=float, default=3.0)
    args = ap.parse_args(argv)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    builder = RailwayModelBuilder(load_config(mode=args.mode))
    dm = builder.build()
    h = builder.tracks[args.origin_track].horizontal.evaluate(args.origin_station)
    sa, ca = math.sin(h.azimuth), math.cos(h.azimuth)

    def loc(p):
        dx, dy = p[0] - h.x, p[1] - h.y
        return (dx * sa + dy * ca, -dx * ca + dy * sa)

    fig, ax = plt.subplots(figsize=(18, 2 + 1.6 * (args.ymax - args.ymin)))
    for cat in ORDER:
        for c in dm.components:
            if c.category != cat or c.geometry is None:
                continue
            parts = c.geometry.parts if isinstance(c.geometry, MultiGeom) else [c.geometry]
            for g in parts:
                if isinstance(g, BoxGeom):
                    pts = [loc(p) for p in g.corners()[4:]]
                elif isinstance(g, SweepGeom):
                    if cat == "BALLAST":
                        pts = [loc(s[2]) for s in g.sections] + [loc(s[3]) for s in reversed(g.sections)]
                    else:
                        n = len(g.sections[0])
                        pts = [loc(s[0]) for s in g.sections] + [loc(s[n // 2]) for s in reversed(g.sections)]
                else:
                    continue
                if not any(args.x0 < p[0] < args.x1 for p in pts):
                    continue
                ax.add_patch(Polygon(pts, closed=True, fc=COLORS[cat], ec="#c0a070" if cat == "BALLAST" else COLORS[cat],
                                     lw=0.5, alpha=0.95))
    ax.set_xlim(args.x0, args.x1)
    ax.set_ylim(args.ymin, args.ymax)
    ax.set_aspect("equal")
    ax.grid(True, lw=0.3)
    ax.set_xlabel("m längs %s från station %.3f" % (args.origin_track, args.origin_station))
    ax.set_ylabel("m (vänster +)")
    ax.set_title("Designmodell, plan (%s-läge)" % builder.cfg.mode)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out, dpi=110, bbox_inches="tight")
    print("written", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
