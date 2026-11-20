"""Configuration settings for the GPS Map Matching application."""

import os


class Config:
    """Application configuration with environment variable overrides."""

    DEFAULT_CITY = os.environ.get("MAP_MATCH_CITY", "Connaught Place, New Delhi, India")
    GPS_NOISE_STD = float(os.environ.get("GPS_NOISE_STD", "20.0"))
    CANDIDATE_RADIUS = float(os.environ.get("CANDIDATE_RADIUS", "50.0"))
    BETA = float(os.environ.get("BETA", "10.0"))

    GEOCODER_URL = os.environ.get("GEOCODER_URL", "https://nominatim.openstreetmap.org/search")
    GEOCODER_USER_AGENT = os.environ.get(
        "GEOCODER_USER_AGENT", "GPSRoadMatchingDemo/1.0 (educational application)"
    )

    OSMNX_OVERPASS_URL = os.environ.get("OSMNX_OVERPASS_URL", "https://overpass-api.de/api")
    OSMNX_FALLBACK_OVERPASS_URL = os.environ.get(
        "OSMNX_FALLBACK_OVERPASS_URL", "https://overpass.private.coffee/api"
    )
    OSMNX_REQUEST_TIMEOUT = int(os.environ.get("OSMNX_REQUEST_TIMEOUT", "60"))
    MAX_NETWORK_LOAD_SIDE_M = int(os.environ.get("MAX_NETWORK_LOAD_SIDE_M", "8000"))

    MAX_UPLOAD_SIZE = 16 * 1024 * 1024

    CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
