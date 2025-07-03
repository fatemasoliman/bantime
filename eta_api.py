from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
from eta_estimator import estimate_trip

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
    class Args:
        pass
    args = Args()
    args.start_lat = req.start_lat
    args.start_lon = req.start_lon
    args.end_lat = req.end_lat
    args.end_lon = req.end_lon
    args.start_datetime = req.start_datetime
    args.ors_api_key = req.ors_api_key or os.getenv("ORS_API_KEY")
    # Call the estimator (returns schedule, last event is 'end')
    schedule = estimate_trip(args)
    eta_event = next((e for e in schedule if e['event'] == 'end'), None)
    if not eta_event:
        raise HTTPException(status_code=500, detail="ETA calculation failed.")
    return {"eta": eta_event['time']}
