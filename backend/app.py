"""
GPS Map Matching — Flask Backend API

Serves the frontend static files and provides REST endpoints for
GPS trace map-matching using a Hidden Markov Model.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import threading
import time
import traceback
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.config import Config
from backend.hmm.model import HMMMapMatcher
from backend.hmm.road_network import RoadNetwork
from backend.hmm.utils import calculate_metrics, haversine_distance, parse_gps_csv, parse_gpx

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("map_match")

# ---------------------------------------------------------------------------
# Application factory helpers
# ---------------------------------------------------------------------------

# Module-level shared state
_road_network: Optional[RoadNetwork] = None
_matcher: Optional[HMMMapMatcher] = None
_geocode_cache: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
_geocode_lock = threading.Lock()
_geocode_last_request = 0.0


def _load_road_network() -> Optional[RoadNetwork]:
    """Load the road network from cache or download via OSMnx."""
    cache_path = os.path.join(Config.CACHE_DIR, "road_network.geojson")

    rn = RoadNetwork()

    # Try loading from cache first
    if os.path.isfile(cache_path):
        try:
            rn.load_from_geojson(cache_path)
            logger.info("Road network loaded from cache (%s)", cache_path)
            return rn
        except Exception:
            logger.warning("Failed to load cached road network; will re-download.")

    # Download from OSMnx
    try:
        logger.info("Downloading road network for '%s' via OSMnx …", Config.DEFAULT_CITY)
        rn.load_from_osm(Config.DEFAULT_CITY)
        # Persist to cache
        rn.save_to_geojson(cache_path)
        logger.info("Road network downloaded and cached (%s)", cache_path)
        return rn
    except Exception as exc:
        logger.error("Could not download road network: %s", exc)
        return None


def _build_matcher(road_network: RoadNetwork) -> HMMMapMatcher:
    """Instantiate an HMMMapMatcher from config values."""
    return HMMMapMatcher(
        road_network=road_network,
        sigma=Config.GPS_NOISE_STD,
        beta=Config.BETA,
        max_candidate_radius=Config.CANDIDATE_RADIUS,
    )


# ---------------------------------------------------------------------------
# Error-response helpers
# ---------------------------------------------------------------------------

def _error_response(message: str, code: int) -> tuple[Response, int]:
    """Return a standard JSON error response."""
    return jsonify({"status": "error", "message": message, "code": code}), code


def _validate_trace(trace: Any) -> Optional[str]:
    """
    Validate a list of GPS points.

    Returns an error message string if invalid, else ``None``.
    """
    if not isinstance(trace, list):
        return "trace must be a list of point objects"
    if len(trace) < 2:
        return "trace must contain at least 2 points"
    for idx, pt in enumerate(trace):
        if not isinstance(pt, dict):
            return f"point at index {idx} is not an object"
        if "lat" not in pt or "lon" not in pt:
            return f"point at index {idx} missing 'lat' or 'lon'"
        try:
            lat = float(pt["lat"])
            lon = float(pt["lon"])
        except (TypeError, ValueError):
            return f"point at index {idx} has non-numeric lat/lon"
        if not math.isfinite(lat) or not math.isfinite(lon):
            return f"point at index {idx} must have finite coordinates"
        if not (-90.0 <= lat <= 90.0):
            return f"point at index {idx} has latitude out of range (-90..90)"
        if not (-180.0 <= lon <= 180.0):
            return f"point at index {idx} has longitude out of range (-180..180)"
    return None


def _trace_dicts_to_tuples(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalise trace dicts — ensure numeric lat/lon and optional timestamp."""
    normalised: List[Dict[str, Any]] = []
    for pt in trace:
        entry: Dict[str, Any] = {
            "lat": float(pt["lat"]),
            "lon": float(pt["lon"]),
        }
        if "timestamp" in pt and pt["timestamp"] is not None:
            entry["timestamp"] = str(pt["timestamp"])
        normalised.append(entry)
    return normalised


# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    """Create and configure the Flask application."""
    global _road_network, _matcher  # noqa: PLW0603

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_UPLOAD_SIZE
    CORS(app)

    # Ensure directories exist
    os.makedirs(Config.CACHE_DIR, exist_ok=True)
    os.makedirs(Config.DATA_DIR, exist_ok=True)

    # Load road network on startup
    _road_network = _load_road_network()
    if _road_network is not None:
        _matcher = _build_matcher(_road_network)
        logger.info("HMM matcher ready.")
    else:
        logger.warning("Road network unavailable — matching endpoints will return 503.")

    # -------------------------------------------------------------------
    # Error handlers
    # -------------------------------------------------------------------
    @app.errorhandler(400)
    def bad_request(error: Any) -> tuple[Response, int]:
        message = getattr(error, "description", "Bad request")
        return _error_response(str(message), 400)

    @app.errorhandler(404)
    def not_found(error: Any) -> tuple[Response, int]:
        message = getattr(error, "description", "Resource not found")
        return _error_response(str(message), 404)

    @app.errorhandler(413)
    def payload_too_large(error: Any) -> tuple[Response, int]:
        return _error_response("Uploaded file exceeds the 16 MB limit", 413)

    @app.errorhandler(500)
    def internal_error(error: Any) -> tuple[Response, int]:
        logger.error("Unhandled 500: %s", error)
        return _error_response("Internal server error", 500)

    # -------------------------------------------------------------------
    # Frontend routes
    # -------------------------------------------------------------------
    @app.route("/")
    def serve_index() -> Response:
        """Serve the main frontend page."""
        index_path = os.path.join(Config.FRONTEND_DIR, "index.html")
        if not os.path.isfile(index_path):
            return _error_response("Frontend not found. Place index.html in the frontend/ directory.", 404)[0]
        return send_from_directory(Config.FRONTEND_DIR, "index.html")

    @app.route("/<path:filename>")
    def serve_static(filename: str) -> Response:
        """Serve frontend static assets (CSS, JS, images, etc.)."""
        full_path = os.path.join(Config.FRONTEND_DIR, filename)
        if not os.path.isfile(full_path):
            return _error_response(f"File not found: {filename}", 404)[0]
        return send_from_directory(Config.FRONTEND_DIR, filename)

    # -------------------------------------------------------------------
    # API: Health
    # -------------------------------------------------------------------
    @app.route("/api/health", methods=["GET"])
    def api_health() -> tuple[Response, int]:
        """Return service health and road-network status."""
        loaded = _road_network is not None
        segments = 0
        if loaded:
            try:
                geojson_data = _road_network.get_edges_geojson()
                if isinstance(geojson_data, dict) and "features" in geojson_data:
                    segments = len(geojson_data["features"])
                elif isinstance(geojson_data, str):
                    import json as _json
                    parsed = _json.loads(geojson_data)
                    segments = len(parsed.get("features", []))
            except Exception:
                segments = 0

        return jsonify({
            "status": "ok",
            "road_network_loaded": loaded,
            "segments_count": segments,
        }), 200

    # -------------------------------------------------------------------
    # API: Match (JSON body)
    # -------------------------------------------------------------------
    @app.route("/api/match", methods=["POST"])
    def api_match() -> tuple[Response, int]:
        """Run map matching on a JSON GPS trace."""
        if _matcher is None or _road_network is None:
            return _error_response("Road network not loaded. Service unavailable.", 503)

        body = request.get_json(silent=True)
        if body is None:
            return _error_response("Request body must be valid JSON", 400)

        trace = body.get("trace")
        if trace is None:
            return _error_response("Missing 'trace' field in request body", 400)

        err = _validate_trace(trace)
        if err is not None:
            return _error_response(err, 400)

        normalised = _trace_dicts_to_tuples(trace)

        try:
            t0 = time.perf_counter()
            result = _matcher.match(normalised)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
        except Exception as exc:
            logger.error("Matching failed: %s\n%s", exc, traceback.format_exc())
            return _error_response(f"Map matching failed: {exc}", 500)

        return jsonify({
            "status": "success",
            "result": result.to_geojson(),
            "statistics": result.statistics,
            "processing_time_ms": round(elapsed_ms, 2),
        }), 200

    # -------------------------------------------------------------------
    # API: Upload (CSV / GPX file)
    # -------------------------------------------------------------------
    @app.route("/api/upload", methods=["POST"])
    def api_upload() -> tuple[Response, int]:
        """Accept a CSV or GPX file upload, parse it, and run matching."""
        if _matcher is None or _road_network is None:
            return _error_response("Road network not loaded. Service unavailable.", 503)

        if "file" not in request.files:
            return _error_response("No file part in the request. Use field name 'file'.", 400)

        uploaded = request.files["file"]
        if uploaded.filename is None or uploaded.filename == "":
            return _error_response("No file selected for upload", 400)

        filename: str = uploaded.filename
        ext = os.path.splitext(filename)[1].lower()

        if ext not in (".csv", ".gpx"):
            return _error_response(
                f"Unsupported file format '{ext}'. Upload a .csv or .gpx file.",
                400,
            )

        try:
            raw_bytes = uploaded.read()
            # Write to a temporary file so the parsers can read it
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as fh:
                fh.write(raw_bytes)
                tmp_path = fh.name
            try:
                trace = parse_gps_csv(tmp_path) if ext == ".csv" else parse_gpx(tmp_path)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        except Exception as exc:
            logger.error("File parsing failed: %s\n%s", exc, traceback.format_exc())
            return _error_response(f"Could not parse uploaded file: {exc}", 400)

        if not trace or len(trace) < 2:
            return _error_response("Parsed trace contains fewer than 2 valid points", 400)

        try:
            t0 = time.perf_counter()
            result = _matcher.match(trace)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
        except Exception as exc:
            logger.error("Matching failed: %s\n%s", exc, traceback.format_exc())
            return _error_response(f"Map matching failed: {exc}", 500)

        return jsonify({
            "status": "success",
            "result": result.to_geojson(),
            "statistics": result.statistics,
            "processing_time_ms": round(elapsed_ms, 2),
        }), 200

    # -------------------------------------------------------------------
    # API: Sample data catalogue & retrieval
    # -------------------------------------------------------------------
    SAMPLE_NAMES: List[str] = [
        "sample_trace_delhi",
        "sample_trace_clean",
        "sample_trace_noisy",
        "sample_trace_sparse",
    ]

    @app.route("/api/sample-data", methods=["GET"])
    def api_sample_list() -> tuple[Response, int]:
        """List available sample trace names."""
        return jsonify({"samples": SAMPLE_NAMES}), 200

    @app.route("/api/sample-data/<string:name>", methods=["GET"])
    def api_sample_get(name: str) -> tuple[Response, int]:
        """Load a named sample CSV from the data/ directory."""
        if name not in SAMPLE_NAMES:
            return _error_response(
                f"Unknown sample '{name}'. Available: {', '.join(SAMPLE_NAMES)}",
                404,
            )

        csv_path = os.path.join(Config.DATA_DIR, f"{name}.csv")
        if not os.path.isfile(csv_path):
            return _error_response(f"Sample file not found on disk: {name}.csv", 404)

        try:
            trace = parse_gps_csv(csv_path)
        except Exception as exc:
            logger.error("Failed to parse sample %s: %s", name, exc)
            return _error_response(f"Could not parse sample file: {exc}", 500)

        # Convert to list-of-dicts for the response
        points: List[Dict[str, Any]] = []
        for pt in trace:
            if isinstance(pt, dict):
                points.append(pt)
            else:
                # Assume it's a tuple/list (lat, lon) or (lat, lon, timestamp)
                entry: Dict[str, Any] = {"lat": pt[0], "lon": pt[1]}
                if len(pt) > 2:
                    entry["timestamp"] = str(pt[2])
                points.append(entry)

        return jsonify({"name": name, "trace": points}), 200

    # -------------------------------------------------------------------
    # API: Live / incremental matching
    # -------------------------------------------------------------------
    @app.route("/api/match-live", methods=["POST"])
    def api_match_live() -> tuple[Response, int]:
        """
        Incremental matching: accumulate points and match a recent window.

        Expects JSON: {
            "points": [...previous accumulated points...],
            "new_point": {"lat": float, "lon": float, "timestamp": str}
        }
        """
        if _matcher is None or _road_network is None:
            return _error_response("Road network not loaded. Service unavailable.", 503)

        body = request.get_json(silent=True)
        if body is None:
            return _error_response("Request body must be valid JSON", 400)

        new_point = body.get("new_point")
        if new_point is None:
            return _error_response("Missing 'new_point' in request body", 400)
        if not isinstance(new_point, dict):
            return _error_response("new_point must be an object", 400)

        if "lat" not in new_point or "lon" not in new_point:
            return _error_response("new_point must contain 'lat' and 'lon'", 400)

        try:
            new_pt: Dict[str, Any] = {
                "lat": float(new_point["lat"]),
                "lon": float(new_point["lon"]),
            }
            if "timestamp" in new_point and new_point["timestamp"] is not None:
                new_pt["timestamp"] = str(new_point["timestamp"])
        except (TypeError, ValueError):
            return _error_response("new_point has non-numeric lat/lon", 400)

        # Build accumulated trace
        existing_points: List[Dict[str, Any]] = body.get("points", [])
        if not isinstance(existing_points, list):
            return _error_response("points must be a list", 400)

        all_points = list(existing_points) + [new_pt]
        # Use a sliding window of the most recent 50 points for performance
        WINDOW_SIZE = 50
        window = all_points[-WINDOW_SIZE:]

        if len(window) < 2:
            # Reuse coordinate validation while allowing the first fix to wait for a pair.
            err = _validate_trace([new_pt, new_pt])
            if err is not None:
                return _error_response(err, 400)
            return jsonify({
                "status": "success",
                "result": None,
                "statistics": {},
                "processing_time_ms": 0.0,
                "total_points": len(all_points),
                "message": "Need at least 2 points for matching",
            }), 200

        err = _validate_trace(window)
        if err is not None:
            return _error_response(err, 400)

        normalised = _trace_dicts_to_tuples(window)

        try:
            t0 = time.perf_counter()
            result = _matcher.match(normalised)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
        except Exception as exc:
            logger.error("Live matching failed: %s\n%s", exc, traceback.format_exc())
            return _error_response(f"Live map matching failed: {exc}", 500)

        return jsonify({
            "status": "success",
            "result": result.to_geojson(),
            "statistics": result.statistics,
            "processing_time_ms": round(elapsed_ms, 2),
            "total_points": len(all_points),
        }), 200

    # -------------------------------------------------------------------
    # API: Road network GeoJSON
    # -------------------------------------------------------------------
    @app.route("/api/road-network", methods=["GET"])
    def api_road_network() -> tuple[Response, int]:
        """Return the loaded road network as GeoJSON for map display."""
        if _road_network is None:
            return _error_response("Road network not loaded", 503)

        try:
            geojson_data = _road_network.get_edges_geojson()
            # get_edges_geojson may return a dict or a JSON string
            if isinstance(geojson_data, str):
                return Response(geojson_data, mimetype="application/geo+json")
            return jsonify(geojson_data), 200
        except Exception as exc:
            logger.error("Failed to serialise road network: %s", exc)
            return _error_response(f"Could not retrieve road network: {exc}", 500)

    @app.route("/api/road-network/load", methods=["POST"])
    def api_load_road_network() -> tuple[Response, int]:
        """Load OSM roads for the current map viewport, anywhere in the world."""
        global _road_network, _matcher  # noqa: PLW0603
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _error_response("Request body must be a JSON object", 400)
        try:
            north, south = float(body["north"]), float(body["south"])
            east, west = float(body["east"]), float(body["west"])
        except (KeyError, TypeError, ValueError):
            return _error_response("Provide numeric north, south, east, and west bounds", 400)
        if not all(math.isfinite(v) for v in (north, south, east, west)):
            return _error_response("Map bounds must be finite numbers", 400)
        if not (-90 <= south < north <= 90) or not (-180 <= west < east <= 180):
            return _error_response("Map bounds are invalid or cross the antimeridian", 400)
        if haversine_distance(south, west, north, west) > Config.MAX_NETWORK_LOAD_SIDE_M or haversine_distance(
            south, west, south, east
        ) > Config.MAX_NETWORK_LOAD_SIDE_M:
            return _error_response(
                f"Zoom in until each viewport side is no longer than {Config.MAX_NETWORK_LOAD_SIDE_M // 1000} km",
                400,
            )
        try:
            network = RoadNetwork()
            network.load_from_bbox(north, south, east, west)
            if not len(network):
                return _error_response("No drivable roads were found in this map area", 404)
            _road_network = network
            _matcher = _build_matcher(network)
        except Exception as exc:
            logger.error("Could not load roads for viewport: %s", exc)
            return _error_response(
                "Could not load roads. Check the location and server internet connection, then try again.",
                502,
            )
        return jsonify({
            "status": "success",
            "segments_count": len(network),
            "message": "Road data loaded for this area. Matching now uses this map region.",
        }), 200

    @app.route("/api/geocode", methods=["GET"])
    def api_geocode() -> tuple[Response, int]:
        """Search for a place through a cached and rate-limited Nominatim proxy."""
        global _geocode_last_request  # noqa: PLW0603
        query = request.args.get("q", "").strip()
        if len(query) < 3 or len(query) > 160:
            return _error_response("Search text must be between 3 and 160 characters", 400)
        cache_key = query.casefold()
        with _geocode_lock:
            if cache_key in _geocode_cache:
                _geocode_cache.move_to_end(cache_key)
                return jsonify({"results": _geocode_cache[cache_key]}), 200
            delay = 1.05 - (time.monotonic() - _geocode_last_request)
            if delay > 0:
                time.sleep(delay)
            params = urllib.parse.urlencode({"format": "jsonv2", "limit": 6, "q": query})
            url = f"{Config.GEOCODER_URL}?{params}"
            req = urllib.request.Request(url, headers={
                "User-Agent": Config.GEOCODER_USER_AGENT,
                "Accept": "application/json",
            })
            _geocode_last_request = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=12) as response:
                    results = json.loads(response.read().decode("utf-8"))
                if not isinstance(results, list):
                    raise ValueError("Geocoder returned an invalid response")
            except Exception as exc:
                logger.warning("Place search request failed: %s", exc)
                return _error_response("Place search is temporarily unavailable. Try again later.", 502)
            _geocode_cache[cache_key] = results
            while len(_geocode_cache) > 200:
                _geocode_cache.popitem(last=False)
        return jsonify({"results": results}), 200

    # -------------------------------------------------------------------
    # API: Evaluation metrics
    # -------------------------------------------------------------------
    @app.route("/api/metrics", methods=["GET"])
    def api_metrics() -> tuple[Response, int]:
        """
        Return evaluation metrics if a ground-truth file exists.

        Looks for data/ground_truth.csv alongside the most-recently matched result.
        """
        if _matcher is None or _road_network is None:
            return _error_response("Road network not loaded. Service unavailable.", 503)

        gt_path = os.path.join(Config.DATA_DIR, "ground_truth.csv")
        if not os.path.isfile(gt_path):
            return _error_response(
                "No ground truth file found. Place ground_truth.csv in the data/ directory.",
                404,
            )

        sample_path = os.path.join(Config.DATA_DIR, "sample_trace_delhi.csv")
        if not os.path.isfile(sample_path):
            return _error_response(
                "No sample trace found to compare against ground truth.",
                404,
            )

        try:
            trace = parse_gps_csv(sample_path)
            result = _matcher.match(trace)

            ground_truth = parse_gps_csv(gt_path)

            metrics = calculate_metrics(result, ground_truth)
        except Exception as exc:
            logger.error("Metrics computation failed: %s\n%s", exc, traceback.format_exc())
            return _error_response(f"Could not compute metrics: {exc}", 500)

        return jsonify({
            "status": "success",
            "metrics": metrics,
        }), 200

    # -------------------------------------------------------------------
    # Request hooks — timing
    # -------------------------------------------------------------------
    @app.before_request
    def _start_timer() -> None:
        request._start_time = time.perf_counter()  # type: ignore[attr-defined]

    @app.after_request
    def _add_timing_header(response: Response) -> Response:
        start: Optional[float] = getattr(request, "_start_time", None)
        if start is not None:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            response.headers["X-Processing-Time-Ms"] = f"{elapsed_ms:.2f}"
        return response

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info("Starting GPS Map Matching server on http://127.0.0.1:%d", port)
    app.run(host="0.0.0.0", port=port, debug=debug)
