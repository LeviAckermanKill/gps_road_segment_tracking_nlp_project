# System Architecture

> GPS Road Matching with HMM and Viterbi Decoding

---

## 1. Architecture Overview

The GPS Map Matching system follows a **three-tier architecture** comprising a browser-based frontend, a Flask REST API backend, and an HMM map-matching engine operating over a cached OpenStreetMap road network. The design prioritises separation of concerns: the frontend handles user interaction and visualisation; the API layer manages request validation, file parsing, and response formatting; and the core engine encapsulates all probabilistic inference logic.

| Layer | Responsibility | Key Technologies |
|---|---|---|
| **Presentation** | Interactive map, GPS input, trace upload, result display | Leaflet.js, HTML5 Geolocation API |
| **API** | REST endpoints, request validation, file parsing, error handling | Flask, Flask-CORS |
| **Engine** | HMM formulation, Viterbi decoding, candidate generation, scoring | NumPy, SciPy (cKDTree), NetworkX |
| **Data** | Road network graph, spatial index, GeoJSON cache | OSMnx, NetworkX GraphML, GeoJSON |

---

## 2. Component Diagram

```mermaid
flowchart TB
    subgraph Frontend["Frontend (Browser)"]
        UI["index.html"]
        MapJS["map.js — Leaflet Map"]
        AppJS["app.js — API Client"]
        GpsJS["gps.js — Geolocation"]
        CSS["style.css"]
    end

    subgraph Backend["Backend (Flask Server)"]
        APP["app.py — Flask Application"]
        CFG["config.py — Configuration"]
        subgraph HMMEngine["HMM Engine"]
            MODEL["model.py — HMMMapMatcher"]
            VIT["viterbi.py — Viterbi Decoder"]
            RN["road_network.py — RoadNetwork"]
            UTILS["utils.py — Utilities"]
        end
    end

    subgraph DataLayer["Data Layer"]
        CACHE["road_network.geojson"]
        GRAPHML["road_network.graphml"]
        SAMPLES["Sample Traces (CSV/GPX)"]
        GT["ground_truth.csv"]
    end

    subgraph External["External Services"]
        OSM["OpenStreetMap / OSMnx"]
        NOM["Nominatim Geocoder"]
        TILES["Tile Servers (OSM/Esri)"]
    end

    UI --> MapJS
    UI --> AppJS
    UI --> GpsJS
    AppJS -->|"HTTP JSON/Multipart"| APP
    GpsJS -->|"Live GPS fixes"| APP
    MapJS -->|"Tile requests"| TILES
    APP --> CFG
    APP --> MODEL
    MODEL --> VIT
    MODEL --> RN
    MODEL --> UTILS
    RN --> CACHE
    RN --> GRAPHML
    RN -->|"Download if no cache"| OSM
    APP -->|"Geocode proxy"| NOM
    APP --> SAMPLES
    APP --> GT
```

---

## 3. Request–Response Sequence: `/api/match`

```mermaid
sequenceDiagram
    actor User
    participant Browser as Browser (Leaflet)
    participant Flask as Flask API
    participant Validator as Request Validator
    participant Matcher as HMMMapMatcher
    participant KDTree as Spatial Index (cKDTree)
    participant RoadNet as RoadNetwork (NetworkX)
    participant Viterbi as Viterbi Decoder

    User->>Browser: Upload trace or select sample
    Browser->>Flask: POST /api/match {trace: [...]}
    Flask->>Validator: _validate_trace(trace)
    Validator-->>Flask: OK / 400 error

    Flask->>Matcher: matcher.match(normalised_trace)

    loop For each GPS observation t
        Matcher->>KDTree: get_nearest_segments(lat, lon, radius)
        KDTree-->>Matcher: Candidate road segments
        Note over Matcher: Radius fallback if empty: 2.5×, then 500 m
        Matcher->>Matcher: emission_log_probability(point, segment)
    end

    Matcher->>Viterbi: viterbi(states, emissions, transition_fn)

    Note over Viterbi: Initialise trellis at t=0

    loop t = 1 … T−1
        loop For each candidate state
            Viterbi->>RoadNet: transition_log_prob_fn → route_distance
            RoadNet->>RoadNet: Dijkstra shortest path
            RoadNet-->>Viterbi: log transition score
            Note over Viterbi: V[t][s] = max over prev {V[t-1][p] + trans + emit}
        end
    end

    Note over Viterbi: Backtrack from best final state

    Viterbi-->>Matcher: ViterbiResult(path, log_prob, trellis)

    Matcher->>Matcher: Project points, build GeoJSON LineString
    Matcher->>Matcher: Compute statistics (RMSE, mean/max error)
    Matcher-->>Flask: MatchResult

    Flask-->>Browser: 200 {status, result (GeoJSON), statistics, time_ms}
    Browser->>Browser: Render matched route + snapped points on map
    Browser-->>User: Display route overlay and statistics panel
```

