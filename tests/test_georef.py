import math

from geometry.georef import SWEREF99_1800, deg_to_dms

# reference: pyproj 3.x, EPSG:3011 -> EPSG:4326 for the first NSpår point
REF_N, REF_E = 6617370.644571, 132866.057940
REF_LAT, REF_LON = 59.670212859663245, 17.695960302532857


def test_inverse_matches_reference():
    lat, lon = SWEREF99_1800.to_geodetic(REF_N, REF_E)
    assert abs(lat - REF_LAT) < 1e-9 and abs(lon - REF_LON) < 1e-9


def test_roundtrip():
    lat, lon = SWEREF99_1800.to_geodetic(REF_N, REF_E)
    n, e = SWEREF99_1800.to_grid(lat, lon)
    assert abs(n - REF_N) < 1e-4 and abs(e - REF_E) < 1e-4


def test_central_meridian():
    lat, lon = SWEREF99_1800.to_geodetic(6600000.0, 150000.0)
    assert math.isclose(lon, 18.0, abs_tol=1e-12)


def test_dms():
    d = deg_to_dms(59.670212859663245)
    assert d[0] == 59 and d[1] == 40 and d[2] == 12
