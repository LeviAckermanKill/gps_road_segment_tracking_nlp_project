"""
Comprehensive tests for GPS map matching utility functions.

Covers: haversine distance, point-to-line distance / projection,
CSV and GPX parsing, trace interpolation, smoothing, noise generation,
and accuracy metric computation.
"""

import math
import os
import tempfile

import pytest
import numpy as np

from backend.hmm.utils import (
    EARTH_RADIUS_M,
    calculate_metrics,
    generate_noisy_trace,
    haversine_distance,
    interpolate_gps_trace,
    parse_gps_csv,
    parse_gpx,
    point_to_line_distance,
    project_point_to_line,
    smooth_gps_trace,
)


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

class TestHaversineDistance:

    def test_zero_distance_for_same_point(self):
        assert haversine_distance(28.6, 77.2, 28.6, 77.2) == pytest.approx(0.0)

    def test_symmetry(self):
        d1 = haversine_distance(28.6, 77.2, 28.7, 77.3)
        d2 = haversine_distance(28.7, 77.3, 28.6, 77.2)
        assert d1 == pytest.approx(d2, rel=1e-9)

    def test_known_distance_equator(self):
        # 1 degree of longitude at the equator ≈ 111.32 km
        d = haversine_distance(0.0, 0.0, 0.0, 1.0)
        assert 111_000 < d < 112_000

    def test_known_distance_pole(self):
        # 1 degree of latitude ≈ 111 km everywhere
        d = haversine_distance(89.0, 0.0, 90.0, 0.0)
        assert 110_000 < d < 112_000

    def test_negative_coordinates(self):
        d = haversine_distance(-33.8688, 151.2093, -33.8688, 151.2093)
        assert d == pytest.approx(0.0)

    def test_antipodal_points(self):
        d = haversine_distance(0.0, 0.0, 0.0, 180.0)
        expected = math.pi * EARTH_RADIUS_M
        assert d == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Point-to-line distance and projection
# ---------------------------------------------------------------------------

class TestPointToLineDistance:

    def test_point_on_line_has_zero_distance(self):
        line = [(77.20, 28.63), (77.22, 28.63)]
        d = point_to_line_distance(28.63, 77.21, line)
        assert d < 1.0  # less than 1 metre

    def test_perpendicular_distance(self):
        # Horizontal line; point directly above midpoint
        line = [(77.20, 28.63), (77.22, 28.63)]
        d = point_to_line_distance(28.6305, 77.21, line)
        expected = haversine_distance(28.63, 77.21, 28.6305, 77.21)
        assert d == pytest.approx(expected, rel=0.05)

    def test_raises_on_single_vertex(self):
        with pytest.raises(ValueError, match="at least 2"):
            point_to_line_distance(28.63, 77.21, [(77.21, 28.63)])


class TestProjectPointToLine:

    def test_projection_onto_midpoint(self):
        line = [(77.20, 28.63), (77.22, 28.63)]
        plat, plon = project_point_to_line(28.6305, 77.21, line)
        assert plat == pytest.approx(28.63, abs=0.001)
        assert plon == pytest.approx(77.21, abs=0.001)

    def test_projection_onto_endpoint(self):
        line = [(77.20, 28.63), (77.22, 28.63)]
        plat, plon = project_point_to_line(28.63, 77.19, line)
        # Should snap to the start of the line
        assert plon == pytest.approx(77.20, abs=0.001)

    def test_raises_on_single_vertex(self):
        with pytest.raises(ValueError, match="at least 2"):
            project_point_to_line(28.63, 77.21, [(77.21, 28.63)])


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

