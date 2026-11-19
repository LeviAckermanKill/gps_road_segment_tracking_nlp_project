"""
Tests for RoadNetwork and RoadSegment classes.

Covers: segment construction, distance/projection, spatial indexing,
graph routing, GeoJSON serialization, and network building.
"""

import math
import os
import json
import tempfile

import pytest
import networkx as nx
import osmnx as ox

from backend.config import Config
from backend.hmm.road_network import RoadNetwork, RoadSegment
from backend.hmm.utils import haversine_distance


# ---------------------------------------------------------------------------
# RoadSegment
# ---------------------------------------------------------------------------

class TestRoadSegment:

    def test_basic_construction(self):
        seg = RoadSegment(
            "s1", "A", "B",
            [(77.21, 28.63), (77.22, 28.63)],
            length=100.0,
            name="Test Road",
        )
        assert seg.id == "s1"
        assert seg.start_node == "A"
        assert seg.end_node == "B"
        assert seg.length == 100.0
        assert seg.name == "Test Road"

    def test_auto_calculated_length(self):
        seg = RoadSegment(
            "s2", "A", "B",
            [(77.21, 28.63), (77.22, 28.63)],
            length=0.0,  # triggers auto-calculation
        )
        assert seg.length > 0
        expected = haversine_distance(28.63, 77.21, 28.63, 77.22)
        assert seg.length == pytest.approx(expected, rel=0.01)

    def test_rejects_single_point(self):
        with pytest.raises(ValueError, match="at least 2"):
            RoadSegment("bad", "A", "B", [(77.21, 28.63)], length=10.0)

    def test_distance_to_point(self):
        seg = RoadSegment(
            "s3", "A", "B",
            [(77.21, 28.63), (77.22, 28.63)],
            length=100.0,
        )
        d = seg.distance_to_point(28.63, 77.215)
        assert d < 2.0  # point is essentially on the line

    def test_project_point(self):
        seg = RoadSegment(
            "s4", "A", "B",
            [(77.21, 28.63), (77.22, 28.63)],
            length=100.0,
        )
        plat, plon = seg.project_point(28.631, 77.215)
        assert plat == pytest.approx(28.63, abs=0.001)
        assert plon == pytest.approx(77.215, abs=0.001)

    def test_to_geojson_feature(self):
        seg = RoadSegment(
            "s5", "A", "B",
            [(77.21, 28.63), (77.22, 28.63)],
            length=100.0,
            name="GeoJSON Road",
        )
        feat = seg.to_geojson_feature()
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "LineString"
        assert feat["properties"]["name"] == "GeoJSON Road"

    def test_string_conversion_of_node_ids(self):
        seg = RoadSegment("s6", 123, 456, [(77.21, 28.63), (77.22, 28.63)], length=10.0)
        assert seg.start_node == "123"
        assert seg.end_node == "456"

    def test_repr(self):
        seg = RoadSegment("s7", "A", "B", [(77.21, 28.63), (77.22, 28.63)], length=50.0)
        r = repr(seg)
        assert "s7" in r
        assert "50.0m" in r


# ---------------------------------------------------------------------------
# RoadNetwork — building
# ---------------------------------------------------------------------------

class TestRoadNetworkBuilding:

    def test_add_segment_updates_graph(self, road_network, mini_segments):
        assert len(road_network) == 3
        # Check graph has nodes
        assert "A" in road_network.graph
        assert "B" in road_network.graph
        assert "C" in road_network.graph
        assert "D" in road_network.graph

    def test_add_segment_bidirectional_edges(self):
        rn = RoadNetwork()
        seg = RoadSegment("s1", "X", "Y", [(77.21, 28.63), (77.22, 28.63)],
                          length=100.0, oneway=False)
        rn.add_segment(seg)
        assert rn.graph.has_edge("X", "Y")
        assert rn.graph.has_edge("Y", "X")  # reverse edge

    def test_add_segment_oneway_no_reverse(self):
        rn = RoadNetwork()
        seg = RoadSegment("s1", "X", "Y", [(77.21, 28.63), (77.22, 28.63)],
                          length=100.0, oneway=True)
        rn.add_segment(seg)
        assert rn.graph.has_edge("X", "Y")
        assert not rn.graph.has_edge("Y", "X")

    def test_clear_resets_everything(self, road_network):
        road_network.clear()
        assert len(road_network) == 0
        assert road_network.kdtree is None


# ---------------------------------------------------------------------------
# Spatial index
# ---------------------------------------------------------------------------

