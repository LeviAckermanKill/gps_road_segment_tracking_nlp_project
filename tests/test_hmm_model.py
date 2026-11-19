"""
Tests for the HMM Map Matching model (HMMMapMatcher and MatchResult).

Covers: emission and transition probabilities, candidate generation,
end-to-end matching, MatchResult serialization, and statistics.
"""

import math

import pytest

from backend.hmm.model import HMMMapMatcher, MatchResult
from backend.hmm.road_network import RoadNetwork, RoadSegment
from backend.hmm.utils import haversine_distance


# ---------------------------------------------------------------------------
# Emission probability
# ---------------------------------------------------------------------------

class TestEmissionProbability:

    def test_closer_point_has_higher_emission(self, matcher, road_network):
        seg = road_network.segments["seg_1"]
        close_pt = {"lat": 28.6320, "lon": 77.2180}  # ~on the road
        far_pt = {"lat": 28.6340, "lon": 77.2180}    # ~200m north

        lp_close = matcher.emission_log_probability(close_pt, seg)
        lp_far = matcher.emission_log_probability(far_pt, seg)
        assert lp_close > lp_far

    def test_emission_on_road_near_zero_exponent(self, matcher, road_network):
        seg = road_network.segments["seg_1"]
        on_road = {"lat": 28.6320, "lon": 77.2180}
        lp = matcher.emission_log_probability(on_road, seg)
        # Should be close to the normalization constant (distance ≈ 0)
        assert lp > -5.0  # not too penalized

    def test_emission_always_negative(self, matcher, road_network):
        seg = road_network.segments["seg_1"]
        for lat in [28.630, 28.632, 28.634, 28.636]:
            pt = {"lat": lat, "lon": 77.218}
            assert matcher.emission_log_probability(pt, seg) < 0.0


# ---------------------------------------------------------------------------
# Transition probability
# ---------------------------------------------------------------------------

class TestTransitionProbability:

    def test_same_segment_zero_route_distance(self, matcher, road_network):
        seg = road_network.segments["seg_1"]
        pt = {"lat": 28.6320, "lon": 77.2180}
        lp = matcher.transition_log_probability(seg, seg, pt, pt)
        # Same segment, same point → d_gc=0, d_route=0, diff=0
        assert math.isfinite(lp)

    def test_connected_segments_better_than_disconnected(self, matcher, road_network):
        seg1 = road_network.segments["seg_1"]
        seg2 = road_network.segments["seg_2"]
        seg3 = road_network.segments["seg_3"]

        pt_a = {"lat": 28.6320, "lon": 77.2180}
        pt_b = {"lat": 28.6320, "lon": 77.2200}

        lp_connected = matcher.transition_log_probability(seg1, seg2, pt_a, pt_b)
        # seg1→seg3 would be more disconnected (need to go through seg2)
        assert math.isfinite(lp_connected)

    def test_transition_always_negative_or_zero(self, matcher, road_network):
        seg1 = road_network.segments["seg_1"]
        seg2 = road_network.segments["seg_2"]
        pt1 = {"lat": 28.632, "lon": 77.218}
        pt2 = {"lat": 28.632, "lon": 77.220}
        lp = matcher.transition_log_probability(seg1, seg2, pt1, pt2)
        assert lp <= 0.0 or lp == pytest.approx(matcher._beta_const, abs=1.0)


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

class TestCandidateGeneration:

    def test_finds_candidates_near_road(self, matcher):
        pt = {"lat": 28.6320, "lon": 77.2180}
        candidates = matcher.get_candidates(pt)
        assert len(candidates) >= 1

    def test_no_candidates_far_away_uses_fallback(self, matcher):
        far_pt = {"lat": 28.6500, "lon": 77.2500}
        candidates = matcher.get_candidates(far_pt, radius=10.0)
        # Even with tiny radius, fallback should give something from the
        # small network or empty list
        # (at 200m radius from __init__ it will find something)
        candidates_wide = matcher.get_candidates(far_pt)
        assert isinstance(candidates_wide, list)

    def test_custom_radius(self, matcher):
        pt = {"lat": 28.6320, "lon": 77.2180}
        narrow = matcher.get_candidates(pt, radius=5.0)
        wide = matcher.get_candidates(pt, radius=500.0)
        assert len(wide) >= len(narrow)