---

## 4. Data Flow Diagram

```mermaid
flowchart LR
    subgraph Input["Input Sources"]
        CSV["CSV File"]
        GPX["GPX File"]
        JSON["JSON Trace"]
        GEO["Browser Geolocation"]
    end

    subgraph Parsing["Parsing & Validation"]
        P1["parse_gps_csv()"]
        P2["parse_gpx()"]
        P3["_validate_trace()"]
        P4["_trace_dicts_to_tuples()"]
    end

    subgraph Matching["HMM Map Matching"]
        CG["Candidate Generation"]
        EM["Emission Scoring"]
        TR["Transition Scoring"]
        VD["Viterbi Decoding"]
        PP["Point Projection"]
    end

    subgraph Network["Road Network"]
        KD["KD-Tree Spatial Index"]
        DK["Dijkstra Router"]
        SG["Segment Geometry"]
    end

    subgraph Output["Output"]
        GJ["GeoJSON FeatureCollection"]
        ST["Statistics Dict"]
        ME["Evaluation Metrics"]
    end

    CSV --> P1
    GPX --> P2
    JSON --> P3
    GEO --> P3
    P1 --> P3
    P2 --> P3
    P3 --> P4
    P4 --> CG
    CG --> KD
    KD --> CG
    CG --> EM
    EM --> VD
    TR --> VD
    CG --> TR
    TR --> DK
    DK --> TR
    VD --> PP
    PP --> SG
    SG --> PP
    PP --> GJ
    PP --> ST
    ST --> ME
```

---

## 5. HMM Decoding Pipeline

```mermaid
flowchart TD
    Z["GPS Observations z₁, z₂, …, zT"] --> SI["Spatial Index Query (cKDTree)"]
    SI --> CAND["Candidate Road Segments per Observation"]
    CAND --> FALL{"Candidates found?"}
    FALL -->|"Yes"| EMIT["Compute Emission Log-Probabilities"]
    FALL -->|"No"| EXP["Expand Radius: 2.5× → 500 m fallback"]
    EXP --> EMIT

    EMIT --> INIT["Initialise Viterbi Trellis at t=0"]
    INIT --> FWD["Forward Recursion: t = 1 … T−1"]

    FWD --> TRANS["Compute Transition Log-Probabilities"]
    TRANS --> GCD["Haversine great-circle distance"]
    TRANS --> DIJKSTRA["Dijkstra shortest-path road distance"]
    GCD --> DIFF["|d_gps − d_route| / β"]
    DIJKSTRA --> DIFF

    DIFF --> SCORE["V[t][s] = max_p { V[t−1][p] + log A(p→s) + log B(s|zₜ) }"]
    SCORE --> STORE["Store best predecessor pointer"]

    STORE --> TERM["Termination: select best final state"]
    TERM --> BACK["Backtrack predecessor pointers"]
    BACK --> SEQ["Optimal state sequence: s₁*, s₂*, …, sT*"]

    SEQ --> PROJ["Project GPS points onto matched segments"]
    PROJ --> GEOM["Build continuous LineString geometry"]
    GEOM --> GEOJSON["Serialise GeoJSON FeatureCollection"]
    GEOJSON --> STATS["Compute displacement statistics"]
```

---

## 6. Module Dependency Diagram

