"""
Shared test fixtures for GPS Map Matching project.

Provides reusable road network, matcher, trace, and Flask client fixtures
so individual test modules remain concise and independent.
"""

import os
import sys
import math
import pytest

# Ensure the project root is on sys.path for backend imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.hmm.road_network import RoadNetwork, RoadSegment
from backend.hmm.model import HMMMapMatcher
from backend.hmm.utils import haversine_distance


# ---------------------------------------------------------------------------
# Minimal road network for unit tests (no OSM download needed)
# ---------------------------------------------------------------------------

def _make_segment(seg_id, u, v, coords, name="Test Road", road_type="primary", oneway=False):
    """Helper to build a RoadSegment with auto-calculated length."""
    total_len = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        total_len += haversine_distance(lat1, lon1, lat2, lon2)
    return RoadSegment(
        segment_id=seg_id,
        start_node=u,
        end_node=v,
        coords=coords,
        length=max(total_len, 0.1),
        name=name,
        road_type=road_type,
        oneway=oneway,
    )


@pytest.fixture
def mini_segments():
    """
    Three connected road segments forming an L-shape near Connaught Place.

    Segment layout (lon, lat coords):
        A ----seg1----> B ----seg2----> C
                                        |
                                       seg3
                                        |
                                        v
                                        D
    """
    seg1 = _make_segment(
        "seg_1", "A", "B",
        [(77.2170, 28.6320), (77.2190, 28.6320)],
        name="Road East-West 1",
    )
    seg2 = _make_segment(
        "seg_2", "B", "C",
        [(77.2190, 28.6320), (77.2210, 28.6320)],
        name="Road East-West 2",
    )
    seg3 = _make_segment(
        "seg_3", "C", "D",
        [(77.2210, 28.6320), (77.2210, 28.6300)],
        name="Road North-South",
    )
    return [seg1, seg2, seg3]


@pytest.fixture
def road_network(mini_segments):
    """Build a small RoadNetwork from the mini_segments fixture."""
    rn = RoadNetwork()
    for seg in mini_segments:
        rn.add_segment(seg)
    rn.build_spatial_index()
    return rn


@pytest.fixture
def matcher(road_network):
    """HMMMapMatcher configured for the mini road network."""
    return HMMMapMatcher(
        road_network=road_network,
        sigma=20.0,
        beta=10.0,
        max_candidate_radius=200.0,
    )


@pytest.fixture
def simple_trace():
    """GPS trace of 4 points that follow the L-shaped mini network."""
    return [
        {"lat": 28.6321, "lon": 77.2172, "timestamp": "2024-01-15T10:00:00"},
        {"lat": 28.6319, "lon": 77.2191, "timestamp": "2024-01-15T10:00:05"},
        {"lat": 28.6321, "lon": 77.2208, "timestamp": "2024-01-15T10:00:10"},
        {"lat": 28.6301, "lon": 77.2211, "timestamp": "2024-01-15T10:00:15"},
    ]


@pytest.fixture
def noisy_trace():
    """Same route as simple_trace but with significant noise added."""
    return [
        {"lat": 28.6325, "lon": 77.2168, "timestamp": "2024-01-15T10:00:00"},
        {"lat": 28.6315, "lon": 77.2195, "timestamp": "2024-01-15T10:00:05"},
        {"lat": 28.6327, "lon": 77.2205, "timestamp": "2024-01-15T10:00:10"},
        {"lat": 28.6298, "lon": 77.2215, "timestamp": "2024-01-15T10:00:15"},
    ]


@pytest.fixture
def app_client():
    """Flask test client — imports the app which loads the cached road network."""
    from backend.app import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def delhi_trace_path():
    """Path to the Delhi sample CSV, if it exists."""
    path = os.path.join(PROJECT_ROOT, "data", "sample_trace_delhi.csv")
    if not os.path.isfile(path):
        pytest.skip("sample_trace_delhi.csv not found — run generate_test_data.py first")
    return path


@pytest.fixture
def ground_truth_path():
    """Path to the ground truth CSV, if it exists."""
    path = os.path.join(PROJECT_ROOT, "data", "ground_truth.csv")
    if not os.path.isfile(path):
        pytest.skip("ground_truth.csv not found — run generate_test_data.py first")
    return path
