"""
utils/gis_utils.py

Bhunaksha returns geometry in UTM metres. Maharashtra spans two UTM zones,
split at ~78 deg E: zone 43N (EPSG:32643) west/central, zone 44N (EPSG:32644)
east. We auto-pick the zone whose result falls inside a Maharashtra outline,
and break any remaining tie using the district CODE.
"""

import sys
from shapely import wkt
from shapely.geometry import Polygon, Point
from pyproj import Transformer

# Coarse Maharashtra outline (lon, lat) — enough to reject Gujarat / sea points.
_MH = Polygon([
    (72.7, 20.1), (73.9, 20.8), (74.5, 21.5), (75.0, 21.6), (76.5, 21.4),
    (78.0, 21.8), (79.5, 21.8), (80.2, 21.6), (80.9, 20.8), (80.5, 19.8),
    (80.2, 19.3), (79.8, 18.7), (78.3, 18.4), (77.0, 17.7), (76.0, 17.0),
    (75.0, 16.2), (74.2, 15.9), (73.7, 15.8), (73.3, 16.5), (73.0, 17.5),
    (72.7, 18.5), (72.7, 19.5),
])

# District CODES (from locations.csv, 2-digit) that are UTM zone 44N (eastern
# Vidarbha). Used as a tie-breaker when the polygon can't decide.
# Confirmed: Wardha 08, Bhandara 10, Gondiya 11, Gadchiroli 12,
#            Chandrapur 13, Yavatmal 14.  Nagpur assumed 09 (please confirm).
EAST_ZONE_DISTRICT_CODES = {"08", "09", "10", "11", "12", "13", "14"}

# Name fallback (lower-cased, prefix-stripped) in case code isn't passed.
EAST_ZONE_DISTRICTS = {
    "nagpur", "wardha", "chandrapur", "gadchiroli",
    "bhandara", "gondia", "gondiya", "yavatmal", "नागपूर", "चंद्रपूर",
    "गडचिरोली", "भंडारा", "गोंदिया", "यवतमाळ", "वर्धा",
}

AMBIGUOUS_DEFAULT_EPSG = 32643
DISTRICT_OFFSETS = {}  # optional {code: (dx_m, dy_m)} calibration

_TRANSFORMERS = {
    32643: Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True),
    32644: Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True),
}


def _in_mh(lon, lat):
    return _MH.contains(Point(lon, lat))


def _norm(name):
    if not name:
        return ""
    # drop a leading numeric code like "09 नागपूर" -> "नागपूर"
    parts = str(name).strip().split(None, 1)
    if len(parts) == 2 and parts[0].isdigit():
        name = parts[1]
    return name.strip().lower()


def _is_east(district=None, district_code=None):
    if district_code is not None and str(district_code).zfill(2) in EAST_ZONE_DISTRICT_CODES:
        return True
    return _norm(district) in EAST_ZONE_DISTRICTS


def _looks_like_latlon(geom):
    minx, miny, maxx, maxy = geom.bounds
    return -180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90


def _resolve_epsg(geom, district=None, district_code=None):
    if _looks_like_latlon(geom):
        return None
    c = geom.centroid
    valid = [epsg for epsg, tr in _TRANSFORMERS.items() if _in_mh(*tr.transform(c.x, c.y))]
    if len(valid) == 1:
        return valid[0]
    if _is_east(district, district_code):
        return 32644
    if valid:
        return AMBIGUOUS_DEFAULT_EPSG if AMBIGUOUS_DEFAULT_EPSG in valid else valid[0]
    sys.stderr.write(f"[gis_utils] no zone in MH (district={district!r}/{district_code!r}); default 44N.\n")
    return 32644


def _to_latlon(epsg, x, y, district_code=None):
    if epsg is None:
        return y, x
    if district_code is not None:
        dx, dy = DISTRICT_OFFSETS.get(str(district_code).zfill(2), (0.0, 0.0))
        x, y = x + dx, y + dy
    lon, lat = _TRANSFORMERS[epsg].transform(x, y)
    return lat, lon


def _iter_polygons(geom):
    return list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]


def get_polygons_latlon(wkt_polygon, district=None, district_code=None):
    geom = wkt.loads(wkt_polygon)
    epsg = _resolve_epsg(geom, district, district_code)
    return [
        [list(_to_latlon(epsg, x, y, district_code)) for x, y in part.exterior.coords]
        for part in _iter_polygons(geom)
    ]


def get_point_latlon(wkt_polygon, district=None, district_code=None):
    geom = wkt.loads(wkt_polygon)
    epsg = _resolve_epsg(geom, district, district_code)
    pt = geom.representative_point()
    return _to_latlon(epsg, pt.x, pt.y, district_code)


def build_gis_code(category, district_code, taluka_code, village_code):
    prefix = "RVM" if category.upper() == "R" else "UCM"
    return prefix + str(district_code).zfill(2) + str(taluka_code).zfill(2) + str(village_code)
