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
                ban_radius_km=ban_radius_km, vehicle_speed_kmph=vehicle_speed_kmph
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
    parser = argparse.ArgumentParser(description="Batch ETA calculator CLI. Requires ORS_API_KEY environment variable.")
    parser.add_argument('--input', '-i', required=True, help='Path to input JSON file containing a list of trips (no API key needed)')
    parser.add_argument('--output', '-o', help='Optional path to output JSON file')
    parser.add_argument('--output-csv', help='Optional path to output CSV file (key and eta columns)')
    parser.add_argument('--ban-radius-km', type=float, help='Override ban area radius in kilometers')
    parser.add_argument('--vehicle-speed-kmph', type=float, help='Override vehicle speed in kilometers per hour')
    args = parser.parse_args()

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

if __name__ == "__main__":
    main()
