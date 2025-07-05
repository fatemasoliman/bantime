from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
from eta_estimator import calculate_eta_with_bans

app = FastAPI()

from typing import List, Dict, Any
import os
from eta_estimator import calculate_eta_with_bans

app = FastAPI()

@app.post("/eta")
async def get_eta(trips: List[Dict[str, Any]]):
    """Calculate ETAs for a batch of trips. Accepts a list of trip dicts as input."""
    if not trips:
        raise HTTPException(status_code=400, detail="No trips provided.")
    results = {}
    # Use API key from first trip or from env as fallback
    default_api_key = trips[0].get("ors_api_key") or os.getenv("ORS_API_KEY")
    if not default_api_key:
        raise HTTPException(status_code=400, detail="OpenRouteService API key is required. Provide in request or set ORS_API_KEY environment variable.")
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

class TripItem(BaseModel):
    key: str
    vehicle_key: Optional[str] = None
    start_time: str
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    ors_api_key: Optional[str] = None

class BatchETARequest(BaseModel):
    trips: List[TripItem]

@app.post("/eta/batch")
def get_eta_batch(batch_req: BatchETARequest):
    """Calculate ETAs for multiple trips in batch."""
    results = {}
    trips = batch_req.trips
    if not trips:
        raise HTTPException(status_code=400, detail="No trips provided.")

    # Use API key from first trip or from env as fallback
    default_api_key = trips[0].ors_api_key or os.getenv("ORS_API_KEY")
    if not default_api_key:
        raise HTTPException(status_code=400, detail="OpenRouteService API key is required. Provide in request or set ORS_API_KEY environment variable.")

    for trip in trips:
        api_key = trip.ors_api_key or default_api_key
        try:
            result = calculate_eta_with_bans(
                trip.start_lat, trip.start_lng,
                trip.end_lat, trip.end_lng,
                trip.start_time, api_key,
                trip.vehicle_key, trip.key
            )
            eta_event = next((e for e in result['schedule'] if e['event'] == 'end'), None)
            if not eta_event:
                results[trip.key] = {"error": "ETA calculation failed - no end event found."}
            else:
                results[trip.key] = {"eta": eta_event['time']}
        except Exception as e:
            results[trip.key] = {"error": str(e)}
    return results

@app.get("/")
def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Truck ETA API is running"}

@app.get("/health")
def health_check():
    """Detailed health check endpoint."""
    try:
        # Check if ban areas CSV exists
        from eta_estimator import BAN_CSV
        import os
        ban_csv_exists = os.path.exists(BAN_CSV)
        
        return {
            "status": "ok",
            "ban_csv_exists": ban_csv_exists,
            "ban_csv_path": BAN_CSV,
            "ors_api_key_configured": bool(os.getenv("ORS_API_KEY"))
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }