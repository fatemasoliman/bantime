import argparse
import json
import os
from typing import List, Dict, Any
from eta_estimator import calculate_eta_with_bans

def process_batch(trips: List[Dict[str, Any]], default_api_key=None):
    results = {}
    if not trips:
        print("No trips provided.")
        return results
    if not default_api_key:
        default_api_key = trips[0].get("ors_api_key") or os.getenv("ORS_API_KEY")
    if not default_api_key:
        print("OpenRouteService API key is required. Provide in trip or set ORS_API_KEY environment variable.")
        return results
    for trip in trips:
        api_key = trip.get("ors_api_key") or default_api_key
        try:
            result = calculate_eta_with_bans(
                trip["start_lat"], trip["start_lng"],
                trip["end_lat"], trip["end_lng"],
                trip["start_time"], api_key,
                trip.get("vehicle_key"), trip["key"]
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
    parser = argparse.ArgumentParser(description="Batch ETA calculator CLI.")
    parser.add_argument('--input', '-i', required=True, help='Path to input JSON file containing a list of trips')
    parser.add_argument('--output', '-o', help='Optional path to output JSON file')
    args = parser.parse_args()

    with open(args.input, 'r') as f:
        trips = json.load(f)

    results = process_batch(trips)

    print(json.dumps(results, indent=2, ensure_ascii=False))

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Results written to {args.output}")

if __name__ == "__main__":
    main()
