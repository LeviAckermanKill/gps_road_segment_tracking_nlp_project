/* ===================================================================
   MapManager — Leaflet map wrapper for GPS Map Matching
   =================================================================== */

class MapManager {
    constructor() {
        this.map = L.map('map-container', {
            center: [18, 0],
            zoom: 2,
            zoomControl: false
        });

        var streets = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        }).addTo(this.map);
        var topographic = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
            attribution: 'Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap',
            maxZoom: 17
        });

        // Zoom control — top-right
        L.control.zoom({ position: 'topright' }).addTo(this.map);

        // Scale control — bottom-left
        L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(this.map);

        // Layer groups
        this.rawGpsLayer = L.layerGroup().addTo(this.map);
        this.matchedRouteLayer = L.layerGroup().addTo(this.map);
        this.groundTruthLayer = L.layerGroup().addTo(this.map);
        this.roadNetworkLayer = L.layerGroup().addTo(this.map);
        this.liveGpsLayer = L.layerGroup().addTo(this.map);
        this.comparisonLayer = L.layerGroup().addTo(this.map);

        // Layer control
        var overlays = {
            'Raw GPS Points': this.rawGpsLayer,
            'Matched Route': this.matchedRouteLayer,
            'Ground Truth': this.groundTruthLayer,
            'Road Network': this.roadNetworkLayer,
            'Live GPS': this.liveGpsLayer,
            'Comparison Lines': this.comparisonLayer
        };
        L.control.layers({ 'Street map': streets, 'Topographic': topographic }, overlays,
            { position: 'topright', collapsed: true }).addTo(this.map);

        // Live tracking state
        this._liveTrail = [];
        this._liveTrailLine = null;
        this._liveMarker = null;
    }

    /* ---- Raw GPS Points ---- */
    displayRawGps(points) {
        this.rawGpsLayer.clearLayers();
        if (!points || points.length === 0) return;

        points.forEach(function (pt, idx) {
            var lat = parseFloat(pt.lat || pt.latitude);
            var lon = parseFloat(pt.lon || pt.lng || pt.longitude);
            if (isNaN(lat) || isNaN(lon)) return;

            var marker = L.circleMarker([lat, lon], {
                radius: 6,
                color: '#ef4444',
                fillColor: '#ef4444',
                fillOpacity: 0.7,
                weight: 2
            });

            var popupContent = '<b>GPS Point #' + (idx + 1) + '</b><br>' +
                'Lat: ' + lat.toFixed(6) + '<br>' +
                'Lon: ' + lon.toFixed(6);
            if (pt.timestamp) popupContent += '<br>Time: ' + pt.timestamp;
            if (pt.accuracy) popupContent += '<br>Accuracy: ' + pt.accuracy + ' m';

            marker.bindPopup(popupContent);
            this.rawGpsLayer.addLayer(marker);
        }.bind(this));
    }

    /* ---- Matched Route (GeoJSON) ---- */
    displayMatchedRoute(geojson) {
        this.matchedRouteLayer.clearLayers();
        if (!geojson) return;

        var geoLayer = L.geoJSON(geojson, {
            style: function () {
                return {
                    color: '#2563eb',
                    weight: 5,
                    opacity: 0.8,
                    lineJoin: 'round',
                    lineCap: 'round'
                };
            },
            onEachFeature: function (feature, layer) {
                if (feature.properties) {
                    var props = feature.properties;
                    var html = '<b>Matched Segment</b>';
                    if (props.road_name || props.name) html += '<br>Road: ' + (props.road_name || props.name);
                    if (props.segment_id !== undefined) html += '<br>Segment ID: ' + props.segment_id;
                    if (props.distance !== undefined) html += '<br>Distance: ' + parseFloat(props.distance).toFixed(1) + ' m';
                    if (props.confidence !== undefined) html += '<br>Confidence: ' + (parseFloat(props.confidence) * 100).toFixed(0) + '%';
                    layer.bindPopup(html);
                }
            },
            pointToLayer: function (feature, latlng) {
                return L.circleMarker(latlng, {
                    radius: 5,
                    color: '#2563eb',
                    fillColor: '#2563eb',
                    fillOpacity: 0.8,
                    weight: 2
                });
            }
        });

        this.matchedRouteLayer.addLayer(geoLayer);
    }

    /* ---- Ground Truth ---- */
    displayGroundTruth(points) {
        this.groundTruthLayer.clearLayers();
        if (!points || points.length < 2) return;

        var latlngs = points.map(function (pt) {
            return [parseFloat(pt.lat || pt.latitude), parseFloat(pt.lon || pt.lng || pt.longitude)];
        }).filter(function (ll) {
            return !isNaN(ll[0]) && !isNaN(ll[1]);
        });

        if (latlngs.length < 2) return;

        var line = L.polyline(latlngs, {
            color: '#22c55e',
            weight: 4,
            opacity: 0.7,
            dashArray: '10 8',
            lineJoin: 'round'
        });

        this.groundTruthLayer.addLayer(line);
    }

    /* ---- Road Network (GeoJSON) ---- */
    displayRoadNetwork(geojson) {
        this.roadNetworkLayer.clearLayers();
        if (!geojson) return;

        var geoLayer = L.geoJSON(geojson, {
            style: function () {
                return {
                    color: '#94a3b8',
                    weight: 1,
                    opacity: 0.3
                };
            },
            onEachFeature: function (feature, layer) {
                if (feature.properties && (feature.properties.name || feature.properties.road_name)) {
                    layer.bindPopup(feature.properties.name || feature.properties.road_name);
                }
            }
        });

        this.roadNetworkLayer.addLayer(geoLayer);
    }

    /* ---- Live GPS Point ---- */
    addLivePoint(lat, lon) {
        lat = parseFloat(lat);
        lon = parseFloat(lon);
        if (isNaN(lat) || isNaN(lon)) return;

        this._liveTrail.push([lat, lon]);

        // Remove old pulsing marker
        if (this._liveMarker) {
            this.liveGpsLayer.removeLayer(this._liveMarker);
        }

        // Current position marker (pulsing)
        this._liveMarker = L.circleMarker([lat, lon], {
            radius: 10,
            color: '#2563eb',
            fillColor: '#60a5fa',
            fillOpacity: 0.8,
            weight: 3,
            className: 'live-pulse-marker'
        });
        this._liveMarker.bindPopup('<b>Current Position</b><br>Lat: ' + lat.toFixed(6) + '<br>Lon: ' + lon.toFixed(6));
        this.liveGpsLayer.addLayer(this._liveMarker);

        // Trail line
        if (this._liveTrailLine) {
            this._liveTrailLine.setLatLngs(this._liveTrail);
        } else {
            this._liveTrailLine = L.polyline(this._liveTrail, {
                color: '#60a5fa',
                weight: 3,
                opacity: 0.6,
                dashArray: '6 4'
            });
            this.liveGpsLayer.addLayer(this._liveTrailLine);
        }

        this.map.panTo([lat, lon]);
    }

    /* ---- Show Match Comparison (connecting lines) ---- */
    showMatchComparison(rawPoints, matchedPoints) {
        this.comparisonLayer.clearLayers();
        if (!rawPoints || !matchedPoints) return;

        var len = Math.min(rawPoints.length, matchedPoints.length);
        for (var i = 0; i < len; i++) {
            var rawLat = parseFloat(rawPoints[i].lat || rawPoints[i].latitude);
            var rawLon = parseFloat(rawPoints[i].lon || rawPoints[i].lng || rawPoints[i].longitude);
            var mLat = parseFloat(matchedPoints[i].lat || matchedPoints[i].latitude);
            var mLon = parseFloat(matchedPoints[i].lon || matchedPoints[i].lng || matchedPoints[i].longitude);

            if (isNaN(rawLat) || isNaN(rawLon) || isNaN(mLat) || isNaN(mLon)) continue;

            var line = L.polyline([[rawLat, rawLon], [mLat, mLon]], {
                color: '#94a3b8',
                weight: 1,
                opacity: 0.5,
                dashArray: '4 4'
            });
            this.comparisonLayer.addLayer(line);
        }
    }

    /* ---- Clear ---- */
    clearAll() {
        this.rawGpsLayer.clearLayers();
        this.matchedRouteLayer.clearLayers();
        this.groundTruthLayer.clearLayers();
        this.roadNetworkLayer.clearLayers();
        this.comparisonLayer.clearLayers();
        this.clearLive();
    }

    clearLive() {
        this.liveGpsLayer.clearLayers();
        this._liveTrail = [];
        this._liveTrailLine = null;
        this._liveMarker = null;
    }

    /* ---- Fit Bounds ---- */
    fitBounds(points) {
        if (!points || points.length === 0) return;

        var latlngs = points.map(function (pt) {
            return [parseFloat(pt.lat || pt.latitude), parseFloat(pt.lon || pt.lng || pt.longitude)];
        }).filter(function (ll) {
            return !isNaN(ll[0]) && !isNaN(ll[1]);
        });

        if (latlngs.length === 0) return;

        var bounds = L.latLngBounds(latlngs);
        this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
    }
}
