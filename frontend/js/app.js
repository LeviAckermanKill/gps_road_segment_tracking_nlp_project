/* ===================================================================
   App — Main controller for GPS Map Matching UI
   =================================================================== */

(function () {
    'use strict';

    var API_BASE = window.location.origin;
    var FETCH_TIMEOUT = 30000;

    var mapManager;
    var liveTracker;
    var liveMatchInterval = null;
    var selectedFile = null;

    /* ==================== Helpers ==================== */

    function fetchWithTimeout(url, options, timeoutMs) {
        options = options || {};
        var controller = new AbortController();
        var timeout = timeoutMs || FETCH_TIMEOUT;
        var timeoutId = setTimeout(function () { controller.abort(); }, timeout);
        options.signal = controller.signal;

        return fetch(url, options).then(function (response) {
            clearTimeout(timeoutId);
            return response;
        }).catch(function (err) {
            clearTimeout(timeoutId);
            if (err.name === 'AbortError') {
                throw new Error('Request timed out after ' + (timeout / 1000) + ' seconds.');
            }
            throw err;
        });
    }

    function showToast(message, type) {
        type = type || 'success';
        var container = document.getElementById('toast-container');
        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(function () {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(80px)';
            toast.style.transition = 'opacity 0.3s, transform 0.3s';
            setTimeout(function () {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300);
        }, 4000);
    }

    function showLoading() {
        document.getElementById('loading-overlay').classList.add('visible');
    }

    function hideLoading() {
        document.getElementById('loading-overlay').classList.remove('visible');
    }

    function showResults(stats) {
        // Backend names are explicit about units; map them to the display fields.
        if (stats.rmse === undefined && stats.rmse_m !== undefined) stats.rmse = stats.rmse_m;
        if (stats.accuracy === undefined && stats.accuracy_percentage !== undefined) {
            stats.accuracy = stats.accuracy_percentage;
        }
        if (stats.matched_segments === undefined && stats.matched_segments_count !== undefined) {
            stats.matched_segments = stats.matched_segments_count;
        }
        if (stats.num_points === undefined && stats.total_points !== undefined) {
            stats.num_points = stats.total_points;
        }
        var panel = document.getElementById('results-panel');
        document.getElementById('metric-points').textContent =
            stats.num_points !== undefined ? stats.num_points : (stats.points || '—');
        document.getElementById('metric-segments').textContent =
            stats.matched_segments !== undefined ? stats.matched_segments : (stats.segments || '—');
        document.getElementById('metric-time').textContent =
            stats.processing_time_ms !== undefined ? Math.round(stats.processing_time_ms) :
            (stats.processing_time !== undefined ? Math.round(stats.processing_time * 1000) : '—');

        var rmse = stats.rmse !== undefined ? stats.rmse : null;
        document.getElementById('metric-rmse').textContent =
            rmse !== null ? parseFloat(rmse).toFixed(2) : '—';

        var accuracy = stats.accuracy !== undefined ? stats.accuracy :
                       (stats.accuracy_percent !== undefined ? stats.accuracy_percent : null);
        if (accuracy !== null) {
            var pct = parseFloat(accuracy);
            if (pct <= 1 && pct > 0) pct = pct * 100;
            document.getElementById('metric-accuracy').textContent = pct.toFixed(1) + '%';
            document.getElementById('accuracy-bar-fill').style.width = Math.min(pct, 100) + '%';
        } else {
            document.getElementById('metric-accuracy').textContent = '—';
            document.getElementById('accuracy-bar-fill').style.width = '0%';
        }

        panel.classList.add('visible');
    }

    function parseCSV(text) {
        var lines = text.trim().split(/\r?\n/);
        if (lines.length < 2) return [];

        var header = lines[0].toLowerCase().split(',').map(function (h) { return h.trim(); });
        var latIdx = header.indexOf('lat') !== -1 ? header.indexOf('lat') : header.indexOf('latitude');
        var lonIdx = header.indexOf('lon') !== -1 ? header.indexOf('lon') :
                     (header.indexOf('lng') !== -1 ? header.indexOf('lng') : header.indexOf('longitude'));
        var tsIdx = header.indexOf('timestamp') !== -1 ? header.indexOf('timestamp') : header.indexOf('time');

        if (latIdx === -1 || lonIdx === -1) return [];

        var points = [];
        for (var i = 1; i < lines.length; i++) {
            var cols = lines[i].split(',').map(function (c) { return c.trim(); });
            if (cols.length <= Math.max(latIdx, lonIdx)) continue;
            var lat = parseFloat(cols[latIdx]);
            var lon = parseFloat(cols[lonIdx]);
            if (isNaN(lat) || isNaN(lon)) continue;

            var pt = { lat: lat, lon: lon };
            if (tsIdx !== -1 && cols[tsIdx]) pt.timestamp = cols[tsIdx];
            points.push(pt);
        }
        return points;
    }

    function extractStatsFromResult(data) {
        var stats = {};

        if (data.statistics) {
            stats = data.statistics;
        } else if (data.stats) {
            stats = data.stats;
        } else if (data.metrics) {
            stats = data.metrics;
        }

        // Fill in from top-level if not inside nested object
        if (data.num_points !== undefined) stats.num_points = data.num_points;
        if (data.matched_segments !== undefined) stats.matched_segments = data.matched_segments;
        if (data.processing_time_ms !== undefined) stats.processing_time_ms = data.processing_time_ms;
        if (data.processing_time !== undefined) stats.processing_time = data.processing_time;
        if (data.rmse !== undefined) stats.rmse = data.rmse;
        if (data.accuracy !== undefined) stats.accuracy = data.accuracy;

        // Try to count segments from GeoJSON
        if (stats.matched_segments === undefined && data.matched_route && data.matched_route.features) {
            stats.matched_segments = data.matched_route.features.length;
        }

        return stats;
    }

    function extractRawPoints(data) {
        if (data.raw_points) return data.raw_points;
        if (data.trace) return data.trace;
        if (data.original_points) return data.original_points;
        return null;
    }

    function extractMatchedGeoJSON(data) {
        if (data.matched_route) return data.matched_route;
        if (data.geojson) return data.geojson;
        if (data.result) return data.result;
        if (data.type === 'FeatureCollection' || data.type === 'Feature') return data;
        return null;
    }

    function extractMatchedPoints(data) {
        if (data.matched_points) return data.matched_points;
        if (data.snapped_points) return data.snapped_points;
        return null;
    }

    function handleMatchResult(data, rawPoints) {
        mapManager.clearAll();

        var geojson = extractMatchedGeoJSON(data);
        var exportButton = document.getElementById('btn-export-match');
        if (exportButton) exportButton.disabled = !geojson;
        var matchedPts = extractMatchedPoints(data);
        var originalPts = extractRawPoints(data) || rawPoints;

        if (originalPts && originalPts.length > 0) {
            mapManager.displayRawGps(originalPts);
        }

        if (geojson) {
            mapManager.displayMatchedRoute(geojson);
        }

        if (data.ground_truth) {
            mapManager.displayGroundTruth(data.ground_truth);
        }

        if (originalPts && matchedPts) {
            mapManager.showMatchComparison(originalPts, matchedPts);
        }

        // Fit bounds
        var boundsPoints = originalPts || matchedPts || [];
        if (boundsPoints.length > 0) {
            mapManager.fitBounds(boundsPoints);
        }

        // Stats
        var stats = extractStatsFromResult(data);
        if (originalPts) stats.num_points = stats.num_points || originalPts.length;
        showResults(stats);

        // Try loading road network in the background
        loadRoadNetwork();

        showToast('GPS trace matched successfully!', 'success');
    }

    function loadRoadNetwork() {
        fetchWithTimeout(API_BASE + '/api/road-network').then(function (resp) {
            if (!resp.ok) return;
            return resp.json();
        }).then(function (data) {
            if (data) mapManager.displayRoadNetwork(data);
        }).catch(function () {
            // Road network is optional — silently ignore
        });
    }

    /* ==================== World map tools ==================== */

    function setupWorldTools() {
        var searchInput = document.getElementById('place-search');
        var searchButton = document.getElementById('btn-place-search');
        var resultSelect = document.getElementById('place-results');
        var worldStatus = document.getElementById('world-status');
        var loadRoadsButton = document.getElementById('btn-load-roads');

        function findPlace() {
            var query = searchInput.value.trim();
            if (query.length < 3) {
                showToast('Enter at least 3 characters to search.', 'warning');
                return;
            }
            searchButton.disabled = true;
            worldStatus.textContent = 'Searching places…';
            var url = API_BASE + '/api/geocode?q=' + encodeURIComponent(query);
            fetchWithTimeout(url, {}, 15000)
                .then(function (response) {
                    if (!response.ok) throw new Error('Place search is temporarily unavailable.');
                    return response.json();
                })
                .then(function (data) {
                    var results = data.results || [];
                    resultSelect.innerHTML = '<option value="">Choose a place…</option>';
                    results.forEach(function (place, index) {
                        var option = document.createElement('option');
                        option.value = String(index);
                        option.textContent = place.display_name;
                        resultSelect.appendChild(option);
                    });
                    resultSelect.hidden = results.length === 0;
                    if (!results.length) {
                        worldStatus.textContent = 'No places found. Try a city or landmark name.';
                    } else {
                        resultSelect._places = results;
                        worldStatus.textContent = results.length + ' result(s). Select one to move the map.';
                    }
                })
                .catch(function (error) {
                    worldStatus.textContent = 'Place search failed. Check your internet connection and try again.';
                    showToast(error.message, 'error');
                })
                .finally(function () { searchButton.disabled = false; });
        }

        searchButton.addEventListener('click', findPlace);
        searchInput.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') findPlace();
        });
        resultSelect.addEventListener('change', function () {
            var index = parseInt(resultSelect.value, 10);
            var place = resultSelect._places && resultSelect._places[index];
            if (!place) return;
            var bounds = place.boundingbox;
            if (bounds && bounds.length === 4) {
                mapManager.map.fitBounds([
                    [parseFloat(bounds[0]), parseFloat(bounds[2])],
                    [parseFloat(bounds[1]), parseFloat(bounds[3])]
                ], { padding: [30, 30], maxZoom: 15 });
            } else {
                mapManager.map.setView([parseFloat(place.lat), parseFloat(place.lon)], 14);
            }
            worldStatus.textContent = 'Map centered on ' + place.name + '. Load roads in view to enable matching here.';
        });

        document.getElementById('btn-world-view').addEventListener('click', function () {
            mapManager.map.setView([18, 0], 2);
        });
        document.getElementById('btn-locate-me').addEventListener('click', function () {
            if (!navigator.geolocation) {
                showToast('Location is not supported by this browser.', 'error');
                return;
            }
            navigator.geolocation.getCurrentPosition(function (position) {
                mapManager.map.setView([position.coords.latitude, position.coords.longitude], 16);
                worldStatus.textContent = 'Map centered on your current location. Load roads in view to match here.';
            }, function () {
                showToast('Could not get your location. Check browser permission and location services.', 'error');
            }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 });
        });

        loadRoadsButton.addEventListener('click', function () {
            var bounds = mapManager.map.getBounds();
            var box = {
                north: bounds.getNorth(), south: bounds.getSouth(),
                east: bounds.getEast(), west: bounds.getWest()
            };
            loadRoadsButton.disabled = true;
            worldStatus.textContent = 'Fetching OSM road data for this viewport…';
            fetchWithTimeout(API_BASE + '/api/road-network/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(box)
            }, 180000).then(function (response) {
                return response.json().then(function (data) {
                    if (!response.ok) throw new Error(data.message || 'Could not load roads.');
                    return data;
                });
            }).then(function (data) {
                return fetchWithTimeout(API_BASE + '/api/road-network').then(function (response) {
                    if (!response.ok) throw new Error('Roads loaded, but the map layer could not be refreshed.');
                    return response.json();
                }).then(function (geojson) {
                    mapManager.displayRoadNetwork(geojson);
                    worldStatus.textContent = data.segments_count.toLocaleString() +
                        ' road segments loaded. HMM matching now uses this area.';
                    showToast('Road data loaded for this map area.', 'success');
                });
            }).catch(function (error) {
                worldStatus.textContent = error.message;
                showToast(error.message, 'error');
            }).finally(function () { loadRoadsButton.disabled = false; });
        });

        document.getElementById('btn-export-match').addEventListener('click', function () {
            var geojson = mapManager.matchedRouteLayer.toGeoJSON();
            if (!geojson.features || !geojson.features.length) return;
            var blob = new Blob([JSON.stringify(geojson, null, 2)], { type: 'application/geo+json' });
            var url = URL.createObjectURL(blob);
            var link = document.createElement('a');
            link.href = url;
            link.download = 'matched-route.geojson';
            link.click();
            setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        });
    }

    /* ==================== Dropzone ==================== */

    function setupDropzone() {
        var dropzone = document.getElementById('dropzone');
        var fileInput = document.getElementById('file-input');
        var fileNameEl = document.getElementById('file-name');
        var btnUpload = document.getElementById('btn-upload-match');

        dropzone.addEventListener('click', function () {
            fileInput.click();
        });

        dropzone.addEventListener('dragover', function (e) {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });

        dropzone.addEventListener('dragleave', function () {
            dropzone.classList.remove('dragover');
        });

        dropzone.addEventListener('drop', function (e) {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            var files = e.dataTransfer.files;
            if (files.length > 0) {
                handleFileSelect(files[0]);
            }
        });

        fileInput.addEventListener('change', function () {
            if (fileInput.files.length > 0) {
                handleFileSelect(fileInput.files[0]);
            }
        });

        function handleFileSelect(file) {
            var ext = file.name.split('.').pop().toLowerCase();
            if (ext !== 'csv' && ext !== 'gpx') {
                showToast('Please upload a .csv or .gpx file.', 'error');
                return;
            }
            selectedFile = file;
            fileNameEl.textContent = '✓ ' + file.name;
            dropzone.classList.add('has-file');
            btnUpload.disabled = false;
        }

        btnUpload.addEventListener('click', function () {
            if (!selectedFile) {
                showToast('Please select a file first.', 'warning');
                return;
            }
            uploadAndMatch(selectedFile);
        });
    }

    function uploadAndMatch(file) {
        showLoading();
        var formData = new FormData();
        formData.append('file', file);

        fetchWithTimeout(API_BASE + '/api/upload', {
            method: 'POST',
            body: formData
        }).then(function (resp) {
            if (!resp.ok) {
                return resp.json().then(function (err) {
                    throw new Error(err.error || err.message || 'Upload failed (HTTP ' + resp.status + ')');
                });
            }
            return resp.json();
        }).then(function (data) {
            hideLoading();
            handleMatchResult(data, null);
        }).catch(function (err) {
            hideLoading();
            showToast(err.message || 'Upload failed. Please try again.', 'error');
        });
    }

    /* ==================== Sample Data ==================== */

    function setupSampleData() {
        var select = document.getElementById('sample-select');
        var btnLoad = document.getElementById('btn-load-sample');

        select.addEventListener('change', function () {
            btnLoad.disabled = !select.value;
        });

        btnLoad.addEventListener('click', function () {
            var sampleName = select.value;
            if (!sampleName) {
                showToast('Please select a sample trace.', 'warning');
                return;
            }
            loadSample(sampleName);
        });

        // Try to populate dropdown dynamically
        fetchWithTimeout(API_BASE + '/api/sample-data').then(function (resp) {
            if (!resp.ok) return;
            return resp.json();
        }).then(function (data) {
            if (data && data.samples && data.samples.length > 0) {
                // Clear existing options except first
                while (select.options.length > 1) {
                    select.remove(1);
                }
                data.samples.forEach(function (name) {
                    var opt = document.createElement('option');
                    opt.value = name;
                    // Create a readable label
                    opt.textContent = name.replace(/sample_trace_/g, '').replace(/_/g, ' ')
                        .replace(/\b\w/g, function (l) { return l.toUpperCase(); }) + ' Trace';
                    select.appendChild(opt);
                });
            }
        }).catch(function () {
            // Keep static options as fallback
        });
    }

    function loadSample(sampleName) {
        showLoading();

        fetchWithTimeout(API_BASE + '/api/sample-data/' + encodeURIComponent(sampleName))
            .then(function (resp) {
                if (!resp.ok) {
                    return resp.json().then(function (err) {
                        throw new Error(err.error || 'Failed to load sample data.');
                    });
                }
                return resp.json();
            })
            .then(function (data) {
                var trace = data.trace || data.points || [];
                if (trace.length === 0) {
                    hideLoading();
                    showToast('Sample has no GPS points.', 'warning');
                    return;
                }

                // Now send the trace for matching
                return fetchWithTimeout(API_BASE + '/api/match', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ trace: trace })
                }).then(function (resp) {
                    if (!resp.ok) {
                        return resp.json().then(function (err) {
                            throw new Error(err.error || 'Matching failed.');
                        });
                    }
                    return resp.json();
                }).then(function (matchData) {
                    hideLoading();
                    handleMatchResult(matchData, trace);
                });
            })
            .catch(function (err) {
                hideLoading();
                showToast(err.message || 'Failed to load sample.', 'error');
            });
    }

    /* ==================== Live GPS ==================== */

    function setupLiveGPS() {
        var btnStart = document.getElementById('btn-start-live');
        var btnStop = document.getElementById('btn-stop-live');
        var statusDot = document.getElementById('status-dot');
        var statusText = document.getElementById('status-text');
        var pointCounter = document.getElementById('point-counter');

        function onLivePoint(point, count, errorMsg) {
            if (errorMsg) {
                showToast(errorMsg, 'error');
                stopTracking();
                return;
            }

            pointCounter.textContent = count + ' pts';

            // Periodically send for live matching (every 5 points)
            if (count >= 2 && count % 2 === 0) {
                var allPts = liveTracker.getPoints();
                fetchWithTimeout(API_BASE + '/api/match-live', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        // The endpoint appends new_point itself.
                        points: allPts.slice(0, -1),
                        new_point: point
                    })
                }).then(function (resp) {
                    if (resp.ok) return resp.json();
                }).then(function (data) {
                    if (data) {
                        var geojson = extractMatchedGeoJSON(data);
                        if (geojson) {
                            mapManager.matchedRouteLayer.clearLayers();
                            mapManager.displayMatchedRoute(geojson);
                        }
                    }
                }).catch(function () {
                    // Live matching failures are non-critical
                });
            }
        }

        liveTracker = new LiveGPSTracker(mapManager, onLivePoint);

        function startTracking() {
            try {
                mapManager.clearLive();
                liveTracker.clearPoints();
                liveTracker.start();

                btnStart.style.display = 'none';
                btnStop.style.display = '';
                statusDot.classList.add('status-active');
                statusText.textContent = 'Tracking…';
                pointCounter.textContent = '0 pts';

                showToast('Live GPS tracking started.', 'info');
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        function stopTracking() {
            liveTracker.stop();

            btnStart.style.display = '';
            btnStop.style.display = 'none';
            statusDot.classList.remove('status-active');
            statusText.textContent = 'Inactive';

            showToast('Live tracking stopped.', 'info');

            // Final match on all accumulated points
            var points = liveTracker.getPoints();
            if (points.length >= 2) {
                showLoading();
                fetchWithTimeout(API_BASE + '/api/match', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ trace: points })
                }).then(function (resp) {
                    if (!resp.ok) throw new Error('Final matching failed.');
                    return resp.json();
                }).then(function (data) {
                    hideLoading();
                    handleMatchResult(data, points);
                }).catch(function (err) {
                    hideLoading();
                    showToast(err.message, 'error');
                });
            } else if (points.length > 0) {
                showToast('Need at least 2 points for matching.', 'warning');
            }
        }

        btnStart.addEventListener('click', startTracking);
        btnStop.addEventListener('click', stopTracking);
    }

    /* ==================== Init ==================== */

    document.addEventListener('DOMContentLoaded', function () {
        mapManager = new MapManager();
        setupDropzone();
        setupSampleData();
        setupLiveGPS();
        setupWorldTools();

        // Health check
        fetchWithTimeout(API_BASE + '/api/health').then(function (resp) {
            if (resp.ok) {
                showToast('Connected to backend.', 'success');
            } else {
                showToast('Backend returned status ' + resp.status + '.', 'warning');
            }
        }).catch(function () {
            showToast('Cannot reach backend server. Some features may not work.', 'error');
        });
    });

})();