```mermaid
flowchart TD
    APP["backend/app.py"] --> CONFIG["backend/config.py"]
    APP --> MODEL["backend/hmm/model.py"]
    APP --> RN["backend/hmm/road_network.py"]
    APP --> UTILS["backend/hmm/utils.py"]

    MODEL --> VIT["backend/hmm/viterbi.py"]
    MODEL --> RN
    MODEL --> UTILS

    RN --> UTILS

    MODEL -.->|"numpy, shapely"| EXT1["External: NumPy, Shapely"]
    RN -.->|"networkx, scipy, shapely"| EXT2["External: NetworkX, SciPy, Shapely"]
    RN -.->|"osmnx (optional download)"| EXT3["External: OSMnx"]
    UTILS -.->|"numpy, gpxpy"| EXT4["External: NumPy, gpxpy"]
    APP -.->|"flask, flask-cors"| EXT5["External: Flask, Flask-CORS"]

    subgraph Frontend["frontend/"]
        IDX["index.html"]
        MAPJS["js/map.js"]
        APPJS["js/app.js"]
        GPSJS["js/gps.js"]
        STYLE["css/style.css"]
    end

    IDX --> MAPJS
    IDX --> APPJS
    IDX --> GPSJS
    IDX --> STYLE
    APPJS -->|"fetch() calls"| APP
    GPSJS -->|"fetch() calls"| APP

    subgraph Tests["tests/"]
        T1["test_viterbi.py"]
        T2["test_hmm_model.py"]
        T3["test_road_network.py"]
        T4["test_utils.py"]
        T5["test_api.py"]
        T6["test_integration.py"]
        CONF["conftest.py"]
    end

    T1 --> VIT
    T2 --> MODEL
    T3 --> RN
    T4 --> UTILS
    T5 --> APP
    T6 --> APP
```

---

## 7. Technology Stack

| Category | Technology | Version / Notes |
|---|---|---|
| **Language** | Python 3.10+ | Type-annotated throughout |
| **Web Framework** | Flask | Lightweight WSGI framework |
| **CORS** | Flask-CORS | Cross-origin support for frontend |
| **Graph Library** | NetworkX | Road network graph + Dijkstra routing |
| **Spatial Index** | SciPy `cKDTree` | Fast nearest-neighbour queries on sampled road points |
| **Geometry** | Shapely | LineString operations, point projection |
| **Numerical** | NumPy | Log-space arithmetic, statistics |
| **OSM Download** | OSMnx | Optional; downloads road networks from OpenStreetMap |
| **GPX Parsing** | gpxpy | Optional; parses GPX track files |
| **Frontend Map** | Leaflet.js 1.9+ | Interactive map with tile layers and GeoJSON overlays |
| **Tile Providers** | OpenStreetMap, Esri | Street and topographic basemaps |
| **Place Search** | Nominatim | Geocoding API (proxied + rate-limited through Flask) |
| **Serialisation** | GeoJSON, GraphML | Road network persistence formats |
| **Testing** | pytest | Unit, integration, and API tests |
| **Configuration** | Environment variables | Via `Config` class with sensible defaults |

---

## 8. Key Design Decisions

### 8.1 Log-Space Computation

All probabilities are stored and accumulated as **log-probabilities**. This prevents floating-point underflow that would otherwise occur when multiplying many small probabilities across a long GPS trace. The Viterbi recurrence operates entirely in log space: addition replaces multiplication, and `max` replaces summation.

### 8.2 Gaussian Emission + Exponential Transition

The emission model uses a **1-D Gaussian** over the perpendicular distance from the GPS point to the road segment. The transition model uses an **exponential distribution** over the absolute difference between the great-circle GPS displacement and the shortest-path road distance. This formulation follows the approach of **Newson & Krumm (2009)**, which has become the standard probabilistic map-matching baseline.

### 8.3 Candidate Radius Fallback Strategy

Candidate generation uses a three-tier fallback to avoid empty candidate sets:

1. **Primary radius** (default 50 m) — cKDTree ball query
2. **Expanded radius** (2.5× = 125 m) — if no candidates found
3. **Emergency radius** (500 m, top 3 nearest) — last resort