class TestSpatialIndex:

    def test_kdtree_is_built(self, road_network):
        assert road_network.kdtree is not None

    def test_nearest_segments_finds_close_road(self, road_network):
        # Point near seg_1 midpoint
        candidates = road_network.get_nearest_segments(28.6320, 77.2180, radius_m=200.0)
        assert len(candidates) >= 1
        ids = [c.id for c in candidates]
        assert "seg_1" in ids

    def test_nearest_segments_returns_empty_for_no_network(self):
        empty = RoadNetwork()
        result = empty.get_nearest_segments(28.63, 77.21)
        assert result == []

    def test_fallback_to_nearest_when_outside_radius(self, road_network):
        # Far away point should still get fallback results
        candidates = road_network.get_nearest_segments(28.6400, 77.2300, radius_m=10.0)
        assert len(candidates) >= 1  # fallback to nearest


# ---------------------------------------------------------------------------
# Graph routing
# ---------------------------------------------------------------------------

class TestGraphRouting:

    def test_same_node_zero_distance(self, road_network):
        assert road_network.shortest_path_distance("A", "A") == 0.0

    def test_connected_nodes_finite_distance(self, road_network):
        d = road_network.shortest_path_distance("A", "B")
        assert d > 0
        assert math.isfinite(d)

    def test_route_distance_between_same_segment(self, road_network):
        seg = road_network.segments["seg_1"]
        assert road_network.route_distance_between_segments(seg, seg) == 0.0

    def test_route_distance_connected_segments(self, road_network):
        seg1 = road_network.segments["seg_1"]
        seg2 = road_network.segments["seg_2"]
        d = road_network.route_distance_between_segments(seg1, seg2)
        assert d > 0
        assert math.isfinite(d)

    def test_path_cache_works(self, road_network):
        d1 = road_network.shortest_path_distance("A", "D")
        d2 = road_network.shortest_path_distance("A", "D")
        assert d1 == d2


# ---------------------------------------------------------------------------
# GeoJSON serialization / round-trip
# ---------------------------------------------------------------------------

class TestGeoJSONSerialization:

    def test_get_edges_geojson(self, road_network):
        geojson = road_network.get_edges_geojson()
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 3

    def test_save_and_load_geojson_roundtrip(self, road_network):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_net.geojson")
            road_network.save_to_geojson(path)
            assert os.path.isfile(path)

            loaded = RoadNetwork()
            loaded.load_from_geojson(path)
            assert len(loaded) == len(road_network)

    def test_load_from_geojson_builds_spatial_index(self, road_network):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_net.geojson")
            road_network.save_to_geojson(path)
            loaded = RoadNetwork()
            loaded.load_from_geojson(path)
            assert loaded.kdtree is not None


class TestViewportLoading:

    def test_retries_configured_overpass_endpoint_and_normalizes_node_ids(self, monkeypatch, tmp_path):
        graph = nx.MultiDiGraph()
        graph.add_node(1, x=77.2, y=28.6)
        graph.add_node(2, x=77.201, y=28.6)
        graph.add_edge(1, 2, key=0, length=100.0, highway="residential", name="Demo Road")
        calls = []

        monkeypatch.setattr(Config, "OSMNX_OVERPASS_URL", "https://first.example/api")
        monkeypatch.setattr(Config, "OSMNX_FALLBACK_OVERPASS_URL", "https://second.example/api")
        monkeypatch.setattr(Config, "OSMNX_REQUEST_TIMEOUT", 1)
        monkeypatch.setattr(Config, "CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(ox.settings, "overpass_url", ox.settings.overpass_url)
        monkeypatch.setattr(ox.settings, "requests_timeout", ox.settings.requests_timeout)
        monkeypatch.setattr(ox.settings, "http_user_agent", ox.settings.http_user_agent)

        def graph_from_bbox(*, bbox, network_type, simplify):
            calls.append(ox.settings.overpass_url)
            if len(calls) == 1:
                raise TimeoutError("primary endpoint unavailable")
            return graph

        monkeypatch.setattr(ox, "graph_from_bbox", graph_from_bbox)
        network = RoadNetwork()
        network.load_from_bbox(28.61, 28.59, 77.21, 77.19)

        assert calls == ["https://first.example/api", "https://second.example/api"]
        assert len(network) == 1
        assert network.segments["1_2_0"].start_node == "1"
        assert "1" in network.graph and "2" in network.graph
