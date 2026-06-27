"""
utils/gis_utils.py

Bhunaksha returns geometry in UTM metres. Maharashtra spans two UTM zones,
split at 78 deg E: zone 43N (EPSG:32643) west/central, zone 44N (EPSG:32644)
eastern Vidarbha. This module auto-picks the right zone per plot.
"""

import sys
from shapely import wkt
from pyproj import Transformer

MH_BBOX = (72.5, 15.4, 81.0, 22.3)

EAST_ZONE_DISTRICTS = {
    "nagpur", "wardha", "chandrapur", "gadchiroli",
    "bhandara", "gondia", "gondiya", "yavatmal",
}

AMBIGUOUS_DEFAULT_EPSG = 32643

# Optional per-district nudge (metres) if a district is consistently offset
# vs satellite, e.g. {"wardha": (3.0, -2.0)}.
DISTRICT_OFFSETS = {}

_TRANSFORMERS = {
    32643: Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True),
    32644: Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True),
}


def _in_mh(lon, lat):
    lo_x, lo_y, hi_x, hi_y = MH_BBOX
    return lo_x <= lon <= hi_x and lo_y <= lat <= hi_y


def _looks_like_latlon(geom):
    minx, miny, maxx, maxy = geom.bounds
    return -180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90


def _resolve_epsg(geom, district=None):
    if _looks_like_latlon(geom):
        return None
    c = geom.centroid
    valid = [epsg for epsg, tr in _TRANSFORMERS.items() if _in_mh(*tr.transform(c.x, c.y))]
    if len(valid) == 1:
        return valid[0]
    if district and district.strip().lower() in EAST_ZONE_DISTRICTS:
        return 32644
    if valid:
        if AMBIGUOUS_DEFAULT_EPSG in valid:
            return AMBIGUOUS_DEFAULT_EPSG
        sys.stderr.write(f"[gis_utils] ambiguous zone (district={district!r}); using {valid[0]}.\n")
        return valid[0]
    sys.stderr.write(f"[gis_utils] no zone in MH (district={district!r}); defaulting 44N.\n")
    return 32644


def _to_latlon(epsg, x, y, district=None):
    if epsg is None:
        return y, x
    if district:
        dx, dy = DISTRICT_OFFSETS.get(district.strip().lower(), (0.0, 0.0))
        x, y = x + dx, y + dy
    lon, lat = _TRANSFORMERS[epsg].transform(x, y)
    return lat, lon


def _iter_polygons(geom):
    return list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]


def get_polygons_latlon(wkt_polygon, district=None):
    geom = wkt.loads(wkt_polygon)
    epsg = _resolve_epsg(geom, district)
    return [
        [list(_to_latlon(epsg, x, y, district)) for x, y in part.exterior.coords]
        for part in _iter_polygons(geom)
    ]


def get_point_latlon(wkt_polygon, district=None):
    geom = wkt.loads(wkt_polygon)
    epsg = _resolve_epsg(geom, district)
    pt = geom.representative_point()
    return _to_latlon(epsg, pt.x, pt.y, district)


def build_gis_code(category, district_code, taluka_code, village_code):
    prefix = "RVM" if category.upper() == "R" else "UCM"
    return prefix + str(district_code).zfill(2) + str(taluka_code).zfill(2) + str(village_code)
