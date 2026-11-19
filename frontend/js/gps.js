/* ===================================================================
   LiveGPSTracker — Browser Geolocation API wrapper
   =================================================================== */

class LiveGPSTracker {
    constructor(mapManager, onPointCallback) {
        this._mapManager = mapManager;
        this._onPointCallback = onPointCallback;
        this._watchId = null;
        this._points = [];
        this._lastUpdate = null;
    }

    /* ---- Public API ---- */

    get isTracking() {
        return this._watchId !== null;
    }

    start() {
        if (this.isTracking) return;

        if (!navigator.geolocation) {
            throw new Error('Geolocation is not supported by your browser.');
        }

        this._watchId = navigator.geolocation.watchPosition(
            this._onSuccess.bind(this),
            this._onError.bind(this),
            {
                enableHighAccuracy: true,
                maximumAge: 2000,
                timeout: 10000
            }
        );
    }

    stop() {
        if (this._watchId !== null) {
            navigator.geolocation.clearWatch(this._watchId);
            this._watchId = null;
        }
    }

    getPoints() {
        return this._points.slice();
    }

    clearPoints() {
        this._points = [];
        this._lastUpdate = null;
    }

    getStatus() {
        return {
            tracking: this.isTracking,
            pointCount: this._points.length,
            lastUpdate: this._lastUpdate
        };
    }

    /* ---- Internal ---- */

    _onSuccess(position) {
        var coords = position.coords;
        var point = {
            lat: coords.latitude,
            lon: coords.longitude,
            timestamp: new Date(position.timestamp).toISOString(),
            accuracy: coords.accuracy ? Math.round(coords.accuracy) : null
        };

        this._points.push(point);
        this._lastUpdate = point.timestamp;

        // Update map
        if (this._mapManager) {
            this._mapManager.addLivePoint(point.lat, point.lon);
        }

        // Callback
        if (typeof this._onPointCallback === 'function') {
            this._onPointCallback(point, this._points.length);
        }
    }

    _onError(error) {
        var message;
        switch (error.code) {
            case error.PERMISSION_DENIED:
                message = 'Location permission denied. Please allow location access in your browser settings.';
                break;
            case error.POSITION_UNAVAILABLE:
                message = 'Position unavailable. Make sure GPS/location services are enabled on your device.';
                break;
            case error.TIMEOUT:
                message = 'Location request timed out. Please try again or move to an area with better signal.';
                break;
            default:
                message = 'An unknown geolocation error occurred.';
                break;
        }

        this.stop();

        if (typeof this._onPointCallback === 'function') {
            this._onPointCallback(null, 0, message);
        }
    }
}
