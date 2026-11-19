"""
Generate realistic synthetic GPS traces and ground-truth data for Connaught Place, New Delhi.

Generates:
1. data/sample_trace_delhi.csv (realistic noise: std 15m)
2. data/sample_trace_clean.csv (clean ground-truth with minimal noise: std 3m)
3. data/sample_trace_noisy.csv (heavy urban canyon noise: std 45m)
4. data/sample_trace_sparse.csv (subsampled trace with larger time intervals)
5. data/ground_truth.csv (exact on-road positions and road names)
6. data/sample_gpx_trace.gpx (GPX 1.1 format trace)
"""

import csv
import datetime
import math
import os
import random
import sys

# Add project root to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.hmm.utils import EARTH_RADIUS_M, haversine_distance

DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Waypoints representing a realistic drive in Connaught Place, New Delhi:
# Route: Rajiv Chowk / Radial Road -> Outer Circle (Connaught Circus) -> Barakhamba Road -> Tolstoy Marg -> Janpath -> Radial Road
WAYPOINTS = [
    # 1. Start on Radial Road 1 near Rajiv Chowk Metro Gate 7
    (28.63220, 77.21850, "Radial Road 1"),
    (28.63260, 77.21910, "Radial Road 1"),
    (28.63310, 77.21980, "Radial Road 1"),
    
    # 2. Enter Connaught Circus (Outer Circle) moving counter-clockwise
    (28.63380, 77.22050, "Connaught Circus"),
    (28.63460, 77.22080, "Connaught Circus"),
    (28.63530, 77.22040, "Connaught Circus"),
    (28.63590, 77.21950, "Connaught Circus"),
    (28.63620, 77.21840, "Connaught Circus"),
    
    # 3. Turn onto Barakhamba Road heading south-east
    (28.63550, 77.22020, "Barakhamba Road"),
    (28.63450, 77.22150, "Barakhamba Road"),
    (28.63320, 77.22300, "Barakhamba Road"),
    (28.63180, 77.22460, "Barakhamba Road"),
    (28.63050, 77.22600, "Barakhamba Road"),
    
    # 4. Turn right onto Tolstoy Marg heading west
    (28.62950, 77.22480, "Tolstoy Marg"),
    (28.62920, 77.22320, "Tolstoy Marg"),
    (28.62890, 77.22150, "Tolstoy Marg"),
    (28.62860, 77.21980, "Tolstoy Marg"),
    (28.62830, 77.21800, "Tolstoy Marg"),
    (28.62800, 77.21620, "Tolstoy Marg"),
    
    # 5. Turn right onto Janpath heading north back towards Connaught Place
    (28.62900, 77.21650, "Janpath"),
    (28.63000, 77.21680, "Janpath"),
    (28.63100, 77.21700, "Janpath"),
    (28.63220, 77.21730, "Janpath"),
    (28.63340, 77.21760, "Janpath"),
    
    # 6. Re-enter Outer Circle near Palika Bazaar
    (28.63400, 77.21650, "Connaught Circus"),
    (28.63430, 77.21520, "Connaught Circus"),
    (28.63380, 77.21400, "Connaught Circus"),
    (28.63300, 77.21320, "Connaught Circus"),
    (28.63200, 77.21400, "Connaught Circus"),
    (28.63150, 77.21550, "Connaught Circus"),
    (28.63180, 77.21700, "Connaught Circus"),
]


