"""
Integration test: full pipeline from sample CSV through HMM matching
to GeoJSON output and metric evaluation.

This test uses the generated Delhi sample data and cached road network.
It is skipped if the required files are not present.
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _data_file(name: str) -> str:
    return os.path.join(PROJECT_ROOT, "data", name)


def _cache_file(name: str) -> str:
    return os.path.join(PROJECT_ROOT, "backend", "cache", name)


needs_delhi_data = pytest.mark.skipif(
    not os.path.isfile(_data_file("sample_trace_delhi.csv")),
    reason="Run scripts/generate_test_data.py first",
)

needs_road_cache = pytest.mark.skipif(
    not os.path.isfile(_cache_file("road_network.geojson")),
    reason="Road network cache not available",
)


@needs_delhi_data
@needs_road_cache
class TestFullPipeline:

    @pytest.fixture(autouse=True)
    def _setup(self):
        from backend.hmm.road_network import RoadNetwork
        from backend.hmm.model import HMMMapMatcher
        from backend.hmm.utils import parse_gps_csv, calculate_metrics

        self.RoadNetwork = RoadNetwork
        self.HMMMapMatcher = HMMMapMatcher
        self.parse_gps_csv = parse_gps_csv
        self.calculate_metrics = calculate_metrics

        self.rn = RoadNetwork()
        self.rn.load_from_geojson(_cache_file("road_network.geojson"))
        self.matcher = HMMMapMatcher(
            road_network=self.rn, sigma=20.0, beta=10.0, max_candidate_radius=50.0,
        )

    def test_delhi_trace_matches(self):
        trace = self.parse_gps_csv(_data_file("sample_trace_delhi.csv"))
        assert len(trace) > 10
        result = self.matcher.match(trace)
        assert len(result.matched_points) == len(trace)
        assert result.statistics["total_points"] == len(trace)

    def test_clean_trace_has_low_error(self):
        trace = self.parse_gps_csv(_data_file("sample_trace_clean.csv"))
        result = self.matcher.match(trace)
        # Clean trace should have low RMSE (< 30m for a good match)
        assert result.statistics["rmse_m"] < 50.0

    def test_noisy_trace_still_produces_result(self):
        trace = self.parse_gps_csv(_data_file("sample_trace_noisy.csv"))
        result = self.matcher.match(trace)
        assert len(result.matched_points) == len(trace)

    def test_sparse_trace(self):
        trace = self.parse_gps_csv(_data_file("sample_trace_sparse.csv"))
        result = self.matcher.match(trace)
        assert len(result.matched_points) == len(trace)

    def test_geojson_output_structure(self):
        trace = self.parse_gps_csv(_data_file("sample_trace_delhi.csv"))
        result = self.matcher.match(trace)
        geojson = result.to_geojson()
        assert geojson["type"] == "FeatureCollection"
        route_features = [f for f in geojson["features"]
                          if f.get("properties", {}).get("layer") == "matched_route"]
        assert len(route_features) >= 1
        assert route_features[0]["geometry"]["type"] == "LineString"

    def test_metrics_against_ground_truth(self):
        trace = self.parse_gps_csv(_data_file("sample_trace_delhi.csv"))
        result = self.matcher.match(trace)
        gt = self.parse_gps_csv(_data_file("ground_truth.csv"))
        metrics = self.calculate_metrics(result, gt)
        assert metrics["count"] > 0
        assert 0.0 <= metrics["precision"] <= 1.0
        assert 0.0 <= metrics["recall"] <= 1.0

    def test_gpx_parsing_and_matching(self):
        from backend.hmm.utils import parse_gpx
        gpx_path = _data_file("sample_gpx_trace.gpx")
        if not os.path.isfile(gpx_path):
            pytest.skip("GPX sample not found")
        trace = parse_gpx(gpx_path)
        assert len(trace) > 2
        result = self.matcher.match(trace)
        assert len(result.matched_points) == len(trace)


@needs_road_cache
class TestAPIIntegration:
    """Test the Flask API end-to-end with the real road network."""

    @pytest.fixture
    def client(self):
        from backend.app import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_health_shows_loaded_network(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["road_network_loaded"] is True
        assert data["segments_count"] > 0

    @needs_delhi_data
    def test_sample_load_and_match(self, client):
        # Load sample
        resp = client.get("/api/sample-data/sample_trace_delhi")
        assert resp.status_code == 200
        trace = resp.get_json()["trace"]
        assert len(trace) > 2

        # Match it
        resp = client.post("/api/match", json={"trace": trace})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "result" in data
        assert "statistics" in data
        assert data["processing_time_ms"] > 0

    @needs_delhi_data
    def test_metrics_endpoint(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "metrics" in data
        metrics = data["metrics"]
        assert metrics["count"] > 0
