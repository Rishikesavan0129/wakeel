import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wakeel.orchestrator import build_sweep_clocks_ps, SweepConfigError, MAX_SWEEP_POINTS


def test_explicit_list_converts_ghz_to_ps():
    clocks = build_sweep_clocks_ps({"frequencies_ghz": [1.0, 0.5, 0.25]})
    assert clocks == [1000, 2000, 4000]


def test_range_is_inclusive_of_end():
    clocks = build_sweep_clocks_ps({"start_ghz": 0.2, "end_ghz": 0.6, "step_ghz": 0.2})
    # ps is an int, so GHz->ps->GHz is lossy by design (sub-1ps rounding) --
    # compare with tolerance, not exact equality.
    freqs_ghz = sorted(round(1000.0 / c, 2) for c in clocks)
    assert freqs_ghz == [0.2, 0.4, 0.6]


def test_range_default_step():
    clocks = build_sweep_clocks_ps({"start_ghz": 1.0, "end_ghz": 1.0})
    assert clocks == [1000]


def test_rejects_empty_list():
    with pytest.raises(SweepConfigError):
        build_sweep_clocks_ps({"frequencies_ghz": []})


def test_rejects_zero_or_negative_frequency():
    with pytest.raises(SweepConfigError):
        build_sweep_clocks_ps({"frequencies_ghz": [0.0]})
    with pytest.raises(SweepConfigError):
        build_sweep_clocks_ps({"frequencies_ghz": [-1.0]})


def test_rejects_bad_step():
    with pytest.raises(SweepConfigError):
        build_sweep_clocks_ps({"start_ghz": 0.1, "end_ghz": 1.0, "step_ghz": 0})


def test_rejects_end_before_start():
    with pytest.raises(SweepConfigError):
        build_sweep_clocks_ps({"start_ghz": 1.0, "end_ghz": 0.5, "step_ghz": 0.1})


def test_caps_at_max_sweep_points():
    with pytest.raises(SweepConfigError):
        build_sweep_clocks_ps({"start_ghz": 0.1, "end_ghz": 100.0, "step_ghz": 0.1})


def test_missing_shape_raises():
    with pytest.raises(SweepConfigError):
        build_sweep_clocks_ps({"foo": "bar"})


def test_caller_can_raise_the_point_cap_up_to_ceiling():
    from wakeel.orchestrator import ABSOLUTE_MAX_SWEEP_POINTS
    clocks = build_sweep_clocks_ps(
        {"start_ghz": 0.1, "end_ghz": 10.0, "step_ghz": 0.1}, max_points=150)
    assert len(clocks) <= 150


def test_caller_supplied_cap_is_still_bounded_by_absolute_ceiling():
    from wakeel.orchestrator import ABSOLUTE_MAX_SWEEP_POINTS
    with pytest.raises(SweepConfigError):
        # asks for way more than the absolute ceiling allows -- must still reject
        build_sweep_clocks_ps(
            {"start_ghz": 0.1, "end_ghz": 100.0, "step_ghz": 0.1},
            max_points=ABSOLUTE_MAX_SWEEP_POINTS * 10)
