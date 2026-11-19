"""
Viterbi algorithm implementation for Hidden Markov Models (HMM).

Implements the dynamic programming Viterbi decoding algorithm in log-space
to prevent numerical underflow with long observation sequences.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence


class ViterbiResult(NamedTuple):
    """
    Container for the result of the Viterbi decoding.

    Attributes
    ----------
    path : list of Any
        The optimal sequence of hidden states.
    log_probability : float
        The cumulative log-probability of the optimal path.
    trellis : list of dict
        The dynamic programming trellis table for visualization and inspection.
        Each entry `trellis[t][state]` contains:
            - 'log_prob': best log-probability reaching this state at time t
            - 'prev_state': predecessor state on the best path
    """
    path: List[Any]
    log_probability: float
    trellis: List[Dict[Any, Dict[str, Any]]]


def viterbi(
    states_per_obs: Sequence[Sequence[Any]],
    emission_log_probs: Sequence[Dict[Any, float]],
    transition_log_prob_fn: Callable[[Any, Any, int, int], float],
    initial_log_probs: Optional[Dict[Any, float]] = None,
    break_penalty: float = -100.0,
) -> ViterbiResult:
    """
    Compute the most probable sequence of hidden states given a sequence of observations.

    Parameters
    ----------
    states_per_obs : sequence of sequences
        Candidate states available at each observation step t in [0, T-1].
    emission_log_probs : sequence of dicts
        For each step t, a dictionary mapping state -> log P(observation_t | state).
    transition_log_prob_fn : callable
        Function (prev_state, curr_state, prev_idx, curr_idx) -> log P(curr_state | prev_state).
    initial_log_probs : dict, optional
        Initial log probabilities for states at t=0. Defaults to uniform.
    break_penalty : float, optional
        Penalty applied when no valid transition exists between consecutive steps,
        allowing graceful path recovery rather than complete breakdown.

    Returns
    -------
    ViterbiResult
        Tuple containing the optimal path, total log probability, and full trellis.
    """
    T = len(states_per_obs)
    if T == 0:
        return ViterbiResult(path=[], log_probability=-math.inf, trellis=[])

    trellis: List[Dict[Any, Dict[str, Any]]] = []

    # ---------------------------------------------------------
    # 1. Initialization (t = 0)
    # ---------------------------------------------------------
    t0_states = list(states_per_obs[0])
    if not t0_states:
        return ViterbiResult(path=[], log_probability=-math.inf, trellis=[])

    t0_trellis: Dict[Any, Dict[str, Any]] = {}
    uniform_init = -math.log(len(t0_states)) if len(t0_states) > 0 else 0.0

    for state in t0_states:
        init_lp = (
            initial_log_probs.get(state, uniform_init)
            if initial_log_probs is not None
            else uniform_init
        )
        emit_lp = emission_log_probs[0].get(state, -math.inf)
        total_lp = init_lp + emit_lp
        t0_trellis[state] = {
            "log_prob": total_lp,
            "prev_state": None,
        }

    trellis.append(t0_trellis)

    if T == 1:
        best_state = max(t0_trellis.keys(), key=lambda s: t0_trellis[s]["log_prob"])
        return ViterbiResult(
            path=[best_state],
            log_probability=t0_trellis[best_state]["log_prob"],
            trellis=trellis,
        )

    # ---------------------------------------------------------
    # 2. Forward recursion (t = 1 .. T-1)
    # ---------------------------------------------------------
    for t in range(1, T):
        curr_states = list(states_per_obs[t])
        prev_trellis = trellis[t - 1]
        curr_trellis: Dict[Any, Dict[str, Any]] = {}

        if not curr_states:
            # Fallback for empty candidate set at time t
            dummy_state = None
            curr_trellis[dummy_state] = {
                "log_prob": -math.inf,
                "prev_state": max(prev_trellis.keys(), key=lambda s: prev_trellis[s]["log_prob"]),
            }
            trellis.append(curr_trellis)
            continue

        for curr_s in curr_states:
            emit_lp = emission_log_probs[t].get(curr_s, -math.inf)
            best_prev_s = None
            best_trans_lp = -math.inf

            # Find predecessor that maximizes V_{t-1}(prev_s) + log A(prev_s -> curr_s)
            for prev_s, prev_info in prev_trellis.items():
                if prev_info["log_prob"] == -math.inf:
                    continue

                trans_lp = transition_log_prob_fn(prev_s, curr_s, t - 1, t)
                score = prev_info["log_prob"] + trans_lp

                if score > best_trans_lp:
                    best_trans_lp = score
                    best_prev_s = prev_s

            # Disconnected recovery: If all transitions were impossible (e.g. large gap)
            if best_prev_s is None or best_trans_lp == -math.inf:
                # Pick the highest probability previous state with a penalty
                best_prev_s = max(prev_trellis.keys(), key=lambda s: prev_trellis[s]["log_prob"])
                best_trans_lp = prev_trellis[best_prev_s]["log_prob"] + break_penalty

            curr_trellis[curr_s] = {
                "log_prob": best_trans_lp + emit_lp,
                "prev_state": best_prev_s,
            }

        trellis.append(curr_trellis)

    # ---------------------------------------------------------
    # 3. Termination & Backtracking
    # ---------------------------------------------------------
    last_trellis = trellis[-1]
    if not last_trellis:
        return ViterbiResult(path=[], log_probability=-math.inf, trellis=trellis)

    best_final_state = max(last_trellis.keys(), key=lambda s: last_trellis[s]["log_prob"])
    best_log_prob = last_trellis[best_final_state]["log_prob"]

    path: List[Any] = [best_final_state]
    curr_s = best_final_state

    for t in range(T - 1, 0, -1):
        prev_s = trellis[t][curr_s]["prev_state"]
        path.append(prev_s)
        curr_s = prev_s

    path.reverse()

    return ViterbiResult(
        path=path,
        log_probability=best_log_prob,
        trellis=trellis,
    )
