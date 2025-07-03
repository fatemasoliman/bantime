import argparse
import os
import pandas as pd
import openrouteservice
from datetime import datetime, timedelta
from dateutil import tz
import math
import folium

# Constants
BAN_CSV = "ban_times.csv"
BAN_RADIUS_KM = 50  # Ban area radius in kilometers
SAUDI_TZ = tz.gettz('Asia/Riyadh')  # Saudi Arabia timezone

# Haversine function to compute distance between two lat/lon points in km
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

# Parse time string (e.g., '6:00') into datetime.time
from datetime import time as dt_time

def parse_time(tstr):
    h, m = map(int, tstr.split(":"))
    return dt_time(h, m)

# Given a weekday and ban row, get ban start and end datetime objects for the trip date
def get_ban_window(trip_date, ban_row):
    # trip_date: datetime.date
    start_time = parse_time(str(ban_row['Time_Start']))
    end_time = parse_time(str(ban_row['Time_End']))
    start_dt = datetime.combine(trip_date, start_time, tzinfo=SAUDI_TZ)
    end_dt = datetime.combine(trip_date, end_time, tzinfo=SAUDI_TZ)
    # Handle overnight ban windows (e.g., 23:00 to 01:00)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt

# Check if a point is within BAN_RADIUS_KM of a ban area
def point_in_ban_area(lat, lon, ban_lat, ban_lon, radius_km=BAN_RADIUS_KM):
    return haversine(lat, lon, ban_lat, ban_lon) <= radius_km

BAN_CSV = "ban_times.csv"


def load_ban_areas(csv_path):
    """Load ban areas from CSV into a DataFrame."""
    df = pd.read_csv(csv_path)
    return df


