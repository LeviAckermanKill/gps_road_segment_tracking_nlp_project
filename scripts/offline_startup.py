"""Make the project work from a fresh clone, including an offline Delhi fallback."""

import os

from backend.config import Config
from backend.hmm.fallback_network import build_delhi_fallback_network


def _load_road_network():
    import os

    cache_path = os.path.join(Config.CACHE_DIR, "road_network.geojson")

    network = build_delhi_fallback_network()

    if os.path.isfile(cache_path):
        try:
            cached = type(network)()
            cached.load_from_geojson(cache_path)
            if len(cached):
                return cached
        except Exception:
            pass

    try:
        import osmnx as ox
        bbox = (28.620, 28.642, 77.208, 77.228)
        graph = ox.graph_from_bbox(bbox=bbox, network_type="drive", simplify=True)
        if len(graph):
            downloaded = type(network)()
            downloaded.graph = graph
            for u, v, key, data in graph.edges(keys=True, data=True):
                from backend.hmm.road_network import RoadSegment
                geometry = data.get("geometry")
                coords = list(geometry.coords) if geometry is not None else [
                    (graph.nodes[u]["x"], graph.nodes[u]["y"]),
                    (graph.nodes[v]["x"], graph.nodes[v]["y"]),
                ]
                name = data.get("name", "Unnamed Road")
                if isinstance(name, list):
                    name = name[0]
                highway = data.get("highway", "unclassified")
                if isinstance(highway, list):
                    highway = highway[0]
                seg = RoadSegment(
                    f"{u}_{v}_{key}", str(u), str(v), coords,
                    float(data.get("length", 0.0)), str(name), str(highway),
                    bool(data.get("oneway", False)),
                )
                downloaded.add_segment(seg)
            downloaded.build_spatial_index()
            try:
                downloaded.save_to_geojson(cache_path)
            except Exception:
                pass
            return downloaded
    except Exception:
        pass

    return network