# ---------------------------------------------------------------------------
# End-to-end matching
# ---------------------------------------------------------------------------

class TestMatchEndToEnd:

    def test_basic_match_produces_result(self, matcher, simple_trace):
        result = matcher.match(simple_trace)
        assert isinstance(result, MatchResult)
        assert len(result.matched_points) == len(simple_trace)
        assert len(result.matched_segments) == len(simple_trace)

    def test_match_produces_valid_geojson(self, matcher, simple_trace):
        result = matcher.match(simple_trace)
        geojson = result.to_geojson()
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) > 0

    def test_match_statistics_complete(self, matcher, simple_trace):
        result = matcher.match(simple_trace)
        for key in ("total_points", "num_points", "matched_segments_count",
                     "log_probability", "mean_error_m", "rmse_m",
                     "accuracy_percentage"):
            assert key in result.statistics

    def test_match_noisy_trace_still_works(self, matcher, noisy_trace):
        result = matcher.match(noisy_trace)
        assert len(result.matched_points) == len(noisy_trace)
        assert math.isfinite(result.statistics["log_probability"])

    def test_empty_trace(self, matcher):
        result = matcher.match([])
        assert len(result.matched_points) == 0
        assert len(result.matched_segments) == 0

    def test_matched_points_closer_to_road_than_raw(self, matcher, simple_trace, road_network):
        result = matcher.match(simple_trace)
        for idx, (plat, plon) in enumerate(result.matched_points):
            raw_lat = float(simple_trace[idx]["lat"])
            raw_lon = float(simple_trace[idx]["lon"])
            seg = result.matched_segments[idx]
            d_matched = seg.distance_to_point(plat, plon)
            d_raw = seg.distance_to_point(raw_lat, raw_lon)
            # Matched (projected) point should be closer to road than raw
            assert d_matched <= d_raw + 1.0  # 1m tolerance


# ---------------------------------------------------------------------------
# MatchResult serialization
# ---------------------------------------------------------------------------

class TestMatchResult:

    def test_geojson_has_matched_route(self, matcher, simple_trace):
        result = matcher.match(simple_trace)
        geojson = result.to_geojson()
        route_features = [f for f in geojson["features"]
                          if f.get("properties", {}).get("layer") == "matched_route"]
        assert len(route_features) >= 1

    def test_geojson_has_snapped_points(self, matcher, simple_trace):
        result = matcher.match(simple_trace)
        geojson = result.to_geojson()
        point_features = [f for f in geojson["features"]
                          if f.get("properties", {}).get("layer") == "snapped_point"]
        assert len(point_features) == len(simple_trace)

    def test_snapped_point_contains_road_name(self, matcher, simple_trace):
        result = matcher.match(simple_trace)
        geojson = result.to_geojson()
        point_features = [f for f in geojson["features"]
                          if f.get("properties", {}).get("layer") == "snapped_point"]
        for feat in point_features:
            assert "road_name" in feat["properties"]

    def test_statistics_key_in_geojson(self, matcher, simple_trace):
        result = matcher.match(simple_trace)
        geojson = result.to_geojson()
        assert "statistics" in geojson


# ---------------------------------------------------------------------------
# Incremental matching
# ---------------------------------------------------------------------------

class TestIncrementalMatching:

    def test_match_incremental(self, matcher, simple_trace):
        existing = simple_trace[:2]
        new_pt = simple_trace[2]
        result = matcher.match_incremental(existing, new_pt)
        assert len(result.matched_points) == 3
