from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
from eta_estimator import calculate_eta_with_bans

app = FastAPI()

class ETARequest(BaseModel):
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    start_datetime: str
    ors_api_key: str = None  # optional, fallback to env

@app.post("/eta")
def get_eta(req: ETARequest):
    """Calculate ETA with ban area considerations."""
    try:
        # Get API key from request or environment
        api_key = req.ors_api_key or os.getenv("ORS_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=400, 
                detail="OpenRouteService API key is required. Provide in request or set ORS_API_KEY environment variable."
            )
        
        # Calculate ETA using the unified function
        result = calculate_eta_with_bans(
            req.start_lat, req.start_lon,
            req.end_lat, req.end_lon,
            req.start_datetime, api_key
        )
        
        # Find the end event for ETA
        eta_event = next((e for e in result['schedule'] if e['event'] == 'end'), None)
        if not eta_event:
            raise HTTPException(status_code=500, detail="ETA calculation failed - no end event found.")
        
        # Format delays for API response
        delays = []
        for d in result['delays']:
            wait_minutes = int((d['wait'].total_seconds() + 59) // 60)  # Round up to nearest minute
            delays.append({
                "city": d["city"],
                "wait_minutes": wait_minutes,
                "ban_arrival": d["eta_at_ban"].strftime('%Y-%m-%d %H:%M'),
                "ban_departure": (d["eta_at_ban"] + d["wait"]).strftime('%Y-%m-%d %H:%M'),
                "ban_lat": d["stop_lat"],
                "ban_lon": d["stop_lon"]
            })
        
        return {
            "eta": eta_event['time'],
            "schedule": result['schedule'],
            "delays": delays
        }
        
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Configuration file not found: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ETA calculation failed: {str(e)}")

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