# Sample GPS Data for Map Matching

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