class TestParseCSV:

    def _write_csv(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return f.name

    def test_standard_header(self):
        path = self._write_csv("latitude,longitude,timestamp\n28.63,77.21,2024-01-15T10:00:00\n")
        try:
            trace = parse_gps_csv(path)
            assert len(trace) == 1
            assert trace[0]["lat"] == pytest.approx(28.63)
            assert trace[0]["lon"] == pytest.approx(77.21)
        finally:
            os.unlink(path)

    def test_alternative_headers_lat_lng(self):
        path = self._write_csv("lat,lng,time\n28.63,77.21,2024-01-15T10:00:00\n")
        try:
            trace = parse_gps_csv(path)
            assert len(trace) == 1
            assert "lon" in trace[0]
        finally:
            os.unlink(path)

    def test_missing_lat_lon_raises(self):
        path = self._write_csv("x,y,z\n1,2,3\n")
        try:
            with pytest.raises(ValueError, match="latitude and longitude"):
                parse_gps_csv(path)
        finally:
            os.unlink(path)

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_gps_csv("/nonexistent/path/file.csv")

    def test_bom_handling(self):
        """UTF-8 BOM should not break header detection."""
        path = self._write_csv("\ufefflatitude,longitude,timestamp\n28.63,77.21,2024-01-15T10:00:00\n")
        try:
            trace = parse_gps_csv(path)
            assert len(trace) == 1
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# GPX parsing
# ---------------------------------------------------------------------------

class TestParseGPX:

    def _write_gpx(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".gpx", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return f.name

    def test_simple_gpx(self):
        gpx = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="28.63" lon="77.21"><time>2024-01-15T10:00:00Z</time></trkpt>
    <trkpt lat="28.64" lon="77.22"><time>2024-01-15T10:00:05Z</time></trkpt>
  </trkseg></trk>
</gpx>"""
        path = self._write_gpx(gpx)
        try:
            trace = parse_gpx(path)
            assert len(trace) == 2
            assert trace[0]["lat"] == pytest.approx(28.63)
        finally:
            os.unlink(path)

    def test_gpx_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_gpx("/nonexistent.gpx")


# ---------------------------------------------------------------------------
# Trace preprocessing
# ---------------------------------------------------------------------------

class TestInterpolateTrace:

    def test_inserts_points_for_large_gap(self):
        trace = [
            {"lat": 28.63, "lon": 77.21, "timestamp": "2024-01-15T10:00:00"},
            {"lat": 28.64, "lon": 77.22, "timestamp": "2024-01-15T10:01:00"},  # 60s gap
        ]
        result = interpolate_gps_trace(trace, max_gap_seconds=10.0)
        assert len(result) > 2

    def test_no_interpolation_for_small_gap(self):
        trace = [
            {"lat": 28.63, "lon": 77.21, "timestamp": "2024-01-15T10:00:00"},
            {"lat": 28.64, "lon": 77.22, "timestamp": "2024-01-15T10:00:05"},
        ]
        result = interpolate_gps_trace(trace, max_gap_seconds=10.0)
        assert len(result) == 2

    def test_single_point_unchanged(self):
        trace = [{"lat": 28.63, "lon": 77.21, "timestamp": "2024-01-15T10:00:00"}]
        assert len(interpolate_gps_trace(trace)) == 1


class TestSmoothTrace:

    def test_smoothing_reduces_variance(self):
        trace = [
            {"lat": 28.630, "lon": 77.210},
            {"lat": 28.635, "lon": 77.215},
            {"lat": 28.630, "lon": 77.210},
            {"lat": 28.635, "lon": 77.215},
            {"lat": 28.630, "lon": 77.210},
        ]
        smoothed = smooth_gps_trace(trace, window_size=3)
        raw_var = np.var([p["lat"] for p in trace])
        smooth_var = np.var([p["lat"] for p in smoothed])
        assert smooth_var < raw_var

    def test_empty_trace(self):
        assert smooth_gps_trace([]) == []

    def test_even_window_size_is_made_odd(self):
        trace = [{"lat": 28.63, "lon": 77.21}] * 5
        result = smooth_gps_trace(trace, window_size=4)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Noise generation
# ---------------------------------------------------------------------------

class TestGenerateNoisyTrace:

    def test_output_length_matches_input(self):
        clean = [{"lat": 28.63, "lon": 77.21}] * 10
        noisy = generate_noisy_trace(clean, noise_std_m=20.0, seed=42)
        assert len(noisy) == 10

    def test_noise_is_applied(self):
        clean = [{"lat": 28.63, "lon": 77.21}]
        noisy = generate_noisy_trace(clean, noise_std_m=50.0, seed=1)
        assert noisy[0]["lat"] != clean[0]["lat"] or noisy[0]["lon"] != clean[0]["lon"]

    def test_seed_reproducibility(self):
        clean = [{"lat": 28.63, "lon": 77.21}] * 5
        a = generate_noisy_trace(clean, noise_std_m=20.0, seed=99)
        b = generate_noisy_trace(clean, noise_std_m=20.0, seed=99)
        assert all(a[i]["lat"] == b[i]["lat"] for i in range(5))


# ---------------------------------------------------------------------------
# Accuracy metrics
# ---------------------------------------------------------------------------

class TestCalculateMetrics:

    def test_perfect_match(self):
        matched = [(28.6, 77.2), (28.6001, 77.2)]
        truth = [
            {"true_lat": 28.6, "true_lon": 77.2},
            {"true_lat": 28.6001, "true_lon": 77.2},
        ]
        metrics = calculate_metrics(matched, truth)
        assert metrics["count"] == 2
        assert metrics["rmse"] == pytest.approx(0.0)
        assert metrics["f1"] == pytest.approx(1.0)

    def test_empty_input_returns_zero_count(self):
        assert calculate_metrics([], [])["count"] == 0

    def test_mismatched_lengths_truncates(self):
        matched = [(28.6, 77.2)] * 5
        truth = [{"lat": 28.6, "lon": 77.2}] * 3
        metrics = calculate_metrics(matched, truth)
        assert metrics["count"] == 3

    def test_all_metrics_keys_present(self):
        matched = [(28.6, 77.2)]
        truth = [{"lat": 28.601, "lon": 77.201}]
        metrics = calculate_metrics(matched, truth)
        for key in ("precision", "recall", "f1", "rmse", "median_error", "max_error", "mean_error", "count"):
            assert key in metrics

    def test_accepts_match_result_object(self):
        """calculate_metrics should handle objects with a .matched_points attribute."""
        class FakeResult:
            matched_points = [(28.6, 77.2)]
        truth = [{"lat": 28.6, "lon": 77.2}]
        metrics = calculate_metrics(FakeResult(), truth)
        assert metrics["count"] == 1
        assert metrics["rmse"] == pytest.approx(0.0, abs=1.0)
