"""Shared state of one build run and the generic component placement loop."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from model.components import Component

from .assign_metadata import attach
from .dgn_geometry import place


@dataclass
class BuildContext:
    cfg: Any
    backend: Any
    level_ids: Dict[str, int]
    library: str
    mode: str
    source_file: str
    bentley_ifc: Optional[Dict[str, Any]] = None
    log: Callable[[str], None] = print
    element_ids: Dict[str, int] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)
    timings: Dict[str, float] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    # IFC class/type values not offered by Bentley's pick lists -> {value: count}
    picklist_misses: Dict[str, int] = field(default_factory=dict)

    @property
    def version_value(self) -> str:
        return self.cfg.mapping["bentley_ifc_classification"].get("version_value", "IFC4X3_ADD2")

    def symbology(self, level: str):
        spec = self.cfg.levels["levels"][level]
        return int(spec.get("color", 0)), int(spec.get("weight", 0))


def place_components(ctx: BuildContext, components: List[Component], label: str) -> int:
    """Create a DGN element with Item Types for every component.  Errors on single
    components are collected (and reported) instead of aborting the run."""
    t0 = time.perf_counter()
    kind = ctx.cfg.model["dgn"].get("linear_solid_kind", "mesh")
    n = 0
    for comp in components:
        if comp.geometry is None:
            ctx.errors.append("%s has no geometry" % comp.object_id)
            continue
        color, weight = ctx.symbology(comp.level)
        try:
            el = place(ctx.backend, comp.geometry, ctx.level_ids[comp.level], color, weight, kind)
            bic = attach(ctx.backend, el, comp, ctx.library, ctx.mode, ctx.source_file, ctx.bentley_ifc,
                         ctx.version_value, ctx.cfg.mapping["bentley_ifc_classification"].get("apply_to_entities"))
            for miss in (bic or {}).get("unmatched", []):
                ctx.picklist_misses[miss] = ctx.picklist_misses.get(miss, 0) + 1
            ctx.element_ids[comp.object_id] = ctx.backend.element_id(el)
            ctx.counts[comp.category] = ctx.counts.get(comp.category, 0) + 1
            n += 1
        except Exception as e:  # keep going, report at the end
            ctx.errors.append("%s (%s): %s" % (comp.object_id, comp.category, e))
    dt = time.perf_counter() - t0
    ctx.timings[label] = ctx.timings.get(label, 0.0) + dt
    ctx.log("  %-28s %6d element  %7.2f s" % (label, n, dt))
    return n
