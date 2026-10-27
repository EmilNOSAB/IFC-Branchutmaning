"""SWEREF 99 TM-family (Gauss-Krüger) projection on GRS 80.

Used to compute IfcSite.RefLatitude/RefLongitude for the model reference
point in SWEREF 99 18 00 (EPSG:3011): central meridian 18°00', scale 1.0,
false easting 150 000 m, false northing 0 m.  Formulas: Lantmäteriet,
"Gauss Konforma projektion (Transverse Mercator)" (Krüger series).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

GRS80_A = 6378137.0
GRS80_F = 1.0 / 298.257222101


@dataclass(frozen=True)
class TMProjection:
    central_meridian_deg: float
    scale: float
    false_northing: float
    false_easting: float
    a: float = GRS80_A
    f: float = GRS80_F

    def _consts(self):
        f = self.f
        e2 = f * (2.0 - f)
        n = f / (2.0 - f)
        a_roof = self.a / (1.0 + n) * (1.0 + n * n / 4.0 + n ** 4 / 64.0)
        return e2, n, a_roof

    def to_grid(self, lat_deg: float, lon_deg: float) -> Tuple[float, float]:
        """(lat, lon) degrees -> (northing, easting)."""
        e2, n, a_roof = self._consts()
        A = e2
        B = (5 * e2 ** 2 - e2 ** 3) / 6.0
        C = (104 * e2 ** 3 - 45 * e2 ** 4) / 120.0
        D = (1237 * e2 ** 4) / 1260.0
        b1 = n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16 + 41 * n ** 4 / 180
        b2 = 13 * n ** 2 / 48 - 3 * n ** 3 / 5 + 557 * n ** 4 / 1440
        b3 = 61 * n ** 3 / 240 - 103 * n ** 4 / 140
        b4 = 49561 * n ** 4 / 161280
        phi = math.radians(lat_deg)
        lam = math.radians(lon_deg)
        lam0 = math.radians(self.central_meridian_deg)
        s, c = math.sin(phi), math.cos(phi)
        phi_s = phi - s * c * (A + B * s ** 2 + C * s ** 4 + D * s ** 6)
        dl = lam - lam0
        xi = math.atan2(math.tan(phi_s), math.cos(dl))
        eta = math.atanh(math.cos(phi_s) * math.sin(dl))
        x = self.scale * a_roof * (xi + b1 * math.sin(2 * xi) * math.cosh(2 * eta) + b2 * math.sin(4 * xi) * math.cosh(4 * eta)
                                   + b3 * math.sin(6 * xi) * math.cosh(6 * eta) + b4 * math.sin(8 * xi) * math.cosh(8 * eta)) + self.false_northing
        y = self.scale * a_roof * (eta + b1 * math.cos(2 * xi) * math.sinh(2 * eta) + b2 * math.cos(4 * xi) * math.sinh(4 * eta)
                                   + b3 * math.cos(6 * xi) * math.sinh(6 * eta) + b4 * math.cos(8 * xi) * math.sinh(8 * eta)) + self.false_easting
        return x, y

    def to_geodetic(self, northing: float, easting: float) -> Tuple[float, float]:
        """(northing, easting) -> (lat, lon) degrees."""
        e2, n, a_roof = self._consts()
        d1 = n / 2 - 2 * n ** 2 / 3 + 37 * n ** 3 / 96 - n ** 4 / 360
        d2 = n ** 2 / 48 + n ** 3 / 15 - 437 * n ** 4 / 1440
        d3 = 17 * n ** 3 / 480 - 37 * n ** 4 / 840
        d4 = 4397 * n ** 4 / 161280
        A_s = e2 + e2 ** 2 + e2 ** 3 + e2 ** 4
        B_s = -(7 * e2 ** 2 + 17 * e2 ** 3 + 30 * e2 ** 4) / 6.0
        C_s = (224 * e2 ** 3 + 889 * e2 ** 4) / 120.0
        D_s = -(4279 * e2 ** 4) / 1260.0
        xi = (northing - self.false_northing) / (self.scale * a_roof)
        eta = (easting - self.false_easting) / (self.scale * a_roof)
        xi_p = (xi - d1 * math.sin(2 * xi) * math.cosh(2 * eta) - d2 * math.sin(4 * xi) * math.cosh(4 * eta)
                - d3 * math.sin(6 * xi) * math.cosh(6 * eta) - d4 * math.sin(8 * xi) * math.cosh(8 * eta))
        eta_p = (eta - d1 * math.cos(2 * xi) * math.sinh(2 * eta) - d2 * math.cos(4 * xi) * math.sinh(4 * eta)
                 - d3 * math.cos(6 * xi) * math.sinh(6 * eta) - d4 * math.cos(8 * xi) * math.sinh(8 * eta))
        phi_s = math.asin(math.sin(xi_p) / math.cosh(eta_p))
        dl = math.atan2(math.sinh(eta_p), math.cos(xi_p))
        s = math.sin(phi_s)
        phi = phi_s + s * math.cos(phi_s) * (A_s + B_s * s ** 2 + C_s * s ** 4 + D_s * s ** 6)
        return math.degrees(phi), self.central_meridian_deg + math.degrees(dl)


SWEREF99_1800 = TMProjection(central_meridian_deg=18.0, scale=1.0, false_northing=0.0, false_easting=150000.0)


def deg_to_dms(value: float) -> Tuple[int, int, int, int]:
    """Decimal degrees -> IfcCompoundPlaneAngleMeasure (deg, min, sec, millionths)."""
    sign = -1 if value < 0 else 1
    v = abs(value)
    d = int(v)
    m_full = (v - d) * 60.0
    m = int(m_full)
    s_full = (m_full - m) * 60.0
    s = int(s_full)
    micro = int(round((s_full - s) * 1e6))
    if micro >= 1000000:
        micro -= 1000000
        s += 1
    if s >= 60:
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        d += 1
    return (sign * d, sign * m, sign * s, sign * micro)
