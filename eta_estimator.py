import argparse
import os
import pandas as pd
import openrouteservice
from datetime import datetime, timedelta, time as dt_time
from dateutil import tz
import math

# Constants
BAN_CSV = "ban_times.csv"
BAN_RADIUS_KM = 20  # Ban area radius in kilometers
SAUDI_TZ = tz.gettz('Asia/Riyadh')  # Saudi Arabia timezone
DEFAULT_SPEED_KMPH = 60.0  # Default driving speed

def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance between two points on Earth (in km)."""
    R = 6371  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def parse_time(tstr):
    """Parse time string (e.g., '6:00') into datetime.time object."""
    h, m = map(int, str(tstr).split(":"))
    return dt_time(h, m)

def point_in_ban_area(lat, lon, ban_lat, ban_lon, radius_km):
    """Check if a point is within the ban area radius."""
    return haversine(lat, lon, ban_lat, ban_lon) <= radius_km

def load_ban_areas(csv_path):
    """Load ban areas from CSV into a DataFrame."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Ban areas CSV file not found: {csv_path}")
    return pd.read_csv(csv_path)

def get_route_from_ors(client, start_lat, start_lon, end_lat, end_lon):
    """Get route from OpenRouteService API."""
    coords = [(start_lon, start_lat), (end_lon, end_lat)]
    try:
        route = client.directions(coords, profile='driving-car', format='geojson', instructions=False)
        return route
    except Exception as e:
        raise Exception(f"Error fetching route from OpenRouteService: {e}")

