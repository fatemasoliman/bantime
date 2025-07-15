import argparse
import json
import os
from typing import List, Dict, Any
from eta_estimator import calculate_eta_with_bans

def process_batch(trips: List[Dict[str, Any]], ban_radius_km=None, vehicle_speed_kmph=None):
    """
    Process a batch of trips using the ORS API key from the environment variable.
    Optionally override ban area radius and vehicle speed.
    """
    results = {}
    if not trips:
        print("No trips provided.")
        return results
    api_key = os.getenv("ORS_API_KEY")
    if not api_key:
        print("OpenRouteService API key is required. Set the ORS_API_KEY environment variable.")
        return results
    for trip in trips:
        try:
            result = calculate_eta_with_bans(
                trip["start_lat"], trip["start_lng"],
                trip["end_lat"], trip["end_lng"],
                trip["start_time"], api_key,
                trip.get("vehicle_key"), trip["key"],
                ban_radius_km=ban_radius_km, vehicle_speed_kmph=vehicle_speed_kmph,
                max_driving_hours=args.max_driving_hours
            )
            eta_event = next((e for e in result['schedule'] if e['event'] == 'end'), None)
            if not eta_event:
                results[trip["key"]] = {"error": "ETA calculation failed - no end event found."}
            else:
                results[trip["key"]] = {"eta": eta_event['time']}
        except Exception as e:
            results[trip["key"]] = {"error": str(e)}
    return results

def main():
    import csv
    parser = argparse.ArgumentParser(description="ETA calculator CLI. Supports batch (--input) or single-trip mode.")
    parser.add_argument('--input', '-i', help='Path to input JSON file containing a list of trips (no API key needed)')
    parser.add_argument('--output', '-o', help='Optional path to output JSON file')
    parser.add_argument('--output-csv', help='Optional path to output CSV file (key and eta columns)')
    parser.add_argument('--ban-radius-km', type=float, help='Override ban area radius in kilometers')
    parser.add_argument('--max-driving-hours', type=float, default=10, help='Maximum continuous driving hours in a 24h window before mandatory rest')
    parser.add_argument('--vehicle-speed-kmph', type=float, help='Override vehicle speed in kilometers per hour')
    # Single-trip arguments
    parser.add_argument('--start-lat', type=float, help='Start latitude')
    parser.add_argument('--start-lon', type=float, help='Start longitude')
    parser.add_argument('--end-lat', type=float, help='End latitude')
    parser.add_argument('--end-lon', type=float, help='End longitude')
    parser.add_argument('--start-datetime', type=str, help='Start datetime in ISO format')
    parser.add_argument('--ors-api-key', type=str, help='OpenRouteService API key')
    parser.add_argument('--vehicle-key', type=str, help='Vehicle key')
    parser.add_argument('--key', type=str, help='Trip key')
    args = parser.parse_args()

    if args.input:
        with open(args.input, 'r') as f:
            trips = json.load(f)
        results = process_batch(trips, ban_radius_km=args.ban_radius_km, vehicle_speed_kmph=args.vehicle_speed_kmph)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"Results written to {args.output}")
        if args.output_csv:
            with open(args.output_csv, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["key", "eta"])
                for key, val in results.items():
                    eta = val.get("eta") if "eta" in val else val.get("error", "")
                    writer.writerow([key, eta])
            print(f"Key/ETA CSV written to {args.output_csv}")
    else:
        # Single-trip mode: require all trip arguments
        required = [args.start_lat, args.start_lon, args.end_lat, args.end_lon, args.start_datetime]
        if any(v is None for v in required):
            parser.error('Single-trip mode requires --start-lat, --start-lon, --end-lat, --end-lon, --start-datetime')
        ors_api_key = args.ors_api_key or os.getenv("ORS_API_KEY")
        if not ors_api_key:
            parser.error('ORS API key must be provided via --ors-api-key or ORS_API_KEY environment variable')
        result = calculate_eta_with_bans(
            args.start_lat, args.start_lon, args.end_lat, args.end_lon,
            args.start_datetime, ors_api_key,
            ban_radius_km=args.ban_radius_km,
            vehicle_speed_kmph=args.vehicle_speed_kmph,
            max_driving_hours=args.max_driving_hours
        )
        # Convert timedelta in delays to minutes for JSON serialization
        delays_serializable = []
        for d in result['delays']:
            d_serial = d.copy()
            # Convert timedelta to minutes
            if isinstance(d_serial.get('wait'), (int, float)):
                pass
            elif d_serial.get('wait') is not None:
                d_serial['wait'] = int((d_serial['wait'].total_seconds() + 59) // 60)
            # Convert datetime fields to strings
            for dt_field in ['ban_start', 'ban_end', 'eta_at_ban']:
                if isinstance(d_serial.get(dt_field), (str, type(None))):
                    continue
                if d_serial.get(dt_field) is not None:
                    d_serial[dt_field] = d_serial[dt_field].strftime('%Y-%m-%d %H:%M:%S')
            delays_serializable.append(d_serial)
        trip_key = args.key or 'trip_1'
        print(json.dumps({trip_key: {'eta': result['eta'].strftime('%Y-%m-%d %H:%M:%S'), 'delays': delays_serializable}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
