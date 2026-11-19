import pytest
from app import app, HMMMapMatcher, haversine_m


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    return app.test_client()


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_match(client):
    points = [{"lat": 51.5050, "lon": -0.0902}, {"lat": 51.5058, "lon": -0.0892}, {"lat": 51.5067, "lon": -0.0881}]
    response = client.post("/api/match", json={"points": points})
    assert response.status_code in (200, 422)


def test_invalid_point(client):
    response = client.post("/api/match", json={"points": [{"lat": 100, "lon": 0}]})
    assert response.status_code == 400


def test_viterbi_returns_route():
    matcher = HMMMapMatcher()
    segments = [{"id": "a", "coordinates": [[51.5, -0.09], [51.51, -0.09]]}, {"id": "b", "coordinates": [[51.51, -0.09], [51.52, -0.09]]}]
    result = matcher.viterbi([(51.501, -0.09), (51.511, -0.09)], segments)
    assert len(result["states"]) == 2


def test_haversine():
    assert haversine_m(0, 0, 0, 1) > 100000
