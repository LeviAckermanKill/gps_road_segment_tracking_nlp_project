"""
Hidden Markov Model (HMM) Map Matching package.

Provides pure Python / NumPy implementations of:
- HMMMapMatcher: Probabilistic map-matching model using Gaussian emissions and exponential transitions.
- viterbi, ViterbiResult: Optimal path decoding in log-probability space.
- RoadNetwork, RoadSegment: Road topology and spatial indexing.
- Utility functions for distance, metrics, and trace manipulation.
"""

from backend.hmm.model import HMMMapMatcher, MatchResult
from backend.hmm.road_network import RoadNetwork, RoadSegment
from backend.hmm.utils import (
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
from backend.hmm.viterbi import ViterbiResult, viterbi

__all__ = [
    "HMMMapMatcher",
    "MatchResult",
    "RoadNetwork",
    "RoadSegment",
    "ViterbiResult",
    "viterbi",
    "calculate_metrics",
    "generate_noisy_trace",
    "haversine_distance",
    "interpolate_gps_trace",
    "parse_gps_csv",
    "parse_gpx",
    "point_to_line_distance",
    "project_point_to_line",
    "smooth_gps_trace",
]