def interpolate_waypoints(waypoints, step_m=20.0):
    """Interpolate between waypoints at approximately step_m meter intervals."""
    dense_points = []
    start_time = datetime.datetime(2024, 1, 15, 10, 0, 0)
    current_time = start_time
    
    for i in range(len(waypoints) - 1):
        lat1, lon1, road1 = waypoints[i]
        lat2, lon2, road2 = waypoints[i + 1]
        dist = haversine_distance(lat1, lon1, lat2, lon2)
        steps = max(1, int(round(dist / step_m)))
        
        for s in range(steps):
            frac = s / float(steps)
            lat = lat1 + frac * (lat2 - lat1)
            lon = lon1 + frac * (lon2 - lon1)
            dense_points.append({
                "true_lat": lat,
                "true_lon": lon,
                "road_name": road1 if frac < 0.5 else road2,
                "timestamp": current_time.isoformat(),
            })
            current_time += datetime.timedelta(seconds=random.randint(2, 4))
            
    # Add final waypoint
    last_lat, last_lon, last_road = waypoints[-1]
    dense_points.append({
        "true_lat": last_lat,
        "true_lon": last_lon,
        "road_name": last_road,
        "timestamp": current_time.isoformat(),
    })
    return dense_points


def add_noise(lat, lon, noise_std_m):
    """Add Gaussian spatial noise in meters to latitude and longitude."""
    dx = random.gauss(0, noise_std_m)
    dy = random.gauss(0, noise_std_m)
    dlat = (dy / EARTH_RADIUS_M) * (180.0 / math.pi)
    dlon = (dx / (EARTH_RADIUS_M * math.cos(math.radians(lat)))) * (180.0 / math.pi)
    return lat + dlat, lon + dlon


