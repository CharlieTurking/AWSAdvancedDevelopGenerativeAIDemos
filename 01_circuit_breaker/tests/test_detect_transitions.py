"""Property test for circuit transition timeline point detection.

# Feature: streamlit-circuit-breaker-ui, Property 11: Timeline adds a point exactly on each circuit-state change
# Validates: Requirements 7.2, 7.3

Property: For any sequence of observed OPEN/CLOSED circuit states, folding
``detect_transitions`` across the sequence appends exactly one timeline point per adjacent
state change, each labeled with the new state and carrying its observation timestamp, and
appends no point when the state is unchanged. UNKNOWN observations yield no point and do not
become the comparison baseline.

The UI maintains ``prev_state`` (the last known OPEN/CLOSED state, initially ``None``),
re-derives the circuit state on each refresh, and calls ``detect_transitions(prev_state,
new_state, ts)`` to decide whether to append a timeline point. On an OPEN/CLOSED observation
it updates ``prev_state`` to the new state; on an UNKNOWN observation it leaves ``prev_state``
untouched. This test replays that fold and checks the collected points against the adjacent
changes in the OPEN/CLOSED-filtered observation sequence.
"""

from hypothesis import given, settings, strategies as st

from app import detect_transitions


# A definite circuit-state observation paired with its observation timestamp.
_definite_obs = st.tuples(
    st.sampled_from(["OPEN", "CLOSED"]),
    st.integers(min_value=0, max_value=2_000_000_000),
)

# An observation that may also be UNKNOWN (e.g. a circuit-read error), still timestamped.
_maybe_unknown_obs = st.tuples(
    st.sampled_from(["OPEN", "CLOSED", "UNKNOWN"]),
    st.integers(min_value=0, max_value=2_000_000_000),
)


def _replay_ui_fold(observations):
    """Replay the UI's timeline fold over a list of ``(state, ts)`` observations.

    Mirrors the Dashboard: keep a ``prev_state`` baseline (``None`` initially) that is only
    advanced on OPEN/CLOSED observations, and accumulate whatever ``detect_transitions``
    returns for each observation.
    """
    prev_state = None
    points = []
    for new_state, ts in observations:
        points.extend(detect_transitions(prev_state, new_state, ts))
        if new_state in ("OPEN", "CLOSED"):
            prev_state = new_state
    return points


def _expected_points(observations):
    """Compute the expected timeline points directly from the spec.

    A point is expected exactly at each adjacent change within the OPEN/CLOSED-filtered
    observation subsequence (UNKNOWN observations are dropped and never participate in the
    comparison). Each point carries the new state and that observation's timestamp.
    """
    expected = []
    prev_state = None
    for new_state, ts in observations:
        if new_state not in ("OPEN", "CLOSED"):
            continue
        if new_state != prev_state:
            expected.append((ts, new_state))
        prev_state = new_state
    return expected


@settings(max_examples=200)
@given(observations=st.lists(_definite_obs, max_size=40))
def test_one_point_per_adjacent_change_open_closed(observations):
    """Folding over OPEN/CLOSED observations yields one point per adjacent change."""
    points = _replay_ui_fold(observations)
    expected = _expected_points(observations)

    # Exactly one point per adjacent state change (and none when unchanged).
    assert points == expected

    # Count check: the number of points equals the number of adjacent changes in the
    # OPEN/CLOSED-filtered sequence (the first definite observation counts as a change from
    # the None baseline).
    states = [state for state, _ in observations]
    adjacent_changes = sum(
        1 for prev, cur in zip([None, *states], states) if prev != cur
    )
    assert len(points) == adjacent_changes

    # Each point is labeled with a definite new state and carries a timestamp from the input.
    input_timestamps = {ts for _, ts in observations}
    for ts, state in points:
        assert state in ("OPEN", "CLOSED")
        assert ts in input_timestamps


@settings(max_examples=200)
@given(observations=st.lists(_maybe_unknown_obs, max_size=40))
def test_unknown_yields_no_point_and_is_not_baseline(observations):
    """UNKNOWN observations add no point and never become the comparison baseline."""
    points = _replay_ui_fold(observations)
    expected = _expected_points(observations)

    assert points == expected

    # The fold with UNKNOWN interleaved must equal the fold over just the definite
    # observations: UNKNOWN neither adds points nor shifts the baseline.
    definite_only = [(s, ts) for s, ts in observations if s in ("OPEN", "CLOSED")]
    assert points == _replay_ui_fold(definite_only)

    # No emitted point is ever UNKNOWN.
    assert all(state in ("OPEN", "CLOSED") for _, state in points)
