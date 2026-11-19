<<<<<<< HEAD
<<<<<<< HEAD
=======
>>>>>>> 44436c6 (Initial GPS HMM map matching project)
# GPS Road Matching with HMM and Viterbi

A full-stack demonstration that reconstructs a likely road route from noisy GPS samples. The backend represents nearby directed road segments as hidden states, scores GPS-to-road distances with a Gaussian emission model, scores route-distance versus GPS-distance with an exponential transition model, and decodes the most likely sequence with log-space Viterbi. It serves a Leaflet map for CSV/GPX uploads, supplied traces, and browser live GPS.

## Features

- Flask JSON API and static frontend; no road-snapping service is used for matching.
- Worldwide street/topographic map layers, place search, and browser location.
- Load an OSM road graph for a zoomed viewport, then run the HMM in that area.
- The included Connaught Place road graph is loaded at startup and works offline from the cache.
- Sample traces and synthetic ground truth for Connaught Place, New Delhi.
- HMM candidate generation, emission and transition log probabilities, Viterbi decoding, and GeoJSON route output.
- CSV and GPX upload, live browser geolocation, error responses, and evaluation metrics.
- Tests and project report/architecture diagrams in `docs/`.

## Run locally

Requires Python 3.10 or newer. From this directory:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
python scripts\generate_test_data.py
python -m backend.app
```

Open `http://127.0.0.1:5000`. The server loads the included cached road network. To match somewhere else, search for a place, zoom until each viewport side is no longer than 8 km, and choose **Load roads in view**. That action downloads drivable roads through OSMnx and switches the running matcher to that area. Successful region downloads are cached under `backend/cache/regions/` for later offline reuse. It requires server internet access and an available OpenStreetMap extract; public Overpass services can be slow or temporarily unavailable. The app tries a configured fallback after the primary endpoint fails. Set `MAP_MATCH_CITY`, `GPS_NOISE_STD`, `CANDIDATE_RADIUS`, `BETA`, `PORT`, `FLASK_DEBUG`, `OSMNX_OVERPASS_URL`, `OSMNX_FALLBACK_OVERPASS_URL`, `OSMNX_REQUEST_TIMEOUT`, and `MAX_NETWORK_LOAD_SIDE_M` to adjust configuration. Browser live GPS generally requires HTTPS or localhost and user permission.

Run automated tests with `python -m pytest -q`. API health is available at `/api/health`; `road_network_loaded` should be true before matching.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Service/network readiness |
| GET | `/api/road-network` | Cached road graph as GeoJSON |
| POST | `/api/road-network/load` | Load a graph for `{ "north", "south", "east", "west" }` bounds (8 km maximum per side) |
| GET | `/api/sample-data` | Available sample identifiers |
| GET | `/api/sample-data/<name>` | Load a sample trace |
| POST | `/api/match` | Match JSON `{ "trace": [{"lat": 28.63, "lon": 77.21}] }` |
| POST | `/api/upload` | Match multipart CSV or GPX field `file` |
| POST | `/api/match-live` | Incrementally match `{ "points": [...], "new_point": {...} }` |
| GET | `/api/metrics` | Evaluate the Delhi sample against the synthetic reference |

CSV accepts `lat`/`latitude`, `lon`/`lng`/`longitude`, and optional timestamp/accuracy columns. Coordinates are WGS84 decimal degrees. Upload size is limited to 16 MiB.

Place search uses a backend proxy to OpenStreetMap Nominatim with a one-request-per-second process-local limit and a 200-query cache. `GEOCODER_URL` and `GEOCODER_USER_AGENT` let the operator switch providers or identify the application. Map layers use OpenStreetMap/OpenTopoMap tiles. Follow their attribution and usage policies when deploying publicly. Loading another road region replaces the active in-memory matching network for all users of that server process; restarting returns to the bundled Delhi network.

## Evaluation notes

The provided reference is simulated from hand-authored waypoints; it is useful for reproducible software evaluation, not evidence of field performance. Metrics compare point positions in order and include mean, median, max, RMSE, and fraction within 15 m. The map-matching result's displacement-to-road statistics are diagnostics, not ground-truth accuracy. See [the report](docs/PROJECT_REPORT.md) for methodology and limitations.

## Project map

- `backend/hmm/`: road graph, HMM matcher, utilities, and Viterbi decoder
- `backend/app.py`: Flask routes and error handling
- `frontend/`: Leaflet UI, file/sample input, live GPS
- `data/`: traces, ground truth, cached map under backend/cache
- `scripts/generate_test_data.py`: deterministic synthetic dataset generator
- `tests/`: unit and API tests
- `docs/`: report and architecture diagrams
- `presentation/`: editable slide source in Markdown
<<<<<<< HEAD
=======
# gps_road_segment_tracking_nlp_project
GPS map-matching using a first-order HMM: hidden states are road segments, observations are noisy GPS points. Transition and emission probabilities score road transitions and point-to-road likelihood; Viterbi decodes the most likely route. It mirrors HMM POS tagging and targets ≥90% point accuracy.
>>>>>>> 3f866d96c8048106de177b3026a1e72b98ede743
=======
>>>>>>> 44436c6 (Initial GPS HMM map matching project)
