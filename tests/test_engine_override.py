import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wakeel.orchestrator import offline_fallback_parser, _infer_resource_mode


def test_resource_mode_defaults_to_synth_power_only_for_orfs():
    params = offline_fallback_parser("run wakeel_alu at 500 MHz on 7nm")
    assert params["engine"] == "orfs"
    assert params["resource_mode"] == "synth_power_only"


def test_resource_mode_full_when_explicitly_requested():
    params = offline_fallback_parser("run wakeel_alu at 500 MHz on 7nm, full flow")
    assert params["resource_mode"] == "full"


def test_openlane_always_full():
    params = offline_fallback_parser("run wakeel_alu at 500 MHz on 130nm")
    assert params["engine"] == "openlane"
    assert params["resource_mode"] == "full"


def test_infer_resource_mode_matches_parser_for_orfs():
    """This is the actual real-world bug: when engine_override changes
    which engine applies, resource_mode must be re-derived with THIS
    function rather than trusted from the prompt-parsed dict, which was
    computed against a possibly-different engine."""
    prompt = "run wakeel_alu at 500 MHz"
    assert _infer_resource_mode(prompt, "orfs") == "synth_power_only"
    assert _infer_resource_mode(prompt, "openlane") == "full"


def test_infer_resource_mode_respects_full_flow_keywords_regardless_of_engine():
    prompt = "run wakeel_alu, full flow"
    assert _infer_resource_mode(prompt, "orfs") == "full"
