import json
from shapely.geometry import Polygon, Point
from datetime import datetime, time as dt_time

class BanAreaManager:
    def __init__(self, polygons_path='polygons.geojson', ban_times_path='ban_times.json'):
        self.polygons = self._load_polygons(polygons_path)
        self.ban_times = self._load_ban_times(ban_times_path)
        
    def _load_polygons(self, path):
        """Load city polygons from GeoJSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        polygons = {}
        for feature in data['features']:
            city = feature['properties']['city']
            coordinates = feature['geometry']['coordinates']
            polygons[city] = Polygon(coordinates[0])  # Assuming single polygon per city
        return polygons
    
    def _load_ban_times(self, path):
        """Load ban times from JSON file."""
        with open(path, 'r') as f:
            return json.load(f)
    
    def is_in_ban_area(self, lat, lon):
        """Check if a point is within any city ban area."""
        point = Point(lon, lat)
        for city, polygon in self.polygons.items():
            if polygon.contains(point):
                return city
        return None
    
    def get_ban_times(self, city, dt):
        """Get applicable ban times for a city at a given datetime."""
        if not city:
            return []
        
        day_of_week = dt.strftime('%A')
        current_time = dt.time()
        
        applicable_bans = []
        for ban in self.ban_times:
            if (ban['city'] == city and 
                ban['day_of_week'] == day_of_week and 
                parse_time(ban['time_start']) <= current_time <= parse_time(ban['time_end'])):
                applicable_bans.append({
                    'start': parse_time(ban['time_start']),
                    'end': parse_time(ban['time_end'])
                })
        return applicable_bans

def parse_time(tstr):
    # Accepts '6:00', '06:00', '6:00:00', etc.
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(tstr, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Invalid time format: {tstr}")
