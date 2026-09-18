import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wakeel.orchestrator import build_power_analysis_tcl, build_power_estimate_tcl


def _base_args():
    return dict(
        orfs_path="/opt/ORFS_7nm",
        top_module="wakeel_alu_top",
        synth_netlist="/opt/ORFS_7nm/flow/results/asap7/wakeel_alu_top/base/1_synth.v",
        sdc_path="/opt/ORFS_7nm/flow/designs/asap7/wakeel_alu/constraint.sdc",
    )


def test_report_units_called_first_for_self_documenting_output():
    tcl = build_power_analysis_tcl(**_base_args())
    assert tcl.strip().index("report_units") < tcl.index("read_liberty")


def test_saif_takes_priority_and_uses_correct_syntax():
    tcl = build_power_analysis_tcl(**_base_args(), saif_path="/tmp/x.saif", vcd_path="/tmp/x.vcd")
    assert 'read_saif -scope "wakeel_alu_top" "/tmp/x.saif"' in tcl
    assert "read_vcd" not in tcl


def test_vcd_used_when_no_saif():
    tcl = build_power_analysis_tcl(**_base_args(), vcd_path="/tmp/x.vcd")
    assert 'read_vcd -scope "wakeel_alu_top" "/tmp/x.vcd"' in tcl
    assert "read_saif" not in tcl


def test_missing_activity_emits_explicit_warning_not_silent_default():
    tcl = build_power_analysis_tcl(**_base_args())
    assert "WAKEEL_POWER_WARNING" in tcl
    assert "default toggle rate" in tcl.lower() or "default activity assumption" in tcl.lower()


def test_report_power_markers_present_for_downstream_parsing():
    tcl = build_power_analysis_tcl(**_base_args())
    assert "WAKEEL_POWER_REPORT_START" in tcl
    assert "WAKEEL_POWER_REPORT_END" in tcl
    assert "report_power" in tcl


def test_backward_compatible_alias_still_works():
    old_style = build_power_estimate_tcl(
        "/opt/ORFS_7nm", "top", "/tmp/synth.v", "/tmp/c.sdc", "/tmp/x.saif")
    assert 'read_saif -scope "top" "/tmp/x.saif"' in old_style
