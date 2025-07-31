import argparse
import os
import openrouteservice
from datetime import datetime, timedelta, time as dt_time
from ban_area_utils import BanAreaManager
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

# Initialize ban area manager
ban_area_manager = BanAreaManager()

# Function to check if a point is in a ban area and get applicable ban times

def get_route_from_ors(client, start_lat, start_lon, end_lat, end_lon):
    """Get route from OpenRouteService API."""
    coords = [(start_lon, start_lat), (end_lon, end_lat)]
    try:
        # Increase search radius for routable points to 1000 meters
        route = client.directions(
            coords,
            profile='driving-car',
            format='geojson',
            instructions=False,
            radiuses=[1000, 1000]
        )
        return route
    except Exception as e:
        raise Exception(f"Error fetching route from OpenRouteService: {e}")

def calculate_eta_with_bans(
    start_lat, start_lon, end_lat, end_lon, start_datetime, ors_api_key,
    vehicle_key=None, key=None, ban_radius_km=None, vehicle_speed_kmph=None, max_driving_hours=10
):
    """
    Calculate ETA considering ban areas, max driving hours, and rest stops along the route.
    Uses OpenRouteService default speeds if vehicle_speed_kmph is not provided.
    Args:
        start_lat, start_lon, end_lat, end_lon: Coordinates for route endpoints.
        start_datetime: ISO string for trip start (with or without timezone).
        ors_api_key: OpenRouteService API key.
        ban_radius_km: Radius for ban area checking (default if None).
        vehicle_speed_kmph: Fixed speed override (if None, use ORS speeds).
        max_driving_hours: Max allowed driving hours in any 24h window (default 10).
    Returns:
        Dict with ETA, delays, and schedule.
    """
    use_ors_durations = vehicle_speed_kmph is None

    # Load ban polygons from JSON with day of week and time ranges
    # Use BanAreaManager for ban zone checks
    # ban_area_manager = BanAreaManager() is already instantiated at the top
    # Helper function to check if a point is in a ban area and get ban times
    def point_in_any_ban_zone_using_manager(lat, lon, current_time):
        city = ban_area_manager.is_in_ban_area(lat, lon)
        if city:
            ban_times = ban_area_manager.get_ban_times(city, current_time)
            for ban_time in ban_times:
                # Handle overnight bans
                if ban_time['start'] <= ban_time['end']:
                    if ban_time['start'] <= current_time.time() <= ban_time['end']:
                        return {
                            'city': city,
                            'time_start': ban_time['start'],
                            'time_end': ban_time['end']
                        }
                else:
                    # Overnight ban
                    if current_time.time() >= ban_time['start'] or current_time.time() <= ban_time['end']:
                        return {
                            'city': city,
                            'time_start': ban_time['start'],
                            'time_end': ban_time['end']
                        }
        return None

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
    
    # If you need to associate time/city info, load it from another source or extend the GeoJSON properties.
    # Here, we only use polygons for spatial checks.
    
    # Walk along the route, checking for ban area encounters
    delays = []
    current_time = start_dt
    last_point = segments[0]
    last_ban_zone = None

    schedule = []  # Initialize schedule as an empty list

    # --- Resting hours logic ---
    # Track driving periods (list of tuples: (start_time, end_time, duration))
    driving_periods = []
    driving_time_24h = timedelta()  # Cumulative driving time in last 24h
    window_start_time = current_time  # Start of current 24h window
    
    # If using ORS durations, extract them from the ORS response
    if use_ors_durations:
        # Try to get segment durations from ORS response
        properties = route['features'][0]['properties']
        if 'segments' in properties and properties['segments']:
            ors_segments = properties['segments'][0]
            ors_total_duration = ors_segments['duration']  # in seconds
            ors_total_distance = ors_segments['distance']  # in meters
        else:
            # Fallback: use summary fields
            ors_total_duration = properties.get('summary', {}).get('duration')
            ors_total_distance = properties.get('summary', {}).get('distance')
            # If still not found, try top-level
            if ors_total_duration is None:
                ors_total_duration = properties.get('duration')
            if ors_total_distance is None:
                ors_total_distance = properties.get('distance')
            if ors_total_duration is None or ors_total_distance is None:
                raise Exception('Could not find route duration/distance in ORS response.')
        # Distribute duration proportionally to each segment by distance
        total_dist = sum(haversine(segments[i-1][1], segments[i-1][0], segments[i][1], segments[i][0]) for i in range(1, len(segments)))
        # Precompute segment durations
        seg_durations = []
        for i in range(1, len(segments)):
            p1 = segments[i-1]
            p2 = segments[i]
            seg_dist = haversine(p1[1], p1[0], p2[1], p2[0])
            if total_dist > 0:
                seg_seconds = ors_total_duration * (seg_dist / total_dist)
            else:
                seg_seconds = 0
            seg_durations.append(seg_seconds)

    
    for i in range(1, len(segments)):
        p1 = last_point
        p2 = segments[i]
        seg_dist = haversine(p1[1], p1[0], p2[1], p2[0])  # in km
        if use_ors_durations:
            seg_time = timedelta(seconds=seg_durations[i-1])
        else:
            seg_time = timedelta(hours=seg_dist / vehicle_speed_kmph)

        # --- SPLIT SEGMENT IF IT EXCEEDS MAX DRIVING HOURS ---
        max_drive_td = timedelta(hours=max_driving_hours)
        n_splits = max(1, int(seg_time // max_drive_td) + (1 if seg_time % max_drive_td > timedelta(0) else 0))
        for split_idx in range(n_splits):
            # For each sub-segment
            if n_splits == 1:
                sub_seg_time = seg_time
                sub_seg_dist = seg_dist
                sub_p1 = p1
                sub_p2 = p2
            else:
                # Interpolate points for sub-segments
                sub_seg_time = min(max_drive_td, seg_time - split_idx * max_drive_td)
                sub_seg_dist = seg_dist * (sub_seg_time / seg_time)
                frac1 = split_idx / n_splits
                frac2 = (split_idx + 1) / n_splits
                sub_p1 = (
                    p1[0] + (p2[0] - p1[0]) * frac1,
                    p1[1] + (p2[1] - p1[1]) * frac1
                )
                sub_p2 = (
                    p1[0] + (p2[0] - p1[0]) * frac2,
                    p1[1] + (p2[1] - p1[1]) * frac2
                )

            # --- Update rolling 24h window ---
            driving_periods = [d for d in driving_periods if (current_time - d[0]) < timedelta(hours=24)]
            driving_time_24h = sum((d[2] for d in driving_periods), timedelta())

            # If adding this sub-segment would exceed max_driving_hours in 24h, insert a 14h rest
            if driving_time_24h + sub_seg_time > max_drive_td:
                if driving_periods:
                    oldest_start = min(d[0] for d in driving_periods)
                    rest_until = oldest_start + timedelta(hours=24)
                else:
                    rest_until = current_time + timedelta(hours=14)
                rest_time = rest_until - current_time
                if rest_time < timedelta(hours=14):
                    rest_time = timedelta(hours=14)
                delays.append({
                    'city': 'Rest Stop',
                    'wait': rest_time,
                    'ban_start': current_time,
                    'ban_end': current_time + rest_time,
                    'eta_at_ban': current_time,
                    'lat': sub_p2[1],
                    'lon': sub_p2[0],
                    'stop_lat': sub_p2[1],
                    'stop_lon': sub_p2[0]
                })
                current_time += rest_time
                driving_periods = [d for d in driving_periods if (current_time - d[0]) < timedelta(hours=24)]
                driving_time_24h = sum((d[2] for d in driving_periods), timedelta())

            # Add this sub-segment driving period
            driving_periods.append((current_time, current_time + sub_seg_time, sub_seg_time))
            driving_time_24h += sub_seg_time

            # Check for ban zones
            ban_zone = point_in_any_ban_zone_using_manager(sub_p2[1], sub_p2[0], current_time)
            if ban_zone and ban_zone != last_ban_zone:
                # Calculate wait time until ban ends
                ban_end_time = current_time.replace(
                    hour=ban_zone['time_end'].hour,
                    minute=ban_zone['time_end'].minute,
                    second=0,
                    microsecond=0
                )
                
                if ban_zone['time_end'] <= ban_zone['time_start']:
                    # Overnight ban - add one day
                    ban_end_time += timedelta(days=1)
                
                wait_time = ban_end_time - current_time
                if wait_time.total_seconds() > 0:  # Only add delay if we need to wait
                    delays.append({
                        'city': ban_zone['city'],
                        'wait': wait_time,
                        'ban_start': current_time,
                        'ban_end': ban_end_time,
                        'eta_at_ban': current_time,
                        'lat': sub_p2[1],
                        'lon': sub_p2[0],
                        'stop_lat': sub_p2[1],
                        'stop_lon': sub_p2[0]
                    })
                    current_time += wait_time
                
                last_ban_zone = ban_zone
            else:
                last_ban_zone = None
            driving_periods.append((current_time, current_time + sub_seg_time, sub_seg_time))
            current_time += sub_seg_time
            last_point = sub_p2

        # Check for ban area encounters at this segment
        ban_hit = False
        # Check both start and end points of the segment
        for point in [p1, p2]:
            in_ban = point_in_any_ban_zone_using_manager(point[1], point[0], current_time)
            if in_ban:
                # Calculate wait time until ban ends
                ban_end_time = current_time.replace(
                    hour=in_ban['time_end'].hour,
                    minute=in_ban['time_end'].minute,
                    second=0,
                    microsecond=0
                )
                
                if in_ban['time_end'] <= in_ban['time_start']:
                    # Overnight ban - add one day
                    ban_end_time += timedelta(days=1)
                
                wait_time = ban_end_time - current_time
                if wait_time.total_seconds() > 0:
                    delays.append({
                        'city': in_ban['city'],
                        'wait': wait_time,
                        'ban_start': current_time,
                        'ban_end': ban_end_time,
                        'eta_at_ban': current_time,
                        'lat': point[1],
                        'lon': point[0],
                        'stop_lat': point[1],
                        'stop_lon': point[0]
                    })
                    current_time += wait_time
                    ban_hit = True
                    break
        
        if not ban_hit:
            current_time = current_time
        
        # Record this segment's driving period
        driving_periods.append((current_time - seg_time, current_time, seg_time))
        last_point = p2

        # Check additional points along the segment if it's long enough
        if seg_dist > 10:  # Check every 10km
            num_points = int(seg_dist / 10)
            for i in range(1, num_points):
                frac = i / num_points
                point = (
                    p1[0] + (p2[0] - p1[0]) * frac,
                    p1[1] + (p2[1] - p1[1]) * frac
                )
                in_ban = point_in_any_ban_zone_using_manager(point[1], point[0], current_time)
                if in_ban:
                    # Calculate wait time until ban ends
                    ban_end_time = current_time.replace(
                        hour=in_ban['time_end'].hour,
                        minute=in_ban['time_end'].minute,
                        second=0,
                        microsecond=0
                    )
                    
                    if in_ban['time_end'] <= in_ban['time_start']:
                        ban_end_time += timedelta(days=1)
                    
                    wait_time = ban_end_time - current_time
                    if wait_time.total_seconds() > 0:
                        delays.append({
                            'city': in_ban['city'],
                            'wait': wait_time,
                        })
                        break
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