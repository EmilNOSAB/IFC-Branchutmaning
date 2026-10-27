"""LandXML 1.1 reader for the Branschutmaningen 2026 track geometry.

Pure Python (standard library only) so that it runs both in a normal CPython
and inside MicroStation's embedded Python.

Coordinate order
----------------
The LandXML file stores points as "Northing Easting Elevation" (the LandXML
default). Example from the file: ``6617370.644571 132866.057940 0.000000``
is N=6617370.64, E=132866.06 in SWEREF 99 18 00.  All objects returned by this
module use **x = Easting, y = Northing** so that they can be used directly as
right-handed model coordinates (x east, y north, z up).

Directions
----------
``dir``/``dirStart``/``dirEnd`` in this file are azimuths in radians measured
from north towards east (clockwise).  This was verified against the start and
end points of every Line element (see tests/test_landxml.py).  ``rot="cw"``
means the curve turns clockwise, i.e. to the right, and the azimuth increases.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional

LANDXML_NS = "http://www.landxml.org/schema/LandXML-1.1"


def _tag(name: str) -> str:
    return "{%s}%s" % (LANDXML_NS, name)


def _floats(text: str) -> List[float]:
    return [float(v) for v in text.split()]


def _point(el: Optional[ET.Element]) -> Optional["XY"]:
    if el is None or el.text is None or not el.text.strip():
        return None
    vals = _floats(el.text)
    # LandXML order: northing, easting[, elevation]
    return XY(x=vals[1], y=vals[0])


def _opt_float(el: ET.Element, attr: str) -> Optional[float]:
    v = el.get(attr)
    if v is None or v == "":
        return None
    if v.upper() == "INF":
        return math.inf
    return float(v)


@dataclass(frozen=True)
class XY:
    x: float  # easting
    y: float  # northing

    def dist(self, other: "XY") -> float:
        return math.hypot(other.x - self.x, other.y - self.y)


@dataclass
class HorizontalElement:
    """One horizontal geometry element exactly as stored in LandXML."""

    kind: str  # "Line" | "Curve" | "Spiral"
    sta_start: float
    length: float
    start: XY
    end: XY
    dir_start: float  # azimuth (rad, from north, clockwise)
    dir_end: float
    rot: Optional[str] = None  # "cw" | "ccw" for Curve/Spiral
    radius: Optional[float] = None  # Curve
    radius_start: Optional[float] = None  # Spiral (inf = straight)
    radius_end: Optional[float] = None  # Spiral
    center: Optional[XY] = None  # Curve
    pi: Optional[XY] = None  # Spiral
    spi_type: Optional[str] = None
    start_code: Optional[str] = None
    end_code: Optional[str] = None


@dataclass
class ProfilePoint:
    """A vertical PVI. ``curve_length``/``radius`` are set for CircCurve/ParaCurve."""

    station: float
    elevation: float
    kind: str = "PVI"  # PVI | CircCurve | ParaCurve
    curve_length: float = 0.0
    radius: Optional[float] = None


@dataclass
class CantStation:
    station: float
    applied_cant_mm: float
    curvature: Optional[str] = None  # cw | ccw
    transition_type: Optional[str] = None
    equilibrium_cant_mm: Optional[float] = None
    cant_deficiency_mm: Optional[float] = None
    speed_kmh: Optional[float] = None


@dataclass
class Cant:
    name: str
    gauge: float  # reference distance between rail contact points (m)
    rotation_point: str
    stations: List[CantStation] = field(default_factory=list)


@dataclass
class Alignment:
    name: str
    length: float
    sta_start: float
    guid: Optional[str]
    description: Optional[str]
    elements: List[HorizontalElement]
    profile: List[ProfilePoint]
    profile_name: Optional[str]
    cant: Optional[Cant]

    @property
    def sta_end(self) -> float:
        return self.sta_start + self.length


@dataclass
class LandXmlDocument:
    path: str
    project_name: Optional[str]
    linear_unit: Optional[str]
    grid_scale_factor: Optional[float]
    application: Optional[str]
    alignments: List[Alignment]

    def alignment(self, name: str) -> Alignment:
        for a in self.alignments:
            if a.name == name:
                return a
        raise KeyError("Alignment %r not found. Available: %s" % (name, [a.name for a in self.alignments]))


def _read_horizontal(coord_geom: ET.Element) -> List[HorizontalElement]:
    elements: List[HorizontalElement] = []
    for child in coord_geom:
        kind = child.tag.split("}")[-1]
        if kind not in ("Line", "Curve", "Spiral"):
            continue
        start_el = child.find(_tag("Start"))
        end_el = child.find(_tag("End"))
        start = _point(start_el)
        end = _point(end_el)
        length = float(child.get("length"))
        sta = float(child.get("staStart"))
        if kind == "Line":
            d = float(child.get("dir")) if child.get("dir") else math.atan2(end.x - start.x, end.y - start.y)
            el = HorizontalElement(kind, sta, length, start, end, d, d)
        elif kind == "Curve":
            el = HorizontalElement(
                kind, sta, length, start, end,
                float(child.get("dirStart")), float(child.get("dirEnd")),
                rot=child.get("rot"), radius=float(child.get("radius")),
                center=_point(child.find(_tag("Center"))),
            )
        else:
            el = HorizontalElement(
                kind, sta, length, start, end,
                float(child.get("dirStart")), float(child.get("dirEnd")),
                rot=child.get("rot"),
                radius_start=_opt_float(child, "radiusStart"),
                radius_end=_opt_float(child, "radiusEnd"),
                pi=_point(child.find(_tag("PI"))),
                spi_type=child.get("spiType"),
            )
        el.start_code = start_el.get("code") if start_el is not None else None
        el.end_code = end_el.get("code") if end_el is not None else None
        elements.append(el)
    return elements


def _read_profile(profile: Optional[ET.Element]):
    if profile is None:
        return [], None
    prof_align = profile.find(_tag("ProfAlign"))
    if prof_align is None:
        return [], None
    pts: List[ProfilePoint] = []
    for child in prof_align:
        kind = child.tag.split("}")[-1]
        if kind not in ("PVI", "CircCurve", "ParaCurve"):
            continue
        sta, elev = _floats(child.text)[:2]
        if kind == "PVI":
            pts.append(ProfilePoint(sta, elev))
        else:
            pts.append(ProfilePoint(
                sta, elev, kind=kind,
                curve_length=float(child.get("length", "0")),
                radius=_opt_float(child, "radius"),
            ))
    return pts, prof_align.get("name")


def _read_cant(cant_el: Optional[ET.Element]) -> Optional[Cant]:
    if cant_el is None:
        return None
    cant = Cant(
        name=cant_el.get("name", ""),
        gauge=float(cant_el.get("gauge", "1.5")),
        rotation_point=cant_el.get("rotationPoint", "insideRail"),
    )
    for cs in cant_el.findall(_tag("CantStation")):
        cant.stations.append(CantStation(
            station=float(cs.get("station")),
            applied_cant_mm=float(cs.get("appliedCant", "0")),
            curvature=cs.get("curvature"),
            transition_type=cs.get("transitionType"),
            equilibrium_cant_mm=_opt_float(cs, "equilibriumCant"),
            cant_deficiency_mm=_opt_float(cs, "cantDeficiency"),
            speed_kmh=_opt_float(cs, "speed"),
        ))
    return cant


def read_landxml(path: str) -> LandXmlDocument:
    tree = ET.parse(path)
    root = tree.getroot()
    project = root.find(_tag("Project"))
    gsf = None
    if project is not None:
        for prop in project.iter(_tag("Property")):
            if prop.get("label") == "GridScaleFactor":
                gsf = float(prop.get("value"))
    metric = root.find("%s/%s" % (_tag("Units"), _tag("Metric")))
    app = root.find(_tag("Application"))
    alignments: List[Alignment] = []
    for al in root.iter(_tag("Alignment")):
        guid = None
        for prop in al.findall("%s/%s" % (_tag("Feature"), _tag("Property"))):
            if prop.get("label") == "guid":
                guid = prop.get("value")
        coord_geom = al.find(_tag("CoordGeom"))
        profile, profile_name = _read_profile(al.find(_tag("Profile")))
        alignments.append(Alignment(
            name=al.get("name"),
            length=float(al.get("length")),
            sta_start=float(al.get("staStart")),
            guid=guid,
            description=al.get("desc"),
            elements=_read_horizontal(coord_geom) if coord_geom is not None else [],
            profile=profile,
            profile_name=profile_name,
            cant=_read_cant(al.find(_tag("Cant"))),
        ))
    return LandXmlDocument(
        path=path,
        project_name=project.get("name") if project is not None else None,
        linear_unit=metric.get("linearUnit") if metric is not None else None,
        grid_scale_factor=gsf,
        application=(app.get("name") + " " + app.get("version", "")) if app is not None else None,
        alignments=alignments,
    )
