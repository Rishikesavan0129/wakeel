import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wakeel.orchestrator import sanitize_identifier


def test_normal_identifier_passes_through():
    assert sanitize_identifier("wakeel_alu") == "wakeel_alu"


def test_shell_metacharacters_rejected():
    assert sanitize_identifier("foo; rm -rf /") == "unknown_design"


def test_path_traversal_rejected():
    assert sanitize_identifier("../../etc/passwd") == "unknown_design"


def test_empty_string_rejected():
    assert sanitize_identifier("") == "unknown_design"


def test_custom_fallback_used():
    assert sanitize_identifier("$(whoami)", fallback="x_top") == "x_top"
