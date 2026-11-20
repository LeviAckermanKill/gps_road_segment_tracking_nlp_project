"""Create a small self-contained road network around Connaught Place.

This fallback is not a substitute for downloaded OSM data, but it guarantees
that the Delhi samples and HMM/Viterbi demonstration work offline.
"""

from backend.hmm.road_network import RoadNetwork, RoadSegment


def build_delhi_fallback_network() -> RoadNetwork:
    network = RoadNetwork()

    roads = [
        ("radial_1", "n0", "n1", [(77.21320, 28.63220), (77.21650, 28.63220)], "Radial Road 1", "primary", False),
        ("outer_circle_1", "n1", "n2", [(77.21650, 28.63220), (77.21840, 28.63430)], "Connaught Circus", "primary", False),
        ("outer_circle_2", "n2", "n3", [(77.21840, 28.63430), (77.22080, 28.63430)], "Connaught Circus", "primary", False),
        ("outer_circle_3", "n3", "n4", [(77.22080, 28.63430), (77.22250, 28.63220)], "Connaught Circus", "primary", False),
        ("outer_circle_4", "n4", "n5", [(77.22250, 28.63220), (77.22080, 28.63010)], "Connaught Circus", "primary", False),
        ("outer_circle_5", "n5", "n6", [(77.22080, 28.63010), (77.21840, 28.63010)], "Connaught Circus", "primary", False),
        ("outer_circle_6", "n6", "n1", [(77.21840, 28.63010), (77.21650, 28.63220)], "Connaught Circus", "primary", False),
        ("barakhamba", "n7", "n8", [(77.21850, 28.63200), (77.22150, 28.63180), (77.22600, 28.63050)], "Barakhamba Road", "secondary", False),
        ("tolstoy", "n8", "n9", [(77.22600, 28.63050), (77.22150, 28.62920), (77.21620, 28.62800)], "Tolstoy Marg", "secondary", False),
        ("janpath", "n9", "n10", [(77.21620, 28.62800), (77.21680, 28.63000), (77.21760, 28.63340)], "Janpath", "secondary", False),
        ("janpath_to_circle", "n10", "n1", [(77.21760, 28.63340), (77.21650, 28.63220)], "Janpath", "secondary", False),
    ]

    for seg_id, u, v, coords, name, road_type, oneway in roads:
        segment = RoadSegment(seg_id, u, v, coords, 0.0, name, road_type, oneway)
        network.add_segment(segment)

    network.build_spatial_index(sample_spacing_m=20.0)
    return network
