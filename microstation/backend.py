"""Backend interface for writing the design model to a DGN.

``MicroStationBackend`` (microstation/msapi.py) performs the real MicroStation
API calls and only works inside MicroStation.  ``RecordingBackend`` implements
the same interface in plain Python: it records levels, item types, elements,
item values and named groups.  It is used for ``--dry-run`` and by the test
suite to exercise the complete build orchestration without MicroStation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


class BackendError(RuntimeError):
    pass


@dataclass
class ElementRecord:
    element_id: int
    object_id: str
    kind: str  # box | mesh | ruled_sweep | linestring | shape | multi
    level: str
    color: int
    weight: int
    items: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    geometry_summary: Dict[str, Any] = field(default_factory=dict)


class DgnBackend:
    """Interface.  All coordinates passed in are metres in SWEREF 99 18 00 /
    RH 2000; the backend converts to UORs."""

    name = "abstract"

    def environment(self) -> Dict[str, Any]:
        raise NotImplementedError

    def check_model(self) -> Dict[str, Any]:
        raise NotImplementedError

    def set_coordinate_system(self, cs_cfg: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def ensure_levels(self, levels: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
        raise NotImplementedError

    def ensure_item_types(self, library: str, spec: Dict[str, Sequence[Tuple[str, str]]]) -> Dict[str, Any]:
        raise NotImplementedError

    def find_bentley_ifc_classification(self, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def purge_generated(self, library: str, marker_item_type: str) -> int:
        raise NotImplementedError

    def begin_bulk(self) -> None:
        pass

    def end_bulk(self) -> None:
        pass

    def add_box(self, base_center, x_axis, y_axis, size_x, size_y, size_z, level_id: int, color: int, weight: int):
        raise NotImplementedError

    def add_mesh(self, vertices, faces, level_id: int, color: int, weight: int):
        raise NotImplementedError

    def add_ruled_sweep(self, sections, level_id: int, color: int, weight: int):
        raise NotImplementedError

    def add_linestring(self, points, level_id: int, color: int, weight: int):
        raise NotImplementedError

    def add_shape(self, points, level_id: int, color: int, weight: int):
        raise NotImplementedError

    def attach_items(self, element, library: str, items: List[Tuple[str, Dict[str, Any]]],
                     bentley_ifc: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    def element_id(self, element) -> int:
        raise NotImplementedError

    def create_named_group(self, name: str, description: str, element_ids: List[int]) -> None:
        raise NotImplementedError

    def save(self) -> None:
        raise NotImplementedError

    def scan_generated(self, library: str, marker_item_type: str) -> List[Dict[str, Any]]:
        """Read back every generated element with its item values (for validate_dgn)."""
        raise NotImplementedError


class RecordingBackend(DgnBackend):
    """In-memory stand-in used for dry runs and tests (no DGN is written)."""

    name = "recording (dry run - no DGN written)"

    def __init__(self):
        self.levels: Dict[str, Dict[str, Any]] = {}
        self.item_types: Dict[str, List[Tuple[str, str]]] = {}
        self.elements: List[ElementRecord] = []
        self.groups: Dict[str, List[int]] = {}
        self._next_id = 1000
        self._pending: Optional[ElementRecord] = None
        self.saved = False

    def environment(self) -> Dict[str, Any]:
        return {"backend": self.name, "microstation": None}

    def check_model(self) -> Dict[str, Any]:
        return {"is3d": True, "master_unit": "m (assumed in dry run)", "uor_per_meter": None, "global_origin": None}

    def set_coordinate_system(self, cs_cfg):
        return {"status": "skipped (dry run)", "requested": cs_cfg.get("bentley_gcs_keynames")}

    def ensure_levels(self, levels):
        out = {}
        for i, (name, spec) in enumerate(levels.items(), start=1):
            self.levels.setdefault(name, dict(spec, id=100 + i))
            out[name] = self.levels[name]["id"]
        return out

    def ensure_item_types(self, library, spec):
        for it, props in spec.items():
            self.item_types[it] = list(props)
        return {"library": library, "item_types": sorted(spec)}

    def find_bentley_ifc_classification(self, cfg):
        return None

    def purge_generated(self, library, marker_item_type):
        n = len(self.elements)
        self.elements = []
        self.groups = {}
        return n

    def _add(self, kind: str, level_id: int, color: int, weight: int, summary: Dict[str, Any]) -> ElementRecord:
        self._next_id += 1
        level = next((k for k, v in self.levels.items() if v["id"] == level_id), str(level_id))
        rec = ElementRecord(self._next_id, "", kind, level, color, weight, geometry_summary=summary)
        self.elements.append(rec)
        return rec

    def add_box(self, base_center, x_axis, y_axis, size_x, size_y, size_z, level_id, color, weight):
        return self._add("box", level_id, color, weight, {"size": (size_x, size_y, size_z), "base": base_center})

    def add_mesh(self, vertices, faces, level_id, color, weight):
        return self._add("mesh", level_id, color, weight, {"vertices": len(vertices), "faces": len(faces)})

    def add_ruled_sweep(self, sections, level_id, color, weight):
        return self._add("ruled_sweep", level_id, color, weight, {"sections": len(sections)})

    def add_linestring(self, points, level_id, color, weight):
        return self._add("linestring", level_id, color, weight, {"points": len(points)})

    def add_shape(self, points, level_id, color, weight):
        return self._add("shape", level_id, color, weight, {"points": len(points)})

    def attach_items(self, element, library, items, bentley_ifc=None):
        for it, values in items:
            if it not in self.item_types:
                raise BackendError("Item type %s not defined" % it)
            names = {p for p, _ in self.item_types[it]}
            unknown = set(values) - names
            if unknown:
                raise BackendError("Item type %s has no properties %s" % (it, sorted(unknown)))
            element.items[it] = dict(values)
        if bentley_ifc:
            element.items["IFC Classification"] = dict(bentley_ifc)
        oid = element.items.get("BU26_Object", {}).get("BU26_ObjectId")
        if oid:
            element.object_id = oid

    def element_id(self, element):
        return element.element_id

    def create_named_group(self, name, description, element_ids):
        self.groups[name] = list(element_ids)

    def save(self):
        self.saved = True

    def scan_generated(self, library, marker_item_type, spec=None):
        out = []
        for e in self.elements:
            if marker_item_type in e.items:
                out.append({"element_id": e.element_id, "level": e.level, "kind": e.kind, "items": e.items,
                            "geometry": e.geometry_summary})
        return out
