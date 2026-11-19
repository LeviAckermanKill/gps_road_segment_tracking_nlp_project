# GPS Road Segment Tracking with HMM and Viterbi

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open <http://localhost:5000>.

## Features
- Genuine first-order hidden Markov model
- Viterbi decoding over road-segment states
- Log-domain emission and transition scoring
- Leaflet interactive map
- JSON/CSV file upload
- Browser Geolocation API live tracking
- Sample London road network and GPS trace
- Input validation and HTTP error responses
- Mean error, RMSE, maximum error and matched-point metrics

## API

`GET /api/health` — health check.

`GET /api/network` — GeoJSON road network.

`POST /api/match` — JSON body:

```json
{"points":[{"lat":51.5050,"lon":-0.0902},{"lat":51.5058,"lon":-0.0892}]}
```

CSV upload expects `lat,lon` columns.

## Tests

```bash
pytest -q
```

## Formulae
Emission: `-0.5*(distance/sigma)^2 - log(sigma*sqrt(2*pi))`

Transition: `-abs(projected_route_distance-gps_distance)/beta`

Final route is recovered with the highest log probability in Viterbi DP.
