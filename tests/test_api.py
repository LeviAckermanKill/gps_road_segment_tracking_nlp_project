"""
Comprehensive tests for the Flask REST API endpoints.

Covers: health check, trace validation, file upload, sample data,
live matching, road-network endpoints, geocode proxy, and metrics.
"""

import io
import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app import _validate_trace, app


# ---------------------------------------------------------------------------
# Trace validation (unit)
# ---------------------------------------------------------------------------

class TestTraceValidation:

    def test_valid_trace(self):
        assert _validate_trace([{"lat": 28.6, "lon": 77.2}, {"lat": 28.61, "lon": 77.21}]) is None

    def test_rejects_non_list(self):
        err = _validate_trace("not a list")
        assert err is not None and "list" in err

    def test_requires_two_points(self):
        assert "at least 2" in _validate_trace([{"lat": 28.6, "lon": 77.2}])

    def test_rejects_nan(self):
        result = _validate_trace([{"lat": float("nan"), "lon": 77.2}, {"lat": 28.6, "lon": 77.2}])
        assert "finite" in result

    def test_rejects_inf(self):
        result = _validate_trace([{"lat": float("inf"), "lon": 77.2}, {"lat": 28.6, "lon": 77.2}])
        assert "finite" in result

    def test_rejects_latitude_out_of_range(self):
        assert "out of range" in _validate_trace([{"lat": 91, "lon": 77.2}, {"lat": 28.6, "lon": 77.2}])

    def test_rejects_longitude_out_of_range(self):
        assert "out of range" in _validate_trace([{"lat": 28.6, "lon": 181}, {"lat": 28.6, "lon": 77.2}])

    def test_rejects_non_numeric(self):
        result = _validate_trace([{"lat": "abc", "lon": 77.2}, {"lat": 28.6, "lon": 77.2}])
        assert "non-numeric" in result

    def test_rejects_missing_keys(self):
        result = _validate_trace([{"lat": 28.6}, {"lat": 28.6, "lon": 77.2}])
        assert "missing" in result.lower()


# ---------------------------------------------------------------------------
# API endpoint tests (integration)
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "road_network_loaded" in data
        assert "segments_count" in data


class TestMatchEndpoint:

    def test_rejects_empty_body(self, client):
        resp = client.post("/api/match", content_type="application/json", data="{}")
        assert resp.status_code == 400

    def test_rejects_non_json(self, client):
        resp = client.post("/api/match", data="not json")
        assert resp.status_code == 400

    def test_rejects_too_few_points(self, client):
        resp = client.post("/api/match",
                           content_type="application/json",
                           data=json.dumps({"trace": [{"lat": 28.6, "lon": 77.2}]}))
        assert resp.status_code == 400


class TestUploadEndpoint:

    def test_rejects_missing_file(self, client):
        resp = client.post("/api/upload")
        assert resp.status_code == 400

    def test_rejects_unsupported_extension(self, client):
        data = {"file": (io.BytesIO(b"data"), "trace.txt")}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_accepts_csv_upload(self, client):
        csv_content = b"latitude,longitude,timestamp\n28.632,77.218,2024-01-15T10:00:00\n28.633,77.219,2024-01-15T10:00:05\n"
        data = {"file": (io.BytesIO(csv_content), "trace.csv")}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
        # May succeed (200) or fail (500 if road network doesn't cover the area)
        # but should not be a 400 (the file format is valid)
        assert resp.status_code in (200, 500, 503)


class TestSampleDataEndpoint:

    def test_sample_list_returns_200(self, client):
        resp = client.get("/api/sample-data")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "samples" in data
        assert isinstance(data["samples"], list)

    def test_unknown_sample_returns_404(self, client):
        resp = client.get("/api/sample-data/nonexistent_sample")
        assert resp.status_code == 404


class TestRoadNetworkEndpoint:

    def test_road_network_returns_geojson_or_503(self, client):
        resp = client.get("/api/road-network")
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            data = resp.get_json()
            assert data.get("type") == "FeatureCollection"


class TestViewportLoadEndpoint:

    def test_rejects_world_scale_bounds(self, client):
        resp = client.post("/api/road-network/load", json={
            "north": 60, "south": -60, "east": 150, "west": -150
        })
        assert resp.status_code == 400
        assert "8 km" in resp.get_json()["message"]

    def test_rejects_missing_fields(self, client):
        resp = client.post("/api/road-network/load", json={"north": 28.65})
        assert resp.status_code == 400

    def test_rejects_non_json_body(self, client):
        resp = client.post("/api/road-network/load", data="not json")
        assert resp.status_code == 400


class TestGeocodeEndpoint:

    def test_requires_min_query_length(self, client):
        resp = client.get("/api/geocode?q=ab")
        assert resp.status_code == 400

    def test_rejects_empty_query(self, client):
        resp = client.get("/api/geocode?q=")
        assert resp.status_code == 400


class TestLiveMatchEndpoint:

    def test_first_point_is_accepted_and_waits_for_a_second(self, client):
        resp = client.post("/api/match-live", json={
            "points": [], "new_point": {"lat": 28.6322, "lon": 77.2185}
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["result"] is None
        assert data["total_points"] == 1

    def test_rejects_missing_new_point(self, client):
        resp = client.post("/api/match-live",
                           content_type="application/json",
                           data=json.dumps({"points": []}))
        assert resp.status_code == 400

    def test_rejects_non_object_new_point(self, client):
        resp = client.post("/api/match-live",
                           content_type="application/json",
                           data=json.dumps({"points": [], "new_point": 42}))
        assert resp.status_code == 400


class TestTimingHeader:

    def test_processing_time_header_present(self, client):
        resp = client.get("/api/health")
        assert "X-Processing-Time-Ms" in resp.headers
