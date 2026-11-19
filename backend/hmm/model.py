"""
Hidden Markov Model (HMM) Map Matching Engine.

Implements the Newson & Krumm (2009) probabilistic map-matching algorithm
using Gaussian emission probabilities and exponential transition probabilities
decoded via the Viterbi algorithm.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from shapely.geometry import LineString, Point, mapping

from backend.hmm.road_network import RoadNetwork, RoadSegment
from backend.hmm.utils import haversine_distance
from backend.hmm.viterbi import ViterbiResult, viterbi

logger = logging.getLogger(__name__)


class MatchResult:
    """
    Encapsulates the complete output of an HMM map-matching run.
    """

    def __init__(
        self,
        matched_segments: List[RoadSegment],
        matched_points: List[Tuple[float, float]],
        raw_points: List[Dict[str, Any]],
        statistics: Dict[str, Any],
        path_geometry: Dict[str, Any],
        trellis: List[Dict[Any, Dict[str, Any]]],
    ) -> None:
        self.matched_segments = matched_segments
        self.matched_points = matched_points
        self.raw_points = raw_points
        self.statistics = statistics
        self.path_geometry = path_geometry
        self.trellis = trellis

    def to_geojson(self) -> Dict[str, Any]:
        """
        Serialize results into a standard GeoJSON FeatureCollection.
        Includes the matched path LineString and the snapped Point features.
        """
        features: List[Dict[str, Any]] = []

        # 1. Matched continuous route LineString feature
        if self.path_geometry and "coordinates" in self.path_geometry:
            features.append({
                "type": "Feature",
                "id": "matched_route",
                "geometry": self.path_geometry,
                "properties": {
                    "layer": "matched_route",
                    "stroke": "#2563eb",
                    "stroke-width": 5,
                    "stroke-opacity": 0.85,
                    "matched_segments_count": len(self.matched_segments),
                },
            })

        # 2. Snapped points Features
        for idx, (proj_lat, proj_lon) in enumerate(self.matched_points):
            raw_pt = self.raw_points[idx] if idx < len(self.raw_points) else {}
            seg = self.matched_segments[idx] if idx < len(self.matched_segments) else None
            road_name = seg.name if seg else "Unknown"

            features.append({
                "type": "Feature",
                "id": f"snapped_pt_{idx}",
                "geometry": {
                    "type": "Point",
                    "coordinates": [proj_lon, proj_lat],
                },
                "properties": {
                    "layer": "snapped_point",
                    "index": idx,
                    "road_name": road_name,
                    "road_id": seg.id if seg else None,
                    "raw_lat": raw_pt.get("lat"),
                    "raw_lon": raw_pt.get("lon"),
                    "timestamp": raw_pt.get("timestamp"),
                },
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "statistics": self.statistics,
        }


class HMMMapMatcher:
    """
    HMM Map Matcher implementing Gaussian emissions and exponential transitions.
    """

    def __init__(
        self,
        road_network: RoadNetwork,
        sigma: float = 20.0,
        beta: float = 10.0,
        max_candidate_radius: float = 50.0,
    ) -> None:
        """
        Parameters
        ----------
        road_network : RoadNetwork
            The underlying street network graph.
        sigma : float
            Standard deviation of GPS measurement noise in meters (default 20.0m).
        beta : float
            Scale parameter for transition probability (default 10.0).
        max_candidate_radius : float
            Search radius in meters for road segment candidates (default 50.0m).
        """
        self.road_network = road_network
        self.sigma = float(sigma)
        self.beta = float(beta)
        self.max_candidate_radius = float(max_candidate_radius)
        self._norm_const = -math.log(self.sigma * math.sqrt(2.0 * math.pi))
        self._beta_const = -math.log(self.beta)

    def emission_log_probability(self, gps_point: Dict[str, Any], segment: RoadSegment) -> float:
        """
        Calculate log P(observation | segment) using a 1D Gaussian distribution
        over the perpendicular distance from GPS observation to the road segment.

        Formula: ln P = -0.5 * (d / sigma)^2 - ln(sigma * sqrt(2*pi))
        """
        lat = float(gps_point["lat"])
        lon = float(gps_point["lon"])
        dist = segment.distance_to_point(lat, lon)
        exponent = -0.5 * ((dist / self.sigma) ** 2)
        return exponent + self._norm_const

    def transition_log_probability(
        self,
        seg_i: RoadSegment,
        seg_j: RoadSegment,
        gps_i: Dict[str, Any],
        gps_j: Dict[str, Any],
    ) -> float:
        """
        Calculate log P(segment_j | segment_i) using an exponential distribution
        over the discrepancy between great-circle distance and shortest-path road distance.

        Formula: ln P = -|d_gc - d_route| / beta - ln(beta)
        """
        d_gc = haversine_distance(
            float(gps_i["lat"]), float(gps_i["lon"]),
            float(gps_j["lat"]), float(gps_j["lon"])
        )
        d_route = self.road_network.route_distance_between_segments(seg_i, seg_j)

        if math.isinf(d_route):
            # Penalize disconnected transitions
            return -50.0

        diff = abs(d_gc - d_route)
        return (-diff / self.beta) + self._beta_const

    def get_candidates(self, gps_point: Dict[str, Any], radius: Optional[float] = None) -> List[RoadSegment]:
        """Find road segment candidates within radius meters of GPS point."""
        r = radius if radius is not None else self.max_candidate_radius
        lat = float(gps_point["lat"])
        lon = float(gps_point["lon"])
        return self.road_network.get_nearest_segments(lat, lon, radius_m=r)

    def match(self, gps_trace: List[Dict[str, Any]]) -> MatchResult:
        """
        Run complete HMM map matching using the Viterbi algorithm on a GPS trace.

        Parameters
        ----------
        gps_trace : list of dicts
            List of points, each containing at least 'lat' and 'lon'.

        Returns
        -------
        MatchResult
            Detailed matching results with snapped points, path geometry, and statistics.
        """
        T = len(gps_trace)
        if T == 0:
            return MatchResult([], [], [], {}, {}, [])

        # 1. Identify candidate states for each GPS point
        states_per_obs: List[List[RoadSegment]] = []
        emission_log_probs: List[Dict[str, float]] = []
        segment_lookup: Dict[str, RoadSegment] = {}

        for pt in gps_trace:
            candidates = self.get_candidates(pt, radius=self.max_candidate_radius)
            if not candidates:
                # Expand radius if no candidate found
                candidates = self.get_candidates(pt, radius=self.max_candidate_radius * 2.5)

            if not candidates:
                # If still empty, fall back to any nearest segment in network
                nearest = self.road_network.get_nearest_segments(float(pt["lat"]), float(pt["lon"]), radius_m=500.0)
                candidates = nearest[:3] if nearest else []

            states_per_obs.append(candidates)
            emit_dict: Dict[str, float] = {}
            for seg in candidates:
                segment_lookup[seg.id] = seg
                emit_dict[seg.id] = self.emission_log_probability(pt, seg)
            emission_log_probs.append(emit_dict)

        # 2. Define transition probability function for Viterbi
        def trans_fn(prev_seg_id: Any, curr_seg_id: Any, prev_t: int, curr_t: int) -> float:
            seg_a = segment_lookup.get(prev_seg_id)
            seg_b = segment_lookup.get(curr_seg_id)
            if seg_a is None or seg_b is None:
                return -100.0
            return self.transition_log_probability(
                seg_a, seg_b, gps_trace[prev_t], gps_trace[curr_t]
            )

        # Convert candidate lists to lists of segment IDs for Viterbi
        state_ids_per_obs = [[seg.id for seg in cands] for cands in states_per_obs]

        # 3. Run Viterbi algorithm
        viterbi_res: ViterbiResult = viterbi(
            states_per_obs=state_ids_per_obs,
            emission_log_probs=emission_log_probs,
            transition_log_prob_fn=trans_fn,
        )

        # 4. Extract matched road segments and project GPS points
        matched_segments: List[RoadSegment] = []
        matched_points: List[Tuple[float, float]] = []
        errors: List[float] = []

        for idx, seg_id in enumerate(viterbi_res.path):
            seg = segment_lookup.get(seg_id)
            if seg is None and len(states_per_obs[idx]) > 0:
                seg = states_per_obs[idx][0]

            if seg is not None:
                matched_segments.append(seg)
                raw_lat = float(gps_trace[idx]["lat"])
                raw_lon = float(gps_trace[idx]["lon"])
                proj_lat, proj_lon = seg.project_point(raw_lat, raw_lon)
                matched_points.append((proj_lat, proj_lon))
                errors.append(haversine_distance(raw_lat, raw_lon, proj_lat, proj_lon))
            else:
                # Fallback if no segment available
                raw_lat = float(gps_trace[idx]["lat"])
                raw_lon = float(gps_trace[idx]["lon"])
                matched_points.append((raw_lat, raw_lon))
                errors.append(0.0)

        # 5. Build continuous path geometry
        path_coords: List[List[float]] = []
        seen_segs = set()
        ordered_unique_segs: List[RoadSegment] = []
        for s in matched_segments:
            if s.id not in seen_segs:
                seen_segs.add(s.id)
                ordered_unique_segs.append(s)

        for s in ordered_unique_segs:
            for coord in s.coords:
                if not path_coords or path_coords[-1] != [coord[0], coord[1]]:
                    path_coords.append([coord[0], coord[1]])

        if not path_coords:
            # Fallback to connecting matched points
            path_coords = [[lon, lat] for lat, lon in matched_points]

        path_geometry = {
            "type": "LineString",
            "coordinates": path_coords,
        }

        # 6. Statistics
        err_arr = np.array(errors, dtype=np.float64) if errors else np.zeros(1)
        stats = {
            "total_points": T,
            "num_points": T,
            "matched_segments_count": len(ordered_unique_segs),
            "matched_segments": len(ordered_unique_segs),
            "log_probability": round(float(viterbi_res.log_probability), 2),
            "mean_error_m": round(float(np.mean(err_arr)), 2),
            "median_error_m": round(float(np.median(err_arr)), 2),
            "rmse_m": round(float(np.sqrt(np.mean(err_arr ** 2))), 2),
            "rmse": round(float(np.sqrt(np.mean(err_arr ** 2))), 2),
            "max_error_m": round(float(np.max(err_arr)), 2),
            "accuracy_percentage": round(float(np.mean(err_arr <= 15.0) * 100.0), 1),
        }

        return MatchResult(
            matched_segments=matched_segments,
            matched_points=matched_points,
            raw_points=gps_trace,
            statistics=stats,
            path_geometry=path_geometry,
            trellis=viterbi_res.trellis,
        )

    def match_incremental(
        self,
        gps_points: List[Dict[str, Any]],
        new_point: Dict[str, Any],
    ) -> MatchResult:
        """Add new point to existing trace and run matching on the combined window."""
        combined = list(gps_points) + [new_point]
        return self.match(combined)
