"""Design model objects: physical components and spatial/system objects.

A ``Component`` carries everything that ends up on one DGN element: geometry,
level, Item Type values (identity, IFC class, CoClass, property and quantity
sets) and its logical parent.  The same data is later used by the IFC
post-processing step and by the validators, so the DGN element id
(``object_id``) is the key that links DGN, IFC and validation reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

Classification = Tuple[str, str, str]  # (system, identification, name)


@dataclass
class Component:
    object_id: str
    category: str
    name: str
    description: str
    level: str
    ifc_entity: str
    predefined_type: Optional[str]
    geometry: Any
    spatial_parent: Optional[str] = None  # object_id of the RailwayPart / container
    spatial_relation: str = "contained"  # contained | aggregated | referenced | none
    railway_part_id: Optional[str] = None
    alignment_id: Optional[str] = None
    station_from: Optional[float] = None
    station_to: Optional[float] = None
    object_type: Optional[str] = None
    long_name: Optional[str] = None
    classifications: List[Classification] = field(default_factory=list)
    psets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    qtos: Dict[str, Dict[str, float]] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)  # extra info (side, position, turnout...)
    groups: List[str] = field(default_factory=list)  # named groups (DGN) the element belongs to

    @property
    def is_physical(self) -> bool:
        return not self.category.startswith(("SPATIAL_", "BUILT_SYSTEM", "ALIGNMENT"))


@dataclass
class RailwayPartDef:
    key: str
    object_id: str
    track: str  # alignment key of the main track
    predefined_type: str
    name: str
    long_name: str
    description: str
    station_from: float
    station_to: float
    turnout_id: Optional[str] = None


@dataclass
class DesignModel:
    components: List[Component]
    parts: List[RailwayPartDef]
    report: Dict[str, Any]

    def by_category(self) -> Dict[str, List[Component]]:
        out: Dict[str, List[Component]] = {}
        for c in self.components:
            out.setdefault(c.category, []).append(c)
        return out

    def get(self, object_id: str) -> Component:
        for c in self.components:
            if c.object_id == object_id:
                return c
        raise KeyError(object_id)