def main():
    parser = argparse.ArgumentParser(description="Estimate ETA with temporal ban area restrictions.")
    parser.add_argument("--start-lat", type=float, required=True, help="Start latitude")
    parser.add_argument("--start-lon", type=float, required=True, help="Start longitude")
    parser.add_argument("--end-lat", type=float, required=True, help="End latitude")
    parser.add_argument("--end-lon", type=float, required=True, help="End longitude")
    parser.add_argument("--start-datetime", type=str, required=True, help="Start datetime in ISO format (e.g. 2025-07-02T23:31:50+03:00)")
    parser.add_argument("--ors-api-key", type=str, default=os.getenv("ORS_API_KEY"), help="OpenRouteService API key (or set ORS_API_KEY env var)")
    args = parser.parse_args()

    # Load ban areas
    ban_df = load_ban_areas(BAN_CSV)
    # Parse trip start datetime
    start_dt = datetime.fromisoformat(args.start_datetime)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=SAUDI_TZ)
    else:
        start_dt = start_dt.astimezone(SAUDI_TZ)
    trip_date = start_dt.date()
    trip_weekday = start_dt.strftime('%A')

    # Prepare OpenRouteService client
    client = openrouteservice.Client(key=args.ors_api_key)
    coords = [(args.start_lon, args.start_lat), (args.end_lon, args.end_lat)]
    # Request route with geometry and segment info
    try:
        route = client.directions(coords, profile='driving-car', format='geojson', instructions=False)
    except Exception as e:
        print(f"Error fetching route: {e}")
        return
    geometry = route['features'][0]['geometry']['coordinates']  # list of [lon, lat]
    segments = geometry
    # Get total route distance and duration
    summary = route['features'][0]['properties']['summary']
    total_distance = summary['distance']  # meters
    total_duration = summary['duration']  # seconds

    # Prepare ban windows for the trip day
    ban_windows = []
    for _, row in ban_df.iterrows():
        if row['Day_of_Week'] == trip_weekday:
            ban_lat, ban_lon = float(row['Latitude']), float(row['Longitude'])
            start_ban, end_ban = get_ban_window(trip_date, row)
            ban_windows.append({
                'city': row['City'],
                'start': start_ban,
                'end': end_ban,
                'lat': ban_lat,
                'lon': ban_lon
            })

    # Walk along the route, checking for ban area entry
    # We'll assume constant speed between points for ETA estimation
    delays = []
    current_time = start_dt
    last_point = segments[0]
    distance_travelled = 0
    for i in range(1, len(segments)):
        p1 = last_point
        p2 = segments[i]
        seg_dist = haversine(p1[1], p1[0], p2[1], p2[0])  # in km
        # Use fixed speed of 20 km/h for ETA calculation
        speed_kmph = 20.0
        seg_time = timedelta(hours=seg_dist / speed_kmph)
        eta_to_seg = current_time + seg_time
        # Check each ban area
        for ban in ban_windows:
            # If segment enters ban area
            if point_in_ban_area(p2[1], p2[0], ban['lat'], ban['lon']):
                # If ETA falls within ban window, add wait
                if ban['start'] <= eta_to_seg <= ban['end']:
                    wait = ban['end'] - eta_to_seg
                    current_time = ban['end']
                    delays.append({
                    'city': ban['city'],
                    'wait': wait,
                    'ban_start': ban['start'],
                    'ban_end': ban['end'],
                    'eta_at_ban': eta_to_seg,
                    'lat': ban['lat'],
                    'lon': ban['lon'],
                    'stop_lat': p2[1],
                    'stop_lon': p2[0]
                })
                # Only delay once per ban area
                ban_windows.remove(ban)
                break
        current_time += seg_time
        last_point = p2
        distance_travelled += seg_dist
    # Output results
    print(f"\nEstimated ETA: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if delays:
        print("Delays encountered:")
        for d in delays:
            # Round up wait to nearest minute
            wait_minutes = int((d['wait'].total_seconds() + 59) // 60)
            print(f" - City: {d['city']}, Wait: {wait_minutes} min, ETA at Ban: {d['eta_at_ban'].strftime('%H:%M')}, Ban Window: {d['ban_start'].strftime('%H:%M')} to {d['ban_end'].strftime('%H:%M')}")
    else:
        print("No ban area delays encountered.")

    # Print schedule
    print("\n=== Trip Schedule ===")
    print(f"START:   {start_dt.strftime('%Y-%m-%d %H:%M')} at ({args.start_lat:.4f}, {args.start_lon:.4f})")
    last_time = start_dt
    last_lat = args.start_lat
    last_lon = args.start_lon
    for d in delays:
        print(f"BAN ARR: {d['eta_at_ban'].strftime('%Y-%m-%d %H:%M')} at ({d['stop_lat']:.4f}, {d['stop_lon']:.4f}) [{d['city']}] (wait {int((d['wait'].total_seconds() + 59) // 60)} min)")
        print(f"BAN DEP: {(d['eta_at_ban'] + d['wait']).strftime('%Y-%m-%d %H:%M')} at ({d['stop_lat']:.4f}, {d['stop_lon']:.4f}) [{d['city']}]")
        last_time = d['eta_at_ban'] + d['wait']
        last_lat = d['stop_lat']
        last_lon = d['stop_lon']
    print(f"END:     {current_time.strftime('%Y-%m-%d %H:%M')} at ({args.end_lat:.4f}, {args.end_lon:.4f})")

    # --- Route Visualization ---
    # Center map between start and end
    mid_lat = (args.start_lat + args.end_lat) / 2
    mid_lon = (args.start_lon + args.end_lon) / 2
    m = folium.Map(location=[mid_lat, mid_lon], zoom_start=6)

    # Draw route polyline
    folium.PolyLine([(lat, lon) for lon, lat in segments], color="blue", weight=5, opacity=0.7).add_to(m)

    # Mark start and end
    folium.Marker(
        [args.start_lat, args.start_lon],
        popup=f"Start ({args.start_lat:.4f}, {args.start_lon:.4f})",
        icon=folium.Icon(color="green", icon="play")
    ).add_to(m)
    folium.Marker(
        [args.end_lat, args.end_lon],
        popup=f"End ({args.end_lat:.4f}, {args.end_lon:.4f})",
        icon=folium.Icon(color="red", icon="stop")
    ).add_to(m)

    # Mark ban stops at the actual stop location
    for d in delays:
        wait_minutes = int((d['wait'].total_seconds() + 59) // 60)
        departure_time = (d['eta_at_ban'] + d['wait']).strftime('%Y-%m-%d %H:%M')
        folium.CircleMarker(
            location=[d['stop_lat'], d['stop_lon']],
            radius=14,
            color="orange",
            fill=True,
            fill_color="red",
            fill_opacity=0.95,
            tooltip=f"Ban Stop: {d['city']}",
            popup=folium.Popup(
                f"<b>Ban Stop: {d['city']}</b><br>"
                f"Arrival: {d['eta_at_ban'].strftime('%Y-%m-%d %H:%M')}<br>"
                f"Departure: {departure_time}<br>"
                f"Wait: {wait_minutes} min<br>"
                f"Ban Window: {d['ban_start'].strftime('%H:%M')} - {d['ban_end'].strftime('%H:%M')}",
                max_width=300
            )
        ).add_to(m)
    # Save map
    m.save("route_map.html")
    print("Route map saved as route_map.html. Open this file in your browser to view the route and ban stops.")

def estimate_trip(args, vehicle_key=None, key=None):
    # Load ban areas
    ban_df = load_ban_areas(BAN_CSV)
    # Parse trip start datetime
    start_dt = datetime.fromisoformat(args.start_datetime)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=SAUDI_TZ)
    else:
        start_dt = start_dt.astimezone(SAUDI_TZ)
    trip_date = start_dt.date()
    trip_weekday = start_dt.strftime('%A')

    # Prepare OpenRouteService client
    client = openrouteservice.Client(key=args.ors_api_key)
    coords = [(args.start_lon, args.start_lat), (args.end_lon, args.end_lat)]
    # Request route with geometry and segment info
    try:
        route = client.directions(coords, profile='driving-car', format='geojson', instructions=False)
    except Exception as e:
        return [{
            'vehicle_key': vehicle_key,
        'key': key,
            'event': 'error',
            'message': f'Error fetching route: {e}'
        }]
    geometry = route['features'][0]['geometry']['coordinates']  # list of [lon, lat]
    segments = geometry
    # Get total route distance and duration
    summary = route['features'][0]['properties']['summary']
    total_distance = summary['distance']  # meters
    total_duration = summary['duration']  # seconds

    # Prepare ban windows for the trip day
    ban_windows = []
    for _, row in ban_df.iterrows():
        if row['Day_of_Week'] == trip_weekday:
            ban_lat, ban_lon = float(row['Latitude']), float(row['Longitude'])
            start_ban, end_ban = get_ban_window(trip_date, row)
            ban_windows.append({
                'city': row['City'],
                'start': start_ban,
                'end': end_ban,
                'lat': ban_lat,
                'lon': ban_lon
            })

    # Walk along the route, checking for ban area entry
    delays = []
    current_time = start_dt
    last_point = segments[0]
    for i in range(1, len(segments)):
        p1 = last_point
        p2 = segments[i]
        seg_dist = haversine(p1[1], p1[0], p2[1], p2[0])  # in km
        seg_time = timedelta(seconds=(seg_dist * 1000) / total_distance * total_duration)
        eta_to_seg = current_time + seg_time
        for ban in ban_windows:
            if point_in_ban_area(p2[1], p2[0], ban['lat'], ban['lon']):
                if ban['start'] <= eta_to_seg <= ban['end']:
                    wait = ban['end'] - eta_to_seg
                    current_time = ban['end']
                    delays.append({
                        'city': ban['city'],
                        'wait': wait,
                        'ban_start': ban['start'],
                        'ban_end': ban['end'],
                        'eta_at_ban': eta_to_seg,
                        'lat': ban['lat'],
                        'lon': ban['lon'],
                        'stop_lat': p2[1],
                        'stop_lon': p2[0]
                    })
                    ban_windows.remove(ban)
                    break
        current_time += seg_time
        last_point = p2

    # Prepare schedule output as list of dicts
    schedule = []
    # Start event
    schedule.append({
        'vehicle_key': vehicle_key,
        'key': key,
        'event': 'start',
        'time': start_dt.strftime('%Y-%m-%d %H:%M'),
        'lat': args.start_lat,
        'lon': args.start_lon,
        'city': '',
        'wait_minutes': '',
        'ban_arrival': '',
        'ban_departure': '',
        'ban_lat': '',
        'ban_lon': '',
        'ban_city': '',
        'end_time': '',
        'end_lat': '',
        'end_lon': ''
    })
    # Ban events
    for d in delays:
        wait_minutes = int((d['wait'].total_seconds() + 59) // 60)
        schedule.append({
            'vehicle_key': vehicle_key,
        'key': key,
            'event': 'ban',
            'time': d['eta_at_ban'].strftime('%Y-%m-%d %H:%M'),
            'lat': d['stop_lat'],
            'lon': d['stop_lon'],
            'city': d['city'],
            'wait_minutes': wait_minutes,
            'ban_arrival': d['eta_at_ban'].strftime('%Y-%m-%d %H:%M'),
            'ban_departure': (d['eta_at_ban'] + d['wait']).strftime('%Y-%m-%d %H:%M'),
            'ban_lat': d['stop_lat'],
            'ban_lon': d['stop_lon'],
            'ban_city': d['city'],
            'end_time': '',
            'end_lat': '',
            'end_lon': ''
        })
    # End event
    schedule.append({
        'vehicle_key': vehicle_key,
        'key': key,
        'event': 'end',
        'time': current_time.strftime('%Y-%m-%d %H:%M'),
        'lat': args.end_lat,
        'lon': args.end_lon,
        'city': '',
        'wait_minutes': '',
        'ban_arrival': '',
        'ban_departure': '',
        'ban_lat': '',
        'ban_lon': '',
        'ban_city': '',
        'end_time': current_time.strftime('%Y-%m-%d %H:%M'),
        'end_lat': args.end_lat,
        'end_lon': args.end_lon
    })
    return schedule

if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description="Estimate ETA with temporal ban area restrictions.")
    parser.add_argument("--start-lat", type=float, help="Start latitude")
    parser.add_argument("--start-lon", type=float, help="Start longitude")
    parser.add_argument("--end-lat", type=float, help="End latitude")
    parser.add_argument("--end-lon", type=float, help="End longitude")
    parser.add_argument("--start-datetime", type=str, help="Start datetime in ISO format (e.g. 2025-07-02T23:31:50+03:00)")
    parser.add_argument("--ors-api-key", type=str, default=os.getenv("ORS_API_KEY"), help="OpenRouteService API key (or set ORS_API_KEY env var)")
    parser.add_argument("--batch-csv", type=str, default=None, help="CSV file with multiple vehicle trips (columns: vehicle_key,start_lat,start_lon,end_lat,end_lon,start_datetime)")
    args = parser.parse_args()

    if args.batch_csv:
        import pandas as pd
        input_path = args.batch_csv
        output_path = input_path.replace('.csv', '_results.csv')
        df = pd.read_csv(input_path)
        results = []
        for idx, row in df.iterrows():
            class BatchArgs:
                pass
            batch_args = BatchArgs()
            batch_args.start_lat = row['start_lat']
            batch_args.start_lon = row['start_lon']
            batch_args.end_lat = row['end_lat']
            batch_args.end_lon = row['end_lon']
            batch_args.start_datetime = row['start_datetime']
            batch_args.ors_api_key = args.ors_api_key
            vehicle_key = row['vehicle_key'] if 'vehicle_key' in row else idx
            key = row['key'] if 'key' in row else ''
            trip_results = estimate_trip(batch_args, vehicle_key, key)
            results.extend(trip_results)
        out_df = pd.DataFrame(results)
        out_df.to_csv(output_path, index=False)
        print(f"Batch results written to {output_path}")
    else:
        main()
