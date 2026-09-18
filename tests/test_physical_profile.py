import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wakeel import physical_profile


def test_comfortable_tier_forces_area_strategy_openlane():
    params, notes = physical_profile.apply({}, "openlane", 0.1)
    assert params["SYNTH_STRATEGY"] == "AREA 0"
    assert params["PL_RESIZER_TIMING_OPTIMIZATIONS"] is False


def test_extreme_tier_forces_delay_strategy_openlane():
    params, notes = physical_profile.apply({}, "openlane", 5.0)
    assert params["SYNTH_STRATEGY"] == "DELAY 1"
    assert any("WARNING" in n for n in notes)


def test_locked_keys_are_not_overwritten():
    """The core v3 bugfix: a KB rule already set SYNTH_STRATEGY this
    attempt -- physical_profile must not silently force it back to the
    tier default on the very next call (i.e. the next retry attempt at
    the same frequency)."""
    params = {"SYNTH_STRATEGY": "AREA 1"}  # what a KB rule just set
    locked = {"SYNTH_STRATEGY"}
    params, notes = physical_profile.apply(params, "openlane", 5.0, locked_keys=locked)
    assert params["SYNTH_STRATEGY"] == "AREA 1", "a locked key must survive physical_profile.apply() untouched"
    assert any("Deferring" in n for n in notes)
    # the OTHER owned keys (not locked) should still be forced as normal
    assert params["PL_RESIZER_TIMING_OPTIMIZATIONS"] is True


def test_orfs_has_real_knobs_not_just_a_warning():
    """v3: ORFS used to be warning-only at aggressive/extreme tiers with
    no actual adjustment. It must now set real schema keys."""
    params, notes = physical_profile.apply({}, "orfs", 2.0)  # aggressive tier
    assert params["SYNTH_MAX_FANOUT"] == 12
    assert params["SYNTH_FLAT_TOP"] is False

    params, notes = physical_profile.apply({}, "orfs", 3.0)  # extreme tier
    assert params["SYNTH_MAX_FANOUT"] == 8
    assert params["SYNTH_FLAT_TOP"] is True


def test_orfs_comfortable_tier_uses_defaults():
    params, notes = physical_profile.apply({}, "orfs", 0.5)
    assert params["SYNTH_MAX_FANOUT"] == 20
    assert params["SYNTH_FLAT_TOP"] is False


def test_owned_keys_constant_matches_what_apply_actually_sets():
    params, _ = physical_profile.apply({}, "openlane", 5.0)
    assert physical_profile.OWNED_KEYS["openlane"] <= set(params.keys())
    params, _ = physical_profile.apply({}, "orfs", 3.0)
    assert physical_profile.OWNED_KEYS["orfs"] <= set(params.keys())
