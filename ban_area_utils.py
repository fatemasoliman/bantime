import json
from shapely.geometry import shape, Point


def load_ban_polygons(geojson_path):
    """
    Load ban polygons from a GeoJSON file.
    Returns a list of shapely Polygon objects.
    """
    with open(geojson_path, 'r') as f:
        geojson = json.load(f)
    polygons = []
    for feature in geojson['features']:
        geom = feature['geometry']
        if geom['type'] == 'Polygon':
            polygons.append(shape(geom))
    return polygons


def point_in_any_ban_polygon(lat, lon, polygons):
    """
    Check if the given (lat, lon) falls within any of the given polygons.
    """
    point = Point(lon, lat)  # Note: shapely uses (x, y) = (lon, lat)
    return any(polygon.contains(point) for polygon in polygons)