This ensures the Viterbi trellis always has at least one state per time step, preventing path breaks.

### 8.4 Dijkstra Routing with Caching

Transition probabilities require the shortest-path road distance between candidate segments. This is computed via **Dijkstra's algorithm** on the NetworkX `MultiDiGraph`. Results are cached in a dictionary (bounded at 20,000 entries) to avoid redundant computations when the same segment pair appears at multiple time steps.

### 8.5 Undirected Fallback for Disconnected Graphs

If the directed shortest path between two segments is infinite (unreachable), the system falls back to an **undirected graph** search with a distance penalty (+50 m). This handles situations where one-way street topology would otherwise prevent valid transitions.

### 8.6 Spatial Indexing via Sampled Points

Rather than indexing road segment bounding boxes, the system **samples points along each segment** at 20 m intervals and builds a cKDTree over all sampled points. This provides accurate nearest-segment queries even for long, curved road geometries that a bounding-box approach would over-approximate.

### 8.7 Stateless API with Server-Side Graph

The Flask API is **stateless** with respect to client sessions. The road network graph is loaded once at startup (from cache or OSMnx download) and shared across all requests. Live GPS matching uses a client-managed point buffer with a server-side sliding window of 50 points, avoiding server-side session state.

### 8.8 GeoJSON as the Universal Exchange Format

All spatial data — road networks, matched routes, snapped points — is exchanged as **GeoJSON** between backend and frontend. This provides native compatibility with Leaflet's `L.geoJSON` layer and standard geospatial tooling.

---

## 9. API Endpoint Summary

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health and road network status |
| `POST` | `/api/match` | Match a JSON GPS trace |
| `POST` | `/api/upload` | Upload and match a CSV or GPX file |
| `POST` | `/api/match-live` | Incremental live GPS matching (sliding window) |
| `GET` | `/api/sample-data` | List available sample trace names |
| `GET` | `/api/sample-data/<name>` | Load a specific sample trace |
| `GET` | `/api/road-network` | Retrieve current road network as GeoJSON |
| `POST` | `/api/road-network/load` | Load OSM roads for a map viewport (bbox) |
| `GET` | `/api/geocode?q=...` | Place search via Nominatim proxy |
| `GET` | `/api/metrics` | Evaluation metrics against ground truth |

---

## 10. Directory Structure

```
GPS Road Matching Project/
├── backend/
│   ├── app.py              # Flask application factory and API routes
│   ├── config.py           # Centralised configuration (env overrides)
│   ├── __init__.py
│   ├── cache/              # Cached road network files
│   │   ├── road_network.geojson
│   │   └── road_network.graphml
│   └── hmm/
│       ├── __init__.py
│       ├── model.py        # HMMMapMatcher, MatchResult
│       ├── viterbi.py      # Viterbi decoder (log-space DP)
│       ├── road_network.py # RoadNetwork, RoadSegment, spatial index
│       └── utils.py        # Haversine, projections, CSV/GPX parsing, metrics
├── frontend/
│   ├── index.html          # Main web page
│   ├── css/style.css       # Application styles
│   └── js/
│       ├── app.js          # API client and UI logic
│       ├── map.js          # Leaflet map initialisation and layers
│       └── gps.js          # Browser Geolocation API wrapper
├── data/
│   ├── sample_trace_delhi.csv
│   ├── sample_trace_clean.csv
│   ├── sample_trace_noisy.csv
│   ├── sample_trace_sparse.csv
│   ├── sample_gpx_trace.gpx
│   └── ground_truth.csv
├── presentation/
│   └── SLIDES.md
├── docs/
│   ├── ARCHITECTURE.md     # (this file)
│   └── PROJECT_REPORT.md
├── scripts/
│   └── generate_test_data.py
├── tests/
│   ├── conftest.py
│   ├── test_viterbi.py
│   ├── test_hmm_model.py
│   ├── test_road_network.py
│   ├── test_utils.py
│   ├── test_api.py
│   └── test_integration.py
├── pyproject.toml
├── run.ps1
└── README.md
```
