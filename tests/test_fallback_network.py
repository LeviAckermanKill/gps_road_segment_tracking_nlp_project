from backend.hmm.fallback_network import build_delhi_fallback_network


def test_delhi_fallback_network_loads_and_matches():
    network = build_delhi_fallback_network()
    assert len(network) >= 10
    candidates = network.get_nearest_segments(28.6322, 77.2185, radius_m=100.0)
    assert candidates
