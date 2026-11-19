from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from math import radians, sin, cos, atan2, sqrt, exp, isfinite, log
from pathlib import Path
import json

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

DATA_DIR = Path(__file__).parent / "data"


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = p2 - p1
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(max(0.0, 1 - a)))


def point_to_segment(p, a, b):
    lat, lon = p
    lat0, lon0 = a
    lat1, lon1 = b
    lat_scale = 111320.0
    lon_scale = 111320.0 * cos(radians(lat))
    ax, ay = lon0 * lon_scale, lat0 * lat_scale
    bx, by = lon1 * lon_scale, lat1 * lat_scale
    px, py = lon * lon_scale, lat * lat_scale
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return haversine_m(lat, lon, lat0, lon0), (lat0, lon0)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    closest = (lat0 + t * (lat1 - lat0), lon0 + t * (lon1 - lon0))
    return haversine_m(lat, lon, closest[0], closest[1]), closest


class HMMMapMatcher:
    """First-order HMM. States are road segments; observations are GPS fixes."""

    def __init__(self, sigma=25.0, beta=5.0, candidate_radius=120.0):
        self.sigma = sigma
        self.beta = beta
        self.candidate_radius = candidate_radius

    def emission(self, distance_m):
        if distance_m > self.candidate_radius:
            return -1e9
        return -0.5 * (distance_m / self.sigma) ** 2 - log(self.sigma * sqrt(2 * 3.141592653589793))

    def candidates(self, road_segments, point):
        ranked = []
        for segment in road_segments:
            distance, projection = point_to_segment(point, tuple(segment["coordinates"][0]), tuple(segment["coordinates"][1]))
            if distance <= self.candidate_radius:
                ranked.append((segment, distance, projection))
        return sorted(ranked, key=lambda x: x[1])

    def transition(self, previous, current, gps_previous, gps_current):
        route_distance = haversine_m(*previous[2], *current[2])
        gps_distance = haversine_m(gps_previous[0], gps_previous[1], gps_current[0], gps_current[1])
        difference = abs(route_distance - gps_distance)
        return -difference / self.beta

    def viterbi(self, observations, road_segments):
        if not observations:
            return {"states": [], "points": [], "score": None}
        candidates_by_time = [self.candidates(road_segments, p) for p in observations]
        if any(len(c) == 0 for c in candidates_by_time):
            return {"states": [], "points": [], "score": None, "error": "A GPS point has no road candidate within 120 m."}

        scores = {}
        paths = {}
        for candidate, distance, projection in candidates_by_time[0]:
            sid = candidate["id"]
            scores[sid] = self.emission(distance)
            paths[sid] = [sid]

        backpointers = []
        for t in range(1, len(observations)):
            new_scores = {}
            new_paths = {}
            bp = {}
            for cur in candidates_by_time[t]:
                cur_segment, cur_distance, cur_projection = cur
                cur_id = cur_segment["id"]
                best_prev = None
                best_score = float("-inf")
                for prev in candidates_by_time[t - 1]:
                    prev_segment, prev_distance, prev_projection = prev
                    prev_id = prev_segment["id"]
                    tr = self.transition(prev, cur, observations[t - 1], observations[t])
                    value = scores[prev_id] + tr + self.emission(cur_distance)
                    if value > best_score:
                        best_score = value
                        best_prev = prev_id
                if best_prev is not None:
                    new_scores[cur_id] = best_score
                    bp[cur_id] = best_prev
                    new_paths[cur_id] = paths[best_prev] + [cur_id]
            scores = new_scores
            paths = new_paths
            backpointers.append(bp)

        if not scores:
            return {"states": [], "points": [], "score": None}
        end_state = max(scores, key=scores.get)
        state_ids = paths[end_state]
        segments = {s["id"]: s for s in road_segments}
        matched = []
        for t, sid in enumerate(state_ids):
            segment = segments[sid]
            distance, projection = point_to_segment(observations[t], tuple(segment["coordinates"][0]), tuple(segment["coordinates"][1]))
            matched.append({"segment_id": sid, "observation": observations[t], "projection": projection, "distance_m": round(distance, 2)})
        return {"states": state_ids, "points": matched, "score": round(scores[end_state], 4)}


matcher = HMMMapMatcher()


def load_network():
    with open(DATA_DIR / "road_network.geojson", encoding="utf-8") as f:
        feature_collection = json.load(f)
    return [{"id": f["properties"]["id"], "name": f["properties"]["name"], "coordinates": f["geometry"]["coordinates"]} for f in feature_collection["features"]]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/network")
def network():
    return jsonify(json.load(open(DATA_DIR / "road_network.geojson", encoding="utf-8")))


@app.route("/api/match", methods=["POST"])
def match():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify(error="Request body must be valid JSON."), 400
    points = payload.get("points")
    if not isinstance(points, list):
        return jsonify(error="'points' must be a list."), 400
    observations = []
    for i, point in enumerate(points):
        try:
            lat = float(point["lat"])
            lon = float(point["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
            observations.append((lat, lon))
        except (KeyError, TypeError, ValueError):
            return jsonify(error=f"Invalid GPS point at index {i}."), 400
    if len(observations) < 2:
        return jsonify(error="At least two GPS points are required."), 400
    result = matcher.viterbi(observations, load_network())
    if result.get("error"):
        return jsonify(result), 422
    distances = [p["distance_m"] for p in result["points"]]
    result["metrics"] = {
        "mean_error_m": round(sum(distances) / len(distances), 2),
        "rmse_m": round(sqrt(sum(d * d for d in distances) / len(distances)), 2),
        "max_error_m": round(max(distances), 2),
        "matched_points": len(distances),
    }
    return jsonify(result)


@app.route("/api/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
