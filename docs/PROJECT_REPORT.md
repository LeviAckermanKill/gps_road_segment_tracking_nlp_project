# GPS Road Matching with HMM and Viterbi

## Abstract

This project is a web application for matching noisy GPS observations to a road network. It implements a Hidden Markov Model (HMM) whose hidden states are candidate directed road segments and whose observations are GPS coordinates. A log-space Viterbi decoder chooses a globally coherent route. Flask provides the API and Leaflet provides an interactive map for uploaded traces, supplied samples, and browser geolocation.

## Problem and objective

GPS error can place a recorded point beside the road or on a parallel street. Choosing the nearest road independently at every timestamp ignores route continuity. The project uses both spatial fit and movement continuity to infer a sequence of road segments. Its objective is a reproducible, inspectable educational implementation rather than a production navigation service.

## Method

For each GPS observation, the road network spatial index returns nearby segments. The observation-to-segment perpendicular distance (d) receives a Gaussian log emission score:

\[
\log P(z_t \mid s_t)=-\frac{1}{2}\left(\frac{d}{\sigma}\right)^2-\log(\sigma\sqrt{2\pi}).
\]

For adjacent observations and candidate segments, the transition score compares great-circle observation distance (d_{gps}) with shortest-path road distance (d_{route}):

\[
\log P(s_t \mid s_{t-1})=-\frac{|d_{gps}-d_{route}|}{\beta}-\log(\beta).
\]

The Viterbi recurrence maximizes the accumulated log score over candidate predecessors. Storing log probabilities avoids underflow for long traces. The selected states are projected to road geometry and serialized as a GeoJSON feature collection. The road-distance calculation uses graph routing; the web application does not call a map-matching API.

## Application design

The Flask service loads a cached road graph at startup, exposes matching/upload/live/sample/metrics endpoints, and returns structured JSON errors. The browser page sends traces to the service and draws raw observations, road network, and matched route using Leaflet. Worldwide street/topographic layers, place search, and browser location let users navigate beyond the sample city. A viewport endpoint downloads drivable OSM roads (each side limited to 20 km) so the same HMM can match in another region. Place queries pass through a configurable backend proxy with a per-process request limit and cache. Live GPS is collected through the browser Geolocation API and requires a secure browser context and permission. Search, map tiles, and road downloads require internet access.

## Data and evaluation

The sample route is a synthetic drive around Connaught Place, New Delhi. The generator interpolates hand-authored waypoints and adds seeded Gaussian noise to produce clean, typical, noisy, and sparse CSV traces, a GPX trace, and a coordinate reference. Evaluation aligns matched points to reference points by sequence index and reports error distances, RMSE, and the share within 15 metres. The UI's matching displacement metrics measure distance between GPS fixes and their selected road projections; they are not equivalent to ground-truth route accuracy.

Because both the route and reference are simulated, scores are a software demonstration only. They do not establish real-world performance. Hand-authored waypoints may also simplify actual road geometry and topology.

## Error handling and constraints

The API checks trace object structure, numeric finite coordinate values, WGS84 bounds, upload extensions, missing files, and minimum trace length. Uploads are capped at 16 MiB. Missing road data produces service-unavailable responses. Live matching uses a bounded recent window. OSM graph download requires network access if no valid cache exists. Leaflet and its tile layer are loaded from public web services, so an internet connection is needed for the map background.

## Validation plan

The test suite covers global Viterbi decoding, log-score behavior, empty candidate recovery, geodesic distance, and evaluation metrics. For a local acceptance check, start the server, confirm `/api/health`, load a sample from the UI, upload the included GPX or CSV, verify the route overlay and statistics, and call `/api/metrics`.

## Future improvements

Useful extensions include timestamp-aware transition priors, heading/speed observations, route geometry stitching that preserves segment direction, uncertainty-aware emissions using per-fix accuracy, real GPS ground truth, and benchmark comparisons against nearest-road baselines. A production service would also need authenticated access, deployment security controls, and careful retention policy for location data.