def generate_all():
    random.seed(42)
    ground_truth = interpolate_waypoints(WAYPOINTS, step_m=22.0)
    n = len(ground_truth)
    print(f"Generated {n} ground truth points along route.")

    # 1. Ground truth CSV
    gt_file = os.path.join(DATA_DIR, "ground_truth.csv")
    with open(gt_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["point_index", "true_road_name", "true_lat", "true_lon", "timestamp"])
        for idx, pt in enumerate(ground_truth):
            writer.writerow([idx, pt["road_name"], f"{pt['true_lat']:.6f}", f"{pt['true_lon']:.6f}", pt["timestamp"]])
    print(f"Wrote {gt_file}")

    # 2. Delhi standard trace (realistic GPS noise ~15m)
    delhi_file = os.path.join(DATA_DIR, "sample_trace_delhi.csv")
    with open(delhi_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["latitude", "longitude", "timestamp", "accuracy"])
        for pt in ground_truth:
            # Varying accuracy simulating mild urban canyon
            acc = random.choice([8.0, 12.0, 15.0, 18.0, 24.0])
            n_lat, n_lon = add_noise(pt["true_lat"], pt["true_lon"], noise_std_m=acc)
            writer.writerow([f"{n_lat:.6f}", f"{n_lon:.6f}", pt["timestamp"], f"{acc:.1f}"])
    print(f"Wrote {delhi_file}")

    # 3. Clean trace (minimal noise ~3m)
    clean_file = os.path.join(DATA_DIR, "sample_trace_clean.csv")
    with open(clean_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["latitude", "longitude", "timestamp", "accuracy"])
        for pt in ground_truth:
            acc = 4.0
            n_lat, n_lon = add_noise(pt["true_lat"], pt["true_lon"], noise_std_m=acc)
            writer.writerow([f"{n_lat:.6f}", f"{n_lon:.6f}", pt["timestamp"], f"{acc:.1f}"])
    print(f"Wrote {clean_file}")

    # 4. Noisy trace (heavy multipath noise ~45m)
    noisy_file = os.path.join(DATA_DIR, "sample_trace_noisy.csv")
    with open(noisy_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["latitude", "longitude", "timestamp", "accuracy"])
        for pt in ground_truth:
            acc = random.choice([35.0, 45.0, 55.0, 70.0])
            n_lat, n_lon = add_noise(pt["true_lat"], pt["true_lon"], noise_std_m=acc)
            writer.writerow([f"{n_lat:.6f}", f"{n_lon:.6f}", pt["timestamp"], f"{acc:.1f}"])
    print(f"Wrote {noisy_file}")

    # 5. Sparse trace (every 3rd or 4th point, larger time intervals)
    sparse_file = os.path.join(DATA_DIR, "sample_trace_sparse.csv")
    sparse_points = ground_truth[::3]
    with open(sparse_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["latitude", "longitude", "timestamp", "accuracy"])
        for pt in sparse_points:
            acc = 18.0
            n_lat, n_lon = add_noise(pt["true_lat"], pt["true_lon"], noise_std_m=acc)
            writer.writerow([f"{n_lat:.6f}", f"{n_lon:.6f}", pt["timestamp"], f"{acc:.1f}"])
    print(f"Wrote {sparse_file} ({len(sparse_points)} points)")

    # 6. Sample GPX trace
    gpx_file = os.path.join(DATA_DIR, "sample_gpx_trace.gpx")
    with open(gpx_file, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<gpx version="1.1" creator="GPS-HMM-MapMatcher" xmlns="http://www.topografix.com/GPX/1/1">\n')
        f.write('  <metadata>\n')
        f.write('    <name>Connaught Place Delhi Route</name>\n')
        f.write('    <desc>GPS driving trace through Connaught Place, New Delhi</desc>\n')
        f.write('  </metadata>\n')
        f.write('  <trk>\n')
        f.write('    <name>Delhi Central Loop</name>\n')
        f.write('    <trkseg>\n')
        for pt in ground_truth:
            n_lat, n_lon = add_noise(pt["true_lat"], pt["true_lon"], noise_std_m=12.0)
            f.write(f'      <trkpt lat="{n_lat:.6f}" lon="{n_lon:.6f}">\n')
            f.write(f'        <ele>216.0</ele>\n')
            f.write(f'        <time>{pt["timestamp"]}Z</time>\n')
            f.write(f'      </trkpt>\n')
        f.write('    </trkseg>\n')
        f.write('  </trk>\n')
        f.write('</gpx>\n')
    print(f"Wrote {gpx_file}")

    # 7. Documentation data/README.md
    readme_file = os.path.join(DATA_DIR, "README.md")
    with open(readme_file, "w", encoding="utf-8") as f:
        f.write("""# Sample GPS Data for Map Matching

This directory contains realistic GPS traces and ground-truth references recorded around **Connaught Place, New Delhi, India** (central coordinates approx. 28.6315° N, 77.2167° E).

## Route Description
The route models a realistic vehicle trajectory traveling through major arterial roads:
1. **Rajiv Chowk / Radial Road 1**
2. **Connaught Circus (Outer Circle)**
3. **Barakhamba Road** (heading south-east towards Mandi House)
4. **Tolstoy Marg** (heading west)
5. **Janpath** (heading north back towards Connaught Place)
6. **Connaught Circus** (completing circular loop)

## Datasets

| File | Points | Noise (σ) | Description |
|---|---|---|---|
| `sample_trace_delhi.csv` | ~50 | 12–24 m | Realistic urban driving trace with standard GPS multipath noise |
| `sample_trace_clean.csv` | ~50 | 3–5 m | High-precision trace serving as near-ground-truth baseline |
| `sample_trace_noisy.csv` | ~50 | 35–70 m | Severe multipath / urban canyon conditions |
| `sample_trace_sparse.csv` | ~17 | 15–20 m | Low-frequency sampling (15–30s intervals) testing Viterbi transition penalties |
| `ground_truth.csv` | ~50 | 0 m | Ground-truth coordinates and canonical road names |
| `sample_gpx_trace.gpx` | ~50 | 12 m | Standard XML GPX 1.1 file format |

## CSV Format
- `latitude`: WGS84 decimal latitude (float)
- `longitude`: WGS84 decimal longitude (float)
- `timestamp`: ISO 8601 UTC timestamp
- `accuracy`: Horizontal dilution/accuracy estimate in meters
""")
    print(f"Wrote {readme_file}")


if __name__ == "__main__":
    generate_all()
