"""
Utility functions for GPS map matching.

Provides haversine distance calculations, point-to-line projections,
GPS trace preprocessing (interpolation, smoothing), file parsing (CSV, GPX),
noise generation for testing, and accuracy metric computation.

All distance functions use the WGS84 ellipsoid approximation and return
results in meters unless otherwise noted.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EARTH_RADIUS_M: float = 6_371_000.0  # mean Earth radius in meters


# ---------------------------------------------------------------------------
# Distance helpers
# ---------------------------------------------------------------------------


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Compute the great-circle distance between two points on the Earth
    using the Haversine formula.

    Parameters
    ----------
    lat1, lon1 : float
        Latitude and longitude of the first point in **degrees**.
    lat2, lon2 : float
        Latitude and longitude of the second point in **degrees**.

    Returns
    -------
    float
        Distance in **meters**.

    Notes
    -----
    Accuracy is typically within 0.3 % for distances up to several hundred
    kilometres. For sub-metre precision, use Vincenty or Karney's method on
    the WGS84 ellipsoid.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2.0) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c


def _point_to_segment_distance_and_proj(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> Tuple[float, float, float]:
    """
    Compute the minimum distance from point P (px, py) to the line segment
    A-B in a *local* metre-scale coordinate system, and return the nearest
    point on the segment.

    Returns (distance, nearest_x, nearest_y) in the **same** coordinate
    system as the inputs.
    """
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay

    ab_sq = abx * abx + aby * aby
    if ab_sq < 1e-18:
        # A and B are the same point
        dx = px - ax
        dy = py - ay
        return math.sqrt(dx * dx + dy * dy), ax, ay

    t = (apx * abx + apy * aby) / ab_sq
    t = max(0.0, min(1.0, t))

    near_x = ax + t * abx
    near_y = ay + t * aby
    dx = px - near_x
    dy = py - near_y
    return math.sqrt(dx * dx + dy * dy), near_x, near_y


def _latlon_to_local(lat: float, lon: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """Convert (lat, lon) to a local (x_m, y_m) relative to a reference."""
    y = math.radians(lat - ref_lat) * EARTH_RADIUS_M
    x = (math.radians(lon - ref_lon)
         * EARTH_RADIUS_M
         * math.cos(math.radians(ref_lat)))
    return x, y


def _local_to_latlon(x: float, y: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """Convert local (x_m, y_m) back to (lat, lon) in degrees."""
    lat = ref_lat + math.degrees(y / EARTH_RADIUS_M)
    lon = ref_lon + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(ref_lat))))
    return lat, lon


def point_to_line_distance(point_lat: float, point_lon: float,
                           line_coords: Sequence[Tuple[float, float]]) -> float:
    """
    Minimum distance from a point to a polyline, in metres.

    Parameters
    ----------
    point_lat, point_lon : float
        Latitude / longitude of the query point (degrees).
    line_coords : sequence of (lon, lat) tuples
        Vertices of the polyline. **Note**: follows the GeoJSON / Shapely
        convention of ``(longitude, latitude)`` ordering.

    Returns
    -------
    float
        Distance in metres.

    Raises
    ------
    ValueError
        If *line_coords* has fewer than 2 vertices.
    """
    if len(line_coords) < 2:
        raise ValueError("line_coords must contain at least 2 vertices.")

    # Convert everything into a local metre-scale frame centred on the point.
    ref_lat, ref_lon = point_lat, point_lon
    px, py = 0.0, 0.0  # the query point in local coords

    best_dist = float("inf")
    prev_x: Optional[float] = None
    prev_y: Optional[float] = None

    for coord_lon, coord_lat in line_coords:
        cx, cy = _latlon_to_local(coord_lat, coord_lon, ref_lat, ref_lon)
        if prev_x is not None:
            d, _, _ = _point_to_segment_distance_and_proj(px, py, prev_x, prev_y, cx, cy)
            if d < best_dist:
                best_dist = d
        prev_x, prev_y = cx, cy

    return best_dist


def project_point_to_line(point_lat: float, point_lon: float,
                          line_coords: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """
    Project a point onto the nearest location of a polyline.

    Parameters
    ----------
    point_lat, point_lon : float
        Latitude / longitude of the query point (degrees).
    line_coords : sequence of (lon, lat) tuples
        Vertices of the polyline (longitude-first ordering).

    Returns
    -------
    tuple[float, float]
        ``(lat, lon)`` of the nearest point on the polyline.

    Raises
    ------
    ValueError
        If *line_coords* has fewer than 2 vertices.
    """
    if len(line_coords) < 2:
        raise ValueError("line_coords must contain at least 2 vertices.")

    ref_lat, ref_lon = point_lat, point_lon
    px, py = 0.0, 0.0

    best_dist = float("inf")
    best_nx: float = 0.0
    best_ny: float = 0.0

    prev_x: Optional[float] = None
    prev_y: Optional[float] = None

    for coord_lon, coord_lat in line_coords:
        cx, cy = _latlon_to_local(coord_lat, coord_lon, ref_lat, ref_lon)
        if prev_x is not None:
            d, nx, ny = _point_to_segment_distance_and_proj(px, py, prev_x, prev_y, cx, cy)
            if d < best_dist:
                best_dist = d
                best_nx = nx
                best_ny = ny
        prev_x, prev_y = cx, cy

    return _local_to_latlon(best_nx, best_ny, ref_lat, ref_lon)


# ---------------------------------------------------------------------------
# GPS trace preprocessing
# ---------------------------------------------------------------------------


def _parse_timestamp(ts: Any) -> datetime:
    """
    Best-effort timestamp parser.  Accepts datetime objects, epoch floats/ints,
    and ISO-8601 strings.
    """
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        # Try ISO format with or without 'Z'
        ts_clean = ts.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(ts_clean)
        except ValueError:
            pass
        # Try common formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    raise ValueError(f"Cannot parse timestamp: {ts!r}")


def interpolate_gps_trace(trace: List[Dict[str, Any]],
                          max_gap_seconds: float = 10.0) -> List[Dict[str, Any]]:
    """
    Linearly interpolate GPS points when the gap between consecutive
    measurements exceeds *max_gap_seconds*.

    Parameters
    ----------
    trace : list of dict
        Each dict must contain ``'lat'``, ``'lon'``, and ``'timestamp'``.
    max_gap_seconds : float
        Maximum allowed gap (seconds) before interpolated points are inserted.

    Returns
    -------
    list of dict
        The augmented trace with interpolated points inserted.
    """
    if len(trace) < 2:
        return list(trace)

    result: List[Dict[str, Any]] = [trace[0]]

    for i in range(1, len(trace)):
        t_prev = _parse_timestamp(trace[i - 1]["timestamp"])
        t_curr = _parse_timestamp(trace[i]["timestamp"])
        gap = (t_curr - t_prev).total_seconds()

        if gap > max_gap_seconds and gap > 0:
            n_interp = int(math.ceil(gap / max_gap_seconds)) - 1
            for j in range(1, n_interp + 1):
                frac = j / (n_interp + 1)
                interp_lat = trace[i - 1]["lat"] + frac * (trace[i]["lat"] - trace[i - 1]["lat"])
                interp_lon = trace[i - 1]["lon"] + frac * (trace[i]["lon"] - trace[i - 1]["lon"])
                interp_ts = t_prev.timestamp() + frac * gap
                pt: Dict[str, Any] = {
                    "lat": interp_lat,
                    "lon": interp_lon,
                    "timestamp": datetime.fromtimestamp(interp_ts, tz=timezone.utc).isoformat(),
                    "interpolated": True,
                }
                result.append(pt)

        result.append(trace[i])

    return result


def smooth_gps_trace(trace: List[Dict[str, Any]],
                     window_size: int = 3) -> List[Dict[str, Any]]:
    """
    Apply a simple moving-average filter to the lat/lon coordinates of a
    GPS trace.

    Parameters
    ----------
    trace : list of dict
        Each dict must contain ``'lat'`` and ``'lon'``.
    window_size : int
        Number of points in the moving-average window (must be odd and ≥ 1).

    Returns
    -------
    list of dict
        Smoothed copy of the trace (original dicts are not mutated).
    """
    if window_size < 1:
        raise ValueError("window_size must be >= 1")
    if window_size % 2 == 0:
        window_size += 1  # make it odd for symmetric window

    n = len(trace)
    if n == 0:
        return []

    lats = np.array([p["lat"] for p in trace], dtype=np.float64)
    lons = np.array([p["lon"] for p in trace], dtype=np.float64)

    half = window_size // 2
    smoothed: List[Dict[str, Any]] = []

    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        new_pt = dict(trace[i])  # shallow copy
        new_pt["lat"] = float(np.mean(lats[lo:hi]))
        new_pt["lon"] = float(np.mean(lons[lo:hi]))
        smoothed.append(new_pt)

    return smoothed


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------


def parse_gps_csv(filepath: str) -> List[Dict[str, Any]]:
    """
    Parse a CSV file with columns ``latitude, longitude, timestamp``
    and optional ``accuracy``.

    The first row is treated as a header.  Column matching is
    case-insensitive and tolerant of common aliases (``lat`` / ``latitude``,
    ``lng`` / ``lon`` / ``longitude``, ``time`` / ``timestamp``).

    Parameters
    ----------
    filepath : str
        Path to the CSV file.

    Returns
    -------
    list of dict
        Each dict has keys ``'lat'``, ``'lon'``, ``'timestamp'``, and
        optionally ``'accuracy'``.
    """
    # Map common header names to our canonical keys
    _aliases: Dict[str, str] = {
        "latitude": "lat",
        "true_lat": "lat",
        "lat": "lat",
        "longitude": "lon",
        "true_lon": "lon",
        "lon": "lon",
        "lng": "lon",
        "long": "lon",
        "timestamp": "timestamp",
        "time": "timestamp",
        "datetime": "timestamp",
        "accuracy": "accuracy",
        "acc": "accuracy",
        "hdop": "accuracy",
    }

    trace: List[Dict[str, Any]] = []

    try:
        with open(filepath, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                return trace

            # Build column mapping
            col_map: Dict[str, str] = {}
            for col in reader.fieldnames:
                canon = _aliases.get(col.strip().lower())
                if canon is not None:
                    col_map[col] = canon

            if "lat" not in col_map.values() or "lon" not in col_map.values():
                raise ValueError(
                    f"CSV must contain latitude and longitude columns. "
                    f"Found headers: {reader.fieldnames}"
                )

            for row_num, row in enumerate(reader, start=2):
                try:
                    pt: Dict[str, Any] = {}
                    for raw_col, canon_key in col_map.items():
                        val = row.get(raw_col, "").strip()
                        if canon_key in ("lat", "lon", "accuracy"):
                            pt[canon_key] = float(val)
                        else:
                            pt[canon_key] = val
                    trace.append(pt)
                except (ValueError, KeyError) as exc:
                    raise ValueError(
                        f"Error parsing row {row_num}: {exc}"
                    ) from exc

    except FileNotFoundError as exc:
        raise FileNotFoundError(f"GPS CSV file not found: {filepath}") from exc

    return trace


def parse_gpx(filepath: str) -> List[Dict[str, Any]]:
    """
    Parse a GPX file and extract track points.

    Uses the ``gpxpy`` library. If ``gpxpy`` is not installed the function
    raises an ``ImportError`` with an installation hint.

    Parameters
    ----------
    filepath : str
        Path to the ``.gpx`` file.

    Returns
    -------
    list of dict
        Each dict has keys ``'lat'``, ``'lon'``, ``'timestamp'``,
        and optionally ``'elevation'``.
    """
    try:
        import gpxpy  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "gpxpy is required to parse GPX files. "
            "Install it with:  pip install gpxpy"
        ) from exc

    trace: List[Dict[str, Any]] = []

    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            gpx = gpxpy.parse(fh)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"GPX file not found: {filepath}") from exc
    except Exception as exc:
        raise ValueError(f"Failed to parse GPX file '{filepath}': {exc}") from exc

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                pt: Dict[str, Any] = {
                    "lat": point.latitude,
                    "lon": point.longitude,
                    "timestamp": (
                        point.time.isoformat() if point.time else ""
                    ),
                }
                if point.elevation is not None:
                    pt["elevation"] = point.elevation
                trace.append(pt)

    return trace


# ---------------------------------------------------------------------------
# Noise generation (for testing / simulation)
# ---------------------------------------------------------------------------


def generate_noisy_trace(clean_trace: List[Dict[str, Any]],
                         noise_std_m: float = 20.0,
                         seed: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Add Gaussian noise to a clean GPS trace for testing / benchmarking.

    The noise is applied independently to latitude and longitude, converted
    from metres to degrees using the local scale factor.

    Parameters
    ----------
    clean_trace : list of dict
        Each dict must contain ``'lat'`` and ``'lon'``.
    noise_std_m : float
        Standard deviation of the additive noise in **metres**.
    seed : int, optional
        Random seed for reproducibility.

    Returns
    -------
    list of dict
        A new trace with noise added (original dicts are not mutated).
    """
    rng = np.random.default_rng(seed)
    noisy: List[Dict[str, Any]] = []

    for pt in clean_trace:
        new_pt = dict(pt)
        lat = pt["lat"]

        # metres -> degrees
        dlat_per_m = 1.0 / (EARTH_RADIUS_M * math.pi / 180.0)
        dlon_per_m = 1.0 / (EARTH_RADIUS_M * math.cos(math.radians(lat)) * math.pi / 180.0)

        new_pt["lat"] = lat + rng.normal(0, noise_std_m) * dlat_per_m
        new_pt["lon"] = pt["lon"] + rng.normal(0, noise_std_m) * dlon_per_m
        noisy.append(new_pt)

    return noisy


