# GPS Road Matching with HMM and Viterbi

## Slide 1 — GPS Road Matching

**Hidden Markov Model and Viterbi decoding**  
Full-stack demonstration · Connaught Place, New Delhi

## Slide 2 — Why map matching

- GPS fixes are noisy and may fall between roads.
- Nearest-road choices at each point can jump between nearby streets.
- Route continuity helps identify a plausible sequence of road segments.

## Slide 3 — System overview

Browser map and GPS/file input → Flask API → HMM matcher → GeoJSON response → Leaflet route visualization.

Road candidates and route distances come from the cached road graph. Matching is implemented in this project rather than delegated to a map-matching API.

## Slide 4 — Hidden states and observations

- Observation: latitude and longitude at time *t*.
- Hidden state: a candidate directed road segment near that observation.
- Candidate generation: spatial index with a configurable radius and fallbacks.

## Slide 5 — HMM scoring

- **Emission:** Gaussian likelihood from GPS-to-road perpendicular distance.
- **Transition:** exponential likelihood from the difference between GPS displacement and shortest-path road distance.
- Parameters: GPS noise σ and transition scale β.

## Slide 6 — Viterbi decoding

1. Initialize candidate scores with emission likelihoods.
2. For each next candidate, select the predecessor with the best accumulated transition and emission score.
3. Store scores in log space to avoid numerical underflow.
4. Backtrack from the best final candidate to recover the route.

## Slide 7 — Full-stack application

- Flask serves the web page, JSON API, uploads, sample traces, and live matching.
- Leaflet displays raw GPS observations, road graph, and matched route.
- Global place search, street/topographic basemaps, and a location control.
- Load roads for a zoomed viewport to match beyond the included Delhi region.
- CSV and GPX uploads share the same matching engine.
- Browser geolocation supports live GPS with user permission.

## Slide 8 — Data and evaluation

- Synthetic route around Connaught Place, New Delhi.
- Seeded noisy, clean, noisy-canyon, sparse, and GPX traces generated from reference waypoints.
- Report mean, median, maximum error, RMSE, and share within a 15 m threshold.
- Synthetic evaluation is reproducible but does not establish field performance.

## Slide 9 — Run and extend

`py -3 -m venv .venv` → activate → `python -m pip install -r backend\requirements.txt` → `python scripts\generate_test_data.py` → `python -m backend.app`

Open `http://127.0.0.1:5000`. Search anywhere, zoom in to a viewport no wider than 20 km per side, then load roads in view; this needs server internet access. Live GPS requires a secure context and browser permission.

## Slide 10 — Limitations and next steps

- Synthetic ground truth follows simplified hand-authored waypoints.
- Results depend on the cached road data and chosen σ, β, and candidate radius.
- Improve timestamp/heading-aware transitions and preserve exact segment direction in route stitching.
- Validate with a real GPS trace and independent surveyed reference.
