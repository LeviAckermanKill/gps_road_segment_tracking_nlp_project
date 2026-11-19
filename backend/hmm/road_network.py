"""
Road network representation, spatial indexing, and graph routing for GPS Map Matching.

Provides data structures for road segments and road network graphs,
interfacing with OSMnx, GeoJSON, Shapely, and NetworkX.
"""

from __future__ import annotations

import json
import inspect
import hashlib
import logging
import math
import os
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, mapping

from backend.hmm.utils import haversine_distance, point_to_line_distance, project_point_to_line
from backend.config import Config

logger = logging.getLogger(__name__)
_overpass_lock = threading.Lock()


class RoadSegment:
    """
    Represents a single directed road edge in the road network.

    Attributes
    ----------
    id : str
        Unique identifier for the segment.
    start_node : Any
        Identifier of the starting junction/intersection node.
    end_node : Any
        Identifier of the ending junction/intersection node.
    geometry : LineString
        Shapely LineString geometry with coordinates in (lon, lat).
    coords : list of (float, float)
        List of (lon, lat) tuples defining the segment.
    length : float
        Length of the segment in meters.
    name : str
        Road name (e.g. 'Barakhamba Road', 'Outer Circle').
    road_type : str
        OSM highway classification (e.g. 'primary', 'secondary', 'residential').
    oneway : bool
        Whether the segment is one-way.
    """

    def __init__(
        self,
        segment_id: str,
        start_node: Any,
        end_node: Any,
        coords: Sequence[Tuple[float, float]],
        length: float,
        name: str = "Unnamed Road",
        road_type: str = "unclassified",
        oneway: bool = False,
    ) -> None:
        self.id = str(segment_id)
        self.start_node = str(start_node)
        self.end_node = str(end_node)
        self.coords = [(float(c[0]), float(c[1])) for c in coords]
        if len(self.coords) < 2:
            raise ValueError(f"RoadSegment {segment_id} must have at least 2 points")
        self.geometry = LineString(self.coords)
        self.length = float(length) if length > 0 else self._calculate_length_m()
        self.name = str(name) if name else "Unnamed Road"
        self.road_type = str(road_type) if road_type else "unclassified"
        self.oneway = bool(oneway)

    def _calculate_length_m(self) -> float:
        """Calculate total segment length in meters using Haversine along coords."""
        total = 0.0
        for i in range(len(self.coords) - 1):
            lon1, lat1 = self.coords[i]
            lon2, lat2 = self.coords[i + 1]
            total += haversine_distance(lat1, lon1, lat2, lon2)
        return max(total, 0.1)

    def distance_to_point(self, lat: float, lon: float) -> float:
        """
        Compute minimum perpendicular or endpoint distance in meters from (lat, lon)
        to this road segment.
        """
        return point_to_line_distance(lat, lon, self.coords)

    def project_point(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Project (lat, lon) onto this road segment.

        Returns
        -------
        (proj_lat, proj_lon) : tuple of float
            The closest point on the segment.
        """
        return project_point_to_line(lat, lon, self.coords)

    def to_geojson_feature(self) -> Dict[str, Any]:
        """Serialize segment to a GeoJSON Feature dictionary."""
        return {
            "type": "Feature",
            "id": self.id,
            "geometry": mapping(self.geometry),
            "properties": {
                "id": self.id,
                "start_node": self.start_node,
                "end_node": self.end_node,
                "name": self.name,
                "highway": self.road_type,
                "length": self.length,
                "oneway": self.oneway,
            },
        }

    def __repr__(self) -> str:
        return f"<RoadSegment {self.id}: '{self.name}' ({self.road_type}, {self.length:.1f}m)>"


class RoadNetwork:
    """
    Road network graph container with spatial indexing and Dijkstra shortest path routing.
    """

    def __init__(self) -> None:
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self.segments: Dict[str, RoadSegment] = {}
        self.spatial_points: np.ndarray = np.empty((0, 2), dtype=np.float64)
        self.spatial_segment_ids: List[str] = []
        self.kdtree: Optional[cKDTree] = None
        self._path_cache: Dict[Tuple[str, str], float] = {}
        self._undirected_graph: Optional[nx.Graph] = None

    def __len__(self) -> int:
        return len(self.segments)

    def clear(self) -> None:
        """Reset network state."""
        self.graph.clear()
        self.segments.clear()
        self.spatial_points = np.empty((0, 2), dtype=np.float64)
        self.spatial_segment_ids = []
        self.kdtree = None
        self._path_cache.clear()
        self._undirected_graph = None

    def add_segment(self, segment: RoadSegment) -> None:
        """Add a RoadSegment to the network and update graph topology."""
        self.segments[segment.id] = segment
        self._undirected_graph = None  # invalidate cached copy

        # Update NetworkX graph
        u, v = segment.start_node, segment.end_node
        self.graph.add_edge(
            u,
            v,
            key=segment.id,
            segment_id=segment.id,
            weight=segment.length,
            name=segment.name,
            highway=segment.road_type,
        )
        if not segment.oneway:
            self.graph.add_edge(
                v,
                u,
                key=f"{segment.id}_rev",
                segment_id=segment.id,
                weight=segment.length,
                name=segment.name,
                highway=segment.road_type,
            )

    def build_spatial_index(self, sample_spacing_m: float = 20.0) -> None:
        """
        Build a KD-tree spatial index by sampling points along all road segments.
        Coordinates in KDTree are stored as [lat, lon].
        """
        pts_list: List[Tuple[float, float]] = []
        ids_list: List[str] = []

        for seg_id, seg in self.segments.items():
            coords = seg.coords
            # Sample along each sub-segment
            for i in range(len(coords) - 1):
                lon1, lat1 = coords[i]
                lon2, lat2 = coords[i + 1]
                sub_len = haversine_distance(lat1, lon1, lat2, lon2)
                num_samples = max(1, int(math.ceil(sub_len / sample_spacing_m)))

                for s in range(num_samples):
                    frac = s / float(num_samples)
                    lat_s = lat1 + frac * (lat2 - lat1)
                    lon_s = lon1 + frac * (lon2 - lon1)
                    pts_list.append((lat_s, lon_s))
                    ids_list.append(seg_id)

            # Ensure endpoint is included
            last_lon, last_lat = coords[-1]
            pts_list.append((last_lat, last_lon))
            ids_list.append(seg_id)

        if pts_list:
            self.spatial_points = np.array(pts_list, dtype=np.float64)
            self.spatial_segment_ids = ids_list
            self.kdtree = cKDTree(self.spatial_points)
            logger.info("Spatial index built with %d sampled points over %d segments", len(pts_list), len(self.segments))
        else:
            self.kdtree = None

    def get_nearest_segments(self, lat: float, lon: float, radius_m: float = 50.0) -> List[RoadSegment]:
        """
        Find candidate road segments within radius_m meters of given (lat, lon).
        Falls back to the nearest segments if none are strictly within radius_m.
        """
        if self.kdtree is None or len(self.segments) == 0:
            return []

        # Convert radius in meters to approximate degrees for KD-tree bounding query
        # 1 deg lat ≈ 111,000 m
        deg_radius = max(radius_m, 50.0) / 111000.0

        indices = self.kdtree.query_ball_point([lat, lon], r=deg_radius)
        if not indices:
            # Fallback: query nearest points if none within ball
            k_val = min(15, len(self.spatial_points))
            _, idxs = self.kdtree.query([lat, lon], k=k_val)
            indices = list(idxs) if hasattr(idxs, "__iter__") else [idxs]

        candidate_ids = set()
        for idx in indices:
            if idx < len(self.spatial_segment_ids):
                candidate_ids.add(self.spatial_segment_ids[idx])

        # Filter and rank by exact distance
        candidates_with_dist: List[Tuple[float, RoadSegment]] = []
        for seg_id in candidate_ids:
            seg = self.segments.get(seg_id)
            if seg:
                dist = seg.distance_to_point(lat, lon)
                candidates_with_dist.append((dist, seg))

        candidates_with_dist.sort(key=lambda x: x[0])

        within_radius = [seg for dist, seg in candidates_with_dist if dist <= radius_m]
        if within_radius:
            return within_radius[:10]
        return [seg for _, seg in candidates_with_dist[:5]]

    def shortest_path_distance(self, node_u: str, node_v: str) -> float:
        """
        Compute the shortest network path distance between two nodes in meters using Dijkstra.
        """
        if node_u == node_v:
            return 0.0

        cache_key = (node_u, node_v)
        if cache_key in self._path_cache:
            return self._path_cache[cache_key]

        try:
            dist = nx.dijkstra_path_length(self.graph, node_u, node_v, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            dist = float("inf")

        # Cache result
        if len(self._path_cache) > 20000:
            self._path_cache.clear()
        self._path_cache[cache_key] = dist
        return dist

    def route_distance_between_segments(self, seg_a: RoadSegment, seg_b: RoadSegment) -> float:
        """
        Compute network distance from segment A to segment B.
        """
        if seg_a.id == seg_b.id:
            return 0.0

        # Direct connection if seg_a feeds into seg_b
        if seg_a.end_node == seg_b.start_node:
            return 0.5 * (seg_a.length + seg_b.length)

        # Distance from end of A to start of B
        graph_dist = self.shortest_path_distance(seg_a.end_node, seg_b.start_node)
        if math.isinf(graph_dist):
            # If not reachable via directed graph, check reverse/undirected distance with penalty
            try:
                if self._undirected_graph is None:
                    self._undirected_graph = self.graph.to_undirected()
                undirected_dist = nx.dijkstra_path_length(
                    self._undirected_graph, seg_a.end_node, seg_b.start_node, weight="weight"
                )
                return undirected_dist + 0.5 * (seg_a.length + seg_b.length) + 50.0
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return float("inf")

        return graph_dist + 0.5 * (seg_a.length + seg_b.length)

    def load_from_geojson(self, filepath: str) -> None:
        """Load road segments from a GeoJSON file and populate graph."""
        self.clear()

        # Check for companion graphml first for exact topology
        graphml_path = os.path.splitext(filepath)[0] + ".graphml"
        if os.path.isfile(graphml_path):
            try:
                self.graph = nx.read_graphml(graphml_path)
                logger.info("Loaded graph topology from companion %s", graphml_path)
            except Exception as e:
                logger.warning("Could not read graphml companion: %s", e)

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        features = data.get("features", [])
        node_id_counter = 1
        coord_to_node: Dict[Tuple[float, float], str] = {}

        for idx, feat in enumerate(features):
            geom = feat.get("geometry", {})
            if geom.get("type") != "LineString":
                continue

            coords = geom.get("coordinates", [])
            if len(coords) < 2:
                continue

            props = feat.get("properties", {})
            seg_id = str(feat.get("id", props.get("id", f"seg_{idx}")))

            # Map endpoints to graph node IDs
            start_coord = (round(coords[0][0], 7), round(coords[0][1], 7))
            end_coord = (round(coords[-1][0], 7), round(coords[-1][1], 7))

            if start_coord not in coord_to_node:
                coord_to_node[start_coord] = str(props.get("u", f"node_{node_id_counter}"))
                node_id_counter += 1
            if end_coord not in coord_to_node:
                coord_to_node[end_coord] = str(props.get("v", f"node_{node_id_counter}"))
                node_id_counter += 1

            u = coord_to_node[start_coord]
            v = coord_to_node[end_coord]

            name = props.get("name") or "Unnamed Road"
            highway = props.get("highway") or "unclassified"
            length = float(props.get("length", 0.0))
            oneway = bool(props.get("oneway", False))

            segment = RoadSegment(
                segment_id=seg_id,
                start_node=u,
                end_node=v,
                coords=coords,
                length=length,
                name=name,
                road_type=highway,
                oneway=oneway,
            )
            self.add_segment(segment)

        self.build_spatial_index()
        logger.info("Loaded %d segments into RoadNetwork from %s", len(self.segments), filepath)

    def load_from_osm(self, place_name: str) -> None:
        """Download road network from OpenStreetMap via OSMnx."""
        import osmnx as ox

        self.clear()
        logger.info("Downloading street network for '%s'...", place_name)
        G = ox.graph_from_place(place_name, network_type="drive", simplify=True)
        # Relabel nodes to strings so they match RoadSegment's str(start_node)
        G = nx.relabel_nodes(G, lambda node: str(node), copy=True)
        self.graph = G

        # Build segments from edges
        for u, v, k, data in G.edges(keys=True, data=True):
            seg_id = f"{u}_{v}_{k}"
            geom = data.get("geometry")
            if geom is not None:
                coords = list(geom.coords)
            else:
                coords = [(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])]

            name = data.get("name")
            if isinstance(name, list):
                name = name[0]
            name = str(name) if name else "Unnamed Road"

            highway = data.get("highway")
            if isinstance(highway, list):
                highway = highway[0]

            length = float(data.get("length", 0.0))
            oneway = bool(data.get("oneway", False))

            segment = RoadSegment(
                segment_id=seg_id,
                start_node=u,
                end_node=v,
                coords=coords,
                length=length,
                name=name,
                road_type=str(highway),
                oneway=oneway,
            )
            self.segments[seg_id] = segment

        self.build_spatial_index()
        logger.info("Downloaded %d segments from OSM for '%s'", len(self.segments), place_name)

    def load_from_bbox(self, north: float, south: float, east: float, west: float) -> None:
        """Download drivable roads for a bounded viewport, anywhere in the world."""
        import osmnx as ox

        self.clear()
        cache_key = self._viewport_cache_key(north, south, east, west)
        cache_path = os.path.join(Config.CACHE_DIR, "regions", f"{cache_key}.geojson")
        if os.path.isfile(cache_path):
            self.load_from_geojson(cache_path)
            logger.info("Loaded viewport road network from cache %s", cache_path)
            return

        params = inspect.signature(ox.graph_from_bbox).parameters
        endpoints = list(dict.fromkeys(filter(None, (
            Config.OSMNX_OVERPASS_URL, Config.OSMNX_FALLBACK_OVERPASS_URL
        ))))
        graph = None
        last_error = None
        # OSMnx settings are process-global, so only one provider request may run at a time.
        with _overpass_lock:
            original_url = ox.settings.overpass_url
            original_timeout = ox.settings.requests_timeout
            original_agent = getattr(ox.settings, "http_user_agent", None)
            try:
                ox.settings.requests_timeout = Config.OSMNX_REQUEST_TIMEOUT
                if hasattr(ox.settings, "http_user_agent"):
                    ox.settings.http_user_agent = Config.GEOCODER_USER_AGENT
                for endpoint in endpoints:
                    ox.settings.overpass_url = endpoint
                    try:
                        if "bbox" in params:
                            graph = ox.graph_from_bbox(
                                bbox=(west, south, east, north), network_type="drive", simplify=True
                            )
                        else:  # OSMnx 1.x uses positional north/south/east/west arguments.
                            graph = ox.graph_from_bbox(
                                north, south, east, west, network_type="drive", simplify=True
                            )
                        break
                    except Exception as exc:
                        last_error = exc
                        logger.warning("Overpass endpoint %s failed: %s", endpoint, exc)
            finally:
                ox.settings.overpass_url = original_url
                ox.settings.requests_timeout = original_timeout
                if original_agent is not None:
                    ox.settings.http_user_agent = original_agent
        if graph is None:
            raise RuntimeError("All configured Overpass endpoints failed") from last_error
        # RoadSegment stores node ids as strings, matching the cached GraphML path.
        graph = nx.relabel_nodes(graph, lambda node: str(node), copy=True)
        self.graph = graph
        for u, v, key, data in graph.edges(keys=True, data=True):
            geometry = data.get("geometry")
            coords = list(geometry.coords) if geometry is not None else [
                (graph.nodes[u]["x"], graph.nodes[u]["y"]),
                (graph.nodes[v]["x"], graph.nodes[v]["y"]),
            ]
            name = data.get("name", "Unnamed Road")
            highway = data.get("highway", "unclassified")
            if isinstance(name, list):
                name = name[0]
            if isinstance(highway, list):
                highway = highway[0]
            segment_id = f"{u}_{v}_{key}"
            self.segments[segment_id] = RoadSegment(
                segment_id, u, v, coords, float(data.get("length", 0.0)),
                str(name) if name else "Unnamed Road", str(highway), data.get("oneway", False)
            )
        self.build_spatial_index()
        self.save_to_geojson(cache_path)
        logger.info("Loaded %d road segments from viewport", len(self.segments))

    @staticmethod
    def _viewport_cache_key(north: float, south: float, east: float, west: float) -> str:
        """Create a stable filename for a bounded OSM download."""
        bounds = ",".join(f"{value:.4f}" for value in (north, south, east, west))
        return hashlib.sha256(bounds.encode("utf-8")).hexdigest()[:20]

    def save_to_geojson(self, filepath: str) -> None:
        """Export all road segments to a GeoJSON file."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        geojson_data = self.get_edges_geojson()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, indent=2)

        # Also save graphml if graph is available
        graphml_path = os.path.splitext(filepath)[0] + ".graphml"
        try:
            nx.write_graphml(self.graph, graphml_path)
            logger.info("Saved graphml companion to %s", graphml_path)
        except Exception as e:
            logger.warning("Could not write graphml companion: %s", e)

    def get_edges_geojson(self) -> Dict[str, Any]:
        """Return the road network as a GeoJSON FeatureCollection dictionary."""
        features = [seg.to_geojson_feature() for seg in self.segments.values()]
        return {
            "type": "FeatureCollection",
            "features": features,
        }