# ---------------------------------------------------------------------------
# Accuracy metrics
# ---------------------------------------------------------------------------


def calculate_metrics(
    matched_points: Any,
    ground_truth_points: Any,
) -> Dict[str, float]:
    """
    Calculate accuracy metrics between matched and ground-truth points.

    Accepts MatchResult, list of (lat, lon) tuples, or list of dicts with 'lat'/'lon'.
    """
    # Normalize matched points
    if hasattr(matched_points, "matched_points"):
        m_pts = [(float(p[0]), float(p[1])) for p in matched_points.matched_points]
    elif isinstance(matched_points, list):
        m_pts = []
        for p in matched_points:
            if isinstance(p, dict):
                m_pts.append((float(p.get("lat", p.get("latitude", 0))), float(p.get("lon", p.get("longitude", 0)))))
            elif isinstance(p, (tuple, list)):
                m_pts.append((float(p[0]), float(p[1])))
    else:
        m_pts = []

    # Normalize ground truth points
    if hasattr(ground_truth_points, "matched_points"):
        g_pts = [(float(p[0]), float(p[1])) for p in ground_truth_points.matched_points]
    elif isinstance(ground_truth_points, list):
        g_pts = []
        for p in ground_truth_points:
            if isinstance(p, dict):
                lat_val = p.get("true_lat", p.get("lat", p.get("latitude", 0)))
                lon_val = p.get("true_lon", p.get("lon", p.get("longitude", 0)))
                g_pts.append((float(lat_val), float(lon_val)))
            elif isinstance(p, (tuple, list)):
                g_pts.append((float(p[0]), float(p[1])))
    else:
        g_pts = []

    # Align lengths if slightly mismatched
    min_len = min(len(m_pts), len(g_pts))
    if min_len == 0:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "rmse": 0.0,
            "median_error": 0.0,
            "max_error": 0.0,
            "mean_error": 0.0,
            "count": 0,
        }

    m_pts = m_pts[:min_len]
    g_pts = g_pts[:min_len]

    THRESHOLD_M = 15.0  # metres — common threshold for "correct" match

    errors: List[float] = []
    within_threshold = 0

    for (mlat, mlon), (glat, glon) in zip(m_pts, g_pts):
        d = haversine_distance(mlat, mlon, glat, glon)
        errors.append(d)
        if d <= THRESHOLD_M:
            within_threshold += 1

    n = len(errors)
    err_arr = np.array(errors, dtype=np.float64)

    precision = within_threshold / n if n > 0 else 0.0
    recall = within_threshold / n if n > 0 else 0.0
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "rmse": round(float(np.sqrt(np.mean(err_arr ** 2))), 4),
        "median_error": round(float(np.median(err_arr)), 4),
        "max_error": round(float(np.max(err_arr)), 4),
        "mean_error": round(float(np.mean(err_arr)), 4),
        "count": n,
    }