def calculate_eta_with_bans(start_lat, start_lon, end_lat, end_lon, start_datetime, ors_api_key, vehicle_key=None, key=None, ban_radius_km=None, vehicle_speed_kmph=None):
    """
    Calculate ETA considering ban areas along the route.
    This is the unified function used by both CLI and API.
    """
    # Load ban areas
    ban_df = load_ban_areas(BAN_CSV)
    # Use custom or default ban radius and vehicle speed
    if ban_radius_km is None:
        ban_radius_km = BAN_RADIUS_KM
    if vehicle_speed_kmph is None:
        vehicle_speed_kmph = DEFAULT_SPEED_KMPH
    
    # Parse and normalize start datetime
    start_dt = datetime.fromisoformat(start_datetime)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=SAUDI_TZ)
    else:
        start_dt = start_dt.astimezone(SAUDI_TZ)
    
    # Get route from OpenRouteService
    client = openrouteservice.Client(key=ors_api_key, retry_over_query_limit=2)
    route = get_route_from_ors(client, start_lat, start_lon, end_lat, end_lon)
    
    # Extract route geometry
    geometry = route['features'][0]['geometry']['coordinates']  # list of [lon, lat]
    segments = geometry
    
    # Prepare ban areas data structure
    ban_areas = []
    for _, row in ban_df.iterrows():
        ban_areas.append({
            'city': row['City'],
            'lat': float(row['Latitude']),
            'lon': float(row['Longitude']),
            'day_of_week': row['Day_of_Week'],
            'time_start': str(row['Time_Start']),
            'time_end': str(row['Time_End'])
        })
    
    # Walk along the route, checking for ban area encounters
    delays = []
    current_time = start_dt
    last_point = segments[0]
    
    for i in range(1, len(segments)):
        p1 = last_point
        p2 = segments[i]
        
        # Calculate segment distance and travel time
        seg_dist = haversine(p1[1], p1[0], p2[1], p2[0])  # in km
        seg_time = timedelta(hours=seg_dist / vehicle_speed_kmph)
        eta_to_seg = current_time + seg_time
        
        # Check for ban area encounters at this segment
        ban_hit = False
        for ban in ban_areas:
            in_ban = point_in_ban_area(p2[1], p2[0], ban['lat'], ban['lon'], ban_radius_km)
            eta_weekday = eta_to_seg.strftime('%A')
            
            if in_ban and eta_weekday == ban['day_of_week']:
                # Calculate ban window for this specific date
                ban_start = datetime.combine(
                    eta_to_seg.date(), 
                    parse_time(ban['time_start']), 
                    tzinfo=SAUDI_TZ
                )
                ban_end = datetime.combine(
                    eta_to_seg.date(), 
                    parse_time(ban['time_end']), 
                    tzinfo=SAUDI_TZ
                )
                
                # Handle overnight ban windows
                if ban_end <= ban_start:
                    ban_end += timedelta(days=1)
                
                # Check if ETA falls within ban window
                if ban_start <= eta_to_seg <= ban_end:
                    wait = ban_end - eta_to_seg
                    delays.append({
                        'city': ban['city'],
                        'wait': wait,
                        'ban_start': ban_start,
                        'ban_end': ban_end,
                        'eta_at_ban': eta_to_seg,
                        'lat': ban['lat'],
                        'lon': ban['lon'],
                        'stop_lat': p2[1],
                        'stop_lon': p2[0]
                    })
                    current_time = ban_end
                    ban_hit = True
                    break
        
        if not ban_hit:
            current_time = eta_to_seg
        
        last_point = p2
    
    # Final check: If end point is inside a ban area during a ban window
    for ban in ban_areas:
        in_ban = point_in_ban_area(end_lat, end_lon, ban['lat'], ban['lon'], ban_radius_km)
        eta_weekday = current_time.strftime('%A')
        
        if in_ban and eta_weekday == ban['day_of_week']:
            ban_start = datetime.combine(
                current_time.date(), 
                parse_time(ban['time_start']), 
                tzinfo=SAUDI_TZ
            )
            ban_end = datetime.combine(
                current_time.date(), 
                parse_time(ban['time_end']), 
                tzinfo=SAUDI_TZ
            )
            
            if ban_end <= ban_start:
                ban_end += timedelta(days=1)
            
            if ban_start <= current_time <= ban_end:
                wait = ban_end - current_time
                delays.append({
                    'city': ban['city'],
                    'wait': wait,
                    'ban_start': ban_start,
                    'ban_end': ban_end,
                    'eta_at_ban': current_time,
                    'lat': ban['lat'],
                    'lon': ban['lon'],
                    'stop_lat': end_lat,
                    'stop_lon': end_lon
                })
                current_time = ban_end
    
    # Build schedule for API response
    schedule = []
    
    # Start event
    schedule.append({
        'vehicle_key': vehicle_key,
        'key': key,
        'event': 'start',
        'time': start_dt.strftime('%Y-%m-%d %H:%M'),
        'lat': start_lat,
        'lon': start_lon,
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
        wait_minutes = int((d['wait'].total_seconds() + 59) // 60)  # Round up to nearest minute
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
        'lat': end_lat,
        'lon': end_lon,
        'city': '',
        'wait_minutes': '',
        'ban_arrival': '',
        'ban_departure': '',
        'ban_lat': '',
        'ban_lon': '',
        'ban_city': '',
        'end_time': current_time.strftime('%Y-%m-%d %H:%M'),
        'end_lat': end_lat,
        'end_lon': end_lon
    })
    
    return {
        'eta': current_time,
        'schedule': schedule,
        'delays': delays,
        'route_segments': segments
    }


def print_trip_results(result, start_lat, start_lon, end_lat, end_lon, start_datetime):
    """Print formatted trip results for CLI."""
    eta = result['eta']
    delays = result['delays']
    
    print(f"\nEstimated ETA: {eta.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    if delays:
        print("Delays encountered:")
        for d in delays:
            wait_minutes = int((d['wait'].total_seconds() + 59) // 60)
            print(f" - City: {d['city']}, Wait: {wait_minutes} min, "
                  f"ETA at Ban: {d['eta_at_ban'].strftime('%H:%M')}, "
                  f"Ban Window: {d['ban_start'].strftime('%H:%M')} to {d['ban_end'].strftime('%H:%M')}")
    else:
        print("No ban area delays encountered.")
    
    # Print detailed schedule
    print("\n=== Trip Schedule ===")
    start_dt = datetime.fromisoformat(start_datetime)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=SAUDI_TZ)
    else:
        start_dt = start_dt.astimezone(SAUDI_TZ)
    
    print(f"START:   {start_dt.strftime('%Y-%m-%d %H:%M')} at ({start_lat:.4f}, {start_lon:.4f})")
    
    for d in delays:
        wait_minutes = int((d['wait'].total_seconds() + 59) // 60)
        print(f"BAN ARR: {d['eta_at_ban'].strftime('%Y-%m-%d %H:%M')} at ({d['stop_lat']:.4f}, {d['stop_lon']:.4f}) [{d['city']}] (wait {wait_minutes} min)")
        print(f"BAN DEP: {(d['eta_at_ban'] + d['wait']).strftime('%Y-%m-%d %H:%M')} at ({d['stop_lat']:.4f}, {d['stop_lon']:.4f}) [{d['city']}]")
    
    print(f"END:     {eta.strftime('%Y-%m-%d %H:%M')} at ({end_lat:.4f}, {end_lon:.4f})")

def main():
    """Main function for CLI usage."""
    parser = argparse.ArgumentParser(description="Estimate ETA with temporal ban area restrictions.")
    parser.add_argument("--start-lat", type=float, required=True, help="Start latitude")
    parser.add_argument("--start-lon", type=float, required=True, help="Start longitude")
    parser.add_argument("--end-lat", type=float, required=True, help="End latitude")
    parser.add_argument("--end-lon", type=float, required=True, help="End longitude")
    parser.add_argument("--start-datetime", type=str, required=True, help="Start datetime in ISO format")
    parser.add_argument("--ors-api-key", type=str, default=os.getenv("ORS_API_KEY"), help="OpenRouteService API key")
    parser.add_argument("--batch-csv", type=str, help="CSV file with multiple vehicle trips")
    
    args = parser.parse_args()
    
    if not args.ors_api_key:
        print("Error: OpenRouteService API key is required. Set ORS_API_KEY environment variable or use --ors-api-key")
        return
    
    if args.batch_csv:
        process_batch_csv(args.batch_csv, args.ors_api_key)
    else:
        try:
            result = calculate_eta_with_bans(
                args.start_lat, args.start_lon, 
                args.end_lat, args.end_lon,
                args.start_datetime, args.ors_api_key
            )
            
            print_trip_results(result, args.start_lat, args.start_lon, args.end_lat, args.end_lon, args.start_datetime)
            
            # Create and save route map
            map_file = create_route_map(
                args.start_lat, args.start_lon, 
                args.end_lat, args.end_lon,
                result['delays'], result['route_segments']
            )
            print(f"Route map saved as {map_file}. Open this file in your browser to view the route and ban stops.")
            
        except Exception as e:
            print(f"Error: {e}")

def process_batch_csv(input_path, ors_api_key):
    """Process multiple trips from a CSV file."""
    output_path = input_path.replace('.csv', '_results.csv')
    df = pd.read_csv(input_path)
    results = []
    
    for idx, row in df.iterrows():
        try:
            vehicle_key = row.get('vehicle_key', idx)
            key = row.get('key', '')
            
            result = calculate_eta_with_bans(
                row['start_lat'], row['start_lon'],
                row['end_lat'], row['end_lon'],
                row['start_datetime'], ors_api_key,
                vehicle_key, key
            )
            
            results.extend(result['schedule'])
            
        except Exception as e:
            print(f"Error processing row {idx}: {e}")
            # Add error record
            results.append({
                'vehicle_key': row.get('vehicle_key', idx),
                'key': row.get('key', ''),
                'event': 'error',
                'message': str(e),
                'time': '', 'lat': '', 'lon': '', 'city': '', 'wait_minutes': '',
                'ban_arrival': '', 'ban_departure': '', 'ban_lat': '', 'ban_lon': '',
                'ban_city': '', 'end_time': '', 'end_lat': '', 'end_lon': ''
            })
    
    # Save results
    out_df = pd.DataFrame(results)
    out_df.to_csv(output_path, index=False)
    print(f"Batch results written to {output_path}")

# For backward compatibility with API
def estimate_trip(args, vehicle_key=None, key=None):
    """Legacy function for API compatibility."""
    try:
        result = calculate_eta_with_bans(
            args.start_lat, args.start_lon,
            args.end_lat, args.end_lon,
            args.start_datetime, args.ors_api_key,
            vehicle_key, key
        )
        return result['schedule']
    except Exception as e:
        return [{
            'vehicle_key': vehicle_key,
            'key': key,
            'event': 'error',
            'message': str(e)
        }]

if __name__ == "__main__":
    main()