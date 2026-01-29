# Truck ETA Calculator with Ban Zone Management

A sophisticated truck routing and ETA (Estimated Time of Arrival) calculator that considers temporal ban zones, maximum driving hours, and realistic transit delays. Built for logistics operations in regions with time-based vehicle restrictions.

## Features

- **Temporal Ban Zone Support**: Automatically accounts for city-specific time-based truck restrictions
- **Driving Hour Limits**: Enforces maximum driving hours (default 14 hours per 24-hour period) with automatic rest stops
- **Realistic Routing**: Uses OpenRouteService for accurate route calculations with configurable vehicle speeds
- **Transit Time Adjustment**: Applies configurable multiplier for realistic delay modeling
- **Batch Processing**: Process multiple trips in a single API call
- **FastAPI Backend**: RESTful API with health checks and detailed error handling
- **CLI Support**: Command-line interface for single trip calculations

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd bantime
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your OpenRouteService API key:
```bash
export ORS_API_KEY="your_api_key_here"
```

Get a free API key from [OpenRouteService](https://openrouteservice.org/).

## Configuration Files

- **polygons.geojson**: GeoJSON file containing city ban zone polygon boundaries
- **ban_times.json**: JSON file defining ban times by city and day of week
- **ban_times.csv**: (Legacy) CSV format for ban time definitions

## Usage

### FastAPI Server

Start the server:
```bash
uvicorn eta_api:app --reload
```

The API will be available at `http://localhost:8000`.

#### API Endpoints

**POST /eta**
Calculate ETAs for multiple trips (accepts list of trip dictionaries).

Headers:
- `X-ORS-API-Key`: OpenRouteService API key (optional if set in environment)
- `X-Ban-Radius-Km`: Override ban area radius in km (optional)
- `X-Vehicle-Speed-Kmph`: Override vehicle speed in km/h (optional)
- `X-Max-Driving-Hours`: Maximum driving hours per 24h window (default: 14)
- `X-Transit-Time-Multiplier`: Multiplier for transit time delays (default: 1.3)

Request body:
```json
[
  {
    "key": "trip_001",
    "vehicle_key": "truck_01",
    "start_time": "2026-01-24T08:00:00",
    "start_lat": 24.7136,
    "start_lng": 46.6753,
    "end_lat": 21.3891,
    "end_lng": 39.8579
  }
]
```

Response:
```json
{
  "trip_001": {
    "eta": "2026-01-25 14:30",
    "delays": [
      {
        "city": "Jeddah",
        "wait": "4.5 hours",
        "ban_start": "2026-01-24 18:00",
        "ban_end": "2026-01-25 06:00",
        "lat": 21.3891,
        "lon": 39.8579
      }
    ]
  }
}
```

**POST /eta/batch**
Calculate ETAs for batch of trips (accepts structured request body).

**GET /**
Health check endpoint.

**GET /health**
Detailed health check with configuration status.

### Command Line Interface

Calculate ETA for a single trip:
```bash
python eta_cli.py \
  --start-lat 24.7136 \
  --start-lon 46.6753 \
  --end-lat 21.3891 \
  --end-lon 39.8579 \
  --start-datetime "2026-01-24T08:00:00" \
  --ors-api-key "your_api_key"
```

Process multiple trips from CSV:
```bash
python eta_cli.py --batch-csv trips.csv --ors-api-key "your_api_key"
```

## How It Works

### ETA Calculation Process

1. **Route Planning**: Fetches optimal route from OpenRouteService API
2. **Ban Zone Detection**: Checks route waypoints against defined ban area polygons
3. **Temporal Validation**: Verifies if arrival times conflict with ban periods
4. **Rest Stop Insertion**: Adds mandatory rest periods when driving limits are reached
5. **Delay Calculation**: Computes wait times for ban zones and rest requirements
6. **Schedule Generation**: Creates detailed timeline with all stops and delays

### Ban Zone Logic

- Ban zones are defined as geographic polygons in `polygons.geojson`
- Ban times are specified per city, day of week, and time range in `ban_times.json`
- When a vehicle would arrive at a ban zone during restricted hours, it waits at the previous location until the ban ends
- Overnight bans (e.g., 18:00 to 06:00) are properly handled

### Driving Hours Enforcement

- Tracks cumulative driving time in rolling 24-hour windows
- Automatically inserts rest stops when driving limits would be exceeded
- Rest duration: (24 - max_driving_hours) to reset the 24-hour window
- Default maximum: 14 hours of driving per 24-hour period

### Transit Time Multiplier

The `transit_time_multiplier` (default: 1.3) accounts for:
- Traffic congestion
- Fuel stops
- Border crossings
- Minor delays
- Real-world routing inefficiencies

## Project Structure

```
bantime/
├── eta_api.py              # FastAPI server and endpoints
├── eta_estimator.py        # Core ETA calculation logic
├── eta_cli.py              # Command-line interface
├── ban_area_utils.py       # Ban zone polygon and time management
├── polygons.geojson        # City ban zone boundaries
├── ban_times.json          # Ban time schedules by city
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## API Response Format

The detailed schedule includes:
- **start**: Trip start event with location and time
- **ban**: Each ban zone wait with duration and location
- **end**: Trip completion with final ETA

Each event includes:
- `vehicle_key`: Vehicle identifier
- `key`: Trip identifier
- `event`: Event type (start/ban/end)
- `time`: Event timestamp
- `lat`, `lon`: Geographic coordinates
- `city`: City name (for ban events)
- `wait_hours`: Wait duration (for ban events)
- `ban_arrival`, `ban_departure`: Ban period timestamps

## Example Scenario

A truck departing Riyadh at 08:00 heading to Jeddah:
1. Route calculated via OpenRouteService
2. System detects Jeddah ban zone on route
3. Checks if arrival time falls during ban period
4. If yes, schedules wait at safe location before entering
5. Calculates total delay and final ETA
6. Returns complete schedule with all stops

## Dependencies

- `openrouteservice`: Routing API client
- `fastapi`: Web framework
- `uvicorn`: ASGI server
- `shapely`: Geometric operations
- `python-dateutil`: Timezone handling
- `pandas`: Data processing (for batch operations)
- `folium`: Map visualization

## Environment Variables

- `ORS_API_KEY`: OpenRouteService API key (required)
