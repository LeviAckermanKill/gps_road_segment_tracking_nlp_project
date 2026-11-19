"""
Comprehensive tests for the Viterbi algorithm implementation.

Covers: basic decoding, greedy vs global optimality, edge cases
(empty input, single state, single observation, disconnected steps),
break penalty recovery, and trellis structure.
"""

import math

import pytest

from backend.hmm.viterbi import ViterbiResult, viterbi


# ---------------------------------------------------------------------------
# Basic decoding
# ---------------------------------------------------------------------------

class TestViterbiBasicDecoding:
    """Core Viterbi behaviour tests."""

    def test_single_observation_picks_best_emission(self):
        result = viterbi(
            [["A", "B"]],
            [{"A": -1.0, "B": -0.5}],
            lambda *_: 0.0,
        )
        assert result.path == ["B"]
        assert math.isfinite(result.log_probability)

    def test_two_observations_respects_transitions(self):
        result = viterbi(
            [["A", "B"], ["C", "D"]],
            [{"A": -0.1, "B": -0.1}, {"C": -0.1, "D": -0.1}],
            lambda a, b, _i, _j: 0.0 if (a, b) in {("A", "C"), ("B", "D")} else -10.0,
        )
        # Both emissions are equal; transitions decide: A→C and B→D are free
        assert result.path in [["A", "C"], ["B", "D"]]

    def test_global_sequence_not_greedy_choice(self):
        """Viterbi must find the globally optimal path, not locally greedy."""
        states = [["A", "B"], ["C", "D"], ["E", "F"]]
        emissions = [
            {"A": -0.1, "B": -0.2},
            {"C": -0.1, "D": -0.2},
            {"E": -0.1, "F": -0.2},
        ]
        transitions = {
            ("A", "C"): -8.0, ("A", "D"): 0.0,
            ("B", "C"): 0.0, ("B", "D"): -8.0,
            ("C", "E"): -8.0, ("C", "F"): 0.0,
            ("D", "E"): 0.0, ("D", "F"): -8.0,
        }
        result = viterbi(states, emissions, lambda a, b, _i, _j: transitions[(a, b)])
        assert result.path == ["A", "D", "E"]
        assert math.isfinite(result.log_probability)
        assert len(result.trellis) == 3

    def test_uniform_emissions_uses_transitions_to_decide(self):
        result = viterbi(
            [["X", "Y"], ["X", "Y"]],
            [{"X": 0.0, "Y": 0.0}, {"X": 0.0, "Y": 0.0}],
            lambda a, b, _i, _j: 0.0 if a == b else -20.0,
        )
        # With uniform emissions, staying on the same state is cheaper
        assert result.path[0] == result.path[1]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestViterbiEdgeCases:
    """Edge-case and boundary tests."""

    def test_empty_input_returns_empty_result(self):
        result = viterbi([], [], lambda *_: 0.0)
        assert result.path == []
        assert result.log_probability == -math.inf
        assert result.trellis == []

    def test_single_candidate_per_step(self):
        """Only one state per observation — the path is forced."""
        result = viterbi(
            [["only1"], ["only2"], ["only3"]],
            [{"only1": -0.5}, {"only2": -0.3}, {"only3": -0.1}],
            lambda *_: -1.0,
        )
        assert result.path == ["only1", "only2", "only3"]
        assert math.isfinite(result.log_probability)

    def test_empty_candidate_step_uses_none_placeholder(self):
        result = viterbi(
            [["A"], [], ["B"]],
            [{"A": 0.0}, {}, {"B": 0.0}],
            lambda *_: -1.0,
        )
        assert result.path == ["A", None, "B"]

    def test_very_long_sequence_does_not_overflow(self):
        """100-step sequence should still produce finite log-prob."""
        T = 100
        states_per_obs = [["S"]] * T
        emissions = [{"S": -0.01}] * T
        result = viterbi(states_per_obs, emissions, lambda *_: -0.01)
        assert len(result.path) == T
        assert math.isfinite(result.log_probability)


# ---------------------------------------------------------------------------
# Trellis structure
# ---------------------------------------------------------------------------

class TestViterbiTrellis:
    """Verify the trellis table is well-formed."""

    def test_trellis_length_matches_observations(self):
        result = viterbi(
            [["A"], ["B"], ["C"]],
            [{"A": 0.0}, {"B": 0.0}, {"C": 0.0}],
            lambda *_: -0.5,
        )
        assert len(result.trellis) == 3

    def test_trellis_entries_contain_required_keys(self):
        result = viterbi(
            [["A", "B"], ["C"]],
            [{"A": -0.1, "B": -0.2}, {"C": -0.1}],
            lambda *_: -0.5,
        )
        for t, step in enumerate(result.trellis):
            for state, info in step.items():
                assert "log_prob" in info
                assert "prev_state" in info
                if t == 0:
                    assert info["prev_state"] is None

    def test_trellis_first_step_has_no_predecessor(self):
        result = viterbi(
            [["A"]],
            [{"A": -1.0}],
            lambda *_: 0.0,
        )
        assert result.trellis[0]["A"]["prev_state"] is None


# ---------------------------------------------------------------------------
# Break penalty
# ---------------------------------------------------------------------------

class TestViterbiBreakPenalty:
    """Verify disconnected-step recovery via break_penalty."""

    def test_custom_break_penalty_is_applied(self):
        # All transitions return -inf, forcing break recovery
        result_default = viterbi(
            [["A"], ["B"]],
            [{"A": 0.0}, {"B": 0.0}],
            lambda *_: -math.inf,
            break_penalty=-50.0,
        )
        result_mild = viterbi(
            [["A"], ["B"]],
            [{"A": 0.0}, {"B": 0.0}],
            lambda *_: -math.inf,
            break_penalty=-5.0,
        )
        # Milder penalty ⇒ higher log-probability
        assert result_mild.log_probability > result_default.log_probability
